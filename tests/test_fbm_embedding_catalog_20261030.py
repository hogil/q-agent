import math
import os

import pytest
import research.fbm_embedding_catalog_20261030 as fbm_catalog

from research.fbm_embedding_catalog_20261030 import (
    AuthorizationError,
    CatalogError,
    EmbeddingSpec,
    FBMEmbeddingCatalog,
)


CHECKPOINT = "a" * 64
RAW = EmbeddingSpec("synthetic-enc-v1", CHECKPOINT, "resize-none-v1", 2, "raw_fbm")
OBJ = EmbeddingSpec("synthetic-enc-v1", CHECKPOINT, "resize-none-v1", 2, "object_id_yield")


def make_catalog(tmp_path, authorize=lambda actor, incident, op: True, name="new-gallery"):
    root = tmp_path / name
    return FBMEmbeddingCatalog(root, authorize=authorize)


def add(cat, *, aid="a", rev="r1", raw=b"synthetic-map", vector=(1.0, 0.0),
        spec=RAW, source_time="2026-10-01", available_at=None,
        incident="inc-1", lot="lot-1", wafer="w-1"):
    return cat.add(asset_id=aid, source_revision=rev, raw_bytes=raw,
        vector=vector, spec=spec, source_time=source_time,
        available_at=available_at or source_time, incident_id=incident,
        lot_id=lot, wafer_id=wafer, actor="trusted-user", incident_scope={incident})


def test_lossless_bytes_hash_and_separate_representations(tmp_path):
    cat = make_catalog(tmp_path, name="scope-gallery")
    try:
        raw = b"\x00synthetic\xff map bytes"
        digest = add(cat, raw=raw)
        assert cat.get_raw(asset_id="a", source_revision="r1", representation="raw_fbm",
                           actor="trusted-user", incident_scope={"inc-1"}, as_of="2026-10-30") == raw
        add(cat, raw=b"different derived representation", spec=OBJ)
        assert len(cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
                              incident_scope={"inc-1"}, as_of="2026-10-30", top_k=10)) == 1
        assert digest
    finally:
        cat.close()


def test_exact_dedupe_revision_and_different_bytes_conflict(tmp_path):
    cat = make_catalog(tmp_path, name="scoped-gallery")
    try:
        first = add(cat, raw=b"bytes")
        assert add(cat, raw=b"bytes") == first
        add(cat, rev="r2", raw=b"revised bytes")
        with pytest.raises(CatalogError):
            add(cat, raw=b"other bytes")
        results = cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
                             incident_scope={"inc-1"}, as_of="2026-10-30", top_k=10)
        assert [x.source_revision for x in results] == ["r1", "r2"]
    finally:
        cat.close()


def test_similarity_deterministic_ties_provenance_scope_asof_and_exclusion(tmp_path):
    cat = make_catalog(tmp_path, authorize=lambda actor, *_: actor == "trusted-user", name="scope-gallery")
    try:
        add(cat, aid="z", vector=(0, 1), source_time="2026-01-01")
        add(cat, aid="b", vector=(0, 1), incident="inc-2", source_time="2026-01-02",
            lot="lot-2", wafer="w-2")
        add(cat, aid="a", vector=(0, 1), source_time="2027-01-01")
        got = cat.search(query_vector=(0, 1), spec=RAW, actor="trusted-user",
            incident_scope={"inc-1", "inc-2"}, as_of="2026-12-31", top_k=5,
            exclude_asset_id="z")
        assert [x.asset_id for x in got] == ["b"]
        assert (got[0].lot_id, got[0].wafer_id, got[0].incident_id) == ("lot-2", "w-2", "inc-2")
        assert got[0].similarity == pytest.approx(1.0)
    finally:
        cat.close()


def test_auth_and_scope_fail_closed(tmp_path):
    with pytest.raises(AuthorizationError):
        FBMEmbeddingCatalog(tmp_path / "no-policy", authorize=None)
    cat = make_catalog(tmp_path, authorize=lambda *_: False, name="denied-gallery")
    try:
        with pytest.raises(AuthorizationError):
            add(cat)
    finally:
        cat.close()
    cat = make_catalog(tmp_path, authorize=lambda actor, *_: actor == "trusted-user", name="scope-gallery")
    try:
        add(cat)
        assert len(cat.search(query_vector=(1, 0), spec=RAW, actor="u", incident_scope=set(),
                              as_of="2027-01-01", top_k=4)) == 0
        with pytest.raises(AuthorizationError):
            cat.search(query_vector=(1, 0), spec=RAW, actor="u", incident_scope={"inc-1"},
                       as_of="2027-01-01", top_k=4)
    finally:
        cat.close()


@pytest.mark.parametrize("spec", [EmbeddingSpec("other", CHECKPOINT, "resize-none-v1", 2, "raw_fbm"),
    EmbeddingSpec("synthetic-enc-v1", "b" * 64, "resize-none-v1", 2, "raw_fbm"),
    EmbeddingSpec("synthetic-enc-v1", CHECKPOINT, "other-preprocess", 2, "raw_fbm"),
    EmbeddingSpec("synthetic-enc-v1", CHECKPOINT, "resize-none-v1", 3, "raw_fbm"), OBJ])
def test_incompatible_contract_returns_no_candidates(tmp_path, spec):
    cat = make_catalog(tmp_path)
    try:
        add(cat)
        vector = (1, 0, 0) if spec.dimension == 3 else (1, 0)
        assert len(cat.search(query_vector=vector, spec=spec, actor="trusted-user",
                              incident_scope={"inc-1"}, as_of="2027-01-01", top_k=4)) == 0
    finally:
        cat.close()


def test_vector_validation_and_empty_gallery(tmp_path):
    cat = make_catalog(tmp_path)
    try:
        assert len(cat.search(query_vector=(1, 0), spec=RAW, actor="u", incident_scope=set(),
                              as_of="2026-01-01", top_k=5)) == 0
        for vector in ((0, 0), (math.nan, 0), (2, 0)):
            with pytest.raises(CatalogError):
                add(cat, vector=vector)
        add(cat, aid="../../outside", raw=b"synthetic")
        assert cat.search(query_vector=(1, 0), spec=RAW, actor="u", incident_scope={"inc-1"},
                          as_of="2027-01-01", top_k=1)[0].asset_id == "../../outside"
    finally:
        cat.close()


def test_existing_nonempty_directory_is_refused(tmp_path):
    root = tmp_path / "already-there"
    root.mkdir()
    (root / "keep.txt").write_text("synthetic placeholder")
    with pytest.raises(CatalogError):
        FBMEmbeddingCatalog(root, authorize=lambda *_: True)
    assert (root / "keep.txt").read_text() == "synthetic placeholder"


def test_new_path_only_and_explicit_reopen_persists_data(tmp_path):
    root = tmp_path / "persistent"
    root.mkdir()
    with pytest.raises(CatalogError):
        FBMEmbeddingCatalog(root, authorize=lambda *_: True)
    root.rmdir()
    cat = FBMEmbeddingCatalog(root, authorize=lambda *_: True)
    expected = add(cat, raw=b"persisted synthetic bytes")
    cat.close()
    reopened = FBMEmbeddingCatalog.open_existing(root, authorize=lambda *_: True)
    try:
        assert reopened.get_raw(asset_id="a", source_revision="r1", representation="raw_fbm",
            actor="trusted-user", incident_scope={"inc-1"}, as_of="2026-10-30") == b"persisted synthetic bytes"
        assert expected
    finally:
        reopened.close()


def test_utc_instant_asof_and_date_end_semantics(tmp_path):
    cat = make_catalog(tmp_path)
    try:
        add(cat, source_time="2026-10-01T00:00:00+09:00",
            available_at="2026-10-01T00:00:00+09:00")
        result = cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
            incident_scope={"inc-1"}, as_of="2026-09-30T15:00:00Z", top_k=3)
        assert len(result) == 1
        assert result[0].available_at == "2026-09-30T15:00:00.000000Z"
        assert len(cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
            incident_scope={"inc-1"}, as_of="2026-09-30T14:59:59Z", top_k=3)) == 0
        # Date-only as_of means the end of that UTC calendar day.
        assert cat.get_raw(asset_id="a", source_revision="r1", representation="raw_fbm",
            actor="trusted-user", incident_scope={"inc-1"}, as_of="2026-09-30")
        with pytest.raises(CatalogError):
            cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
                incident_scope={"inc-1"}, as_of="2026-09-30T15:00:00", top_k=3)
    finally:
        cat.close()


def test_available_at_is_required_for_retrieval_and_duplicate_metadata_conflicts(tmp_path):
    cat = make_catalog(tmp_path)
    try:
        add(cat, available_at="2027-01-01T00:00:00Z")
        assert len(cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
            incident_scope={"inc-1"}, as_of="2026-12-31", top_k=3)) == 0
        with pytest.raises(CatalogError):
            cat.get_raw(asset_id="a", source_revision="r1", representation="raw_fbm",
                actor="trusted-user", incident_scope={"inc-1"}, as_of="2026-12-31")
        for kwargs in ({"vector": (0, 1)}, {"available_at": "2027-01-02T00:00:00Z"},
                       {"lot": "other-lot"}, {"incident": "other-incident"}):
            with pytest.raises((CatalogError, AuthorizationError)):
                add(cat, **({"available_at": "2027-01-01T00:00:00Z"} | kwargs))
    finally:
        cat.close()


def test_symlink_root_refused_when_supported(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")
    with pytest.raises(CatalogError):
        FBMEmbeddingCatalog(link, authorize=lambda *_: True)


def test_scope_is_authorized_before_sql_and_excluded_before_candidate_cap(tmp_path):
    calls = []
    cat = make_catalog(tmp_path, authorize=lambda actor, incident, op:
        calls.append(incident) or op == "write" or incident == "inc-1")
    try:
        add(cat, aid="in-scope", incident="inc-1")
        add(cat, aid="outside", incident="inc-2")
        calls.clear()
        result = cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
            incident_scope={"inc-1"}, as_of="2027-01-01", top_k=5)
        assert [r.asset_id for r in result] == ["in-scope"]
        assert calls == ["inc-1"]
        calls.clear()
        with pytest.raises(AuthorizationError):
            cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
                incident_scope={"inc-1", "inc-2"}, as_of="2027-01-01", top_k=5)
        assert calls == ["inc-1", "inc-2"]
    finally:
        cat.close()


def test_exact_content_exclusion_is_filtered_before_cap(tmp_path):
    cat = make_catalog(tmp_path)
    try:
        digest = add(cat, aid="query", raw=b"same synthetic content")
        add(cat, aid="duplicate-id", raw=b"same synthetic content")
        add(cat, aid="other", raw=b"different content", vector=(0, 1))
        result = cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
            incident_scope={"inc-1"}, as_of="2027-01-01", top_k=10, exclude_sha256=digest)
        assert [r.asset_id for r in result] == ["other"]
        assert result.eligible_count == 1
        assert result.truncated is False
    finally:
        cat.close()


def test_bounded_candidate_cap_scoped_population_and_topk_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(fbm_catalog, "_MAX_CANDIDATES", 2)
    cat = make_catalog(tmp_path)
    try:
        for index in range(3):
            add(cat, aid=f"allowed-{index}")
        add(cat, aid="outside", incident="other-incident")
        with pytest.raises(CatalogError, match="candidate limit"):
            cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
                incident_scope={"inc-1"}, as_of="2027-01-01", top_k=1)
        # Content exclusion is in SQL before the candidate cap.
        digest = cat._db.execute("SELECT sha256 FROM assets WHERE asset_id='allowed-0'").fetchone()[0]
        result = cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
            incident_scope={"inc-1"}, as_of="2027-01-01", top_k=1, exclude_sha256=digest)
        assert result.eligible_count == 0
        assert result.items == () and result.truncated is False
        assert "no exhaustive" in result.population_note.lower()
    finally:
        cat.close()


def test_topk_reports_eligible_count_and_truncation(tmp_path):
    cat = make_catalog(tmp_path)
    try:
        add(cat, aid="b", vector=(0, 1))
        add(cat, aid="a", vector=(1, 0))
        add(cat, aid="c", vector=(-1, 0))
        result = cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
            incident_scope={"inc-1"}, as_of="2027-01-01", top_k=2)
        assert result.eligible_count == 3
        assert result.truncated is True
        assert [item.asset_id for item in result] == ["a", "b"]
        with pytest.raises(CatalogError):
            cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
                incident_scope={"inc-1"}, as_of="2027-01-01", top_k=fbm_catalog._MAX_TOP_K + 1)
    finally:
        cat.close()


def test_asset_byte_limit_is_checked_on_write(tmp_path, monkeypatch):
    monkeypatch.setattr(fbm_catalog, "MAX_ASSET_BYTES", 8)
    cat = make_catalog(tmp_path)
    try:
        with pytest.raises(CatalogError, match="research-store limit"):
            add(cat, raw=b"x" * 9)
    finally:
        cat.close()


def test_oversized_corrupt_stored_asset_is_rejected_before_blob_read(tmp_path, monkeypatch):
    monkeypatch.setattr(fbm_catalog, "MAX_ASSET_BYTES", 8)
    cat = make_catalog(tmp_path)
    try:
        add(cat, raw=b"small")
        cat._db.execute("UPDATE assets SET raw=zeroblob(9)")
        cat._db.commit()
        with pytest.raises(CatalogError, match="research-store limit"):
            cat.get_raw(asset_id="a", source_revision="r1", representation="raw_fbm",
                actor="trusted-user", incident_scope={"inc-1"}, as_of="2027-01-01")
        with pytest.raises(CatalogError, match="research-store limit"):
            cat.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
                incident_scope={"inc-1"}, as_of="2027-01-01", top_k=1)
    finally:
        cat.close()


def test_get_raw_hides_out_of_scope_and_missing_identity_equally(tmp_path, monkeypatch):
    monkeypatch.setattr(fbm_catalog, "MAX_ASSET_BYTES", 8)
    cat = make_catalog(tmp_path)
    try:
        add(cat, aid="visible", incident="inc-1", raw=b"small")
        add(cat, aid="hidden", incident="inc-secret", raw=b"tiny")
        cat._db.execute("UPDATE assets SET raw=zeroblob(9) WHERE asset_id='hidden'")
        cat._db.commit()
        responses = []
        for identity in ("hidden", "missing"):
            try:
                cat.get_raw(asset_id=identity, source_revision="r1", representation="raw_fbm",
                    actor="trusted-user", incident_scope={"inc-1"}, as_of="2027-01-01")
            except CatalogError as exc:
                responses.append((type(exc), str(exc)))
        assert responses[0] == responses[1]
        assert "limit" not in responses[0][1]
    finally:
        cat.close()


def test_open_existing_rejects_malformed_schema_and_tampered_record(tmp_path):
    root = tmp_path / "gallery"
    cat = FBMEmbeddingCatalog(root, authorize=lambda *_: True)
    add(cat)
    cat._db.execute("UPDATE assets SET sha256=?", ("0" * 64,))
    cat._db.commit()
    with pytest.raises(CatalogError):
        cat.get_raw(asset_id="a", source_revision="r1", representation="raw_fbm",
            actor="trusted-user", incident_scope={"inc-1"}, as_of="2027-01-01")
    cat.close()
    reopened = FBMEmbeddingCatalog.open_existing(root, authorize=lambda *_: True)
    try:
        with pytest.raises(CatalogError):
            reopened.search(query_vector=(1, 0), spec=RAW, actor="trusted-user",
                incident_scope={"inc-1"}, as_of="2027-01-01", top_k=3)
    finally:
        reopened.close()

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / ".fbm-synthetic-research-gallery").write_text("synthetic-fbm-gallery-v1\n")
    (bad / "catalog.sqlite3").write_bytes(b"not sqlite")
    with pytest.raises(CatalogError):
        FBMEmbeddingCatalog.open_existing(bad, authorize=lambda *_: True)
