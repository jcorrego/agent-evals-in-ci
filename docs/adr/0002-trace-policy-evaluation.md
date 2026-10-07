# ADR 0002: Evaluate trajectories separately from response text

Status: accepted for the synthetic reference evaluator.

## Decision

Use a versioned ordered-event fixture for tool and citation checks. Validate all event shapes before scoring, apply deterministic rules over the supplied order, and keep trace results separate from response-text and optional provider judgments. Consume a grant after one sensitive call. Report findings and errors by case and severity without exporting raw output text.

## Why

A final response can contain a source marker even when no retrieval preceded it. Similarly, a model may write "approved" without any approval event. Offline trace checks expose both cases, but only the serving system can establish that an event came from a trusted source. The gate therefore measures consistency, not authorization or provenance.

## Trade-offs

The tool allowlist and severity map are fixed for the synthetic example; deployment would need policy ownership, event signatures, verified approver identity and independent reference labels. A fabricated or incomplete trace can appear clean. Warnings do not block on missed cases yet because this small fixture cannot calibrate a meaningful recall threshold. No provider is required for this path.
