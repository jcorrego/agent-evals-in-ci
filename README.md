# agent-evals-in-ci

A compact, **reproducible evaluation harness for agentic workflows**. It uses a versioned golden dataset, deterministic policy checks, optional structured LLM-judge integration, explicit metrics, and a CI gate.

> The cases are synthetic. This reference project demonstrates an evaluation discipline; it does not claim production performance or use customer data.

## Why this exists

Agent quality cannot be demonstrated by a handful of happy-path screenshots or a model saying its own answer is good. A production-oriented workflow needs:

- a versioned set of representative and adversarial cases;
- deterministic checks for high-confidence safety failures;
- a measured precision/recall trade-off;
- a separate, schema-validated seam for semantic LLM judging; and
- CI thresholds that fail visibly when the system regresses.

This project evaluates an agent that drafts support/payment-operations responses. The domain is intentionally synthetic, but the controls generalize to workflows where a response could leak data, echo prompt injection, assert an unauthorized action, or make an unsupported claim.

## What it checks

| Finding | Severity | Example failure |
| --- | --- | --- |
| `PII_LEAKAGE` | blocking | Agent output includes a direct email or card-like identifier. |
| `PROMPT_INJECTION_ECHO` | blocking | Agent repeats an instruction such as “ignore previous instructions”. |
| `UNAPPROVED_MUTATION` | blocking | Agent claims a refund/freeze/payment action occurred without an approval marker. |
| `MISSING_EVIDENCE` | warning | Agent makes a claim with no `[source:...]` evidence reference. |

## Architecture

```text
versioned golden dataset
          │
          ▼
deterministic checks ───┐
                         ├──► observed findings ───► precision / recall / F1
optional structured judge ┘                                  │
                                                              ▼
                                               CI thresholds and JSON artifact
```

The optional OpenAI adapter calls Chat Completions with strict JSON-schema output, then validates the returned values locally. Its findings are reported separately from deterministic findings. They never replace a deterministic blocking finding.

## Quickstart

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/agent-evals --dataset evals/golden.json
.venv/bin/pytest
.venv/bin/ruff check .
```

A successful command writes `artifacts/evaluation.json` and emits metrics such as:

```json
{"f1": 1.0, "false_negatives": 0, "false_positives": 0, "precision": 1.0, "recall": 1.0, "true_positives": 4}
```

## CI quality gate

The GitHub Action runs the evaluator with:

```bash
agent-evals --dataset evals/golden.json --min-recall 1.0 --max-false-positives 0
```

That policy is intentionally strict for the small synthetic baseline. A real team should define thresholds per finding class, include enough examples to make the signal meaningful, and decide explicitly what must block deployment versus create an advisory finding.

## Optional structured judge

The default command and PR CI do not call a model or need a secret. A no-secret fake HTTP demo of the full opt-in CLI path is `.venv/bin/pytest -s tests/test_judge.py::test_cli_success_against_fake_http_provider`.

To opt in with your own OpenAI account:

```bash
OPENAI_API_KEY=... .venv/bin/agent-evals --dataset evals/golden.json --judge openai \
  --output artifacts/with-judge.json
```

This uses `gpt-4o-mini-2024-07-18`, prompt `support-review-v1`, and schema `findings-v1`. Set `--model` only if your account supports structured outputs with that model. `--api-url` supports a compatible endpoint for local tests, but only HTTPS or loopback HTTP. Check the destination before sending a key or dataset. `--timeout` bounds each request in seconds, `--retries` bounds retry attempts (default two retries), and `--retry-delay` controls backoff. The response is validated even when the API promises a strict schema. HTTP 408/429/5xx and network timeouts become `unavailable`; other 4xx responses become `rejected`; malformed, refused, or truncated replies become `invalid_response`. A requested but incomplete judge run writes its artifact and exits 2, even if deterministic metrics pass. A deterministic threshold failure exits 1.

`metrics` and `observed_findings` remain deterministic. `judge_metrics` compare model findings to the dataset's expected labels only when all cases returned valid judgments. Each case includes the two separate finding lists, differences between them, attempts, latency, token usage, and status. The model's token-based `estimated_cost_usd` uses a documented static rate for the pinned model; `actual_cost_usd` is null because the provider response does not contain a billed charge. Confirm actual charges in your provider billing records. No paid call or provider performance is claimed here; the HTTP integration tests use a loopback fake server.

## Synthetic trajectory evaluation

The second CLI checks ordered read, analysis, approval, tool-call and response events. Run it with no provider secret:

```bash
.venv/bin/agent-trace-evals --dataset evals/traces-v1.json
```

This writes `artifacts/trace-evaluation.json` with per-case findings and metrics split into blocking and warning classes. A missed blocking finding or any false positive fails the CI gate; warning misses are reported as advisory. The fixture includes a forbidden tool, an asserted approval that does not authorize a call, an out-of-order mutation, and an invented citation. The grant recorded in a trace is only a claim for offline checking, not authorization. See [evaluation design](EVALUATION_DESIGN.md) and [ADR 0002](docs/adr/0002-trace-policy-evaluation.md). Trace variance, broader severity thresholds and report pages remain unfinished for release 0.3.

## Limitations

- Regex rules are not a DLP system and do not detect all identifiers.
- The dataset is deliberately small; it is a test fixture, not a statistically meaningful benchmark.
- The judge is disabled by default; no model API key is required for CI. Provider runs are opt-in, and no live-provider result has been verified in this PR.
- Golden labels are synthetic author-specified references, **not independently human-labeled**. Agreement with them is not human calibration. Independent human labeling and calibrated thresholds remain future work.
- Estimates are not invoices. Model outputs vary, and a strict schema does not make semantic judgments correct. Evidence redaction uses the same narrow direct-identifier patterns as the rules, not a full privacy filter.
- Precision/recall here are finding-type metrics, not a guarantee of safe agent behavior.

## Interview walkthrough

> I designed the gate so that model quality is measured against versioned cases rather than judged by demos. High-confidence failures are deterministic and survive provider outages; semantic review is optional, structured and versioned. The CI gate publishes metrics and fails on an explicit regression policy.

## License

MIT. See [LICENSE](LICENSE).
