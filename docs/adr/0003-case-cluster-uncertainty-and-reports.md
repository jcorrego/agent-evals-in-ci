# ADR 0003: resample cases and report expectation mismatches

Status: proposed in the trace-report increment, toward release 0.3.

## Decision

Add a seeded, whole-case percentile bootstrap to the offline trace evaluator. A draw samples N case indices with replacement from the N supplied cases. It keeps all expected and observed finding classes of a case together, including their correlation across severities. Each draw recomputes micro precision, recall and F1 from unrounded TP/FP/FN counts. The 95% interval uses linearly interpolated 2.5th and 97.5th percentiles, rounded only for output.

Use the standard library rather than adding a numerical dependency for this small fixture. Record method `case-cluster-percentile-v1`, sample count, seed, case count, confidence level and defined/undefined draw counts for each ratio. The default is 2,000 draws with seed 0. The CLI accepts 1 to 10,000 draws, with the full dataset size in each draw. This is a local developer tool, not a resource-isolated service for arbitrary uploads.

A precision denominator of zero, a recall denominator of zero, or an F1 denominator of zero produces an undefined value for that metric in that draw. Exclude it from that metric's percentiles and count it. If all draws are undefined, both bounds are JSON null. Do not turn missing statistical support into a perfect result. The existing point metrics retain their historical empty-denominator convention of 1.0; the report explains this difference explicitly.

The same result object supplies JSON, an inert HTML report and the CLI exit status. The deterministic gate stays unchanged: any missed blocking finding or any false positive fails; warning misses remain advisory. Write both reports before returning a failing gate status. CI uploads JSON and HTML even after failure.

## Why whole cases

Findings inside one trajectory are related. Sampling individual finding labels would pretend that a forbidden call and an approval bypass in the same workflow were independent evidence. Resampling case indices keeps that relationship intact. A private PRNG prevents a report from altering the caller's global random state.

## Report boundary

The HTML displays severity metrics, the gate outcome, interval support counts, and case IDs with false-positive/false-negative finding names. It does not copy raw events, model summaries, response text or source IDs. Every dynamic field is HTML-escaped. There are no scripts or remote assets, and a content-security policy denies external resources. Case IDs are not redacted: the input contract still requires synthetic pseudonymous identifiers.

The report compares observed findings with the current fixture's expected labels. It is not a historical regression comparison. Commit-bound baseline selection, paired-difference intervals and intentional label-change review remain release 0.4 work. These additions are not implicitly claimed by calling an expectation mismatch a regression.

## Limits

This fixture is small, synthetic and author-labeled. Bootstrap intervals describe sensitivity to the composition of this fixture under empirical case resampling. They do not establish production safety, independent human calibration, model-run variance or causal performance improvements. Perfect agreement can produce a degenerate [1, 1] interval, even when the evaluator misses unrepresented attacks. Undefined draws mean each interval is conditional on a defined denominator. The interval is advisory and cannot override a deterministic finding.

The evaluator still checks the consistency of an untrusted supplied trace, not runtime authorization or completeness of event capture. No model provider is called. Artifacts are local files and not a tamper-resistant record.

## Verification

`tests/test_trace_reporting.py` covers seeded replay against an independent whole-case recall calculation, global PRNG isolation, absent support, degenerate perfect-fixture intervals, invalid work budgets, HTML escaping and trace-text omission, advisory warning misses, artifact creation on gate failure, and protection against input/output path collisions including symlinks and hard links. The workflow test checks that both artifact types upload under `always()`.
