# ADR 0004: compare selected, compatible trace artifacts

## Status

Implemented in a feature branch toward release 0.4. Not a release or an automated historical PR gate. Tracked in [issue #6](https://github.com/jcorrego/agent-evals-in-ci/issues/6).

## Problem

The existing report compares observed findings with the current fixture labels. It cannot tell a reviewer which mismatch appeared after an earlier run. A simple difference of aggregate F1 can also hide a new blocking miss behind an unrelated improvement.

## Decision

Add `agent-trace-compare` over minimized evaluation JSON, with explicit full baseline and candidate commit arguments. Pair by case ID and finding type, not list position or aggregate metric. Report introduced and resolved false negatives and false positives.

The trace CLI records the SHA-256 of the exact dataset bytes it parses, an evaluator contract version and a framed hash of `models.py`, `traces.py` and `trace_provenance.py`. The comparator hashes the exact artifact bytes it reads. Length-prefixed file names and bytes make the evaluator hash input unambiguous. These hashes deliberately exclude HTML/bootstrap code because those advisory reports do not affect deterministic findings or metrics.

`--source-commit` is a caller assertion. Validate the literal identifier as exactly 40 lowercase hexadecimal characters, without trimming or repair. Do not claim that a supplied identifier verifies a clean checkout, runtime behavior, remote commit existence or authorship. Trusted workflow code must supply the actual checkout SHA. An omitted value is null and cannot participate in a comparison. Hashes are identifiers, not signatures or build attestations. An attacker who controls an artifact can forge its provenance and findings.

Require identical dataset byte hashes, identical case ID sets and expected finding sets, and the currently supported schema, evaluator contract, tool-policy and gate-policy versions. Evaluator code hashes may differ because evaluating an implementation change is useful. Do not silently intersect coverage or accept label edits. Reordering result rows is harmless; reformatting the source dataset changes its byte hash and requires rebaselining.

Validate both artifacts before pairing. Reject unknown result fields, duplicate JSON keys and cases, invalid/duplicate findings, inconsistent mismatch sets, unsupported versions, invalid hashes and nonfinite numbers. Recompute per-severity metrics and the absolute gate from expected/observed sets, including JSON type distinctions such as `false` versus `0`. Input reads are bounded to 5 MiB and case counts to 10,000. Optional bootstrap data is ignored and never copied into the comparison report.

The comparison exit gate is the validated candidate absolute gate. Zero changed mismatches cannot approve an existing blocking miss or false positive. A newly missed warning remains advisory. A fixed old failure may pass. This is an inspection report with the existing absolute policy, not a statistical significance test or a new calibrated delta threshold.

## Export and failure behavior

JSON and inert, script-free HTML contain provenance, case IDs and finding changes, not raw events, summaries, responses or source IDs. Escape all dynamic HTML. Case IDs are not redacted and must be synthetic pseudonyms. No remote assets are loaded.

A valid comparison writes both artifacts before exit 1 for candidate gate failure. Invalid or incompatible input exits 2 without writing new comparison artifacts. Existing output files are not removed on input error, so consumers must check the process exit status and artifact provenance, not the existence of an old file. Reject output aliases with either input or the other output, including symlinks and hard links. These local checks assume a non-hostile filesystem; they are not a defense against concurrent symlink replacement. Writes are not a crash-atomic multi-file transaction.

## CI and baseline review policy

This increment adds provenance to the real CI trace artifact, JUnit retention and a named same-artifact comparison roundtrip. It proves the installed command and artifact contract work. It does **not** select or download a previous commit's baseline and must not be described as a historical regression gate.

Until a trusted baseline-selection workflow exists, an operator must generate and retain both artifacts from selected checkouts, inspect their actual code/dataset provenance and select both commits explicitly. Legacy artifacts need regeneration with provenance support; never attach a guessed historical SHA. Deliberate label, fixture or policy corrections need a separate review explaining the old expectation, the evidence for the change and a regenerated baseline. Keep the old artifacts and commit links. Do not rewrite labels just to make a failing gate pass.

Historical artifact retrieval, signed provenance, a GitHub check/summary and provider calibration remain open. All tests and demos use synthetic fixtures and no provider secret.

## Evidence

Tests exercise an actual in-memory evaluator mutation removing approval-bypass detection, new and existing failures, resolved failures, warning semantics, mismatched fixture/coverage/labels/versions, forged metrics, duplicate/nonfinite JSON, bounded input, path aliasing, escaping, exact hashes, literal commit validation and CLI success/failure artifacts. A runtime mutation can retain the same file hash, another reason not to treat a hash as attestation.
