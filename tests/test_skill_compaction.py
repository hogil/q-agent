"""Lossless prompt schema encoding and the combined image workflow budget."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from config_loader import load_config
from skill_loader import compact_schema, compile_prompt


class SkillCompactionTests(unittest.TestCase):
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
        settings = load_config(ROOT / 'config/config.yaml', ROOT / 'config/demo.yaml')
        settings.data['runtime']['prompt_examples'] = True
        limit = json.loads((ROOT / 'app/skill_registry.json').read_text(encoding='utf-8'))['max_prompt_characters']
        for role in ('router', 'judge', 'answer'):
            prompt = compile_prompt(role, ['incident_search', 'lots', 'wafers', 'images', 'meetings'], settings=settings)
            self.assertLessEqual(len(prompt['system_prompt']), limit, role)
            self.assertIn('column_fields', prompt['system_prompt'])
            self.assertTrue(any('image-metadata-schema' in value for value in prompt['loaded_files']))


if __name__ == '__main__':
    unittest.main()
