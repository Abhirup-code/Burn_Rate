import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client():
    return TestClient(create_app(chaos_token=TOKEN, seed=42))


def metric(client, name, **labels):
    """Read one sample from /metrics, or 0 when it has not been recorded yet."""
    text = client.get("/metrics").text
    want = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    for line in text.splitlines():
        m = re.match(rf"^{name}\{{(.*)\}} (\S+)$", line)
        if m and ",".join(sorted(m.group(1).split(","))) == want:
            return float(m.group(2))
    return 0.0


def test_a_healthy_service_pays_and_counts_success(client):
    for _ in range(5):
        assert client.get("/checkout").json() == {"status": "paid"}
    assert (
        metric(
            client, "http_requests_total", code="200", method="GET", route="/checkout"
        )
        == 5
    )


def test_health_and_metrics_are_not_counted_as_user_traffic(client):
    client.get("/healthz")
    client.get("/metrics")
    text = client.get("/metrics").text
    assert 'route="/healthz"' not in text
    assert 'route="/metrics"' not in text


def test_the_latency_histogram_has_a_bucket_at_the_300ms_target(client):
    client.get("/checkout")
    text = client.get("/metrics").text
    assert (
        'http_request_duration_seconds_bucket{le="0.3",method="GET",route="/checkout"}'
        in text
    )


def test_unknown_paths_share_one_label_so_metrics_cannot_explode(client):
    for path in ("/a", "/b", "/c"):
        assert client.get(path).status_code == 404
    assert (
        metric(
            client, "http_requests_total", code="404", method="GET", route="unmatched"
        )
        == 3
    )


def test_chaos_needs_the_token(client):
    assert client.put("/chaos", json={"error_rate": 1}).status_code == 401
    assert (
        client.put(
            "/chaos", json={"error_rate": 1}, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    assert client.get("/chaos").json() == {
        "error_rate": 0.0,
        "latency_ms": 0,
        "duration_s": 0,
        "expires_in_s": None,
    }


def test_chaos_is_locked_when_no_token_is_configured():
    locked = TestClient(create_app(chaos_token="", seed=1))
    assert (
        locked.put(
            "/chaos", json={"error_rate": 1}, headers={"Authorization": "Bearer "}
        ).status_code
        == 401
    )


def test_injected_errors_show_up_as_500s(client):
    assert client.put("/chaos", json={"error_rate": 1}, headers=AUTH).status_code == 200
    for _ in range(4):
        assert client.get("/checkout").status_code == 500
    assert (
        metric(
            client, "http_requests_total", code="500", method="GET", route="/checkout"
        )
        == 4
    )


def test_a_partial_error_rate_fails_roughly_that_share(client):
    client.put("/chaos", json={"error_rate": 0.2}, headers=AUTH)
    codes = [client.get("/checkout").status_code for _ in range(500)]
    assert 0.12 < codes.count(500) / 500 < 0.28


def test_injected_latency_slows_checkout(client):
    client.put("/chaos", json={"latency_ms": 350}, headers=AUTH)
    client.get("/checkout")
    # 350 ms is above the 300 ms target, so the request lands outside the 0.3 bucket.
    fast = metric(
        client,
        "http_request_duration_seconds_bucket",
        le="0.3",
        method="GET",
        route="/checkout",
    )
    total = metric(
        client, "http_request_duration_seconds_count", method="GET", route="/checkout"
    )
    assert (fast, total) == (0.0, 1.0)


@pytest.mark.parametrize(
    "bad",
    [
        {"error_rate": 1.5},
        {"error_rate": -0.1},
        {"latency_ms": 99999},
        {"duration_s": -1},
        {"duration_s": 7200},
    ],
)
def test_out_of_range_chaos_is_rejected(client, bad):
    assert client.put("/chaos", json=bad, headers=AUTH).status_code == 422


def test_turning_chaos_off_restores_health(client):
    client.put("/chaos", json={"error_rate": 1}, headers=AUTH)
    client.put("/chaos", json={"error_rate": 0, "latency_ms": 0}, headers=AUTH)
    assert client.get("/checkout").status_code == 200


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_chaos_with_a_duration_switches_itself_off():
    clock = FakeClock()
    timed = TestClient(create_app(chaos_token=TOKEN, seed=1, clock=clock))
    body = timed.put(
        "/chaos", json={"error_rate": 1, "duration_s": 60}, headers=AUTH
    ).json()
    assert body["expires_in_s"] == 60
    assert timed.get("/checkout").status_code == 500

    clock.now += 59.5
    assert timed.get("/chaos").json()["expires_in_s"] == 1
    assert timed.get("/checkout").status_code == 500

    clock.now += 1
    assert timed.get("/checkout").status_code == 200
    assert timed.get("/chaos").json() == {
        "error_rate": 0.0,
        "latency_ms": 0,
        "duration_s": 0,
        "expires_in_s": None,
    }


def test_chaos_without_a_duration_stays_on():
    clock = FakeClock()
    timed = TestClient(create_app(chaos_token=TOKEN, seed=1, clock=clock))
    timed.put("/chaos", json={"error_rate": 1}, headers=AUTH)
    clock.now += 86400
    assert timed.get("/checkout").status_code == 500
    assert timed.get("/chaos").json()["expires_in_s"] is None


def test_checkout_failure_series_exists_before_any_failure():
    """Without it, the availability SLI has no data on a fresh service."""
    fresh = TestClient(create_app(chaos_token=TOKEN, seed=1))
    body = fresh.get("/metrics").text
    assert 'http_requests_total{code="500",method="GET",route="/checkout"} 0.0' in body
    assert 'http_requests_total{code="200",method="GET",route="/checkout"} 0.0' in body
