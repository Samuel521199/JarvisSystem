"""Check navigation drift and ownership failures using temporary documents."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.sync_doc_navigation import build, validate


class BookNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "docs/nested").mkdir(parents=True)
        self.chapter = self.root / "docs/nested/topic.md"
        self.chapter.write_text(
            '# Topic\n\n<!-- book-nav:start -->\n<!-- book-nav:end -->\n\n'
            '<a id="stable-section"></a>\n## Section\n\nEvidence stays here.\n\n'
            '```markdown\n### This is an example, not a section\n```\n\n'
            '<!-- book-footer:start -->\n<!-- book-footer:end -->\n', encoding="utf-8")
        (self.root / "docs/README.md").write_text(
            '# Index\n\n<!-- book-tree:start -->\n<!-- book-tree:end -->\n', encoding="utf-8")
        self.manifest = {
            "documents": [{"id": "topic", "path": "docs/nested/topic.md", "title": "Topic", "reader_summary": "Find the topic details."}],
            "book": {"parts": [{"id": "part-test", "title": "Test", "chapters": ["topic"]}]},
        }
        self.save_manifest()

    def save_manifest(self):
        (self.root / "docs/manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def synchronize(self):
        for path, text in build(self.root).items():
            path.write_text(text, encoding="utf-8")

    def test_nested_links_and_idempotence_preserve_body(self):
        original = self.chapter.read_text(encoding="utf-8")
        self.synchronize()
        text = self.chapter.read_text(encoding="utf-8")
        self.assertIn('(../README.md#book-tree)', text)
        body = original.split('<a id="stable-section">')[1].split('<!-- book-footer:start -->')[0]
        self.assertIn(body, text)
        self.assertEqual(validate(self.root), [])
        self.assertEqual(build(self.root)[self.chapter], text)

    def test_renamed_heading_detects_stale_navigation_and_keeps_anchor(self):
        self.synchronize()
        self.chapter.write_text(self.chapter.read_text(encoding="utf-8").replace('## Section', '## Renamed'), encoding="utf-8")
        self.assertTrue(any('Stale' in error for error in validate(self.root)))
        self.synchronize()
        self.assertIn('[1.1 Renamed](#stable-section)', self.chapter.read_text(encoding="utf-8"))

    def test_duplicate_or_missing_chapter_fails(self):
        for chapters in (["topic", "topic"], []):
            with self.subTest(chapters=chapters):
                self.manifest['book']['parts'][0]['chapters'] = chapters
                self.save_manifest()
                self.assertTrue(any('exactly one' in error for error in validate(self.root)))

    def test_missing_anchor_or_skipped_level_fails(self):
        original = self.chapter.read_text(encoding="utf-8")
        for modified, message in (
            (original.replace('<a id="stable-section"></a>\n', ''), 'stable anchor'),
            (original.replace('## Section', '#### Section'), 'Skipped heading'),
            (original.replace('Evidence stays here.', '# Another title'), 'exactly one H1'),
        ):
            with self.subTest(message=message):
                self.chapter.write_text(modified, encoding="utf-8")
                self.assertTrue(any(message in error for error in validate(self.root)))


if __name__ == '__main__':
    unittest.main()
