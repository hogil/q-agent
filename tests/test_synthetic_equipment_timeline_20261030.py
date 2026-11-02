from datetime import datetime, timedelta, timezone

import pytest

from research.synthetic_equipment_timeline_20261030 import (
    MAX_INPUT_RECORDS, TimelineInputError, search_synthetic_equipment_timeline,
)

UTC = timezone.utc
ASOF = datetime(2026, 10, 30, 12, tzinfo=UTC)
START = ASOF - timedelta(hours=2)
END = ASOF - timedelta(hours=1)


def row(record_id="r1", **kw):
    result = {
        "record_id": record_id, "type": "event", "incident_id": "I1",
        "equipment_id": "EQ1", "lot_id": "L1", "event_time": END,
        "available_at": ASOF - timedelta(minutes=1), "text": "synthetic note",
    }
    result.update(kw)
    return result


def search(records, **kw):
    args = dict(incident_id="I1", equipment_ids=["EQ1"], lot_ids=["L1"], as_of=ASOF,
                window_start=START, window_end=END, records=records,
                synthetic_fixture_asserted=True,
                validate_incident_scope=lambda scope: True,
                authorize_record=lambda scope, record: True)
    args.update(kw)
    return search_synthetic_equipment_timeline(**args)


def test_scope_and_record_authorization_fail_closed():
    denied = search([row()], validate_incident_scope=lambda scope: False)
    assert denied["records"] == [] and not denied["authorized_input_scan_complete"]
    assert search([row()], validate_incident_scope=None)["records"] == []
    assert search([row()], authorize_record=None)["records"] == []
    assert search([row()], authorize_record=lambda *a: (_ for _ in ()).throw(RuntimeError()))["records"] == []


def test_unknown_scope_dates_and_timezone_validation():
    assert search([row(incident_id="I2")])["records"] == []
    with pytest.raises(TimelineInputError):
        search([row()], window_start=END + timedelta(seconds=1))
    with pytest.raises(TimelineInputError):
        search([row()], as_of=ASOF.replace(tzinfo=None))


def test_boundaries_timezone_conversion_and_future_available():
    local = timezone(timedelta(hours=9))
    boundary = row(event_time=END.astimezone(local), available_at=ASOF.astimezone(local))
    future = row("future", available_at=ASOF + timedelta(microseconds=1))
    outside = row("outside", event_time=START - timedelta(microseconds=1))
    result = search([boundary, future, outside])
    assert [r["record_id"] for r in result["records"]] == ["r1"]
    assert result["records"][0]["event_time"].endswith("+00:00")


def test_equipment_lot_unknown_lot_and_no_causality_claim():
    result = search([row("wrong-eq", equipment_id="EQ2"), row("wrong-lot", lot_id="L2"),
                     row("unknown-lot", lot_id=None)])
    assert [r["record_id"] for r in result["records"]] == ["unknown-lot"]
    assert result["records"][0]["lot_scope_status"] == "unknown_equipment_time_candidate_only"
    assert result["records"][0]["causality"] == "not_assessed"


def test_duplicate_first_wins_sort_and_top_k_truncation():
    rows = [row("same", event_time=END), row("same", text="duplicate"),
            row("older", event_time=START), row("newer", event_time=END - timedelta(minutes=1))]
    result = search(rows, top_k=1)
    assert [r["record_id"] for r in result["records"]] == ["same"]
    assert result["records"][0]["text"] == "synthetic note"
    assert result["truncated"] and not result["authorized_input_scan_complete"]


def test_input_cap_marks_result_incomplete():
    result = search((row(str(i)) for i in range(MAX_INPUT_RECORDS + 2)), top_k=2)
    assert result["truncated"] and not result["authorized_input_scan_complete"]
    assert result["synthetic_assertion"] == "caller_asserted_unverified"
    assert result["real_source_coverage"] == "unknown"


def test_fixture_assertion_is_required_and_record_counts_are_not_exposed():
    with pytest.raises(TimelineInputError):
        search([row()], synthetic_fixture_asserted=False)
    result = search([row(), row("bad", event_time="not-a-date")])
    assert result["authorized_input_scan_complete"] is False
    assert "source_coverage" not in result
    assert result["real_source_coverage"] == "unknown"


@pytest.mark.parametrize("bad_row", [
    row("bad-type", type="unexpected"),
    row("bad-text", text=object()),
    row("long-text", text="x" * 4_001),
])
def test_invalid_type_or_text_marks_input_scan_incomplete(bad_row):
    result = search([bad_row, row("valid")])
    assert [r["record_id"] for r in result["records"]] == ["valid"]
    assert result["authorized_input_scan_complete"] is False


def test_out_of_scope_duplicate_does_not_hide_scoped_row_and_duplicate_marks_incomplete():
    result = search([row("dup", incident_id="I2"), row("dup")])
    assert [r["text"] for r in result["records"]] == ["synthetic note"]
    duplicate = search([row("dup"), row("dup", text="conflict")])
    assert len(duplicate["records"]) == 1
    assert duplicate["authorized_input_scan_complete"] is False


def test_scope_denial_does_not_consume_iterator_and_false_is_not_exception():
    consumed = []
    def source():
        consumed.append(True)
        yield row()
    result = search(source(), validate_incident_scope=lambda scope: False)
    assert result["records"] == [] and consumed == []
    mixed = search([row("denied"), row("allowed")], authorize_record=lambda scope, rec: rec["record_id"] == "allowed")
    assert [r["record_id"] for r in mixed["records"]] == ["allowed"]
    assert mixed["authorized_input_scan_complete"] is True


def test_input_cap_does_not_fetch_10001st_item():
    consumed = []
    def source():
        for i in range(MAX_INPUT_RECORDS + 1):
            consumed.append(i)
            yield row(str(i))
    result = search(source())
    assert len(consumed) == MAX_INPUT_RECORDS
    assert result["truncated"] and not result["authorized_input_scan_complete"]


def test_iter_creation_exception_returns_incomplete_without_error_details():
    class BrokenIterable:
        def __iter__(self):
            raise RuntimeError("private implementation detail")

    result = search(BrokenIterable())
    assert result["records"] == []
    assert result["authorized_input_scan_complete"] is False
    assert "private implementation detail" not in repr(result)
