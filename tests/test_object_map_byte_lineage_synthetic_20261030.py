import hashlib
import unittest
from datetime import datetime, timedelta, timezone

from research.object_map_byte_lineage_synthetic_20261030 import (
    ARTIFACTS, validate_synthetic_byte_lineage,
)

T0 = datetime(2026, 10, 30, 1, tzinfo=timezone.utc)


def fixture():
    artifacts = {name: (name + " synthetic bytes").encode() for name in ARTIFACTS}
    entries = {}
    for i, name in enumerate(ARTIFACTS):
        entries[name] = {"artifact_id": name + "-id", "version": "v1",
                         "sha256": hashlib.sha256(artifacts[name]).hexdigest(),
                         "generated_at": T0 + timedelta(minutes=i),
                         "available_at": T0 + timedelta(minutes=i),
                         "synthetic_wafer_key": "wafer-fixture", "source_revision": "rev-fixture",
                         "dependencies": {}}
    entries["predictions"]["generated_at"] = T0 + timedelta(minutes=5)
    entries["predictions"]["available_at"] = T0 + timedelta(minutes=5)
    for parent in ("image", "positions", "checkpoint"):
        entries["predictions"]["dependencies"][parent] = {k: entries[parent][k] for k in ("artifact_id", "version", "sha256")}
    entries["object_map"]["generated_at"] = T0 + timedelta(minutes=6)
    entries["object_map"]["available_at"] = T0 + timedelta(minutes=6)
    for parent in ("positions", "predictions"):
        entries["object_map"]["dependencies"][parent] = {k: entries[parent][k] for k in ("artifact_id", "version", "sha256")}
    return artifacts, {"artifacts": entries}


class ByteLineageTests(unittest.TestCase):
    def check(self, artifacts=None, manifest=None, *, analysis_at=None, cutoff=None, synthetic_fixture_asserted=True):
        a, m = fixture()
        return validate_synthetic_byte_lineage(artifacts or a, manifest or m,
            analysis_at=analysis_at or T0 + timedelta(minutes=10), cutoff=cutoff or T0 + timedelta(minutes=10),
            synthetic_fixture_asserted=synthetic_fixture_asserted)

    def rejected(self, mutate):
        a, m = fixture(); mutate(a, m)
        with self.assertRaisesRegex(ValueError, "validation failed"):
            validate_synthetic_byte_lineage(a, m, analysis_at=T0 + timedelta(minutes=10),
                cutoff=T0 + timedelta(minutes=10), synthetic_fixture_asserted=True)

    def test_valid_and_explicit_limits(self):
        r = self.check()
        self.assertEqual(r["status"], "bytes_match_causality_unverified")
        self.assertEqual(r["basis"], "caller_asserted")
        self.assertIn("not_proof_of_archive_at_asserted_time", r["limitations"])

    def test_requires_per_map_metadata_and_rejects_global_only(self):
        self.rejected(lambda a, m: m.pop("artifacts"))
        self.rejected(lambda a, m: m["artifacts"].pop("object_map"))

    def test_hash_tamper_and_old_map_later_checkpoint_metadata(self):
        self.rejected(lambda a, m: a.__setitem__("object_map", b"tampered"))
        self.rejected(lambda a, m: m["artifacts"]["checkpoint"].update(
            sha256="0" * 64, version="later", artifact_id="later-checkpoint"))

    def test_swapped_wafer_or_revision(self):
        self.rejected(lambda a, m: m["artifacts"]["object_map"].update(synthetic_wafer_key="other"))
        self.rejected(lambda a, m: m["artifacts"]["predictions"].update(source_revision="other"))

    def test_dependency_id_version_or_digest_mismatch(self):
        self.rejected(lambda a, m: m["artifacts"]["object_map"]["dependencies"]["predictions"].update(version="wrong"))

    def test_chronology_cutoff_equality_and_timezone(self):
        self.rejected(lambda a, m: m["artifacts"]["image"].update(available_at=T0 - timedelta(seconds=1)))
        self.rejected(lambda a, m: m["artifacts"]["object_map"].update(available_at=T0 + timedelta(minutes=10)))
        self.rejected(lambda a, m: m["artifacts"]["image"].update(generated_at=datetime(2026, 10, 30)))

    def test_fixture_assertion_and_analysis_after_cutoff(self):
        a, m = fixture()
        result = self.check(a, m, analysis_at=T0 + timedelta(minutes=11), cutoff=T0 + timedelta(minutes=10))
        self.assertEqual(result["status"], "bytes_match_causality_unverified")
        m["artifacts"]["object_map"].update(available_at=T0 + timedelta(minutes=11))
        with self.assertRaisesRegex(ValueError, "validation failed"):
            validate_synthetic_byte_lineage(a, m, analysis_at=T0 + timedelta(minutes=10),
                cutoff=T0 + timedelta(minutes=12), synthetic_fixture_asserted=True)
        with self.assertRaises(ValueError):
            validate_synthetic_byte_lineage(a, m, analysis_at=T0, cutoff=T0,
                synthetic_fixture_asserted=False)

    def test_changed_checkpoint_with_stale_prediction_dependency_rejected(self):
        a, m = fixture()
        a["checkpoint"] = b"new checkpoint bytes"
        m["artifacts"]["checkpoint"].update(
            artifact_id="new-checkpoint-id", version="v2",
            sha256=hashlib.sha256(a["checkpoint"]).hexdigest())
        # Predictions intentionally still names the old checkpoint dependency.
        with self.assertRaisesRegex(ValueError, "validation failed"):
            validate_synthetic_byte_lineage(a, m, analysis_at=T0 + timedelta(minutes=10),
                cutoff=T0 + timedelta(minutes=10), synthetic_fixture_asserted=True)

    def test_caller_rewritten_checkpoint_lineage_passes_but_causality_unverified(self):
        a, m = fixture()
        a["checkpoint"] = b"new checkpoint bytes"
        cp = m["artifacts"]["checkpoint"]
        cp.update(artifact_id="new-checkpoint-id", version="v2",
                  sha256=hashlib.sha256(a["checkpoint"]).hexdigest())
        m["artifacts"]["predictions"]["dependencies"]["checkpoint"] = {
            k: cp[k] for k in ("artifact_id", "version", "sha256")}
        result = self.check(a, m)
        self.assertEqual(result["status"], "bytes_match_causality_unverified")
        self.assertIn("causality_unverified", result["limitations"])

    def test_empty_bytes_and_blank_identity_rejected(self):
        self.rejected(lambda a, m: a.__setitem__("object_map", b""))
        self.rejected(lambda a, m: m["artifacts"]["object_map"].update(artifact_id="  "))
        self.rejected(lambda a, m: m["artifacts"]["object_map"].update(version=" "))

    def test_blank_common_wafer_or_revision_rejected(self):
        self.rejected(lambda a, m: [m["artifacts"][name].update(synthetic_wafer_key="  ")
                                    for name in ("image", "positions", "predictions", "object_map")])
        self.rejected(lambda a, m: [m["artifacts"][name].update(source_revision="  ")
                                    for name in ("image", "positions", "predictions", "object_map")])


if __name__ == "__main__":
    unittest.main()
