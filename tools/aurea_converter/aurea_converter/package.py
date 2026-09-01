from __future__ import annotations

import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping, Optional


METADATA_FILENAME = ".project.json"
SUPPORTED_EXTENSIONS = {
    ".bpmn",
    ".form",
    ".groovy",
    ".txt",
    ".md",
    ".xml",
    ".mjml",
    ".json",
}
REQUIRED_PROJECT_FILES = {METADATA_FILENAME, "process.bpmn", "process.form"}
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class PackageError(RuntimeError):
    """Raised when a generated project archive violates the backend contract."""


def project_metadata(name: str, version: str) -> Dict[str, Any]:
    """Create non-null metadata accepted by ImportProject on current backend master."""
    return {
        "name": name,
        "displayName": {},
        "description": {},
        "version": version,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_project_zip(
    destination: Path,
    metadata_path: Path,
    project_files: Mapping[str, Path],
) -> None:
    """Write a deterministic archive matching ExportProject/ProjectZipExtractor."""
    entries = {METADATA_FILENAME: metadata_path, **dict(project_files)}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            archive.writestr(_zip_info(name), entries[name].read_bytes(), compresslevel=9)


def _is_suspicious(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized.rstrip("/"))
    return path.is_absolute() or ".." in path.parts or not normalized.rstrip("/")


def validate_project_zip(path: Path) -> Dict[str, Any]:
    """Mirror the current backend's import-relevant ZIP and extension checks."""
    errors = []
    metadata: Optional[Dict[str, Any]] = None
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                errors.append(f"Duplicate ZIP entries: {', '.join(duplicates)}")
            bad_crc = archive.testzip()
            if bad_crc:
                errors.append(f"CRC validation failed for {bad_crc}.")
            for name in names:
                if _is_suspicious(name):
                    errors.append(f"Suspicious or unsupported ZIP path: {name}")
                    continue
                if name.endswith("/"):
                    continue
                filename = PurePosixPath(name.replace("\\", "/")).name
                if filename == METADATA_FILENAME:
                    if name != METADATA_FILENAME:
                        errors.append(f"{METADATA_FILENAME} must be at the ZIP root.")
                    continue
                if filename != ".gitignore" and PurePosixPath(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
                    errors.append(f"Backend does not support project file extension: {name}")
            missing = sorted(REQUIRED_PROJECT_FILES - set(names))
            if missing:
                errors.append(f"Missing required project entries: {', '.join(missing)}")
            if METADATA_FILENAME in names:
                try:
                    metadata = json.loads(archive.read(METADATA_FILENAME).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"Invalid {METADATA_FILENAME}: {exc}")
                if metadata is not None:
                    if not isinstance(metadata, dict):
                        errors.append(f"{METADATA_FILENAME} must contain a JSON object.")
                    else:
                        if not isinstance(metadata.get("name"), str) or not metadata["name"].strip():
                            errors.append("Project metadata name must be a non-empty string.")
                        if not isinstance(metadata.get("displayName"), dict):
                            errors.append("Project metadata displayName must be a JSON object.")
                        if not isinstance(metadata.get("description"), dict):
                            errors.append("Project metadata description must be a JSON object.")
                        if not isinstance(metadata.get("version"), str) or not metadata["version"].strip():
                            errors.append("Project metadata version must be a non-empty string.")
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"Invalid ZIP archive: {exc}")
        names = []
    return {
        "valid": not errors,
        "errors": errors,
        "entries": sorted(names),
        "metadata": metadata,
        "backendContract": {
            "metadataFilename": METADATA_FILENAME,
            "fileTypesInferredFromExtensions": True,
        },
    }
