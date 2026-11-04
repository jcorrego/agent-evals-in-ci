# Roadmap

The original [portfolio roadmap issue #1](https://github.com/jcorrego/agent-evals-in-ci/issues/1) is closed. Its unchecked release items are not proof of completion. The current bounded increment is tracked in [issue #4](https://github.com/jcorrego/agent-evals-in-ci/issues/4).

## Implemented on main, not tagged as a release

- [PR #2](https://github.com/jcorrego/agent-evals-in-ci/pull/2): optional schema-validated OpenAI adapter, versioned prompt/model/schema, retries, timeout and per-case failure records. Deterministic findings remain separate. Tested against a loopback provider, not a paid live provider.
- [PR #3](https://github.com/jcorrego/agent-evals-in-ci/pull/3): trace schema and synthetic trajectories, forbidden-call/approval/order/evidence checks, per-severity metrics and deterministic gate, CI failure-artifact upload.

## Current increment toward 0.3

[Issue #4](https://github.com/jcorrego/agent-evals-in-ci/issues/4): case-cluster bootstrap intervals and an offline reviewer report. The interval is not model-run variance, and the report identifies current expectation mismatches, not differences from a previous commit. See ADR 0003 for the statistical and export boundaries.

## Still open

- Release 0.2: independent human labels and calibration, an explicitly approved live-provider run, and verified provider results. Token-rate cost estimates are not actual billed charges.
- Release 0.3: broader trajectory coverage and calibrated class-specific thresholds; repeated-run experiments if probabilistic trajectory evaluation is introduced.
- Release 0.4: a GitHub check/summary, baseline selection tied to commit and evaluator version, paired comparisons, and review policy for intentional label corrections.
- Tag releases only after owner-approved merge, verified tests and CI. No automatic merge or release is part of the scheduled engineering cycle.
