import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from prompt_contracts import structure


def mes_filters_schema():
    tools = json.loads((ROOT / 'app/skills/roles/router/references/tools.json').read_text(encoding='utf-8'))
    return tools['search_mes_reference']['parameters']['properties']['filters']


def test_actual_mes_filters_schema_accepts_one_to_five_ascii_conditions():
    schema = mes_filters_schema()
    structure({'Wafer_ID': 'W123'}, schema)
    structure({f'field_{i}': f'value_{i}' for i in range(5)}, schema)


@pytest.mark.parametrize('filters,code', [
    ({}, 'MINPROPERTIES'),
    ({f'field_{i}': 'x' for i in range(6)}, 'MAXPROPERTIES'),
    ({'1field': 'x'}, 'PATTERN'),
    ({'필드': 'x'}, 'PATTERN'),
    ({'field': ''}, 'MINLENGTH'),
    ({'field': 'x' * 129}, 'MAXLENGTH'),
    ({'field': 7}, 'TYPE'),
])
def test_actual_mes_filters_schema_rejects_invalid_conditions(filters, code):
    with pytest.raises(ValueError, match=code):
        structure(filters, mes_filters_schema())


def test_json_schema_pattern_search_and_property_names_are_applied_to_keys():
    structure({'prefix_A9_suffix': 'ok'}, {
        'type': 'object',
        'propertyNames': {'type': 'string', 'pattern': '[A-Z][0-9]'},
        'additionalProperties': {'type': 'string'},
    })
    with pytest.raises(ValueError, match='PATTERN'):
        structure({'bad key': 'ok'}, mes_filters_schema())


def test_additional_properties_schema_only_checks_unlisted_properties():
    structure({'known': 3, 'other': 'ok'}, {
        'type': 'object',
        'properties': {'known': {'type': 'integer'}},
        'additionalProperties': {'type': 'string'},
    })
    with pytest.raises(ValueError, match='TYPE'):
        structure({'known': 3, 'other': 4}, {
            'type': 'object',
            'properties': {'known': {'type': 'integer'}},
            'additionalProperties': {'type': 'string'},
        })


def test_unknown_schema_keyword_still_fails_closed():
    with pytest.raises(ValueError, match='UNSUPPORTED_SCHEMA_KEYWORD'):
        structure({'x': 'y'}, {'type': 'object', 'unevaluatedProperties': False})
