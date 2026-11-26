# Changelog

## Unreleased

### Added

- Commit-selected `agent-trace-compare` CLI with paired finding changes, strict artifact validation, exact dataset/evaluator/artifact hashes and minimized JSON/HTML reports. Candidate absolute failures still block when the baseline has the same failure.
- Explicit compatibility and label-correction review policy in ADR 0004. Commit metadata is caller-asserted, not authenticated provenance. Legacy artifacts require regeneration.
- Real CI trace provenance, a clearly labeled same-artifact comparison roundtrip and JUnit upload. Automatic historical baseline retrieval and PR summaries remain open.
- Advisory 95% whole-case bootstrap intervals for trace precision, recall and F1, with fixed seed, bounded draw count and explicit undefined-ratio support counts.
- Self-contained HTML report of severity metrics, gate status and case/finding expectation mismatches. Raw trace text stays out of the report; case IDs are escaped but not redacted.
- JSON gate-policy metadata shared with the report and exit status. Both artifacts are written before returning a failing gate status.
- CI upload of HTML alongside JSON, including on failed evaluations.
- Regression tests and ADR 0003 describing the empirical-resampling limits.

No release tag, live-provider performance, independent human calibration or production safety claim accompanies this increment. Earlier judge and trace changes were merged in PRs #2 and #3; see ROADMAP.md for remaining work.
