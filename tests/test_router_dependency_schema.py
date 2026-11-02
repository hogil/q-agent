"""Router dependency schema regression tests."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from prompt_contracts import structure


class RouterDependencySchemaTests(unittest.TestCase):
    def test_independent_batch_has_empty_dependencies(self):
        schema_path = ROOT / 'app/skills/roles/router/references/output.schema.json'
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        plan_schema = schema['properties']['plan']
        step_schema = plan_schema['items']
        dependency_schema = step_schema['properties']['depends_on']

        self.assertEqual(dependency_schema['maxItems'], 0)
        structure([
            {'tool': 'tool_a', 'arguments': {}, 'depends_on': [], 'reason': 'independent A'},
            {'tool': 'tool_b', 'arguments': {}, 'depends_on': [], 'reason': 'independent B'},
        ], plan_schema)

    def test_first_step_dependency_is_rejected_by_schema(self):
        schema_path = ROOT / 'app/skills/roles/router/references/output.schema.json'
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        plan_schema = schema['properties']['plan']

        invalid_plans = (
            ([
                {'tool': 'tool_a', 'arguments': {}, 'depends_on': [0], 'reason': 'invalid self dependency'},
                {'tool': 'tool_b', 'arguments': {}, 'depends_on': [], 'reason': 'independent B'},
            ], r'MAXITEMS: \$\[0\]\.depends_on'),
            ([
                {'tool': 'tool_a', 'arguments': {}, 'depends_on': [], 'reason': 'independent A'},
                {'tool': 'tool_b', 'arguments': {}, 'depends_on': [0], 'reason': 'earlier dependency is not independent'},
            ], r'MAXITEMS: \$\[1\]\.depends_on'),
        )
        for plan, error in invalid_plans:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                structure(plan, plan_schema)


if __name__ == '__main__':
    unittest.main()
