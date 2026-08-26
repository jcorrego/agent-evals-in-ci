from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .judge import DisabledJudge, StructuredJudge
from .models import EvaluationCase, Metrics
from .rules import deterministic_findings


def load_dataset(path: Path) -> list[EvaluationCase]:
    raw = json.loads(path.read_text())
    return [
        EvaluationCase(
            case_id=item["case_id"],
            agent_output=item["agent_output"],
            expected_findings=frozenset(item["expected_findings"]),
        )
        for item in raw["cases"]
    ]


def evaluate_dataset(
    cases: list[EvaluationCase], judge: StructuredJudge | None = None
) -> dict[str, Any]:
    active_judge = judge or DisabledJudge()
    tp = fp = fn = 0
    per_case: list[dict[str, Any]] = []

    for case in cases:
        findings = [
            *deterministic_findings(case.agent_output),
            *active_judge.review(case.agent_output),
        ]
        observed = {finding.finding_type for finding in findings}
        tp += len(observed & case.expected_findings)
        fp += len(observed - case.expected_findings)
        fn += len(case.expected_findings - observed)
        per_case.append(
            {
                "case_id": case.case_id,
                "expected_findings": sorted(case.expected_findings),
                "observed_findings": sorted(observed),
                "findings": [finding.to_dict() for finding in findings],
            }
        )

    metrics = Metrics(tp, fp, fn)
    return {"metrics": metrics.to_dict(), "cases": per_case}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate agent outputs against a golden dataset.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/evaluation.json"))
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--max-false-positives", type=int, default=0)
    args = parser.parse_args()

    result = evaluate_dataset(load_dataset(args.dataset))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    metrics = result["metrics"]
    print(json.dumps(metrics, sort_keys=True))

    if metrics["recall"] < args.min_recall or metrics["false_positives"] > args.max_false_positives:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
