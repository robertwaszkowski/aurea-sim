from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .converter import ConversionError, Metadata, convert_definition


REQUIRED_CSV_COLUMNS = {
    "process_definition_id",
    "process_id",
    "process_version",
    "process_name",
    "combined_definition_xml",
}


def _allow_large_csv_fields() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def _read_rows(path: Path) -> List[Dict[str, str]]:
    _allow_large_csv_fields()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or ())
            missing = REQUIRED_CSV_COLUMNS - columns
            if missing:
                raise ConversionError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
            return list(reader)
    except OSError as exc:
        raise ConversionError(f"Cannot read CSV {path}: {exc}") from exc


def _metadata(row: Dict[str, str]) -> Metadata:
    return Metadata(
        process_id=row.get("process_id") or None,
        process_version=row.get("process_version") or None,
        process_name=row.get("process_name") or None,
        process_definition_id=row.get("process_definition_id") or None,
    )


def _select_row(
    rows: Iterable[Dict[str, str]],
    process_id: Optional[str],
    process_version: Optional[str],
    definition_id: Optional[str],
) -> Dict[str, str]:
    selected = []
    for row in rows:
        if process_id is not None and row.get("process_id") != process_id:
            continue
        if process_version is not None and row.get("process_version") != process_version:
            continue
        if definition_id is not None and row.get("process_definition_id") != definition_id:
            continue
        selected.append(row)
    if not selected:
        raise ConversionError("No CSV row matches the supplied process selectors.")
    if len(selected) > 1:
        raise ConversionError(
            f"The source contains {len(selected)} matching rows. Supply --process-id, "
            "--process-version, or --definition-id to select exactly one."
        )
    return selected[0]


def _definition_from_source(args: argparse.Namespace) -> tuple[str, Metadata, str]:
    source = args.source.resolve()
    if not source.is_file():
        raise ConversionError(f"Source file does not exist: {source}")
    if source.suffix.lower() == ".csv":
        row = _select_row(
            _read_rows(source),
            args.process_id,
            args.process_version,
            args.definition_id,
        )
        xml_text = row.get("combined_definition_xml") or ""
        if not xml_text.strip():
            raise ConversionError("Selected CSV row has an empty combined_definition_xml field.")
        return xml_text, _metadata(row), str(source)
    try:
        xml_text = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConversionError(f"Cannot read XML {source}: {exc}") from exc
    return (
        xml_text,
        Metadata(
            process_id=args.process_id,
            process_version=args.process_version,
            process_definition_id=args.definition_id,
        ),
        str(source),
    )


def _default_data_root() -> Path:
    return Path(__file__).resolve().parents[3] / "processmining_data"


def _dataset_source(dataset: str, data_root: Path) -> Path:
    supplied = Path(dataset)
    candidates = []
    if supplied.exists():
        candidates.append(supplied)
    candidates.append(data_root / dataset)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
        if candidate.is_dir():
            direct_manifest = candidate / "manifest.json"
            if candidate.name == "process_models" and direct_manifest.is_file():
                return direct_manifest.resolve()
            model_manifest = candidate / "process_models" / "manifest.json"
            if model_manifest.is_file():
                return model_manifest.resolve()
            csv_path = candidate / "internal" / "process_definitions_source_internal.csv"
            if csv_path.is_file():
                return csv_path.resolve()
    raise ConversionError(
        f"Cannot resolve dataset {dataset!r}. Supply a dataset directory/CSV or use --data-root."
    )


def _read_model_manifest(path: Path) -> List[Dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConversionError(f"Cannot read process-model manifest {path}: {exc}") from exc
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ConversionError(f"Process-model manifest has no models array: {path}")
    rows = []
    for ordinal, item in enumerate(models, 1):
        if not isinstance(item, dict):
            raise ConversionError(f"Process-model manifest entry {ordinal} is not an object.")
        filename = item.get("file")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ConversionError(f"Process-model manifest entry {ordinal} has an unsafe file name.")
        model_path = path.parent / filename
        try:
            model_bytes = model_path.read_bytes()
            xml_text = model_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ConversionError(f"Cannot read extracted process model {model_path}: {exc}") from exc
        expected_hash = item.get("sha256")
        actual_hash = hashlib.sha256(model_bytes).hexdigest()
        if not isinstance(expected_hash, str) or actual_hash != expected_hash:
            raise ConversionError(f"Extracted process model hash does not match its manifest: {model_path}")
        rows.append({
            "process_definition_id": str(item.get("process_definition_id") or ""),
            "process_id": str(item.get("process_id") or ""),
            "process_version": str(item.get("process_version") or ""),
            "process_name": str(item.get("process_name") or ""),
            "combined_definition_xml": xml_text,
            "source_label": str(model_path),
            "definition_format": str(item.get("definition_format") or "AuGraph"),
        })
    return rows


def _output_name(row: Dict[str, str], ordinal: int) -> str:
    raw = "_".join(
        value for value in (
            row.get("process_id") or "process",
            row.get("process_version") or "version",
            row.get("process_definition_id") or str(ordinal),
        ) if value
    )
    safe = "".join(character if character.isalnum() or character in "._-" else "_" for character in raw)
    return safe.strip("._-") or f"process_{ordinal}"


def _print_summary(report: Dict[str, object], output: Path) -> None:
    summary = report["summary"]
    print(
        f"Converted to {output} "
        f"({summary['convertedConnectors']} connectors, "
        f"{summary['convertedConnections']} flows, "
        f"{summary['warnings']} warnings)."
    )


def process_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert one old-Aurea AuGraph definition.")
    parser.add_argument("--source", type=Path, required=True, help="AuGraph XML or extractor CSV")
    parser.add_argument("--output", type=Path, required=True, help="New, empty output directory")
    parser.add_argument("--process-id", help="Process selector/identity")
    parser.add_argument("--process-version", help="Process-version selector/identity")
    parser.add_argument("--definition-id", help="Process-definition row selector")
    return parser


def source_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert every definition in an extractor dataset.")
    parser.add_argument("dataset", help="Dataset name, directory, or process-definition CSV")
    parser.add_argument("--data-root", type=Path, default=_default_data_root(), help="Directory containing named datasets")
    parser.add_argument("--output", type=Path, required=True, help="Destination root for per-process directories")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-process output paths")
    return parser


def process_main(argv: Optional[List[str]] = None) -> int:
    args = process_parser().parse_args(argv)
    try:
        xml_text, metadata, label = _definition_from_source(args)
        report = convert_definition(xml_text, args.output.resolve(), metadata, label)
        _print_summary(report, args.output.resolve())
        return 0
    except ConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def source_main(argv: Optional[List[str]] = None) -> int:
    args = source_parser().parse_args(argv)
    try:
        dataset_source = _dataset_source(args.dataset, args.data_root.resolve())
        from_models = dataset_source.name == "manifest.json" and dataset_source.parent.name == "process_models"
        rows = _read_model_manifest(dataset_source) if from_models else _read_rows(dataset_source)
        already_bpmn = [row for row in rows if row.get("definition_format") == "BPMN"] if from_models else []
        if already_bpmn:
            rows = [row for row in rows if row.get("definition_format") != "BPMN"]
            print(f"Skipped {len(already_bpmn)} definitions already stored as BPMN.")
        if not rows:
            if from_models and already_bpmn:
                return 0
            raise ConversionError(f"Dataset contains no process definitions: {dataset_source}")
        output_root = args.output.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        for ordinal, row in enumerate(rows, 1):
            xml_text = row.get("combined_definition_xml") or ""
            if not xml_text.strip():
                raise ConversionError(f"Row {ordinal} has an empty combined_definition_xml field.")
            destination = output_root / _output_name(row, ordinal)
            source_label = row.get("source_label") or f"{dataset_source}#row={ordinal}"
            report = convert_definition(xml_text, destination, _metadata(row), source_label)
            if not args.quiet:
                _print_summary(report, destination)
        source_kind = "extracted process models" if from_models else "definitions"
        print(f"Converted {len(rows)} {source_kind} from {dataset_source}.")
        return 0
    except ConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
