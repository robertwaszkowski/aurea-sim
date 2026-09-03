from aureasim.ai_generator import stabilize_task_durations


def _payload(mean: float) -> dict:
    return {
        "metadata": {},
        "task_resource_distribution": [{
            "task_id": "Task_Authorize",
            "resources": [{
                "resource_id": "Approver_1",
                "distribution_name": "norm",
                "distribution_params": [
                    {"value": mean},
                    {"value": mean * 0.2},
                    {"value": 0},
                    {"value": 9999999},
                ],
                "evidence_status": "grounded_extrapolated",
                "source_urls": ["https://example.test/approval-cycle"],
                "evidence_rationale": "Entry-to-approval median is 5.4 days.",
            }],
        }],
    }


def _semantics(role: str = "Approver") -> dict:
    return {"tasks": [{
        "task_id": "Task_Authorize",
        "task_name": "Authorization",
        "clean_task_name": "Authorization",
        "role_id": role,
        "resolved_role": role,
    }]}


def test_cycle_time_outlier_is_replaced_and_audited():
    result = stabilize_task_durations(_payload(466_560), _semantics())
    resource = result["task_resource_distribution"][0]["resources"][0]
    policy = result["metadata"]["task_duration_stabilization_policy"]

    assert [item["value"] for item in resource["distribution_params"]] == [
        600, 120.0, 0, 9999999
    ]
    assert resource["evidence_status"] == "heuristic_fallback"
    assert resource["source_urls"] == []
    assert policy["corrections"][0]["original_mean_seconds"] == 466_560
    assert policy["corrections"][0]["replacement_mean_seconds"] == 600


def test_plausible_active_service_time_is_preserved():
    result = stabilize_task_durations(_payload(900), _semantics())
    resource = result["task_resource_distribution"][0]["resources"][0]

    assert resource["distribution_params"][0]["value"] == 900
    assert result["metadata"]["task_duration_stabilization_policy"]["corrections"] == []


def test_system_task_uses_shorter_deterministic_fallback():
    result = stabilize_task_durations(_payload(90_000), _semantics("System"))
    resource = result["task_resource_distribution"][0]["resources"][0]

    assert [item["value"] for item in resource["distribution_params"]] == [
        0.02, 0.01, 0.001, 1.0
    ]
    assert resource["evidence_status"] == "structural_value"


def test_system_task_overrides_a_plausible_ai_duration():
    result = stabilize_task_durations(_payload(300), _semantics("System SAP"))
    resource = result["task_resource_distribution"][0]["resources"][0]
    correction = result["metadata"]["task_duration_stabilization_policy"]["corrections"][0]

    assert resource["distribution_params"][0]["value"] == 0.02
    assert resource["evidence_status"] == "structural_value"
    assert correction["original_mean_seconds"] == 300
    assert correction["replacement_mean_seconds"] == 0.02


def test_script_task_overrides_ai_duration_without_a_system_role():
    semantics = _semantics("Integration")
    semantics["tasks"][0]["bpmn_task_type"] = "scriptTask"
    result = stabilize_task_durations(_payload(300), semantics)

    assert result["task_resource_distribution"][0]["resources"][0]["distribution_params"][0]["value"] == 0.02


def test_explicit_external_wait_overrides_ai_duration():
    semantics = _semantics("Operator")
    semantics["tasks"][0]["task_class"] = "external_wait"
    result = stabilize_task_durations(_payload(300), semantics)
    resource = result["task_resource_distribution"][0]["resources"][0]

    assert resource["distribution_params"][0]["value"] == 0.02
    assert resource["evidence_status"] == "structural_value"
    assert "external-wait" in result["metadata"]["task_duration_stabilization_policy"]["corrections"][0]["reason"]


def test_short_transaction_replaces_minutes_scale_estimate_with_seconds_prior():
    semantics = _semantics("Approver")
    semantics["tasks"][0]["task_class"] = "short_transaction"
    result = stabilize_task_durations(_payload(600), semantics, fallback_seed=7)
    resource = result["task_resource_distribution"][0]["resources"][0]
    correction = result["metadata"]["task_duration_stabilization_policy"]["corrections"][0]

    assert 1 <= resource["distribution_params"][0]["value"] <= 60
    assert resource["distribution_params"][1]["value"] == 7.5
    assert resource["evidence_status"] == "heuristic_fallback"
    assert correction["original_mean_seconds"] == 600
    # Short-task fallbacks are bounded and reproducible for a given seed, but
    # are intentionally not a universal fixed duration.
    assert 1 <= correction["replacement_mean_seconds"] <= 60
    assert correction["replacement_mean_seconds"] != 15


def test_short_transaction_preserves_seconds_scale_estimate():
    semantics = _semantics("Approver")
    semantics["tasks"][0]["task_class"] = "short_transaction"
    result = stabilize_task_durations(_payload(45), semantics)

    assert result["task_resource_distribution"][0]["resources"][0]["distribution_params"][0]["value"] == 45
    assert result["metadata"]["task_duration_stabilization_policy"]["corrections"] == []


def test_financial_short_transaction_uses_its_wider_semantic_policy():
    semantics = _semantics("Approver")
    semantics["tasks"][0]["task_class"] = "short_transaction"
    semantics["tasks"][0]["duration_policy"] = {
        "id": "financial_approval", "minimum_seconds": 30,
        "fallback_seconds": 90, "maximum_seconds": 180, "std_seconds": 30,
    }
    result = stabilize_task_durations(_payload(600), semantics, fallback_seed=7)
    resource = result["task_resource_distribution"][0]["resources"][0]

    assert 30 <= resource["distribution_params"][0]["value"] <= 180
    assert resource["distribution_params"][1]["value"] == 30.0
