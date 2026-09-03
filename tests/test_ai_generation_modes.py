import json
from pathlib import Path

import pytest

from aureasim import ai_generator


SIMPLE_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start" />
    <bpmn:task id="Task_PrepareOffer" name="Prepare Offer (Sales Specialist)" />
    <bpmn:endEvent id="EndEvent_1" name="End" />
  </bpmn:process>
</bpmn:definitions>
"""


class DummyResponse:
    text = json.dumps(
        {
            "metadata": {
                "methodology": "Heuristic BPMN semantic estimation",
                "sources": [],
                "source_urls": [],
                "rationale": "Values are estimated from task and role labels.",
            },
            "arrival_time": {
                "frequency": {
                    "events": 1,
                    "per_count": 1,
                    "per_unit": "week",
                    "rationale": "One case per week for test purposes.",
                }
            },
            "resource_profiles": [
                {
                    "id": "Sales_Specialist",
                    "name": "Sales_Specialist",
                    "resource_list": [
                        {
                            "id": "Sales_Specialist_1",
                            "name": "Sales_Specialist_1",
                            "cost_per_hour": 80,
                            "amount": 1,
                            "calendar": "Standard_Working_Hours",
                        }
                    ],
                }
            ],
            "task_resource_distribution": [
                {
                    "task_id": "Task_PrepareOffer",
                    "resources": [
                        {
                            "resource_id": "Sales_Specialist_1",
                            "distribution_name": "norm",
                            "distribution_params": [
                                {"value": 3600},
                                {"value": 600},
                                {"value": 0},
                                {"value": 9999999},
                            ],
                        }
                    ],
                }
            ],
            "gateway_branching_probabilities": [],
        }
    )


CAPTURED_PROMPTS = []


class DummyModels:
    def generate_content(self, *args, **kwargs):
        if "contents" in kwargs:
            CAPTURED_PROMPTS.append(kwargs["contents"])
        elif len(args) >= 2:
            CAPTURED_PROMPTS.append(args[1])
        return DummyResponse()


class DummyClient:
    def __init__(self, api_key):
        self.models = DummyModels()


class DummyGenAI:
    Client = DummyClient


def test_heuristic_generation_mode_skips_web_research(monkeypatch, tmp_path):
    CAPTURED_PROMPTS.clear()
    bpmn_path = tmp_path / "process.bpmn"
    bpmn_path.write_text(SIMPLE_BPMN, encoding="utf-8")

    monkeypatch.setattr(ai_generator, "genai", DummyGenAI)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("_research_with_search should not be called in heuristic mode")

    monkeypatch.setattr(ai_generator, "_research_with_search", fail_if_called)

    out_path = ai_generator.generate_base_prosimos_json(
        str(bpmn_path),
        api_key="dummy",
        industry_context="General business process, Poland",
        generation_mode="heuristic",
    )

    assert CAPTURED_PROMPTS
    prompt = CAPTURED_PROMPTS[0]
    assert "HEURISTIC GENERATION MODE" in prompt
    assert "Task_PrepareOffer" in prompt
    assert "Estimate costs, durations, arrival rates, and gateway probabilities" in prompt
    assert "{research_section}" not in prompt
    assert "{json.dumps(semantics, indent=2)}" not in prompt
    assert "{parameter_instruction}" not in prompt

    base_params = json.loads(Path(out_path).read_text(encoding="utf-8"))
    research_log = json.loads((tmp_path / "research_log.json").read_text(encoding="utf-8"))

    assert research_log["mode"] == "heuristic"
    assert research_log["success"] is False
    assert research_log["urls"] == []
    assert research_log["grounding_mode"] == "heuristic"
    assert research_log["grounding_status"] == "disabled_by_experiment"

    assert base_params["metadata"]["grounding_mode"] == "heuristic"
    assert base_params["metadata"]["grounding_status"] == "disabled_by_experiment"
    assert base_params["metadata"]["source_urls"] == []
    assert "Grounding intentionally disabled" in base_params["metadata"]["sources"][0]


def test_invalid_generation_mode_is_rejected(tmp_path):
    bpmn_path = tmp_path / "process.bpmn"
    bpmn_path.write_text(SIMPLE_BPMN, encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported generation_mode"):
        ai_generator.generate_base_prosimos_json(
            str(bpmn_path),
            api_key="dummy",
            generation_mode="not-a-mode",
        )


def test_frozen_evidence_mode_skips_live_search(monkeypatch, tmp_path):
    CAPTURED_PROMPTS.clear()
    bpmn_path = tmp_path / "process.bpmn"
    bpmn_path.write_text(SIMPLE_BPMN, encoding="utf-8")
    monkeypatch.setattr(ai_generator, "genai", DummyGenAI)
    monkeypatch.setattr(
        ai_generator,
        "_research_with_search",
        lambda *args, **kwargs: pytest.fail("live search must not run for frozen evidence"),
    )

    out_path = ai_generator.generate_base_prosimos_json(
        str(bpmn_path),
        api_key="dummy",
        generation_mode="frozen_evidence",
        frozen_evidence={
            "brief": "Task_PrepareOffer has a reviewed 120-second proxy benchmark.",
            "urls": ["https://example.com/benchmark"],
            "sources": ["Reviewed benchmark"],
        },
    )

    assert "Locally frozen, reviewed evidence packet" in CAPTURED_PROMPTS[0]
    research_log = json.loads((tmp_path / "research_log.json").read_text(encoding="utf-8"))
    assert research_log["grounding_mode"] == "frozen_evidence"
    assert research_log["grounding_status"] == "reviewed_packet"
    assert json.loads(Path(out_path).read_text(encoding="utf-8"))["metadata"]["grounding_mode"] == "frozen_evidence"


def test_scenario_schema_rejects_zero_resource_count():
    with pytest.raises(ValueError):
        ai_generator.RoleAllocation(role_id="Installer", count=0)
