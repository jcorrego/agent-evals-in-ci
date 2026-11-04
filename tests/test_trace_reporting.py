"""No provider calls: uncertainty is over whole synthetic cases, not model runs."""

import json
from pathlib import Path

import pytest

from agent_evals.trace_reporting import bootstrap_intervals, render_report
from agent_evals.traces import evaluate_traces, load_traces, main

ROOT = Path(__file__).parents[1]


def row(case_id, expected, observed):
    return {
        "case_id": case_id,
        "expected_findings": expected,
        "observed_findings": observed,
        "false_negatives": sorted(set(expected) - set(observed)),
        "false_positives": sorted(set(observed) - set(expected)),
    }


def test_cluster_bootstrap_is_seeded_and_does_not_change_global_random_state():
    import random

    rows = [
        row("both", ["FORBIDDEN_TOOL", "TOOL_ORDER"], ["FORBIDDEN_TOOL"]),
        row("miss", ["APPROVAL_BYPASS"], []),
        row("extra", [], ["FORBIDDEN_TOOL"]),
    ]
    state = random.getstate()
    result = bootstrap_intervals(rows, samples=200, seed=17)
    assert result == bootstrap_intervals(rows, samples=200, seed=17)
    assert random.getstate() == state
    assert result["method"] == "case-cluster-percentile-v1"
    assert result["confidence_level"] == 0.95
    assert result["case_count"] == 3
    # Independently replay the draws and calculate unrounded ratios over whole cases.
    rng = random.Random(17)
    recalls = []
    for _ in range(200):
        draws = [rng.randrange(3) for _ in rows]
        tp = draws.count(0)
        fn = draws.count(0) + draws.count(1)
        if tp + fn:
            recalls.append(tp / (tp + fn))
    recalls.sort()
    low_index = (len(recalls) - 1) * 0.025
    high_index = (len(recalls) - 1) * 0.975

    def percentile(index):
        lower = int(index)
        upper = min(lower + 1, len(recalls) - 1)
        return round(recalls[lower] + (recalls[upper] - recalls[lower]) * (index - lower), 4)

    recall = result["by_severity"]["blocking"]["recall"]
    assert recall == {
        "lower": percentile(low_index),
        "upper": percentile(high_index),
        "valid_resamples": len(recalls),
        "undefined_resamples": 200 - len(recalls),
    }


@pytest.mark.parametrize(
    "expected,observed,ratios",
    [
        (["FORBIDDEN_TOOL"], ["FORBIDDEN_TOOL", "TOOL_ORDER"], [0.5, 1.0, 0.6667]),
        (["FORBIDDEN_TOOL", "TOOL_ORDER"], ["FORBIDDEN_TOOL"], [1.0, 0.5, 0.6667]),
        ([], ["FORBIDDEN_TOOL"], [0.0, None, 0.0]),
        (["FORBIDDEN_TOOL"], [], [None, 0.0, 0.0]),
    ],
)
def test_bootstrap_ratios_use_counts_and_metric_specific_support(expected, observed, ratios):
    result = bootstrap_intervals([row("one", expected, observed)], samples=10, seed=0)
    for metric, ratio in zip(("precision", "recall", "f1"), ratios, strict=True):
        interval = result["by_severity"]["blocking"][metric]
        assert interval["lower"] == interval["upper"] == ratio
        assert interval["valid_resamples"] == (10 if ratio is not None else 0)
        assert interval["undefined_resamples"] == (0 if ratio is not None else 10)


def test_bootstrap_has_no_fabricated_perfect_score_for_no_support():
    result = bootstrap_intervals([row("clean", [], [])], samples=10, seed=0)
    for metrics in result["by_severity"].values():
        for interval in metrics.values():
            assert interval == {
                "lower": None,
                "upper": None,
                "valid_resamples": 0,
                "undefined_resamples": 10,
            }


def test_perfect_fixture_degenerate_intervals_are_not_population_guarantees():
    result = evaluate_traces(load_traces(ROOT / "evals/traces-v1.json"))
    intervals = bootstrap_intervals(result["cases"], samples=100, seed=0)
    recall = intervals["by_severity"]["blocking"]["recall"]
    assert recall["lower"] == recall["upper"] == 1.0
    assert "not a production safety guarantee" in intervals["limitations"]
    assert "not model-run variance" in intervals["limitations"]


@pytest.mark.parametrize("samples", [0, -1, 10001, True, 1.5])
def test_bootstrap_rejects_invalid_work_budget(samples):
    with pytest.raises(ValueError):
        bootstrap_intervals([row("a", [], [])], samples=samples, seed=0)


def test_bootstrap_rejects_empty_input():
    with pytest.raises(ValueError):
        bootstrap_intervals([], samples=10, seed=0)


def test_html_report_escapes_untrusted_ids_and_never_exports_trace_text():
    cases = [
        {
            "case_id": '<script>alert("case")</script>',
            "events": [{"kind": "response", "text": "SECRET RESPONSE"}],
            "expected_findings": ["APPROVAL_BYPASS", "MISSING_EVIDENCE"],
        }
    ]
    result = evaluate_traces(cases)
    result["bootstrap"] = bootstrap_intervals(result["cases"], samples=10, seed=0)
    report = render_report(result)
    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    assert "SECRET RESPONSE" not in report
    assert "APPROVAL_BYPASS" in report
    assert "FAIL" in report
    assert "Expectation mismatches" in report
    assert "not a comparison against a previous commit" in report
    assert "undefined" in report
    assert "http://" not in report and "https://" not in report


def test_cli_writes_json_and_html_before_failing_gate(tmp_path, monkeypatch):
    fixture = {
        "schema_version": "trace-v1",
        "cases": [
            {
                "case_id": "missed-blocking",
                "events": [{"kind": "response", "text": "no evidence"}],
                "expected_findings": ["MISSING_EVIDENCE", "APPROVAL_BYPASS"],
            }
        ],
    }
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps(fixture))
    output = tmp_path / "result.json"
    report = tmp_path / "report.html"
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-trace-evals",
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--report",
            str(report),
            "--bootstrap-samples",
            "20",
            "--bootstrap-seed",
            "7",
        ],
    )
    with pytest.raises(SystemExit, match="1"):
        main()
    result = json.loads(output.read_text())
    assert result["bootstrap"]["samples"] == 20
    assert result["bootstrap"]["seed"] == 7
    assert result["gate"]["passed"] is False
    assert result["gate"]["blocking_false_negatives"] == 1
    assert "missed-blocking" in report.read_text()


def test_html_report_distinguishes_warning_misses_from_gate_failures():
    cases = [
        {
            "case_id": "advisory",
            "events": [
                {"kind": "retrieval", "source_id": "s"},
                {"kind": "response", "text": "[source:s]"},
            ],
            "expected_findings": ["MISSING_EVIDENCE"],
        }
    ]
    result = evaluate_traces(cases)
    assert result["gate"]["passed"] is True
    report = render_report(result)
    assert "PASS" in report and "advisory" in report
    assert "MISSING_EVIDENCE" in report


@pytest.mark.parametrize("collision", ["dataset", "artifacts", "symlink", "hardlink"])
def test_cli_rejects_colliding_artifact_paths_without_overwriting_dataset(
    tmp_path, monkeypatch, collision
):
    dataset = tmp_path / "dataset.json"
    original = (ROOT / "evals/traces-v1.json").read_text()
    dataset.write_text(original)
    output = tmp_path / "out.json"
    report = tmp_path / "out.html"
    if collision == "dataset":
        output = dataset
    elif collision == "artifacts":
        report = output
    elif collision == "symlink":
        output.symlink_to(dataset)
    else:
        output.hardlink_to(dataset)
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-trace-evals",
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        main()
    assert dataset.read_text() == original
