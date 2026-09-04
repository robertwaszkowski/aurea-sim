from pathlib import Path

from aureasim.gateway_probability_mining import infer_gateway_probabilities


def test_counts_only_unambiguous_exclusive_gateway_paths(tmp_path: Path):
    bpmn = tmp_path / "model.bpmn"
    bpmn.write_text('''<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"><process id="p">
    <task id="A"/><exclusiveGateway id="G"/><task id="B"/><task id="C"/>
    <sequenceFlow id="f1" sourceRef="A" targetRef="G"/><sequenceFlow id="f2" sourceRef="G" targetRef="B"/><sequenceFlow id="f3" sourceRef="G" targetRef="C"/>
    </process></definitions>''', encoding="utf-8")
    result = infer_gateway_probabilities(bpmn, [["A", "B"], ["A", "B"], ["A", "C"], ["B"]])
    gateway = result["gateway_probabilities"][0]
    assert gateway["gateway_id"] == "G"
    assert gateway["observation_count"] == 3
    assert gateway["probabilities"] == [
        {"path_id": "f2", "count": 2, "value": 2 / 3},
        {"path_id": "f3", "count": 1, "value": 1 / 3},
    ]


def test_does_not_infer_when_gateway_paths_rejoin_before_an_activity(tmp_path: Path):
    bpmn = tmp_path / "model.bpmn"
    bpmn.write_text('''<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"><process id="p">
    <task id="A"/><exclusiveGateway id="G"/><exclusiveGateway id="J"/><task id="B"/>
    <sequenceFlow id="f1" sourceRef="A" targetRef="G"/><sequenceFlow id="f2" sourceRef="G" targetRef="J"/><sequenceFlow id="f3" sourceRef="G" targetRef="J"/><sequenceFlow id="f4" sourceRef="J" targetRef="B"/>
    </process></definitions>''', encoding="utf-8")
    result = infer_gateway_probabilities(bpmn, [["A", "B"]])
    assert result["gateway_probabilities"] == []
