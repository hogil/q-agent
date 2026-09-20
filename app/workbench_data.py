"""Load and validate the local synthetic workbench raw-data sidecar."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


MAX_RAW_FILE_BYTES = 25 * 1024 * 1024
_ANOMALY_PATTERNS = {
    "drift",
    "abrupt_level_shift",
    "spike",
    "variance_burst",
    "periodic_pattern",
}
_STATUSES = {"RUN", "WAIT", "HOLD"}


def _fail(message: str) -> None:
    raise ValueError(f"invalid workbench raw data: {message}")


def _object(value, label: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    return value


def _array(value, label: str) -> list:
    if not isinstance(value, list):
        _fail(f"{label} must be an array")
    return value


def _string(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} must be a non-empty string")
    return value


def _finite(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(f"{label} must be finite")
    return value


def _integer(value, label: str) -> int:
    _finite(value, label)
    if not isinstance(value, int):
        _fail(f"{label} must be an integer")
    return value


def _timestamp(value, label: str) -> str:
    text = _string(value, label)
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        _fail(f"{label} must be an ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"{label} must include a timezone")
    return text


def _unique(values: list, label: str) -> None:
    if len(values) != len(set(values)):
        _fail(f"{label} must be unique")


def _validate_trend(rows: list) -> None:
    timestamps = []
    for index, row in enumerate(rows):
        item = _object(row, f"engineering.trend[{index}]")
        for key in ("timestamp", "temperature", "queue", "availability"):
            if key not in item:
                _fail(f"engineering.trend[{index}].{key} is required")
        timestamps.append(_timestamp(item["timestamp"], f"engineering.trend[{index}].timestamp"))
        for key in ("temperature", "queue", "availability"):
            _finite(item[key], f"engineering.trend[{index}].{key}")
    _unique(timestamps, "engineering.trend timestamps")


def _validate_engineering(engineering: dict) -> set[str]:
    required = {"signals", "trend", "fab", "yields", "wip", "downtime", "changes"}
    if set(engineering) != required:
        _fail("engineering must contain signals, trend, fab, yields, wip, downtime and changes")
    signals = _array(engineering["signals"], "engineering.signals")
    if not signals:
        _fail("engineering.signals must not be empty")
    trend = _array(engineering["trend"], "engineering.trend")
    if not trend:
        _fail("engineering.trend must not be empty")
    _validate_trend(trend)
    signal_ids = []
    signal_scopes = set()
    metric_keys = {"temperature", "queue", "availability"}
    for index, row in enumerate(signals):
        item = _object(row, f"engineering.signals[{index}]")
        required_signal = (
            "id", "title", "severity", "metric", "device", "equipment", "step",
            "item", "legendAxis", "recipe", "detectedAt", "startIndex", "endIndex",
            "description", "onsetIndex",
        )
        for key in required_signal:
            if key not in item:
                _fail(f"engineering.signals[{index}].{key} is required")
        signal_ids.append(_string(item["id"], f"engineering.signals[{index}].id"))
        _string(item["title"], f"engineering.signals[{index}].title")
        _string(item["severity"], f"engineering.signals[{index}].severity")
        metric = _string(item["metric"], f"engineering.signals[{index}].metric")
        if metric not in metric_keys:
            _fail(f"engineering.signals[{index}].metric is unsupported")
        for key in ("device", "equipment", "step", "item", "legendAxis", "recipe", "description"):
            _string(item[key], f"engineering.signals[{index}].{key}")
        detected = _timestamp(item["detectedAt"], f"engineering.signals[{index}].detectedAt")
        start = _integer(item["startIndex"], f"engineering.signals[{index}].startIndex")
        end = _integer(item["endIndex"], f"engineering.signals[{index}].endIndex")
        onset = _integer(item["onsetIndex"], f"engineering.signals[{index}].onsetIndex")
        if start < 0 or end < start or end >= len(trend) or onset < 0 or onset >= len(trend):
            _fail(f"engineering.signals[{index}] index is outside trend scope")
        if "pattern" in item and item["pattern"] not in _ANOMALY_PATTERNS:
            _fail(f"engineering.signals[{index}].pattern is unsupported")
        signal_scopes.add((item["step"], item["equipment"]))
        _ = detected
    _unique(signal_ids, "engineering signal ids")

    for index, row in enumerate(_array(engineering["fab"], "engineering.fab")):
        item = _object(row, f"engineering.fab[{index}]")
        for key in ("lotId", "waferId", "timestamp", "equipment", "step", "recipe", "value"):
            if key not in item:
                _fail(f"engineering.fab[{index}].{key} is required")
        for key in ("lotId", "waferId", "equipment", "step", "recipe"):
            _string(item[key], f"engineering.fab[{index}].{key}")
        _timestamp(item["timestamp"], f"engineering.fab[{index}].timestamp")
        _finite(item["value"], f"engineering.fab[{index}].value")

    for index, row in enumerate(_array(engineering["yields"], "engineering.yields")):
        item = _object(row, f"engineering.yields[{index}]")
        for key in ("lotId", "waferId", "measuredAt", "yieldPct"):
            if key not in item:
                _fail(f"engineering.yields[{index}].{key} is required")
        _string(item["lotId"], f"engineering.yields[{index}].lotId")
        _string(item["waferId"], f"engineering.yields[{index}].waferId")
        _timestamp(item["measuredAt"], f"engineering.yields[{index}].measuredAt")
        if item["yieldPct"] is not None:
            _finite(item["yieldPct"], f"engineering.yields[{index}].yieldPct")

    for index, row in enumerate(_array(engineering["wip"], "engineering.wip")):
        item = _object(row, f"engineering.wip[{index}]")
        required_wip = ("lotId", "productCode", "layer", "endLayer", "step", "equipment", "recipe", "status", "wafers", "queueHours", "holdCode")
        for key in required_wip:
            if key not in item:
                _fail(f"engineering.wip[{index}].{key} is required")
        for key in ("lotId", "productCode", "step", "equipment", "recipe", "holdCode"):
            _string(item[key], f"engineering.wip[{index}].{key}")
        for key in ("layer", "endLayer", "wafers", "queueHours"):
            _finite(item[key], f"engineering.wip[{index}].{key}")
        if item["status"] not in _STATUSES:
            _fail(f"engineering.wip[{index}].status is unsupported")

    for index, row in enumerate(_array(engineering["downtime"], "engineering.downtime")):
        item = _object(row, f"engineering.downtime[{index}]")
        for key in ("id", "equipment", "start", "end", "code", "category", "description"):
            if key not in item:
                _fail(f"engineering.downtime[{index}].{key} is required")
            _string(item[key], f"engineering.downtime[{index}].{key}")
        _timestamp(item["start"], f"engineering.downtime[{index}].start")
        _timestamp(item["end"], f"engineering.downtime[{index}].end")
    _unique([row["id"] for row in engineering["downtime"]], "engineering downtime ids")

    for index, row in enumerate(_array(engineering["changes"], "engineering.changes")):
        item = _object(row, f"engineering.changes[{index}]")
        for key in ("id", "equipment", "recipe", "kind", "timestamp", "before", "after", "sourceRef"):
            if key not in item:
                _fail(f"engineering.changes[{index}].{key} is required")
        for key in ("id", "equipment", "kind", "before", "after", "sourceRef"):
            _string(item[key], f"engineering.changes[{index}].{key}")
        if not isinstance(item["recipe"], str):
            _fail(f"engineering.changes[{index}].recipe must be a string")
        if item["kind"] not in {"recipe", "system"}:
            _fail(f"engineering.changes[{index}].kind is unsupported")
        _timestamp(item["timestamp"], f"engineering.changes[{index}].timestamp")
    _unique([row["id"] for row in engineering["changes"]], "engineering change ids")
    return signal_scopes


def _validate_trend_fleets(value: object, signal_ids: set[str]) -> None:
    fleets = _object(value, "trend_fleets")
    if set(fleets) != signal_ids:
        _fail("trend_fleets keys must exactly match engineering signal ids")
    for signal_id, traces in fleets.items():
        for trace_index, trace in enumerate(_array(traces, f"trend_fleets.{signal_id}")):
            item = _object(trace, f"trend_fleets.{signal_id}[{trace_index}]")
            for key in ("member", "highlighted", "points"):
                if key not in item:
                    _fail(f"trend_fleets.{signal_id}[{trace_index}].{key} is required")
            _string(item["member"], f"trend_fleets.{signal_id}[{trace_index}].member")
            if not isinstance(item["highlighted"], bool):
                _fail(f"trend_fleets.{signal_id}[{trace_index}].highlighted must be boolean")
            timestamps = []
            for point_index, point in enumerate(_array(item["points"], f"trend_fleets.{signal_id}[{trace_index}].points")):
                if not isinstance(point, list) or len(point) != 2:
                    _fail(f"trend_fleets.{signal_id}[{trace_index}].points[{point_index}] must be [timestamp, value]")
                timestamps.append(_finite(point[0], f"trend_fleets.{signal_id}[{trace_index}].points[{point_index}][0]"))
                _finite(point[1], f"trend_fleets.{signal_id}[{trace_index}].points[{point_index}][1]")
            _unique(timestamps, f"trend_fleets.{signal_id}[{trace_index}] point timestamps")


def _validate_comparison_traces(value: object, signals: list[dict]) -> None:
    traces = _object(value, "comparison_traces")
    signal_ids = {row["id"] for row in signals}
    if set(traces) != signal_ids:
        _fail("comparison_traces keys must exactly match engineering signal ids")
    equipment_by_step: dict[str, set[str]] = {}
    for signal in signals:
        equipment_by_step.setdefault(signal["step"], set()).add(signal["equipment"])
    for signal in signals:
        signal_traces = _object(traces[signal["id"]], f"comparison_traces.{signal['id']}")
        expected_equipment = equipment_by_step[signal["step"]]
        if set(signal_traces) != expected_equipment:
            _fail(f"comparison_traces.{signal['id']} must contain all same-step equipment including primary")
        for equipment, points in signal_traces.items():
            _string(equipment, f"comparison_traces.{signal['id']} equipment")
            timestamps = []
            for point_index, point in enumerate(_array(points, f"comparison_traces.{signal['id']}.{equipment}")):
                item = _object(point, f"comparison_traces.{signal['id']}.{equipment}[{point_index}]")
                if set(item) != {"timestamp", "value"}:
                    _fail(f"comparison_traces.{signal['id']}.{equipment}[{point_index}] must contain timestamp and value")
                timestamps.append(_timestamp(item["timestamp"], f"comparison_traces.{signal['id']}.{equipment}[{point_index}].timestamp"))
                _finite(item["value"], f"comparison_traces.{signal['id']}.{equipment}[{point_index}].value")
            _unique(timestamps, f"comparison_traces.{signal['id']}.{equipment} timestamps")


def _validate_inform_notes(value: object, signal_scopes: set[tuple[str, str]]) -> None:
    notes = _array(value, "inform_notes")
    ids = []
    for index, note in enumerate(notes):
        item = _object(note, f"inform_notes[{index}]")
        for key in ("id", "title", "step", "equipment", "date", "version", "body"):
            if key not in item:
                _fail(f"inform_notes[{index}].{key} is required")
            _string(item[key], f"inform_notes[{index}].{key}")
        _timestamp(item["date"], f"inform_notes[{index}].date")
        ids.append(item["id"])
        if (item["step"], item["equipment"]) not in signal_scopes:
            _fail(f"inform_notes[{index}] has no matching signal scope")
    _unique(ids, "inform note ids")


def _validate_sem_assets(value: object, fab_pairs: set[tuple[str, str]]) -> None:
    assets = _array(value, "sem_assets")
    ids = []
    asset_pairs = set()
    for index, asset in enumerate(assets):
        item = _object(asset, f"sem_assets[{index}]")
        for key in ("id", "lotId", "waferId", "src", "provenance", "description"):
            if key not in item:
                _fail(f"sem_assets[{index}].{key} is required")
            _string(item[key], f"sem_assets[{index}].{key}")
        source = item["src"]
        parsed = urlsplit(source)
        parts = source.split("/")
        if parsed.scheme or parsed.netloc or not source.startswith("/assets/") or ".." in parts or "\\" in source or "//" in source[1:]:
            _fail(f"sem_assets[{index}].src must be a local /assets/ path")
        pair = (item["lotId"], item["waferId"])
        if pair not in fab_pairs:
            _fail(f"sem_assets[{index}] is outside the engineering wafer scope")
        ids.append(item["id"])
        asset_pairs.add(pair)
    _unique(ids, "SEM asset ids")
    if len(asset_pairs) != len(assets):
        _fail("SEM asset lot/wafer pairs must be unique")


def _validate_incident(incident_number: str, record: object) -> dict:
    item = _object(record, f"incidents.{incident_number}")
    required = {"engineering", "trend_fleets", "comparison_traces", "inform_notes", "sem_assets"}
    if set(item) != required:
        _fail(f"incidents.{incident_number} must contain engineering, trend_fleets, comparison_traces, inform_notes and sem_assets")
    engineering = _object(item["engineering"], f"incidents.{incident_number}.engineering")
    signal_scopes = _validate_engineering(engineering)
    signal_ids = {row["id"] for row in engineering["signals"]}
    _validate_trend_fleets(item["trend_fleets"], signal_ids)
    _validate_comparison_traces(item["comparison_traces"], engineering["signals"])
    _validate_inform_notes(item["inform_notes"], signal_scopes)
    fab_pairs = {(row["lotId"], row["waferId"]) for row in engineering["fab"]}
    _validate_sem_assets(item["sem_assets"], fab_pairs)
    return item


def load_workbench_data(sources: object, base_dir: str | Path) -> dict[str, dict] | None:
    """Load a configured local raw sidecar, or return ``None`` when unconfigured.

    ``sources`` deliberately accepts only a local ``raw_file`` reference. It never
    downloads a URL and it never generates or substitutes missing fixture data.
    """
    if sources is None or sources == {}:
        return None
    if not isinstance(sources, dict):
        _fail("sources must be an object")
    if set(sources) != {"raw_file"}:
        _fail("sources may only contain raw_file")
    raw_file = sources["raw_file"]
    if not isinstance(raw_file, str) or not raw_file.strip():
        _fail("sources.raw_file must be a local path")
    parsed = urlsplit(raw_file)
    windows_drive_path = len(parsed.scheme) == 1 and len(raw_file) >= 3 and raw_file[1] == ":" and raw_file[2] in ("/", "\\")
    if raw_file.startswith(("//", "\\\\")) or (parsed.scheme and not windows_drive_path) or parsed.netloc:
        _fail("sources.raw_file must be a local path")
    path = Path(raw_file).expanduser()
    path = (path if path.is_absolute() else Path(base_dir).expanduser().resolve() / path).resolve()
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("invalid workbench raw data: raw_file is missing or unreadable") from exc
    if size > MAX_RAW_FILE_BYTES:
        _fail(f"raw_file exceeds {MAX_RAW_FILE_BYTES} bytes")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid workbench raw data: raw_file is not valid UTF-8 JSON") from exc
    root = _object(payload, "root")
    if set(root) != {"version", "synthetic", "incidents"}:
        _fail("root must contain version, synthetic and incidents")
    if root["version"] != 1:
        _fail("version must be 1")
    if root["synthetic"] is not True:
        _fail("synthetic must be true")
    incidents = _object(root["incidents"], "incidents")
    if not incidents:
        _fail("incidents must not be empty")
    return {
        _string(number, "incident number"): _validate_incident(number, record)
        for number, record in incidents.items()
    }
