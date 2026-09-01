# Expert-survey reference CSV

Use this optional CSV to attach an independent reference to candidates in a
project's **Parameter evidence and review** workspace. It evaluates values; it
never changes the baseline or replaces an expert-edit decision.

Required columns are:

```text
process_alias,parameter_family,entity_key,reference_value,reference_type,source
```

Optional columns are `reference_min`, `reference_max`, `unit`, and `notes`.
Use `expert_survey_reference` as `reference_type`. Parameter families use
`execution_duration_seconds` and `resource_cost_per_hour`. `entity_key` must
match the BPMN task ID/name or resource ID/name shown by AureaSim.

The completed research workbook can be converted with:

```powershell
.venv\Scripts\python.exe tools\export_expert_survey_references.py INPUT.xlsx OUTPUT.csv
```

After uploading the CSV in the web workspace, a matching candidate displays an
error against the labelled expert-survey reference. A project with no matching
survey or process-mining reference continues to show **Not measured**; a
method-level expected-error range is not measured fidelity.
