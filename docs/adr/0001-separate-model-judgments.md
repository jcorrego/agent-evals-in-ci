# ADR 0001: Keep model judgments separate from the deterministic gate

Status: proposed for release 0.2 PR. Related: [roadmap issue #1](https://github.com/jcorrego/agent-evals-in-ci/issues/1).

The existing PR gate checks known violations without a provider secret. A semantic judge can find cases the rules miss, but its outputs may vary, refuse, fail, or disagree with the fixture labels. Replacing rule results with a model verdict would let an outage or false negative hide a blocking violation.

We use OpenAI Chat Completions with a pinned default model and strict JSON-schema response format. We check the response again locally, reject malformed findings, refusals, truncated responses and missing token usage, and distinguish unavailable from rejected requests. We retry only timeouts/network errors, 408, 429, and 5xx, within a bounded per-attempt timeout and retry count. Artifacts omit credentials, raw provider errors and raw response bodies. Redirects are disabled so a provider response cannot forward a credential to a second host. The adapter accepts HTTPS or loopback HTTP for local tests.

The deterministic metrics remain the sole CI quality gate. Model findings and metrics are recorded separately, along with finding-type disagreement against deterministic findings and the fixture labels. If any case fails, the optional judge run returns a nonzero exit code after writing the artifact. No absent model result is treated as a clean result. Per-request token counts and wall-clock latency are recorded. A static rate permits a cost estimate for the pinned model, not an actual billed charge; actual cost remains null until a billing source can supply it.

This does not calibrate the judge to independent human labels. The tiny golden set has author-specified synthetic expectations, not verified human annotations. Real-provider execution is opt-in and unverified here. A later increment can add independently reviewed labels and a secure, approved or scheduled provider-backed run without making normal PR CI dependent on a paid API.
