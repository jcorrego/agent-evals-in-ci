from __future__ import annotations

from typing import Protocol

from .models import Finding


class StructuredJudge(Protocol):
    """Optional seam for an LLM judge that must return validated findings.

    Implementations should use a provider's structured-output API, validate the schema,
    and record model/version/prompt metadata outside this interface.
    """

    def review(self, agent_output: str) -> list[Finding]: ...


class DisabledJudge:
    """Explicitly represents CI runs that do not have a model provider configured."""

    def review(self, agent_output: str) -> list[Finding]:
        del agent_output
        return []
