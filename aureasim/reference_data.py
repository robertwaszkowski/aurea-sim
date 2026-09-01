"""Shared reference-data configuration and validation for every AureaSim interface."""
from __future__ import annotations

import hashlib
import os
import json
from pathlib import Path
from typing import Any

from aureasim.historical_repository import load_repository


def configured_repository_path(base_dir: Path) -> Path:
    configured = os.getenv("AUREASIM_HISTORICAL_REPOSITORY", "").strip()
    path = Path(configured).expanduser() if configured else base_dir / "local_evidence" / "historical_tasks" / "historical_task_repository.json"
    return (path if path.is_absolute() else base_dir / path).resolve()


def repository_status(base_dir: Path) -> dict[str, object]:
    path = configured_repository_path(base_dir)
    result: dict[str, object] = {"path": str(path), "configured": path.exists(), "valid": False}
    if not path.exists():
        return result
    try:
        payload, records = load_repository(path)
    except (OSError, ValueError) as exc:
        return {**result, "error": str(exc)}
    result.update({
        "valid": True,
        "format_version": payload["format_version"],
        "evidence_scope": payload.get("evidence_scope", "unspecified"),
        "source_connector": payload.get("source_connector", "external_repository"),
        "profiles": len(records),
        "calibration_samples": sum(len(samples) for _, samples in records),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
    return result


def source_catalog(path: Path) -> list[dict[str, object]]:
    payload, records = load_repository(path)
    counts: dict[str, int] = {}
    for profile, samples in records:
        counts[profile.process_alias] = counts.get(profile.process_alias, 0) + len(samples)
    catalog = payload.get("source_catalog") or [
        {"source_id": alias, "display_name": alias, "enabled": True}
        for alias in sorted(counts)
    ]
    return [{**item, "calibration_samples": counts.get(str(item["source_id"]), 0)} for item in catalog]


def set_source_enabled(path: Path, source_id: str, enabled: bool) -> list[dict[str, object]]:
    payload, _ = load_repository(path)
    catalog = payload.get("source_catalog")
    if catalog is None:
        raise ValueError("Legacy repository has no editable source catalogue")
    match = next((item for item in catalog if item.get("source_id") == source_id), None)
    if match is None:
        raise ValueError(f"Unknown reference source: {source_id}")
    match["enabled"] = bool(enabled)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return source_catalog(path)


def import_reference_package(path: Path, package: dict) -> list[dict[str, object]]:
    """Merge a validated remote package; incoming sources are always disabled."""
    if package.get("format_version") != 1 or not isinstance(package.get("profiles"), list):
        raise ValueError("Unsupported reference package format")
    incoming = package.get("source_catalog") or []
    if not incoming:
        raise ValueError("Reference package has no source catalogue")
    payload, _ = load_repository(path)
    catalog = payload.setdefault("source_catalog", [])
    existing = {str(item["source_id"]): item for item in catalog}
    incoming_ids = {str(item.get("source_id", "")) for item in incoming}
    if "" in incoming_ids or any(source_id in existing for source_id in incoming_ids):
        raise ValueError("Package contains a duplicate or invalid source ID")
    profiles = package["profiles"]
    if any(str(item.get("profile", {}).get("process_alias", "")) not in incoming_ids for item in profiles):
        raise ValueError("Every imported profile must belong to a declared source")
    for item in incoming:
        catalog.append({**item, "enabled": False, "imported": True})
    payload.setdefault("profiles", []).extend(profiles)
    payload.setdefault("import_history", []).append({"source_ids": sorted(incoming_ids), "package_sha256": hashlib.sha256(json.dumps(package, sort_keys=True).encode()).hexdigest()})
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return source_catalog(path)


def apply_eligible_historical_analogues(
    baseline: dict[str, Any], *, repository_path: Path, project_path: Path,
    process_alias: str, process_id: str, process_version: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Apply only evidence-qualified analogue durations and audit every choice."""
    from aureasim.candidate_application import apply_candidate_to_baseline
    from aureasim.historical_repository import candidate_from_search, search_repository

    updated = baseline
    applied: list[dict[str, str]] = []
    for assignment in baseline.get("task_resource_distribution", []):
        task_id = str(assignment.get("task_id") or "")
        if not task_id:
            continue
        search = search_repository(
            repository_path=repository_path, project_path=project_path, task_id=task_id,
            process_alias=process_alias, process_id=process_id, process_version=process_version,
        )
        if not search["sufficient"]:
            continue
        candidate = candidate_from_search(search, repository_path)
        updated, _, _ = apply_candidate_to_baseline(updated, candidate)
        applied.append({"task_id": task_id, "candidate_id": candidate.candidate_id})
    metadata = updated.setdefault("metadata", {})
    metadata["reference_data_resolution"] = {
        "repository": str(repository_path), "repository_sha256": hashlib.sha256(repository_path.read_bytes()).hexdigest(),
        "method": "eligible_historical_analogue_only", "applied": applied,
    }
    return updated, applied
