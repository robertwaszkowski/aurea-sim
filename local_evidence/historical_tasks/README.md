# Historical-task evidence

AureaSim can propose a task-duration candidate from similar tasks executed in
other processes. This directory contains a **fully synthetic** working example:

```text
local_evidence/historical_tasks/example_historical_task_repository.json
```

The example demonstrates the file format and the frozen evidence thresholds.
It is not operational evidence and must not be used to justify production
parameters.

## Activate a repository

Keep the example unchanged and copy it only when testing the feature:

```powershell
Copy-Item local_evidence/historical_tasks/example_historical_task_repository.json `
  local_evidence/historical_tasks/historical_task_repository.json
```

For real local evidence, create `historical_task_repository.json` directly or
set `AUREASIM_HISTORICAL_REPOSITORY` to an absolute or repository-relative JSON
path:

```powershell
$env:AUREASIM_HISTORICAL_REPOSITORY = "D:\evidence\historical_tasks.json"
```

## Aurea process-miner connector

`aureasim.aurea_process_miner_connector` is the built-in connector for the
normalized, pseudonymised CSV export produced by the Aurea process miner.  It
requires three interface files: a process-alias manifest, chronological case
splits, and a unique source-activity-to-BPMN crosswalk.  The connector accepts
only `calibration` cases and positive `end_time - start_time` intervals marked
`include_in_duration_fit`; it writes the same portable JSON format used by all
other interfaces.

```powershell
python -m aureasim.aurea_process_miner_connector `
  --aliases research/process_mining/data/research_baselines/publication_alias_map.json `
  --splits research/process_mining/data/research_phase0/case_splits.csv `
  --crosswalk research/process_mining/data/research_phase0/bpmn_activity_crosswalk.csv `
  --data-root research/process_mining/data `
  --output software/local_evidence/historical_tasks/historical_task_repository.json
```

The generated file includes source hashes, counts, and an exclusion audit in
its `provenance` object.  Selection and holdout records are deliberately not
read into the repository.

## Source catalogue and remote packages

The active repository has a `source_catalog` array. Each item identifies one
process-mined source and its process version. `enabled` controls whether that
source may supply an exact reference or an historical-analogue donor. Sources
created by the local connector and sources imported from a remote package are
disabled by default; enable them explicitly in **Settings → Reference Data**.

Remote users should use the separate process-miner application to produce a
portable JSON package in this same format. The package must contain a unique
`source_catalog`, its corresponding `profiles`, calibration-only samples, and
provenance. Import it in AureaSim through `POST /api/reference-data/import`
with a JSON file. AureaSim rejects malformed packages, duplicate source IDs,
and profiles not declared by the package catalogue. It never receives source
database credentials.

The source-management API is also available to non-web clients:

```text
GET /api/reference-data
GET /api/reference-data/sources
PUT /api/reference-data/sources/{source_id}?enabled=true
POST /api/reference-data/import
```

The headless CLI accepts `--reference-repository PATH`. It validates that same
repository and uses only enabled sources when resolving eligible analogue
durations before simulation. The selected repository hash and applied source
evidence are recorded in baseline metadata.

The active repository and operational inputs are intentionally ignored by Git.
Only the synthetic example is published. Without an active file, AureaSim
remains fully usable and reports that historical evidence is not configured.

## From event data to repository records

Prepare task-level calibration evidence in the following order:

1. Retain completed human-task executions with valid chronological timestamps.
2. Calculate final-executor execution duration as `end_date - acq_date`.
   Queue, first-acquisition, release, delegation, escalation, and handoff delays
   are separate measures and must not be mixed into this duration.
3. Remove missing, zero/negative, or otherwise invalid intervals according to a
   documented rule. Preserve the unchanged source extract separately.
4. Assign cases chronologically to calibration, selection, and hold-out splits.
   Put **calibration durations only** in this repository. Selection and hold-out
   observations must remain unavailable to candidate construction.
5. Group valid calibration durations by process version and BPMN task.
6. Describe each task with its BPMN neighbours, role, process name, and stable
   domain-field identifiers. Use the same vocabulary across processes where
   concepts are equivalent.
7. Write one profile object per task and verify that `observation_count` equals
   the number of values in `calibration_samples_seconds`.
8. Search from a project and inspect the reported component scores and donor
   list before accepting a candidate.

Never include costs in this repository unless they are independently observed;
the current candidate builder uses execution durations only.

## Repository structure

The top-level object contains the matching policy and a `profiles` array. Keep
the published defaults unless a separately validated method justifies a policy
change.

### Historical Semantic Analogue Refinement (HSAR)

Set `"retrieval_strategy": "historical_semantic_analogue"` to use HSAR. Each
profile must then include ISO-8601 `observed_from` and `observed_to` fields.
HSAR accepts only donor evidence ending strictly before the target evidence
window begins. It ranks both an earlier version of the same logical process
and a semantically and structurally similar task from another process. It
never infers chronology from a version label, and it does not silently fall
back when time bounds are missing.

The standard cross-process strategy remains the default for legacy
repositories without observation windows.

| Field | Meaning |
|---|---|
| `format_version` | Must be `1`. |
| `weights` | Similarity weights for task semantics, BPMN context, role, and domain; values must sum to `1.0`. |
| `minimum_score` | Minimum weighted similarity for a donor task. |
| `minimum_donor_observations` | Minimum valid calibration executions for each donor. |
| `minimum_analogue_tasks` | Minimum number of qualifying donor tasks. |
| `minimum_process_families` | Minimum number of distinct `process_alias` values among donors. |
| `minimum_combined_executions` | Minimum combined donor observation count. |
| `maximum_results` | Maximum number of ranked donors retained. |
| `retrieval_strategy` | Omit or set to `cross_process_semantic` for the legacy policy; set to `historical_semantic_analogue` for HSAR. |
| `profiles` | Task descriptions and their calibration-only duration samples. |

Each profile entry has this form:

```json
{
  "profile": {
    "process_alias": "P01",
    "process_id": "stable-process-id",
    "process_version": "1",
    "task_id": "stable-bpmn-task-id",
    "task_name": "Verify application",
    "task_kind": "PROCESSSTEP",
    "parameter_family": "execution_duration_seconds",
    "unit": "seconds",
    "predecessor_labels": ["Register application"],
    "successor_labels": ["Approve application"],
    "role_label": "Case worker",
    "process_name": "Application handling",
    "domain_fields": ["application_id", "amount"],
    "observation_count": 40,
    "observed_from": "2025-01-01T00:00:00Z",
    "observed_to": "2025-05-31T23:59:59Z"
  },
  "calibration_samples_seconds": [240, 300, 360]
}
```

The shortened fragment above illustrates field meaning only; a real record must
contain exactly `observation_count` samples. Durations are positive seconds.
`process_id` and `task_id` must match the identifiers used by the corresponding
BPMN model. `process_alias` defines a process family for the diversity check.

A profile with zero observations may describe the current query task more
richly than BPMN labels alone. It cannot become a donor and its sample list must
be empty. Donor profiles must come from processes other than the target process;
AureaSim enforces this exclusion again during search.

## Validate before use

Run the loader against the file:

```powershell
python -c "from pathlib import Path; from aureasim.historical_repository import load_repository; p=Path(r'local_evidence/historical_tasks/example_historical_task_repository.json'); settings, records=load_repository(p); print(f'valid: {len(records)} profiles')"
```

Then run the focused tests:

```powershell
python -m pytest tests/test_historical_repository.py
```

Loading proves structural compatibility; it does not prove that task similarity
is meaningful or that the evidence is representative. Candidate acceptance
remains an expert decision and requires a recorded justification.

## Privacy and maintenance

- Use stable pseudonyms instead of employee, customer, or case identifiers.
- Do not store raw forms, comments, document contents, or personal data here.
- Record the extraction period, filtering rules, split boundaries, source-system
  version, and repository hash in your internal evidence documentation.
- Rebuild the repository when process definitions or work practices change.
- Keep hold-out observations separate so they can measure fidelity after
  candidate selection.
