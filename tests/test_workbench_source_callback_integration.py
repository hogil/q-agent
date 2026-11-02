"""End-to-end Workbench retrieval callback checks using temporary synthetic data."""

import copy
from contextlib import closing
from contextlib import redirect_stdout
from io import StringIO
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import agent
import run_agent as run_agent_module
import app.workbench as workbench_module
from app.config_loader import (ConfigError, DEFAULT_CONFIG, SPEC, Settings, check_shape, merge,
                               load_config, read_config, resolve_paths, validate_values)
from app.document_evidence_contract import validate_hybrid_response
from mes_reference_sqlite import SyntheticMESReferenceReader
from app.workbench import Workbench, load_workbench
from skill_loader import freeze


def plan(tool=None, arguments=None, *, ready=False):
    return {
        "intents": ["analysis"], "filters": {}, "plan": [] if ready or tool is None else [{
            "tool": tool, "arguments": arguments or {}, "depends_on": [], "reason": "synthetic integration check",
        }], "needs_skills": [], "clarification": None,
        "decision": "ready_for_judge" if ready else "execute",
        "stage": "incident" if tool == "find_incidents" else "tools",
        "search_mode": "sql_exact" if tool == "find_incidents" else "none", "limitations": [],
    }


def judge(payload):
    ids = payload["evidence_ids"]
    return {"verdict": "pass", "return_to": "answer", "coverage": [{
        "requirement": payload["question"], "status": "satisfied", "evidence_ids": ids,
    }], "issues": []}


def answer(payload):
    return {"status": "answered", "answer": "합성 MES 기준정보를 조회했습니다.", "claims": [{
        "claim_id": "c1", "text": "합성 기준정보가 근거에 있습니다.",
        "evidence_ids": payload["evidence_ids"],
    }], "limitations": [], "inspection_plan": {
        "historical_matches": [],
        "checks": [{"target": "synthetic product reference", "basis": "Retrieved synthetic MES reference",
                    "comparison": "Compare the selected incident's product conditions",
                    "evidence_ids": payload["evidence_ids"]}],
        "eds_followup": {"target": "synthetic EDS reference", "basis": "Follow up against retrieved reference",
                         "comparison": "Compare available synthetic EDS evidence",
                         "evidence_ids": payload["evidence_ids"]},
    }}


class ScriptedClient:
    def __init__(self, source_tool="search_mes_reference"):
        self.calls = []
        search_args = ({"kind": "product", "query": "Alpha"} if source_tool == "search_mes_reference"
                       else {"query": "Alpha"})
        self.steps = iter([
            ("router", plan("find_incidents", {"incident_number": "SYN-2026-01"})),
            ("router", plan(source_tool, search_args)),
            ("judge", judge), ("answer", answer),
        ])

    def call(self, role, system_prompt, payload, history):
        expected, output = next(self.steps)
        if expected != role:
            raise AssertionError((role, expected))
        self.calls.append((role, copy.deepcopy(payload)))
        value = output(payload) if callable(output) else output
        call_id = "synthetic-call" if role == "router" else None
        if role == "router":
            history.append({"role": "assistant", "tool_calls": [{"id": call_id, "type": "function",
                "function": {"name": "submit_plan", "arguments": json.dumps(value)}}]})
        return value, call_id


class WorkbenchSourceCallbackIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config_path = root / "workbench.yaml"
        static_root = root / "static"
        static_root.mkdir()
        (static_root / "index.html").write_text("<main>test</main>", encoding="utf-8")
        self.overlay_path = root / "demo.yaml"
        self.overlay_path.write_text(
            f"environment: demo\npaths:\n  data_root: {str(root / 'data').replace(chr(92), '/')}\n"
            f"meetings:\n  enabled: true\n  sqlite_file: {str(root / 'data' / 'meetings.sqlite').replace(chr(92), '/')}\n",
            encoding="utf-8")
        self.config_path.write_text(
            "config_version: 1\n"
            f"demo:\n  base_config: {str(ROOT / 'config/config.yaml').replace(chr(92), '/')}\n"
            f"  overlay: {str(self.overlay_path).replace(chr(92), '/')}\n"
            f"chat:\n  sqlite_file: {str(root / 'chat.sqlite').replace(chr(92), '/')}\n  history_limit: 40\n"
            "cutoff: 2026-03-31\n"
            f"static_root: {str(static_root).replace(chr(92), '/')}\n", encoding="utf-8")
        config = load_workbench(self.config_path)
        settings_data = copy.deepcopy(config["settings"].data)
        settings_data["paths"]["skill_lock_file"] = str((root / "release.lock.json").resolve())
        config["settings"] = Settings(settings_data, config["settings"].source_files)
        self.assertTrue(Path(config["settings"].data["database"]["sqlite_file"]).is_relative_to(root))
        self.assertTrue(Path(config["settings"].data["meetings"]["sqlite_file"]).is_relative_to(root))
        self.mes_path = root / "synthetic-mes.sqlite"
        with closing(sqlite3.connect(self.mes_path)) as db:
            db.execute("CREATE TABLE synthetic_refs (kind, record_id, version, name, source_ref, available_at, effective_from, effective_to, applicability, incident_ids)")
            db.execute("INSERT INTO synthetic_refs VALUES (?,?,?,?,?,?,?,?,?,?)", (
                "product", "SYN-PROD-1", "v1", "Product Alpha", "synthetic://product/1",
                "2026-03-01T00:00:00+09:00", "2026-01-01T00:00:00+09:00", None,
                "candidate", json.dumps(["SYN-2026-01"])))
            db.commit()
        mapping = {"table": "synthetic_refs", "columns": {key: key for key in (
            "kind", "record_id", "version", "name", "source_ref", "available_at",
            "effective_from", "effective_to", "applicability", "incident_ids")}}
        reader = SyntheticMESReferenceReader(self.mes_path, mapping, timezone_name="Asia/Seoul",
                                             allowed_kinds={"product"})
        self.reader_calls = []

        def recorded_reader(**kwargs):
            self.reader_calls.append(copy.deepcopy(kwargs))
            return reader(**kwargs)

        data = merge(config["settings"].data, {
            "models": {"text": {"enabled": True, "mode": "api", "base_url": "http://llm.test/v1",
                                 "api_key_env": "UNUSED_SYNTHETIC_TEST_KEY", "served_model": "scripted"}},
            "mes_reference": {"enabled": True, "top_k": 10, "allowed_kinds": ["product"]},
        })
        config["settings"] = Settings(data, config["settings"].source_files)
        freeze(settings=config["settings"])
        self.workbench_config = config
        self.app = Workbench(config, mes_reference_query=recorded_reader)
        self.room_id = self.app.create_room("synthetic integration", "SYN-2026-01")["id"]
        self.incident_id = self.app.workspace("SYN-2026-01")["incident"]["incident_id"]
        wafer = self.app.workspace("SYN-2026-01")["wafers"][0]
        self.context = {
            "incident_number": "SYN-2026-01", "item": "SYN-TEMP", "step": "ETCH",
            "equipment": "EQP-ETCH-01", "from": "2026-01-01T00:00:00+00:00",
            "to": "2026-01-31T23:59:59+00:00",
            "wafers": [{"lot_id": wafer["lot_id"], "wafer_id": wafer["wafer_id"]}],
        }

    def test_workbench_incident_first_real_synthetic_mes_reader_to_judge_answer(self):
        client = ScriptedClient()
        with patch.object(workbench_module, "run_agent", wraps=agent.run) as run_agent:
            run_agent.side_effect = lambda *args, **kwargs: agent.run(*args, **kwargs)
            with patch.object(agent, "RoleClient", return_value=client):
                result = self.app.analysis(self.room_id, {
                    "content": "선택 사고의 Product Alpha 기준정보를 확인해줘",
                    "sources": ["incident", "mes_reference_search"], "context": self.context,
                })

        roles = [role for role, _ in client.calls]
        self.assertEqual(roles[-2:], ["judge", "answer"])
        self.assertEqual(roles, ["router", "router", "judge", "answer"])
        self.assertEqual(self.reader_calls[0]["actor"], "local-workbench")
        self.assertEqual(self.reader_calls[0]["incident_ids"], [self.incident_id])
        self.assertEqual(self.reader_calls[0]["as_of"], "2026-03-31")
        self.assertEqual(self.reader_calls[0]["kind"], "product")
        self.assertEqual(self.reader_calls[0]["query"], "Alpha")

        retrieved = result["analysis"]["report"]["retrieval_evidence"]
        self.assertEqual(len(retrieved), 1)
        evidence = retrieved[0]["result"]
        self.assertEqual(evidence["status"], "OK")
        self.assertEqual(evidence["as_of"], "2026-03-31")
        self.assertEqual(evidence["incident_ids"], [self.incident_id])
        self.assertEqual(evidence["items"][0]["record_id"], "SYN-PROD-1")
        self.assertEqual(result["analysis"]["steps"][-1]["status"], "completed")
        self.assertIn("SYN-PROD-1", json.dumps(client.calls[-1][1]["evidence"], ensure_ascii=False))
        self.assertIn("합성 MES 기준정보를 조회했습니다", result["messages"][-1]["content"])

    def test_configured_reader_is_created_and_explicit_callback_wins(self):
        data = copy.deepcopy(self.app.settings.data)
        data['paths']['data_root'] = str(self.mes_path.parent)
        data['mes_reference']['synthetic_sqlite'] = {
            'enabled': True, 'database_file': str(self.mes_path.resolve()), 'table': 'synthetic_refs',
            'timezone': 'Asia/Seoul',
            'columns': {key: key for key in ('kind', 'record_id', 'version', 'name', 'source_ref',
                'available_at', 'effective_from', 'effective_to', 'applicability', 'incident_ids')},
        }
        enabled = {**self.workbench_config, 'settings': Settings(data, self.app.settings.source_files)}
        configured = Workbench(enabled)
        self.addCleanup(configured.monitor.stop)
        self.assertIsInstance(configured.mes_reference_query, SyntheticMESReferenceReader)
        with closing(configured.mes_reference_query._connect()) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO synthetic_refs VALUES ('x','x','x','x','x','2026-03-01',NULL,NULL,'x','[]')")
        callback = lambda **kwargs: {'status': 'NO_MATCH'}
        overridden = Workbench(enabled, mes_reference_query=callback)
        self.addCleanup(overridden.monitor.stop)
        self.assertIs(overridden.mes_reference_query, callback)

    def test_synthetic_reader_config_validation_and_data_root_confinement(self):
        options = {
            'enabled': True, 'database_file': 'mes-reference.sqlite', 'table': 'synthetic_refs',
            'timezone': 'Asia/Seoul',
            'columns': {key: key for key in ('kind', 'record_id', 'version', 'name', 'source_ref',
                'available_at', 'effective_from', 'effective_to', 'applicability', 'incident_ids')},
        }
        data = merge(read_config(DEFAULT_CONFIG), {
            'paths': {'data_root': str(Path(self.temp.name) / 'data')},
            'mes_reference': {'enabled': True, 'allowed_kinds': ['product'], 'synthetic_sqlite': options},
        })
        check_shape(data, SPEC)
        validate_values(data)
        resolve_paths(data, ROOT / 'config')
        self.assertEqual(data['mes_reference']['synthetic_sqlite']['database_file'],
                         str((Path(self.temp.name) / 'data' / 'mes-reference.sqlite').resolve()))

        invalid = merge(read_config(DEFAULT_CONFIG), {'mes_reference': {
            'enabled': True, 'allowed_kinds': ['product'], 'synthetic_sqlite': options,
        }})
        invalid['mes_reference']['synthetic_sqlite']['columns'] = {'kind': 'kind'}
        with self.assertRaisesRegex(ConfigError, 'all required logical columns'):
            validate_values(invalid)
        invalid = merge(read_config(DEFAULT_CONFIG), {'mes_reference': {
            'enabled': True, 'allowed_kinds': ['product'],
            'synthetic_sqlite': {**options, 'database_file': '../outside.sqlite'},
        }})
        with self.assertRaisesRegex(ConfigError, 'below paths.data_root'):
            validate_values(invalid)
        invalid['environment'] = 'onprem'
        with self.assertRaisesRegex(ConfigError, 'demo MES reference only'):
            validate_values(invalid)

    def test_check_paths_checks_only_enabled_synthetic_reader_file(self):
        base = load_config(DEFAULT_CONFIG)
        base.check_paths()
        root = Path(self.temp.name) / 'check-paths-data'
        root.mkdir()
        data = copy.deepcopy(base.data)
        data['paths']['data_root'] = str(root)
        data['mes_reference']['synthetic_sqlite']['database_file'] = str(root / 'not-created.sqlite')
        off_settings = Settings(data, base.source_files)
        off_settings.check_paths()  # Existing default-off behavior ignores the optional DB path.

        enabled = copy.deepcopy(data)
        enabled['mes_reference']['enabled'] = True
        enabled['mes_reference']['allowed_kinds'] = ['product']
        enabled['mes_reference']['synthetic_sqlite']['enabled'] = True
        enabled['mes_reference']['synthetic_sqlite']['database_file'] = str(root / 'present.sqlite')
        present = Path(enabled['mes_reference']['synthetic_sqlite']['database_file'])
        present.touch()
        Settings(enabled, base.source_files).check_paths()

        enabled['mes_reference']['synthetic_sqlite']['database_file'] = str(root / 'missing.sqlite')
        with self.assertRaisesRegex(ConfigError, 'mes_reference.synthetic_sqlite.database_file: file missing'):
            Settings(enabled, base.source_files).check_paths()

    def test_create_server_builds_configured_reader_from_site_overlay(self):
        database_root = Path(self.temp.name) / 'data'
        database_root.mkdir(exist_ok=True)
        db_path = database_root / 'mes-reference.sqlite'
        with closing(sqlite3.connect(db_path)) as db:
            db.execute('CREATE TABLE synthetic_refs (kind, record_id, version, name, source_ref, available_at, effective_from, effective_to, applicability, incident_ids)')
            db.commit()
        self.overlay_path.write_text(
            f"environment: demo\npaths:\n  data_root: {database_root.as_posix()}\n"
            "meetings:\n  enabled: true\n"
            "models:\n  text:\n    enabled: true\n    mode: api\n    base_url: http://llm.test/v1\n"
            "    api_key_env: UNUSED_SYNTHETIC_TEST_KEY\n    served_model: scripted\n"
            "mes_reference:\n  enabled: true\n  top_k: 10\n  allowed_kinds: [product]\n"
            "  synthetic_sqlite:\n    enabled: true\n    database_file: mes-reference.sqlite\n"
            "    table: synthetic_refs\n    timezone: Asia/Seoul\n    columns:\n"
            "      kind: kind\n      record_id: record_id\n      version: version\n"
            "      name: name\n      source_ref: source_ref\n      available_at: available_at\n"
            "      effective_from: effective_from\n      effective_to: effective_to\n"
            "      applicability: applicability\n      incident_ids: incident_ids\n",
            encoding='utf-8')
        server = workbench_module.create_server(self.config_path, 0)
        self.addCleanup(server.server_close)
        self.assertIsInstance(server.app.mes_reference_query, SyntheticMESReferenceReader)

        with closing(sqlite3.connect(db_path)) as db:
            db.execute('INSERT INTO synthetic_refs VALUES (?,?,?,?,?,?,?,?,?,?)', (
                'product', 'SYN-PROD-AUTO-1', 'v1', 'Product Alpha', 'synthetic://auto/product/1',
                '2026-03-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00', None,
                'candidate', json.dumps([self.incident_id])))
            db.commit()
        data = copy.deepcopy(server.app.settings.data)
        data["paths"]["skill_lock_file"] = str((Path(self.temp.name) / "release.lock.json").resolve())
        server.app.settings = Settings(data, server.app.settings.source_files)
        freeze(settings=server.app.settings)
        room_id = server.app.create_room('automatic synthetic MES integration', 'SYN-2026-01')['id']
        workspace = server.app.workspace('SYN-2026-01')
        wafer = workspace['wafers'][0]
        context = {
            'incident_number': 'SYN-2026-01', 'item': 'SYN-TEMP', 'step': 'ETCH',
            'equipment': 'EQP-ETCH-01', 'from': '2026-01-01T00:00:00+00:00',
            'to': '2026-01-31T23:59:59+00:00',
            'wafers': [{'lot_id': wafer['lot_id'], 'wafer_id': wafer['wafer_id']}],
        }
        client = ScriptedClient()
        with patch.object(agent, 'RoleClient', return_value=client):
            result = server.app.analysis(room_id, {
                'content': '선택 사고의 Product Alpha 기준정보를 확인해줘',
                'sources': ['incident', 'mes_reference_search'], 'context': context,
            })
        self.assertEqual([role for role, _ in client.calls], ['router', 'router', 'judge', 'answer'])
        retrieved = result['analysis']['report']['retrieval_evidence']
        self.assertEqual(len(retrieved), 1)
        evidence = retrieved[0]['result']
        self.assertEqual(evidence['status'], 'OK')
        self.assertEqual(evidence['as_of'], '2026-03-31')
        self.assertEqual(evidence['incident_ids'], [self.incident_id])
        self.assertEqual(evidence['items'][0]['record_id'], 'SYN-PROD-AUTO-1')
        self.assertEqual(evidence['items'][0]['scope_relation'], 'current_scope')
        self.assertEqual(evidence['items'][0]['incident_ids'], [self.incident_id])

    def test_cli_run_passes_configured_mes_reader_to_agent(self):
        root = Path(self.temp.name) / 'cli-data'
        root.mkdir()
        with closing(sqlite3.connect(root / 'mes-reference.sqlite')) as db:
            db.execute('CREATE TABLE synthetic_refs (kind, record_id, version, name, source_ref, available_at, effective_from, effective_to, applicability, incident_ids)')
            db.commit()
        overlay = Path(self.temp.name) / 'cli-overlay.yaml'
        overlay.write_text(
            f"environment: demo\npaths:\n  data_root: {root.as_posix()}\n"
            "mes_reference:\n  enabled: true\n  top_k: 10\n  allowed_kinds: [product]\n"
            "  synthetic_sqlite:\n    enabled: true\n    database_file: mes-reference.sqlite\n"
            "    table: synthetic_refs\n    timezone: Asia/Seoul\n    columns:\n"
            "      kind: kind\n      record_id: record_id\n      version: version\n"
            "      name: name\n      source_ref: source_ref\n      available_at: available_at\n"
            "      effective_from: effective_from\n      effective_to: effective_to\n"
            "      applicability: applicability\n      incident_ids: incident_ids\n",
            encoding='utf-8')
        captured = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)
            return {'status': 'answered', 'answer': 'scripted synthetic fixture'}

        argv = ['run_agent.py', '--demo', '--demo-overlay', str(overlay), '--mode', 'run',
                '--question', 'fixture', '--actor', 'test']
        with patch.object(agent, 'run', side_effect=fake_run), patch.object(sys, 'argv', argv):
            with redirect_stdout(StringIO()):
                self.assertEqual(run_agent_module.main(), 0)
        self.assertIsInstance(captured['mes_reference_query'], SyntheticMESReferenceReader)

    def test_document_callback_is_explicit_synthetic_contract_fixture(self):
        callback_calls = []

        def synthetic_document_callback(*, source_kind, actor, incident_ids,
                                        historical_incident_ids, as_of, query, top_k):
            callback_calls.append({"source_kind": source_kind, "actor": actor,
                                   "incident_ids": incident_ids, "as_of": as_of,
                                   "query": query, "top_k": top_k})
            return validate_hybrid_response({
                "status": "OK", "retrieval_method": "bm25_vector_hybrid", "as_of": as_of,
                "items": [{
                    "document_id": "SYN-DOC-1", "chunk_id": "SYN-CHUNK-1", "version": "v1",
                    "text": "Synthetic callback fixture only; no BM25 or vector retrieval occurred.",
                    "source_ref": "synthetic://document/1", "locator": "chunk:1", "status": "active",
                    "available_at": "2026-03-01T00:00:00+09:00", "incident_ids": incident_ids,
                    "relation": "direct", "score": 1.0, "observed_at": None,
                    "effective_from": None, "effective_to": None, "applicability": None,
                }],
            }, source_kind=source_kind, incident_ids=incident_ids, as_of=as_of,
                timezone_name="Asia/Seoul", top_k=top_k,
                historical_incident_ids=historical_incident_ids, allowed_statuses=["active"])

        self.app.document_query = synthetic_document_callback
        self.app.document_allowed_statuses = {"engineer_notes": ["active"]}
        settings_data = merge(self.app.settings.data, {"retrieval": {
            "engineer_notes": {**self.app.settings.data["retrieval"]["engineer_notes"], "enabled": True},
        }})
        self.app.settings = Settings(settings_data, self.app.settings.source_files)
        client = ScriptedClient("search_engineer_notes")
        with patch.object(workbench_module, "run_agent", wraps=agent.run) as run_agent:
            run_agent.side_effect = lambda *args, **kwargs: agent.run(*args, **kwargs)
            with patch.object(agent, "RoleClient", return_value=client):
                result = self.app.analysis(self.room_id, {
                    "content": "선택 사고의 Alpha 엔지니어 노트를 확인해줘",
                    "sources": ["incident", "engineer_note_search"], "context": self.context,
                })

        self.assertEqual(callback_calls[0]["source_kind"], "engineer_notes")
        self.assertEqual(callback_calls[0]["incident_ids"], [self.incident_id])
        self.assertEqual(callback_calls[0]["as_of"], "2026-03-31")
        evidence = result["analysis"]["report"]["retrieval_evidence"][0]["result"]
        self.assertEqual(evidence["retrieval_method"], "bm25_vector_hybrid")
        self.assertEqual(evidence["items"][0]["document_id"], "SYN-DOC-1")
        self.assertIn("historical_candidate_not_current_scope", evidence["limitations"])
        self.assertIn("SYN-DOC-1", json.dumps(client.calls[-1][1]["evidence"], ensure_ascii=False))
        self.assertEqual(result["analysis"]["steps"][-1]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
