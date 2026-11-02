import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'app'))
from config_loader import ConfigError, DEFAULT_CONFIG, load_config


class FBMSearchConfigTests(unittest.TestCase):
    def test_default_is_off(self):
        config = load_config(DEFAULT_CONFIG).data
        self.assertEqual(config['fbm_search'], {'enabled': False, 'top_k': 10})

    def test_invalid_enabled_type_and_top_k_are_rejected(self):
        for overlay_text in (
            'fbm_search:\n  enabled: "false"\n  top_k: 10\n',
            'fbm_search:\n  enabled: false\n  top_k: 0\n',
            'fbm_search:\n  enabled: false\n  top_k: 51\n',
        ):
            with self.subTest(overlay=overlay_text), tempfile.TemporaryDirectory() as folder:
                overlay = Path(folder) / 'overlay.yaml'
                overlay.write_text(overlay_text, encoding='utf-8')
                with self.assertRaises(ConfigError):
                    load_config(DEFAULT_CONFIG, overlay)

    def test_site_overlay_merges_search_values(self):
        with tempfile.TemporaryDirectory() as folder:
            overlay = Path(folder) / 'overlay.yaml'
            overlay.write_text('fbm_search:\n  enabled: true\n  top_k: 25\n', encoding='utf-8')
            config = load_config(DEFAULT_CONFIG, overlay).data
        self.assertEqual(config['fbm_search'], {'enabled': True, 'top_k': 25})


if __name__ == '__main__':
    unittest.main()
