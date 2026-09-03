import json
import os
from unittest.mock import patch, MagicMock
from aureasim.ai_generator import generate_base_prosimos_json

def test_ai_fallback_warning_metadata(tmp_path):
    # Mock a minimal valid BPMN
    bpmn_path = tmp_path / "test.bpmn"
    bpmn_path.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_1">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:task id="Task_1" name="Dummy Task" />
  </bpmn:process>
</bpmn:definitions>""")

    dummy_json = {
        "metadata": {
            "methodology": "Heuristic",
            "sources": [],
            "source_urls": [],
            "rationale": "Values are heuristic."
        },
        "arrival_time": {
            "frequency": {"events": 1.0, "per_count": 1.0, "per_unit": "day", "rationale": "Test"}
        },
        "resource_profiles": [{"id": "R1", "name": "Role 1", "resource_list": [{"id": "R1_1", "name": "R1_1", "cost_per_hour": 10, "amount": 1, "calendar": "Standard"}]}],
        "task_resource_distribution": [{"task_id": "Task_1", "resources": [{"resource_id": "R1_1", "distribution_name": "norm", "distribution_params": [{"value": 10}, {"value": 1}, {"value": 0}, {"value": 99}]}]}],
        "gateway_branching_probabilities": []
    }

    mock_generate_response = MagicMock()
    mock_generate_response.text = json.dumps(dummy_json)

    with patch("aureasim.ai_generator._research_with_search") as mock_research, \
         patch("aureasim.ai_generator.generate_with_fallback") as mock_generate, \
         patch("aureasim.ai_generator.genai"):
         
        mock_research.return_value = {
            "brief": "",
            "urls": [],
            "sources": [],
            "success": False,
            "fallback_note": "Web search unavailable. Values are heuristic estimates based on BPMN semantic analysis only."
        }
        
        mock_generate.return_value = mock_generate_response

        # Call function
        out_path = generate_base_prosimos_json(str(bpmn_path), api_key="fake-key")

    # Assert outputs
    assert os.path.exists(out_path)
    with open(out_path, "r") as f:
        result = json.load(f)

    # Acceptance criteria
    assert result["metadata"]["source_urls"] == [], "source_urls should be empty"
    assert len(result["metadata"]["sources"]) == 1
    assert "Web search unavailable" in result["metadata"]["sources"][0]
    assert "heuristic estimates" in result["metadata"]["sources"][0]
