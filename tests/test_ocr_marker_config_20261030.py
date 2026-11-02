"""Config compatibility and validation for document OCR marker policy."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))

from config_loader import ConfigError, DEFAULT_CONFIG, load_config, read_config


class OcrMarkerConfigTests(unittest.TestCase):
    def test_default_sources_disable_content_kind_requirement(self):
        retrieval = load_config(DEFAULT_CONFIG).data['retrieval']
        self.assertFalse(retrieval['internal_documents']['require_content_kind'])
        self.assertFalse(retrieval['engineer_notes']['require_content_kind'])

    def test_legacy_config_missing_field_defaults_false(self):
        data = read_config(DEFAULT_CONFIG)
        for source in data['retrieval'].values():
            source.pop('require_content_kind')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.yaml'
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
            retrieval = load_config(path).data['retrieval']
        self.assertFalse(retrieval['internal_documents']['require_content_kind'])
        self.assertFalse(retrieval['engineer_notes']['require_content_kind'])

    def test_overlay_sets_policy_independently_per_source(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / 'site.yaml'
            overlay.write_text(
                'retrieval:\n  internal_documents:\n    require_content_kind: true\n'
                '  engineer_notes:\n    require_content_kind: false\n',
                encoding='utf-8',
            )
            retrieval = load_config(DEFAULT_CONFIG, overlay).data['retrieval']
        self.assertIs(retrieval['internal_documents']['require_content_kind'], True)
        self.assertIs(retrieval['engineer_notes']['require_content_kind'], False)

    def test_rejects_non_boolean_policy_values(self):
        for invalid in ('true', 0, 1):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                overlay = Path(directory) / 'site.yaml'
                overlay.write_text(
                    'retrieval:\n  internal_documents:\n    require_content_kind: '
                    + yaml.safe_dump(invalid).strip() + '\n',
                    encoding='utf-8',
                )
                with self.assertRaises(ConfigError):
                    load_config(DEFAULT_CONFIG, overlay)

    def test_rejects_non_mapping_retrieval_source_as_config_error(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / 'site.yaml'
            overlay.write_text('retrieval:\n  internal_documents: invalid\n', encoding='utf-8')
            with self.assertRaises(ConfigError):
                load_config(DEFAULT_CONFIG, overlay)

    def test_rejects_non_mapping_retrieval_as_config_error(self):
        for malformed in ('[]', 'invalid', 'null'):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as directory:
                overlay = Path(directory) / 'site.yaml'
                overlay.write_text(f'retrieval: {malformed}\n', encoding='utf-8')
                with self.assertRaises(ConfigError):
                    load_config(DEFAULT_CONFIG, overlay)


if __name__ == '__main__':
    unittest.main()
