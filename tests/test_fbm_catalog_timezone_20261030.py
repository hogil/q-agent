import pytest

from research.fbm_embedding_catalog_20261030 import (
    CatalogError, EmbeddingSpec, FBMEmbeddingCatalog,
)


SPEC = EmbeddingSpec("synthetic", "a" * 64, "pre-v1", 2, "raw_fbm")
SCOPE = {"SYNTHETIC-INC"}


@pytest.fixture
def cat(tmp_path):
    catalog = FBMEmbeddingCatalog(tmp_path / "gallery", authorize=lambda *_: True)
    yield catalog
    catalog.close()


def add(catalog, asset_id, available_at):
    catalog.add(asset_id=asset_id, source_revision="r1", raw_bytes=asset_id.encode(),
                vector=(1, 0), spec=SPEC, source_time="2026-01-01T00:00:00Z",
                available_at=available_at, incident_id="SYNTHETIC-INC", lot_id=None,
                wafer_id=None, actor="synthetic", incident_scope=SCOPE)


def search(catalog, as_of, **kwargs):
    return catalog.search(query_vector=(1, 0), spec=SPEC, actor="synthetic",
                          incident_scope=SCOPE, as_of=as_of, top_k=20, **kwargs)


def raw(catalog, asset_id, as_of, **kwargs):
    return catalog.get_raw(asset_id=asset_id, source_revision="r1", representation="raw_fbm",
                           actor="synthetic", incident_scope=SCOPE, as_of=as_of, **kwargs)


def test_seoul_date_cutoff_uses_next_local_midnight_exclusive(cat):
    add(cat, "inside", "2026-10-30T14:59:59.999999Z")
    add(cat, "midnight", "2026-10-30T15:00:00.000000Z")  # Seoul 2026-10-31 00:00
    assert [x.asset_id for x in search(cat, "2026-10-30", timezone_name="Asia/Seoul")] == ["inside"]
    assert raw(cat, "inside", "2026-10-30", timezone_name="Asia/Seoul") == b"inside"
    with pytest.raises(CatalogError):
        raw(cat, "midnight", "2026-10-30", timezone_name="Asia/Seoul")


def test_timezone_date_cutoff_and_dst_day_length(cat):
    add(cat, "ny-inside", "2026-03-09T03:59:59.999999Z")
    add(cat, "ny-next-day", "2026-03-09T04:00:00.000000Z")
    assert [x.asset_id for x in search(cat, "2026-03-08", timezone_name="America/New_York")] == ["ny-inside"]
    assert raw(cat, "ny-inside", "2026-03-08", timezone_name="America/New_York") == b"ny-inside"
    with pytest.raises(CatalogError):
        raw(cat, "ny-next-day", "2026-03-08", timezone_name="America/New_York")


def test_default_utc_and_aware_timestamp_keep_existing_inclusive_semantics(cat):
    add(cat, "utc-end", "2026-10-30T23:59:59.999999Z")
    add(cat, "utc-next", "2026-10-31T00:00:00.000000Z")
    assert [x.asset_id for x in search(cat, "2026-10-30")] == ["utc-end"]
    assert [x.asset_id for x in search(cat, "2026-10-30T23:59:59.999999Z",
                                        timezone_name="Asia/Seoul")] == ["utc-end"]
    assert raw(cat, "utc-end", "2026-10-30") == b"utc-end"
    with pytest.raises(CatalogError):
        raw(cat, "utc-next", "2026-10-30")


@pytest.mark.parametrize("timezone_name", ["", "Mars/Olympus_Mons", "Not_A_Zone"])
def test_invalid_timezone_fails_closed_for_both_reads(cat, timezone_name):
    add(cat, "asset", "2026-10-30T12:00:00Z")
    with pytest.raises(CatalogError):
        search(cat, "2026-10-30", timezone_name=timezone_name)
    with pytest.raises(CatalogError):
        raw(cat, "asset", "2026-10-30", timezone_name=timezone_name)


def test_named_timezone_does_not_change_aware_timestamp_instant(cat):
    add(cat, "at-cutoff", "2026-10-30T15:00:00.000000Z")
    assert [x.asset_id for x in search(cat, "2026-10-31T00:00:00+09:00",
                                        timezone_name="America/New_York")] == ["at-cutoff"]
    assert raw(cat, "at-cutoff", "2026-10-31T00:00:00+09:00",
               timezone_name="America/New_York") == b"at-cutoff"
