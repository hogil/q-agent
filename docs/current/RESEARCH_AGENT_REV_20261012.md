# Q-Agent Research Revision

2026-10-12. This is a research proposal, not a validated novelty claim.

## Research Question

Can a small language-model agent improve defect investigation under a fixed
query budget by retrieving evidence that distinguishes competing hypotheses,
with process, wafer, time, spatial correspondence, and source lineage checks?

## Proposed Method

| Stage | Responsibility |
|---|---|
| Router | Normalize the task; choose single-incident or population scope; select the next discriminating query |
| Incident DB | Full-population statistics, history retrieval, and scope validation |
| Follow-up Tools | Production SQL, document RAG, numerical Trend and spatial/image measurements |
| Judge | Check correspondence and update supporting, opposing, and missing evidence |
| Answer | Explain checked observations, candidate causes, limitations, and proposed inspections |
| Final status | Display investigation population and diagnostic status separately |

Judge requery returns to the same Router. Tool permissions and scope gates
remain enforced by code. Association is not causal confirmation.

## Candidate Contributions

1. An evidence contract that enforces entity/time/site correspondence and
   groups derived records by their original source.
2. A retrieval policy trained on evidence that discriminates plausible causes,
   including visually similar cases with different causes and normal controls.
3. A controlled industrial investigation benchmark with decision-time cutoffs,
   missing evidence, confounding, and unresolved cases.

Active diagnosis and multimodal RCA already exist. The combination alone is
insufficient: demonstrate what the proposed constraints and acquisition policy
improve relative to the closest existing methods.

## Data and Learning

Generate numerical trends, maps, events, and procedural images from shared
scenario variables. Keep simulator truth and future resolution meetings in an
evaluator-only store. Existing UI fixtures do not establish physical consistency.
Split by incident family and time, then hold out equipment/product/recipe groups.

Start with separate modality encoders and a candidate reranker. Train the sLLM
on expert-reviewed observable Tool trajectories and claims. Compare SFT alone
before adding preference optimization. Do not automatically mutate live Skills.

## Experiments

Compare fixed retrieval, one-shot RAG, the current Router loop, adaptive
retrieval without correspondence checks, and the full method using the same
backbone, tools, context limits, and query/token budgets. Replay identical
evidence to separate retrieval improvements from reasoning improvements.
Remove alignment, source grouping, counterevidence, reranking, and SFT one at
a time. Use incident-level paired uncertainty estimates and blind expert review.

Measure diagnosis quality, false defect/cause assertions, claim-level evidence
recall and precision, numeric correctness, scope errors, abstention coverage,
tokens, latency, and calls. Token recall/ROUGE are supplementary. A model must
not gain score by adding unsupported content or always abstaining.

## Implementation Status

- Implemented: summarize_incidents, explicit cohort lookup, full-population SQL
  counts/grouping, period comparison, bounded detail scopes, and role contracts.
- Still required: corporate normalization and PostgreSQL/search adapters,
  evidence correspondence and claim verification, acquisition policy, joint
  scenario generator, learned reranker, sLLM SFT, and controlled evaluation.
- Corporate source code and actual data have not been supplied or validated.

## Related Work

- TAMO: https://arxiv.org/abs/2504.20462
- TraceBench (preprint): https://arxiv.org/abs/2608.27182
- Self-RAG: https://arxiv.org/abs/2310.11511
- Corrective RAG: https://arxiv.org/abs/2401.15884
- OpenRCA: https://microsoft.github.io/OpenRCA/
