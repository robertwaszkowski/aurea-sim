from pathlib import Path

import pytest

from aureasim.semantic_enrichment import (
    build_task_operational_context,
    validate_enriched_label,
)


def _bpmn(tmp_path: Path) -> Path:
    path = tmp_path / "context.bpmn"
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="P" name="Application review">
    <bpmn:startEvent id="start" />
    <bpmn:userTask id="enter" name="Enter application data" />
    <bpmn:exclusiveGateway id="complete" />
    <bpmn:userTask id="approve" name="Approve decision" />
    <bpmn:endEvent id="end" />
    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="enter" />
    <bpmn:sequenceFlow id="f2" sourceRef="enter" targetRef="complete" />
    <bpmn:sequenceFlow id="f3" sourceRef="complete" targetRef="approve" />
    <bpmn:sequenceFlow id="f4" sourceRef="approve" targetRef="end" />
  </bpmn:process>
</bpmn:definitions>""",
        encoding="utf-8",
    )
    return path


def test_context_includes_nearest_task_across_gateway(tmp_path: Path):
    contexts = {item["task_id"]: item for item in build_task_operational_context(_bpmn(tmp_path))}
    assert contexts["enter"]["process_name"] == "Application review"
    assert contexts["enter"]["following_task_labels"] == ["Approve decision"]
    assert contexts["approve"]["preceding_task_labels"] == ["Enter application data"]


def test_contextual_labels_reject_duration_and_speed_cues():
    assert validate_enriched_label("Task_1", "Approve the prepared decision") == "Approve the prepared decision"
    assert validate_enriched_label("Task_2", "Calculate EUR amounts", "Calculate EUR amount") == "Calculate EUR amounts"
    with pytest.raises(ValueError, match="cue"):
        validate_enriched_label("Task_1", "Quick decision approval")
