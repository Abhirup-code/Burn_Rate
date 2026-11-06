"""Checks the Grafana dashboard against the SLO rules, so a renamed SLO or rule cannot
leave panels silently empty."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = json.loads((ROOT / "deploy/k8s/dashboards/checkout-slo.json").read_text())
RULES = list(yaml.safe_load_all((ROOT / "deploy/k8s/slo-rules.yaml").read_text()))
SPEC = yaml.safe_load((ROOT / "slos/checkout.yaml").read_text())

RECORDED = {
    r["record"]
    for doc in RULES
    if doc
    for g in doc["spec"]["groups"]
    for r in g["rules"]
    if "record" in r
}
ALERTS = {
    r["alert"]
    for doc in RULES
    if doc
    for g in doc["spec"]["groups"]
    for r in g["rules"]
    if "alert" in r
}
SLO_NAMES = {s["name"] for s in SPEC["spec"]["slos"]}
APP_METRICS = {"http_requests_total", "http_request_duration_seconds_bucket", "ALERTS"}


def queries():
    for panel in DASHBOARD["panels"]:
        for t in panel.get("targets", []):
            yield panel["title"], t


def test_every_query_uses_a_recorded_rule_or_an_app_metric():
    for title, t in queries():
        names = set(
            re.findall(r"\b(slo:[a-z_:0-9]+|[a-zA-Z_][a-zA-Z0-9_]*)\{", t["expr"])
        )
        assert names, title
        unknown = names - RECORDED - APP_METRICS
        assert not unknown, (
            f"{title}: {unknown} is not produced by the SLO rules or the app"
        )


def test_every_slo_named_in_a_query_exists():
    for title, t in queries():
        for slo in re.findall(r'sloth_slo="([^"]+)"', t["expr"]):
            assert slo in SLO_NAMES, f"{title}: no SLO called {slo}"


def test_both_slos_have_budget_burn_and_time_left_panels():
    titles = {p["title"] for p in DASHBOARD["panels"]}
    for slo in SLO_NAMES:
        label = slo.capitalize()
        for suffix in ("budget left", "burn rate", "budget gone in"):
            assert f"{label} {suffix}" in titles


def test_queries_use_the_datasource_variable():
    for title, t in queries():
        assert t["datasource"] == {"type": "prometheus", "uid": "${datasource}"}, title


def test_panels_have_unique_ids_and_stay_inside_the_grid():
    ids = [p["id"] for p in DASHBOARD["panels"]]
    assert len(ids) == len(set(ids))
    taken = set()
    for p in DASHBOARD["panels"]:
        g = p["gridPos"]
        assert g["x"] + g["w"] <= 24, p["title"]
        cells = {
            (x, y)
            for x in range(g["x"], g["x"] + g["w"])
            for y in range(g["y"], g["y"] + g["h"])
        }
        assert not cells & taken, f"{p['title']} overlaps another panel"
        taken |= cells


def test_the_alert_table_matches_the_real_alert_names():
    assert ALERTS == {"CheckoutAvailabilityBudgetBurn", "CheckoutLatencyBudgetBurn"}
    table = next(p for p in DASHBOARD["panels"] if p["type"] == "table")
    assert 'sloth_service="checkout"' in table["targets"][0]["expr"]
