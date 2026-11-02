"""Train-only tabular anomaly analysis for explicitly synthetic chip fixtures.

This module is a demo foundation, not a production measurement model. Feature
metadata and all preprocessing are learned from the training-normal partition.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote
import re
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.covariance import MinCovDet
from sklearn.decomposition import PCA

_SHA_CACHE: dict[tuple[str, int, int, int, int], str] = {}


def temporal_group_split(groups: np.ndarray, timestamps: np.ndarray, holdout_fraction: float = 0.2,
                         *, return_metadata: bool = False):
    """Hold out latest whole groups and purge groups overlapping the time boundary."""
    if not 0.05 <= holdout_fraction <= 0.5:
        raise ValueError("holdout_fraction must be in 0.05..0.5")
    group_ranges: dict[str, list[float]] = {}
    for group, stamp in zip(groups.tolist(), timestamps.tolist()):
        try:
            timestamp = datetime.fromisoformat(str(stamp)).timestamp()
        except (TypeError, ValueError, OverflowError):
            raise ValueError("invalid event timestamp for temporal group split") from None
        bounds = group_ranges.setdefault(str(group), [timestamp, timestamp])
        bounds[0] = min(bounds[0], timestamp)
        bounds[1] = max(bounds[1], timestamp)
    ordered = sorted(group_ranges, key=lambda key: (group_ranges[key][0], group_ranges[key][1], key))
    holdout_count = max(1, int(np.ceil(len(ordered) * holdout_fraction)))
    held = set(ordered[-holdout_count:])
    holdout_boundary = min(group_ranges[group][0] for group in held)
    train_groups = {group for group in ordered[:-holdout_count]
                    if group_ranges[group][1] < holdout_boundary}
    purged_groups = set(group_ranges) - held - train_groups
    if len(train_groups) < 2 or not held:
        raise ValueError("temporal overlap purge left fewer than two train groups")
    train = np.asarray([str(group) in train_groups for group in groups], dtype=bool)
    holdout = np.asarray([str(group) in held for group in groups], dtype=bool)
    purged = np.asarray([str(group) in purged_groups for group in groups], dtype=bool)
    metadata = {"train_groups": sorted(train_groups), "holdout_groups": sorted(held),
                "purged_groups": sorted(purged_groups), "holdout_boundary_epoch": holdout_boundary,
                "train_max_epoch": max(group_ranges[group][1] for group in train_groups),
                "holdout_min_epoch": min(group_ranges[group][0] for group in held)}
    if not metadata["train_max_epoch"] < metadata["holdout_min_epoch"]:
        raise ValueError("temporal split did not preserve a strict time gap")
    return (train, holdout, purged, metadata) if return_metadata else (train, holdout)


def bounded_profile(X: np.ndarray, feature_metadata: list[dict[str, Any]], labels: np.ndarray,
                    groups: np.ndarray, timestamps: np.ndarray, train_mask: np.ndarray,
                    chip_keys: list[tuple] | None = None, holdout_mask: np.ndarray | None = None,
                    purge_mask: np.ndarray | None = None) -> dict[str, Any]:
    """Return bounded schema/quality statistics; never emit raw chip rows."""
    matrix = np.asarray(X, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(feature_metadata):
        raise ValueError("feature matrix/catalogue shape mismatch")
    if not 1 <= matrix.shape[1] <= 512 or not 1 <= matrix.shape[0] <= 250_000:
        raise ValueError("matrix outside bounded synthetic profile limits")
    if len(labels) != len(matrix) or len(groups) != len(matrix) or len(timestamps) != len(matrix):
        raise ValueError("chip metadata length mismatch")
    profiles = []
    for index, spec in enumerate(feature_metadata):
        col = matrix[:, index]
        finite = col[np.isfinite(col)]
        unit_ok = bool(spec.get("unit")) and bool(spec.get("unit_spec_consistent", True))
        lower, upper = spec.get("lower_limit"), spec.get("upper_limit")
        spec_ok = (isinstance(lower, (int, float)) and isinstance(upper, (int, float))
                   and np.isfinite(lower) and np.isfinite(upper) and lower < upper)
        profiles.append({"name": str(spec["name"]), "unit": spec.get("unit"),
                         "non_null": int(finite.size), "missing_count": int(col.size - finite.size),
                         "missing_rate": round(float((col.size - finite.size) / col.size), 6),
                         "distinct_count": int(np.unique(finite).size),
                         "spec_consistent": bool(unit_ok and spec_ok),
                         "unit_spec_consistent": bool(unit_ok),
                         "lower_limit": lower if spec_ok else None,
                         "upper_limit": upper if spec_ok else None})
    keys = chip_keys if chip_keys is not None else [(index,) for index in range(len(matrix))]
    if len(keys) != len(matrix):
        raise ValueError("chip key length mismatch")
    key_hashes = [hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(",", ":"),
                                                   default=str).encode("utf-8")).digest()
                  for key in keys]
    duplicate_count = int(len(key_hashes) - len(set(key_hashes)))
    train_normal = train_mask & (np.asarray(labels) == 0)
    holdout_mask = ~train_mask if holdout_mask is None else holdout_mask
    purge_mask = np.zeros(len(matrix), dtype=bool) if purge_mask is None else purge_mask
    return {"synthetic": True, "chip_count": int(len(matrix)), "feature_count": int(matrix.shape[1]),
            "group_count": int(np.unique(groups).size), "duplicate_chip_rows": duplicate_count,
            "missing_cells": int(np.isnan(matrix).sum()),
            "missing_rate": round(float(np.isnan(matrix).mean()), 6),
            "train_chip_count": int(train_mask.sum()), "holdout_chip_count": int(holdout_mask.sum()),
            "purged_chip_count": int(purge_mask.sum()),
            "train_normal_chip_count": int(train_normal.sum()),
            "train_group_count": int(np.unique(groups[train_mask]).size),
            "holdout_group_count": int(np.unique(groups[holdout_mask]).size),
            "purged_group_count": int(np.unique(groups[purge_mask]).size),
            "feature_profile": profiles,
            "notice": "Synthetic feature catalogue and results; not validated against site data."}


def fit_global_model(X: np.ndarray, labels: np.ndarray, groups: np.ndarray, timestamps: np.ndarray,
                     feature_metadata: list[dict[str, Any]], *, seed: int = 20261024,
                     holdout_fraction: float = 0.2, fit_sample_limit: int = 4096):
    """Fit a single model on a bounded train-normal sample and score every row."""
    values = np.asarray(X)
    y = np.asarray(labels, dtype=int)
    groups = np.asarray(groups).astype(str)
    timestamps = np.asarray(timestamps).astype(str)
    if values.ndim != 2 or values.shape[1] != len(feature_metadata):
        raise ValueError("feature matrix/catalogue shape mismatch")
    if type(fit_sample_limit) is not int or not 128 <= fit_sample_limit <= 8192:
        raise ValueError("fit_sample_limit must be in 128..8192")
    train_mask, holdout_mask, purge_mask, split_metadata = temporal_group_split(
        groups, timestamps, holdout_fraction, return_metadata=True)
    fit_candidates = np.flatnonzero(train_mask & (y == 0))
    if len(fit_candidates) <= 2:
        raise ValueError("insufficient train-normal chips")
    if len(fit_candidates) > fit_sample_limit:
        selection = np.random.default_rng(seed).choice(fit_candidates, size=fit_sample_limit, replace=False)
        fit_indexes = np.sort(selection)
    else:
        fit_indexes = fit_candidates

    train = np.asarray(values[fit_indexes], dtype=float)
    if np.any(np.isfinite(train).sum(axis=0) == 0):
        raise ValueError("a feature is entirely null in the selected train-normal sample")
    medians = np.nanmedian(train, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    imputed = np.where(np.isnan(train), medians, train)
    center = np.median(imputed, axis=0)
    mad = np.median(np.abs(imputed - center), axis=0) * 1.4826
    scale = np.where(mad > 1e-9, mad, 1.0)
    standardized_train = np.clip((imputed - center) / scale, -20.0, 20.0)
    component_count = min(16, standardized_train.shape[1], len(fit_indexes) - 1)
    pca = PCA(n_components=component_count, svd_solver="full", random_state=seed)
    train_scores = pca.fit_transform(standardized_train)
    robust_cov = MinCovDet(random_state=seed, support_fraction=0.75).fit(train_scores)
    train_covariance_scores = robust_cov.mahalanobis(train_scores)
    train_residual_scores = np.mean((standardized_train - pca.inverse_transform(train_scores)) ** 2, axis=1)
    covariance_threshold = float(np.quantile(train_covariance_scores, 0.99))
    residual_threshold = float(np.quantile(train_residual_scores, 0.99))
    model = {"medians": medians, "center": center, "scale": scale, "pca": pca,
             "robust_cov": robust_cov, "covariance_threshold": covariance_threshold,
             "residual_threshold": residual_threshold, "fit_indexes": fit_indexes,
             "fit_sample_limit": fit_sample_limit, "component_count": component_count}
    covariance_scores, residual_scores = score_components_matrix(values, model)
    covariance_flagged = covariance_scores > covariance_threshold
    residual_flagged = residual_scores > residual_threshold
    flagged = covariance_flagged | residual_flagged
    held = np.asarray(holdout_mask, dtype=bool)
    true = y[held] == 1
    def metrics(predicted):
        predicted = predicted[held]
        tp = int(np.sum(true & predicted)); fp = int(np.sum(~true & predicted))
        fn = int(np.sum(true & ~predicted)); tn = int(np.sum(~true & ~predicted))
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "precision": round(tp / (tp + fp), 6) if tp + fp else None,
                "sensitivity": round(tp / (tp + fn), 6) if tp + fn else None,
                "specificity": round(tn / (tn + fp), 6) if tn + fp else None}
    metric_report = {"combined": metrics(flagged), "covariance": metrics(covariance_flagged),
                     "residual": metrics(residual_flagged),
                     "synthetic_rule_label": "measurement outside configured synthetic limits; heuristic label, not independent ground truth"}
    model["distances"] = covariance_scores
    model["residual_scores"] = residual_scores
    model["covariance_flagged"] = covariance_flagged
    model["residual_flagged"] = residual_flagged
    model["train_mask"] = train_mask
    model["holdout_mask"] = holdout_mask
    model["purge_mask"] = purge_mask
    model["split_metadata"] = split_metadata
    model["metrics"] = metric_report
    return model


def score_matrix(X: np.ndarray, model: dict[str, Any], *, batch_size: int = 8192) -> np.ndarray:
    """Transform and score rows in bounded batches."""
    return score_components_matrix(X, model, batch_size=batch_size)[0]


def score_components_matrix(X: np.ndarray, model: dict[str, Any], *, batch_size: int = 8192):
    """Return PCA-space robust covariance and orthogonal residual scores."""
    values = np.asarray(X)
    covariance = np.empty(len(values), dtype=np.float64)
    residual = np.empty(len(values), dtype=np.float64)
    for start in range(0, len(values), batch_size):
        end = min(len(values), start + batch_size)
        block = np.asarray(values[start:end], dtype=float)
        block = np.where(np.isnan(block), model["medians"], block)
        standardized = np.clip((block - model["center"]) / model["scale"], -20.0, 20.0)
        scores = model["pca"].transform(standardized)
        covariance[start:end] = model["robust_cov"].mahalanobis(scores)
        reconstruction = model["pca"].inverse_transform(scores)
        residual[start:end] = np.mean((standardized - reconstruction) ** 2, axis=1)
    return covariance, residual


def feature_deviations(X: np.ndarray, model: dict[str, Any], feature_metadata: list[dict[str, Any]],
                       *, top_k: int = 5) -> list[list[dict[str, Any]]]:
    block = np.asarray(X, dtype=float)
    block = np.where(np.isnan(block), model["medians"], block)
    standardized = np.clip((block - model["center"]) / model["scale"], -20.0, 20.0)
    indices = np.argsort(-np.abs(standardized), axis=1)[:, :top_k]
    result = []
    for row_index, feature_indexes in enumerate(indices):
        result.append([{"feature": str(feature_metadata[j]["name"]),
                        "robust_deviation": round(float(abs(standardized[row_index, j])), 4),
                        "unit": feature_metadata[j].get("unit")}
                       for j in feature_indexes])
    return result


def _sqlid(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[^\W\d]\w*", value, re.UNICODE):
        raise ValueError("invalid configured SQL identifier")
    return '"' + value.replace('"', '""') + '"'


def _readonly(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _sha256(path: Path, *, force: bool = False) -> str:
    stat = path.stat()
    key = (str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    if not force and key in _SHA_CACHE:
        return _SHA_CACHE[key]
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    result = digest.hexdigest()
    _SHA_CACHE[key] = result
    return result


def _data_contract_hash(settings) -> str:
    """Ignore unrelated LLM/path overlays while pinning the tabular read contract."""
    data = settings.data
    platform = data["platform"]
    contract = {"environment": data["environment"], "tables": data["tables"],
        "relations": data["relations"], "arrays": data["arrays"],
        "database_dialect": data["database"]["dialect"],
        "timezone": data["runtime"]["timezone"],
        "platform": {"enabled": platform["enabled"], "seed": platform["seed"],
                     "tables": platform["tables"], "tabular": platform.get("tabular", {})}}
    return hashlib.sha256(json.dumps(contract, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()


def _source_paths(settings):
    cfg = settings.data.get("platform", {})
    tabular = cfg.get("tabular", {})
    if (not cfg.get("enabled") or not tabular.get("enabled")
            or settings.data.get("environment") not in ("demo", "test")):
        raise ValueError("platform.tabular requires enabled synthetic demo/test configuration")
    data_root = Path(settings.data["paths"]["data_root"]).resolve()
    subdirectory = Path(tabular.get("subdirectory", ""))
    if subdirectory.is_absolute() or not str(subdirectory) or ".." in subdirectory.parts:
        raise ValueError("platform.tabular.subdirectory must be a nonempty relative path without parent traversal")
    target_root = (data_root / subdirectory).resolve()
    try:
        target_root.relative_to(data_root)
    except ValueError:
        raise ValueError("tabular output must remain inside paths.data_root") from None
    source_db = Path(settings.data["database"]["sqlite_file"]).resolve()
    manifest_path = data_root / "platform-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("synthetic") is not True or not manifest.get("sha256", {}).get("database"):
        raise ValueError("synthetic platform manifest/database hash is required")
    actual_hash = _sha256(source_db)
    if actual_hash != manifest["sha256"]["database"]:
        raise ValueError("PLATFORM_SOURCE_HASH_MISMATCH")
    try:
        cutoff = datetime.combine(date.fromisoformat(manifest["as_of"]) + timedelta(days=1), time.min,
                                  ZoneInfo(settings.data["runtime"]["timezone"])).isoformat()
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid platform manifest source cutoff") from None
    return cfg, tabular, data_root, target_root, source_db, manifest, actual_hash, cutoff


def _measure_mapping(settings):
    platform = settings.data["platform"]
    measure = platform["tables"]["measure"]
    core = settings.data["tables"]
    for key in ("incident_id", "lot_id", "wafer_id", "chip_id", "item", "value", "unit",
                "lower_limit", "upper_limit", "die_x", "die_y", "occurred_at", "available_at", "synthetic"):
        if not measure["columns"].get(key):
            raise ValueError("platform measure mapping lacks a required feature column")
    return measure, core


def _measure_from_sql(settings, cutoff: str, *, incident_ids: list[str] | None = None):
    measure, core = _measure_mapping(settings)
    relations = settings.data["relations"]
    mtab = _sqlid(measure["name"])
    mc = lambda key: "m." + _sqlid(measure["columns"][key])
    itab, ltab, wtab = (_sqlid(core[name]["name"]) for name in ("incident", "lot_list", "wafer_list"))
    ic = lambda key: "i." + _sqlid(core["incident"]["columns"][key])
    lc = lambda key: "l." + _sqlid(core["lot_list"]["columns"][key])
    wc = lambda key: "w." + _sqlid(core["wafer_list"]["columns"][key])
    incident_key = relations["incident_parent_key"]
    if relations.get("wafer_scope") != "incident_affected":
        raise ValueError("tabular model requires configured incident-affected wafer scope")
    where = [mc("synthetic") + "=1", "julianday(" + mc("occurred_at") + ")<julianday(?)",
              "julianday(" + mc("available_at") + ")<julianday(?)",
              "EXISTS (SELECT 1 FROM " + itab + " i WHERE " + ic("incident_id") + "=" + mc("incident_id") + ")",
              "EXISTS (SELECT 1 FROM " + ltab + " l JOIN " + itab + " i ON " + lc("incident_ref")
              + "=" + ic(incident_key) + " WHERE " + ic("incident_id") + "=" + mc("incident_id")
              + " AND " + lc("lot_id") + "=" + mc("lot_id") + ")",
              "EXISTS (SELECT 1 FROM " + wtab + " w JOIN " + itab + " i ON " + wc("incident_ref")
              + "=" + ic(incident_key) + " WHERE " + ic("incident_id") + "=" + mc("incident_id")
              + " AND " + wc("lot_id") + "=" + mc("lot_id") + " AND " + wc("wafer_id")
              + "=" + mc("wafer_id") + ")"]
    params: list[Any] = [cutoff, cutoff]
    if incident_ids is not None:
        where.append(mc("incident_id") + " IN (" + ",".join("?" for _ in incident_ids) + ")")
        params.extend(incident_ids)
    sql = (" FROM " + mtab + " m WHERE " + " AND ".join(where))
    selected = ["incident_id", "lot_id", "wafer_id", "chip_id", "die_x", "die_y", "stage",
                "item", "value", "unit", "lower_limit", "upper_limit", "occurred_at", "available_at"]
    if not measure["columns"].get("stage"):
        selected.remove("stage")
    expressions = [mc(key) + " AS " + _sqlid(key) for key in selected]
    return sql, params, expressions, measure


def build_platform_tabular(settings) -> dict[str, Any]:
    """Build one configured wide synthetic chip table and one global model."""
    cfg, tabular, data_root, target_root, source_path, manifest, source_hash, cutoff = _source_paths(settings)
    if target_root.exists():
        raise FileExistsError("configured platform tabular directory exists; refusing overwrite")
    feature_count = tabular.get("feature_count", 128)
    fit_limit = tabular.get("fit_sample_limit", 4096)
    if type(feature_count) is not int or not 2 <= feature_count <= 512:
        raise ValueError("platform.tabular.feature_count must be in 2..512")
    if type(fit_limit) is not int or not 128 <= fit_limit <= 8192:
        raise ValueError("platform.tabular.fit_sample_limit must be in 128..8192")
    sql, params, expressions, measure = _measure_from_sql(settings, cutoff)
    source_feature_sql = ("SELECT " + ",".join("m." + _sqlid(measure["columns"][key]) + " AS " + _sqlid(key)
                         for key in ("item", "unit", "lower_limit", "upper_limit"))
                         + " FROM " + _sqlid(measure["name"]) + " m WHERE " + sql.split(" WHERE ", 1)[1]
                         + " GROUP BY " + ",".join("m." + _sqlid(measure["columns"][key])
                         for key in ("item", "unit", "lower_limit", "upper_limit"))
                         + " ORDER BY " + "m." + _sqlid(measure["columns"]["item"]))
    target_root.parent.mkdir(parents=True, exist_ok=True)
    source = _readonly(source_path)
    try:
        catalog_rows = source.execute(source_feature_sql, params).fetchall()
        if not catalog_rows:
            raise ValueError("no registered synthetic measure rows at the manifest cutoff")
        source_items = sorted({str(row["item"]) for row in catalog_rows})
        if len(source_items) > feature_count:
            raise ValueError("configured feature_count is smaller than source logical item count")
        item_index = {name: index for index, name in enumerate(source_items)}
        grouped_specs: dict[str, set[tuple[str, float | None, float | None]]] = {name: set() for name in source_items}
        for row in catalog_rows:
            unit = str(row["unit"]) if row["unit"] is not None else ""
            lower = float(row["lower_limit"]) if row["lower_limit"] is not None else None
            upper = float(row["upper_limit"]) if row["upper_limit"] is not None else None
            grouped_specs[str(row["item"])].add((unit, lower, upper))
        feature_metadata = []
        for name in source_items:
            specs = grouped_specs[name]
            units = {spec[0] for spec in specs}
            limits = {(spec[1], spec[2]) for spec in specs}
            unit = next(iter(units)) if len(units) == 1 and next(iter(units)) else None
            lower, upper = next(iter(limits)) if len(limits) == 1 else (None, None)
            feature_metadata.append({"name": name, "unit": unit, "lower_limit": lower,
                "upper_limit": upper, "source_kind": "configured_synthetic_measure",
                "unit_spec_consistent": len(units) == 1 and len(limits) == 1,
                "semantic_description": "Configured synthetic platform measurement item; physical meaning is unverified."})
        while len(feature_metadata) < feature_count:
            index = len(feature_metadata)
            channel_group = (index - len(source_items)) // 16 + 1
            feature_metadata.append({"name": f"synthetic_electrical_channel_{index - len(source_items) + 1:03d}",
                "unit": f"synthetic_electrical_unit_{channel_group:02d}", "lower_limit": -8.0,
                "upper_limit": 8.0, "source_kind": "synthetic_dummy_channel", "unit_spec_consistent": True,
                "semantic_description": f"Synthetic electrical channel group {channel_group}; no physical measurement meaning assigned."})

        measure_key_columns = ["incident_id", "lot_id", "wafer_id", "chip_id"]
        if measure["columns"].get("stage"):
            measure_key_columns.append("stage")
        group_columns = [*measure_key_columns]
        count_sql = "SELECT COUNT(*) FROM (SELECT " + ",".join("m." + _sqlid(measure["columns"][key])
                    for key in group_columns) + sql + " GROUP BY " + ",".join("m." + _sqlid(measure["columns"][key])
                    for key in group_columns) + ")"
        chip_count = int(source.execute(count_sql, params).fetchone()[0])
        if not 30 <= chip_count <= 250_000:
            raise ValueError("registered synthetic tabular population must be in 30..250000 chips")
        X = np.full((chip_count, feature_count), np.nan, dtype=np.float32)
        labels = np.zeros(chip_count, dtype=np.int8)
        row_groups, row_times, row_keys, row_meta = [], [], [], []
        query = "SELECT " + ",".join(expressions) + sql + " ORDER BY " + ",".join(
            "m." + _sqlid(measure["columns"][key]) for key in (*group_columns, "item"))
        cursor = source.execute(query, params)
        current_key = None
        values: dict[int, tuple[float | None, str | None, float | None, float | None]] = {}
        meta: dict[str, Any] = {}
        duplicate_source_items = 0

        def finish_chip():
            nonlocal current_key, values, meta, duplicate_source_items
            if current_key is None:
                return
            row_index = len(row_keys)
            for feature_index, (value, _, lower, upper) in values.items():
                if value is not None:
                    X[row_index, feature_index] = value
                    if lower is not None and value < lower or upper is not None and value > upper:
                        labels[row_index] = 1
            row_keys.append(tuple(current_key))
            row_groups.append(str(meta["incident_id"]))
            row_times.append(str(meta["occurred_at"]))
            row_meta.append(meta.copy())

        for raw in cursor:
            row = dict(raw)
            key = tuple(row[name] for name in group_columns)
            if key != current_key:
                finish_chip()
                current_key = key
                values = {}
                meta = {name: row.get(name) for name in ("incident_id", "lot_id", "wafer_id", "chip_id",
                         "die_x", "die_y", "stage", "occurred_at", "available_at")}
            if row["occurred_at"] != meta["occurred_at"]:
                raise ValueError("measurement chip group has inconsistent event timestamps")
            index = item_index[str(row["item"])]
            lower = float(row["lower_limit"]) if row["lower_limit"] is not None else None
            upper = float(row["upper_limit"]) if row["upper_limit"] is not None else None
            candidate = (float(row["value"]) if row["value"] is not None else None,
                         str(row["unit"]) if row["unit"] is not None else None, lower, upper)
            if index in values:
                if values[index] != candidate:
                    raise ValueError("conflicting duplicate item values for a synthetic chip key")
                duplicate_source_items += 1
            else:
                values[index] = candidate
            if row.get("available_at") and (not meta.get("available_at") or row["available_at"] > meta["available_at"]):
                meta["available_at"] = row["available_at"]
        finish_chip()
        if len(row_keys) != chip_count:
            raise ValueError("chip grouping count changed during source read")
        if _sha256(source_path, force=True) != source_hash:
            raise ValueError("PLATFORM_SOURCE_CHANGED_DURING_BUILD")

        dummy_count = feature_count - len(source_items)
        seed = int(cfg.get("seed", 20261024))
        if dummy_count:
            rng = np.random.default_rng(seed)
            latent_count = min(8, dummy_count)
            loadings = rng.normal(0, 0.45, size=(latent_count, dummy_count)).astype(np.float32)
            for start in range(0, chip_count, 8192):
                end = min(chip_count, start + 8192)
                latent = rng.normal(0, 1, size=(end - start, latent_count)).astype(np.float32)
                block = latent @ loadings + rng.normal(0, 0.55, size=(end - start, dummy_count)).astype(np.float32)
                block[rng.random(block.shape) < 0.015] = np.nan
                X[start:end, len(source_items):] = block
            group_times = {}
            for group, stamp in zip(row_groups, row_times):
                group_times.setdefault(group, stamp)
            sorted_incidents = sorted(group_times, key=lambda incident: (datetime.fromisoformat(group_times[incident]).timestamp(), incident))
            shifted = {group for index, group in enumerate(sorted_incidents)
                       if index >= int(len(sorted_incidents) * 0.7) and index % 3 == 0}
            if dummy_count >= 4:
                for row_index, group in enumerate(row_groups):
                    if group in shifted:
                        X[row_index, len(source_items):len(source_items) + 4] += 1.5

        model = fit_global_model(X, labels, np.asarray(row_groups), np.asarray(row_times), feature_metadata,
                                 seed=seed, fit_sample_limit=fit_limit)
        all_train = np.asarray(model["train_mask"], dtype=bool)
        holdout_mask = np.asarray(model["holdout_mask"], dtype=bool)
        purge_mask = np.asarray(model["purge_mask"], dtype=bool)
        train_group_names = model["split_metadata"]["train_groups"]
        holdout_group_names = model["split_metadata"]["holdout_groups"]
        purged_group_names = model["split_metadata"]["purged_groups"]
        group_hash = lambda names: hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()
        pca = model["pca"]
        parameter_hash = hashlib.sha256(b"".join(array.tobytes() for array in (
            model["medians"], model["center"], model["scale"], pca.components_, pca.mean_,
            model["robust_cov"].location_, model["robust_cov"].covariance_))).hexdigest()
        profile = bounded_profile(X, feature_metadata, labels, np.asarray(row_groups), np.asarray(row_times),
                                  all_train, row_keys, holdout_mask, purge_mask)
        report = {"synthetic": True, "grain": "one row per registered incident/Lot/Wafer/chip/stage key",
            "method": "train_normal_robust_scaling_pca_mcd_plus_reconstruction_residual",
            "source_feature_count": len(source_items), "dummy_feature_count": dummy_count,
            "feature_count": feature_count, "chip_count": chip_count,
            "fit_sample_limit": fit_limit, "fit_sample_count": len(model["fit_indexes"]),
            "train_normal_fit_count": len(model["fit_indexes"]),
            "train_group_count": len(train_group_names), "holdout_group_count": len(holdout_group_names),
            "purged_group_count": len(purged_group_names),
            "train_group_sha256": group_hash(train_group_names), "holdout_group_sha256": group_hash(holdout_group_names),
            "purged_group_sha256": group_hash(purged_group_names),
            "train_max_event_epoch": model["split_metadata"]["train_max_epoch"],
            "holdout_min_event_epoch": model["split_metadata"]["holdout_min_epoch"],
            "covariance_threshold_train_q99": model["covariance_threshold"],
            "residual_threshold_train_q99": model["residual_threshold"],
            "holdout_metrics": model["metrics"], "profile": profile,
            "source_cutoff": manifest["as_of"], "source_database_sha256": source_hash,
            "config_hash": settings.config_hash, "data_contract_hash": _data_contract_hash(settings),
            "model_parameter_sha256": parameter_hash,
            "limitations": ["synthetic-only", "outside-limit labels are heuristic synthetic rules, not independent truth",
                "feature deviation list is univariate diagnostic, not covariance contribution",
                "source measurement meanings remain unverified; dummy electrical channels have no physical meaning"]}
        report["read_model_version"] = hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False,
                                                       default=str).encode("utf-8")).hexdigest()

        target_root.mkdir(parents=True)
        target_db = target_root / "chip_tabular.sqlite"
        conn = sqlite3.connect(target_db)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            feature_columns = [f'"feature_{i:03d}" REAL' for i in range(feature_count)]
            metadata_columns = ['"incident_id" TEXT NOT NULL', '"lot_id" TEXT NOT NULL', '"wafer_id" TEXT NOT NULL',
                '"chip_id" TEXT NOT NULL', '"stage" TEXT NOT NULL', '"die_x" INTEGER', '"die_y" INTEGER',
                '"occurred_at" TEXT NOT NULL', '"available_at" TEXT NOT NULL', '"source_feature_count" INTEGER NOT NULL',
                '"missing_feature_count" INTEGER NOT NULL', '"synthetic_label" INTEGER NOT NULL',
                '"anomaly_score" REAL NOT NULL', '"residual_score" REAL NOT NULL',
                '"covariance_threshold" REAL NOT NULL', '"residual_threshold" REAL NOT NULL',
                '"covariance_flagged" INTEGER NOT NULL', '"residual_flagged" INTEGER NOT NULL',
                '"flagged" INTEGER NOT NULL', '"training_group" INTEGER NOT NULL', '"top_deviations" TEXT NOT NULL']
            key_sql = 'PRIMARY KEY("incident_id","lot_id","wafer_id","chip_id","stage")'
            conn.execute('CREATE TABLE "chip_features" (' + ','.join(metadata_columns + feature_columns + [key_sql]) + ')')
            conn.execute('CREATE TABLE "feature_catalog" ("feature_index" INTEGER PRIMARY KEY,"name" TEXT NOT NULL,"unit" TEXT,"lower_limit" REAL,"upper_limit" REAL,"source_kind" TEXT NOT NULL,"unit_spec_consistent" INTEGER NOT NULL,"semantic_description" TEXT NOT NULL,"missing_count" INTEGER NOT NULL,"distinct_count" INTEGER NOT NULL)')
            conn.execute('CREATE TABLE "analysis_metadata" ("key" TEXT PRIMARY KEY,"value" TEXT NOT NULL)')
            columns_sql = [part.split()[0] for part in metadata_columns] + [f'"feature_{i:03d}"' for i in range(feature_count)]
            placeholders = ','.join('?' for _ in columns_sql)
            insert_sql = 'INSERT INTO "chip_features" (' + ','.join(columns_sql) + ') VALUES (' + placeholders + ')'
            for start in range(0, chip_count, 4096):
                end = min(chip_count, start + 4096)
                devs = feature_deviations(X[start:end], model, feature_metadata, top_k=5)
                batch = []
                for local, index in enumerate(range(start, end)):
                    meta = row_meta[index]
                    covariance_flagged = bool(model["distances"][index] > model["covariance_threshold"])
                    residual_flagged = bool(model["residual_scores"][index] > model["residual_threshold"])
                    keys = row_keys[index]
                    key_values = dict(zip(group_columns, keys))
                    values = (key_values["incident_id"], key_values["lot_id"], key_values["wafer_id"],
                        key_values["chip_id"], key_values.get("stage") or "", meta.get("die_x"), meta.get("die_y"),
                        meta["occurred_at"], meta["available_at"], len(source_items),
                        int(np.isnan(X[index]).sum()), int(labels[index]), float(model["distances"][index]),
                        float(model["residual_scores"][index]), model["covariance_threshold"], model["residual_threshold"],
                        int(covariance_flagged), int(residual_flagged), int(covariance_flagged or residual_flagged),
                        int(all_train[index]), json.dumps(devs[local], ensure_ascii=False, separators=(",", ":")),
                        *[None if np.isnan(value) else float(value) for value in X[index]])
                    batch.append(values)
                conn.executemany(insert_sql, batch)
            conn.execute('CREATE INDEX "chip_features_scope_time" ON "chip_features"("incident_id","occurred_at","available_at")')
            conn.executemany('INSERT INTO "feature_catalog" VALUES (?,?,?,?,?,?,?,?,?,?)', [
                (index, spec["name"], spec.get("unit"), spec.get("lower_limit"), spec.get("upper_limit"),
                 spec["source_kind"], int(spec.get("unit_spec_consistent", True)), spec["semantic_description"],
                 profile["feature_profile"][index]["missing_count"], profile["feature_profile"][index]["distinct_count"])
                for index, spec in enumerate(feature_metadata)])
            report["duplicate_source_item_records"] = duplicate_source_items
            report["holdout_chip_count"] = int(holdout_mask.sum())
            report["purged_chip_count"] = int(purge_mask.sum())
            report["model_parameters"] = {"medians": model["medians"].tolist(), "center": model["center"].tolist(),
                "scale": model["scale"].tolist(), "pca_components": pca.components_.tolist(),
                "pca_mean": pca.mean_.tolist(), "robust_location": model["robust_cov"].location_.tolist(),
                "robust_covariance": model["robust_cov"].covariance_.tolist()}
            conn.executemany('INSERT INTO "analysis_metadata" VALUES (?,?)', [
                (key, json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))
                for key, value in report.items()])
            conn.commit()
        finally:
            conn.close()
        return {"status": "SYNTHETIC_PLATFORM_TABULAR_READY", "synthetic": True,
                "path": str(target_db), "chip_count": chip_count, "feature_count": feature_count,
                "source_feature_count": len(source_items), "dummy_feature_count": dummy_count,
                "read_model_version": report["read_model_version"], "holdout_metrics": report["holdout_metrics"],
                "notice": "Synthetic fixture model only; not site-validated."}
    finally:
        source.close()


def profile_platform_tabular(settings) -> dict[str, Any]:
    """Return the complete bounded configured feature catalogue/profile."""
    _, _, _, target_root, source_path, _, source_hash, _ = _source_paths(settings)
    target_db = target_root / "chip_tabular.sqlite"
    if not target_db.is_file():
        return {"status": "UNAVAILABLE", "synthetic": True, "feature_count": 0, "features": []}
    conn = _readonly(target_db)
    try:
        meta = {row["key"]: json.loads(row["value"]) for row in conn.execute('SELECT "key","value" FROM "analysis_metadata"')}
        if (meta.get("source_database_sha256") != source_hash
                or meta.get("data_contract_hash") != _data_contract_hash(settings)):
            return {"status": "STALE", "synthetic": True, "feature_count": 0, "features": [],
                    "reason": "source/config hash changed; rebuild required"}
        features = [dict(row) for row in conn.execute('SELECT * FROM "feature_catalog" ORDER BY "feature_index"')]
        return {"status": "OK", "synthetic": True, "feature_count": meta["feature_count"],
                "source_feature_count": meta["source_feature_count"],
                "dummy_feature_count": meta["dummy_feature_count"], "chip_count": meta["chip_count"],
                "source_cutoff": meta["source_cutoff"], "read_model_version": meta["read_model_version"],
                "profile": meta["profile"], "features": features,
                "notice": "Complete synthetic feature catalogue; feature semantics are unverified."}
    finally:
        conn.close()


def analyze_platform_case(settings, incident_ids: list[str], as_of: str, *, top_k: int = 10,
                          feature_names: list[str] | None = None) -> dict[str, Any]:
    """Read bounded case scores and optionally selected exact-catalog chip values."""
    if (not isinstance(incident_ids, list) or not incident_ids or len(incident_ids) > settings.data["runtime"]["max_scope_incidents"]
            or any(not isinstance(value, str) or not value or len(value) > 128 for value in incident_ids)
            or len(set(incident_ids)) != len(incident_ids)):
        raise ValueError("invalid bounded incident scope")
    if type(top_k) is not int or not 1 <= top_k <= 10:
        raise ValueError("top_k must be in 1..10")
    if feature_names is not None and (not isinstance(feature_names, list) or len(feature_names) > 8
            or any(not isinstance(name, str) or not name or len(name) > 128 for name in feature_names)):
        raise ValueError("feature_names must contain at most 8 exact catalogue names")
    if feature_names is not None and len(set(feature_names)) != len(feature_names):
        raise ValueError("duplicate feature name")
    try:
        cutoff = datetime.combine(date.fromisoformat(as_of) + timedelta(days=1), time.min,
                                  ZoneInfo(settings.data["runtime"]["timezone"])).isoformat()
    except (TypeError, ValueError, KeyError):
        raise ValueError("invalid as_of") from None
    cfg, _, _, target_root, source_path, _, source_hash, _ = _source_paths(settings)
    target_db = target_root / "chip_tabular.sqlite"
    if not target_db.is_file():
        return {"status": "UNAVAILABLE", "synthetic": True, "scope": {"incident_ids": incident_ids, "as_of": as_of}}
    score_db = _readonly(target_db)
    source_uri = "file:" + quote(source_path.as_posix(), safe="/:") + "?mode=ro"
    try:
        score_db.execute("ATTACH DATABASE ? AS source_ro", (source_uri,))
        meta = {row["key"]: json.loads(row["value"]) for row in score_db.execute('SELECT "key","value" FROM "analysis_metadata"')}
        if (meta.get("source_database_sha256") != source_hash
                or meta.get("data_contract_hash") != _data_contract_hash(settings)):
            return {"status": "STALE", "synthetic": True, "scope": {"incident_ids": incident_ids, "as_of": as_of}}
        if as_of < str(meta.get("source_cutoff", "unknown")):
            return {"status": "MODEL_AFTER_AS_OF", "synthetic": True,
                    "scope": {"incident_ids": incident_ids, "as_of": as_of},
                    "model_source_cutoff": meta.get("source_cutoff")}
        catalog = [dict(row) for row in score_db.execute('SELECT * FROM "feature_catalog" ORDER BY "feature_index"')]
        catalog_by_name = {row["name"]: row for row in catalog}
        if len(catalog_by_name) != len(catalog):
            raise ValueError("duplicate feature names in configured catalogue")
        selected_features = []
        for name in feature_names or []:
            feature = catalog_by_name.get(name)
            if feature is None:
                raise ValueError("UNKNOWN_MEASURE_FEATURE: " + name)
            selected_features.append(feature)
        measure, core = _measure_mapping(settings)
        rel = settings.data["relations"]
        m = measure["columns"]; incident = core["incident"]; lot = core["lot_list"]; wafer = core["wafer_list"]
        mtable = "source_ro." + _sqlid(measure["name"])
        ic = lambda key: "i." + _sqlid(incident["columns"][key])
        mc = lambda key: "m." + _sqlid(m[key])
        lc = lambda key: "l." + _sqlid(lot["columns"][key])
        wc = lambda key: "w." + _sqlid(wafer["columns"][key])
        itable, ltable, wtable = ("source_ro." + _sqlid(core[name]["name"])
                                   for name in ("incident", "lot_list", "wafer_list"))
        member_sql = ("EXISTS (SELECT 1 FROM " + mtable + " m WHERE " + mc("incident_id") + "=t." + _sqlid("incident_id")
            + " AND " + mc("lot_id") + "=t." + _sqlid("lot_id") + " AND " + mc("wafer_id") + "=t." + _sqlid("wafer_id")
            + " AND " + mc("chip_id") + "=t." + _sqlid("chip_id") + " AND " + mc("synthetic") + "=1"
            + (" AND " + mc("stage") + "=t." + _sqlid("stage") if m.get("stage") else "")
            + " AND julianday(" + mc("occurred_at") + ")<julianday(?) AND julianday(" + mc("available_at") + ")<julianday(?)"
            + " AND EXISTS (SELECT 1 FROM " + itable + " i WHERE " + ic("incident_id") + "=" + mc("incident_id") + ")"
            + " AND EXISTS (SELECT 1 FROM " + ltable + " l JOIN " + itable + " i ON " + lc("incident_ref")
            + "=" + ic(rel["incident_parent_key"]) + " WHERE " + ic("incident_id") + "=" + mc("incident_id")
            + " AND " + lc("lot_id") + "=" + mc("lot_id") + ")"
            + " AND EXISTS (SELECT 1 FROM " + wtable + " w JOIN " + itable + " i ON " + wc("incident_ref")
            + "=" + ic(rel["incident_parent_key"]) + " WHERE " + ic("incident_id") + "=" + mc("incident_id")
            + " AND " + wc("lot_id") + "=" + mc("lot_id") + " AND " + wc("wafer_id") + "=" + mc("wafer_id") + "))")
        scope = '"incident_id" IN (' + ','.join('?' for _ in incident_ids) + ')'
        cutoff_clause = 'julianday("occurred_at")<julianday(?) AND julianday("available_at")<julianday(?)'
        base = ' FROM "chip_features" t WHERE ' + scope + ' AND ' + cutoff_clause + ' AND ' + member_sql
        params = [*incident_ids, cutoff, cutoff, cutoff, cutoff]
        count, average_missing, flagged_count = score_db.execute(
            'SELECT COUNT(*),AVG("missing_feature_count"),SUM("flagged")' + base, params).fetchone()
        feature_count = int(meta["feature_count"])
        source_count = int(meta["source_feature_count"])
        if not count:
            return {"status": "NO_MATCH", "synthetic": True, "scope": {"incident_ids": incident_ids, "as_of": as_of},
                    "feature_count": feature_count, "source_feature_count": source_count,
                    "dummy_feature_count": int(meta["dummy_feature_count"]),
                    "selected_feature_count": len(selected_features),
                    "selected_features": [{"name": item["name"], "index": item["feature_index"],
                        "unit": item["unit"], "lower_limit": item["lower_limit"],
                        "upper_limit": item["upper_limit"], "description": item["semantic_description"]}
                        for item in selected_features], "chips": []}
        selected_sql = ''.join(',t.' + _sqlid(f'feature_{item["feature_index"]:03d}')
                               + ' AS ' + _sqlid(f'selected_{index}')
                               for index, item in enumerate(selected_features))
        sql = ('SELECT "incident_id","lot_id","wafer_id","chip_id","stage","occurred_at","available_at",'
               '"anomaly_score","residual_score","covariance_threshold","residual_threshold","flagged",'
               '"training_group","top_deviations"' + selected_sql + base + ' ORDER BY "flagged" DESC,MAX("anomaly_score"/"covariance_threshold",'
               '"residual_score"/"residual_threshold") DESC,"incident_id","lot_id","wafer_id","chip_id" LIMIT ?')
        rows = score_db.execute(sql, (*params, top_k)).fetchall()
        training_group = bool(score_db.execute('SELECT 1' + base + ' AND "training_group"=1 LIMIT 1', params).fetchone())
        return {"status": "OK", "synthetic": True, "scope": {"incident_ids": incident_ids, "as_of": as_of},
            "grain": "chip-stage", "chip_count": int(count), "feature_count": feature_count,
            "source_feature_count": source_count, "dummy_feature_count": int(meta["dummy_feature_count"]),
            "average_missing_features_per_chip": round(float(average_missing or 0), 4),
            "flagged_chip_count": int(flagged_count or 0), "duplicate_chip_key_count": 0,
            "source_cutoff": meta["source_cutoff"], "read_model_version": meta["read_model_version"],
            "holdout_metrics": meta["holdout_metrics"], "case_may_be_in_training": training_group,
            "selected_feature_count": len(selected_features),
            "selected_features": [{"name": item["name"], "index": item["feature_index"],
                "unit": item["unit"], "lower_limit": item["lower_limit"],
                "upper_limit": item["upper_limit"], "description": item["semantic_description"]}
                for item in selected_features],
            "chips": [{"incident_id": row["incident_id"], "lot_id": row["lot_id"], "wafer_id": row["wafer_id"],
                "chip_id": row["chip_id"], "stage": row["stage"], "occurred_at": row["occurred_at"],
                "available_at": row["available_at"], "anomaly_score": row["anomaly_score"],
                "residual_score": row["residual_score"], "covariance_threshold": row["covariance_threshold"],
                "residual_threshold": row["residual_threshold"], "flagged": bool(row["flagged"]),
                "selected_values": {item["name"]: row[f"selected_{index}"]
                    for index, item in enumerate(selected_features)},
                "top_feature_deviations": json.loads(row["top_deviations"])} for row in rows],
            "limitations": ["synthetic-only; training labels are not returned", "top feature deviations are univariate diagnostics",
                            "unknown chip groups may be outside the fitted training distribution"]}
    finally:
        score_db.close()


def analyze_matrix(X: np.ndarray, labels: np.ndarray, groups: np.ndarray, timestamps: np.ndarray,
                   feature_metadata: list[dict[str, Any]], *, seed: int = 20261024,
                   holdout_fraction: float = 0.2, top_k: int = 5,
                   fit_sample_limit: int = 4096, chip_keys: list[tuple] | None = None) -> dict[str, Any]:
    """Fit robust PCA-space covariance on train-normal chips; score later groups."""
    if type(top_k) is not int or not 1 <= top_k <= 10:
        raise ValueError("top_k must be in 1..10")
    values = np.asarray(X, dtype=float)
    y = np.asarray(labels, dtype=int)
    groups = np.asarray(groups).astype(str)
    timestamps = np.asarray(timestamps).astype(str)
    if values.ndim != 2 or len(feature_metadata) != values.shape[1] or not np.isfinite(values[~np.isnan(values)]).all():
        raise ValueError("invalid feature matrix or catalogue")
    if len(np.unique(y)) < 1:
        raise ValueError("insufficient train-normal or holdout data")
    model = fit_global_model(values, y, groups, timestamps, feature_metadata, seed=seed,
                             holdout_fraction=holdout_fraction, fit_sample_limit=fit_sample_limit)
    holdout_mask = model["holdout_mask"]
    hold_indexes = np.flatnonzero(holdout_mask)
    deviations = feature_deviations(values[holdout_mask], model, feature_metadata, top_k=top_k)
    scored = []
    for local_index, source_index in enumerate(hold_indexes):
        contributions = deviations[local_index]
        scored.append({"chip_index": int(source_index), "group": str(groups[source_index]),
                       "timestamp": str(timestamps[source_index]), "synthetic_label": int(y[source_index]),
                       "anomaly_score": round(float(model["distances"][source_index]), 6),
                       "residual_score": round(float(model["residual_scores"][source_index]), 6),
                       "covariance_threshold": round(model["covariance_threshold"], 6),
                       "residual_threshold": round(model["residual_threshold"], 6),
                       "covariance_flagged": bool(model["covariance_flagged"][source_index]),
                       "residual_flagged": bool(model["residual_flagged"][source_index]),
                       "flagged": bool(model["covariance_flagged"][source_index] or model["residual_flagged"][source_index]),
                       "top_feature_deviations": contributions})
    keys = chip_keys if chip_keys is not None else [(index,) for index in range(len(values))]
    profile = bounded_profile(values, feature_metadata, y, groups, timestamps, model["train_mask"], keys,
                              model["holdout_mask"], model["purge_mask"])
    return {"synthetic": True, "method": "train_normal_robust_scaling_pca_mcd_plus_reconstruction_residual",
            "split": "latest whole groups held out; interval-overlap groups purged; group-disjoint with strict temporal gap",
            "train_normal_count": int(len(model["fit_indexes"])), "holdout_count": int(holdout_mask.sum()),
            "fit_sample_limit": fit_sample_limit, "pca_components": model["component_count"],
            "train_threshold_quantile": 0.99,
            "holdout_flagged_count": int(np.sum((model["covariance_flagged"] | model["residual_flagged"])[holdout_mask])),
            "purged_group_count": len(model["split_metadata"]["purged_groups"]),
            "holdout_metrics": model["metrics"], "profile": profile,
            "holdout_scores": scored,
            "limitations": ["synthetic-only demonstration", "feature deviations are univariate diagnostics, not covariance contributions",
                            "thresholds are fit on training normals; no site calibration or causal claim"]}


def analyze_npz(dataset_path: str | Path, *, top_k: int = 5) -> dict[str, Any]:
    """Analyze a generated NPZ and adjacent metadata JSON without writing outputs."""
    path = Path(dataset_path).resolve()
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("synthetic") is not True:
        raise ValueError("only explicitly synthetic datasets are accepted")
    with np.load(path, allow_pickle=False) as data:
        return analyze_matrix(data["X"], data["labels"], data["groups"], data["timestamps"],
                              metadata["features"], seed=int(metadata["seed"]),
                              holdout_fraction=float(metadata["holdout_fraction"]), top_k=top_k)

