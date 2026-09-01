# Known issues and operational limits

- Live AI and web-grounded outputs may change when external models, search
  results, or APIs change.
- Prosimos 1.2.4 does not natively execute every statistically fitted duration
  family. AureaSim preserves the fitted evidence and uses an explicitly
  recorded compatible execution representation where required.
- Historical analogue search requires a user-supplied local historical-task
  repository. The software does not distribute operational logs.
- Candidate discovery only auto-attaches an exact baseline-hash match. Other
  packages must not be silently applied.
- Updating an active baseline invalidates previously generated simulation
  results. Rerun the affected scenarios before interpreting them.
- Resource costs cannot be inferred from operational event logs that contain
  no cost records; use external evidence or expert review.
