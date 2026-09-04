"""Conservative gateway-path probability estimation from event-log traces.

Gateways normally have no event-log record.  This module therefore counts a
path only when a pair of consecutive, uniquely mapped activities proves that
the case crossed one particular exclusive gateway path.  Ambiguous paths,
parallelism, and unobservable gateway chains are deliberately not imputed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _walk_until_activity(
    start: str, graph: dict[str, list[str]], activity_ids: set[str],
    gateway_ids: set[str], *, reverse: bool,
) -> set[str]:
    """Find first mapped activity nodes, without crossing another gateway."""
    if start in activity_ids:
        return {start}
    found: set[str] = set()
    pending = list(graph.get(start, []))
    seen: set[str] = set()
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        if node in activity_ids:
            found.add(node)
            continue
        if node in gateway_ids:
            continue
        pending.extend(graph.get(node, []))
    return found


def infer_gateway_probabilities(
    bpmn_path: Path, traces: Iterable[Iterable[str]],
) -> dict[str, object]:
    """Estimate exclusive-gateway path probabilities from mapped activity traces.

    A trace is a chronologically ordered sequence of BPMN activity IDs.  The
    returned estimates are calibration evidence, not a completion of missing
    routes: only uniquely identifiable predecessor/path/successor triples are
    counted.
    """
    root = ET.parse(bpmn_path).getroot()
    process = next((node for node in root.iter() if _local(node.tag) == "process"), None)
    if process is None:
        raise ValueError("BPMN model has no process")
    nodes = {node.get("id", ""): _local(node.tag) for node in process.iter() if node.get("id")}
    activities = {node_id for node_id, kind in nodes.items() if kind in {
        "task", "userTask", "serviceTask", "manualTask", "sendTask", "receiveTask",
        "businessRuleTask", "scriptTask", "subProcess", "callActivity",
    }}
    exclusive_gateways = {node_id for node_id, kind in nodes.items() if kind == "exclusiveGateway"}
    forward: dict[str, list[str]] = defaultdict(list)
    backward: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for flow in process.iter():
        if _local(flow.tag) != "sequenceFlow":
            continue
        flow_id, source, target = flow.get("id", ""), flow.get("sourceRef", ""), flow.get("targetRef", "")
        if source and target:
            forward[source].append(target)
            backward[target].append(source)
            if source in exclusive_gateways:
                outgoing[source].append((flow_id, target))

    # An exclusive gateway with one outgoing flow is a join/merge, not a
    # branching decision and therefore has no probability parameter to infer.
    gateways = {gateway_id for gateway_id in exclusive_gateways if len(outgoing[gateway_id]) > 1}

    # (previous mapped activity, next mapped activity) -> unique gateway/path.
    transitions: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    paths_by_gateway: dict[str, list[str]] = defaultdict(list)
    for gateway_id in sorted(gateways):
        predecessors = _walk_until_activity(gateway_id, backward, activities, gateways, reverse=True)
        for path_id, target in outgoing[gateway_id]:
            paths_by_gateway[gateway_id].append(path_id)
            successors = _walk_until_activity(target, forward, activities, gateways, reverse=False)
            for predecessor in predecessors:
                for successor in successors:
                    transitions[(predecessor, successor)].add((gateway_id, path_id))

    counts: Counter[tuple[str, str]] = Counter()
    audit: Counter[str] = Counter()
    for trace in traces:
        observed = [activity for activity in trace if activity in activities]
        for previous, current in zip(observed, observed[1:]):
            candidates = transitions.get((previous, current), set())
            if len(candidates) == 1:
                counts[next(iter(candidates))] += 1
                audit["identified_transitions"] += 1
            elif candidates:
                audit["ambiguous_transitions"] += 1
            else:
                audit["unmatched_transitions"] += 1

    estimates = []
    for gateway_id, path_ids in sorted(paths_by_gateway.items()):
        total = sum(counts[(gateway_id, path_id)] for path_id in path_ids)
        if not total:
            continue
        estimates.append({
            "gateway_id": gateway_id,
            "observation_count": total,
            "probabilities": [
                {"path_id": path_id, "count": counts[(gateway_id, path_id)],
                 "value": counts[(gateway_id, path_id)] / total}
                for path_id in sorted(path_ids)
            ],
        })
    return {"gateway_probabilities": estimates, "audit": dict(sorted(audit.items()))}
