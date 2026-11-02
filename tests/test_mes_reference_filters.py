import sqlite3
import gc
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from app.config_loader import ConfigError, SPEC, check_shape, merge, read_config, validate_values
from mes_reference_sqlite import SyntheticMESReferenceReader


class MESReferenceFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.sqlite"
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""CREATE TABLE refs (
                kind, record_id, version, name, source_ref, available_at,
                effective_from, effective_to, applicability, incident_ids,
                product_code, process_name, equipment_id
            )""")
            self._insert(db, "p1", "P-1", "ETCH", "EQ-1", ' ["I-1"] ')
            self._insert(db, "p2", "P-1", "ETCH", "EQ-2", '["I-2"]')
            self._insert(db, "p3", "P-1", "LITHO", "EQ-1", '["I-1"]')
            self._insert(db, "future", "P-1", "ETCH", "EQ-1", '["I-1"]',
                         "2026-10-30T00:00:00+09:00")
            db.commit()
        self.mapping = {"table": "refs", "columns": {key: key for key in (
            "kind", "record_id", "version", "name", "source_ref", "available_at",
            "effective_from", "effective_to", "applicability", "incident_ids")}}
        self.filters = {"product": "product_code", "process": "process_name", "equipment": "equipment_id"}
        self.reader = SyntheticMESReferenceReader(
            self.path, self.mapping, timezone_name="Asia/Seoul", allowed_kinds={"product"},
            filter_columns=self.filters)

    def tearDown(self):
        self.reader = None
        gc.collect()

    @staticmethod
    def _insert(db, record_id, product, process, equipment, ids,
                available="2026-10-28T10:00:00+09:00"):
        db.execute("INSERT INTO refs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "product", record_id, "v1", "Alpha", "synthetic://" + record_id, available,
            "2026-01-01", None, "candidate", ids, product, process, equipment))

    def _query(self, **kwargs):
        return self.reader(actor="demo", incident_ids=["I-1"], as_of="2026-10-29",
                           kind="product", query="Alpha", top_k=10, **kwargs)

    def test_exact_match_filters_are_combined_and_scoped_and_cut_off(self):
        result = self._query(filters={"product": "P-1", "process": "ETCH", "equipment": "EQ-1"})
        self.assertEqual([row["record_id"] for row in result["items"]], ["p1"])
        self.assertEqual(result["items"][0]["scope_relation"], "current_scope")
        self.assertNotIn("future", [row["record_id"] for row in result["items"]])

    def test_filter_values_are_parameters_and_legacy_no_filter_still_works(self):
        injected = self._query(filters={"product": "P-1' OR 1=1 --"})
        self.assertEqual(injected["status"], "NO_MATCH")
        legacy = self._query()
        self.assertEqual([row["record_id"] for row in legacy["items"]], ["p1", "p2", "p3"])

    def test_invalid_filter_requests_fail_closed(self):
        for filters in ({}, {"unknown": "x"}, {"product": " "}, {"product": "x" * 129}, [], "x"):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self._query(filters=filters)

    def test_filter_mapper_validation(self):
        for mapper in (
            {"bad-key": "product_code"}, {"x" * 65: "product_code"},
            {"product": "product_code; DROP TABLE refs"},
            {str(i): "product_code" for i in range(33)},
        ):
            with self.subTest(mapper=mapper), self.assertRaises(ValueError):
                SyntheticMESReferenceReader(self.path, self.mapping, timezone_name="Asia/Seoul",
                    allowed_kinds={"product"}, filter_columns=mapper)

    def test_config_filter_mapper_validation(self):
        base = read_config(Path(__file__).resolve().parents[1] / "config" / "config.yaml")
        options = base["mes_reference"]["synthetic_sqlite"]
        for mapper in ({"bad-key": "product_code"}, {"product": "product_code;DROP"},
                       {str(i): "column" for i in range(33)}):
            data = merge(base, {"mes_reference": {"enabled": True, "allowed_kinds": ["product"],
                "synthetic_sqlite": {**options, "enabled": True, "database_file": "refs.sqlite",
                                     "filter_columns": mapper}}})
            with self.subTest(mapper=mapper), self.assertRaises(ConfigError):
                check_shape(data, SPEC)
                validate_values(data)

    def test_config_empty_optional_and_valid_filter_mappers(self):
        base = read_config(ROOT / "config" / "config.yaml")
        check_shape(base, SPEC)  # Explicit default empty mapping is allowed.
        omitted = merge(base, {})
        del omitted["mes_reference"]["synthetic_sqlite"]["filter_columns"]
        check_shape(omitted, SPEC)  # The optional mapping can also be absent.
        valid = merge(base, {"mes_reference": {"synthetic_sqlite": {
            "filter_columns": {"ProductCode": "product_code"}}}})
        check_shape(valid, SPEC)
        validate_values(valid)
        for invalid in (None, [], "product_code"):
            malformed = merge(base, {"mes_reference": {"synthetic_sqlite": {
                "filter_columns": invalid}}})
            with self.subTest(invalid=invalid), self.assertRaises(ConfigError):
                check_shape(malformed, SPEC)

    def test_other_wildcard_mappings_still_reject_empty_tables(self):
        base = read_config(ROOT / "config" / "config.yaml")
        base["models"] = {}
        with self.assertRaisesRegex(ConfigError, "empty table"):
            check_shape(base, SPEC)


if __name__ == "__main__":
    unittest.main()
