import os
import json
import pytest
from aureasim.sanitizer import auto_sanitize_bpmn

def test_sanitizer_behavior(tmp_path):
    # Create a dummy BPMN with all the edge cases
    bpmn_content = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_1">
  <bpmn:collaboration id="Collaboration_1">
    <bpmn:participant id="Participant_1" processRef="Process_1" />
    <bpmn:participant id="Participant_2" processRef="Process_2" />
    <bpmn:messageFlow id="Flow_msg" sourceRef="Task_1" targetRef="Task_2" />
  </bpmn:collaboration>

  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" />
    <bpmn:sequenceFlow id="Flow_From_Start" sourceRef="StartEvent_1" targetRef="Task_User" />

    <!-- Task conversion -->
    <bpmn:userTask id="Task_User" name="User Task" />
    <bpmn:sequenceFlow id="Flow_U_M" sourceRef="Task_User" targetRef="Task_Manual" />
    
    <bpmn:manualTask id="Task_Manual" name="Manual Task" />
    <bpmn:sequenceFlow id="Flow_M_S" sourceRef="Task_Manual" targetRef="Task_Service" />

    <bpmn:serviceTask id="Task_Service" name="Service Task" />
    <bpmn:sequenceFlow id="Flow_S_St" sourceRef="Task_Service" targetRef="Task_Standard" />
    
    <!-- Standard task -->
    <bpmn:task id="Task_Standard" name="Standard Task" />
    
    <!-- SubProcess Flattening -->
    <bpmn:sequenceFlow id="Flow_St_Sub" sourceRef="Task_Standard" targetRef="SubProcess_1" />
    <bpmn:subProcess id="SubProcess_1" name="Sub">
      <bpmn:startEvent id="SubStart" />
      <bpmn:task id="SubTask" name="Internal Task" />
      <bpmn:endEvent id="SubEnd" />
      <bpmn:sequenceFlow id="Flow_Sub_1" sourceRef="SubStart" targetRef="SubTask" />
      <bpmn:sequenceFlow id="Flow_Sub_2" sourceRef="SubTask" targetRef="SubEnd" />
    </bpmn:subProcess>
    
    <!-- External routing for SubProcess -->
    <bpmn:sequenceFlow id="Flow_Sub_End" sourceRef="SubProcess_1" targetRef="EndEvent_1" />
    
    <!-- Multiple End Events -->
    <bpmn:sequenceFlow id="Flow_To_End_2" sourceRef="Task_Standard" targetRef="EndEvent_2" />
    <bpmn:endEvent id="EndEvent_1" name="End 1" />
    <bpmn:endEvent id="EndEvent_2" name="End 2" />

    <!-- Boundary Event -->
    <bpmn:boundaryEvent id="Boundary_1" attachedToRef="SubProcess_1" />
  </bpmn:process>
</bpmn:definitions>
"""

    in_path = tmp_path / "test_input.bpmn"
    in_path.write_text(bpmn_content)

    params = {
        "task_resource_distribution": [
            {"task_id": "Task_User"},
            {"task_id": "Task_Standard"}
        ]
    }

    out_path = auto_sanitize_bpmn(str(in_path), str(tmp_path), params=params)
    report_path = tmp_path / "sanitizer_report.json"
    
    assert os.path.exists(out_path)
    assert os.path.exists(report_path)
    
    with open(out_path, "r") as f:
        sanitized_xml = f.read()

    with open(report_path, "r") as f:
        report = json.load(f)

    # 1. Message flows should be removed
    assert "bpmn:messageFlow" not in sanitized_xml
    assert any(mf["id"] == "Flow_msg" for mf in report["removed_message_flows"])
    
    # 2. Task conversions (userTask -> task, etc)
    assert "bpmn:userTask" not in sanitized_xml
    assert "id=\"Task_User\"" in sanitized_xml
    assert "bpmn:task id=\"Task_User\"" in sanitized_xml
    assert "bpmn:task id=\"Task_Manual\"" in sanitized_xml
    assert "bpmn:task id=\"Task_Service\"" in sanitized_xml
    
    # 3. Standard task left alone
    assert "bpmn:task id=\"Task_Standard\"" in sanitized_xml
    
    # 4. Multiple end events merged
    assert "id=\"EndEvent_1\"" in sanitized_xml
    assert "bpmn:endEvent id=\"EndEvent_2\"" not in sanitized_xml
    assert "targetRef=\"EndEvent_1\"" in sanitized_xml
    
    # 5. Subprocess flattening
    assert "bpmn:subProcess" not in sanitized_xml
    assert "id=\"SubTask\"" in sanitized_xml
    assert "targetRef=\"SubTask\"" in sanitized_xml
    assert "sourceRef=\"SubTask\"" in sanitized_xml
    assert any(sub["id"] == "SubProcess_1" for sub in report["flattened_subprocesses"])
    
    # 6. Boundary events removed
    assert "bpmn:boundaryEvent" not in sanitized_xml


def test_malformed_subprocess(tmp_path):
    bpmn_content = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_1">
    <bpmn:subProcess id="SubProcess_1">
      <bpmn:startEvent id="SubStart_1" />
      <bpmn:startEvent id="SubStart_2" />
      <bpmn:endEvent id="SubEnd" />
    </bpmn:subProcess>
  </bpmn:process>
</bpmn:definitions>
"""
    in_path = tmp_path / "malformed.bpmn"
    in_path.write_text(bpmn_content)

    with pytest.raises(ValueError, match="not well-structured"):
        auto_sanitize_bpmn(str(in_path), str(tmp_path))

def test_missing_start_end(tmp_path):
    bpmn_content = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_1">
    <bpmn:task id="Task_1" />
  </bpmn:process>
</bpmn:definitions>
"""
    in_path = tmp_path / "missing_events.bpmn"
    in_path.write_text(bpmn_content)

    with pytest.raises(ValueError, match="at least one startEvent and one endEvent"):
        auto_sanitize_bpmn(str(in_path), str(tmp_path))

def test_missing_task_params(tmp_path):
    bpmn_content = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_1">
    <bpmn:startEvent id="Start" />
    <bpmn:task id="Task_1" />
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="F1" sourceRef="Start" targetRef="Task_1" />
    <bpmn:sequenceFlow id="F2" sourceRef="Task_1" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
"""
    in_path = tmp_path / "valid.bpmn"
    in_path.write_text(bpmn_content)

    params = {
        "task_resource_distribution": [
            {"task_id": "Task_1"},
            {"task_id": "Task_Missing"}
        ]
    }

    with pytest.raises(ValueError, match="do not exist in the sanitized BPMN"):
        auto_sanitize_bpmn(str(in_path), str(tmp_path), params=params)
