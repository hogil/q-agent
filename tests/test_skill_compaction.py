"""Lossless prompt schema encoding and the combined image workflow budget."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from config_loader import load_config
from skill_loader import compact_schema, compile_prompt, freeze


class SkillCompactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = load_config(ROOT / 'config/config.yaml', ROOT / 'config/demo.yaml')
        self.settings.data['paths']['skill_lock_file'] = str(Path(self.temp.name) / 'release.lock.json')
        freeze(settings=self.settings)

    def test_statistics_contract_is_loaded_only_for_statistics_topic(self):
        plain = compile_prompt('router', ['incident_search'], settings=self.settings)
        statistics = compile_prompt('router', ['incident_search', 'statistics'], settings=self.settings)
        self.assertFalse(any('rules/statistics' in path for path in plain['loaded_files']))
        self.assertTrue(any('rules/statistics' in path for path in statistics['loaded_files']))
        self.assertIn('comparison_period', statistics['system_prompt'])
        self.assertNotIn('comparison_period', plain['system_prompt'])

    def test_all_schema_values_round_trip_without_changing_source(self):
        count = 0
        for path in (ROOT / 'app/skills/schema').rglob('*.json'):
            original = json.loads(path.read_text(encoding='utf-8'))
            if 'logical_entity' not in original:
                continue
            before = json.dumps(original)
            compact = compact_schema(original)
            fields = compact['column_fields']
            decoded = {key: value for key, value in compact.items() if key != 'column_fields'}
            decoded['columns'] = {name: dict(zip(fields, values, strict=True))
                                  for name, values in compact['columns'].items()}
            self.assertEqual(decoded, original, path)
            self.assertEqual(json.dumps(original), before)
            self.assertLess(len(json.dumps(compact)), len(before))
            count += 1
        self.assertEqual(count, 7)

    def test_nonuniform_column_fields_remain_unmodified(self):
        schema = {'columns': {'a': {'type': 'string'}, 'b': {'description': 'b'}}}
        self.assertEqual(compact_schema(schema), schema)

    def test_combined_image_and_meeting_prompts_fit_with_examples(self):
        self.settings.data['runtime']['prompt_examples'] = True
        limit = json.loads((ROOT / 'app/skill_registry.json').read_text(encoding='utf-8'))['max_prompt_characters']
        for role in ('router', 'judge', 'answer'):
            prompt = compile_prompt(role, ['incident_search', 'lots', 'wafers', 'images', 'meetings'], settings=self.settings)
            self.assertLessEqual(len(prompt['system_prompt']), limit, role)
            self.assertIn('column_fields', prompt['system_prompt'])
            self.assertTrue(any('image-metadata-schema' in value for value in prompt['loaded_files']))

    def test_prompt_retains_contract_grounding_and_registered_topics(self):
        topics = ['incident_search', 'lots', 'wafers', 'images', 'meetings']
        for role in ('router', 'judge', 'answer'):
            prompt = compile_prompt(role, topics, settings=self.settings)
            self.assertIn('column_fields', prompt['system_prompt'])
            self.assertIn('confirmed_cause', prompt['system_prompt'])
            self.assertTrue(any('output.schema.json' in path for path in prompt['loaded_files']))
            self.assertIn('images', prompt['available_topics'])
            self.assertNotIn('get_engineering_snapshot', prompt['available_topics'])

    def test_all_role_allowed_topics_compile_with_examples_and_preserve_contracts(self):
        self.settings.data['runtime']['prompt_examples'] = True
        registry = json.loads((ROOT / 'app/skill_registry.json').read_text(encoding='utf-8'))
        for role in ('router', 'judge', 'answer'):
            topics = registry['role_allowed_topics'][role]
            prompt = compile_prompt(role, topics, settings=self.settings)
            self.assertLessEqual(len(prompt['system_prompt']), 70000, role)
            self.assertEqual(set(prompt['topics']), set(topics))
            for required in ('source', 'as_of', 'scope', '권한'):
                self.assertIn(required, prompt['system_prompt'], (role, required))
            self.assertIn('output.schema.json', '\n'.join(prompt['loaded_files']))
            if role == 'router':
                tools = json.loads((ROOT / 'app/skills/roles/router/references/tools.json').read_text(encoding='utf-8'))
                enabled = [name for name, spec in tools.items() if spec.get('enabled')]
                for name in enabled:
                    self.assertIn('"' + name + '"', prompt['system_prompt'], (role, name))
                self.assertIn('"enabled":true', prompt['system_prompt'])

    def test_prompt_over_70000_characters_fails_explicitly(self):
        self.settings.data['tables']['incident']['columns']['incident_id'] = 'x' * 71000
        freeze(settings=self.settings)
        with self.assertRaisesRegex(ValueError, 'PROMPT_BUDGET_EXCEEDED'):
            compile_prompt('router', ['incident_search'], settings=self.settings)


if __name__ == '__main__':
    unittest.main()
