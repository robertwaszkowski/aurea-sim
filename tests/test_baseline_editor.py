import copy

import pytest

from aureasim.baseline_editor import apply_baseline_update


@pytest.fixture
def baseline():
    return {
        "arrival_time_distribution": {
            "distribution_name": "expon",
            "distribution_params": [{"value": 0}, {"value": 604800}],
            "frequency": {"events": 1, "per_count": 1, "per_unit": "week"},
        },
        "resource_calendars": [{"id": "business"}],
        "resource_profiles": [{
            "id": "Installer",
            "name": "Installer",
            "resource_list": [{
                "id": "Installer_1",
                "name": "Installer 1",
                "amount": 1,
                "cost_per_hour": 40,
                "calendar": "business",
            }],
        }],
        "task_resource_distribution": [{
            "task_id": "Task_Install",
            "resources": [{
                "resource_id": "Installer_1",
                "distribution_name": "norm",
                "distribution_params": [
                    {"value": 3600}, {"value": 600}, {"value": 0}, {"value": 999999},
                ],
            }],
        }],
        "gateway_branching_probabilities": [{
            "gateway_id": "Gateway_1",
            "probabilities": [
                {"path_id": "Flow_A", "value": 0.5},
                {"path_id": "Flow_B", "value": 0.5},
            ],
        }],
    }


def test_updates_task_duration_without_mutating_input(baseline):
    original = copy.deepcopy(baseline)
    updated, _ = apply_baseline_update(
        baseline,
        "task_duration",
        "Task_Install",
        {"mean_minutes": 90, "stddev_minutes": 15},
    )
    params = updated["task_resource_distribution"][0]["resources"][0]["distribution_params"]
    assert params[0]["value"] == 5400
    assert params[1]["value"] == 900
    assert baseline == original


def test_resource_headcount_rebuilds_task_assignments(baseline):
    updated, _ = apply_baseline_update(
        baseline,
        "resource",
        "Installer",
        {"headcount": 2, "cost_per_hour": 55, "calendar": "business"},
    )
    profile = updated["resource_profiles"][0]
    assert [item["id"] for item in profile["resource_list"]] == ["Installer_1", "Installer_2"]
    resources = updated["task_resource_distribution"][0]["resources"]
    assert [item["resource_id"] for item in resources] == ["Installer_1", "Installer_2"]


def test_arrival_frequency_and_gateway_probabilities_are_validated(baseline):
    updated, _ = apply_baseline_update(
        baseline,
        "arrival",
        "arrival",
        {"events": 2, "per_count": 1, "per_unit": "week"},
    )
    assert updated["arrival_time_distribution"]["distribution_params"][1]["value"] == 302400

    with pytest.raises(ValueError, match="sum to 1"):
        apply_baseline_update(
            baseline,
            "gateway",
            "Gateway_1",
            {"probabilities": {"Flow_A": 0.8, "Flow_B": 0.8}},
        )
