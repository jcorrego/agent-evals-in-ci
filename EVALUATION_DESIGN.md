# Evaluation design notes

## Test levels

1. **Deterministic policy tests** catch violations that should not depend on a judge: direct identifiers, known injection text, unsupported state-change claims, and missing source markers.
2. **Golden-set regression evaluation** measures observed finding types against expected finding types across versioned examples.
3. **Optional semantic judging** is a separate layer for nuance that rules cannot capture. It must return structured, validated findings.

## What the metrics mean

- **True positive:** a finding type expected by the golden case is emitted.
- **False positive:** an emitted finding type was not expected for that case.
- **False negative:** an expected finding type was not emitted.
- **Precision / recall / F1:** computed over finding types across cases.

This is deliberately simple and inspectable. It is not a substitute for human review of representative failures, policy-specific calibration, or online production monitoring.

## CI policy

The repository baseline requires recall of `1.0` and zero false positives. This is appropriate only because the sample is a tiny, controlled fixture. In a real workflow, configure policy by severity and decide which classes are blocking. For example, missed direct PII or unapproved financial mutations may require fail-closed behavior, while a citation-style warning could remain advisory.
