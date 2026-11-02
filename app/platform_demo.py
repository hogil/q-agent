"""Generate a deterministic, synthetic multi-source platform fixture."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import math
import random
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from config_loader import add_config_arguments, load_config


AS_OF = "2026-10-24"
FAMILIES = ("normal", "temperature_drift", "sem_bridge", "sem_gap", "failbit_row", "measurement_shift")
IDENTIFIER = re.compile(r"^[^\W\d]\w*$", re.UNICODE)
PLATFORM_TYPES = {
    "record_id": "string", "incident_id": "string", "lot_id": "string", "equipment": "string",
    "step": "string", "recipe": "string", "occurred_at": "string", "available_at": "string",
    "status": "string", "hold_code": "string", "queue_hours": "number", "wafer_id": "string",
    "stage": "string", "yield_pct": "number", "bin_code": "string", "fail_count": "integer",
    "tested_count": "integer", "chip_id": "string", "die_x": "integer", "die_y": "integer",
    "item": "string", "value": "number", "unit": "string", "lower_limit": "number",
    "upper_limit": "number", "bit_x": "integer", "bit_y": "integer", "test_item": "string",
    "asset_id": "string", "storage_ref": "string", "sha256": "string", "pixel_size_nm": "number",
    "orientation": "string", "edge_density": "number", "contrast": "number",
    "training_label": "string", "timestamp": "string", "document_id": "string", "title": "string",
    "content": "string", "version": "string", "synthetic": "boolean",
}
PLATFORM_FIELDS = {
    "mes": ("record_id incident_id lot_id equipment step recipe occurred_at available_at status hold_code queue_hours synthetic").split(),
    "test": ("record_id incident_id lot_id wafer_id stage equipment step occurred_at available_at yield_pct bin_code fail_count tested_count synthetic").split(),
    "measure": ("record_id incident_id lot_id wafer_id chip_id die_x die_y item value unit lower_limit upper_limit stage occurred_at available_at synthetic").split(),
    "failbit": ("record_id incident_id lot_id wafer_id chip_id bit_x bit_y test_item fail_count bin_code occurred_at available_at synthetic").split(),
    "sem": ("record_id incident_id lot_id wafer_id chip_id asset_id storage_ref sha256 pixel_size_nm orientation recipe edge_density contrast training_label occurred_at available_at synthetic").split(),
    "trend": ("record_id incident_id lot_id wafer_id equipment step item timestamp value unit available_at training_label synthetic").split(),
    "inform": ("record_id incident_id document_id title content version step equipment occurred_at available_at synthetic").split(),
}


def _ident(value: str, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label}: invalid SQLite identifier")
    return '"' + value + '"'


def _inside(path: Path, root: Path, label: str) -> Path:
    path, root = path.resolve(), root.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError(f"{label}: generated output must be inside paths.data_root") from None
    return path


def _utc_text(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _case(index: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed * 1_000_003 + index)
    family = rng.choice(FAMILIES)
    incident_id = f"synp-{index:04d}"
    incident_number = f"SYN-P-{index:04d}"
    day = (index * 29) % 274
    happened = datetime(2026, 1, 1, tzinfo=None) + timedelta(days=day, hours=rng.randrange(24), minutes=rng.randrange(60))
    happened = happened.replace(tzinfo=timezone(timedelta(hours=9)))
    step = f"SYN-STEP-{rng.randrange(1, 5):02d}"
    equipment = f"SYN-EQ-{rng.randrange(1, 9):02d}"
    if family == "normal":
        variant = ("normal_counterexample", "normal", "normal")[rng.randrange(3)]
    else:
        variant = "unconfirmed" if index % 5 == 0 else "synthetic_signal"
    return {"index": index, "incident_id": incident_id, "incident_number": incident_number,
            "family": family, "variant": variant, "title": f"합성 플랫폼 기록 {index:04d}", "happened": happened,
            "equipment": equipment, "step": step}


def _availability(happened: datetime, hours: int) -> str:
    return _utc_text(happened + timedelta(hours=hours))


def _type_for(field: str) -> str:
    if field in ("expected_lot_count", "affected_wafer_count"):
        return "INTEGER"
    if field in ("product_generations", "fab_out_failure_codes"):
        return "TEXT"
    return "TEXT"


def _create_mapped_table(con: sqlite3.Connection, mapping: dict[str, Any], types: dict[str, str] | None = None,
                         primary_key: str | None = None) -> None:
    columns = {key: value for key, value in mapping["columns"].items() if value}
    if not columns:
        raise ValueError("table mapping must include at least one column")
    definitions = []
    for logical, physical in columns.items():
        sql_type = (types or {}).get(logical, "TEXT")
        if sql_type not in ("TEXT", "INTEGER", "REAL"):
            raise ValueError("unsupported generated column type")
        definition = f"{_ident(physical, 'column')} {sql_type}"
        if logical == primary_key:
            definition += " PRIMARY KEY"
        definitions.append(definition)
    con.execute(f"CREATE TABLE {_ident(mapping['name'], 'table')} ({', '.join(definitions)})")


def _write_rows(con: sqlite3.Connection, mapping: dict[str, Any], records: Iterable[dict[str, Any]],
                *, batch_size: int = 1000) -> int:
    columns = {key: value for key, value in mapping["columns"].items() if value}
    physical = [_ident(value, "column") for value in columns.values()]
    sql = (f"INSERT INTO {_ident(mapping['name'], 'table')} ({', '.join(physical)}) "
           f"VALUES ({', '.join('?' for _ in physical)})")
    logical = list(columns)
    batch, count = [], 0
    for row in records:
        values = []
        for key in logical:
            value = row.get(key)
            if key in ("product_generations", "fab_out_failure_codes") and value is not None:
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(value, bool):
                value = int(value)
            values.append(value)
        batch.append(tuple(values))
        if len(batch) >= batch_size:
            con.executemany(sql, batch)
            count += len(batch)
            batch.clear()
    if batch:
        con.executemany(sql, batch)
        count += len(batch)
    return count


def _incident_row(case: dict[str, Any], lots: int, wafers: int) -> dict[str, Any]:
    return {
        "incident_id": case["incident_id"], "incident_number": case["incident_number"],
        "title": case["title"], "city": f"SYN-CITY-{case['index'] % 4 + 1}",
        "line": f"SYN-LINE-{case['index'] % 3 + 1:02d}", "line_code": f"SYN{case['index'] % 3 + 1:02d}",
        "line_alias": "SYNTH", "department": "SYNTH-QA", "occurred_at": _utc_text(case["happened"]),
        "product_generations": ["SYN-GEN-A", "SYN-GEN-B" if case["index"] % 2 else "SYN-GEN-C"],
        "fab_out_failure_codes": ["SYNTH_PATTERN"], "expected_lot_count": lots,
        "affected_wafer_count": lots * wafers,
        "incident_detail": "절차적으로 생성한 합성 플랫폼 fixture; 실제 생산 데이터가 아님.",
        "analysis_detail": "합성 feature 시연용 기록이며 원인·상관관계는 검증되지 않음.",
        "confirmed_cause": None, "containment": "합성 fixture 범위 전용.",
        "corrective_action": "합성 데이터이며 실제 조치 없음.", "verification": None,
        "prevention": "실제 원인·조치로 해석하지 않음.", "remaining": "실제 자료 검증 미수행.",
    }


def _lot_rows(settings: Any, count: int, lots_per_incident: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    for i in range(1, count + 1):
        case = _case(i, seed)
        for lot_n in range(1, lots_per_incident + 1):
            yield {"incident_ref": case["incident_id"], "lot_id": f"SYN-LOT-{i:04d}-{lot_n:02d}",
                   "product_code": f"SYN-PRODUCT-{i % 5 + 1}", "status": "SYNTHETIC_REGISTERED"}


def _wafer_rows(settings: Any, count: int, lots_per_incident: int, wafers_per_lot: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    for i in range(1, count + 1):
        case = _case(i, seed)
        for lot_n in range(1, lots_per_incident + 1):
            lot_id = f"SYN-LOT-{i:04d}-{lot_n:02d}"
            for wafer_n in range(1, wafers_per_lot + 1):
                yield {"incident_ref": case["incident_id"], "lot_id": lot_id,
                       "wafer_id": f"W{wafer_n:02d}", "status": "SYNTHETIC_REGISTERED"}


def _mes_rows(settings: Any, count: int, lots_per_incident: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    for i in range(1, count + 1):
        case = _case(i, seed)
        for lot_n in range(1, lots_per_incident + 1):
            lot_id = f"SYN-LOT-{i:04d}-{lot_n:02d}"
            when = case["happened"] + timedelta(minutes=lot_n * 10)
            status = ('HOLD' if case['family'] != 'normal' and lot_n == 1
                      else 'WAIT' if (i + lot_n) % 4 == 0 else 'RUN')
            yield {"record_id": f"mes-{i:04d}-{lot_n:02d}", "incident_id": case["incident_id"],
                   "lot_id": lot_id, "equipment": case["equipment"], "step": case["step"],
                   "recipe": f"SYN-RECIPE-{i % 7 + 1}", "occurred_at": _utc_text(when),
                   "available_at": _availability(when, 2), "status": status,
                   "hold_code": "SYN-QUALITY-REVIEW" if status == 'HOLD' else 'NONE',
                   "queue_hours": round((4 if status in ('HOLD', 'WAIT') else .5) + (i % 12) * .25, 2), "synthetic": True}


def _chip_values(case: dict[str, Any], lot_n: int, wafer_n: int, chips: int, seed: int):
    rng = random.Random(seed + case["index"] * 100_003 + lot_n * 101 + wafer_n * 7)
    for chip_n in range(chips):
        leakage = max(0.1, rng.gauss(2.0, 0.35))
        vth = rng.gauss(0.55, 0.025)
        if case["family"] == "measurement_shift":
            interval = 16 if case["variant"] == "unconfirmed" else 8
            if chip_n % interval == 0:
                vth += 0.10 if case["variant"] == "unconfirmed" else 0.16
        elif case["variant"] == "normal_counterexample" and chip_n % 16 == 0:
            vth += 0.075
        yield chip_n, leakage, vth


def _failbit_chip_count(case: dict[str, Any], chips: int) -> int:
    if case["family"] != "failbit_row":
        return 0
    requested = 1 if case["variant"] == "unconfirmed" else 2
    return min(chips, requested)


def _chip_failed(case: dict[str, Any], chip_n: int, leakage: float, vth: float, chips: int) -> bool:
    return (vth < 0.40 or vth > 0.70 or leakage > 10.0
            or chip_n < _failbit_chip_count(case, chips))


def _test_rows(settings: Any, count: int, lots: int, wafers: int, chips: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    for i in range(1, count + 1):
        case = _case(i, seed)
        for lot_n in range(1, lots + 1):
            lot_id = f"SYN-LOT-{i:04d}-{lot_n:02d}"
            for wafer_n in range(1, wafers + 1):
                wafer_id = f"W{wafer_n:02d}"
                fail_count = sum(1 for chip_n, leakage, vth in _chip_values(case, lot_n, wafer_n, chips, seed)
                                 if _chip_failed(case, chip_n, leakage, vth, chips))
                # Both generated stages use this same synthetic chip-level rule; it does not assert causality.
                for stage_n, stage in enumerate(("EDS", "FAB_OUT")):
                    when = case["happened"] + timedelta(hours=stage_n + wafer_n / 10)
                    yield {"record_id": f"test-{i:04d}-{lot_n:02d}-{wafer_n:02d}-{stage_n}",
                           "incident_id": case["incident_id"], "lot_id": lot_id, "wafer_id": wafer_id,
                           "stage": stage, "equipment": case["equipment"], "step": case["step"],
                           "occurred_at": _utc_text(when), "available_at": _availability(when, 3),
                           "yield_pct": round(100.0 * (chips - fail_count) / chips, 4),
                           "bin_code": "SYN-BIN-FAIL" if fail_count else "SYN-BIN-PASS",
                           "fail_count": fail_count, "tested_count": chips, "synthetic": True}


def _measure_rows(settings: Any, count: int, lots: int, wafers: int, chips: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    for i in range(1, count + 1):
        case = _case(i, seed)
        for lot_n in range(1, lots + 1):
            lot_id = f"SYN-LOT-{i:04d}-{lot_n:02d}"
            for wafer_n in range(1, wafers + 1):
                wafer_id = f"W{wafer_n:02d}"
                when = case["happened"] + timedelta(hours=1)
                for chip_n, leakage, vth in _chip_values(case, lot_n, wafer_n, chips, seed):
                    chip_id = f"{wafer_id}-C{chip_n:03d}"
                    x, y = chip_n % 8, chip_n // 8
                    for metric, value, unit, lower, upper in (
                            ("leakage_uA", leakage, "uA", 0.0, 10.0),
                            ("Vth_V", vth, "V", 0.40, 0.70)):
                        yield {"record_id": f"measure-{i:04d}-{lot_n:02d}-{wafer_n:02d}-{chip_n:03d}-{metric}",
                               "incident_id": case["incident_id"], "lot_id": lot_id, "wafer_id": wafer_id,
                               "chip_id": chip_id, "die_x": x, "die_y": y, "item": metric,
                               "value": round(value, 6), "unit": unit, "lower_limit": lower,
                               "upper_limit": upper, "stage": "EDS", "occurred_at": _utc_text(when),
                               "available_at": _availability(when, 4), "synthetic": True}


def _failbit_rows(settings: Any, count: int, lots: int, wafers: int, chips: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    for i in range(1, count + 1):
        case = _case(i, seed)
        for lot_n in range(1, lots + 1):
            for wafer_n in range(1, wafers + 1):
                target_chips = _failbit_chip_count(case, chips)
                if not target_chips:
                    continue
                lot_id, wafer_id = f"SYN-LOT-{i:04d}-{lot_n:02d}", f"W{wafer_n:02d}"
                when = case["happened"] + timedelta(hours=1)
                for chip_n in range(target_chips):
                    for bit_n in range(4):
                        yield {"record_id": f"failbit-{i:04d}-{lot_n:02d}-{wafer_n:02d}-{chip_n:03d}-{bit_n:02d}",
                               "incident_id": case["incident_id"], "lot_id": lot_id, "wafer_id": wafer_id,
                               "chip_id": f"{wafer_id}-C{chip_n:03d}", "bit_x": bit_n, "bit_y": 2,
                               "test_item": "SYN-ROW-TEST", "fail_count": 1, "bin_code": "SYN-BIN-FAIL",
                               "occurred_at": _utc_text(when), "available_at": _availability(when, 4), "synthetic": True}


def _failbit_asset_rows(records: list[dict[str, Any]], image_dir: Path) -> list[dict[str, Any]]:
    from PIL import Image, ImageDraw

    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (record["incident_id"], record["lot_id"], record["wafer_id"], record["chip_id"])
        groups.setdefault(key, []).append(record)
    image_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    for incident_id, lot_id, wafer_id, chip_id in sorted(groups):
        asset_id = f"failbit-{incident_id}-{lot_id}-{wafer_id}-{chip_id}"
        image = Image.new("L", (64, 64), 238)
        draw = ImageDraw.Draw(image)
        cell = 2
        for grid in range(0, 64, cell):
            draw.line((grid, 0, grid, 63), fill=198, width=1)
            draw.line((0, grid, 63, grid), fill=198, width=1)
        for record in groups[(incident_id, lot_id, wafer_id, chip_id)]:
            x, y = record["bit_x"] * cell, record["bit_y"] * cell
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=25)
        path = image_dir / f"{asset_id}.png"
        image.save(path, format="PNG", optimize=False)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assets.append({"asset_id": asset_id, "image_id": asset_id, "incident_id": incident_id,
                       "lot_id": lot_id, "wafer_id": wafer_id, "chip_id": chip_id,
                       "storage_ref": f"platform_failbit/{asset_id}.png", "sha256": digest,
                       "stage": "EDS_FAILBIT", "coordinate_system": "chip_bit_grid"})
    return assets


def _trend_label(case: dict[str, Any]) -> str:
    if case["family"] == "temperature_drift":
        return "drift"
    if case["family"] == "measurement_shift":
        return "shift"
    if case["family"] == "normal" and (case["variant"] == "normal_counterexample" or case["index"] % 4 == 0):
        return "spike"
    return "normal"


def _trend_value(label: str, item: str, point: int, rng: random.Random, unconfirmed: bool = False) -> tuple[float, str]:
    wave = math.sin(point / 8.0)
    if item == "temperature":
        value = 24.0 + wave * 0.25 + rng.uniform(-0.08, 0.08)
        if label == "drift": value += point * (0.006 if unconfirmed else 0.018)
        return value, "degC"
    if item == "pressure":
        value = 100.0 + wave * 0.8 + rng.uniform(-0.2, 0.2)
        if label == "shift" and point >= 48: value += 1.5 if unconfirmed else 5.0
        return value, "kPa"
    value = 1.5 + wave * 0.04 + rng.uniform(-0.015, 0.015)
    if label == "spike" and point == 52: value += 1.2
    return value, "A"


def _trend_rows(settings: Any, count: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    for i in range(1, count + 1):
        case = _case(i, seed)
        label = _trend_label(case)
        rng = random.Random(seed + i * 1777)
        lot_id, wafer_id = f"SYN-LOT-{i:04d}-01", "W01"
        for item in ("temperature", "pressure", "current"):
            # A raw series is normal when the scenario's signal belongs to another sensor.
            item_label = label if {'drift': 'temperature', 'shift': 'pressure', 'spike': 'current'}.get(label) == item else 'normal'
            for point in range(96):
                value, unit = _trend_value(item_label, item, point, rng, case["variant"] == "unconfirmed")
                when = case["happened"] + timedelta(hours=point)
                yield {"record_id": f"trend-{i:04d}-{item}-{point:03d}", "incident_id": case["incident_id"],
                       "lot_id": lot_id, "wafer_id": wafer_id, "equipment": case["equipment"],
                       "step": case["step"], "item": item, "timestamp": _utc_text(when),
                       "value": round(value, 5), "unit": unit, "available_at": _availability(when, 2),
                       "training_label": item_label, "synthetic": True}


def _notes(settings: Any, count: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    for i in range(1, count + 1):
        case = _case(i, seed)
        hypothesis, counterevidence = {
            'normal': ('정상 비교군의 Vth·leakage 규격과 센서 기준 분포를 검토한다.',
                       '일시적 current spike만으로 검사 불량이나 사고 원인을 확정할 수 없다.'),
            'temperature_drift': ('temperature의 점진적 변화와 검사 시점의 연관을 가설로 검토한다.',
                                  'pressure/current와 전기 Measure가 정상일 수 있다. 센서 변화와 불량 영향은 분리해 확인한다.'),
            'sem_bridge': ('SEM의 연결 형태를 정상 patch와 비교하고 bridge 형태 가능성을 검토한다.',
                           '전기검사 정상과 표면 형태는 공존할 수 있다. SEM pixel과 bit 좌표의 물리 정합은 미확인이다.'),
            'sem_gap': ('SEM 단절 형태와 Vth·leakage 및 검사 결과의 일치 여부를 검토한다.',
                        '표면 gap 관측만으로 전기 open을 확정하지 않는다. 촬영 조건과 같은 Chip의 추가 검사가 필요하다.'),
            'failbit_row': ('같은 Chip의 row 방향 bit 실패와 EDS/FAB_OUT의 failed chip 분모를 대조한다.',
                            'SEM 정상 형태도 함께 관측될 수 있다. 검사 프로그램·주소 매핑·재시험 조건이 원인 확인에 필요하다.'),
            'measurement_shift': ('Vth 규격 초과 Chip과 pressure 변화 시점을 대조하고 probe/recipe 차이를 검토한다.',
                                  'leakage와 SEM은 정상일 수 있다. pressure와 Vth의 연관은 합성 설계이며 물리 인과 증거가 아니다.')
        }[case['family']]
        for version_n, (stance, delay) in enumerate((
                ("승인된 합성 가설 검토이며 원인 확정이 아님", 12),
                ("승인된 합성 반대 근거이며 인과 확정이 아님", 7 * 24)), 1):
            when = case["happened"] + timedelta(hours=delay)
            note_id = f"inform-{i:04d}-{version_n}"
            title = f"{case['incident_number']} 합성 근거 메모 v{version_n}"
            content = (f"{case['incident_number']} 합성 데이터 메모. {stance}. "
                       + (hypothesis if version_n == 1 else counterevidence) + ' '
                       f"step={case['step']}, equipment={case['equipment']}, "
                       f"reference_time={_utc_text(case['happened'])}, note_time={_utc_text(when)}. "
                       "관측 feature와 같은 시간·step 범위를 비교하는 예시이며 실제 공정 사실이 아니다.")
            yield {"record_id": note_id, "incident_id": case["incident_id"],
                   "document_id": f"doc-{i:04d}-{version_n}", "title": title, "content": content,
                   "version": f"v{version_n}", "step": case["step"], "equipment": case["equipment"],
                   "occurred_at": _utc_text(when), "available_at": _availability(when, 1),
                   "synthetic": True, "meeting_id": f"meeting-{i:04d}-{version_n}",
                   "meeting_date": _availability(when, 1)[:10], "status": "approved",
                   "source_ref": f"synthetic://platform/inform/{note_id}"}


def _sem_patch(case: dict[str, Any], view: int):
    from PIL import Image, ImageDraw

    image = Image.new("L", (96, 96), 218)
    draw = ImageDraw.Draw(image)
    family = case["family"]
    rng = random.Random(case["index"] * 31 + view)
    for _ in range(14):
        x, y = rng.randrange(4, 92), rng.randrange(4, 92)
        draw.ellipse((x, y, x + 1, y + 1), fill=rng.randrange(180, 235))
    tone = 90 if case["variant"] == "unconfirmed" else 35
    if family == "sem_bridge":
        draw.line((24, 12, 24, 84), fill=tone, width=5)
        draw.line((70, 12, 70, 84), fill=tone, width=5)
        draw.line((24, 47 + view, 70, 47 + view), fill=tone + 5, width=4)
        label = "bridge"
    elif family == "sem_gap":
        draw.line((10, 48, 42, 48), fill=tone + 3, width=5)
        draw.line((55, 48, 86, 48), fill=tone + 3, width=5)
        draw.line((49, 12, 49, 40), fill=55, width=3)
        label = "gap"
    else:
        draw.line((10, 48, 86, 48), fill=48, width=4)
        draw.line((30, 12, 30, 84), fill=80, width=2)
        label = "normal"
    pixels = list(image.getdata())
    mean_pixel = sum(pixels) / len(pixels)
    contrast = (sum((value - mean_pixel) ** 2 for value in pixels) / len(pixels)) ** 0.5 / 255.0
    edges = 0
    for y in range(96):
        for x in range(96):
            value = pixels[y * 96 + x]
            if x < 95 and abs(value - pixels[y * 96 + x + 1]) >= 36: edges += 1
            if y < 95 and abs(value - pixels[(y + 1) * 96 + x]) >= 36: edges += 1
    edge_density = edges / (2 * 96 * 96 - 192)
    return image, round(edge_density, 6), round(contrast, 6), label


def _sem_rows(settings: Any, count: int, image_dir: Path, chips: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    image_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        case = _case(i, seed)
        lot_id, wafer_id = f"SYN-LOT-{i:04d}-01", "W01"
        when = case["happened"] + timedelta(hours=2)
        for view in range(2):
            asset_id = f"sem-{i:04d}-{view + 1}"
            image, edge_density, contrast, label = _sem_patch(case, view)
            path = image_dir / f"{asset_id}.png"
            image.save(path, format="PNG", optimize=False)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            yield {"record_id": asset_id, "incident_id": case["incident_id"], "lot_id": lot_id,
                   "wafer_id": wafer_id, "chip_id": f"{wafer_id}-C{min(view, chips - 1):03d}", "asset_id": asset_id,
                   "storage_ref": f"platform_demo/{asset_id}.png", "sha256": digest,
                   "pixel_size_nm": 1.5, "orientation": "synthetic_top_down", "recipe": "SYN-SEM-RECIPE-1",
                   "edge_density": edge_density, "contrast": contrast, "training_label": label,
                   "occurred_at": _utc_text(when), "available_at": _availability(when, 5), "synthetic": True}


def _document_rows(notes: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for note in notes:
        yield {"document_id": note["document_id"], "incident_ref": note["incident_id"],
               "title": note["title"], "version": note["version"],
               "storage_ref": note["source_ref"], "format": "synthetic_text", "source": "synthetic_platform"}


def _chunk_rows(notes: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for note in notes:
        yield {"chunk_id": note["record_id"], "document_ref": note["document_id"],
               "location": "synthetic-note-1", "content": note["content"]}


def _image_metadata_rows(sem_rows: Iterable[dict[str, Any]], failbit_rows: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for row in sem_rows:
        yield {"image_id": row["asset_id"], "asset_id": row["asset_id"], "sha256": row["sha256"],
               "incident_ref": row["incident_id"], "lot_id": row["lot_id"],
               "wafer_id": row["wafer_id"], "stage": "SEM", "storage_ref": row["storage_ref"],
               "coordinate_system": "synthetic-pixel-grid"}
    for row in failbit_rows:
        yield {"image_id": row["image_id"], "asset_id": row["asset_id"], "sha256": row["sha256"],
               "incident_ref": row["incident_id"], "lot_id": row["lot_id"],
               "wafer_id": row["wafer_id"], "stage": row["stage"], "storage_ref": row["storage_ref"],
               "coordinate_system": row["coordinate_system"]}


def _trend_metadata_rows(settings: Any, count: int) -> Iterable[dict[str, Any]]:
    seed = settings.data["platform"]["seed"]
    for i in range(1, count + 1):
        case = _case(i, seed)
        for item, unit in (("temperature", "degC"), ("pressure", "kPa"), ("current", "A")):
            yield {"trend_id": f"trend-meta-{i:04d}-{item}", "incident_ref": case["incident_id"],
                   "metric": item, "unit": unit,
                   "storage_ref": f"synthetic://platform/trend/{case['incident_id']}/{item}",
                   "timezone": "Asia/Seoul"}


def _make_meeting_db(path: Path, config: dict[str, Any], notes: Iterable[dict[str, Any]]) -> int:
    table, fts = _ident(config["table"], "meetings.table"), _ident(config["fts_table"], "meetings.fts_table")
    count = 0
    with closing(sqlite3.connect(path)) as con, con:
        con.execute(f"CREATE TABLE {table} (chunk_id TEXT PRIMARY KEY, meeting_id TEXT, title TEXT, meeting_date TEXT, version TEXT, status TEXT CHECK(status IN ('approved','draft')), incident_ids TEXT, text TEXT, source_ref TEXT)")
        con.execute(f"CREATE VIRTUAL TABLE {fts} USING fts5(chunk_id UNINDEXED, title, text, tokenize='unicode61')")
        batch = []
        for note in notes:
            batch.append(note)
            if len(batch) == 500:
                _insert_meetings(con, table, fts, batch)
                count += len(batch)
                batch.clear()
        if batch:
            _insert_meetings(con, table, fts, batch)
            count += len(batch)
    return count


def _insert_meetings(con: sqlite3.Connection, table: str, fts: str, batch: list[dict[str, Any]]) -> None:
    rows = [(r["record_id"], r["meeting_id"], r["title"], r["meeting_date"], r["version"], r["status"],
             json.dumps([r["incident_id"]], separators=(",", ":")), r["content"], r["source_ref"]) for r in batch]
    con.executemany(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.executemany(f"INSERT INTO {fts}(chunk_id,title,text) VALUES (?,?,?)",
                    [(r[0], r[2], r[7]) for r in rows])


def _create_index(con: sqlite3.Connection, mapping: dict[str, Any], fields: tuple[str, ...], suffix: str) -> None:
    columns = mapping["columns"]
    if not all(columns.get(field) for field in fields):
        return
    name = _ident(f"{mapping['name']}_{suffix}_idx", "index")
    table = _ident(mapping["name"], "table")
    keys = ", ".join(_ident(columns[field], "column") for field in fields)
    con.execute(f"CREATE INDEX {name} ON {table} ({keys})")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(settings: Any) -> dict[str, Any]:
    """Create mapped synthetic SQLite tables and procedural SEM patches without overwriting."""
    data = settings.data
    platform = data.get("platform")
    if not isinstance(platform, dict) or platform.get("enabled") is not True:
        raise ValueError("platform.enabled must be true")
    if data.get("environment") not in ("demo", "test"):
        raise ValueError("platform fixture generation requires demo/test environment")
    if data.get("meetings", {}).get("enabled") is not True or data["meetings"].get("backend") != "sqlite":
        raise ValueError("platform fixture generation requires enabled SQLite meetings")
    for key, upper in (("incident_count", 2000), ("lots_per_incident", 10),
                       ("wafers_per_lot", 25), ("chips_per_wafer", 256)):
        if type(platform.get(key)) is not int or not 1 <= platform[key] <= upper:
            raise ValueError(f"platform.{key} is out of range")
    if type(platform.get("seed")) is not int:
        raise ValueError("platform.seed must be an integer")
    if set(platform.get("tables", {})) != set(PLATFORM_FIELDS):
        raise ValueError("platform.tables must map exactly the seven logical sources")
    for name, fields in PLATFORM_FIELDS.items():
        mapping = platform["tables"][name]
        if set(mapping.get("columns", {})) != set(fields):
            raise ValueError(f"platform.tables.{name}.columns does not match the logical schema")
        if len({value.casefold() for value in mapping["columns"].values()}) != len(fields):
            raise ValueError(f"platform.tables.{name}.columns has duplicate physical names")
    table_names = [table["name"].casefold() for table in data["tables"].values()]
    table_names.extend(table["name"].casefold() for table in platform["tables"].values())
    if len(table_names) != len(set(table_names)):
        raise ValueError("platform and core table mappings must use distinct physical names")

    root = Path(data["paths"]["data_root"]).resolve()
    db_path = _inside(Path(data["database"]["sqlite_file"]), root, "database.sqlite_file")
    meeting_path = _inside(Path(data["meetings"]["sqlite_file"]), root, "meetings.sqlite_file")
    image_root = _inside(Path(data["paths"]["image_root"]), root, "paths.image_root")
    manifest_path = _inside(root / "platform-manifest.json", root, "platform_manifest")
    if db_path == meeting_path or db_path == manifest_path or meeting_path == manifest_path:
        raise ValueError("generated output paths must be distinct")
    targets = (db_path, meeting_path, image_root, manifest_path)
    if any(path.exists() for path in targets):
        raise FileExistsError("platform demo output already exists; refusing to overwrite")

    root.mkdir(parents=True, exist_ok=True)
    image_root.mkdir(parents=True)
    sem_image_dir = image_root / "platform_demo"
    failbit_image_dir = image_root / "platform_failbit"
    counts: dict[str, int] = {}
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        meeting_path.parent.mkdir(parents=True, exist_ok=True)
        seed, n = platform["seed"], platform["incident_count"]
        lots, wafers, chips = platform["lots_per_incident"], platform["wafers_per_lot"], platform["chips_per_wafer"]
        core = data["tables"]
        source = platform["tables"]
        core_types = {
            "incident": {field: _type_for(field) for field in core["incident"]["columns"]},
            "lot_list": {}, "wafer_list": {}, "incident_document": {}, "document_chunk": {},
            "image_metadata": {}, "trend_metadata": {},
        }
        # Build all mapped tables in the target database, then stream rows in bounded batches.
        with closing(sqlite3.connect(db_path)) as con, con:
            con.execute("PRAGMA journal_mode=DELETE")
            for entity in ("incident", "lot_list", "wafer_list", "incident_document", "document_chunk", "image_metadata", "trend_metadata"):
                _create_mapped_table_for_core(con, core[entity], core_types[entity])
            for name, fields in PLATFORM_FIELDS.items():
                types = {field: {"string": "TEXT", "integer": "INTEGER", "number": "REAL", "boolean": "INTEGER"}[PLATFORM_TYPES[field]]
                         for field in fields}
                _create_mapped_table(con, source[name], types, primary_key="record_id")
            counts["incident"] = _write_rows(con, core["incident"],
                (_incident_row(_case(i, seed), lots, wafers) for i in range(1, n + 1)),
                batch_size=250)
            counts["lot_list"] = _write_rows(con, core["lot_list"], _lot_rows(settings, n, lots))
            counts["wafer_list"] = _write_rows(con, core["wafer_list"], _wafer_rows(settings, n, lots, wafers))
            counts["mes"] = _write_rows(con, source["mes"], _mes_rows(settings, n, lots))
            counts["test"] = _write_rows(con, source["test"], _test_rows(settings, n, lots, wafers, chips))
            counts["measure"] = _write_rows(con, source["measure"], _measure_rows(settings, n, lots, wafers, chips))
            failbit_records = list(_failbit_rows(settings, n, lots, wafers, chips))
            counts["failbit"] = _write_rows(con, source["failbit"], iter(failbit_records))
            failbit_assets = _failbit_asset_rows(failbit_records, failbit_image_dir)
            sem_records = list(_sem_rows(settings, n, sem_image_dir, chips))
            counts["sem"] = _write_rows(con, source["sem"], iter(sem_records))
            counts["trend"] = _write_rows(con, source["trend"], _trend_rows(settings, n))
            notes_for_core = list(_notes(settings, n))
            counts["inform"] = _write_rows(con, source["inform"], iter(notes_for_core))
            counts["incident_document"] = _write_rows(con, core["incident_document"], _document_rows(iter(notes_for_core)))
            counts["document_chunk"] = _write_rows(con, core["document_chunk"], _chunk_rows(iter(notes_for_core)))
            counts["image_metadata"] = _write_rows(
                con, core["image_metadata"], _image_metadata_rows(iter(sem_records), iter(failbit_assets)))
            counts["trend_metadata"] = _write_rows(con, core["trend_metadata"], _trend_metadata_rows(settings, n))
            _create_index(con, source["mes"], ("incident_id", "occurred_at", "lot_id"), "incident_time_lot")
            _create_index(con, source["test"], ("incident_id", "occurred_at", "lot_id"), "incident_time_lot")
            _create_index(con, source["measure"], ("incident_id", "occurred_at", "lot_id"), "incident_time_lot")
            _create_index(con, source["failbit"], ("incident_id", "occurred_at", "lot_id"), "incident_time_lot")
            _create_index(con, source["sem"], ("incident_id", "occurred_at", "lot_id"), "incident_time_lot")
            _create_index(con, source["trend"], ("incident_id", "timestamp", "lot_id"), "incident_time_lot")
            _create_index(con, source["inform"], ("incident_id", "occurred_at"), "incident_time")
            _create_index(con, core["lot_list"], ("incident_ref", "lot_id"), "incident_lot")
            _create_index(con, core["wafer_list"], ("incident_ref", "lot_id", "wafer_id"), "incident_lot_wafer")
            _create_index(con, core["incident_document"], ("incident_ref",), "incident")
            _create_index(con, core["document_chunk"], ("document_ref",), "document")
            _create_index(con, core["image_metadata"], ("incident_ref", "lot_id"), "incident_lot")
            _create_index(con, core["trend_metadata"], ("incident_ref",), "incident")
        counts["meetings"] = _make_meeting_db(meeting_path, data["meetings"], iter(notes_for_core))
        image_files = sorted(sem_image_dir.glob("*.png"))
        counts["sem_images"] = len(image_files)
        counts["failbit_images"] = len(failbit_assets)
        counts["total_images"] = counts["sem_images"] + counts["failbit_images"]
        counts["chips"] = n * lots * wafers * chips
        image_digest = hashlib.sha256("".join(_hash_file(path) for path in image_files).encode()).hexdigest()
        assets = sorted([{"asset_id": row["asset_id"], "storage_ref": row["storage_ref"],
                          "sha256": row["sha256"], "stage": "SEM",
                          **{key: row[key] for key in ('incident_id', 'lot_id', 'wafer_id', 'chip_id')}} for row in sem_records]
                        + [{"asset_id": row["asset_id"], "storage_ref": row["storage_ref"],
                            "sha256": row["sha256"], "stage": row["stage"],
                            **{key: row[key] for key in ('incident_id', 'lot_id', 'wafer_id', 'chip_id')}} for row in failbit_assets],
                        key=lambda row: row["asset_id"])
        all_image_digest = hashlib.sha256("".join(row["sha256"] for row in assets).encode()).hexdigest()
        manifest = {"schema_version": "1", "synthetic": True, "as_of": AS_OF, "seed": seed,
                    "wm_811k_excluded": True, "counts": counts, "assets": assets,
                    "sha256": {"database": _hash_file(db_path), "meetings": _hash_file(meeting_path),
                               "sem_images_ordered_sha256": image_digest,
                               "all_images_ordered_sha256": all_image_digest},
                    "source": {"kind": "procedurally_generated", "generator": "app/platform_demo.py",
                               "recipe_basis": ["repository code recipes; no source images/models copied"],
                               "enterprise_validation": "not_performed"}}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        for path in (db_path, meeting_path, manifest_path):
            path.unlink(missing_ok=True)
        shutil.rmtree(image_root, ignore_errors=True)
        raise
    return {"synthetic": True,
            "paths": {"database": str(db_path), "meetings": str(meeting_path),
                      "images": str(image_root), "manifest": str(manifest_path)},
            "counts": counts}


def _create_mapped_table_for_core(con: sqlite3.Connection, mapping: dict[str, Any], types: dict[str, str]) -> None:
    # Core table physical names and columns come exclusively from the deployment mapping.
    logical_types = {field: ("INTEGER" if field in ("expected_lot_count", "affected_wafer_count") else
                             "REAL" if field in ("expected_wafer_count",) else "TEXT") for field in mapping["columns"]}
    logical_types.update(types)
    _create_mapped_table(con, mapping, logical_types)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    args = parser.parse_args(argv)
    settings = load_config(args.config, args.overlay)
    result = generate(settings)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
