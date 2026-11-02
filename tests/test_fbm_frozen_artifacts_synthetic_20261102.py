import hashlib
import unittest

from research.fbm_frozen_artifacts_synthetic_20261102 import (
    Artifact,
    ArtifactValidationError,
    validate_frozen_artifacts,
)


class FrozenArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = "2026-11-02T12:00:00Z"
        self.artifacts = {
            role: Artifact(f"id-{role}", f"{role}-bytes".encode(), "2026-11-02T11:59:00Z")
            for role in ("encoder", "checkpoint", "preprocessing", "code")
        }
        self.manifest = {
            role: hashlib.sha256(artifact.content).hexdigest()
            for role, artifact in self.artifacts.items()
        }

    def test_accepts_matching_bytes_created_before_cutoff(self):
        report = validate_frozen_artifacts(self.artifacts, self.manifest, self.cutoff)
        self.assertTrue(report.valid)
        self.assertEqual(report.verified_artifact_ids, tuple(f"id-{r}" for r in self.artifacts))
        self.assertIn("does not prove freeze-before-evaluation", report.scope)

    def test_rejects_changed_bytes(self):
        changed = dict(self.artifacts)
        changed["encoder"] = Artifact("id-encoder", b"changed", "2026-11-02T11:59:00Z")
        with self.assertRaisesRegex(ArtifactValidationError, "SHA-256 mismatch"):
            validate_frozen_artifacts(changed, self.manifest, self.cutoff)

    def test_rejects_missing_artifact(self):
        missing = dict(self.artifacts)
        del missing["code"]
        with self.assertRaisesRegex(ArtifactValidationError, "all and only"):
            validate_frozen_artifacts(missing, self.manifest, self.cutoff)

    def test_rejects_artifact_created_after_cutoff(self):
        future = dict(self.artifacts)
        original = future["checkpoint"]
        future["checkpoint"] = Artifact(original.artifact_id, original.content, "2026-11-02T12:00:00.000001Z")
        with self.assertRaisesRegex(ArtifactValidationError, "after cutoff"):
            validate_frozen_artifacts(future, self.manifest, self.cutoff)

    def test_rejects_duplicate_ids_and_naive_timestamps(self):
        duplicate = dict(self.artifacts)
        a = duplicate["encoder"]
        duplicate["checkpoint"] = Artifact(a.artifact_id, duplicate["checkpoint"].content, "2026-11-02T11:59:00Z")
        with self.assertRaisesRegex(ArtifactValidationError, "unique"):
            validate_frozen_artifacts(duplicate, self.manifest, self.cutoff)

        naive = dict(self.artifacts)
        a = naive["encoder"]
        naive["encoder"] = Artifact(a.artifact_id, a.content, "2026-11-02T11:59:00")
        with self.assertRaisesRegex(ArtifactValidationError, "timezone"):
            validate_frozen_artifacts(naive, self.manifest, self.cutoff)

    def test_rejects_noncanonical_cutoff(self):
        with self.assertRaisesRegex(ArtifactValidationError, "ending in Z"):
            validate_frozen_artifacts(self.artifacts, self.manifest, "2026-11-02T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
