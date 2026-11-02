"""Isolated, file-backed synthetic FBM embedding gallery for research only.

This module accepts caller-produced bytes and normalized vectors. It does not
perform image decoding, model inference, production authorization, or uploads.
"""

from __future__ import annotations

import hashlib
import bisect
import math
import os
import re
import sqlite3
import stat
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence


REPRESENTATIONS = {"raw_fbm", "object_id_yield"}
_MARKER = ".fbm-synthetic-research-gallery"
_MAX_CANDIDATES = 100_000
_MAX_TOP_K = 1_000
_MAX_SCOPE = 1_000
MAX_ASSET_BYTES = 64 * 1024 * 1024


class CatalogError(ValueError):
    """Invalid input or unavailable catalog operation."""


class AuthorizationError(PermissionError):
    """Access was not explicitly authorized by the injected policy."""


@dataclass(frozen=True)
class EmbeddingSpec:
    model_id: str
    checkpoint_sha256: str
    preprocess_version: str
    dimension: int
    representation: str


@dataclass(frozen=True)
class SearchResult:
    asset_id: str
    source_revision: str
    similarity: float
    representation: str
    model_id: str
    checkpoint_sha256: str
    preprocess_version: str
    dimension: int
    source_time: str
    available_at: str
    as_of: str
    lot_id: str | None
    wafer_id: str | None
    incident_id: str
    raw_sha256: str


@dataclass(frozen=True)
class SearchResponse:
    items: tuple[SearchResult, ...]
    eligible_count: int
    truncated: bool
    population_note: str = "Authorized scoped indexed population only; no exhaustive corpus claim."

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


@dataclass(frozen=True)
class AssetRecord:
    """Authorized synthetic source bytes and their catalog identity metadata."""

    raw_bytes: bytes
    asset_id: str
    source_revision: str
    representation: str
    incident_id: str
    lot_id: str | None
    wafer_id: str | None
    available_at: str
    sha256: str
    model_id: str
    preprocess_version: str
    checkpoint_sha256: str
    dimension: int


Authorize = Callable[[str, str, str], bool]


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise CatalogError(f"{field} must be a nonempty string")
    return value


def _utc_time(value: str, field: str, *, date_end: bool = False) -> str:
    """Normalize aware ISO datetimes to UTC; date-only cutoff means UTC day end."""
    _text(value, field)
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(parsed_date, time.max if date_end else time.min,
                                      tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timezone required")
            parsed = parsed.astimezone(timezone.utc)
    except ValueError as exc:
        raise CatalogError(f"{field} must be an ISO date or timezone-aware datetime") from exc
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _as_of_cutoff(value: str, *, timezone_name: str | None) -> tuple[str, str]:
    """Return canonical UTC cutoff and SQL comparator for an as-of value."""
    _text(value, "as_of")
    if timezone_name is not None:
        try:
            zone = ZoneInfo(_text(timezone_name, "timezone_name"))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise CatalogError("timezone_name must be a valid IANA timezone") from exc
    else:
        zone = None
    if len(value) == 10 and zone is not None:
        try:
            next_day = date.fromisoformat(value) + timedelta(days=1)
            midnight = datetime.combine(next_day, time.min, tzinfo=zone)
        except (ValueError, OverflowError) as exc:
            raise CatalogError("as_of must be an ISO date or timezone-aware datetime") from exc
        return (midnight.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"), "<")
    return _utc_time(value, "as_of", date_end=True), "<="


def _vector(values: Sequence[float], dimension: int) -> tuple[float, ...]:
    if len(values) != dimension:
        raise CatalogError("vector dimension mismatch")
    result = tuple(float(v) for v in values)
    if not all(math.isfinite(v) for v in result):
        raise CatalogError("vector values must be finite")
    norm = math.sqrt(sum(v * v for v in result))
    if norm == 0 or abs(norm - 1.0) > 1e-5:
        raise CatalogError("vector must be nonzero and L2-normalized")
    return tuple(v / norm for v in result)


def _spec(spec: EmbeddingSpec) -> EmbeddingSpec:
    _text(spec.model_id, "model_id")
    if not isinstance(spec.checkpoint_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", spec.checkpoint_sha256):
        raise CatalogError("checkpoint_sha256 must be a 64-character SHA-256 hex digest")
    _text(spec.preprocess_version, "preprocess_version")
    if spec.representation not in REPRESENTATIONS:
        raise CatalogError("unsupported representation")
    if isinstance(spec.dimension, bool) or not isinstance(spec.dimension, int) or spec.dimension <= 0:
        raise CatalogError("dimension must be a positive integer")
    return spec


class FBMEmbeddingCatalog:
    """Synthetic research gallery; callback/scope are trusted-caller inputs, not site ACL.

    source_time describes source observation/creation; available_at gates retrieval.
    Source-time semantics and caller authorization are not validated against production.
    Callers provide a trusted incident scope; it is not derived or verified here.
    SHA-256 values detect accidental corruption, not authentic provenance.
    """

    def __init__(self, root: str | os.PathLike[str], *, authorize: Authorize | None):
        if authorize is None or not callable(authorize):
            raise AuthorizationError("trusted authorize callback is required")
        raw_root = Path(root).absolute()
        if raw_root.exists() or raw_root.is_symlink():
            raise CatalogError("catalog creation requires a new path")
        _reject_symlink_parents(raw_root)
        raw_root.mkdir(parents=True, exist_ok=False)
        self.root = raw_root.resolve(strict=True)
        self._authorize = authorize
        (self.root / _MARKER).write_text("synthetic-fbm-gallery-v1\n", encoding="ascii")
        self._db = sqlite3.connect(str(self.root / "catalog.sqlite3"))
        self._initialize_schema()

    @classmethod
    def open_existing(cls, root: str | os.PathLike[str], *, authorize: Authorize | None):
        """Explicitly reopen a catalog created by this module after marker validation."""
        if authorize is None or not callable(authorize):
            raise AuthorizationError("trusted authorize callback is required")
        path = Path(root).absolute()
        _reject_symlink_parents(path)
        if path.is_symlink() or not path.is_dir():
            raise CatalogError("catalog path must be a real directory")
        marker = path / _MARKER
        db_path = path / "catalog.sqlite3"
        if (_is_reparse_point(marker) or _is_reparse_point(db_path)
                or not marker.is_file() or not db_path.is_file()):
            raise CatalogError("catalog marker or database is missing or unsafe")
        try:
            marker_content = marker.read_text(encoding="ascii")
        except (OSError, UnicodeError) as exc:
            raise CatalogError("catalog marker is malformed or unreadable") from exc
        if marker_content != "synthetic-fbm-gallery-v1\n":
            raise CatalogError("unrecognized catalog marker")
        instance = cls.__new__(cls)
        instance.root = path.resolve(strict=True)
        instance._authorize = authorize
        try:
            instance._db = sqlite3.connect(str(db_path))
            instance._initialize_schema(create=False)
        except (sqlite3.DatabaseError, OSError) as exc:
            raise CatalogError("catalog database is malformed or unreadable") from exc
        return instance

    def _initialize_schema(self, *, create: bool = True) -> None:
        self._db.execute("PRAGMA foreign_keys = ON")
        statement = """
            CREATE TABLE assets (
              asset_id TEXT NOT NULL, revision TEXT NOT NULL,
              representation TEXT NOT NULL, raw BLOB NOT NULL, sha256 TEXT NOT NULL,
              vector BLOB NOT NULL, dimension INTEGER NOT NULL,
              model_id TEXT NOT NULL, preprocess_version TEXT NOT NULL,
              checkpoint_sha256 TEXT NOT NULL, source_time TEXT NOT NULL, available_at TEXT NOT NULL,
              lot_id TEXT, wafer_id TEXT,
              incident_id TEXT NOT NULL,
            PRIMARY KEY(asset_id, revision, representation)
            );
            -- Synthetic query ID + revision + representation is globally unique by catalog key only;
            -- the key does not prove physical asset identity or provenance.
            CREATE INDEX asset_identity ON assets(asset_id, representation, sha256);
        """
        if create:
            self._db.executescript(statement)
            self._db.execute("PRAGMA user_version = 1")
            self._db.commit()
        else:
            check = self._db.execute("PRAGMA quick_check").fetchone()
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            exists = self._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assets'").fetchone()
            columns = [row[1] for row in self._db.execute("PRAGMA table_info(assets)").fetchall()] if exists else []
            expected = ["asset_id", "revision", "representation", "raw", "sha256", "vector",
                        "dimension", "model_id", "preprocess_version", "checkpoint_sha256",
                        "source_time", "available_at", "lot_id", "wafer_id", "incident_id"]
            indexes = {row[1] for row in self._db.execute("PRAGMA index_list(assets)").fetchall()} if exists else set()
            if (check is None or check[0] != "ok" or version != 1 or columns != expected
                    or "sqlite_autoindex_assets_1" not in indexes or "asset_identity" not in indexes):
                self._db.close()
                raise CatalogError("unsupported or invalid catalog database")

    def close(self) -> None:
        self._db.close()

    def add(self, *, asset_id: str, source_revision: str, raw_bytes: bytes,
            vector: Sequence[float], spec: EmbeddingSpec, source_time: str, available_at: str,
            incident_id: str, lot_id: str | None, wafer_id: str | None,
            actor: str, incident_scope: Iterable[str]) -> str:
        spec = _spec(spec)
        asset_id = _text(asset_id, "asset_id")
        source_revision = _text(source_revision, "source_revision")
        source_time = _utc_time(source_time, "source_time")
        available_at = _utc_time(available_at, "available_at")
        incident_id = _text(incident_id, "incident_id")
        actor = _text(actor, "actor")
        if not isinstance(raw_bytes, bytes) or not raw_bytes:
            raise CatalogError("raw_bytes must be nonempty bytes")
        if len(raw_bytes) > MAX_ASSET_BYTES:
            raise CatalogError(f"source exceeds research-store limit ({MAX_ASSET_BYTES} bytes)")
        _optional_text(lot_id, "lot_id")
        _optional_text(wafer_id, "wafer_id")
        scope = {_text(s, "incident scope member") for s in incident_scope}
        _validate_scope(scope)
        if incident_id not in scope:
            raise AuthorizationError("incident is outside trusted caller scope")
        self._check_authorized(actor, incident_id, "write")
        vec = _vector(vector, spec.dimension)
        digest = hashlib.sha256(raw_bytes).hexdigest()
        existing = self._db.execute(
            """SELECT raw, sha256, vector, dimension, model_id, preprocess_version,
                    checkpoint_sha256, source_time, available_at, lot_id, wafer_id, incident_id
                    FROM assets WHERE asset_id=? AND revision=? AND representation=?""",
            (asset_id, source_revision, spec.representation),
        ).fetchone()
        if existing:
            stored = (bytes(existing[0]), existing[2], existing[3], existing[4], existing[5],
                      existing[6], existing[7], existing[8], existing[9], existing[10], existing[11])
            incoming = (raw_bytes, _pack_vector(vec), spec.dimension, spec.model_id,
                        spec.preprocess_version, spec.checkpoint_sha256, source_time, available_at,
                        lot_id, wafer_id, incident_id)
            if existing[1] != digest or stored != incoming:
                raise CatalogError("identity/revision already exists with conflicting immutable metadata")
            return digest
        self._db.execute("""INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (asset_id, source_revision, spec.representation, sqlite3.Binary(raw_bytes), digest,
             _pack_vector(vec), spec.dimension, spec.model_id, spec.preprocess_version,
             spec.checkpoint_sha256, source_time, available_at, lot_id, wafer_id, incident_id))
        self._db.commit()
        return digest

    def get_raw(self, *, asset_id: str, source_revision: str, representation: str,
                actor: str, incident_scope: Iterable[str], as_of: str,
                timezone_name: str | None = None) -> bytes:
        return self.get_asset(asset_id=asset_id, source_revision=source_revision,
            representation=representation, actor=actor, incident_scope=incident_scope,
            as_of=as_of, timezone_name=timezone_name).raw_bytes

    def get_asset(self, *, asset_id: str, source_revision: str, representation: str,
                  actor: str, incident_scope: Iterable[str], as_of: str,
                  timezone_name: str | None = None) -> AssetRecord:
        """Read bytes plus identity from the authorized, available synthetic scope."""
        if representation not in REPRESENTATIONS:
            raise CatalogError("unsupported representation")
        actor = _text(actor, "actor")
        cutoff, cutoff_operator = _as_of_cutoff(as_of, timezone_name=timezone_name)
        scope = {_text(s, "incident scope member") for s in incident_scope}
        _validate_scope(scope)
        self._check_scope_authorized(actor, scope, "read")
        if not scope:
            raise CatalogError("asset unavailable in authorized scope")
        placeholders = ",".join("?" for _ in scope)
        identity = (asset_id, source_revision, representation)
        row = self._db.execute(
            f"""SELECT length(raw) FROM assets WHERE asset_id=? AND revision=?
                AND representation=? AND incident_id IN ({placeholders}) AND available_at{cutoff_operator}?""",
            (*identity, *sorted(scope), cutoff),
        ).fetchone()
        if row is None:
            raise CatalogError("asset unavailable in authorized scope")
        if row[0] > MAX_ASSET_BYTES:
            raise CatalogError(f"stored source exceeds research-store limit ({MAX_ASSET_BYTES} bytes)")
        row = self._db.execute(
            f"""SELECT raw, sha256, vector, dimension, model_id, preprocess_version,
                checkpoint_sha256, incident_id, available_at, source_time, asset_id, revision,
                representation, lot_id, wafer_id FROM assets
                WHERE asset_id=? AND revision=? AND representation=?
                AND incident_id IN ({placeholders}) AND available_at{cutoff_operator}?""",
            (*identity, *sorted(scope), cutoff),
        ).fetchone()
        if row is None:
            raise CatalogError("asset unavailable in authorized scope")
        raw = bytes(row[0])
        self._validate_record_integrity(raw, (row[1], row[2], row[3], row[4], row[5],
            row[6], row[7], row[8], row[9]))
        _optional_text(row[13], "stored lot_id")
        _optional_text(row[14], "stored wafer_id")
        return AssetRecord(raw, row[10], row[11], row[12], row[7], row[13], row[14],
                           row[8], row[1], row[4], row[5], row[6], row[3])

    def search(self, *, query_vector: Sequence[float], spec: EmbeddingSpec,
               actor: str, incident_scope: Iterable[str], as_of: str, top_k: int,
               exclude_asset_id: str | None = None,
               exclude_sha256: str | None = None,
               exclude_asset_revision: tuple[str, str] | None = None,
               timezone_name: str | None = None) -> SearchResponse:
        spec = _spec(spec)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise CatalogError("top_k must be positive")
        if top_k > _MAX_TOP_K:
            raise CatalogError("top_k exceeds configured maximum")
        cutoff, cutoff_operator = _as_of_cutoff(as_of, timezone_name=timezone_name)
        actor = _text(actor, "actor")
        scope = {_text(s, "incident scope member") for s in incident_scope}
        _validate_scope(scope)
        self._check_scope_authorized(actor, scope, "read")
        q = _vector(query_vector, spec.dimension)
        if not scope:
            return SearchResponse((), 0, False)
        if exclude_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", exclude_sha256):
            raise CatalogError("exclude_sha256 must be a 64-character SHA-256 hex digest")
        if exclude_asset_id is not None:
            exclude_asset_id = _text(exclude_asset_id, "exclude_asset_id")
        if exclude_asset_revision is not None:
            if (not isinstance(exclude_asset_revision, tuple) or len(exclude_asset_revision) != 2
                    or any(not isinstance(value, str) or not value or "\x00" in value
                           for value in exclude_asset_revision)):
                raise CatalogError("exclude_asset_revision must be a pair of nonempty strings")
        placeholders = ",".join("?" for _ in scope)
        hash_clause = " AND sha256<>?" if exclude_sha256 is not None else ""
        asset_clause = " AND asset_id<>?" if exclude_asset_id is not None else ""
        revision_clause = " AND NOT (asset_id=? AND revision=?)" if exclude_asset_revision is not None else ""
        # Scope and all contract values are bound before candidate limiting.
        sql = f"""SELECT asset_id, revision, vector, source_time, lot_id,
            wafer_id, incident_id, sha256, available_at, length(raw) FROM assets WHERE representation=? AND model_id=?
            AND preprocess_version=? AND checkpoint_sha256=? AND dimension=? AND available_at{cutoff_operator}?
            AND incident_id IN ({placeholders}){hash_clause}{asset_clause}{revision_clause}
            ORDER BY asset_id,revision LIMIT ?"""
        parameters = (spec.representation, spec.model_id, spec.preprocess_version,
             spec.checkpoint_sha256, spec.dimension, cutoff, *sorted(scope))
        if exclude_sha256 is not None:
            parameters += (exclude_sha256.lower(),)
        if exclude_asset_id is not None:
            parameters += (exclude_asset_id,)
        if exclude_asset_revision is not None:
            parameters += exclude_asset_revision
        parameters += (_MAX_CANDIDATES + 1,)
        cursor = self._db.execute(sql, parameters)
        best: list[tuple[tuple[float, str, str], SearchResult]] = []
        eligible_count = 0
        while True:
            row = cursor.fetchone()
            if row is None:
                break
            eligible_count += 1
            if eligible_count > _MAX_CANDIDATES:
                raise CatalogError("candidate limit exceeded; narrow scope or time range")
            aid, rev, blob, source_time, lot, wafer, incident, digest, available_at, raw_length = row
            if raw_length > MAX_ASSET_BYTES:
                raise CatalogError(f"stored source exceeds research-store limit ({MAX_ASSET_BYTES} bytes)")
            raw_row = self._db.execute("SELECT raw FROM assets WHERE asset_id=? AND revision=? AND representation=?",
                                       (aid, rev, spec.representation)).fetchone()
            raw = bytes(raw_row[0])
            self._validate_record_integrity(raw, (digest, blob, spec.dimension, spec.model_id,
                spec.preprocess_version, spec.checkpoint_sha256, incident, available_at, source_time))
            vec = _unpack_vector(blob, spec.dimension)
            similarity = sum(x * y for x, y in zip(q, vec))
            if not math.isfinite(similarity):
                raise CatalogError("non-finite similarity from stored vector")
            similarity = min(1.0, max(-1.0, similarity))
            item = SearchResult(aid, rev, similarity, spec.representation,
                spec.model_id, spec.checkpoint_sha256, spec.preprocess_version, spec.dimension, source_time, available_at,
                cutoff, lot, wafer, incident, digest)
            key = (-item.similarity, item.asset_id, item.source_revision)
            bisect.insort(best, (key, item))
            if len(best) > top_k:
                best.pop()
        return SearchResponse(tuple(pair[1] for pair in best), eligible_count,
                              eligible_count > top_k)

    def _check_authorized(self, actor: str, incident_id: str, operation: str) -> None:
        try:
            allowed = self._authorize(actor, incident_id, operation)
        except Exception as exc:
            raise AuthorizationError("authorization callback failed") from exc
        if allowed is not True:
            raise AuthorizationError("access denied")

    def _check_scope_authorized(self, actor: str, scope: set[str], operation: str) -> None:
        for incident_id in sorted(scope):
            self._check_authorized(actor, incident_id, operation)

    @staticmethod
    def _validate_record_integrity(raw: bytes, fields: Sequence[object]) -> None:
        digest, vector_blob, dimension, model_id, preprocess_version, checkpoint_hash, incident, available_at, source_time = fields
        if hashlib.sha256(raw).hexdigest() != digest:
            raise CatalogError("stored source hash mismatch")
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise CatalogError("invalid stored dimension")
        vector = _unpack_vector(vector_blob, dimension)
        norm = math.sqrt(sum(v * v for v in vector))
        if not all(math.isfinite(v) for v in vector) or abs(norm - 1.0) > 1e-5:
            raise CatalogError("invalid stored vector")
        _text(model_id, "stored model_id")
        _text(preprocess_version, "stored preprocess_version")
        if not isinstance(checkpoint_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", checkpoint_hash):
            raise CatalogError("invalid stored checkpoint hash")
        _text(incident, "stored incident_id")
        if _utc_time(available_at, "stored available_at") != available_at:
            raise CatalogError("invalid stored available_at")
        if _utc_time(source_time, "stored source_time") != source_time:
            raise CatalogError("invalid stored source_time")


def _optional_text(value: str | None, field: str) -> None:
    if value is not None:
        _text(value, field)


def _pack_vector(vector: Sequence[float]) -> bytes:
    import struct
    return struct.pack(f"!{len(vector)}d", *vector)


def _unpack_vector(blob: bytes, dimension: int) -> tuple[float, ...]:
    import struct
    if len(blob) != dimension * 8:
        raise CatalogError("corrupt stored vector")
    return struct.unpack(f"!{dimension}d", blob)


def _reject_symlink_parents(path: Path) -> None:
    """Reject symlinks and Windows reparse points without traversing them."""
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if _is_reparse_point(current):
            raise CatalogError("symlink or reparse-point catalog paths are not allowed")


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & reparse_flag)


def _validate_scope(scope: set[str]) -> None:
    if len(scope) > _MAX_SCOPE:
        raise CatalogError("incident scope exceeds configured maximum")
