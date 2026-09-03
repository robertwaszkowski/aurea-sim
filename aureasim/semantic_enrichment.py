"""Auditable BPMN-context support for semantic task-label enrichment.

The module deliberately describes *what a task is*, not how long it should
take.  Duration class and duration policy remain independent outputs of
``role_resolver``.  This separation lets a reviewer inspect and approve a
clearer operational label without leaking an estimated duration into a
generation experiment.
"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from aureasim.role_resolver import get_elements_by_local_name, resolve_task_roles


TASK_LOCAL_NAMES = {
    "task", "userTask", "serviceTask", "scriptTask", "receiveTask",
    "sendTask", "manualTask",
}
PROHIBITED_MEASURE_CUE = re.compile(
    r"(?:\d|\b(?:second|seconds|minute|minutes|hour|hours|day|days|week|weeks|month|months|"
    r"sekund\w*|minut\w*|godzin\w*|dni\w*|tygodni\w*|miesi(?:ą|a)c\w*|PLN|EUR|USD|%|percent|"
    r"quick|rapid|long)\b)",
    re.IGNORECASE,
)


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _nearest_task_labels(
    start_id: str,
    graph: dict[str, list[str]],
    task_labels: dict[str, str],
) -> list[str]:
    """Return adjacent operational task labels, crossing gateways/events.

    Traversal stops after the first task layer.  It is therefore contextual
    enough to disambiguate an activity while avoiding a whole-process summary.
    """
    visited = {start_id}
    queue: deque[str] = deque(graph.get(start_id, []))
    found: list[str] = []
    while queue and len(found) < 4:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        if node_id in task_labels:
            label = task_labels[node_id].strip()
            if label:
                found.append(label)
            continue
        queue.extend(graph.get(node_id, []))
    return found


def build_task_operational_context(bpmn_path: str | Path) -> list[dict[str, object]]:
    """Extract task-local BPMN context for reviewable semantic enrichment.

    Returned records retain the original label and stable task ID.  Role and
    neighboring-task information are contextual evidence only: a caller must
    not turn them into a duration claim.
    """
    path = Path(bpmn_path)
    root = ET.parse(path).getroot()
    resolved = resolve_task_roles(path)
    task_labels = {
        task_id: str(info["clean_task_name"])
        for task_id, info in resolved.items()
    }
    forward: dict[str, list[str]] = defaultdict(list)
    backward: dict[str, list[str]] = defaultdict(list)
    for flow in get_elements_by_local_name(root, "sequenceFlow"):
        source, target = flow.get("sourceRef"), flow.get("targetRef")
        if source and target:
            forward[source].append(target)
            backward[target].append(source)

    process_names = [
        element.get("name", "").strip()
        for element in get_elements_by_local_name(root, "process")
        if element.get("name", "").strip()
    ]
    process_name = process_names[0] if process_names else ""
    contexts: list[dict[str, object]] = []
    for task_id, info in resolved.items():
        contexts.append({
            "task_id": task_id,
            "original_label": info["clean_task_name"],
            "responsible_role": info["role_name"],
            "bpmn_task_type": info["bpmn_task_type"],
            "process_name": process_name,
            "preceding_task_labels": _nearest_task_labels(task_id, backward, task_labels),
            "following_task_labels": _nearest_task_labels(task_id, forward, task_labels),
        })
    return contexts


def semantic_enrichment_prompt(contexts: list[dict[str, object]]) -> str:
    """Build the model prompt for labels that clarify meaning but not effort."""
    import json

    return f"""
You are preparing reviewable operational labels for a BPMN process simulation.

For every task, propose a short, clearer, self-contained operational label in
the SAME LANGUAGE as its original label. Improve meaning using the local BPMN
context (process name, adjacent activities, gateways implied by the flow, and
role only when it disambiguates the activity). Do not add a role merely to make
the label longer.

Strict rules:
1. Preserve every task_id exactly and return one result per supplied task.
2. Describe the operational action and object; do not estimate performance.
3. Do not introduce duration, speed, workload, quantity, cost, frequency,
   benchmark, external fact, or mined information. In particular, do not use
   words such as quick, rapid, long, or time units.
4. Do not change process logic, task type, or responsibility.
5. Do not use technical IDs as labels. Retain an already clear label rather
   than inventing unsupported details.

Return JSON only in this exact shape:
{{"labels":[{{"task_id":"...","enriched_label":"..."}}]}}

TASK CONTEXT:
{json.dumps(contexts, ensure_ascii=False, indent=2)}
"""


def validate_enriched_label(task_id: str, label: str, original_label: str = "") -> str:
    """Validate a label without forbidding information already in the source.

    A task named ``Calculate EUR amounts`` must be allowed to retain ``EUR``.
    The safeguard rejects only a newly introduced measurement or speed cue,
    which is the source of outcome leakage in an enrichment experiment.
    """
    cleaned = str(label or "").strip()
    if not cleaned or len(cleaned) > 240:
        raise ValueError(f"Invalid enriched label for {task_id}")
    original = str(original_label or "").casefold()
    introduced_cues = [
        match.group(0) for match in PROHIBITED_MEASURE_CUE.finditer(cleaned)
        if match.group(0).casefold() not in original
    ]
    if introduced_cues:
        raise ValueError(
            f"Prohibited newly introduced measurement/speed cue for {task_id}: {introduced_cues!r}"
        )
    if cleaned.casefold() in {task_id.casefold(), task_id.replace("_", " ").casefold()}:
        raise ValueError(f"Technical-ID label returned for {task_id}")
    return cleaned
