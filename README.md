# AureaSim

AureaSim is an AI-assisted framework for preparing, reviewing, executing, and
analyzing BPMN process simulations with the Prosimos engine. It combines a
Python/FastAPI backend, a Vue web interface, a terminal workflow, and a
headless runner.

- Version: **1.2.1**
- License: **GNU GPL v3.0**
- Python: **3.9-3.11**
Node.js: **20 or newer**

## What AureaSim provides

- BPMN sanitization and Prosimos-compatible parameter generation.
- Generic-label, semantically constrained, and web-grounded generation modes.
- Explicit parameter candidates with method, provenance, uncertainty,
  expected-error, measured-fidelity, and review metadata.
- Expert accept, edit, reject, and lock decisions with a hash-chained audit
  history.
- Optional local historical-task analogue search with conservative evidence
  thresholds.
- Baseline validation, candidate application, and immutable hybrid
  configuration export.
- Multi-scenario simulation, Activity-Based Costing, KPI analysis, charts, and
  DOCX/PDF/LaTeX reports.
- Web, interactive terminal, and headless interfaces.

Generated task durations are protected by a deterministic service-time
guardrail. Values above one working day are treated as likely queue, waiting,
or end-to-end cycle times and replaced by an auditable ten-minute human-task
prior. BPMN service/script tasks and tasks assigned to an authoritative System
role use a near-zero machine-service prior. Every correction is recorded in
`metadata.task_duration_stabilization_policy`; the original value is not
silently presented as grounded active execution time.

## Interface

![Parameter workflow](docs/assets/parameter_workflow_validation.png)

Additional screenshots are available under `docs/assets/screenshots/`.

## Quick start

### Prerequisites

- Conda, Miniconda, or a compatible Python 3.9-3.11 environment;
- Node.js 20 or newer for the web interface.

Clone the repository and run the platform launcher:

```bash
git clone https://github.com/robertwaszkowski/aurea-sim.git
cd aurea-sim
```

macOS/Linux:

```bash
./aureasim.sh
```

Windows:

```powershell
.\aureasim.bat
```

The launcher creates or reuses the `aureasim` Conda environment and offers the
terminal wizard or web dashboard.

For manual installation:

```bash
conda env create -f environment.yml
conda activate aureasim
cd frontend
npm ci
npm run build
cd ..
python server.py
```

Open `http://localhost:8000` after the production frontend build. During
frontend development, run `npm run dev` under `frontend/` and use
`http://localhost:3000`.

## Gemini API key

Live AI-assisted generation requires a Gemini API key. Offline examples and
review of existing projects do not.

macOS/Linux:

```bash
export GEMINI_API_KEY="your-key"
```

Windows PowerShell:

```powershell
$env:GEMINI_API_KEY = "your-key"
```

You may also copy `.env.example` to `.env` and set the key there. `.env` is
ignored by Git.

## Curated project gallery

The web dashboard includes three completed demonstration projects:

- **Incident Management** - compact IT-service baseline, peak-load, and
  recovery comparison;
- **Leave Request** - multi-role approval workflow with a visible capacity
  stress and recovery case;
- **RES Sales Process** - larger commercial workflow with baseline, peak,
  recovery, and cost-cutting scenarios.

New simulations create additional folders under `projects/`. Those folders are
local application state and are not committed.

## Headless example

```bash
python run_experiment.py \
  --bpmn "examples/RES_Sales_Process.bpmn" \
  --config "examples/RES_Sales_Process_config.json" \
  --params "examples/RES_Sales_Process_base.json" \
  --outdir "results/res-sales-example"
```

This replay does not contact an AI service.

If `--reference-repository` is supplied, the headless runner validates that
repository and applies only enabled historical analogues that satisfy the
frozen evidence thresholds. Without that option or an explicitly configured
`AUREASIM_HISTORICAL_REPOSITORY`, replay uses the supplied baseline unchanged.

## Parameter evidence

Opening **Baseline Parameters** automatically creates reviewable candidates
from the project's executable baseline. Each candidate carries its source,
method, confidence, transferable empirical error range when available, and
measured fidelity only when an independent reference exists. Users can retain
the active value, select another candidate, search historical analogues, or add
an expert alternative without destroying the original value.

Externally prepared candidate packages can still be imported from the
advanced section or placed below `local_evidence/candidate_packages/`. Configure another
discovery directory with `AUREASIM_CANDIDATE_PACKAGES_DIR`.

Historical-task analogue search is optional. Place a compatible repository at
`local_evidence/historical_tasks/historical_task_repository.json` or set
`AUREASIM_HISTORICAL_REPOSITORY`. Operational event logs and derived evidence
are deliberately not distributed with the software repository.

A fully synthetic working repository and instructions for transforming
calibration-only task executions into the required format are provided in
[local_evidence/historical_tasks/README.md](local_evidence/historical_tasks/README.md). The example illustrates
the feature but is never loaded automatically as operational evidence.

Reference Data in Settings shows the configured repository and its
process-mined source catalogue. Enable only the sources approved for the
current modelling task; disabled sources are excluded from automatic analogue
resolution in both the web app and the CLI. Remote contributors import data
through the separate process-miner workflow, which emits a portable
calibration-only JSON package. AureaSim validates and imports that package but
does not connect to its source database or retain database credentials.

See [the parameter workflow guide](docs/PARAMETER_WORKFLOW.md) for candidate
selection, expert review, confidence/fidelity interpretation, baseline
validation, and hybrid export.

The software replay procedure is documented in
[docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).

## Documentation

- [Installation](docs/INSTALLATION.md)
- [Parameter workflow](docs/PARAMETER_WORKFLOW.md)
- [Model settings and external-service variability](docs/MODEL_SETTINGS.md)
- [Software replay and verification](docs/REPRODUCIBILITY.md)
- [Known issues](docs/KNOWN_ISSUES.md)
- [Frontend development](frontend/README.md)

## Citation

Release metadata is provided in `CITATION.cff`. The software source snapshot
for this version is:

<https://github.com/robertwaszkowski/aurea-sim/releases/tag/v1.2.1>


## Support

Questions and reproducible issue reports: `robert.waszkowski@wat.edu.pl`.
