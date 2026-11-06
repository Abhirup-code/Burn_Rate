import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gate import budget_gate as g
from gate.budget_gate import ALLOW, BLOCK, UNKNOWN, Budget, decide


def test_budget_left_on_every_slo_allows_the_deploy():
    d = decide([Budget("availability", 0.62), Budget("latency", 0.9)])
    assert d.code == ALLOW


def test_one_spent_budget_blocks_the_deploy_and_names_it():
    d = decide([Budget("availability", -0.4), Budget("latency", 0.9)])
    assert d.code == BLOCK
    assert "availability" in d.reason and "latency" not in d.reason


def test_exactly_zero_left_counts_as_spent():
    assert decide([Budget("availability", 0.0)]).code == BLOCK


def test_a_safety_margin_blocks_earlier():
    assert decide([Budget("availability", 0.08)], min_remaining=0.1).code == BLOCK
    assert decide([Budget("availability", 0.12)], min_remaining=0.1).code == ALLOW


def test_no_data_fails_closed():
    assert decide([]).code == UNKNOWN
    assert decide([Budget("availability", float("nan"))]).code == UNKNOWN


def test_report_lists_each_slo_as_a_percentage():
    text = g.report(decide([Budget("latency", 0.5), Budget("availability", -0.25)]))
    assert "Deploy blocked" in text
    assert "| availability | -25.0% |" in text
    assert text.index("availability") < text.index("| latency")


class FakePrometheus(BaseHTTPRequestHandler):
    body = {}

    def do_GET(self):
        payload = json.dumps(self.body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def prometheus():
    server = HTTPServer(("127.0.0.1", 0), FakePrometheus)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def result(slo, value):
    return {
        "metric": {"sloth_slo": slo, "sloth_service": "checkout"},
        "value": [1700000000, str(value)],
    }


def test_main_reads_prometheus_and_blocks(prometheus, tmp_path, monkeypatch, capsys):
    FakePrometheus.body = {
        "status": "success",
        "data": {"result": [result("availability", -1.2), result("latency", 0.7)]},
    }
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert g.main(["--prometheus", prometheus]) == BLOCK
    assert "Deploy blocked" in capsys.readouterr().out
    assert "| availability | -120.0% |" in summary.read_text()


def test_main_allows_when_budgets_are_healthy(prometheus):
    FakePrometheus.body = {
        "status": "success",
        "data": {"result": [result("availability", 0.99), result("latency", 0.95)]},
    }
    assert g.main(["--prometheus", prometheus]) == ALLOW


def test_an_unreachable_prometheus_blocks(capsys):
    assert g.main(["--prometheus", "http://127.0.0.1:1"]) == UNKNOWN
    assert "Could not read the error budget" in capsys.readouterr().out


def test_a_non_http_url_is_refused(capsys):
    assert g.main(["--prometheus", "file:///etc/passwd"]) == UNKNOWN


def test_a_hotfix_with_a_reason_gets_through_and_is_recorded():
    blocked = decide([Budget("availability", -0.5)])
    d = g.apply_hotfix(blocked, "Roll back the bad 1.4 release", "abhirup")
    assert d.code == ALLOW
    assert d.reason.startswith(
        "HOTFIX OVERRIDE by abhirup: Roll back the bad 1.4 release"
    )
    assert "Error budget exhausted for: availability" in d.reason
    assert "Hotfix allowed while the budget is spent" in g.report(d)


def test_a_hotfix_without_a_real_reason_stays_blocked():
    blocked = decide([Budget("availability", -0.5)])
    d = g.apply_hotfix(blocked, "  fix  ", "abhirup")
    assert d.code == BLOCK
    assert "needs a reason" in d.reason


def test_the_hotfix_flag_changes_nothing_when_budget_is_left():
    ok = decide([Budget("availability", 0.5)])
    assert g.apply_hotfix(ok, "Roll back the bad 1.4 release", "abhirup") == ok


def test_main_hotfix_from_the_environment(prometheus, monkeypatch, capsys):
    FakePrometheus.body = {
        "status": "success",
        "data": {"result": [result("availability", -0.3)]},
    }
    monkeypatch.setenv("HOTFIX_REASON", "Revert the config that broke checkout")
    monkeypatch.setenv("GITHUB_ACTOR", "abhirup-code")
    assert g.main(["--prometheus", prometheus]) == ALLOW
    assert "HOTFIX OVERRIDE by abhirup-code" in capsys.readouterr().out
