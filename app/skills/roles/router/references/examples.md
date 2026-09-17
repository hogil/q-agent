# Optional Few-Shot Examples

Synthetic train scenarios only; authored 2026-09-18 from local Tool contracts.
These are behavior examples, not lookup data or an exhaustive keyword classifier.
Use the current question's values. Output must include all required schema fields.

## Incident With Expert Analysis

Question: "SYN-2026-01의 초기 가설과 나중에 확인된 원인을 구분해줘."
Initial auto decision: route, stage=incident, plan=[], search_mode=none.
Next action: find_incidents(arguments={"incident_number":"SYN-2026-01"}), stage=incident, search_mode=sql_exact.
After a valid single-incident scope: search_meeting_minutes(arguments={"query":"원인"}), stage=tools, search_mode=none.
Read returned dates/versions and request more evidence only if needed; never infer a heater problem from this example.

## Independent Minutes

Question: "독립 설비 메모의 교정 주기는?"
Initial auto decision: route, stage=independent, plan=[], search_mode=none.
Next action: search_meeting_minutes(arguments={"query":"교정"}), stage=independent, search_mode=none.
No find_incidents or accident ID is needed. If results are empty, rephrase once if justified or report missing evidence.
