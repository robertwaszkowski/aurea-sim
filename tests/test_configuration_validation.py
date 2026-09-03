from pathlib import Path

from aureasim.configuration_validation import validate_parameter_references


def test_validation_checks_gateway_flow_identity_and_source(tmp_path: Path):
    bpmn = tmp_path / "p.bpmn"
    bpmn.write_text(
        '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">'
        '<process id="p"><exclusiveGateway id="g"/><exclusiveGateway id="g2"/>'
        '<task id="t"/><sequenceFlow id="f" sourceRef="g2" targetRef="t"/>'
        '</process></definitions>', encoding="utf-8",
    )
    params = {
        "task_resource_distribution": [{"task_id": "missing", "resources": []}],
        "gateway_branching_probabilities": [{
            "gateway_id": "g", "probabilities": [
                {"path_id": "f", "value": 0.5},
                {"path_id": "typo", "value": 0.5},
            ],
        }],
    }
    assert validate_parameter_references(bpmn, params) == [
        "unknown task_id: missing",
        "gateway path source mismatch: g -> f",
        "unknown gateway path_id: g -> typo",
    ]
