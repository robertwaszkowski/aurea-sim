import pytest

from aureasim.candidate_application import active_candidate_ids, apply_candidate_to_baseline
from aureasim.parameter_candidates import DistributionSpec, ExportCompatibility
from tests.test_parameter_candidates import candidate


def baseline():
    return {
        "metadata": {},
        "arrival_time_distribution": {
            "distribution_name": "expon",
            "distribution_params": [{"value": 0}, {"value": 300}],
        },
        "task_resource_distribution": [{
            "task_id": "task",
            "resources": [{
                "resource_id": "worker_1",
                "distribution_name": "norm",
                "distribution_params": [{"value": 60}, {"value": 10}],
            }],
        }],
    }


def test_task_candidate_replaces_executable_distribution_and_records_source():
    item = candidate()
    updated, previous, representation = apply_candidate_to_baseline(baseline(), item)
    resource = updated["task_resource_distribution"][0]["resources"][0]
    assert previous["resources"][0]["distribution_name"] == "norm"
    assert resource["distribution_name"] == "lognorm"
    assert resource["candidate_id"] == item.candidate_id
    assert representation["used_fallback"] is False
    assert active_candidate_ids(updated) == [item.candidate_id]


def test_declared_prosimos_fallback_is_used_for_discrete_candidate():
    discrete = DistributionSpec(
        distribution_name="empirical_discrete",
        discrete_mass_points=[{"value": 0, "probability": 1}],
        fit_method="empirical",
    )
    fallback = DistributionSpec(
        distribution_name="norm",
        distribution_params=[10, 2, 0, 100],
        fit_method="documented_fallback",
    )
    item = candidate(
        distribution=discrete,
        export_compatibility=[ExportCompatibility(
            target="prosimos_task_duration_1.2.4",
            supported=False,
            reason="Discrete values are unsupported.",
            fallback_distribution=fallback,
        )],
    )
    updated, _, representation = apply_candidate_to_baseline(baseline(), item)
    assert updated["task_resource_distribution"][0]["resources"][0]["distribution_name"] == "norm"
    assert representation["used_fallback"] is True


def test_diagnostic_candidate_cannot_be_applied():
    item = candidate(parameter_family="queue_wait_seconds", scalar_value=30, distribution=None)
    with pytest.raises(ValueError, match="diagnostic evidence"):
        apply_candidate_to_baseline(baseline(), item)


def test_resource_cost_candidate_updates_matching_resource():
    data = baseline()
    data["resource_profiles"] = [{
        "id": "worker",
        "resource_list": [{"id": "worker_1", "cost_per_hour": 20, "amount": 1}],
    }]
    item = candidate(
        parameter_family="resource_cost_per_hour",
        entity_id="worker_1",
        unit="currency/hour",
        scalar_value=35,
        distribution=None,
    )
    updated, previous, representation = apply_candidate_to_baseline(data, item)
    resource = updated["resource_profiles"][0]["resource_list"][0]
    assert previous["cost_per_hour"] == 20
    assert resource["cost_per_hour"] == 35
    assert resource["cost_per_hour_candidate_id"] == item.candidate_id
    assert representation == {"scalar_value": 35.0, "field": "cost_per_hour"}


def test_gateway_probability_candidate_updates_matching_path():
    data = baseline()
    data["gateway_branching_probabilities"] = [{
        "gateway_id": "Gateway_1",
        "probabilities": [{"path_id": "Flow_yes", "value": 0.5}],
    }]
    item = candidate(
        parameter_family="gateway_probability",
        entity_id="Flow_yes",
        unit="probability",
        scalar_value=0.7,
        distribution=None,
    )
    updated, previous, representation = apply_candidate_to_baseline(data, item)
    path = updated["gateway_branching_probabilities"][0]["probabilities"][0]
    assert previous["value"] == 0.5
    assert path["value"] == 0.7
    assert path["candidate_id"] == item.candidate_id
    assert representation == {"scalar_value": 0.7, "field": "value"}
