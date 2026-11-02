from datetime import datetime, timedelta, timezone

import pytest

from research.ocr_temporal_lineage_policy_20261030 import evaluate_temporal_lineage


UTC = timezone.utc
BASE = datetime(2026, 10, 29, tzinfo=UTC)


def records(*, shift=timedelta(0)):
    def rec(i, avail, gen=None):
        row = {"id": i, "version": "v1", "available_at": avail + shift}
        if gen is not None:
            row["generated_at"] = gen + shift
        return row
    data = {
        "source_version": rec("src", BASE),
        "ocr_model": rec("ocr", BASE),
        "ocr_output": rec("ocr-out", BASE + timedelta(hours=1), BASE + timedelta(hours=1)),
        "embedding_model": rec("emb", BASE),
        "embedding_output": rec("emb-out", BASE + timedelta(hours=2), BASE + timedelta(hours=2)),
        "index_snapshot": rec("idx", BASE + timedelta(hours=3), BASE + timedelta(hours=3)),
    }
    data["ocr_output"]["dependencies"] = {
        "source_version": {"id": "src", "version": "v1"},
        "ocr_model": {"id": "ocr", "version": "v1"},
    }
    data["embedding_output"]["dependencies"] = {
        "ocr_output": {"id": "ocr-out", "version": "v1"},
        "embedding_model": {"id": "emb", "version": "v1"},
    }
    data["index_snapshot"]["dependencies"] = {
        "ocr_output": {"id": "ocr-out", "version": "v1"},
        "embedding_output": {"id": "emb-out", "version": "v1"},
    }
    return data


def evaluate(data=None, **kw):
    return evaluate_temporal_lineage(
        mode=kw.pop("mode", "historical_realized"),
        historical_cutoff_exclusive=kw.pop("cutoff", datetime(2026, 10, 30, tzinfo=UTC)),
        analysis_at=kw.pop("at", datetime(2026, 10, 30, tzinfo=UTC)),
        retrieval_kind=kw.pop("kind", "hybrid"),
        artifacts=records() if data is None else data,
        **kw,
    )


def test_historical_before_exclusive_cutoff_with_offset_timezone():
    shifted = records(shift=timedelta(hours=9))
    result = evaluate(shifted, cutoff=datetime(2026, 10, 30, 9, tzinfo=timezone(timedelta(hours=9))),
                      at=datetime(2026, 10, 30, 10, tzinfo=timezone(timedelta(hours=9))))
    assert result["allowed"]


def test_historical_rejects_late_ocr_and_retrospective_allows_only_before_analysis():
    data = records()
    data["ocr_output"]["available_at"] = datetime(2026, 10, 30, tzinfo=UTC)
    data["ocr_output"]["generated_at"] = datetime(2026, 10, 30, tzinfo=UTC)
    data["embedding_output"]["generated_at"] = datetime(2026, 10, 30, 1, tzinfo=UTC)
    data["embedding_output"]["available_at"] = datetime(2026, 10, 30, 1, tzinfo=UTC)
    data["index_snapshot"]["generated_at"] = datetime(2026, 10, 30, 2, tzinfo=UTC)
    data["index_snapshot"]["available_at"] = datetime(2026, 10, 30, 2, tzinfo=UTC)
    assert not evaluate(data)["allowed"]
    posthoc = evaluate(data, mode="retrospective_reprocessing", at=datetime(2026, 10, 31, tzinfo=UTC))
    assert posthoc["allowed"]
    assert "retrospective_mode_not_historical_replay" in posthoc["reasons"]
    assert "postcutoff_artifact_present" in posthoc["reasons"]
    future = evaluate(data, mode="retrospective_reprocessing", at=datetime(2026, 10, 29, 12, tzinfo=UTC))
    assert not future["allowed"] and future["artifact_metadata"] == {}


@pytest.mark.parametrize("source_time", [datetime(2026, 10, 30, tzinfo=UTC), datetime(2026, 10, 31, tzinfo=UTC)])
def test_retrospective_rejects_source_at_or_after_historical_cutoff(source_time):
    data = records()
    data["source_version"]["available_at"] = source_time
    result = evaluate(data, mode="retrospective_reprocessing", at=datetime(2026, 11, 1, tzinfo=UTC))
    assert not result["allowed"] and result["artifact_metadata"] == {}
    assert "source_version_not_available_before_historical_cutoff" in result["reasons"]


@pytest.mark.parametrize("target,field,value", [
    ("embedding_model", "available_at", datetime(2026, 10, 30, tzinfo=UTC)),
    ("embedding_output", "generated_at", datetime(2026, 10, 30, 2, tzinfo=UTC)),
    ("index_snapshot", "generated_at", datetime(2026, 10, 30, 4, tzinfo=UTC)),
])
def test_unavailable_or_impossible_hybrid_lineage_is_blocked(target, field, value):
    data = records()
    data[target][field] = value
    result = evaluate(data, mode="retrospective_reprocessing", at=datetime(2026, 10, 31, tzinfo=UTC))
    assert not result["allowed"] and result["artifact_metadata"] == {}


def test_lexical_has_no_embedding_requirement():
    data = records()
    del data["embedding_model"]
    del data["embedding_output"]
    assert evaluate(data, kind="lexical")["allowed"]


def test_retrospective_with_only_pre_cutoff_artifacts_does_not_claim_postcutoff_data():
    result = evaluate(mode="retrospective_reprocessing")
    assert result["allowed"]
    assert result["reasons"] == ["retrospective_mode_not_historical_replay"]


@pytest.mark.parametrize("target,dependency,reference", [
    ("ocr_output", "source_version", {"id": "other", "version": "v1"}),
    ("ocr_output", "ocr_model", {"id": "ocr", "version": "v2"}),
    ("embedding_output", "ocr_output", {"id": "wrong", "version": "v1"}),
    ("embedding_output", "embedding_model", {"id": "emb", "version": "wrong"}),
    ("index_snapshot", "ocr_output", {"id": "not-ocr", "version": "v1"}),
    ("index_snapshot", "embedding_output", {"id": "not-embedding", "version": "v1"}),
])
def test_dependency_identity_mismatch_is_blocked(target, dependency, reference):
    data = records()
    data[target]["dependencies"][dependency] = reference
    assert not evaluate(data)["allowed"]


def test_missing_dependency_mapping_is_blocked():
    data = records()
    del data["ocr_output"]["dependencies"]
    result = evaluate(data)
    assert not result["allowed"] and result["artifact_metadata"] == {}


@pytest.mark.parametrize("callback", [lambda _: False, lambda _: "true", lambda _: 1, lambda _: (_ for _ in ()).throw(RuntimeError())])
def test_callback_must_return_exact_true(callback):
    result = evaluate(caller_verifier=callback)
    assert not result["allowed"] and result["artifact_metadata"] == {}


def test_non_mapping_artifacts_fail_closed():
    result = evaluate([])
    assert not result["allowed"] and "invalid_artifacts_mapping" in result["reasons"]


@pytest.mark.parametrize("kwargs", [
    {"mode": "mystery"}, {"kind": "semantic"},
    {"at": datetime(2026, 10, 30)},
    {"cutoff": datetime(2026, 10, 30)},
])
def test_unknown_or_naive_inputs_fail_closed(kwargs):
    result = evaluate(**kwargs)
    assert not result["allowed"] and result["artifact_metadata"] == {}


def test_missing_and_invalid_times_do_not_leak_any_artifact_metadata():
    data = records()
    del data["ocr_output"]["available_at"]
    data["index_snapshot"]["generated_at"] = "yesterday"
    result = evaluate(data)
    assert not result["allowed"] and result["artifact_metadata"] == {}
    assert "invalid_ocr_output_available_at" in result["reasons"]


def test_caller_callback_is_only_an_assertion_and_does_not_mutate_input():
    data = records()
    original = {k: dict(v) for k, v in data.items()}
    result = evaluate(data, caller_verifier=lambda _: True)
    assert result["caller_verifier_assertion"] is True
    assert result["input_provenance"] == "caller_asserted_unverified"
    assert data == original
