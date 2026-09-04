"""Build portable historical-task evidence from Aurea process-miner exports.

The connector consumes pseudonymised normalized ``events.csv`` files plus a
case-split and BPMN-activity crosswalk.  It writes only calibration-split,
positive active execution durations to the product's interface-neutral
historical-task repository format.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from aureasim.gateway_probability_mining import infer_gateway_probabilities


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip()) if value else None
    except ValueError:
        return None


def _truth(value: str | None) -> bool:
    return str(value).casefold() in {"true", "1", "yes"}


def build_repository(*, aliases_path: Path, splits_path: Path, crosswalk_path: Path,
                     data_root: Path, output_path: Path, bpmn_root: Path | None = None) -> dict:
    """Build calibration-only duration evidence and, when supplied, gateway evidence."""
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    by_process = {
        (row["source"], row["process_id"], row["process_version"]): alias
        for alias, row in aliases.items()
    }
    splits: dict[tuple[str, str, str, str], str] = {}
    with splits_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["source"], row["process_id"], row["process_version"])
            if key in by_process:
                splits[(*key, row["case_id"])] = row["split"]
    crosswalk: dict[tuple[str, str, str, str], dict[str, str]] = {}
    with crosswalk_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["source"], row["process_id"], row["process_version"])
            if key in by_process and row["mapping_status"] == "mapped_unique":
                crosswalk[(*key, row["source_activity_id"])] = row

    samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    roles: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    kinds: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    names: dict[tuple[str, str], str] = {}
    audit: Counter[str] = Counter()
    traces: dict[str, dict[str, list[tuple[datetime, str]]]] = defaultdict(lambda: defaultdict(list))
    sources = sorted({key[0] for key in by_process})
    source_hashes = {str(path): _sha256(path) for path in (aliases_path, splits_path, crosswalk_path)}
    for source in sources:
        events_path = data_root / source / "anonymized" / "events.csv"
        source_hashes[str(events_path)] = _sha256(events_path)
        with events_path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                key = (source, row["process_id"], row["process_version"])
                alias = by_process.get(key)
                if not alias or splits.get((*key, row["case_id"])) != "calibration":
                    continue
                mapping = crosswalk.get((*key, row["source_activity_id"]))
                if mapping is not None:
                    stamp = _time(row.get("start_time", "")) or _time(row.get("end_time", ""))
                    if stamp is not None:
                        traces[alias][row["case_id"]].append((stamp, mapping["bpmn_activity_id"]))
                if mapping is None or not _truth(row.get("include_in_duration_fit")):
                    audit["excluded_unmapped_or_not_fit"] += 1
                    continue
                start, end = _time(row.get("start_time", "")), _time(row.get("end_time", ""))
                if start is None or end is None or end <= start:
                    audit["excluded_invalid_or_nonpositive"] += 1
                    continue
                task_key = (alias, mapping["bpmn_activity_id"])
                samples[task_key].append((end - start).total_seconds())
                roles[task_key][row.get("resource_role", "")] += 1
                kinds[task_key][row.get("activity_kind", "PROCESSSTEP")] += 1
                names[task_key] = mapping["bpmn_activity_name"]
                audit["included_calibration_executions"] += 1

    profiles = []
    for (alias, task_id), values in sorted(samples.items()):
        source, process_id, version = aliases[alias]["source"], aliases[alias]["process_id"], aliases[alias]["process_version"]
        profiles.append({"profile": {
            "process_alias": alias, "process_id": process_id, "process_version": version,
            "task_id": task_id, "task_name": names[(alias, task_id)],
            "task_kind": kinds[(alias, task_id)].most_common(1)[0][0],
            "parameter_family": "execution_duration_seconds", "unit": "seconds",
            "predecessor_labels": [], "successor_labels": [],
            "role_label": roles[(alias, task_id)].most_common(1)[0][0],
            "process_name": process_id, "domain_fields": [], "observation_count": len(values),
        }, "calibration_samples_seconds": values})
    gateway_estimates = {}
    if bpmn_root is not None:
        for alias, case_events in sorted(traces.items()):
            bpmn_path = bpmn_root / f"{alias}.bpmn"
            if not bpmn_path.is_file():
                audit["gateway_skipped_missing_bpmn"] += 1
                continue
            evidence = infer_gateway_probabilities(
                bpmn_path, ([activity for _, activity in sorted(events)] for events in case_events.values())
            )
            gateway_estimates[alias] = evidence
            for name, value in evidence["audit"].items():
                audit[f"gateway_{name}"] += value

    payload = {
        "format_version": 1,
        "description": "Calibration-only operational evidence generated by Aurea process-miner connector.",
        "evidence_scope": "chronological_calibration_only",
        "source_connector": "aurea_process_miner_normalized_csv_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "minimum_score": 0.7,
        "weights": {"semantic": 0.55, "bpmn_context": 0.20, "role": 0.15, "domain": 0.10},
        "minimum_donor_observations": 30, "minimum_analogue_tasks": 3,
        "minimum_process_families": 2, "minimum_combined_executions": 100,
        "maximum_results": 5, "profiles": profiles,
        "gateway_probability_estimates": gateway_estimates,
        "source_catalog": [
            {"source_id": alias, "display_name": alias, "enabled": False,
             "process_id": row["process_id"], "process_version": row["process_version"],
             "connector": "aurea_process_miner_normalized_csv_v1"}
            for alias, row in sorted(aliases.items())
        ],
        "provenance": {"source_sha256": source_hashes, "audit": dict(sorted(audit.items()))},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"profiles": len(profiles), "samples": sum(len(item["calibration_samples_seconds"]) for item in profiles), "gateways": sum(len(item["gateway_probabilities"]) for item in gateway_estimates.values()), "output": str(output_path), "audit": payload["provenance"]["audit"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--splits", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bpmn-root", type=Path, help="Directory containing <process_alias>.bpmn models for gateway-path mining")
    args = parser.parse_args()
    print(json.dumps(build_repository(aliases_path=args.aliases, splits_path=args.splits, crosswalk_path=args.crosswalk, data_root=args.data_root, output_path=args.output, bpmn_root=args.bpmn_root), indent=2))


if __name__ == "__main__":
    main()
