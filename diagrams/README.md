# Public BPMN example library

This folder is the BPMN library shown in **Run Simulation**. It contains
English-language, non-customer-specific models that can be used to explore the
AureaSim workflow.

| Group | Models | Purpose |
| --- | --- | --- |
| Core examples | `Incident Management`, `Leave Request`, `Contract Conclusion Process` | Small, generic processes for a quick simulation. |
| Renewable-energy examples | `RES Installation Process`, `RES Sales Process` | The complete example projects included with AureaSim. |
| Sanitised evaluation models | `Business Travel Delegation Request`, `Cost Invoice Workflow`, `Milk Support Application` | English-labelled BPMN structure retained from three process-mining evaluation models. |

The three sanitised evaluation models retain their control flow and task IDs,
but have no event logs, operational values, proprietary forms, scripts,
descriptions, or legacy package metadata. Consequently, they allow reviewers
to run and inspect AureaSim, but they cannot reproduce the private
process-mining evaluation or infer customer operations from this folder.

To add a personal BPMN model, use **Upload from device** in the application.
Uploaded files are intentionally ignored by Git unless someone explicitly adds
them to the public example library.
