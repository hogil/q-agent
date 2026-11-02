"""Synthetic acquired_at cutoff checks for the configured runtime timezone."""
import unittest

import test_image_tools as image_fixtures
from incident_tools import ToolError


class ImageTimeZoneBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image_fixtures.ImageToolsTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        image_fixtures.ImageToolsTests.tearDownClass()

    def setUp(self):
        self.fixture = image_fixtures.ImageToolsTests()
        self.fixture.setUp()

    def _tool(self, timezone="Asia/Seoul"):
        return image_fixtures.ImageTools(self.fixture.settings(
            runtime={"max_page_size": 2, "timezone": timezone}), self.fixture.incidents)

    def _assets(self, modality, acquired_at):
        return [
            image_fixtures._asset("A1", modality=modality, acquired_at=acquired_at),
            image_fixtures._asset("A2", wafer_id="W2", revision="r2",
                                  modality=modality, acquired_at=acquired_at),
        ]

    def _list(self, tool, modality, as_of="2026-03-01"):
        return tool.list_comparison_assets("actor", "scope", "ITEM-A", modality, as_of)

    def test_seoul_cutoff_converts_timestamp_before_comparing_date_for_both_modalities(self):
        cases = (
            # UTC March 1, but March 2 in Seoul: reject.
            ("2026-03-01T17:00:00+00:00", False),
            # March 2 in +14, but March 1 in Seoul: allow.
            ("2026-03-02T00:30:00+14:00", True),
            # Last instant of the cutoff date in Seoul: allow.
            ("2026-03-01T23:59:59+09:00", True),
            # Following local midnight: reject.
            ("2026-03-02T00:00:00+09:00", False),
        )
        for modality in ("sem", "overlay"):
            for acquired_at, allowed in cases:
                with self.subTest(modality=modality, acquired_at=acquired_at):
                    self.fixture.incidents.scope_calls.clear()
                    image_fixtures._ImageHandler.assets = self._assets(modality, acquired_at)
                    tool = self._tool()
                    if allowed:
                        result = self._list(tool, modality)
                        self.assertEqual([row["asset_id"] for row in result["assets"]], ["A1", "A2"])
                    else:
                        with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_ASSET"):
                            self._list(tool, modality)
                    self.assertEqual(self.fixture.incidents.scope_calls, [("actor", "scope")])
                    self.assertEqual(image_fixtures._ImageHandler.requests[0][2]["incident_ids"], ["I1"])

    def test_other_runtime_timezone_controls_cutoff_and_scope_configuration_survives(self):
        image_fixtures._ImageHandler.assets = self._assets("sem", "2026-03-01T17:00:00+00:00")
        tool = self._tool("America/Los_Angeles")
        # The same instant is March 1 in Los Angeles, so it is within the cutoff.
        result = self._list(tool, "sem")
        self.assertEqual(len(result["assets"]), 2)
        self.assertEqual(tool.page_size, 2)
        self.assertEqual(tool.config["sem"]["served_model"], "sem-model")
        self.assertEqual(self.fixture.incidents.scope_calls, [("actor", "scope")])

    def test_malformed_naive_or_invalid_timezone_timestamps_fail_closed(self):
        invalid = (
            "not-a-timestamp",
            "2026-03-01T12:00:00",
            "2026-03-01T12:00:00+99:99",
            "",
        )
        for modality in ("sem", "overlay"):
            for acquired_at in invalid:
                with self.subTest(modality=modality, acquired_at=acquired_at):
                    image_fixtures._ImageHandler.assets = self._assets(modality, acquired_at)
                    with self.assertRaisesRegex(ToolError, "INVALID_IMAGE_ASSET"):
                        self._list(self._tool(), modality)

    def test_missing_or_invalid_runtime_timezone_fails_closed(self):
        for timezone in (None, "Mars/Olympus_Mons", ""):
            with self.subTest(timezone=timezone):
                image_fixtures._ImageHandler.assets = self._assets("sem", "2026-03-01T12:00:00+09:00")
                tool = self._tool(timezone)
                with self.assertRaisesRegex(ToolError, "INVALID_RUNTIME_TIMEZONE"):
                    self._list(tool, "sem")


if __name__ == "__main__":
    unittest.main()
