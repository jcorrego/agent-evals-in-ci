# Evaluation design notes

## Test levels

1. **Deterministic policy tests** catch violations that should not depend on a judge: direct identifiers, known injection text, unsupported state-change claims, and missing source markers.
2. **Golden-set regression evaluation** measures observed finding types against expected finding types across versioned examples.
3. **Optional semantic judging** uses strict structured output and local shape/value validation. We report its metrics against the same author-specified synthetic reference labels, but do not combine its findings into the deterministic gate.

## What the metrics mean

- **True positive:** a finding type expected by the golden case is emitted.
- **False positive:** an emitted finding type was not expected for that case.
- **False negative:** an expected finding type was not emitted.
- **Precision / recall / F1:** computed over finding types across cases.

This is deliberately simple and inspectable. It is not a substitute for human review of representative failures, policy-specific calibration, or online production monitoring.

## Judge failure and disagreement

The provider adapter records a status per case. Only complete, valid runs get judge metrics; invalid/refused/truncated replies or an unavailable provider leave them null and cause an opt-in CLI run to fail after writing the artifact. Disagreements list finding types only on valid cases. The deterministic gate does not depend on those results. Attempts and wall-clock latency include retries. Token counts come from provider usage; estimated USD is computed with static rates for the pinned model and actual billed USD is unknown. We do not silently interpret an outage as no findings.

The synthetic golden labels were written with the fixture; they were not independently labeled by people. A future calibration set needs provenance and separate label review before making a human-agreement claim. We also do not gate PRs on model disagreement because this tiny dataset cannot support a stable semantic threshold.

## CI policy

The repository baseline requires recall of `1.0` and zero false positives. This is appropriate only because the sample is a tiny, controlled fixture. In a real workflow, configure policy by severity and decide which classes are blocking. For example, missed direct PII or unapproved financial mutations may require fail-closed behavior, while a citation-style warning could remain advisory.

## Trace policy check (increment toward 0.3)

`evals/traces-v1.json` defines synthetic ordered events and author-specified expectations. `agent-trace-evals` validates every event before evaluation, tracks prior retrieval IDs and grants, consumes a grant after one sensitive call, and flags missing citations, forbidden tools and calls made before analysis or without a grant. The separate JSON artifact records per-case false positives/negatives, per-severity metrics and the deterministic gate outcome. CI fails on a missed blocking class or any false positive; warning misses remain visible but advisory. This small fixture has no model repeated-run variance or calibrated thresholds yet.

The evaluator is **not** an authorization system: the trace itself is untrusted and an attacker could forge a `granted` event or omit a call. Production systems must emit tamper-resistant events from verified tool/approval services; this evaluator only checks consistency of supplied events. Source markers prove only that the ID appeared earlier in the supplied trace, not that a claim is true. Summaries and response text are never exported in the trace result artifact.

## Case-cluster uncertainty and offline report

The advisory 95% bootstrap uses the case as its resampling unit. All findings in a trajectory move together. Each draw samples N cases with replacement, recomputes micro TP/FP/FN counts and unrounded ratios, then contributes to linearly interpolated percentile bounds. Ratios with zero denominators are excluded separately, with defined and undefined counts exported. An entirely undefined metric has null bounds. The existing point-metric convention of 1.0 for an empty denominator is preserved, not reused for bootstrap observations.

These intervals describe the empirical fixture under resampling. They do not measure model-run variance, and author-specified synthetic cases do not justify population inference. Perfect fixture agreement can yield [1, 1] intervals even though the fixture omits important attacks. Conditional intervals and low support require inspection, not a softer gate. Method, seed, budget and case count are in JSON for replay. No provider call or paid secret is needed.

The HTML report shows expectation mismatches by case and finding, severity metrics, gate status and interval support. It is not a comparison against a previous commit. It omits raw trace text and source IDs, escapes all dynamic content and loads no remote assets. Case IDs are not redacted and must remain synthetic pseudonyms. JSON and HTML are written before returning a gate-failure exit code; CI uploads both under `always()`. See ADR 0003 for details and tests.
