"""Fail-closed paired comparisons of minimized, explicitly selected trace artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from html import escape
from pathlib import Path
from typing import Any

from .models import Metrics
from .trace_provenance import DIGEST, EVALUATOR_VERSION, validate_commit
from .traces import SCHEMA_VERSION, SEVERITIES, _object, _text, _unique_object

LIMITATIONS = (
    "Source commits are caller assertions, not authenticated build attestations. "
    "Content hashes identify inputs, not their truth. Case IDs are escaped, not redacted. "
    "Only identical dataset bytes, evaluator contract and policy versions are comparable. "
    "Evaluator code hashes may differ. This is not a population safety measurement."
)
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
ROW_FIELDS = {
    "case_id",
    "expected_findings",
    "observed_findings",
    "false_negatives",
    "false_positives",
}


def _findings(value: Any) -> set[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(x, str) or x not in SEVERITIES for x in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("unknown or duplicate finding")
    return set(value)


def _same_json(actual: Any, expected: Any) -> bool:
    # Python equates False with 0 and True with 1; the artifact contract must not.
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
        expected, sort_keys=True, allow_nan=False
    )


def validate_artifact(value: Any) -> dict[str, dict[str, Any]]:
    required = {
        "schema_version",
        "policy_version",
        "metrics_by_severity",
        "gate",
        "cases",
        "provenance",
    }
    if not isinstance(value, dict) or not required <= set(value) <= required | {"bootstrap"}:
        raise ValueError("unknown or missing artifact fields; legacy artifacts need regeneration")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported trace schema")
    if value["policy_version"] != "synthetic-tool-policy-v1":
        raise ValueError("unsupported tool policy")
    metadata = _object(
        value["provenance"],
        {"source_commit", "dataset_sha256", "evaluator_sha256", "evaluator_version"},
        "provenance",
    )
    validate_commit(metadata["source_commit"])
    for key in ("dataset_sha256", "evaluator_sha256"):
        if not isinstance(metadata[key], str) or not DIGEST.fullmatch(metadata[key]):
            raise ValueError("invalid content digest")
    if metadata["evaluator_version"] != EVALUATOR_VERSION:
        raise ValueError("unsupported evaluator contract")
    if not isinstance(value["cases"], list) or not 1 <= len(value["cases"]) <= 10000:
        raise ValueError("artifact needs 1 to 10000 cases")
    rows = {}
    totals = {severity: [0, 0, 0] for severity in ("blocking", "warning")}
    for row in value["cases"]:
        _object(row, ROW_FIELDS, "case result")
        case_id = _text(row["case_id"], "case_id")
        if case_id in rows:
            raise ValueError("duplicate case_id")
        rows[case_id] = row
        expected, observed = (_findings(row[k]) for k in ("expected_findings", "observed_findings"))
        if (
            _findings(row["false_negatives"]) != expected - observed
            or _findings(row["false_positives"]) != observed - expected
        ):
            raise ValueError("inconsistent per-case mismatches")
        for severity, counts in totals.items():
            e = {x for x in expected if SEVERITIES[x] == severity}
            o = {x for x in observed if SEVERITIES[x] == severity}
            for index, count in enumerate((len(e & o), len(o - e), len(e - o))):
                counts[index] += count
    metrics = {severity: Metrics(*counts).to_dict() for severity, counts in totals.items()}
    if not _same_json(value["metrics_by_severity"], metrics):
        raise ValueError("inconsistent severity metrics")
    misses = metrics["blocking"]["false_negatives"]
    fps = sum(m["false_positives"] for m in metrics.values())
    gate = {
        "policy_version": "trace-gate-v1",
        "passed": not misses and not fps,
        "blocking_false_negatives": misses,
        "false_positives": fps,
    }
    if not _same_json(value["gate"], gate):
        raise ValueError("inconsistent or unsupported gate")
    return rows


def _nonfinite(_: str) -> None:
    raise ValueError("nonfinite JSON number")


def _read_artifact(path: Path) -> tuple[dict[str, Any], str]:
    # Read at most the budget plus one byte, not an unbounded file followed by a check.
    with path.open("rb") as stream:
        data = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact exceeds 5 MiB limit")
    value = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    validate_artifact(value)
    return value, hashlib.sha256(data).hexdigest()


def load_artifact(path: Path) -> dict[str, Any]:
    return _read_artifact(path)[0]


def compare_artifacts(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    baseline_commit: str,
    candidate_commit: str,
) -> dict[str, Any]:
    before, after = validate_artifact(baseline), validate_artifact(candidate)
    for value, selected in ((baseline, baseline_commit), (candidate, candidate_commit)):
        validate_commit(selected)
        if value["provenance"]["source_commit"] != selected:
            raise ValueError("artifact does not match the explicitly selected commit")
    for key in ("dataset_sha256", "evaluator_version"):
        if baseline["provenance"][key] != candidate["provenance"][key]:
            raise ValueError(
                "incompatible dataset or evaluator contract; reviewed rebaseline required"
            )
    if set(before) != set(after):
        raise ValueError("case coverage changed; reviewed rebaseline required")
    changes = []
    for case_id in sorted(before):
        b, c = before[case_id], after[case_id]
        if set(b["expected_findings"]) != set(c["expected_findings"]):
            raise ValueError("expected labels changed; reviewed rebaseline required")
        for mismatch in ("false_negatives", "false_positives"):
            previous, current = set(b[mismatch]), set(c[mismatch])
            for change, findings in (
                ("introduced", current - previous),
                ("resolved", previous - current),
            ):
                for finding in sorted(findings):
                    changes.append(
                        {
                            "case_id": case_id,
                            "mismatch": mismatch,
                            "finding": finding,
                            "severity": SEVERITIES[finding],
                            "change": change,
                        }
                    )
    return {
        "schema_version": "trace-comparison-v1",
        "baseline": dict(baseline["provenance"]),
        "candidate": dict(candidate["provenance"]),
        "case_count": len(before),
        "gate": {
            "policy_version": "trace-comparison-gate-v1",
            "passed": candidate["gate"]["passed"],
            "baseline_passed": baseline["gate"]["passed"],
            "candidate_passed": candidate["gate"]["passed"],
        },
        "changes": changes,
        "limitations": LIMITATIONS,
    }


def render_comparison(result: dict[str, Any]) -> str:
    def text(value: Any) -> str:
        return escape(str(value), quote=True)

    status = "PASS" if result["gate"]["passed"] else "FAIL"
    parts = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; base-uri 'none'\">",
        "<title>Paired trace comparison</title><body><h1>Paired trace comparison</h1>",
        f"<p>Candidate deterministic gate: <strong>{status}</strong></p>",
        "<p>A zero delta never approves an existing candidate failure. "
        "Warning misses remain advisory; any false positive blocks.</p>",
        f"<p>{text(result['limitations'])}</p>",
        f"<p>Paired cases: {text(result['case_count'])}.</p>",
    ]
    for role in ("baseline", "candidate"):
        parts.append(f"<h2>{text(role)}</h2><ul>")
        for key, value in result[role].items():
            parts.append(f"<li>{text(key)}: <code>{text(value)}</code></li>")
        parts.append("</ul>")
    parts.append("<h2>Changed expectation mismatches</h2>")
    if not result["changes"]:
        parts.append("<p>No changed mismatches. Inspect the candidate gate separately.</p>")
    for row in result["changes"]:
        parts.append(
            "<p>"
            + " | ".join(
                text(row[key]) for key in ("case_id", "change", "mismatch", "finding", "severity")
            )
            + "</p>"
        )
    parts.append("<p>Raw events, responses and source IDs are omitted.</p></body></html>")
    return "\n".join(parts) + "\n"


def _distinct_outputs(inputs: list[Path], outputs: list[Path]) -> None:
    for index, output in enumerate(outputs):
        for other in inputs + outputs[:index]:
            if output.resolve() == other.resolve() or (
                output.exists() and other.exists() and output.samefile(other)
            ):
                raise ValueError("outputs must not alias inputs or each other")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare commit-selected trace results.")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-commit", required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/trace-comparison.json"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/trace-comparison.html"))
    args = parser.parse_args()
    try:
        _distinct_outputs([args.baseline, args.candidate], [args.output, args.report])
        baseline, baseline_digest = _read_artifact(args.baseline)
        candidate, candidate_digest = _read_artifact(args.candidate)
        result = compare_artifacts(
            baseline,
            candidate,
            baseline_commit=args.baseline_commit,
            candidate_commit=args.candidate_commit,
        )
        result["baseline"]["artifact_sha256"] = baseline_digest
        result["candidate"]["artifact_sha256"] = candidate_digest
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(render_comparison(result), encoding="utf-8")
    print(json.dumps(result["gate"], sort_keys=True))
    if not result["gate"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
