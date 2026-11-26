"""Commit-selected, same-fixture comparisons. No provider or GitHub token needed."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from agent_evals.trace_comparison import compare_artifacts, load_artifact, main, render_comparison
from agent_evals.traces import evaluate_traces, load_traces

ROOT = Path(__file__).parents[1]
BASE = "a" * 40
HEAD = "b" * 40


def artifact(commit=BASE):
    result = evaluate_traces(load_traces(ROOT / "evals/traces-v1.json"))
    result["provenance"] = {
        "source_commit": commit,
        "dataset_sha256": "c" * 64,
        "evaluator_sha256": "d" * 64,
        "evaluator_version": "trace-evaluator-v1",
    }
    return result


def change_findings(result, case_index, observed):
    """Recalculate a changed evaluator's output independently of the comparator."""
    from agent_evals.models import Metrics
    from agent_evals.traces import SEVERITIES

    row = result["cases"][case_index]
    expected = set(row["expected_findings"])
    row["observed_findings"] = sorted(observed)
    row["false_negatives"] = sorted(expected - set(observed))
    row["false_positives"] = sorted(set(observed) - expected)
    metrics = {}
    for severity in ("blocking", "warning"):
        tp = fp = fn = 0
        for case in result["cases"]:
            e = {x for x in case["expected_findings"] if SEVERITIES[x] == severity}
            o = {x for x in case["observed_findings"] if SEVERITIES[x] == severity}
            tp += len(e & o)
            fp += len(o - e)
            fn += len(e - o)
        metrics[severity] = Metrics(tp, fp, fn).to_dict()
    result["metrics_by_severity"] = metrics
    misses = metrics["blocking"]["false_negatives"]
    fps = sum(m["false_positives"] for m in metrics.values())
    result["gate"].update(
        passed=not misses and not fps, blocking_false_negatives=misses, false_positives=fps
    )


def compare(base, candidate):
    return compare_artifacts(base, candidate, baseline_commit=BASE, candidate_commit=HEAD)


def test_identical_results_are_paired_by_id_not_position():
    base, candidate = artifact(), artifact(HEAD)
    candidate["cases"].reverse()
    candidate["provenance"]["evaluator_sha256"] = "e" * 64
    result = compare(base, candidate)
    assert result["gate"]["passed"] is True
    assert result["changes"] == []
    assert result["case_count"] == len(base["cases"])
    assert result["baseline"]["source_commit"] == BASE
    assert result["candidate"]["source_commit"] == HEAD


def test_new_blocking_miss_fails_and_identifies_exact_case_finding():
    base, candidate = artifact(), artifact(HEAD)
    index = next(
        i for i, r in enumerate(candidate["cases"]) if "APPROVAL_BYPASS" in r["expected_findings"]
    )
    observed = set(candidate["cases"][index]["observed_findings"]) - {"APPROVAL_BYPASS"}
    change_findings(candidate, index, observed)
    result = compare(base, candidate)
    assert result["gate"]["passed"] is False
    assert result["changes"] == [
        {
            "case_id": candidate["cases"][index]["case_id"],
            "mismatch": "false_negatives",
            "finding": "APPROVAL_BYPASS",
            "severity": "blocking",
            "change": "introduced",
        }
    ]


def test_existing_failure_never_becomes_pass_because_delta_is_zero():
    base, candidate = artifact(), artifact(HEAD)
    change_findings(base, 0, ["FORBIDDEN_TOOL"])
    change_findings(candidate, 0, ["FORBIDDEN_TOOL"])
    result = compare(base, candidate)
    assert result["changes"] == []
    assert result["gate"]["passed"] is False
    assert result["gate"]["candidate_passed"] is False


def test_resolved_failure_is_not_a_regression():
    base, candidate = artifact(), artifact(HEAD)
    change_findings(base, 0, ["FORBIDDEN_TOOL"])
    result = compare(base, candidate)
    assert result["gate"]["passed"] is True
    assert result["changes"][0]["change"] == "resolved"
    assert result["changes"][0]["mismatch"] == "false_positives"


def test_warning_miss_is_advisory_but_warning_false_positive_blocks():
    base, candidate = artifact(), artifact(HEAD)
    index = next(
        i
        for i, r in enumerate(candidate["cases"])
        if r["expected_findings"] == ["MISSING_EVIDENCE"]
    )
    change_findings(candidate, index, [])
    result = compare(base, candidate)
    assert result["gate"]["passed"] is True
    assert result["changes"][0]["severity"] == "warning"
    change_findings(candidate, 0, ["MISSING_EVIDENCE"])
    assert compare(base, candidate)["gate"]["passed"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_sha256", "e" * 64),
        ("evaluator_version", "trace-evaluator-v2"),
        ("source_commit", "e" * 40),
    ],
)
def test_incompatible_or_wrongly_selected_candidate_is_rejected(field, value):
    candidate = artifact(HEAD)
    candidate["provenance"][field] = value
    with pytest.raises(ValueError):
        compare(artifact(), candidate)


def test_wrong_baseline_commit_is_rejected():
    with pytest.raises(ValueError):
        compare(artifact("e" * 40), artifact(HEAD))


@pytest.mark.parametrize("mutation", ["labels", "missing_case", "policy", "gate_policy"])
def test_changed_labels_case_coverage_or_policy_need_review_not_silent_pairing(mutation):
    candidate = artifact(HEAD)
    if mutation == "labels":
        candidate["cases"][0]["expected_findings"] = ["FORBIDDEN_TOOL"]
        change_findings(candidate, 0, [])
    elif mutation == "missing_case":
        candidate["cases"].pop(0)
    elif mutation == "policy":
        candidate["policy_version"] = "different-policy"
    else:
        candidate["gate"]["policy_version"] = "different-gate"
    with pytest.raises(ValueError):
        compare(artifact(), candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_case",
        "unknown_finding",
        "duplicate_finding",
        "bad_fn",
        "fake_metrics",
        "fake_gate",
        "bool_count",
        "raw_events",
        "unknown_root",
        "missing_provenance",
        "short_commit",
        "null_commit",
        "extra_provenance",
        "bad_digest",
        "empty_cases",
    ],
)
def test_malformed_artifacts_fail_closed(mutation, tmp_path):
    value = artifact()
    if mutation == "duplicate_case":
        value["cases"].append(copy.deepcopy(value["cases"][0]))
    elif mutation == "unknown_finding":
        value["cases"][0]["observed_findings"] = ["UNKNOWN"]
    elif mutation == "duplicate_finding":
        value["cases"][0]["observed_findings"] = ["FORBIDDEN_TOOL"] * 2
    elif mutation == "bad_fn":
        value["cases"][0]["false_negatives"] = ["FORBIDDEN_TOOL"]
    elif mutation == "fake_metrics":
        value["metrics_by_severity"]["blocking"]["recall"] = 0.5
    elif mutation == "fake_gate":
        value["gate"]["passed"] = False
    elif mutation == "bool_count":
        value["metrics_by_severity"]["blocking"]["false_negatives"] = False
    elif mutation == "raw_events":
        value["cases"][0]["events"] = [{"text": "SECRET"}]
    elif mutation == "unknown_root":
        value["raw_trace"] = "SECRET"
    elif mutation == "missing_provenance":
        del value["provenance"]
    elif mutation == "short_commit":
        value["provenance"]["source_commit"] = "abc1234"
    elif mutation == "null_commit":
        value["provenance"]["source_commit"] = None
    elif mutation == "extra_provenance":
        value["provenance"]["secret"] = "SECRET"
    elif mutation == "bad_digest":
        value["provenance"]["dataset_sha256"] = "X" * 64
    else:
        value["cases"] = []
    file = tmp_path / "artifact.json"
    file.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_artifact(file)


def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(tmp_path):
    file = tmp_path / "artifact.json"
    for payload in ('{"cases":[],"cases":[]}', '{"cases":NaN}', '{"cases":Infinity}'):
        file.write_text(payload)
        with pytest.raises(ValueError):
            load_artifact(file)


def test_html_is_inert_escaped_and_minimized():
    base, candidate = artifact(), artifact(HEAD)
    for value in (base, candidate):
        value["cases"][0]["case_id"] = '<script>alert("case")</script>'
    change_findings(candidate, 0, ["FORBIDDEN_TOOL"])
    report = render_comparison(compare(base, candidate))
    assert "<script>" not in report and "&lt;script&gt;" in report
    assert "FAIL" in report and "FORBIDDEN_TOOL" in report
    assert BASE in report and HEAD in report
    assert "not authenticated" in report
    assert "http://" not in report and "https://" not in report


def run_cli(tmp_path, monkeypatch, base, candidate, extra=None):
    baseline = tmp_path / "base.json"
    head = tmp_path / "head.json"
    baseline.write_text(json.dumps(base))
    head.write_text(json.dumps(candidate))
    output, report = tmp_path / "comparison.json", tmp_path / "comparison.html"
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-trace-compare",
            "--baseline",
            str(baseline),
            "--candidate",
            str(head),
            "--baseline-commit",
            BASE,
            "--candidate-commit",
            HEAD,
            "--output",
            str(output),
            "--report",
            str(report),
            *(extra or []),
        ],
    )
    return baseline, head, output, report


def test_cli_writes_failure_artifacts_and_binds_exact_input_bytes(tmp_path, monkeypatch):
    candidate = artifact(HEAD)
    change_findings(candidate, 0, ["FORBIDDEN_TOOL"])
    baseline, head, output, report = run_cli(tmp_path, monkeypatch, artifact(), candidate)
    with pytest.raises(SystemExit, match="1"):
        main()
    result = json.loads(output.read_text())
    assert (
        result["baseline"]["artifact_sha256"] == hashlib.sha256(baseline.read_bytes()).hexdigest()
    )
    assert result["candidate"]["artifact_sha256"] == hashlib.sha256(head.read_bytes()).hexdigest()
    assert result["gate"]["passed"] is False
    assert "FORBIDDEN_TOOL" in report.read_text()


def test_cli_success_and_invalid_selection_exit_codes(tmp_path, monkeypatch):
    _, _, output, report = run_cli(tmp_path, monkeypatch, artifact(), artifact(HEAD))
    main()
    assert json.loads(output.read_text())["gate"]["passed"] is True
    assert "PASS" in report.read_text()
    output.unlink()
    report.unlink()
    run_cli(tmp_path, monkeypatch, artifact(), artifact(HEAD), ["--baseline-commit", "abc1234"])
    with pytest.raises(SystemExit, match="2"):
        main()
    assert not output.exists() and not report.exists()


@pytest.mark.parametrize("collision", ["baseline", "candidate", "outputs", "symlink", "hardlink"])
def test_cli_never_overwrites_inputs_or_colliding_outputs(tmp_path, monkeypatch, collision):
    baseline, head, output, report = run_cli(tmp_path, monkeypatch, artifact(), artifact(HEAD))
    originals = [p.read_bytes() for p in (baseline, head)]
    if collision in ("baseline", "candidate"):
        path = baseline if collision == "baseline" else head
        option = ["--output", str(path)]
    elif collision == "outputs":
        option = ["--report", str(output)]
    elif collision == "symlink":
        output.symlink_to(baseline)
        option = []
    else:
        report.hardlink_to(head)
        option = []
    import sys

    monkeypatch.setattr("sys.argv", [*sys.argv, *option])
    with pytest.raises(SystemExit, match="2"):
        main()
    assert [p.read_bytes() for p in (baseline, head)] == originals


def test_trace_cli_records_exact_dataset_and_evaluator_hashes(tmp_path, monkeypatch):
    from agent_evals import traces

    dataset = ROOT / "evals/traces-v1.json"
    output = tmp_path / "trace.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-trace-evals",
            "--dataset",
            str(dataset),
            "--source-commit",
            HEAD,
            "--output",
            str(output),
            "--report",
            str(tmp_path / "trace.html"),
            "--bootstrap-samples",
            "10",
        ],
    )
    traces.main()
    result = load_artifact(output)
    assert result["provenance"]["source_commit"] == HEAD
    assert (
        result["provenance"]["dataset_sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    )
    assert len(result["provenance"]["evaluator_sha256"]) == 64
    assert result["provenance"]["evaluator_version"] == "trace-evaluator-v1"


def test_trace_cli_rejects_malformed_source_commit_before_writing(tmp_path, monkeypatch):
    from agent_evals import traces

    output = tmp_path / "trace.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-trace-evals",
            "--dataset",
            str(ROOT / "evals/traces-v1.json"),
            "--source-commit",
            " abc1234 ",
            "--output",
            str(output),
            "--report",
            str(tmp_path / "trace.html"),
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        traces.main()
    assert not output.exists()


def test_comparison_detects_an_actual_evaluator_mutation(monkeypatch):
    from agent_evals import traces

    cases = load_traces(ROOT / "evals/traces-v1.json")
    baseline = artifact()
    real_check = traces.check_trace
    monkeypatch.setattr(
        traces, "check_trace", lambda events: real_check(events) - {"APPROVAL_BYPASS"}
    )
    candidate = traces.evaluate_traces(cases)
    candidate["provenance"] = artifact(HEAD)["provenance"]
    result = compare(baseline, candidate)
    assert result["gate"]["passed"] is False
    assert any(
        row["finding"] == "APPROVAL_BYPASS" and row["change"] == "introduced"
        for row in result["changes"]
    )


def test_cli_end_to_end_detects_real_mutated_evaluator(tmp_path, monkeypatch):
    from agent_evals import traces

    baseline, candidate = tmp_path / "baseline.json", tmp_path / "candidate.json"
    for path, commit in ((baseline, BASE), (candidate, HEAD)):
        monkeypatch.setattr(
            "sys.argv",
            [
                "agent-trace-evals",
                "--dataset",
                str(ROOT / "evals/traces-v1.json"),
                "--source-commit",
                commit,
                "--output",
                str(path),
                "--report",
                str(path.with_suffix(".html")),
                "--bootstrap-samples",
                "10",
            ],
        )
        if path == candidate:
            real_check = traces.check_trace
            monkeypatch.setattr(
                traces,
                "check_trace",
                lambda events, check=real_check: check(events) - {"APPROVAL_BYPASS"},
            )
            with pytest.raises(SystemExit, match="1"):
                traces.main()
        else:
            traces.main()
    output = tmp_path / "comparison.json"
    report = tmp_path / "comparison.html"
    monkeypatch.setattr(
        "sys.argv",
        [
            "agent-trace-compare",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--baseline-commit",
            BASE,
            "--candidate-commit",
            HEAD,
            "--output",
            str(output),
            "--report",
            str(report),
        ],
    )
    with pytest.raises(SystemExit, match="1"):
        main()
    result = json.loads(output.read_text())
    assert result["gate"]["passed"] is False
    assert result["changes"] == [
        {
            "case_id": "model_claims_approval_without_event",
            "change": "introduced",
            "mismatch": "false_negatives",
            "finding": "APPROVAL_BYPASS",
            "severity": "blocking",
        }
    ]
    assert "APPROVAL_BYPASS" in report.read_text()


def test_artifact_input_budget_is_enforced(tmp_path):
    from agent_evals.trace_comparison import MAX_ARTIFACT_BYTES

    file = tmp_path / "large.json"
    file.write_bytes(b" " * (MAX_ARTIFACT_BYTES + 1))
    with pytest.raises(ValueError, match="5 MiB"):
        load_artifact(file)


def test_evaluator_fingerprint_matches_independent_framed_hash():
    from agent_evals import trace_provenance

    digest = hashlib.sha256()
    for name in ("models.py", "traces.py", "trace_provenance.py"):
        for part in (name.encode(), Path(trace_provenance.__file__).with_name(name).read_bytes()):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    metadata = trace_provenance.provenance(b"fixture", BASE)
    assert metadata["evaluator_sha256"] == digest.hexdigest()
    assert (
        metadata["dataset_sha256"]
        != trace_provenance.provenance(b"fixture\n", BASE)["dataset_sha256"]
    )


def test_missing_commit_is_explicit_and_not_comparable():
    from agent_evals.trace_provenance import provenance

    assert provenance(b"fixture", None)["source_commit"] is None
    candidate = artifact(HEAD)
    candidate["provenance"]["source_commit"] = None
    with pytest.raises(ValueError):
        compare(artifact(), candidate)


def test_ci_roundtrip_is_not_misrepresented_as_historical_comparison():
    workflow = (ROOT / ".github/workflows/quality.yml").read_text()
    assert "roundtrip, not a historical baseline gate" in workflow
    assert '--source-commit "$GITHUB_SHA"' in workflow
    assert '--baseline-commit "$GITHUB_SHA" --candidate-commit "$GITHUB_SHA"' in workflow
    assert "artifacts/*.xml" in workflow
