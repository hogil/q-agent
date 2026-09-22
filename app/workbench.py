"""Loopback-only HTTP workbench for the local synthetic Q-Agent demo."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import mimetypes
import re
import sqlite3
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from config_loader import (ConfigError, Settings, SPEC, check_shape, load_config,
                           merge, read_config, resolve_paths, validate_values)  # noqa: E402
from agent import run as run_agent  # noqa: E402
from demo_data import generate  # noqa: E402
from incident_tools import ToolError  # noqa: E402
from meeting_tools import MeetingTools  # noqa: E402
from runtime_factory import open_incident_tools  # noqa: E402
from detection_workflow import DetectionWorkflow  # noqa: E402
from workbench_data import load_workbench_data  # noqa: E402
from engineering_tools import EngineeringTools  # noqa: E402
from enterprise_tools import EnterpriseTools  # noqa: E402


MAX_BODY = 64 * 1024
INCIDENT_RE = re.compile(r"(?<![A-Za-z0-9])SYN-2026-\d{2}(?![A-Za-z0-9])")
SAFE_HOSTS = {"127.0.0.1", "localhost", "::1"}
INCIDENT_FIELDS = [
    "incident_detail", "analysis_detail", "confirmed_cause", "containment",
    "corrective_action", "verification", "prevention", "remaining",
    "department", "product_generations", "fab_out_failure_codes",
]
ANALYSIS_SOURCES = (
    "incident", "trend", "correlation", "maps", "sem", "production",
    "inform", "meetings", "changes", "enterprise", "related",
)
ANALYSIS_CONTEXT_FIELDS = {"incident_number", "item", "step", "equipment", "from", "to", "wafers"}
ANALYSIS_OPTIONAL_FIELDS = {"recipe", "trend_selection", "sem_wafers", "map_view", "map_comparison"}
ANALYSIS_TEXT_FIELDS = ("item", "step", "equipment")
ANALYSIS_TEXT_LIMIT = 256
ANALYSIS_TIME_LIMIT = 64
ANALYSIS_MAX_WAFERS = 100


class WorkbenchError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _analysis_time(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > ANALYSIS_TIME_LIMIT:
        raise WorkbenchError(f"context {field} must be an ISO date or timezone-aware datetime")
    if len(value) == 10:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError:
            parsed_date = None
        if parsed_date is not None:
            return datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc)
    candidate = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise WorkbenchError(f"context {field} must be an ISO date or timezone-aware datetime") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkbenchError(f"context {field} datetime must include a timezone")
    return parsed.astimezone(timezone.utc)


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _loopback(value: str | None) -> bool:
    if not value or any(ch in value for ch in "\r\n"):
        return False
    try:
        parsed = urlsplit("//" + value)
        parsed.port
        return (not parsed.path and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment and parsed.hostname in SAFE_HOSTS)
    except ValueError:
        return False


def _origin_ok(value: str | None) -> bool:
    if value is None:
        return True
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ("http", "https") and _loopback(parsed.netloc)
    except ValueError:
        return False


def _path(value: str, base: Path) -> Path:
    target = Path(value).expanduser()
    return (target if target.is_absolute() else base / target).resolve()


def _validate_wafer_geometry(raw):
    fields = {
        "radius_mm", "coordinate_radius", "chip_pitch_x_mm", "chip_pitch_y_mm",
        "chip_origin_x_mm", "chip_origin_y_mm",
    }
    if not isinstance(raw, dict) or set(raw) != fields:
        raise WorkbenchError("wafer_geometry must contain exactly six fields")
    positive = {"radius_mm", "coordinate_radius", "chip_pitch_x_mm", "chip_pitch_y_mm"}
    for field, value in raw.items():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise WorkbenchError(f"wafer_geometry.{field} must be a finite number")
        if field in positive and value <= 0:
            raise WorkbenchError(f"wafer_geometry.{field} must be greater than zero")
    return raw


def load_workbench(path: str | Path, *, raw_file=None, agent_overlay=None) -> dict:
    config_path = Path(path).expanduser().resolve()
    raw = read_config(config_path)
    if set(raw) - {"agent_overlay", "sources", "server", "wafer_geometry", "demo_image_tools", "demo_image_model_dir"} != {"config_version", "demo", "chat", "cutoff", "static_root"}:
        raise WorkbenchError("workbench config keys are invalid")
    if raw["config_version"] != 1:
        raise WorkbenchError("unsupported workbench config version")
    demo_image_tools = raw.get("demo_image_tools", False)
    if type(demo_image_tools) is not bool:
        raise WorkbenchError("demo_image_tools must be a boolean")
    if demo_image_tools and (not isinstance(raw.get("demo_image_model_dir"), str)
                             or not raw["demo_image_model_dir"].strip()):
        raise WorkbenchError("demo_image_model_dir is required for synthetic image models")
    demo_image_model_dir = (_path(raw.get("demo_image_model_dir"), config_path.parent)
                            if demo_image_tools else None)
    wafer_geometry = (_validate_wafer_geometry(raw["wafer_geometry"])
                      if "wafer_geometry" in raw else None)
    server = raw.get("server", {"port": 8787})
    if (not isinstance(server, dict) or set(server) != {"port"}
            or type(server["port"]) is not int or not 1 <= server["port"] <= 65535):
        raise WorkbenchError("server.port must be between 1 and 65535")
    sources = {"raw_file": str(Path(raw_file).expanduser().resolve())} if raw_file is not None else raw.get("sources")
    try:
        raw_data = load_workbench_data(sources, config_path.parent)
    except ValueError as exc:
        raise WorkbenchError(str(exc)) from None
    if demo_image_tools and raw_data is None:
        raise WorkbenchError("demo_image_tools requires configured synthetic raw data")
    demo = raw["demo"]
    chat = raw["chat"]
    if not isinstance(demo, dict) or set(demo) != {"base_config", "overlay"}:
        raise WorkbenchError("demo base_config and overlay are required")
    if not isinstance(chat, dict) or set(chat) != {"sqlite_file", "history_limit"}:
        raise WorkbenchError("chat sqlite_file and history_limit are required")
    try:
        cutoff = (raw["cutoff"] if isinstance(raw["cutoff"], date)
                  else datetime.strptime(raw["cutoff"], "%Y-%m-%d").date()).isoformat()
    except (TypeError, ValueError):
        raise WorkbenchError("cutoff must be YYYY-MM-DD") from None
    base = _path(demo["base_config"], config_path.parent)
    overlay = _path(demo["overlay"], config_path.parent)
    if base.name != "config.yaml" or overlay.name != "demo.yaml":
        raise WorkbenchError("synthetic workbench requires config.yaml plus demo.yaml")
    try:
        settings = load_config(base, overlay)
        overlay_path = str(Path(agent_overlay).expanduser().resolve()) if agent_overlay is not None else raw.get("agent_overlay")
        if overlay_path:
            agent_path = _path(overlay_path, config_path.parent)
            agent_config = read_config(agent_path)
            if set(agent_config) - {"models", "roles", "runtime", "image_tools", "enterprise"}:
                raise WorkbenchError("agent_overlay may only configure models, roles, runtime, image_tools and enterprise")
            merged = merge(settings.data, agent_config)
            check_shape(merged, SPEC)
            validate_values(merged)
            resolve_paths(merged, base.parent)
            settings = Settings(merged, [*settings.source_files, str(agent_path)])
    except ConfigError as exc:
        raise WorkbenchError(str(exc)) from None
    if settings.data.get("environment") != "demo":
        raise WorkbenchError("workbench accepts only environment: demo")
    if type(chat["history_limit"]) is not int or not 1 <= chat["history_limit"] <= 200:
        raise WorkbenchError("chat.history_limit must be between 1 and 200")
    static_root = _path(raw["static_root"], config_path.parent)
    chat_db = _path(chat["sqlite_file"], config_path.parent)
    data = settings.data
    outputs = [Path(data["database"]["sqlite_file"]), Path(data["meetings"]["sqlite_file"]), Path(data["paths"]["golden_file"])]
    for source in data["enterprise"]["sources"]:
        if source["dialect"] == "sqlite":
            source_path = Path(source["sqlite_file"]).resolve()
            if source_path == chat_db.resolve() or source_path.is_relative_to(static_root.resolve()):
                raise WorkbenchError("enterprise SQLite must differ from chat DB and stay outside static_root")
    if chat_db in {output.resolve() for output in outputs}:
        raise WorkbenchError("chat sqlite must differ from synthetic data outputs")
    try:
        chat_db.relative_to(static_root)
    except ValueError:
        pass
    else:
        raise WorkbenchError("chat sqlite must be outside static_root")
    existing = [target.exists() for target in outputs]
    if any(existing) and not all(existing):
        raise WorkbenchError("partial synthetic data exists; refusing to overwrite it")
    if not any(existing):
        try:
            generate(settings, profile="basic")
        except (OSError, ValueError, FileExistsError) as exc:
            raise WorkbenchError(f"synthetic data generation failed: {type(exc).__name__}") from None
    registry = json.loads(Path(data["paths"]["registry_file"]).read_text(encoding="utf-8"))
    return {"settings": settings, "cutoff": cutoff, "static_root": static_root,
            "chat_db": chat_db, "history_limit": chat["history_limit"],
            "raw_data": raw_data, "port": server["port"],
            "release": registry.get("release", "unknown"), "wafer_geometry": wafer_geometry,
            "demo_image_tools": demo_image_tools, "demo_image_model_dir": demo_image_model_dir}


def _summary(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {key: row.get(key) for key in ("id", "title", "incident_number", "updated_at")}


class Workbench:
    def __init__(self, config: dict):
        self.settings = config["settings"]
        self.cutoff = config["cutoff"]
        self.static_root = config["static_root"]
        self.chat_db = config["chat_db"]
        self.history_limit = config["history_limit"]
        self.release = config["release"]
        self.wafer_geometry = config.get("wafer_geometry")
        self.raw_data = config.get("raw_data")
        self.actor = "local-workbench"
        self.lock = threading.RLock()
        self.running_rooms = set()
        self.analysis_runs = {}
        self.llm_connected = False
        self.image_connections = set()
        self.demo_images = None
        if config.get("demo_image_tools"):
            from demo_images import DemoImageService
            self.demo_images = DemoImageService(self.raw_data, self.static_root, self._incident_map(),
                                               config["demo_image_model_dir"])
        self.chat_db.parent.mkdir(parents=True, exist_ok=True)
        self._init_chat_db()
        self.monitor = DetectionWorkflow(self.chat_db, self._analyze_detection)
        if not self._rooms():
            incidents = self._incidents()
            if incidents:
                incident = next((row for row in incidents if row["incident_number"] == "SYN-2026-01"), incidents[0])
                room_id = self._create_room("외곽 패턴 원인 분석", incident["incident_number"])
                answer, attachments = self._answer(incident["incident_number"], "개요")
                self._append_messages(room_id, "SYN-2026-01의 원인과 관련 근거를 확인해줘.", [], answer, attachments)

    def _connect(self):
        db = sqlite3.connect(self.chat_db, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _db(self):
        db = self._connect()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()
        finally:
            db.close()

    def _init_chat_db(self):
        with self.lock, self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS rooms (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, incident_number TEXT,
                    updated_at TEXT NOT NULL
                );
            CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
                    created_at TEXT NOT NULL, attachments TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_room_created ON messages(room_id, created_at, id);
            CREATE TABLE IF NOT EXISTS analysis_scopes (
                    room_id TEXT PRIMARY KEY REFERENCES rooms(id) ON DELETE CASCADE,
                    incident_number TEXT NOT NULL,
                    sources TEXT NOT NULL,
                    context TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(analysis_scopes)")}
            if "steps" not in columns:
                db.execute("ALTER TABLE analysis_scopes ADD COLUMN steps TEXT NOT NULL DEFAULT '[]'")
            if "runtime" not in columns:
                db.execute("ALTER TABLE analysis_scopes ADD COLUMN runtime TEXT NOT NULL DEFAULT '{}'")

    def _rooms(self):
        with self.lock, self._db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM rooms ORDER BY updated_at DESC, id DESC")]

    def _room(self, room_id):
        with self.lock, self._db() as db:
            row = db.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
            if not row:
                raise WorkbenchError("room not found")
            return dict(row)

    def _incident_map(self):
        return {row["incident_number"]: row for row in self._incidents()}

    def _incidents(self):
        fields = INCIDENT_FIELDS
        with open_incident_tools(self.settings) as tool:
            result = tool.find_incidents(
                self.actor,
                filters={"occurred_at": {"gte": "0001-01-01T00:00:00+00:00", "lt": "9999-12-31T23:59:59+00:00"}},
                fields=fields,
            )
        rows = result["data"]
        rows.sort(key=lambda row: row.get("occurred_at") or "", reverse=True)
        return rows

    @staticmethod
    def _pages(method, *args):
        result = method(*args, page_size=100, offset=0)
        items = list(result.get("items", []))
        while result.get("next_offset") is not None:
            result = method(*args, page_size=100, offset=result["next_offset"])
            items.extend(result.get("items", []))
        return items

    def _workspace(self, incident_number, include_meetings=True):
        incident = self._incident_map().get(incident_number)
        if incident is None:
            raise WorkbenchError("incident not found")
        try:
            with open_incident_tools(self.settings) as tool:
                found = tool.find_incidents(self.actor, incident_number=incident_number, fields=INCIDENT_FIELDS)
                scope = found["scope_id"]
                lots = self._pages(tool.list_incident_lots, self.actor, scope)
                wafers = self._pages(tool.list_incident_wafers, self.actor, scope)
            meetings = []
            if include_meetings:
                meetings = MeetingTools(self.settings).search(
                    self.actor, incident_number, [incident["incident_id"]], self.cutoff,
                    top_k=self.settings.data["meetings"]["max_top_k"]
                )["items"]
        except (ToolError, KeyError, OSError) as exc:
            raise WorkbenchError(str(exc)) from None
        result = {"incident": incident, "lots": lots, "wafers": wafers, "meetings": meetings,
                  "synthetic": True, "as_of": self.cutoff}
        if self.wafer_geometry is not None:
            result["wafer_geometry"] = self.wafer_geometry
        if self.raw_data is not None:
            record = self.raw_data.get(incident_number)
            if record is None:
                raise WorkbenchError("configured raw data has no selected incident")
            registered = {(row["lot_id"], row["wafer_id"]) for row in wafers}
            supplied = {(row["lotId"], row["waferId"]) for row in record["engineering"]["fab"]}
            if not supplied <= registered:
                raise WorkbenchError("raw data includes wafers outside the selected incident")
            result["raw"] = record
        return result

    def bootstrap(self):
        return {"synthetic": True, **self.llm_status(),
                "incidents": self._incidents(), "rooms": [_summary(row) for row in self._rooms()],
                "release": self.release, "default_room_id": self._default_room_id()}

    def _default_room_id(self):
        # Bind the report to its saved analysis message, never a later chat reply.
        with self.lock, self._db() as db:
            rows = db.execute("""SELECT a.runtime, a.context, a.updated_at, r.id, r.title,
                r.incident_number FROM analysis_scopes a JOIN rooms r ON r.id=a.room_id
                WHERE a.incident_number=r.incident_number ORDER BY a.updated_at DESC, r.id DESC""").fetchall()
            for row in rows:
                runtime = json.loads(row["runtime"])
                report = runtime.get("report")
                if (runtime.get("mode") != "llm" or not runtime.get("llm_connected")
                        or runtime.get("status") not in ("answered", "partial") or not report):
                    continue
                message = db.execute("SELECT content FROM messages WHERE id=? AND room_id=? AND role='assistant'",
                                     (runtime.get("answer_message_id"), row["id"])).fetchone()
                if not message or not message["content"].strip():
                    continue
                return row["id"]
        return None

    def llm_status(self):
        profiles = {role: self.settings.model_profile(role)["deployment"]
                    for role in ("router", "judge", "answer")}
        configured = any(profile["enabled"] for profile in profiles.values())
        return {"mode": "llm" if configured else "demo", "llm_configured": configured,
                "llm_connected": self.llm_connected,
                "models": {role: profile["served_model"] for role, profile in profiles.items()
                           if profile["enabled"]}}

    def monitoring(self):
        value = self.monitor.snapshot()
        value["image_tools"] = {name: {"configured": cfg["enabled"], "model": cfg["served_model"],
                                        "connection_verified": name in self.image_connections,
                                        "synthetic_model": bool(self.demo_images) and cfg["served_model"] == self.demo_images.model_ids[name]}
                                for name, cfg in self.settings.data["image_tools"].items()}
        return value

    def demo_image_request(self, action, body):
        if self.demo_images is None:
            raise WorkbenchError("synthetic image service is disabled")
        try:
            result = getattr(self.demo_images, action)(body)
        except ValueError as exc:
            raise WorkbenchError(str(exc)) from None
        if action == "compare":
            with self.lock:
                self.image_connections.add(body["modality"])
        return result

    def replay_detection(self, body):
        if not isinstance(body, dict) or set(body) != {"context", "comparison"}:
            raise WorkbenchError("context and comparison are required")
        supplied = body["context"]
        if not isinstance(supplied, dict):
            raise WorkbenchError("invalid detection context")
        context = self._validate_analysis_context(supplied, supplied.get("incident_number"))
        context["wafers"].sort(key=lambda row: (row["lot_id"], row["wafer_id"]))
        comparison = body["comparison"]
        if not isinstance(comparison, dict) or set(comparison) != {"item", "a", "b"} or comparison["item"] != context["item"]:
            raise WorkbenchError("comparison must use the selected item")
        pair = [comparison["a"], comparison["b"]]
        if any(not isinstance(row, dict) or set(row) != {"lot_id", "wafer_id"} for row in pair) or pair[0] == pair[1]:
            raise WorkbenchError("two distinct registered comparison wafers required")
        self._validate_analysis_context({**context, "wafers": pair}, context["incident_number"])
        payload = {"source": "synthetic_replay", "model_id": "synthetic-event-fixture", "model_version": "1",
                   "item": context["item"], "score": 0.96, "threshold": 0.9, "context": context, "comparison": comparison}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        try:
            return self.monitor.submit({"event_id": "demo-" + digest, **payload})
        except ValueError as exc:
            raise WorkbenchError(str(exc)) from None

    def _analyze_detection(self, event):
        context = event["context"]
        room_id = "detection-" + hashlib.sha256(event["event_id"].encode()).hexdigest()[:32]
        with self.lock, self._db() as db:
            db.execute("INSERT OR IGNORE INTO rooms VALUES (?,?,?,?)", (room_id,
                       "합성 감지 · " + context["item"], context["incident_number"], _now()))
        scope = self._analysis_scope(room_id)
        if self._room(room_id)["incident_number"] != context["incident_number"] or (scope is not None and scope["context"] != context):
            raise WorkbenchError("detection analysis room scope changed")
        if scope is None:
            self.analysis(room_id, {"content": "합성 감지 이벤트의 사고 DB와 회의록 근거를 확인해줘. 실제 감지 모델 판정이나 생산 조치는 요청하지 않습니다.",
                                   "sources": ["incident", "meetings", "sem", "maps", "trend"], "context": context})
        metadata = self.analysis_metadata(room_id)["analysis"]
        return {"room_id": room_id, "analysis_mode": metadata["mode"], "model_inference": metadata["llm_connected"],
                "comparison": event["comparison"], "comparison_status": "image_models_not_invoked",
                "action": "엔지니어 검토 요청", "production_executed": False}

    def workspace(self, incident_number):
        return self._workspace(incident_number)

    def _create_room(self, title, incident_number):
        room_id = "room-" + uuid.uuid4().hex
        with self.lock, self._db() as db:
            db.execute("INSERT INTO rooms VALUES (?,?,?,?)", (room_id, title, incident_number, _now()))
        return room_id

    def create_room(self, title=None, incident_number=None):
        title = self._title(title or "새 분석")
        if incident_number is not None:
            self._require_incident(incident_number)
        else:
            incidents = self._incidents()
            if not incidents:
                raise WorkbenchError("no incident available")
            incident_number = incidents[0]["incident_number"]
        return _summary(self._room(self._create_room(title, incident_number)))

    def update_room(self, room_id, values):
        with self.lock:
            return self._update_room_locked(room_id, values)

    def _update_room_locked(self, room_id, values):
        self._require_idle(room_id)
        if not isinstance(values, dict) or set(values) - {"title", "incident_number"}:
            raise WorkbenchError("invalid room fields")
        room = self._room(room_id)
        title = self._title(values["title"]) if "title" in values else room["title"]
        incident = values["incident_number"] if "incident_number" in values else room["incident_number"]
        if "incident_number" in values:
            self._require_incident(incident)
        with self.lock, self._db() as db:
            db.execute("UPDATE rooms SET title=?,incident_number=?,updated_at=? WHERE id=?", (title, incident, _now(), room_id))
        return _summary(self._room(room_id))

    def delete_room(self, room_id):
        with self.lock, self._db() as db:
            self._require_idle(room_id)
            if not db.execute("DELETE FROM rooms WHERE id=?", (room_id,)).rowcount:
                raise WorkbenchError("room not found")
            self.analysis_runs.pop(room_id, None)
        return {"ok": True}

    def room(self, room_id, before=None):
        with self.lock:
            room = self._room(room_id)
            with self._db() as db:
                if before is None:
                    rows = db.execute(
                        "SELECT * FROM messages WHERE room_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                        (room_id, self.history_limit + 1),
                    ).fetchall()
                else:
                    cursor = db.execute(
                        "SELECT created_at,rowid AS sequence FROM messages WHERE room_id=? AND id=?",
                        (room_id, before),
                    ).fetchone()
                    if not cursor:
                        raise WorkbenchError("message cursor not found")
                    rows = db.execute(
                        "SELECT * FROM messages WHERE room_id=? AND (created_at<? OR (created_at=? AND rowid<?)) "
                        "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                        (room_id, cursor["created_at"], cursor["created_at"], cursor["sequence"], self.history_limit + 1),
                    ).fetchall()
            has_more = len(rows) > self.history_limit
            rows = list(rows[:self.history_limit])
            rows.reverse()
            messages = [self._message(row) for row in rows]
            return {"id": room["id"], "title": room["title"], "incident_number": room["incident_number"],
                    "updated_at": room["updated_at"], "messages": messages,
                    "has_more": has_more, "oldest_id": messages[0]["id"] if messages else None}

    def message(self, room_id, body):
        if self.llm_status()["llm_configured"]:
            return self._live_message(room_id, body)
        with self.lock:
            self._require_idle(room_id)
            return self._message_locked(room_id, body)

    def _require_idle(self, room_id):
        if room_id in self.running_rooms:
            raise WorkbenchError("analysis is already running in this room")

    def analysis_progress(self, room_id):
        with self.lock:
            self._room(room_id)
            return {"run": copy.deepcopy(self.analysis_runs.get(room_id))}

    def _begin_analysis_run(self, room_id, sources, context):
        self.analysis_runs[room_id] = {"id": uuid.uuid4().hex, "status": "running",
            "context": copy.deepcopy(context), "sources": list(sources), "events": [],
            "started_at": _now()}
        self._analysis_event(room_id, {"event": "scope_validated"})

    def _analysis_event(self, room_id, event):
        allowed = ("event", "role", "model", "step", "source", "error", "status", "metrics")
        item = {key: event[key] for key in allowed if key in event}
        item["time"] = _now()
        if event.get("event") == "tool_result":
            item["status"] = event.get("result", {}).get("status", "completed")
        if event.get("event") == "llm_output":
            output = event.get("output", {})
            item["status"] = output.get("decision", output.get("verdict", output.get("status", "completed")))
            if event.get("role") == "router":
                item["plan"] = copy.deepcopy(output.get("plan", []))
                item["needs_skills"] = output.get("needs_skills", [])
                item["clarification"] = output.get("clarification")
            elif event.get("role") == "judge":
                item["coverage"] = copy.deepcopy(output.get("coverage", []))
                item["issues"] = copy.deepcopy(output.get("issues", []))
        with self.lock:
            run = self.analysis_runs.get(room_id)
            if run and run["status"] == "running":
                run["events"] = [*run["events"], item][-200:]

    def _finish_analysis_run(self, room_id, error=None):
        with self.lock:
            run = self.analysis_runs[room_id]
            run.update(status="failed" if error else "completed", finished_at=_now())
            if error:
                run["error"] = str(error) if isinstance(error, WorkbenchError) else type(error).__name__

    def _live_message(self, room_id, body):
        if not isinstance(body, dict) or set(body) - {"content", "attachments"}:
            raise WorkbenchError("invalid message fields")
        content = body.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > 12000:
            raise WorkbenchError("content must be a nonempty string up to 12000 characters")
        with self.lock:
            self._require_idle(room_id)
            room = self._room(room_id)
            numbers = set(INCIDENT_RE.findall(content))
            if len(numbers) > 1:
                raise WorkbenchError("select one incident for this conversation")
            target = next(iter(numbers), room["incident_number"])
            self._require_incident(target)
            attachments = self._attachments(body.get("attachments", []), target)
            attachments.insert(0, self._ref("data", "conversation scope", target, target))
            scope = self._analysis_scope(room_id)
            if scope and scope["incident_number"] == target:
                sources, context = scope["sources"], scope["context"]
            else:
                sources = ["incident", "meetings"]
                context = {"incident_number": target, "item": "", "step": "", "equipment": "",
                           "from": self.cutoff, "to": self.cutoff, "wafers": []}
            self.running_rooms.add(room_id)
            self._begin_analysis_run(room_id, sources, context)
        try:
            answer, refs, _ = self._llm_answer(room_id, content, sources, context)
            result = self._append_messages(room_id, content, attachments, answer, refs,
                                           room={**room, "incident_number": target})
            self._finish_analysis_run(room_id)
            return result
        except Exception as exc:
            self._finish_analysis_run(room_id, exc)
            raise
        finally:
            with self.lock:
                self.running_rooms.discard(room_id)

    def _message_locked(self, room_id, body):
        room = self._room(room_id)
        if not isinstance(body, dict) or set(body) - {"content", "attachments"}:
            raise WorkbenchError("invalid message fields")
        content = body.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > 12000:
            raise WorkbenchError("content must be a nonempty string up to 12000 characters")
        numbers = INCIDENT_RE.findall(content)
        invalid = [number for number in numbers if number not in self._incident_map()]
        if numbers and (invalid or len(set(numbers)) != 1):
            answer = "요청에 포함된 합성 사고 번호를 찾을 수 없습니다. 기존 방의 사고 데이터는 재사용하지 않았습니다. (출처: demo)"
            target = None
        elif numbers:
            target = numbers[0]
            room = {**room, "incident_number": target}
        else:
            target = room["incident_number"]
        attachments = self._attachments(body.get("attachments", []), room["incident_number"])
        demo_terms = ("사고", "원인", "분석", "조회", "근거", "회의", "inform", "lot", "wafer", "trend", "트렌드", "map", "맵", "지도", "요약", "결과", "조치", "개요", "확인", "production", "생산", "sem", "image", "이미지", "overlay", "오버레이")
        if not (numbers and (invalid or len(set(numbers)) != 1)) and target and any(term in content.casefold() for term in demo_terms):
            answer, answer_attachments = self._answer(target, content)
        elif numbers and (invalid or len(set(numbers)) != 1):
            answer = "요청에 포함된 합성 사고 번호를 찾을 수 없습니다. 기존 방의 사고 데이터는 재사용하지 않았습니다. (출처: demo)"
            answer_attachments = []
        else:
            answer = "LLM이 연결되지 않은 로컬 demo입니다. 사고 번호나 조회 대상을 포함한 질문을 입력해 주세요. (출처: demo)"
            answer_attachments = []
        return self._append_messages(room_id, content, attachments, answer, answer_attachments, room=room)

    def analysis(self, room_id, body):
        with self.lock:
            self._require_idle(room_id)
            room = self._room(room_id)
            scope = self._analysis_scope(room_id)
            content, sources, context = self._analysis_request(room, scope, body)
            self.running_rooms.add(room_id)
            self._begin_analysis_run(room_id, sources, context)
        try:
            if self.llm_status()["llm_configured"]:
                answer, answer_attachments, runtime = self._llm_answer(
                    room_id, content, sources, context, include_previous_answers="context" not in body,
                    inspection_requested=True)
            else:
                data = self._workspace(room["incident_number"], include_meetings="meetings" in sources)
                answer, answer_attachments, steps = self._analysis_answer(data, sources, context)
                runtime = {"mode": "demo", "llm_connected": False, "steps": steps}
                for step in steps:
                    self._analysis_event(room_id, {"event": "source_result", **step})
            analysis = {**runtime, "sources": sources, "context": context}
            result = self._append_analysis(room_id, content, sources, context, answer,
                                           answer_attachments, analysis)
            self._finish_analysis_run(room_id)
            return result
        except Exception as exc:
            self._finish_analysis_run(room_id, exc)
            raise
        finally:
            with self.lock:
                self.running_rooms.discard(room_id)

    def _llm_answer(self, room_id, content, sources, context, include_previous_answers=True, inspection_requested=False):
        # UI context and earlier messages are unverified input, never tool evidence.
        incident = self._incident_map()[context["incident_number"]]
        history = [{"role": message["role"], "content": message["content"][:600]}
                   for message in self.room(room_id)["messages"][-8:]
                   if (include_previous_answers or message["role"] != "assistant")
                   and any(ref.get("incident_number") == context["incident_number"]
                          for ref in message["attachments"])]
        image_config = {name: {"enabled": self.settings.data["image_tools"][name]["enabled"] and source in sources
                              and (name != "overlay" or context.get("map_view", {}).get("kind", "overlay") == "overlay")}
                        for name, source in (("sem", "sem"), ("overlay", "maps"))
                        }
        available = {"incident", "meetings", "related"}
        engineering_sources = set(sources) & {"trend", "correlation", "production", "inform", "changes", "maps"}
        engineering_context = {key: value for key, value in context.items() if key != "map_comparison"}
        engineering = (EngineeringTools(self.raw_data, self._incident_map(), engineering_context, sources)
                       if self.raw_data and engineering_sources else None)
        if engineering:
            available.update(engineering_sources)
        enterprise = (EnterpriseTools(self.settings, self._incident_map(), engineering_context)
                      if "enterprise" in sources and self.settings.data["enterprise"]["enabled"] else None)
        if enterprise:
            available.add("enterprise")

        def engineering_query(actor, incident_ids, as_of):
            result = (engineering.query(actor, incident_ids, as_of) if engineering else
                      {"status": "OK", "sections": {}, "observations": {}, "limitations": []})
            if enterprise:
                section = enterprise.query(actor, incident_ids, as_of)
                for system in section["systems"]:
                    self._analysis_event(room_id, {"event": "source_result", "source": "enterprise:" + system["id"],
                                                  "status": system["status"], **({"error": system["error"]}
                                                  if system.get("error") else {})})
                result["sections"]["enterprise"] = section
                result["limitations"].extend(section["limitations"])
                if section["status"] in ("UNAVAILABLE", "PARTIAL"):
                    result["status"] = "PARTIAL" if engineering else section["status"]
                result.pop("synthetic", None)
                result["provenance"] = {"raw_sections_synthetic": bool(engineering),
                                        "enterprise": "per_system_synthetic_flag"}
            return result
        available.update(source for name, source in (("sem", "sem"), ("overlay", "maps"))
                         if image_config[name]["enabled"])
        payload = {"incident_data_synthetic": True,
                   "selected_incident": context["incident_number"], "ui_context_unverified": context,
                   "requested_sources": sources, "previous_messages_unverified": history,
                   "unavailable_sources": [source for source in sources if source not in available],
                   "map_model_capabilities": {"cd": "not_connected", "bin": "not_connected",
                                              "failbit": "not_connected", "thk": "not_connected",
                                              "sem": "enabled" if image_config["sem"]["enabled"] else "not_connected",
                                              "overlay": "enabled" if image_config["overlay"]["enabled"] else "not_connected"}}
        config = merge(self.settings.data, {"meetings": {"enabled": "meetings" in sources
                       and self.settings.data["meetings"]["enabled"]},
                       "image_tools": image_config})
        question = f"선택 사고번호: {context['incident_number']}\n{content}"
        if len(question) > 12000:
            raise WorkbenchError("content plus selected incident context must not exceed 12000 characters")
        requested_tools = ["find_incidents"]
        if "related" in sources:
            requested_tools.append("search_related_incidents")
        if engineering or enterprise:
            requested_tools.append("get_engineering_snapshot")
        if config["meetings"]["enabled"]:
            requested_tools.append("search_meeting_minutes")
        requested_tools.extend(tool for name, tool in (("sem", "compare_sem_images"), ("overlay", "compare_overlay_maps"))
                               if image_config[name]["enabled"])
        result = run_agent(Settings(config, self.settings.source_files), question, actor=self.actor,
                           selected=[incident["incident_id"]], request_scope="incident", as_of=self.cutoff,
                           requested_tools=requested_tools, related_search="related" in sources,
                           inspection_requested=inspection_requested,
                           context_data=payload, engineering_query=engineering_query if engineering or enterprise else None,
                           emit=lambda event: self._analysis_event(room_id, event))
        events = result.get("events", [])
        self.llm_connected = any(event["event"] == "llm_output" for event in events)
        if result["status"] not in ("answered", "partial") or not result.get("answer"):
            errors = [event.get("error", "") for event in events if event["event"] in ("run_error", "validation_or_tool_error")]
            raise WorkbenchError("LLM analysis did not complete: " + result["status"] +
                                 (" / " + errors[-1] if errors else ""))
        tool_names = {event["source"] for event in events if event["event"] == "tool_result"}
        with self.lock:
            self.image_connections.update(name for name, tool in (
                ("sem", "compare_sem_images"), ("overlay", "compare_overlay_maps")) if tool in tool_names)
        retrieved = {"incident": "find_incidents" in tool_names,
                     "related": "search_related_incidents" in tool_names,
                     "meetings": "search_meeting_minutes" in tool_names,
                     "sem": "compare_sem_images" in tool_names,
                     "maps": "compare_overlay_maps" in tool_names}
        enterprise_result = None
        for event in events:
            if event.get("event") == "tool_result" and event.get("source") == "get_engineering_snapshot":
                retrieved.update({source: True for source in event["result"].get("sections", {})})
                enterprise_result = event["result"].get("sections", {}).get("enterprise")
        if enterprise_result:
            retrieved["enterprise"] = enterprise_result["status"] in ("OK", "PARTIAL")
        steps = [{"source": source, "status": "completed" if retrieved.get(source) else "unavailable",
                  "detail": "Agent tool queried synthetic data" if retrieved.get(source)
                  else "Not queried; UI fixtures are not model evidence"} for source in sources]
        for step in steps:
            if step["source"] == "enterprise":
                step["detail"] = ("; ".join(f"{s['system']} / {s['view']}: {s['status']} ({s['row_count']})"
                                            for s in enterprise_result["systems"]) if enterprise_result
                                  else "사내 SQL 미연결: 조회용 DB 설정 필요")
        trace = [{"role": event["role"], "model": event["model"], "step": event["step"]}
                 for event in events if event["event"] == "llm_start"]
        runtime = {"mode": "llm", "release": self.release, "llm_connected": self.llm_connected, "steps": steps,
                   "status": result["status"], "trace": trace, "tool_calls": result["tool_calls"],
                   "llm_calls": result["llm_calls"], "limitations": result.get("limitations", []),
                   "enterprise": enterprise_result,
                   "llm_metrics": [{"role": event["role"], **event["metrics"]} for event in events
                                   if event["event"] in ("llm_output", "llm_metrics") and event.get("metrics")]}
        runtime["report"] = self._analysis_report(result, context)
        answer = result["answer"]
        labels = {"historical_match": "과거 사고 매칭", "check": "점검 권고", "eds_followup": "EDS 후속 확인"}
        for row in result.get("inspection_plan", []):
            answer += (f"\n\n{labels[row['kind']]}\n대상: {row['target']}\n근거: {row['basis']}"
                       f"\n비교·확인: {row['comparison']}")
        if result.get("inspection_plan"):
            answer += "\n\n점검·EDS 확인은 미실행 권고이며, 조치 완료나 현재 불량 확정이 아닙니다."
        if result.get("limitations"):
            answer += "\n\n제한 사항:\n" + "\n".join(result["limitations"])
        answer += ("\n\n[합성 사고 데이터 + SQL 조회 · 출처별 synthetic 표시 확인 · LLM 생성 답변]"
                   if enterprise_result else "\n\n[합성 데이터 · LLM 생성 답변]")
        refs = [self._ref("data", context["incident_number"], incident["incident_id"], context["incident_number"])]
        return answer, refs, runtime

    def _analysis_report(self, result, context):
        report = {"version": 2, "summary": result["answer"], "inspection_plan": result.get("inspection_plan", []),
                  "images": [], "trend": [], "image_findings": [], "historical_cases": []}
        record = (self.raw_data or {}).get(context["incident_number"], {})
        assets = {asset["id"]: asset for asset in record.get("sem_assets", [])}
        history = {asset["id"]: asset for asset in record.get("image_history", [])}
        inform = {note["id"]: note for note in record.get("inform_notes", [])}
        images = {}
        for event in result.get("events", []):
            if event.get("event") != "tool_result":
                continue
            data = event.get("result", {})
            if event.get("source") == "get_engineering_snapshot":
                sections = data.get("sections", {})
                report["trend"] = list(sections.get("trend", {}).get("stats", {}).values())
                for ref in sections.get("maps", {}).get("records", []):
                    case = copy.deepcopy(ref)
                    note = inform.get(ref.get("inform_id"), {})
                    case["title"] = note.get("title", ref["incident_number"])
                    overlay = history.get(ref.get("overlay", {}).get("id"), {})
                    if (overlay.get("modality") == "overlay" and overlay.get("step") == context["step"]
                            and overlay.get("item") == context["item"]
                            and overlay.get("incident_number") == ref["incident_number"]):
                        case["overlay"]["vectors"] = copy.deepcopy(overlay.get("vectors", []))
                    report["historical_cases"].append(case)
                    sem = ref.get("sem", {})
                    if sem.get("src"):
                        images[sem["id"]] = {"id": sem["id"], "src": sem["src"], "kind": "historical",
                            "label": ref["incident_number"], "description": sem["description"],
                            "time": sem["occurred_at"], "provenance": "조회된 과거 합성 참조 · 이미지 유사도 확정 아님"}
            elif event.get("source") == "compare_sem_images":
                report["image_findings"].append({"status": data.get("status"),
                    "model": data.get("model"), "findings": data.get("findings", []),
                    "limitations": data.get("limitations", [])})
                for metadata in data.get("provenance", {}).get("validated_asset_metadata", []):
                    asset = assets.get(metadata.get("asset_id"))
                    if (asset and asset["lotId"] == metadata.get("lot_id")
                            and asset["waferId"] == metadata.get("wafer_id")
                            and metadata.get("item") == context["item"]
                            and metadata.get("step") == context["step"]):
                        images[asset["id"]] = {"id": asset["id"], "src": asset["src"], "kind": "comparison",
                            "label": f"{asset['lotId']} / {asset['waferId']}", "description": asset["description"],
                            "time": metadata.get("acquired_at"), "provenance": asset["provenance"]}
        report["images"] = sorted(images.values(), key=lambda image: image["kind"] == "historical")[:6]
        return report

    def analysis_metadata(self, room_id):
        with self.lock:
            room = self._room(room_id)
            scope = self._analysis_scope(room_id)
            if scope is None or scope["incident_number"] != room["incident_number"]:
                return {"analysis": None}
            return {"analysis": {"mode": "demo", "llm_connected": False, **scope["runtime"],
                                  "sources": scope["sources"], "context": scope["context"],
                                  "steps": scope["steps"]}}

    def _analysis_scope(self, room_id):
        with self.lock, self._db() as db:
            row = db.execute("SELECT * FROM analysis_scopes WHERE room_id=?", (room_id,)).fetchone()
            if not row:
                return None
            return {"room_id": row["room_id"], "incident_number": row["incident_number"],
                    "sources": json.loads(row["sources"]), "context": json.loads(row["context"]),
                    "steps": json.loads(row["steps"]),
                    "runtime": json.loads(row["runtime"]),
                    "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def _analysis_request(self, room, scope, body):
        if not isinstance(body, dict) or set(body) - {"content", "sources", "context"}:
            raise WorkbenchError("invalid analysis fields")
        content = body.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > 12000:
            raise WorkbenchError("content must be a nonempty string up to 12000 characters")
        mentioned_incidents = INCIDENT_RE.findall(content)
        if mentioned_incidents and (set(mentioned_incidents) != {room["incident_number"]}):
            raise WorkbenchError("analysis content incident must match the room scope")
        has_sources = "sources" in body
        has_context = "context" in body
        if not has_sources and not has_context:
            if scope is None:
                raise WorkbenchError("sources and context are required for the first analysis")
            if scope["incident_number"] != room["incident_number"]:
                raise WorkbenchError("stored analysis scope is stale; select a new scope")
            return content, scope["sources"], scope["context"]
        if scope is not None and not has_sources and scope["incident_number"] != room["incident_number"]:
            raise WorkbenchError("stored analysis scope is stale; select a new scope")
        raw_sources = body.get("sources", scope["sources"] if scope is not None else None)
        raw_context = body.get("context", scope["context"] if scope is not None else None)
        sources = self._validate_analysis_sources(raw_sources)
        context = self._validate_analysis_context(raw_context, room["incident_number"])
        return content, sources, context

    def _validate_analysis_sources(self, value):
        if not isinstance(value, list) or not value or len(value) > len(ANALYSIS_SOURCES):
            raise WorkbenchError("sources must be a nonempty array")
        if any(type(item) is not str or not item.strip() for item in value):
            raise WorkbenchError("sources must contain nonempty strings")
        if len(set(value)) != len(value) or any(item not in ANALYSIS_SOURCES for item in value):
            raise WorkbenchError("sources contains an unknown or duplicate source")
        return ["incident", *[item for item in value if item != "incident"]]

    def _validate_analysis_context(self, value, incident_number):
        if (not isinstance(value, dict) or not ANALYSIS_CONTEXT_FIELDS.issubset(value)
                or set(value) - ANALYSIS_CONTEXT_FIELDS - ANALYSIS_OPTIONAL_FIELDS):
            raise WorkbenchError("analysis context requires incident_number, item, step, equipment, from, to, and wafers")
        normalized = {}
        supplied_incident = value["incident_number"]
        if (not isinstance(supplied_incident, str) or not supplied_incident.strip()
                or len(supplied_incident) > 64 or supplied_incident != incident_number):
            raise WorkbenchError("context incident_number must match the room incident")
        normalized["incident_number"] = incident_number
        for field in ANALYSIS_TEXT_FIELDS:
            item = value[field]
            empty_allowed = field == "equipment"
            if (not isinstance(item, str) or (not empty_allowed and not item.strip())
                    or len(item) > ANALYSIS_TEXT_LIMIT):
                raise WorkbenchError(f"context {field} must be a string up to {ANALYSIS_TEXT_LIMIT} characters")
            normalized[field] = item
        from_time = _analysis_time(value["from"], "from")
        to_time = _analysis_time(value["to"], "to")
        normalized["from"] = value["from"]
        normalized["to"] = value["to"]
        if from_time > to_time:
            raise WorkbenchError("context from must be on or before context to")
        if "recipe" in value:
            if not isinstance(value["recipe"], str) or len(value["recipe"]) > ANALYSIS_TEXT_LIMIT:
                raise WorkbenchError("context recipe must be a string up to 256 characters")
            normalized["recipe"] = value["recipe"]
        if "trend_selection" in value:
            trend = value["trend_selection"]
            if (not isinstance(trend, dict) or set(trend) != {"range_selected", "value_range", "regions"}
                    or type(trend["range_selected"]) is not bool):
                raise WorkbenchError("invalid context trend_selection")

            def valid_bounds(bounds):
                return (isinstance(bounds, list) and len(bounds) == 2
                        and all(type(item) in (int, float) and math.isfinite(item) for item in bounds)
                        and bounds[0] <= bounds[1])

            regions = trend["regions"]
            if (trend["value_range"] is not None and not valid_bounds(trend["value_range"])):
                raise WorkbenchError("invalid context trend_selection value_range")
            if (not isinstance(regions, list) or len(regions) > 16
                    or any(not isinstance(region, list) or len(region) != 2
                           or not all(valid_bounds(axis) for axis in region) for region in regions)):
                raise WorkbenchError("invalid context trend_selection regions")
            if not trend["range_selected"] and (regions or trend["value_range"] is not None):
                raise WorkbenchError("inactive context trend_selection must have no bounds")
            normalized["trend_selection"] = copy.deepcopy(trend)
        if "map_view" in value:
            view = value["map_view"]
            if (not isinstance(view, dict) or set(view) != {"kind", "overlay"}
                    or view["kind"] not in ("cd", "thk", "overlay", "bin")
                    or view["overlay"] not in ("raw", "fit", "residual")):
                raise WorkbenchError("invalid context map_view")
            normalized["map_view"] = dict(view)
        wafers = value["wafers"]
        if not isinstance(wafers, list) or len(wafers) > ANALYSIS_MAX_WAFERS:
            raise WorkbenchError(f"context wafers must be an array of at most {ANALYSIS_MAX_WAFERS} items")
        normalized_wafers = []
        seen = set()
        for item in wafers:
            if not isinstance(item, dict) or set(item) != {"lot_id", "wafer_id"}:
                raise WorkbenchError("context wafers must contain lot_id and wafer_id only")
            lot_id, wafer_id = item["lot_id"], item["wafer_id"]
            if (not isinstance(lot_id, str) or not lot_id.strip() or len(lot_id) > 128
                    or not isinstance(wafer_id, str) or not wafer_id.strip() or len(wafer_id) > 128):
                raise WorkbenchError("context wafer tuple fields are invalid")
            pair = (lot_id, wafer_id)
            if pair in seen:
                raise WorkbenchError("context wafers must be unique")
            seen.add(pair)
            normalized_wafers.append({"lot_id": lot_id, "wafer_id": wafer_id})
        workspace = self._workspace(incident_number, include_meetings=False)
        registered = {(item.get("lot_id"), item.get("wafer_id")) for item in workspace["wafers"]}
        if any((item["lot_id"], item["wafer_id"]) not in registered for item in normalized_wafers):
            raise WorkbenchError("context wafer tuple is outside the registered incident scope")
        normalized["wafers"] = normalized_wafers
        if "map_comparison" in value:
            groups = value["map_comparison"]
            if not isinstance(groups, dict) or set(groups) != {"a", "b"}:
                raise WorkbenchError("invalid context map_comparison")
            for pairs in groups.values():
                if not isinstance(pairs, list) or len(pairs) > ANALYSIS_MAX_WAFERS:
                    raise WorkbenchError("invalid context map_comparison size")
                seen = set()
                for pair in pairs:
                    if (not isinstance(pair, dict) or set(pair) != {"lot_id", "wafer_id"}
                            or any(not isinstance(item, str) for item in pair.values())):
                        raise WorkbenchError("invalid context map_comparison pair")
                    key = (pair["lot_id"], pair["wafer_id"])
                    if key not in registered or key in seen:
                        raise WorkbenchError("context map_comparison must contain distinct registered wafers")
                    seen.add(key)
            normalized["map_comparison"] = copy.deepcopy(groups)
        if "sem_wafers" in value:
            pairs = value["sem_wafers"]
            if not isinstance(pairs, list) or len(pairs) > 2:
                raise WorkbenchError("context sem_wafers must contain at most two wafer pairs")
            seen = set()
            for pair in pairs:
                if (not isinstance(pair, dict) or set(pair) != {"lot_id", "wafer_id"}
                        or any(not isinstance(item, str) for item in pair.values())):
                    raise WorkbenchError("invalid context sem_wafers pair")
                key = (pair["lot_id"], pair["wafer_id"])
                if key not in registered or key in seen:
                    raise WorkbenchError("context sem_wafers must be distinct registered wafers")
                seen.add(key)
            normalized["sem_wafers"] = copy.deepcopy(pairs)
        return normalized

    @staticmethod
    def _analysis_scope_text(sources, context):
        wafer_text = ", ".join(f"{item['lot_id']}/{item['wafer_id']}" for item in context["wafers"]) or "none"
        trend_text = json.dumps(context.get("trend_selection"), separators=(",", ":"))
        sem_text = json.dumps(context.get("sem_wafers", []), separators=(",", ":"))
        map_text = json.dumps(context.get("map_view"), separators=(",", ":"))
        comparison_text = json.dumps(context.get("map_comparison"), separators=(",", ":"))
        return (f"sources={','.join(sources)}; incident={context['incident_number']}; "
                f"item={context.get('item') or 'none'}; step={context.get('step') or 'none'}; "
                f"equipment={context['equipment'] if context['equipment'] else 'all'}; "
                f"recipe={context.get('recipe') or 'all'}; "
                f"date={context['from']}..{context['to']}; wafers={wafer_text}; "
                f"trend_selection={trend_text}; sem_wafers={sem_text}; map_view={map_text}; "
                f"map_comparison={comparison_text} "
                "(UI condition only; region X=Unix ms, Y=item value)")

    def _analysis_answer(self, data, sources, context):
        incident, lots, wafers, meetings = data["incident"], data["lots"], data["wafers"], data["meetings"]
        incident_number = incident["incident_number"]
        lines = [
            f"{incident_number} 선택 소스 분석 결과 (synthetic demo)",
            "실제 LLM에 연결되지 않았습니다. 이 답변은 선택된 합성 DB 조회 결과이며 추론이나 Router/Judge 실행을 주장하지 않습니다.",
            f"사고 DB: 제목={incident.get('title') or '기록 없음'}; 발생시각={incident.get('occurred_at') or '기록 없음'}",
            f"사고 DB 필드: 분석={incident.get('analysis_detail') or '기록 없음'}; 확인 원인={incident.get('confirmed_cause') or '확정되지 않음'}",
            f"등록 Lot: {len(lots)}건 (기대 {incident.get('expected_lot_count')})",
            f"등록 Wafer: {len(wafers)}건 (기대 {incident.get('affected_wafer_count')})",
            f"뷰어 선택 Wafer: {len(context['wafers'])}건. 사고 등록 키만 검증했으며 실제 Fab 시각/설비 매칭은 미연결입니다.",
            f"요청 scope: {self._analysis_scope_text(sources, context)}",
        ]
        attachments = [self._ref("data", incident_number, incident["incident_id"], incident_number)]
        steps = [{"source": "incident", "status": "completed",
                  "detail": f"local synthetic incident DB queried; lots={len(lots)}, wafers={len(wafers)}"}]
        for source in sources[1:]:
            if source == "meetings":
                steps.append({"source": "meetings", "status": "completed",
                              "detail": f"selected incident-scoped meeting retrieval completed; excerpts={len(meetings)}"})
                if meetings:
                    lines.append("선택된 회의 excerpts:")
                    for item in meetings:
                        lines.append(f"- {item['meeting_date']} {item['title']}: {item['text']}")
                        attachments.append(self._ref("inform", item["title"], item["chunk_id"], incident_number))
            else:
                steps.append({"source": source, "status": "unavailable",
                              "detail": "UI-only synthetic source; backend is unavailable and no real LLM inference was used."})
        return "\n".join(lines), attachments, steps

    def _append_analysis(self, room_id, content, sources, context, answer, answer_attachments, analysis):
        scope_text = self._analysis_scope_text(sources, context)
        scope_attachment = self._ref("data", "selected analysis scope", context["incident_number"], context["incident_number"])
        user = {"id": "msg-" + uuid.uuid4().hex, "role": "user",
                "content": content + "\n분석 scope: " + scope_text,
                "created_at": _now(), "attachments": [scope_attachment]}
        assistant = {"id": "msg-" + uuid.uuid4().hex, "role": "assistant",
                     "content": answer,
                     "created_at": _now(), "attachments": answer_attachments}
        analysis = {**analysis, "answer_message_id": assistant["id"]}
        now = _now()
        with self.lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            room = db.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
            if not room:
                raise WorkbenchError("room not found")
            if room["incident_number"] != context["incident_number"]:
                raise WorkbenchError("analysis scope incident does not match the room")
            db.execute("""INSERT INTO analysis_scopes
                (room_id, incident_number, sources, context, steps, runtime, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(room_id) DO UPDATE SET incident_number=excluded.incident_number,
                sources=excluded.sources, context=excluded.context, steps=excluded.steps, runtime=excluded.runtime,
                updated_at=excluded.updated_at""",
                        (room_id, context["incident_number"], json.dumps(sources, ensure_ascii=False),
                         json.dumps(context, ensure_ascii=False), json.dumps(analysis["steps"], ensure_ascii=False),
                         json.dumps({k: v for k, v in analysis.items() if k not in ("sources", "context", "steps")}, ensure_ascii=False), now, now))
            for item in (user, assistant):
                db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)", (item["id"], room_id, item["role"],
                             item["content"], item["created_at"], json.dumps(item["attachments"], ensure_ascii=False)))
            db.execute("UPDATE rooms SET updated_at=? WHERE id=?", (now, room_id))
            db.commit()
        return {"messages": [user, assistant], "room": _summary(self._room(room_id)), "analysis": analysis}

    def _append_messages(self, room_id, content, attachments, answer, answer_attachments, room=None):
        user = {"id": "msg-" + uuid.uuid4().hex, "role": "user", "content": content, "created_at": _now(), "attachments": attachments}
        assistant = {"id": "msg-" + uuid.uuid4().hex, "role": "assistant", "content": answer, "created_at": _now(), "attachments": answer_attachments}
        with self.lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM rooms WHERE id=?", (room_id,)).fetchone():
                raise WorkbenchError("room not found")
            if room is not None:
                db.execute("UPDATE rooms SET incident_number=? WHERE id=?", (room["incident_number"], room_id))
            for item in (user, assistant):
                db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)", (item["id"], room_id, item["role"], item["content"], item["created_at"], json.dumps(item["attachments"], ensure_ascii=False)))
            db.execute("UPDATE rooms SET updated_at=? WHERE id=?", (_now(), room_id))
            db.commit()
        return {"messages": [user, assistant], "room": _summary(self._room(room_id))}

    def _answer(self, incident_number, content):
        data = self._workspace(incident_number)
        incident, lots, wafers, meetings = data["incident"], data["lots"], data["wafers"], data["meetings"]
        lower = content.casefold()
        if any(word in lower for word in ("production", "생산계", "생산 시스템", "prod system", "prod 시스템")):
            return ("Production system에는 연결되지 않은 synthetic demo입니다. 회사 생산계 기록을 조회하거나 추론해 만들지 않았습니다. (출처: demo)", [])
        if any(word in lower for word in ("sem", "image", "이미지", "overlay", "오버레이", "map", "맵", "지도")):
            return ("SEM/image/overlay map source와 모델에는 연결되지 않은 synthetic demo입니다. 실제 이미지·map 값이나 회사 기록을 생성하지 않았습니다. (출처: demo)", [])
        attachments = [self._ref("data", incident_number, incident["incident_id"], incident_number)]
        lines = [f"{incident_number} 합성 DB 조회 결과", f"제목: {incident['title']}",
                 f"분석 기록: {incident.get('analysis_detail') or '기록 없음'}",
                 f"확인 원인: {incident.get('confirmed_cause') or '확정되지 않음'}",
                 f"등록 Lot: 실제 조회 {len(lots)}건 (기대 {incident.get('expected_lot_count')}건)"]
        if "wafer" in lower or "웨이퍼" in content:
            lines.append(f"등록 Wafer: 실제 조회 {len(wafers)}건")
        focused_on_counts = "lot" in lower or "wafer" in lower or "로트" in content or "웨이퍼" in content
        if meetings and (not focused_on_counts or any(word in content for word in ("회의", "Inform", "inform", "근거", "원인", "조치"))):
            lines.append("관련 회의 원문:")
            for item in meetings:
                lines.append(f"- {item['meeting_date']} {item['title']}: {item['text']}")
                attachments.append(self._ref("inform", item["title"], item["chunk_id"], incident_number))
        lines.append("※ 이 답변은 LLM 생성이 아닌 합성 DB 조회 결과입니다. (출처: demo)")
        return "\n".join(lines), attachments

    def _require_incident(self, incident):
        if not isinstance(incident, str) or incident not in self._incident_map():
            raise WorkbenchError("incident not found")

    @staticmethod
    def _title(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise WorkbenchError("title must be a nonempty string up to 200 characters")
        return value.strip()

    @staticmethod
    def _ref(kind, label, identifier, incident_number):
        return {"kind": kind, "label": label, "id": identifier, "incident_number": incident_number}

    def _attachments(self, value, incident_number):
        if not isinstance(value, list) or len(value) > 20:
            raise WorkbenchError("attachments must be a list of at most 20 items")
        valid_incidents = set(self._incident_map())
        result = []
        for item in value:
            if not isinstance(item, dict) or set(item) - {"kind", "label", "id", "incident_number"} or not {"kind", "label", "id"}.issubset(item):
                raise WorkbenchError("invalid attachment")
            if any(not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > 256 for key in ("kind", "label", "id")):
                raise WorkbenchError("invalid attachment")
            attachment_incident = item.get("incident_number", incident_number)
            if attachment_incident is not None and (not isinstance(attachment_incident, str) or attachment_incident not in valid_incidents):
                raise WorkbenchError("invalid attachment incident_number")
            result.append(self._ref(item["kind"], item["label"], item["id"], attachment_incident))
        return result

    @staticmethod
    def _message(row):
        return {"id": row["id"], "role": row["role"], "content": row["content"], "created_at": row["created_at"], "attachments": json.loads(row["attachments"])}


class Handler(BaseHTTPRequestHandler):
    server_version = "QAgentWorkbench/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def app(self):
        return self.server.app

    def log_message(self, *_):
        return

    def _guard(self):
        if not _loopback(self.headers.get("Host")) or not _origin_ok(self.headers.get("Origin")):
            self._send(403, {"error": "loopback host/origin required"})
            return False
        if self.headers.get("Transfer-Encoding", "").lower() not in ("", "identity"):
            self._send(400, {"error": "chunked requests are not supported"})
            return False
        length = self.headers.get("Content-Length")
        if length is not None:
            try:
                if int(length) > MAX_BODY or int(length) < 0:
                    self._send(413, {"error": "request body too large"})
                    return False
            except ValueError:
                self._send(400, {"error": "invalid content length"})
                return False
        return True

    def _send(self, status, value, content_type="application/json; charset=utf-8"):
        body = value if isinstance(value, bytes) else _json(value)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            raise WorkbenchError("request body too large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise WorkbenchError("JSON body required") from None

    def _route(self):
        parts = [unquote(part) for part in urlsplit(self.path).path.split("/") if part]
        if any(part in (".", "..") or "\x00" in part for part in parts):
            raise WorkbenchError("invalid path")
        return parts

    def _api(self, method, parts):
        if (len(parts) == 3 and parts[:2] == ["api", "demo-images"]
                and parts[2] in ("assets", "compare") and method == "POST"):
            return self.app.demo_image_request(parts[2], self._read())
        if parts == ["api", "bootstrap"] and method == "GET": return self.app.bootstrap()
        if parts == ["api", "monitoring"] and method == "GET": return self.app.monitoring()
        if parts == ["api", "monitoring", "replay"] and method == "POST": return self.app.replay_detection(self._read())
        if len(parts) == 4 and parts[:2] == ["api", "monitoring"] and method == "POST":
            body = self._read()
            try:
                if parts[3] == "retry" and body == {}: return self.app.monitor.retry(parts[2])
                if parts[3] == "decision" and isinstance(body, dict) and set(body) == {"decision"}:
                    return self.app.monitor.decide(parts[2], body["decision"])
            except ValueError as exc:
                raise WorkbenchError(str(exc)) from None
            raise WorkbenchError("invalid monitoring action; production execution is unavailable")
        if parts == ["api", "workspace"] and method == "GET":
            values = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("incident", [])
            if len(values) != 1 or not values[0]: raise WorkbenchError("incident query is required")
            return self.app.workspace(values[0])
        if len(parts) >= 3 and parts[:2] == ["api", "rooms"]:
            room_id = parts[2]
            if len(parts) == 3 and method == "GET":
                values = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("before", [])
                if len(values) > 1 or (values and not values[0]):
                    raise WorkbenchError("invalid before cursor")
                return self.app.room(room_id, values[0] if values else None)
            if len(parts) == 4 and parts[3] == "analysis" and method == "GET": return self.app.analysis_metadata(room_id)
            if len(parts) == 5 and parts[3:] == ["analysis", "progress"] and method == "GET": return self.app.analysis_progress(room_id)
            if len(parts) == 3 and method == "PATCH": return self.app.update_room(room_id, self._read())
            if len(parts) == 3 and method == "DELETE": return self.app.delete_room(room_id)
            if len(parts) == 4 and parts[3] == "analysis" and method == "POST": return self.app.analysis(room_id, self._read())
            if len(parts) == 4 and parts[3] == "messages" and method == "POST": return self.app.message(room_id, self._read())
        if parts == ["api", "rooms"] and method == "POST":
            body = self._read()
            if not isinstance(body, dict) or set(body) - {"title", "incident_number"}:
                raise WorkbenchError("invalid room fields")
            return self.app.create_room(body.get("title"), body.get("incident_number"))
        raise WorkbenchError("not found")

    def _static(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/": path = "/index.html"
        if any(part in (".", "..") for part in Path(path).parts):
            raise WorkbenchError("invalid path")
        root = self.app.static_root.resolve()
        target = (root / path.lstrip("/")).resolve()
        try: target.relative_to(root)
        except ValueError: raise WorkbenchError("invalid path") from None
        if not target.is_file(): raise WorkbenchError("static file not found")
        self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")

    def _handle(self):
        if not self._guard(): return
        try:
            parts = self._route()
            if parts and parts[0] == "api":
                self._send(200, self._api(self.command, parts))
            elif self.command == "GET":
                self._static()
            else:
                raise WorkbenchError("not found")
        except WorkbenchError as exc:
            self._send(404 if str(exc) in ("not found", "static file not found", "room not found", "incident not found") else 400, {"error": str(exc)})
        except Exception:
            self._send(500, {"error": "internal workbench error"})

    do_GET = _handle
    do_POST = _handle
    do_PATCH = _handle
    do_DELETE = _handle


class WorkbenchServer(ThreadingHTTPServer):
    def server_close(self):
        if hasattr(self, "app"):
            self.app.monitor.stop()
        super().server_close()


def create_server(config_path: str | Path = REPO_ROOT / "config/workbench.yaml", port: int | None = None,
                  *, raw_file=None, agent_overlay=None):
    if port is not None and (type(port) is not int or not 0 <= port <= 65535):
        raise WorkbenchError("port must be between 0 and 65535")
    config = load_workbench(config_path, raw_file=raw_file, agent_overlay=agent_overlay)
    server = WorkbenchServer(("127.0.0.1", config["port"] if port is None else port), Handler)
    server.app = Workbench(config)
    server.app.monitor.start()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    parser.add_argument("--config", default=str(REPO_ROOT / "config/workbench.yaml"))
    parser.add_argument("--raw-file")
    parser.add_argument("--agent-overlay")
    args = parser.parse_args(argv)
    try:
        server = create_server(args.config, args.port, raw_file=args.raw_file, agent_overlay=args.agent_overlay)
    except (WorkbenchError, ConfigError) as exc:
        parser.exit(2, f"WORKBENCH_ERROR: {exc}\n")
    print(f"Q-Agent synthetic workbench: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
