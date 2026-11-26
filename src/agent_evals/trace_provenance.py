"""Reproducible content hashes, not authenticated build attestations."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

EVALUATOR_VERSION = "trace-evaluator-v1"
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def validate_commit(value: str) -> str:
    if not isinstance(value, str) or not COMMIT.fullmatch(value):
        raise ValueError("source commit must be exactly 40 lowercase hexadecimal characters")
    return value


def provenance(dataset: bytes, source_commit: str | None) -> dict[str, str | None]:
    if source_commit is not None:
        validate_commit(source_commit)
    digest = hashlib.sha256()
    # Length-prefix names and bytes so concatenation cannot create ambiguous inputs.
    for name in ("models.py", "traces.py", "trace_provenance.py"):
        for part in (name.encode(), Path(__file__).with_name(name).read_bytes()):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return {
        "source_commit": source_commit,
        "dataset_sha256": hashlib.sha256(dataset).hexdigest(),
        "evaluator_sha256": digest.hexdigest(),
        "evaluator_version": EVALUATOR_VERSION,
    }
