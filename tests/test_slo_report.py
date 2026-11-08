import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gate import slo_report as r
from tests.test_dashboard import RECORDED

# What the fake Prometheus answers, by metric name: {slo: value}.
DATA = {}


class FakePrometheus(BaseHTTPRequestHandler):
    def do_GET(self):
        promql = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)["query"][
            0
        ]
        name = promql.split("{")[0]
        rows = [
            {"metric": {"sloth_slo": slo, **extra}, "value": [0, str(v)]}
            for slo, v, extra in DATA.get(name, [])
        ]
        payload = json.dumps({"status": "success", "data": {"result": rows}}).encode()
        self.send_response(200)
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


def outage():
    """Availability is mid-outage, latency is healthy."""
    DATA.clear()
    DATA["slo:objective:ratio"] = [("availability", 0.995, {}), ("latency", 0.95, {})]
    DATA["slo:error_budget:ratio"] = [
        ("availability", 0.005, {}),
        ("latency", 0.05, {}),
    ]
    DATA["slo:period_error_budget_remaining:ratio"] = [
        ("availability", 0.2, {}),
        ("latency", 0.97, {}),
    ]
    for w in r.WINDOWS:
        DATA[f"slo:sli_error:ratio_rate{w}"] = [
            ("availability", 0.5 if w == "5m" else 0.05, {}),
            ("latency", 0.0, {}),
        ]
    DATA["ALERTS"] = [("availability", 1, {"sloth_severity": "page"})]


def test_the_report_shows_state_burn_and_time_left(prometheus, capsys):
    outage()
    assert r.main(["--prometheus", prometheus]) == 0
    out = capsys.readouterr().out
    avail = next(line for line in out.splitlines() if line.startswith("| availability"))
    cells = [c.strip() for c in avail.strip("|").split("|")]
    # SLO, objective, state, budget, 5 burn windows, gone in, alerts
    assert cells[:4] == ["availability", "99.5%", "low", "20.0%"]
    assert cells[4:9] == ["100.0x", "10.0x", "10.0x", "10.0x", "10.0x"]
    # 20% of a 30 day budget at 100x lasts 0.2 * 30d / 100 = 86.4 minutes.
    assert cells[9] == "1h 26m"
    assert cells[10] == "page"
    assert "| latency | 95.0% | ok | 97.0% | 0.0x" in out
    assert "not at this pace | none |" in out


def test_no_slos_is_an_error(prometheus, capsys):
    DATA.clear()
    assert r.main(["--prometheus", prometheus]) == 2
    assert "No SLOs found" in capsys.readouterr().err


def test_an_unreachable_prometheus_is_an_error(capsys):
    assert r.main(["--prometheus", "http://127.0.0.1:1"]) == 2
    assert "Could not read" in capsys.readouterr().err


@pytest.mark.parametrize(
    "left, state", [(0.6, "ok"), (0.1, "low"), (0.0, "spent"), (-1.0, "spent")]
)
def test_state_follows_the_budget_left(left, state):
    assert r.SloStatus("a", budget_left=left).state == state


def test_missing_budget_is_no_data():
    assert r.SloStatus("a").state == "no data"


@pytest.mark.parametrize(
    "seconds, text",
    [(None, "not at this pace"), (600, "10m"), (5400, "1h 30m"), (200000, "2d 7h")],
)
def test_durations_read_like_a_person_wrote_them(seconds, text):
    assert r.duration(seconds) == text


def test_every_query_uses_a_rule_sloth_records():
    names = {"slo:objective:ratio", "slo:period_error_budget_remaining:ratio"}
    names |= {"slo:error_budget:ratio"}
    names |= {f"slo:sli_error:ratio_rate{w}" for w in r.WINDOWS}
    assert names <= RECORDED
    source = open(r.__file__).read()
    for name in re.findall(r'f"(slo:[a-z_:]+)', source):
        assert name in RECORDED or name == "slo:sli_error:ratio_rate"
