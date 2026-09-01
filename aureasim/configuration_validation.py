"""Structural validation shared by generated, calibrated, and hybrid configs."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping


def validate_parameter_references(
    bpmn: str | Path, params: Mapping[str, object]
) -> list[str]:
    """Return exact BPMN-reference errors without changing either input."""
    root = ET.parse(bpmn).getroot()
    elements = {
        str(element.get("id")): element
        for element in root.iter()
        if element.get("id")
    }
    flows = {
        identifier: element
        for identifier, element in elements.items()
        if element.tag.rsplit("}", 1)[-1] == "sequenceFlow"
    }
    errors: list[str] = []
    for assignment in params.get("task_resource_distribution", []):
        task_id = str(assignment.get("task_id") or "")
        if task_id not in elements:
            errors.append(f"unknown task_id: {task_id}")
    for gateway in params.get("gateway_branching_probabilities", []):
        gateway_id = str(gateway.get("gateway_id") or "")
        if gateway_id not in elements:
            errors.append(f"unknown gateway_id: {gateway_id}")
        for probability in gateway.get("probabilities", []):
            path_id = str(probability.get("path_id") or "")
            if path_id not in flows:
                errors.append(f"unknown gateway path_id: {gateway_id} -> {path_id}")
            elif str(flows[path_id].get("sourceRef") or "") != gateway_id:
                errors.append(
                    f"gateway path source mismatch: {gateway_id} -> {path_id}"
                )
    return errors
