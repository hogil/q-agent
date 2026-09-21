"""Read-only engineering snapshot over the validated workbench raw sidecar."""
from __future__ import annotations

import copy
import math
from datetime import date, datetime, time, timedelta, timezone

from incident_tools import ToolError


ENGINEERING_SOURCES = ("trend", "correlation", "production", "inform", "changes")
MAX_ROWS = 12
MAX_WIP_GROUPS = 100
_UNITS = {"temperature": "degC", "queue": "hours", "availability": "%"}


def _error(code: str) -> None:
    raise ToolError(code)


def _parse_time(value, code="INVALID_ENGINEERING_TIME", *, date_end=False):
    if not isinstance(value, str) or not value.strip():
        _error(code)
    if len(value) == 10:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            _error(code)
        return datetime.combine(parsed, time.max if date_end else time.min, tzinfo=timezone.utc)
    candidate = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        _error(code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _error(code)
    return parsed.astimezone(timezone.utc)


def _copy_rows(rows, limit=MAX_ROWS):
    rows = list(rows)
    return {"rows": copy.deepcopy(rows[:limit]), "count": len(rows), "truncated": len(rows) > limit}


def _summary(values, unit=None):
    values = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)
              and math.isfinite(value)]
    result = {"mean": None, "min": None, "max": None, "count": len(values)}
    if values:
        result.update(mean=round(sum(values) / len(values), 6), min=round(min(values), 6), max=round(max(values), 6))
    if unit is not None:
        result["unit"] = unit
    return result


class EngineeringTools:
    """Expose bounded, incident-scoped observations from normalized raw data.

    The constructor receives the UI selection only as a filter.  It never turns
    selection text into engineering evidence; every returned observation comes
    from the selected incident's raw record.
    """

    def __init__(self, raw_data, incident_map, context, sources):
        if not isinstance(raw_data, dict) or not raw_data:
            _error("SYNTHETIC_RAW_REQUIRED")
        if not isinstance(incident_map, dict) or not incident_map:
            _error("INCIDENT_LOOKUP_REQUIRED")
        self.raw_data = raw_data
        self.incident_map = incident_map
        self.context = self._validate_context(context)
        if not isinstance(sources, (list, tuple)):
            _error("INVALID_ENGINEERING_SOURCES")
        if any(type(source) is not str for source in sources):
            _error("INVALID_ENGINEERING_SOURCES")
        self.sources = tuple(dict.fromkeys(source for source in sources if source in ENGINEERING_SOURCES))

    @staticmethod
    def _validate_context(value):
        required = {"incident_number", "item", "step", "equipment", "from", "to", "wafers"}
        optional = {"recipe", "trend_selection", "sem_wafers", "map_view"}
        if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - optional:
            _error("INVALID_ENGINEERING_CONTEXT")
        if any(not isinstance(value[field], str) or (field != "equipment" and not value[field].strip())
               for field in ("incident_number", "item", "step", "equipment")):
            _error("INVALID_ENGINEERING_CONTEXT")
        start = _parse_time(value["from"])
        end = _parse_time(value["to"], date_end=True)
        if start > end:
            _error("INVALID_ENGINEERING_CONTEXT")
        wafers = value["wafers"]
        if not isinstance(wafers, list) or any(
                not isinstance(row, dict) or set(row) != {"lot_id", "wafer_id"}
                or any(not isinstance(item, str) or not item.strip() for item in row.values()) for row in wafers):
            _error("INVALID_ENGINEERING_CONTEXT")
        result = copy.deepcopy(value)
        result["_from_time"], result["_to_time"] = start, end
        if "recipe" in value and (not isinstance(value["recipe"], str) or len(value["recipe"]) > 256):
            _error("INVALID_ENGINEERING_CONTEXT")
        if "trend_selection" in value:
            selection = value["trend_selection"]
            if (not isinstance(selection, dict)
                    or set(selection) != {"range_selected", "value_range", "regions"}
                    or type(selection["range_selected"]) is not bool):
                _error("INVALID_ENGINEERING_CONTEXT")
            bounds = selection["value_range"]
            if bounds is not None and not _valid_bounds(bounds):
                _error("INVALID_ENGINEERING_CONTEXT")
            regions = selection["regions"]
            if (not isinstance(regions, list) or len(regions) > 16
                    or any(not isinstance(region, list) or len(region) != 2
                           or not all(_valid_bounds(axis) for axis in region) for region in regions)
                    or (not selection["range_selected"] and (regions or bounds is not None))):
                _error("INVALID_ENGINEERING_CONTEXT")
        if "map_view" in value:
            view = value["map_view"]
            if (not isinstance(view, dict) or set(view) != {"kind", "overlay"}
                    or view["kind"] not in ("cd", "thk", "overlay", "bin")
                    or view["overlay"] not in ("raw", "fit", "residual")):
                _error("INVALID_ENGINEERING_CONTEXT")
        return result

    @staticmethod
    def _scope_row(incident_map, incident_number):
        row = incident_map.get(incident_number)
        if not isinstance(row, dict):
            _error("INCIDENT_LOOKUP_REQUIRED")
        incident_id = row.get("incident_id")
        if not isinstance(incident_id, str) or not incident_id.strip():
            _error("INCIDENT_LOOKUP_REQUIRED")
        return row, incident_id

    def _record(self, incident_number):
        record = self.raw_data.get(incident_number)
        if not isinstance(record, dict):
            _error("ENGINEERING_RAW_INCIDENT_MISSING")
        return record

    def _signal_match(self, signal):
        return signal.get("step") == self.context["step"] and signal.get("item") == self.context["item"]

    def _in_time_scope(self, value, as_of=None):
        try:
            moment = _parse_time(value)
        except ToolError:
            return False
        return self.context["_from_time"] <= moment <= self.context["_to_time"] and (as_of is None or moment <= as_of)

    def _point_selected(self, timestamp_ms, value, as_of=None):
        if not isinstance(timestamp_ms, (int, float)) or not math.isfinite(timestamp_ms):
            return False
        moment = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        if not self.context["_from_time"] <= moment <= self.context["_to_time"]:
            return False
        if as_of is not None and moment > as_of:
            return False
        selection = self.context.get("trend_selection")
        if not selection or not selection["range_selected"]:
            return True
        regions = selection["regions"]
        if regions:
            return any(x[0][0] <= timestamp_ms <= x[0][1] and x[1][0] <= value <= x[1][1]
                       for x in regions)
        bounds = selection["value_range"]
        return bounds is None or bounds[0] <= value <= bounds[1]

    @staticmethod
    def _clip_interval(row, window_start, window_end):
        start = _parse_time(row["start"])
        end = _parse_time(row["end"])
        if end <= window_start or start >= window_end:
            return None
        clipped = copy.deepcopy(row)
        clipped["start"] = max(start, window_start).isoformat().replace("+00:00", "Z")
        clipped["end"] = min(end, window_end).isoformat().replace("+00:00", "Z")
        return clipped

    def _trend(self, record, as_of):
        engineering = record["engineering"]
        signals = [row for row in engineering["signals"] if self._signal_match(row)]
        signal_ids = {row["id"] for row in signals}
        fleets = {}
        stats = {}
        fleet_source = record.get("trend_fleets", {})
        for signal in signals:
            signal_id, metric = signal["id"], signal["metric"]
            traces = []
            selected_values = []
            matching_traces = fleet_source.get(signal_id, [])
            selected_members = {trace.get("member") for trace in matching_traces if trace.get("highlighted")}
            point_budget = 6
            group_stats = {}
            for trace in matching_traces:
                points = trace.get("points", [])
                selected_points = [point for point in points
                                   if isinstance(point, list) and len(point) == 2
                                   and self._point_selected(point[0], point[1], as_of)]
                if trace.get("member") in selected_members:
                    selected_values.extend(point[1] for point in selected_points)
                group_stats[trace.get("member")] = _summary(
                    [point[1] for point in selected_points], _UNITS.get(metric))
                visible_points = selected_points[:point_budget]
                point_budget = max(0, point_budget - len(visible_points))
                traces.append({"member": trace.get("member"), "highlighted": trace.get("highlighted", False),
                               "points": visible_points, "count": len(selected_points),
                               "truncated": len(selected_points) > len(visible_points)})
            fleets[signal_id] = traces
            selection = self.context.get("trend_selection", {})
            selected_start = as_of
            if selection.get("range_selected"):
                starts = [region[0][0] for region in selection.get("regions", [])]
                selected_start = (datetime.fromtimestamp(min(starts) / 1000, tz=timezone.utc)
                                  if starts else self.context["_from_time"])
            onset_index = signal.get("onsetIndex")
            onset_time = (engineering.get("trend", [])[onset_index].get("timestamp")
                          if isinstance(onset_index, int) and 0 <= onset_index < len(engineering.get("trend", [])) else None)
            baseline_cutoff = min(as_of, _parse_time(onset_time) if onset_time else as_of,
                                  selected_start)
            baseline_values = [point[1] for trace in matching_traces
                               if trace.get("member") in selected_members
                               for point in trace.get("points", [])
                               if point[0] < baseline_cutoff.timestamp() * 1000]
            stats[signal_id] = {"metric": metric, "unit": _UNITS.get(metric),
                                "selected": _summary(selected_values, _UNITS.get(metric)),
                                "baseline": _summary(baseline_values, _UNITS.get(metric)),
                                "group_stats": group_stats}
        trend_rows = [row for row in engineering.get("trend", []) if self._in_time_scope(row.get("timestamp"), as_of)]
        pairs = {(row["lot_id"], row["wafer_id"]) for row in self.context["wafers"]}
        fab_rows = [row for row in engineering.get("fab", [])
                    if self._in_time_scope(row.get("timestamp"), as_of)
                    and (not pairs or (row.get("lotId"), row.get("waferId")) in pairs)
                    and row.get("step") == self.context["step"]
                    and (not self.context["equipment"] or row.get("equipment") == self.context["equipment"])
                    and (not self.context.get("recipe") or row.get("recipe") == self.context["recipe"])]
        return {"signals": copy.deepcopy(signals[:MAX_ROWS]), "trend_fleets": fleets,
                "engineering_trend": _copy_rows(trend_rows), "fab": _copy_rows(fab_rows),
                "stats": stats, "signal_count": len(signal_ids)}

    def _production(self, record, as_of):
        engineering = record["engineering"]
        wip = [row for row in engineering.get("wip", [])
               if row.get("step") == self.context["step"]
               and (not self.context["equipment"] or row.get("equipment") == self.context["equipment"])
               and (not self.context.get("recipe") or row.get("recipe") == self.context["recipe"])]
        groups = {}
        for row in wip:
            key = (row.get("step"), row.get("equipment"), row.get("recipe"))
            group = groups.setdefault(key, {"step": key[0], "equipment": key[1], "recipe": key[2],
                                             "rows": 0, "wafers": 0})
            group["rows"] += 1
            group["wafers"] += row.get("wafers", 0)
        detections = [_parse_time(signal["detectedAt"]) for signal in engineering.get("signals", [])
                      if self._signal_match(signal)]
        anchor = min(detections) if detections else self.context["_from_time"]
        window_start = anchor - timedelta(days=3.5)
        window_end = min(anchor + timedelta(days=3.5), as_of)
        states = []
        for row in engineering.get("equipmentStates", []):
            if self.context["equipment"] and row.get("equipment") != self.context["equipment"]:
                continue
            clipped = self._clip_interval(row, window_start, window_end)
            if clipped:
                states.append(clipped)
        downtime = []
        for row in engineering.get("downtime", []):
            if self.context["equipment"] and row.get("equipment") != self.context["equipment"]:
                continue
            clipped = self._clip_interval(row, window_start, window_end)
            if clipped:
                downtime.append(clipped)
        return {"wip": _copy_rows(wip), "wip_by_step_equipment_recipe": _copy_rows(list(groups.values()), MAX_WIP_GROUPS),
                "equipmentStates": _copy_rows(states), "downtime": _copy_rows(downtime),
                "detection_window": {"from": window_start.isoformat().replace("+00:00", "Z"),
                                     "to": window_end.isoformat().replace("+00:00", "Z"),
                                     "days_each_side": 3.5, "clipped_as_of": True}}

    def _inform(self, record, as_of):
        rows = [row for row in record.get("inform_notes", [])
                if row.get("step") == self.context["step"]
                and (not self.context["equipment"] or row.get("equipment") == self.context["equipment"])
                and _parse_time(row.get("date")) <= as_of]
        return _copy_rows(rows)

    def _changes(self, record, as_of):
        rows = [row for row in record["engineering"].get("changes", [])
                if _parse_time(row.get("timestamp")) <= as_of
                and self.context["_from_time"] <= _parse_time(row.get("timestamp")) <= self.context["_to_time"]
                and (not self.context["equipment"] or row.get("equipment") == self.context["equipment"])
                and (not self.context.get("recipe") or not row.get("recipe") or row.get("recipe") == self.context["recipe"])]
        return _copy_rows(rows)

    def _correlation(self, record, as_of):
        historical = record.get("historical_records")
        if not isinstance(historical, list):
            return {"baseline": "historical_records", "rows": [], "count": 0,
                    "pearson_r": None,
                    "truncated": False, "limitations": ["RAW_HISTORICAL_PAIRS_UNAVAILABLE"]}
        signals = [row for row in record["engineering"].get("signals", []) if self._signal_match(row)]
        signal = signals[0] if signals else None
        metric = signal.get("metric") if signal else None
        rows = []
        for row in historical:
            if not isinstance(row, dict) or not all(key in row for key in (
                    "id", "lotId", "waferId", "step", "item", "equipment", "recipe",
                    "fabAt", "edsAt", "temperature", "queue", "availability", "yieldPct")):
                continue
            eds_at = _parse_time(row["edsAt"])
            fab_at = _parse_time(row["fabAt"])
            if (row["step"] == self.context["step"] and row["item"] == self.context["item"]
                    and (not self.context["equipment"] or row["equipment"] == self.context["equipment"])
                    and (not self.context.get("recipe") or row["recipe"] == self.context["recipe"])
                    and eds_at < self.context["_from_time"] and eds_at <= as_of
                    and fab_at <= eds_at and fab_at <= as_of):
                rows.append(row)
        values = [(row[metric], row["yieldPct"]) for row in rows
                  if metric and isinstance(row.get(metric), (int, float))
                  and isinstance(row.get("yieldPct"), (int, float))
                  and not isinstance(row.get(metric), bool) and not isinstance(row.get("yieldPct"), bool)
                  and math.isfinite(row[metric]) and math.isfinite(row["yieldPct"])]
        pearson = None
        if len(values) >= 2:
            x_mean = sum(pair[0] for pair in values) / len(values)
            y_mean = sum(pair[1] for pair in values) / len(values)
            numerator = sum((x - x_mean) * (y - y_mean) for x, y in values)
            x_var = sum((x - x_mean) ** 2 for x, _ in values)
            y_var = sum((y - y_mean) ** 2 for _, y in values)
            if x_var > 0 and y_var > 0:
                pearson = numerator / math.sqrt(x_var * y_var)
        paired = [{"id": row["id"], "lotId": row["lotId"], "waferId": row["waferId"],
                   "fabAt": row["fabAt"], "edsAt": row["edsAt"], "metric": row[metric],
                   "yieldPct": row["yieldPct"]} for row in rows if metric]
        result = {"baseline": "historical_records", "metric": metric, "unit": _UNITS.get(metric),
                  "yield_unit": "%", "count": len(values), "pearson_r": pearson,
                  "truncated": len(rows) > MAX_ROWS, "rows": paired[:MAX_ROWS]}
        if len(rows) > MAX_ROWS:
            result["limitations"] = ["CORRELATION_ROWS_TRUNCATED"]
        return result

    def query(self, actor, incident_ids, as_of):
        if not isinstance(actor, str) or not actor.strip():
            _error("INVALID_ACTOR")
        if not isinstance(incident_ids, list) or len(incident_ids) != 1 or type(incident_ids[0]) is not str:
            _error("INCIDENT_SCOPE_MISMATCH")
        incident_number = self.context["incident_number"]
        _, actual_id = self._scope_row(self.incident_map, incident_number)
        if incident_ids[0] != actual_id:
            _error("INCIDENT_SCOPE_MISMATCH")
        as_of_value = _parse_time(as_of, date_end=True)
        record = self._record(incident_number)
        sections = {}
        limitations = []
        for source in self.sources:
            if source == "trend":
                sections[source] = self._trend(record, as_of_value)
            elif source == "production":
                sections[source] = self._production(record, as_of_value)
            elif source == "inform":
                sections[source] = self._inform(record, as_of_value)
            elif source == "changes":
                sections[source] = self._changes(record, as_of_value)
            elif source == "correlation":
                sections[source] = self._correlation(record, as_of_value)
                limitations.extend(sections[source].get("limitations", []))
        scope = {key: copy.deepcopy(value) for key, value in self.context.items() if not key.startswith("_")}
        scope.update({"incident_ids": list(incident_ids), "as_of": as_of})
        return {"status": "OK", "synthetic": True, "sections": sections,
                "limitations": limitations, "scope": scope}


def _valid_bounds(value):
    return (isinstance(value, list) and len(value) == 2
            and all(type(item) in (int, float) and math.isfinite(item) for item in value)
            and value[0] <= value[1])
