# Model settings and external-service variability

AureaSim supports offline replay and live AI-assisted generation.

Offline replay uses supplied BPMN, parameter, and scenario files. It does not
call Gemini or web search and is the appropriate installation smoke test.

Live generation uses structured Gemini requests and, in evidence-grounded
mode, web search. The implementation uses low-temperature generation, but
external-service output is not guaranteed to be deterministic. Model updates,
search-result changes, API availability, and public-source drift can change a
later result.

Current generation settings:

| Stage | Model | Temperature |
| --- | --- | ---: |
| Web-grounded context gathering | Gemini 2.5 Flash | 0.1 |
| Base parameter generation | Gemini 2.5 Flash | 0.2 |
| Missing-task/schema repair | Gemini 2.5 Flash | 0.2 |
| Scenario generation | Gemini 2.5 Flash | 0.4 |
| Evidence audit | Gemini 2.5 Flash | 0.0 |

For this reason, generated values are parameter candidates rather than assumed
truth. AureaSim records their method and evidence, exposes expected error or
measured fidelity when available, and supports expert review and replacement.

## Active-service-time guardrail

Prosimos task-duration fields represent active resource service time, not
queueing, handoffs, waiting, or end-to-end case duration. After generation,
AureaSim therefore applies a deterministic guardrail:

- a non-finite, non-positive, or greater-than-one-working-day human-task mean
  is replaced with a 600-second normal prior;
- a BPMN service/script task, or a task assigned to an authoritative System
  role, receives the structural machine prior (mean 0.02 seconds);
- role identity is read from both legacy Aurea role elements and the
  lower-case 2024 converter schema, so a converted `Role_3` with
  `code="system"` is treated as `System`, not as an anonymous role ID;
- System subroles such as `System_SAP` are normalized as authoritative System
  roles as well, so they receive the same structural prior and cannot retain
  incompatible web-evidence metadata;
- every replacement records the original value, replacement, reason, and
  policy constants in `metadata.task_duration_stabilization_policy`.

This guardrail prevents an elapsed-time benchmark from being represented as
active execution evidence. It does not make the replacement calibrated; the
result remains an explicit heuristic or structural prior requiring review.
