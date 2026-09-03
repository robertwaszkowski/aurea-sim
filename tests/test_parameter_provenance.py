import pytest
from pydantic import ValidationError

from aureasim.ai_generator import ResourceInstance, TaskResourceDetail, DistributionParam
from aureasim.ai_generator import apply_deterministic_resources
from aureasim.ai_generator import normalize_parameter_provenance
from aureasim.ai_generator import validate_parameter_provenance

def test_resource_instance_rejects_invalid_evidence_status():
    with pytest.raises(ValidationError):
        ResourceInstance(
            id="Auditor_1",
            name="Auditor_1",
            cost_per_hour=100,
            amount=1,
            calendar="Standard_Working_Hours",
            evidence_status="not_a_valid_status",
            source_urls=[],
            evidence_rationale="test",
        )

def test_task_resource_detail_rejects_invalid_evidence_status():
    with pytest.raises(ValidationError):
        TaskResourceDetail(
            resource_id="Auditor_1",
            distribution_name="norm",
            distribution_params=[
                DistributionParam(value=600),
                DistributionParam(value=120),
                DistributionParam(value=0),
                DistributionParam(value=9999999),
            ],
            evidence_status="not_a_valid_status",
            source_urls=[],
            evidence_rationale="test",
        )

def test_apply_deterministic_resources_preserves_cost_and_duration_provenance():
    semantics = {
        "tasks": [
            {
                "task_id": "Task_A",
                "role_id": "Auditor",
                "resource_instance_id": "Auditor_1",
            }
        ]
    }

    ai_data = {
        "resource_profiles": [
            {
                "id": "Auditor",
                "name": "Auditor",
                "resource_list": [
                    {
                        "id": "Auditor_1",
                        "name": "Auditor_1",
                        "cost_per_hour": 320,
                        "amount": 1,
                        "calendar": "Standard_Working_Hours",
                        "evidence_status": "grounded_confirmed",
                        "source_urls": ["https://example.com/auditor"],
                        "evidence_rationale": "Auditor cost from source.",
                    }
                ],
            }
        ],
        "task_resource_distribution": [
            {
                "task_id": "Task_A",
                "resources": [
                    {
                        "resource_id": "Wrong_Resource_1",
                        "distribution_name": "norm",
                        "distribution_params": [
                            {"value": 900},
                            {"value": 180},
                            {"value": 0},
                            {"value": 9999999},
                        ],
                        "evidence_status": "grounded_proxy",
                        "source_urls": ["https://example.com/task"],
                        "evidence_rationale": "Task duration proxied from source.",
                    }
                ],
            }
        ],
    }

    repaired = apply_deterministic_resources(ai_data, semantics)

    resource = repaired["resource_profiles"][0]["resource_list"][0]
    assert resource["id"] == "Auditor_1"
    assert resource["cost_per_hour"] == 320
    assert resource["evidence_status"] == "grounded_confirmed"
    assert resource["source_urls"] == ["https://example.com/auditor"]

    task_resource = repaired["task_resource_distribution"][0]["resources"][0]
    assert task_resource["resource_id"] == "Auditor_1"
    assert task_resource["distribution_params"][0]["value"] == 900
    assert task_resource["evidence_status"] == "grounded_proxy"
    assert task_resource["source_urls"] == ["https://example.com/task"]

def test_validate_parameter_provenance_requires_fields():
    ai_data = {
        "resource_profiles": [
            {
                "id": "Auditor",
                "resource_list": [
                    {
                        "id": "Auditor_1",
                        "cost_per_hour": 100,
                    }
                ],
            }
        ],
        "task_resource_distribution": [],
    }

    with pytest.raises(ValueError):
        validate_parameter_provenance(ai_data)


def test_normalize_parameter_provenance_downgrades_unsupported_grounding():
    ai_data = {
        "metadata": {},
        "resource_profiles": [{
            "resource_list": [{
                "id": "Auditor_1",
                "evidence_status": "grounded_confirmed",
                "source_urls": [],
                "evidence_rationale": "Model cited a source in the research summary.",
            }],
        }],
        "task_resource_distribution": [],
    }

    result = normalize_parameter_provenance(ai_data)
    resource = result["resource_profiles"][0]["resource_list"][0]

    assert resource["evidence_status"] == "heuristic_fallback"
    assert resource["source_urls"] == []
    assert len(result["metadata"]["parameter_provenance_normalization"]["corrections"]) == 1
