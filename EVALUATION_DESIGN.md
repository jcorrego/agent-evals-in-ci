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
