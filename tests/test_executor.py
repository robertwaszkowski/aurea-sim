from pathlib import Path

from aureasim import executor
import pytest


def test_resolve_prosimos_beside_active_python(monkeypatch, tmp_path):
    scripts_dir = tmp_path / "Scripts"
    scripts_dir.mkdir()
    python_exe = scripts_dir / "python.exe"
    prosimos_exe = scripts_dir / "prosimos.exe"
    python_exe.touch()
    prosimos_exe.touch()

    monkeypatch.delenv("PROSIMOS_BIN", raising=False)
    monkeypatch.setattr(executor.shutil, "which", lambda _name: None)
    monkeypatch.setattr(executor.sys, "executable", str(python_exe))
    monkeypatch.setattr(executor.os, "name", "nt")

    assert Path(executor._resolve_prosimos_bin()) == prosimos_exe


def test_resolve_prosimos_prefers_explicit_configuration(monkeypatch):
    monkeypatch.setenv("PROSIMOS_BIN", r"C:\\tools\\prosimos.exe")

    assert executor._resolve_prosimos_bin() == r"C:\\tools\\prosimos.exe"


def test_zero_resource_allocation_is_rejected_instead_of_silently_coerced():
    scenario = {
        "name": "Installer_Absence",
        "resource_allocations": {"Installer": 0},
    }
    base_config = {
        "resource_profiles": [{"id": "Installer", "resource_list": []}],
    }

    with pytest.raises(ValueError, match="allocates 0 resources"):
        executor._validate_scenario_resource_allocations(scenario, base_config)


def test_unknown_resource_profile_allocation_is_rejected():
    scenario = {
        "name": "Typo",
        "resource_allocations": {"Instaler": 1},
    }
    base_config = {
        "resource_profiles": [{"id": "Installer", "resource_list": []}],
    }

    with pytest.raises(ValueError, match="unknown resource profile 'Instaler'"):
        executor._validate_scenario_resource_allocations(scenario, base_config)


def test_legacy_role_id_punctuation_and_case_are_resolved():
    scenario = {
        "name": "Legacy",
        "resource_allocations": {"Eco_Advisor": 2},
    }
    base_config = {
        "resource_profiles": [{"id": "eco_Advisor", "resource_list": []}],
    }

    assert executor._validate_scenario_resource_allocations(scenario, base_config) == {
        "eco_Advisor": 2,
    }
