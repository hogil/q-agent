# Optional Few-Shot Examples

Synthetic train patterns, 2026-09-18. Wording and values are illustrations only.

If a retrieved independent memo explicitly records a 30-day calibration interval:
"조회한 설비 메모에는 교정 주기가 30일로 기록되어 있습니다. [actual chunk_id, meeting_date, version]"
Replace the bracket with returned metadata and cite its Tool evidence ID in claims. Never reuse 30 days for a different memo.

If DB and list evidence show expected four Lots and three registered Lots:
"기대 Lot는 4건, 조회된 등록 Lot는 3건으로 일치하지 않습니다. 목록 완전성은 unknown이므로 실제 영향 Lot 전체가 3건이라고 단정할 수 없습니다."
Use only actual retrieved counts. A count mismatch does not by itself prove loss, cause or recovery status.
