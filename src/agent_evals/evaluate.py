from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .judge import MODEL, DisabledJudge, OpenAIJudge, StructuredJudge
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


def _metrics(observed: set[str], expected: frozenset[str]) -> tuple[int, int, int]:
    return len(observed & expected), len(observed - expected), len(expected - observed)


def evaluate_dataset(
    cases: list[EvaluationCase], judge: StructuredJudge | None = None
) -> dict[str, Any]:
    active_judge = judge if judge is not None else DisabledJudge()
    tp = fp = fn = 0
    jtp = jfp = jfn = 0
    complete = active_judge.provider != "disabled"
    per_case: list[dict[str, Any]] = []

    for case in cases:
        deterministic = deterministic_findings(case.agent_output)
        review = active_judge.review(case.agent_output)
        observed = {finding.finding_type for finding in deterministic}
        dtp, dfp, dfn = _metrics(observed, case.expected_findings)
        tp += dtp
        fp += dfp
        fn += dfn
        judge_findings = review.findings
        if review.status == "ok" and judge_findings is not None:
            judged = {finding.finding_type for finding in judge_findings}
            a, b, c = _metrics(judged, case.expected_findings)
            jtp += a
            jfp += b
            jfn += c
            disagreement = {
                "deterministic_only": sorted(observed - judged),
                "judge_only": sorted(judged - observed),
            }
        else:
            complete = False
            disagreement = None
        per_case.append(
            {
                "case_id": case.case_id,
                "expected_findings": sorted(case.expected_findings),
                "observed_findings": sorted(observed),
                "findings": [finding.to_dict() for finding in deterministic],
                "deterministic_findings": [finding.to_dict() for finding in deterministic],
                "judge_findings": (
                    [finding.to_dict() for finding in judge_findings]
                    if judge_findings is not None
                    else None
                ),
                "judge": review.to_dict(),
                "disagreement": disagreement,
            }
        )

    return {
        "metrics": Metrics(tp, fp, fn).to_dict(),
        "judge_metrics": Metrics(jtp, jfp, jfn).to_dict() if complete else None,
        "judge_config": {
            "provider": active_judge.provider,
            "model": active_judge.model,
            "prompt_version": active_judge.prompt_version,
            "schema_version": active_judge.schema_version,
        },
        "cases": per_case,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate agent outputs against a golden dataset.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/evaluation.json"))
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--max-false-positives", type=int, default=0)
    parser.add_argument("--judge", choices=("disabled", "openai"), default="disabled")
    parser.add_argument("--api-url", default="https://api.openai.com/v1/chat/completions")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-delay", type=float, default=0.25)
    args = parser.parse_args()

    try:
        judge = (
            OpenAIJudge(
                api_key=os.environ.get("OPENAI_API_KEY", ""),
                api_url=args.api_url,
                model=args.model,
                timeout=args.timeout,
                retries=args.retries,
                retry_delay=args.retry_delay,
            )
            if args.judge == "openai"
            else None
        )
    except ValueError as error:
        parser.error(str(error))
    result = evaluate_dataset(load_dataset(args.dataset), judge)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    metrics = result["metrics"]
    print(
        json.dumps(
            {
                "deterministic": metrics,
                "judge_status": [row["judge"]["status"] for row in result["cases"]],
            },
            sort_keys=True,
        )
    )

    if metrics["recall"] < args.min_recall or metrics["false_positives"] > args.max_false_positives:
        raise SystemExit(1)
    if judge is not None and result["judge_metrics"] is None:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
