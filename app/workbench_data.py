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
_LEGEND_AXES = {"eqp_id", "chamber", "recipe"}
_STATUSES = {"RUN", "WAIT", "HOLD"}
_EQUIPMENT_STATES = {"RUN", "DOWN", "PM", "IDLE"}


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


def _validate_equipment_states(rows: list) -> None:
    by_equipment: dict[str, list[tuple[datetime, datetime]]] = {}
    for index, row in enumerate(rows):
        item = _object(row, f"engineering.equipmentStates[{index}]")
        for key in ("equipment", "start", "end", "state", "code"):
            if key not in item:
                _fail(f"engineering.equipmentStates[{index}].{key} is required")
        equipment = _string(item["equipment"], f"engineering.equipmentStates[{index}].equipment")
        start_text = _timestamp(item["start"], f"engineering.equipmentStates[{index}].start")
        end_text = _timestamp(item["end"], f"engineering.equipmentStates[{index}].end")
        _string(item["code"], f"engineering.equipmentStates[{index}].code")
        state = _string(item["state"], f"engineering.equipmentStates[{index}].state")
        if state not in _EQUIPMENT_STATES:
            _fail(f"engineering.equipmentStates[{index}].state is unsupported")
        start_value = datetime.fromisoformat(
            start_text[:-1] + "+00:00" if start_text.endswith(("Z", "z")) else start_text
        )
        end_value = datetime.fromisoformat(
            end_text[:-1] + "+00:00" if end_text.endswith(("Z", "z")) else end_text
        )
        if end_value <= start_value:
            _fail(f"engineering.equipmentStates[{index}] end must be after start")
        by_equipment.setdefault(equipment, []).append((start_value, end_value))
    for equipment, intervals in by_equipment.items():
        ordered = sorted(intervals)
        for previous, current in zip(ordered, ordered[1:]):
            if current[0] < previous[1]:
                _fail(f"engineering.equipmentStates overlaps for {equipment}")


def _validate_engineering(engineering: dict) -> set[str]:
    required = {"signals", "trend", "fab", "yields", "wip", "downtime", "changes"}
    optional = {"equipmentStates"}
    if not required.issubset(engineering) or set(engineering) - required - optional:
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
        if item["legendAxis"] not in _LEGEND_AXES:
            _fail(f"engineering.signals[{index}].legendAxis is unsupported")
        if "highlightedMember" in item:
            _string(item["highlightedMember"], f"engineering.signals[{index}].highlightedMember")
        elif item["legendAxis"] != "eqp_id":
            _fail(f"engineering.signals[{index}].highlightedMember is required for non-equipment axes")
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
    if "equipmentStates" in engineering:
        _validate_equipment_states(_array(engineering["equipmentStates"], "engineering.equipmentStates"))
    return signal_scopes


def _validate_trend_fleets(value: object, signals: list[dict]) -> None:
    fleets = _object(value, "trend_fleets")
    signal_ids = {row["id"] for row in signals}
    if set(fleets) != signal_ids:
        _fail("trend_fleets keys must exactly match engineering signal ids")
    signal_by_id = {row["id"]: row for row in signals}
    for signal_id, traces in fleets.items():
        trace_rows = _array(traces, f"trend_fleets.{signal_id}")
        if not trace_rows:
            _fail(f"trend_fleets.{signal_id} must not be empty")
        members = []
        highlighted_members = []
        for trace_index, trace in enumerate(trace_rows):
            item = _object(trace, f"trend_fleets.{signal_id}[{trace_index}]")
            for key in ("member", "highlighted", "points"):
                if key not in item:
                    _fail(f"trend_fleets.{signal_id}[{trace_index}].{key} is required")
            _string(item["member"], f"trend_fleets.{signal_id}[{trace_index}].member")
            members.append(item["member"])
            if not isinstance(item["highlighted"], bool):
                _fail(f"trend_fleets.{signal_id}[{trace_index}].highlighted must be boolean")
            if item["highlighted"]:
                highlighted_members.append(item["member"])
            timestamps = []
            for point_index, point in enumerate(_array(item["points"], f"trend_fleets.{signal_id}[{trace_index}].points")):
                if not isinstance(point, list) or len(point) != 2:
                    _fail(f"trend_fleets.{signal_id}[{trace_index}].points[{point_index}] must be [timestamp, value]")
                timestamps.append(_finite(point[0], f"trend_fleets.{signal_id}[{trace_index}].points[{point_index}][0]"))
                _finite(point[1], f"trend_fleets.{signal_id}[{trace_index}].points[{point_index}][1]")
            _unique(timestamps, f"trend_fleets.{signal_id}[{trace_index}] point timestamps")
        _unique(members, f"trend_fleets.{signal_id} members")
        if len(highlighted_members) != 1:
            _fail(f"trend_fleets.{signal_id} must contain exactly one highlighted member")
        signal = signal_by_id[signal_id]
        expected_member = signal.get("highlightedMember")
        if expected_member is None and signal["legendAxis"] == "eqp_id":
            expected_member = signal["equipment"]
        if highlighted_members[0] != expected_member:
            _fail(f"trend_fleets.{signal_id} highlighted member does not match signal metadata")


def _validate_comparison_traces(value: object, signals: list[dict]) -> None:
    traces = _object(value, "comparison_traces")
    signal_ids = {row["id"] for row in signals}
    if set(traces) != signal_ids:
        _fail("comparison_traces keys must exactly match engineering signal ids")
    equipment_by_step: dict[str, set[str]] = {}
    for signal in signals:
        if signal["legendAxis"] == "eqp_id":
            equipment_by_step.setdefault(signal["step"], set()).add(signal["equipment"])
    for signal in signals:
        signal_traces = _object(traces[signal["id"]], f"comparison_traces.{signal['id']}")
        if signal["legendAxis"] != "eqp_id":
            if signal_traces:
                _fail(f"comparison_traces.{signal['id']} is only supported for eqp_id signals")
            continue
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


def _validate_image_history(value: object) -> None:
    rows = _array(value, "image_history")
    if len(rows) > 100:
        _fail("image_history exceeds 100 references")
    ids = []
    for row in rows:
        _object(row, "image_history reference")
        for key in ("id", "incident_number", "item", "step", "provenance", "description"):
            _string(row.get(key), "image_history." + key)
        if not row["incident_number"].startswith("SYN-"):
            _fail("image_history requires synthetic incident references")
        _timestamp(row.get("occurred_at"), "image_history.occurred_at")
        if row.get("modality") == "sem":
            source = _string(row.get("src"), "image_history.src")
            parsed = urlsplit(source)
            if (parsed.scheme or parsed.netloc or not source.startswith("/assets/")
                    or ".." in source.split("/") or "\\" in source or "//" in source[1:]):
                _fail("image_history.src must be a local /assets/ path")
        elif row.get("modality") == "overlay":
            points = _array(row.get("vectors"), "image_history.vectors")
            if not 1 <= len(points) <= 4096:
                _fail("image_history.vectors requires 1..4096 points")
            for point in points:
                _object(point, "image_history vector")
                for key in ("x", "y", "dx", "dy"):
                    _finite(point.get(key), "image_history.vector." + key)
            _unique([(point["x"], point["y"]) for point in points], "image_history coordinates")
        else:
            _fail("image_history.modality must be sem or overlay")
        ids.append(row["id"])
    _unique(ids, "image_history reference ids")


def _validate_defect_references(value: object, inform_notes: list[dict], image_history: list[dict],
                                historical_records: list[dict]) -> None:
    references = _array(value, "defect_references")
    if len(references) > 100:
        _fail("defect_references exceeds 100 records")
    informs = {row["id"]: row for row in inform_notes}
    images = {row["id"]: row for row in image_history}
    historical_by_id = {row["id"]: row for row in historical_records}
    ids = []
    required = {"id", "date", "step", "equipment", "item", "lotId", "waferId", "inform_id",
                "historical_record_id", "incident_number", "sem", "cd", "overlay", "finding", "synthetic"}
    for index, row in enumerate(references):
        item = _object(row, f"defect_references[{index}]")
        if set(item) != required:
            _fail(f"defect_references[{index}] has unsupported fields")
        for key in required - {"sem", "cd", "overlay", "synthetic"}:
            _string(item[key], f"defect_references[{index}].{key}")
        if item["synthetic"] is not True:
            _fail(f"defect_references[{index}].synthetic must be true")
        date_text = _timestamp(item["date"], f"defect_references[{index}].date")
        date_value = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
        inform = informs.get(item["inform_id"])
        historical = historical_by_id.get(item["historical_record_id"])
        if (not inform or inform["step"] != item["step"] or inform["equipment"] != item["equipment"]
                or not historical or any(historical.get(key) != item[key]
                                         for key in ("step", "item", "equipment", "lotId", "waferId"))
                or (inform and datetime.fromisoformat(inform["date"].replace("Z", "+00:00")) > date_value)
                or (historical and datetime.fromisoformat(historical["edsAt"].replace("Z", "+00:00")) > date_value)):
            _fail(f"defect_references[{index}] has an invalid Inform or historical record link")
        for modality in ("sem", "overlay"):
            reference = _object(item[modality], f"defect_references[{index}].{modality}")
            if set(reference) != {"image_history_id"}:
                _fail(f"defect_references[{index}].{modality} must reference image_history")
            image = images.get(reference["image_history_id"])
            if (not image or image["modality"] != modality or image["step"] != item["step"]
                    or image["item"] != item["item"]
                    or image["incident_number"] != item["incident_number"]
                    or datetime.fromisoformat(image["occurred_at"].replace("Z", "+00:00")) > date_value):
                _fail(f"defect_references[{index}].{modality} has an invalid image_history link")
        cd = _object(item["cd"], f"defect_references[{index}].cd")
        if set(cd) != {"unit", "range", "measurements"} or cd["unit"] != "nm":
            _fail(f"defect_references[{index}].cd must contain nm measurements")
        bounds = cd["range"]
        if not isinstance(bounds, list) or len(bounds) != 2 or not all(
                type(value) in (int, float) and math.isfinite(value) for value in bounds) or bounds[0] > bounds[1]:
            _fail(f"defect_references[{index}].cd.range must be finite and ordered")
        measurements = _array(cd["measurements"], f"defect_references[{index}].cd.measurements")
        if not measurements:
            _fail(f"defect_references[{index}].cd.measurements must not be empty")
        for point in measurements:
            point = _object(point, f"defect_references[{index}].cd.measurement")
            if set(point) != {"site", "value"}:
                _fail(f"defect_references[{index}].cd.measurement has unsupported fields")
            _string(point["site"], f"defect_references[{index}].cd.measurement.site")
            measured = _finite(point["value"], f"defect_references[{index}].cd.measurement.value")
            if not bounds[0] <= measured <= bounds[1]:
                _fail(f"defect_references[{index}].cd measurement is outside range")
        ids.append(item["id"])
    _unique(ids, "defect reference ids")


def _validate_incident(incident_number: str, record: object) -> dict:
    item = _object(record, f"incidents.{incident_number}")
    required = {"engineering", "trend_fleets", "comparison_traces", "inform_notes", "sem_assets"}
    if not required.issubset(item) or set(item) - required - {"historical_records", "image_history", "defect_references"}:
        _fail(f"incidents.{incident_number} must contain engineering, trend_fleets, comparison_traces, inform_notes and sem_assets")
    engineering = _object(item["engineering"], f"incidents.{incident_number}.engineering")
    signal_scopes = _validate_engineering(engineering)
    _validate_trend_fleets(item["trend_fleets"], engineering["signals"])
    _validate_comparison_traces(item["comparison_traces"], engineering["signals"])
    _validate_inform_notes(item["inform_notes"], signal_scopes)
    fab_pairs = {(row["lotId"], row["waferId"]) for row in engineering["fab"]}
    _validate_sem_assets(item["sem_assets"], fab_pairs)
    if "image_history" in item:
        _validate_image_history(item["image_history"])
    historical_records = []
    if "historical_records" in item:
        ids = []
        historical_records = _array(item["historical_records"], "historical_records")
        for row in historical_records:
            _object(row, "historical record")
            for field in ("id", "lotId", "waferId", "step", "item", "equipment", "recipe"):
                _string(row.get(field), "historical_records." + field)
            for field in ("temperature", "queue", "availability", "yieldPct", "bin3Pct", "bin4Pct"):
                _finite(row.get(field), "historical_records." + field)
            for field in ("availability", "yieldPct", "bin3Pct", "bin4Pct"):
                if not 0 <= row[field] <= 100:
                    _fail("historical_records percentage must be within 0..100")
            times = [datetime.fromisoformat(_timestamp(row.get(field), field).replace("Z", "+00:00"))
                     for field in ("fabAt", "edsAt")]
            if times[0] > times[1]:
                _fail("historical_records EDS must follow Fab")
            ids.append(row["id"])
        _unique(ids, "historical record ids")
    if "defect_references" in item:
        _validate_defect_references(item["defect_references"], item["inform_notes"],
                                     item.get("image_history", []), historical_records)
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
