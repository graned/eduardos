"""Guard against stale Forge installation-preview drafts.

Static assertions complement browser navigation testing; no disk commands run.
"""
from pathlib import Path
import unittest

SCRIPT = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text()


class ForgeDraftInvalidationTests(unittest.TestCase):
    def test_draft_revision_tracks_async_validation(self):
        self.assertIn("let draftRevision = 0", SCRIPT)
        self.assertIn("draftRevision !== revision", SCRIPT)
        self.assertIn("function invalidateDraft()", SCRIPT)

    def test_edits_and_disk_switch_invalidate_review(self):
        self.assertIn('addEventListener("input", invalidateDraft)', SCRIPT)
        self.assertIn("if (selected !== disk.by_id) invalidateDraft()", SCRIPT)
        self.assertIn('$("validated-config").replaceChildren()', SCRIPT)

    def test_review_stays_preview_only(self):
        self.assertIn('plan.mode === "dry-run-only"', SCRIPT)
        self.assertIn("plan.would_write_to_disk === false", SCRIPT)
        self.assertNotIn('fetch("/api/install"', SCRIPT)


if __name__ == "__main__":
    unittest.main()
