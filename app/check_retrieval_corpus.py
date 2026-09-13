"""Run the authored query corpus against a fresh, isolated synthetic database."""
import json
import time
import unittest
from pathlib import Path

from check_config import ConfigTests
from config_loader import read_toml
from generate_dummy import generate
from variant_query_demo import run_cases


class RetrievalCorpusTests(unittest.TestCase):
    setUp = ConfigTests.setUp
    settings = ConfigTests.settings

    def test_full_synthetic_corpus(self):
        overlay = read_toml(Path(__file__).resolve().parents[1] / 'config/demo.variants.toml')
        # Keep experiment data inside the test's temporary directory.
        overlay['paths'].pop('data_root')
        overlay['paths'].pop('output_root')
        settings = self.settings(overlay)
        started = time.perf_counter()
        generated = generate(settings)
        report = run_cases(settings)
        elapsed = time.perf_counter() - started
        print(json.dumps({
            'notice': 'Synthetic finite-grammar retrieval, not LLM or production validation.',
            'counts': generated['counts'], 'queries': report['total'],
            'passed': report['passed'], 'failed': report['failed'],
            'elapsed_seconds': round(elapsed, 3),
        }))
        self.assertGreater(report['total'], 0)
        self.assertEqual(report['failed'], 0,
                         [r for r in report['results'] if not r['passed']])


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RetrievalCorpusTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
