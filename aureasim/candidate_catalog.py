"""Discover compatible local candidate packages without arbitrary path input."""

from __future__ import annotations

import hashlib
from pathlib import Path

from aureasim.parameter_candidates import CandidateSet


def discover_candidate_packages(
    repo_root: Path,
    base_path: Path,
    roots: list[Path] | None = None,
) -> list[dict]:
    base_hash = hashlib.sha256(base_path.read_bytes()).hexdigest()
    roots = roots or [repo_root / "local_evidence" / "candidate_packages"]
    results: list[dict] = []
    seen_ids: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("parameter_candidates.json")):
            try:
                candidate_set = CandidateSet.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if candidate_set.candidate_set_id in seen_ids:
                continue
            seen_ids.add(candidate_set.candidate_set_id)
            results.append({
                "candidate_set_id": candidate_set.candidate_set_id,
                "process_alias": candidate_set.process_alias,
                "process_id": candidate_set.process_id,
                "process_version": candidate_set.process_version,
                "candidate_count": len(candidate_set.candidates),
                "compatible": candidate_set.base_configuration_sha256 == base_hash,
                "compatibility_reason": (
                    "Exact baseline hash match"
                    if candidate_set.base_configuration_sha256 == base_hash
                    else "Package was built for a different baseline configuration"
                ),
                "path": path,
            })
    return results
