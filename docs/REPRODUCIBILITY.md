# Software replay and verification

This repository contains the AureaSim software and compact public examples.
The empirical SoftwareX evaluation data and analysis scripts are maintained in
a separate immutable reproducibility capsule so operational and publication
material does not overload the product repository.

## Clean installation

```bash
conda env create -f environment.yml
conda activate aureasim
cd frontend
npm ci
npm run build
cd ..
```

## Offline replay

```bash
python run_experiment.py \
  --bpmn "examples/RES_Sales_Process.bpmn" \
  --config "examples/RES_Sales_Process_config.json" \
  --params "examples/RES_Sales_Process_base.json" \
  --outdir "results/res-sales-example"
```

Expected outputs include `Simulation_KPIs.csv`, `Scenario_Comparison.png`, and
a generated report. This command does not require `GEMINI_API_KEY`.

## Automated verification

```bash
python -m pytest
cd frontend
npm run build
```

The Python suite covers BPMN sanitization, simulation execution, API behavior,
parameter candidates, expert review, historical-task matching, configuration
validation, hybrid export, and the offline replay. The frontend build performs
Vue/TypeScript validation before producing the deployable bundle.

The suite also verifies the active-service-time guardrail, including rejection
of cycle-time outliers and deterministic handling of structurally automated
tasks. Live-AI outputs are intentionally not used by the offline replay test.

## Research capsule boundary

The external capsule freezes the research inputs, manifests, scripts, expected
outputs, and environment used for the manuscript evaluation. Its persistent
identifier is recorded in the article metadata and release notes rather than
duplicating those materials in Git history.
