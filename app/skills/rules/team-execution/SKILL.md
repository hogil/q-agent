---
name: team-execution
description: Scope와 시점이 검증된 분석 task의 의존성, 근거 버전, 코드 Worker 실행과 선택적 복구를 관리한다. 업무 LLM 팀과 생산 권한을 자동 활성화하지 않는다.
---

# Scoped Team Execution

Source/basis: Q-Agent AGENTS.md, actual app/agent.py and llm_client.py inspected on 2026-10-28; ASCOPE_TEAM_DESIGN_20261028_ROOT_v1.md; [MasRouter](https://aclanthology.org/2025.acl-long.757/), [MaAS](https://proceedings.mlr.press/v267/zhang25bi.html), and [IMPACT-CYCLE](https://arxiv.org/abs/2604.20136) checked on 2026-10-28. Company data and production behavior are unverified.

- This is an offline application Skill contract. It is not an online permission grant or an installed development-assistant team. Only currently registered, enabled adapters may execute. A planner/compiler is not an LLM Worker.
- Preserve the single Router → incident DB → follow-up Tools/optional team → Judge → Answer flow. Incident DB search/aggregation and scope validation precede business team dispatch. All Judge requery returns to the same Router; Answer is the last LLM.
- The trusted caller supplies scope references, as_of and evidence version/availability metadata separately from model-proposed task JSON. A matching hash or scope string is not authentication, ACL, truth or company validation. A child may not expand target, comparison or historical scope.
- Bind each evidence record to its server-attested owning scope references. Root access to both current and historical scopes does not let a current-only child consume historical evidence. Evidence scope references must be declared by the consuming task. Data-parent scope references must also be declared by the child; control-only dependencies do not transfer their output. Include ownership metadata in input identity/cache keys. The Adapter remains responsible for actual row membership and projection; this contract does not infer a Lot/Chip scope lattice from strings.
- Keep distinct data and control dependencies. Reject unknown IDs, cycles, absent capabilities, unavailable inputs and exhausted shared budgets before dispatch. Select the smallest feasible provider set for complete tasks; do not fabricate quality estimates. Deterministic calculations do not require another LLM.
- A task may use only its pinned evidence and committed data-parent outputs. Use server as_of and availability, not a cutoff invented by a Worker. Preserve units, grain, Chip/wafer frames, observed/selected/eligible denominators, missing values and limitations.
- Record evidence versions and the exact validation attempt before work begins. Commit only against that validation snapshot. Reject a late callback after evidence/scope/parent changes, even if it sees a newer global ledger revision.
- Ledger commitment records an immutable technical version; Judge support/counterevidence/unknown remains separate. Preserve previous attempts. Repeat identical completion only if input pins, validation identity and canonical JSON output are identical.
- On a changed source, stale direct consumers and data descendants. Control-order siblings are not automatically data consumers. Revalidate stale work. Scope/as_of/release changes invalidate affected work; failed task repair does not clear a failed business gate.
- Callback failure may abandon that attempt and leave independent completed work available. Never retry MES writes or unknown commits through this mechanism. Workers only read, analyze or propose.
- In-process code workers must honor adapter deadlines. Thread scheduling is not hard process isolation or a general Python sandbox. The experimental synthetic runner does not establish production scheduling or actual LLM team quality.
- Trace planned/completed/cached/stale/failed tasks, provider choice, input pins, attempts and measured local time. Missing provider token usage stays unknown. An injected source update or structural guard is not an LLM answer benchmark.
- FAB IN future FAB OUT is predicted or retrieved from historical cases, never supplied as future actual evidence. Skip-rule comparison cohorts may have different Lots/Wafers and require separately validated scope. Do not replace missing Measure/Yield with normal values. FDC detection remains deferred.

Online queries may not edit this Skill, policy, model or source. Improvements are reviewed and explicitly frozen offline. General removed LLM question/answer banks remain removed.
