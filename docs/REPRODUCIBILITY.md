# Software replay and verification

This repository contains the AureaSim software and compact public examples.
The empirical SoftwareX evaluation data and analysis scripts are maintained in
a separate immutable reproducibility capsule so operational and publication
material does not overload the product repository.

## Verified Docker installation and replay

Docker is the recommended clean-environment route for reviewers. From the
`software/` directory, build the complete web application and Python runtime:

```bash
docker build --tag aureasim:1.3.0 .
```

Run the bundled offline RES Sales replay. The command requires neither a
Gemini key nor network access after the image has been built. On Windows
PowerShell, use:

```powershell
docker run --rm `
  -v "${PWD}\docker-review-results:/output" `
  aureasim:1.3.0 `
  python run_experiment.py `
    --bpmn examples/RES_Sales_Process.bpmn `
    --config examples/RES_Sales_Process_config.json `
    --params examples/RES_Sales_Process_base.json `
    --outdir /output
```

The host directory `docker-review-results/` contains the sanitized BPMN,
scenario logs, `Simulation_KPIs.csv`, `Scenario_Comparison.png`, XLSX, DOCX,
PDF, LaTeX source, and `sanitizer_report.json`. To start the web interface:

```bash
docker run --rm --name aureasim-review -p 8000:8000 aureasim:1.3.0
```

Open `http://localhost:8000`. The bundled Incident Management, Leave Request,
and RES Sales demos use fixed, executable scenarios; offline mode does not
contact an AI service.

## Clean installation without Docker

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

The Code Ocean capsule rebuilds the frozen research evidence; it is not the
interactive product container. Thus, `bash run` in Code Ocean verifies the
paper-facing tables and figures, while the Docker procedure above verifies
clean installation and execution of AureaSim itself.
