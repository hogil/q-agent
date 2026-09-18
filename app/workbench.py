"""Loopback-only HTTP workbench for the local synthetic Q-Agent demo."""
from __future__ import annotations

import argparse
import json
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

from config_loader import ConfigError, load_config, read_config  # noqa: E402
from demo_data import generate  # noqa: E402
from incident_tools import ToolError  # noqa: E402
from meeting_tools import MeetingTools  # noqa: E402
from runtime_factory import open_incident_tools  # noqa: E402


MAX_BODY = 64 * 1024
INCIDENT_RE = re.compile(r"(?<![A-Za-z0-9])SYN-2026-\d{2}(?![A-Za-z0-9])")
SAFE_HOSTS = {"127.0.0.1", "localhost", "::1"}
INCIDENT_FIELDS = [
    "incident_detail", "analysis_detail", "confirmed_cause", "containment",
    "corrective_action", "verification", "prevention", "remaining",
    "department", "product_generations", "fab_out_failure_codes",
]


class WorkbenchError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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


def load_workbench(path: str | Path) -> dict:
    config_path = Path(path).expanduser().resolve()
    raw = read_config(config_path)
    if set(raw) != {"config_version", "demo", "chat", "cutoff", "static_root"}:
        raise WorkbenchError("workbench config keys are invalid")
    if raw["config_version"] != 1:
        raise WorkbenchError("unsupported workbench config version")
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
            "release": registry.get("release", "unknown")}


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
        self.actor = "local-workbench"
        self.lock = threading.RLock()
        self.chat_db.parent.mkdir(parents=True, exist_ok=True)
        self._init_chat_db()
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
            """)

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

    def _workspace(self, incident_number):
        incident = self._incident_map().get(incident_number)
        if incident is None:
            raise WorkbenchError("incident not found")
        try:
            with open_incident_tools(self.settings) as tool:
                found = tool.find_incidents(self.actor, incident_number=incident_number, fields=INCIDENT_FIELDS)
                scope = found["scope_id"]
                lots = self._pages(tool.list_incident_lots, self.actor, scope)
                wafers = self._pages(tool.list_incident_wafers, self.actor, scope)
            meetings = MeetingTools(self.settings).search(
                self.actor, incident_number, [incident["incident_id"]], self.cutoff, top_k=self.settings.data["meetings"]["max_top_k"]
            )["items"]
        except (ToolError, KeyError, OSError) as exc:
            raise WorkbenchError(str(exc)) from None
        return {"incident": incident, "lots": lots, "wafers": wafers, "meetings": meetings,
                "synthetic": True, "as_of": self.cutoff}

    def bootstrap(self):
        return {"synthetic": True, "mode": "demo", "llm_connected": False,
                "incidents": self._incidents(), "rooms": [_summary(row) for row in self._rooms()],
                "release": self.release}

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
            if not db.execute("DELETE FROM rooms WHERE id=?", (room_id,)).rowcount:
                raise WorkbenchError("room not found")
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
        with self.lock:
            return self._message_locked(room_id, body)

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
        if parts == ["api", "bootstrap"] and method == "GET": return self.app.bootstrap()
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
            if len(parts) == 3 and method == "PATCH": return self.app.update_room(room_id, self._read())
            if len(parts) == 3 and method == "DELETE": return self.app.delete_room(room_id)
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


def create_server(config_path: str | Path = REPO_ROOT / "config/workbench.yaml", port: int = 8787):
    if type(port) is not int or not 0 <= port <= 65535:
        raise WorkbenchError("port must be between 0 and 65535")
    config = load_workbench(config_path)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = Workbench(config)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--config", default=str(REPO_ROOT / "config/workbench.yaml"))
    args = parser.parse_args(argv)
    try:
        server = create_server(args.config, args.port)
    except (WorkbenchError, ConfigError) as exc:
        parser.exit(2, f"WORKBENCH_ERROR: {exc}\n")
    print(f"Q-Agent synthetic workbench: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
