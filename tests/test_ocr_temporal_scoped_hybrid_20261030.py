from datetime import datetime, timezone

import pytest

from research.ocr_temporal_scoped_hybrid_20261030 import ScopedTemporalError, search_scoped_temporal

UTC = timezone.utc
CUTOFF = datetime(2026, 10, 30, tzinfo=UTC)


def lineage():
    def rec(i, at, generated=False):
        row = {"id": i, "version": "v1", "available_at": at}
        if generated:
            row["generated_at"] = at
        return row
    d = {"source_version": rec("d", datetime(2026, 10, 29, tzinfo=UTC)),
         "ocr_model": rec("om", datetime(2026, 10, 29, tzinfo=UTC)),
         "ocr_output": rec("oo", datetime(2026, 10, 29, 1, tzinfo=UTC), True),
         "embedding_model": rec("em", datetime(2026, 10, 29, tzinfo=UTC)),
         "embedding_output": rec("eo", datetime(2026, 10, 29, 2, tzinfo=UTC), True),
         "index_snapshot": rec("ix", datetime(2026, 10, 29, 3, tzinfo=UTC), True)}
    d["ocr_output"]["dependencies"] = {"source_version": {"id": "d", "version": "v1"}, "ocr_model": {"id": "om", "version": "v1"}}
    d["embedding_output"]["dependencies"] = {"ocr_output": {"id": "oo", "version": "v1"}, "embedding_model": {"id": "em", "version": "v1"}}
    d["index_snapshot"]["dependencies"] = {"ocr_output": {"id": "oo", "version": "v1"}, "embedding_output": {"id": "eo", "version": "v1"}}
    return d


def chunks():
    base = {"document_id": "d", "version": "v1", "source_ref": "synthetic://d", "locator": "{}",
            "status": "active", "incident_ids": ["I1"], "synthetic_fixture": True,
            "ocr_output_id": "oo", "ocr_output_version": "v1", "embedding_output_id": "eo", "embedding_output_version": "v1"}
    src = "2026-10-29T00:00:00+00:00"
    return [dict(base, chunk_id="old", text="bearing failure commonword", source_available_at=src, available_at="2026-10-29T23:59:59+00:00"),
            dict(base, chunk_id="edge", text="bearing failure commonword", source_available_at=src, available_at="2026-10-30T00:00:00+00:00"),
            dict(base, chunk_id="scope", incident_ids=["I2"], text="bearing failure commonword", source_available_at=src, available_at="2026-10-29T12:00:00+00:00")]


def run(*, docs=None, mode="historical_realized", cutoff=CUTOFF, at=datetime(2026, 10, 30, 12, tzinfo=UTC),
        verifier=None, authorize=lambda _: True, authorize_document=lambda _: True, as_of="2026-10-29", timezone_name="UTC"):
    docs = chunks() if docs is None else docs
    return search_scoped_temporal(chunks=docs, vectors={c["chunk_id"]: [1.0, 0.0] for c in docs}, artifacts=lineage(),
        mode=mode, historical_cutoff_exclusive=cutoff, analysis_at=at, caller_verifier=verifier,
        query="commonword", query_vector=[1.0, 0.0], incident_ids=["I1"], as_of=as_of,
        timezone_name=timezone_name, top_k=10, similarity_threshold=-1, authorize=authorize, authorize_document=authorize_document)


def test_pre_index_temporal_scope_filtering_and_metadata_nonleak():
    result = run()
    assert [x["chunk_id"] for x in result["items"]] == ["old"]
    assert result["candidate_count"] == 1
    assert result["historical_index_proof"].endswith("not_historical_index_proof")
    assert "edge" not in str(result) and "scope" not in str(result)


def test_retrospective_marks_posthoc_and_source_future_is_rejected():
    docs = chunks()
    docs[1]["available_at"] = "2026-10-30T01:00:00+00:00"
    result = run(docs=docs, mode="retrospective_reprocessing", at=datetime(2026, 10, 31, tzinfo=UTC))
    assert result["posthoc"] is True
    assert "edge" in [x["chunk_id"] for x in result["items"]]
    assert result["bridge_search_as_of"] == "2026-10-31"
    data = lineage()
    data["source_version"]["available_at"] = CUTOFF
    result = search_scoped_temporal(chunks=chunks(), vectors={c["chunk_id"]: [1., 0.] for c in chunks()}, artifacts=data,
        mode="retrospective_reprocessing", historical_cutoff_exclusive=CUTOFF,
        analysis_at=datetime(2026, 10, 31, tzinfo=UTC), query="commonword", query_vector=[1., 0.],
        incident_ids=["I1"], as_of="2026-10-29", timezone_name="UTC", top_k=5,
        similarity_threshold=-1, authorize=lambda _: True, authorize_document=lambda _: True)
    assert result["status"] == "INELIGIBLE" and result["items"] == []


@pytest.mark.parametrize("callback", [lambda _: 1, lambda _: "true", lambda _: False, lambda _: (_ for _ in ()).throw(RuntimeError())])
def test_scope_callback_exact_true_and_exception_fail_closed(callback):
    with pytest.raises(ScopedTemporalError):
        run(authorize=callback)


@pytest.mark.parametrize("callback", [lambda _: 1, lambda _: "true", lambda _: False])
def test_document_authorization_is_exact_true(callback):
    result = run(authorize_document=callback)
    assert result["status"] == "NO_MATCH" and "old" not in str(result)


def test_document_authorization_exception_fails_closed():
    with pytest.raises(ScopedTemporalError):
        run(authorize_document=lambda _: (_ for _ in ()).throw(RuntimeError()))


def test_temporal_verifier_must_be_exact_true():
    result = run(verifier=lambda _: 1)
    assert result["status"] == "INELIGIBLE" and result["items"] == []


def test_date_timezone_boundary_must_equal_aware_cutoff():
    with pytest.raises(ScopedTemporalError, match="boundary"):
        run(cutoff=datetime(2026, 10, 30, 1, tzinfo=UTC))
    # A boundary at local midnight is valid in the named zone, including the date contract.
    result = run(cutoff=datetime(2026, 10, 30, tzinfo=UTC), as_of="2026-10-29", timezone_name="UTC")
    assert result["status"] == "OK"


def test_lineage_document_identity_mismatch_excludes_chunks_before_indexing():
    data = lineage()
    data["source_version"]["id"] = "different-document"
    data["ocr_output"]["dependencies"]["source_version"]["id"] = "different-document"
    result = search_scoped_temporal(chunks=chunks(), vectors={c["chunk_id"]: [1., 0.] for c in chunks()}, artifacts=data,
        mode="historical_realized", historical_cutoff_exclusive=CUTOFF,
        analysis_at=datetime(2026, 10, 30, 12, tzinfo=UTC), query="commonword", query_vector=[1., 0.],
        incident_ids=["I1"], as_of="2026-10-29", timezone_name="UTC", top_k=5,
        similarity_threshold=-1, authorize=lambda _: True, authorize_document=lambda _: True)
    assert result["status"] == "NO_MATCH" and result["items"] == []


def test_per_chunk_derived_output_id_and_version_are_required():
    docs = chunks()
    docs[0]["ocr_output_id"] = "different"
    result = run(docs=docs)
    assert result["status"] == "NO_MATCH" and result["items"] == []


def test_wrapper_rejects_lexical_mode_instead_of_running_unchecked_vectors():
    with pytest.raises(ScopedTemporalError, match="hybrid retrieval only"):
        search_scoped_temporal(chunks=chunks(), vectors={c["chunk_id"]: [1., 0.] for c in chunks()}, artifacts=lineage(),
            mode="historical_realized", historical_cutoff_exclusive=CUTOFF,
            analysis_at=datetime(2026, 10, 30, 12, tzinfo=UTC), retrieval_kind="lexical",
            query="commonword", query_vector=[1., 0.], incident_ids=["I1"], as_of="2026-10-29",
            timezone_name="UTC", top_k=5, similarity_threshold=-1, authorize=lambda _: True,
            authorize_document=lambda _: True)


def test_chunk_source_and_derived_timestamps_must_match_lineage_order():
    docs = chunks()
    docs[0]["source_available_at"] = "2026-10-29T00:00:01+00:00"
    docs[1]["available_at"] = "2026-10-29T01:30:00+00:00"
    result = run(docs=docs)
    assert result["status"] == "NO_MATCH" and result["items"] == []


def test_future_and_denied_documents_do_not_change_bm25_vector_scores():
    baseline = run(docs=chunks())
    mixed = chunks() + [
        dict(chunks()[0], chunk_id="future-secret", text="commonword commonword commonword", available_at="2026-10-30T01:00:00+00:00"),
        dict(chunks()[0], chunk_id="denied-secret", text="commonword commonword commonword", document_id="denied")]
    result = run(docs=mixed, authorize_document=lambda request: request["document_id"] != "denied")
    assert [(i["chunk_id"], i["score"]) for i in result["items"]] == [(i["chunk_id"], i["score"]) for i in baseline["items"]]


def test_cutoff_derived_ocr_and_embedding_included_only_for_retrospective():
    docs = chunks()
    docs[0]["available_at"] = "2026-10-30T01:00:00+00:00"
    historical = run(docs=docs)
    retro = run(docs=docs, mode="retrospective_reprocessing", at=datetime(2026, 10, 31, tzinfo=UTC))
    assert historical["status"] == "NO_MATCH"
    assert retro["status"] == "OK" and {x["chunk_id"] for x in retro["items"]} == {"old", "edge"}


def test_historical_cutoff_chunk_is_removed_before_fts_so_scores_match_baseline():
    baseline_docs = chunks()[:1]
    baseline_docs[0]["available_at"] = "2026-10-29T23:00:00+00:00"
    baseline = run(docs=baseline_docs)
    mixed = baseline_docs + [dict(chunks()[0], chunk_id="postcutoff-noise",
        text="commonword uncommon token noise that distorts FTS corpus statistics",
        available_at="2026-10-30T00:00:00+00:00")]
    strict = run(docs=mixed)
    assert [(x["chunk_id"], x["score"]) for x in strict["items"]] == [(x["chunk_id"], x["score"]) for x in baseline["items"]]
