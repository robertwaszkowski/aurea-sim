import os
import subprocess
import sys
import pytest

from aureasim.executor import _resolve_prosimos_bin

@pytest.mark.integration
def test_reviewer_replay_command_runs(tmp_path):
    """
    Smoke test to ensure the public offline replay command works.
    Uses subprocess to call run_experiment.py, simulating exactly what a user would do.
    """
    prosimos_bin = _resolve_prosimos_bin()
    if not prosimos_bin:
        pytest.skip("prosimos CLI not found. Skipping integration replay test.")

    bpmn_path = "examples/RES_Sales_Process.bpmn"
    config_path = "examples/RES_Sales_Process_config.json"
    params_path = "examples/RES_Sales_Process_base.json"
    out_dir = tmp_path / "results"

    # Verify that the test artifacts exist
    assert os.path.exists(bpmn_path), f"Test artifact not found: {bpmn_path}"
    assert os.path.exists(config_path), f"Test artifact not found: {config_path}"
    assert os.path.exists(params_path), f"Test artifact not found: {params_path}"

    cmd = [
        sys.executable, "run_experiment.py",
        "--bpmn", bpmn_path,
        "--config", config_path,
        "--params", params_path,
        "--outdir", str(out_dir)
    ]

    env = os.environ.copy()
    env["PROSIMOS_BIN"] = prosimos_bin
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)

    # Check for successful execution
    assert result.returncode == 0, f"Replay command failed with error: {result.stderr}"
    
    # Check that expected output files were generated
    if not os.path.exists(out_dir / "Simulation_KPIs.csv"):
        pytest.fail(f"Simulation_KPIs.csv not generated. Stdout: {result.stdout}\nStderr: {result.stderr}")
    assert os.path.exists(out_dir / "Scenario_Comparison.png")
    assert os.path.exists(out_dir / "Experiment_Report.docx")
