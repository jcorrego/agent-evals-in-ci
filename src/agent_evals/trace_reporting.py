"""Case-cluster uncertainty and an inert HTML report over minimized trace results."""

from __future__ import annotations

import random
from html import escape
from typing import Any

from .traces import SEVERITIES

LIMITATIONS = (
    "Resampling whole synthetic cases measures fixture-composition sensitivity, "
    "not model-run variance. "
    "Cases and labels are author-specified, not an independent population sample. "
    "A degenerate [1, 1] interval is not a production safety guarantee. "
    "Undefined ratios are excluded separately per metric; their counts remain visible. "
    "Intervals are conditional on defined ratios and are advisory, never a CI gate."
)


def _percentile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return round(values[lower] + (values[upper] - values[lower]) * (position - lower), 4)


def bootstrap_intervals(
    rows: list[dict[str, Any]], *, samples: int = 2000, seed: int = 0
) -> dict[str, Any]:
    """Percentile intervals with each entire case as one resampling unit.

    Unlike the historical point metrics' empty-set convention, undefined bootstrap
    precision/recall/F1 values are not silently replaced by perfect scores.
    """
    if not rows or type(samples) is not int or not 1 <= samples <= 10000:
        raise ValueError("bootstrap needs nonempty cases and 1 to 10000 samples")
    if type(seed) is not int:
        raise ValueError("bootstrap seed must be an integer")
    counts = {}
    for severity in ("blocking", "warning"):
        counts[severity] = []
        for row in rows:
            expected = {x for x in row["expected_findings"] if SEVERITIES[x] == severity}
            found = {x for x in row["observed_findings"] if SEVERITIES[x] == severity}
            counts[severity].append(
                (len(expected & found), len(found - expected), len(expected - found))
            )
    draws = {
        severity: {metric: [] for metric in ("precision", "recall", "f1")} for severity in counts
    }
    rng = random.Random(seed)
    for _ in range(samples):
        # The same draw applies to all severities, preserving within-case correlation.
        indices = [rng.randrange(len(rows)) for _ in rows]
        for severity, per_case in counts.items():
            tp, fp, fn = (sum(per_case[i][column] for i in indices) for column in range(3))
            denominators = {"precision": tp + fp, "recall": tp + fn, "f1": 2 * tp + fp + fn}
            for metric, denominator in denominators.items():
                if denominator:
                    numerator = 2 * tp if metric == "f1" else tp
                    draws[severity][metric].append(numerator / denominator)
    intervals = {}
    for severity, metrics in draws.items():
        intervals[severity] = {}
        for metric, values in metrics.items():
            values.sort()
            intervals[severity][metric] = {
                "lower": _percentile(values, 0.025) if values else None,
                "upper": _percentile(values, 0.975) if values else None,
                "valid_resamples": len(values),
                "undefined_resamples": samples - len(values),
            }
    return {
        "method": "case-cluster-percentile-v1",
        "confidence_level": 0.95,
        "samples": samples,
        "seed": seed,
        "case_count": len(rows),
        "limitations": LIMITATIONS,
        "by_severity": intervals,
    }


def render_report(result: dict[str, Any]) -> str:
    """No script, remote assets, raw events, summaries, response text or source IDs."""

    def text(value: Any) -> str:
        return escape(str(value), quote=True)

    status = "PASS" if result["gate"]["passed"] else "FAIL"
    parts = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'\">",
        "<title>Trace evaluation report</title><style>",
        "body{font:16px system-ui;max-width:960px;margin:2rem auto;padding:0 1rem}",
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #999;",
        "padding:.5rem;text-align:left;overflow-wrap:anywhere}code{white-space:pre-wrap}",
        "</style><body><h1>Trace evaluation report</h1>",
        f"<p>Deterministic gate: <strong>{status}</strong></p>",
        f"<p>Trace schema: {text(result['schema_version'])}. "
        f"Policy: {text(result['policy_version'])}. "
        f"Gate: {text(result['gate']['policy_version'])}.</p>",
        "<p>A missed blocking finding or any false positive fails. Warning misses are advisory. "
        "Bootstrap intervals do not change this gate.</p>",
        "<p>Point metrics preserve the empty-denominator convention of 1.0; "
        "bootstrap intervals instead count undefined ratios explicitly.</p>",
        "<h2>Metrics by severity</h2><table><tr><th>Severity</th><th>TP / FP / FN</th>"
        "<th>Precision / recall / F1</th></tr>",
    ]
    for severity, metrics in result["metrics_by_severity"].items():
        counts = " / ".join(
            str(metrics[k]) for k in ("true_positives", "false_positives", "false_negatives")
        )
        ratios = " / ".join(str(metrics[k]) for k in ("precision", "recall", "f1"))
        parts.append(
            f"<tr><td>{text(severity)}</td><td>{text(counts)}</td><td>{text(ratios)}</td></tr>"
        )
    parts.append(
        "</table><h2>Expectation mismatches</h2><p>These are differences against "
        "author-specified fixture labels, not a comparison against a previous commit.</p>"
    )
    mismatches = [r for r in result["cases"] if r["false_negatives"] or r["false_positives"]]
    if not mismatches:
        parts.append("<p>No expectation mismatches.</p>")
    for row in mismatches:
        parts.append(f"<h3><code>{text(row['case_id'])}</code></h3>")
        for field in ("false_negatives", "false_positives"):
            values = ", ".join(row[field]) or "none"
            parts.append(f"<p>{text(field)}: <code>{text(values)}</code></p>")
    bootstrap = result.get("bootstrap")
    if bootstrap:
        parts.extend(
            [
                "<h2>95% case-cluster bootstrap intervals</h2>",
                f"<p>{text(bootstrap['limitations'])}</p>",
                f"<p>Cases: {text(bootstrap['case_count'])}. "
                f"Resamples: {text(bootstrap['samples'])}. Seed: {text(bootstrap['seed'])}.</p>",
                "<table><tr><th>Severity / metric</th><th>Interval</th>"
                "<th>Defined / undefined</th></tr>",
            ]
        )
        for severity, metrics in bootstrap["by_severity"].items():
            for metric, interval in metrics.items():
                bounds = (
                    "undefined"
                    if interval["lower"] is None
                    else f"[{interval['lower']}, {interval['upper']}]"
                )
                parts.append(
                    f"<tr><td>{text(severity)} / {text(metric)}</td><td>{text(bounds)}</td>"
                    f"<td>{text(interval['valid_resamples'])} / "
                    f"{text(interval['undefined_resamples'])}</td></tr>"
                )
        parts.append("</table>")
    parts.append(
        "<p>Only synthetic pseudonymous case IDs and finding names belong in this "
        "report. Case IDs are not redacted. Raw trace text is omitted.</p></body></html>"
    )
    return "\n".join(parts) + "\n"
