"""Behavioral configuration tests, using temporary synthetic databases only."""
import copy
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_loader import ConfigError, DEFAULT_CONFIG, TABLE_FIELDS, load_config
from generate_dummy import generate
from incident_tools import ToolError, ident
from runtime_factory import open_incident_tools
from skill_loader import compile_prompt


def toml_dump(data, prefix=''):
    lines = [f'[{prefix}]'] if prefix else []
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f'{key} = {json.dumps(value, ensure_ascii=False)}')
    for key, value in data.items():
        if isinstance(value, dict):
            lines += ['', toml_dump(value, f'{prefix}.{key}' if prefix else key)]
    return '\n'.join(lines) + '\n'


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'QAGENT_CONFIG': '', 'QAGENT_OVERLAY': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def settings(self, override=None, filename='site.toml'):
        value = {'environment': 'test', 'paths': {'data_root': str(self.root / 'data'),
                 'output_root': str(self.root / 'output')}, 'demo': {'incident_count': 4, 'lots_per_incident': 4}}
        from config_loader import merge
        path = self.root / filename
        path.write_text(toml_dump(merge(value, override or {})), encoding='utf-8')
        return load_config(DEFAULT_CONFIG, path)

    def test_overlay_preserves_unmodified_columns(self):
        s = self.settings({'tables': {'incident': {'name': '품질사고', 'columns': {'title': '사고명'}}}})
        self.assertEqual(s.data['tables']['incident']['columns']['incident_id'], 'accident_pk')
        self.assertEqual(s.mapping()['entities']['incident']['columns']['title'], '사고명')

    def test_paths_ignore_working_directory(self):
        before = load_config().data['paths']
        original = Path.cwd()
        try:
            os.chdir(self.root)
            self.assertEqual(before, load_config().data['paths'])
        finally:
            os.chdir(original)

    def test_derived_paths_follow_changed_root(self):
        s = self.settings()
        self.assertEqual(s.data['paths']['image_root'], str(self.root / 'data/images'))
        self.assertEqual(s.data['database']['sqlite_file'], str(self.root / 'data/quality_demo.sqlite'))

    def test_override_relative_path_uses_base_file(self):
        s = self.settings({'paths': {'model_root': 'relative-models'}})
        self.assertEqual(s.data['paths']['model_root'], str(DEFAULT_CONFIG.parent / 'relative-models'))

    def test_config_selection_precedence(self):
        alternate = self.root / 'alternate.toml'
        alternate.write_text(DEFAULT_CONFIG.read_text().replace('environment = "demo"', 'environment = "test"'))
        with patch.dict(os.environ, {'QAGENT_CONFIG': str(alternate)}):
            self.assertEqual(load_config().data['environment'], 'test')
            self.assertEqual(load_config(DEFAULT_CONFIG).data['environment'], 'demo')

    def test_unknown_key_is_error(self):
        with self.assertRaises(ConfigError): self.settings({'models': {'text': {'checkpont_file': 'wrong.pt'}}})

    def test_wrong_type_is_error(self):
        with self.assertRaises(ConfigError): self.settings({'runtime': {'max_page_size': '100'}})
        with self.assertRaises(ConfigError): self.settings({'runtime': {'max_page_size': True}})

    def test_invalid_page_range(self):
        with self.assertRaises(ConfigError): self.settings({'runtime': {'default_page_size': 101}})

    def test_unknown_model_reference(self):
        with self.assertRaises(ConfigError): self.settings({'roles': {'router': {'model': 'missing'}}})

    def test_model_folder_filename_and_served_name_are_distinct(self):
        s = self.settings({'models': {'text': {'local_dir': str(self.root / 'new-model'),
                          'checkpoint_file': 'changed.gguf', 'served_model': 'router-serving-name'}}})
        profile = s.model_profile('router')['deployment']
        self.assertEqual(profile['checkpoint_path'], str(self.root / 'new-model/changed.gguf'))
        self.assertEqual(profile['served_model'], 'router-serving-name')

    def test_add_named_model_and_switch_role(self):
        model = copy.deepcopy(load_config().data['models']['text'])
        model['served_model'] = 'fast-model'
        s = self.settings({'models': {'fast': model}, 'roles': {'router': {'model': 'fast'}}})
        self.assertEqual(s.model_profile('router')['deployment']['served_model'], 'fast-model')

    def test_checkpoint_cannot_escape_model_folder(self):
        for name in ('../model.pt', '/model.pt', 'D:\\model.pt'):
            with self.assertRaises(ConfigError): self.settings({'models': {'image': {'checkpoint_file': name}}})

    def test_missing_enabled_local_checkpoint(self):
        s = self.settings({'models': {'image': {'enabled': True, 'local_dir': str(self.root)}}})
        with self.assertRaisesRegex(ConfigError, 'file missing'): s.check_paths()

    def test_cycles_and_unknown_path_references(self):
        with self.assertRaises(ConfigError): self.settings({'paths': {'data_root': '${paths.image_root}'}})
        with self.assertRaises(ConfigError): self.settings({'paths': {'data_root': '${paths.absent}'}})

    def test_no_inline_secrets_or_credential_urls(self):
        with self.assertRaises(ConfigError): self.settings({'database': {'password': 'secret-value'}})
        with self.assertRaises(ConfigError): self.settings({'models': {'text': {'base_url': 'http://user:secret@localhost/v1'}}})

    def test_environment_secret_value_is_not_loaded(self):
        with patch.dict(os.environ, {'QAGENT_LLM_API_KEY': 'DO_NOT_PRINT_SECRET'}):
            s = self.settings()
            self.assertNotIn('DO_NOT_PRINT_SECRET', json.dumps(s.data))

    def test_existing_hybrid_rag_contract_preserved(self):
        with self.assertRaises(ConfigError): self.settings({'retrieval': {'engineer_notes': {'existing_chunks': False}}})
        with self.assertRaises(ConfigError): self.settings({'retrieval': {'engineer_notes': {'enabled': True}}})

    def test_sql_identifiers_reject_injection(self):
        with self.assertRaises(ConfigError): self.settings({'tables': {'incident': {'name': 'x; DROP TABLE y'}}})

    def test_duplicate_physical_columns_rejected(self):
        with self.assertRaises(ConfigError): self.settings({'tables': {'incident': {'columns': {'title': 'accident_pk'}}}})

    def test_non_sqlite_does_not_fall_back(self):
        s = self.settings({'database': {'dialect': 'postgresql'}, 'arrays': {'product_generations': 'native_array'}})
        with self.assertRaisesRegex(ConfigError, 'NOT_IMPLEMENTED'):
            with open_incident_tools(s): pass

    def test_config_load_has_no_filesystem_side_effects(self):
        s = self.settings()
        self.assertFalse(Path(s.data['paths']['data_root']).exists())

    def test_read_only_database_and_scope_expiry(self):
        s = self.settings()
        generate(s)
        with open_incident_tools(s) as tool:
            with self.assertRaises(sqlite3.OperationalError): tool.db.execute('CREATE TABLE forbidden (id TEXT)')
            found = tool.find_incidents('test', incident_number='SYN-2026-0001')
            tool.scopes[found['scope_id']]['expires_at'] = 0
            with self.assertRaises(ToolError): tool.list_incident_lots('test', found['scope_id'])

    def test_full_table_column_and_directory_rename_same_result(self):
        original = self.settings({'runtime': {'default_page_size': 2}})
        generate(original)
        tables = {name: {'name': '사내테이블_' + str(n), 'columns': {key: '컬럼_' + str(i)
                  for i, key in enumerate(table['columns'])}} for n, (name, table) in enumerate(original.data['tables'].items())}
        renamed = self.settings({'paths': {'data_root': str(self.root / 'renamed-data'), 'output_root': str(self.root / 'renamed-output')},
                                 'tables': tables, 'runtime': {'default_page_size': 2}}, 'renamed.toml')
        generate(renamed)
        results = []
        for settings in (original, renamed):
            with open_incident_tools(settings) as tool:
                found = tool.find_incidents('test', incident_number='SYN-2026-0001')
                first = tool.list_incident_lots('test', found['scope_id'])
                second = tool.list_incident_lots('test', found['scope_id'], offset=first['next_offset'])
                self.assertEqual(len(first['items']), 2)
                self.assertIsNone(second['next_offset'])
                results.append((found['data'], first['items'] + second['items']))
        self.assertEqual(results[0], results[1])

    def test_display_number_join(self):
        s = self.settings({'relations': {'incident_parent_key': 'incident_number'}})
        generate(s)
        with open_incident_tools(s) as tool:
            found = tool.find_incidents('test', incident_number='SYN-2026-0001')
            self.assertEqual(tool.list_incident_lots('test', found['scope_id'])['total_memberships'], 4)

    def test_connected_fixture_counts_and_no_orphans(self):
        s = self.settings()
        result = generate(s)
        self.assertEqual(result['counts'], {'incident': 4, 'lot_list': 16, 'incident_document': 12,
                                          'document_chunk': 36, 'image_metadata': 8, 'trend_metadata': 4})
        self.assertEqual(result['unique_lots'], 14)
        with sqlite3.connect(s.data['database']['sqlite_file']) as db:
            tables = s.data['tables']
            parent = tables['incident'];pkey = ident(parent['columns']['incident_id'])
            for name in ('lot_list', 'incident_document', 'image_metadata', 'trend_metadata'):
                child = tables[name];fk = ident(child['columns']['incident_ref'])
                query = f'SELECT COUNT(*) FROM {ident(child["name"])} c LEFT JOIN {ident(parent["name"])} p ON c.{fk}=p.{pkey} WHERE p.{pkey} IS NULL'
                self.assertEqual(db.execute(query).fetchone()[0], 0)
            chunk = tables['document_chunk'];doc = tables['incident_document']
            query = f'SELECT COUNT(*) FROM {ident(chunk["name"])} c LEFT JOIN {ident(doc["name"])} d ON c.{ident(chunk["columns"]["document_ref"])}=d.{ident(doc["columns"]["document_id"])} WHERE d.{ident(doc["columns"]["document_id"])} IS NULL'
            self.assertEqual(db.execute(query).fetchone()[0], 0)
        self.assertTrue(all(Path(f['path']).is_file() for f in result['files']))

    def test_unavailable_optional_columns_not_invented(self):
        s = self.settings({'tables': {'incident': {'columns': {'expected_lot_count': '', 'department': ''}}}})
        generate(s)
        with open_incident_tools(s) as tool:
            found = tool.find_incidents('test', incident_number='SYN-2026-0001')
            self.assertIsNone(found['data'][0]['expected_lot_count'])
            page = tool.list_incident_lots('test', found['scope_id'])
            self.assertEqual(page['status'], 'PARTIAL')
            self.assertIsNone(page['coverage'][0]['expected_lots'])

    def test_dummy_refuses_existing_files_and_onprem(self):
        s = self.settings()
        generate(s)
        with self.assertRaisesRegex(ConfigError, 'OUTPUT_EXISTS'): generate(s)
        with self.assertRaises(ConfigError): generate(self.settings({'environment': 'onprem'}))

    def test_null_and_empty_generation_arrays(self):
        s = self.settings({'demo': {'incident_count': 13}})
        generate(s)
        with sqlite3.connect(s.data['database']['sqlite_file']) as db:
            values = [r[0] for r in db.execute('SELECT product_generations FROM demo_incident')]
        self.assertIsNone(values[10])
        self.assertEqual(json.loads(values[12]), [])

    def test_config_change_keeps_prompt_hash_and_changes_config_hash(self):
        a = self.settings()
        b = self.settings({'models': {'text': {'served_model': 'changed-api-name'}}})
        x, y = (compile_prompt('router', ['lots'], settings=s) for s in (a, b))
        self.assertEqual(x['prompt_sha256'], y['prompt_sha256'])
        self.assertNotEqual(x['config_hash'], y['config_hash'])
        self.assertEqual(y['model_profile']['deployment']['served_model'], 'changed-api-name')

    def test_relocate_skills_and_registry_without_rewriting_prompt(self):
        a = self.settings()
        for source, target in [('skills_root', 'moved-skills'), ('dictionary_root', 'moved-dictionary')]:
            shutil.copytree(a.data['paths'][source], self.root / target)
        shutil.copyfile(a.data['paths']['registry_file'], self.root / 'roles-renamed.json')
        shutil.copyfile(a.data['paths']['skill_lock_file'], self.root / 'release-renamed.json')
        b = self.settings({'paths': {'skills_root': str(self.root/'moved-skills'),
             'dictionary_root': str(self.root/'moved-dictionary'), 'registry_file': str(self.root/'roles-renamed.json'),
             'skill_lock_file': str(self.root/'release-renamed.json')}})
        x = compile_prompt('router', ['lots'], settings=a)
        y = compile_prompt('router', ['lots'], settings=b)
        self.assertEqual(x['prompt_sha256'], y['prompt_sha256'])

    def test_every_configured_column_has_skill_definition(self):
        root = Path(load_config().data['paths']['skills_root'])
        catalogs = {}
        for path in root.glob('*/references/*.json'):
            value = json.loads(path.read_text())
            if 'logical_entity' in value:
                self.assertNotIn(value['logical_entity'], catalogs)
                catalogs[value['logical_entity']] = value['columns']
        self.assertEqual(set(catalogs), set(TABLE_FIELDS))
        for entity, fields in TABLE_FIELDS.items():
            self.assertEqual(set(catalogs[entity]), set(fields))
            for spec in catalogs[entity].values():
                self.assertTrue(spec['description'])
                self.assertTrue(spec['type'])
                self.assertTrue(spec['unit'])
                self.assertTrue(spec['null_meaning'])
                self.assertTrue(spec['allowed_operations'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
