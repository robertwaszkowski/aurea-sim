# Aurea definition converter

This self-contained Python tool converts an old Aurea `AuGraph` definition into
the independently useful artifacts that can be confirmed from local new-Aurea
evidence:

- BPMN 2.0 XML with Aurea 2024 extension elements;
- a new-Aurea `.form` JSON document;
- a plain JSON Schema and separate UI-options JSON;
- a structured preservation file for legacy task/field visibility rules;
- an old-to-new ID map and machine-readable conversion report;
- an untouched copy of the source AuGraph for lossless local retention;
- a deterministic `project.zip` accepted by the current Modeler backend's
  project-import contract.

It has no runtime dependencies beyond Python 3.9 or newer. The ZIP contract is
derived from the current `aurea-modeler-backend`: project files are identified
by extension and `.project.json` supplies project name and version metadata.

## Usage

Convert an XML file or one selected row from an extractor CSV:

```powershell
python convert_process.py --source C:\path\definition.xml --output C:\path\converted
python convert_process.py --source C:\path\process_definitions_source_internal.csv --process-id ID --process-version 1.0 --output C:\path\converted
```

Convert every definition in an extractor dataset. The dataset argument may be
a dataset directory, its `process_models/` directory, its CSV file, or a dataset
name such as `bm` when `--data-root` points at `processmining_data`. When a
dataset contains `process_models/manifest.json`, those individual extracted
models are preferred:

```powershell
python convert_source.py bm --data-root D:\Work\VSCodeProjects\aurea-sim\processmining_data --output .\work\bm
```

Extracted `.augraph.xml` process models are complete combined definitions and
include `ProcessData`, so diagrams and forms are converted together. Definitions
whose manifest marks them as BPMN are already in the target diagram format and
are skipped by the old-Aurea converter.

The destination may contain confidential names, scripts, and source XML. Keep
it in an access-controlled location. This folder's `work/` directory is ignored
by Git for local trials.

## Evidence-based mapping (milestone 1)

The BM source contains 20 combined AuGraph documents in namespace
`http://xmlns.tecna.pl/xml/ns/diagram`. Its observed connector subtypes map as
follows:

| Old subtype | Confirmed old meaning | Milestone-1 target |
| --- | --- | --- |
| 301 | start event | `bpmn:startEvent` |
| 302 | end event | `bpmn:endEvent` |
| 401 | data-driven XOR gateway | `bpmn:exclusiveGateway` |
| 600 | abstract task | `bpmn:task` |
| 604 | script-calling task | `bpmn:task` with procedure extensions |
| 101 | annotation | `bpmn:textAnnotation` |
| 102 | label | `bpmn:textAnnotation` with a conversion warning |

Old `SEQ_FLOW` connections become BPMN sequence flows. All observed BM
connection endpoints resolve to connector `hashCode` values. Old connector and
connection coordinates become BPMN DI shapes and waypoints. Role indices become
stable role IDs; task owners refer to those IDs through
`aurea:responsibleRef`. Legacy absolute canvas coordinates are shifted as one
diagram so the smallest coordinate starts at 100 while relative layout remains
unchanged. Connector procedures become
`aurea:groovyScript` references with uppercase event names. Procedure names and
arguments are retained in those references. The legacy `source` attribute has
no slot in the new moddle type and remains in `source.augraph.xml`, with an
explicit diagnostic; event names not observed in the new sample are likewise
reported as unverified.

Process-data fields are converted recursively. Scalar types are mapped to JSON
Schema types, while old labels and basic widget choices become schema `label`
and `layout` annotations used by the new frontend's `vue3-schema-forms` runtime.
Legacy layouts, actions, scripts, access rules, option metadata, and unsupported
field types are retained in `x-aurea-legacy` annotations and reported rather
than silently discarded.

Task-specific visibility is stored in AuGraph connector `params/param` entries.
The converter preserves every observed attribute in `legacy-visibility.json`
and links each source connector to its generated BPMN ID. It does not yet apply
these rules to the deployable form because no equivalent new-Aurea runtime
contract has been confirmed. RACI is different: the old application loads and
saves it separately from the model data (with task code, role code, and the R,
A, C, and I flags), so it is not present in the current extractor definition
CSV and cannot be reconstructed from AuGraph alone.

## Output contract

Each converted definition gets one output directory:

```text
process.bpmn
process.form
process.schema.json
process.ui-options.json
legacy-visibility.json
id-map.json
conversion-report.json
source.augraph.xml
.project.json
project.zip
```

Only `.project.json`, `process.bpmn`, and `process.form` are included in the
deployable ZIP. Diagnostic files and the confidential source AuGraph remain
outside it. ZIP entries have fixed timestamps, ordering, permissions, and
compression settings so identical input produces identical bytes.

Outputs are deterministic for identical input and metadata. The report contains
source identity, artifact hashes, validation results, warning/error codes, and
unsupported XML locations. A conversion exits nonzero if XML/JSON structure or
BPMN references fail validation.

## Principal uncertainties

- The available new BPMN was extracted inside an `AuGraph` wrapper; new-modeler
  templates establish that authored `.bpmn` files use standard BPMN
  `definitions`, which this converter follows.
- Legacy global process procedures have no confirmed process-level target in the
  current Aurea moddle schema, so they are retained only in the report/source.
- Legacy visual layout and dynamic field actions do not have a fully evidenced
  one-to-one representation in the current form builder.
- The visibility matrix is preserved but not activated in `process.form` until
  the corresponding new-Aurea runtime representation is confirmed.
- Full RACI conversion requires a supplementary old-database export; the
  existing definition CSV contains only AuGraph/process-data XML.
- Actual procedure bodies are external to AuGraph. `Proc@source` identifies
  `database`, `script`, or `java`; it is not source code. References are retained
  but no placeholder executable files are fabricated.
- Runtime semantics for legacy procedure events `ACQUIRE_TL`, `DELEGATE_TL`,
  `INTERCEPT_TL`, `LOAD`, and `POST` remain unverified.

Run the sanitized tests with:

```powershell
python -m unittest discover -s tests -v
```
