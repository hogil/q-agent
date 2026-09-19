# Optional Few-Shot Examples

Synthetic behavior examples, not lookup data or exhaustive rules. Local Tool contracts,
2026-09-18; shortened 2026-09-19 without changing actions. Use current question values and all schema fields.

## Incident With Expert Analysis

"SYN-2026-01 초기 가설과 확인 원인은?"
route(incident) → find_incidents({"incident_number":"SYN-2026-01"}, sql_exact)
→ valid single scope → search_meeting_minutes({"query":"원인"}, tools/none).
Inspect dates/versions; the example supplies no cause or answer.

## Independent Minutes

"독립 설비 메모의 교정 주기는?"
route(independent) → search_meeting_minutes({"query":"교정"}, independent/none).
No incident DB/ID. Empty results: justified rephrase once or report missing evidence.
