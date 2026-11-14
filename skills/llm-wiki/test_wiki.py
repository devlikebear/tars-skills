import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wiki  # noqa: E402


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ParseFrontmatterTests(unittest.TestCase):
    def test_block_list(self):
        text = (
            "---\n"
            "title: Foo\n"
            "sources:\n"
            "  - raw/a.md\n"
            "  - https://example.com\n"
            "---\n"
            "Body with [[Bar]].\n"
        )
        meta, body = wiki.parse_frontmatter(text)
        self.assertEqual(meta["title"], "Foo")
        self.assertEqual(meta["sources"], ["raw/a.md", "https://example.com"])
        self.assertEqual(body, "Body with [[Bar]].\n")

    def test_inline_list(self):
        meta, _ = wiki.parse_frontmatter("---\nsources: [raw/a.md, raw/b.md]\n---\nbody\n")
        self.assertEqual(meta["sources"], ["raw/a.md", "raw/b.md"])

    def test_no_frontmatter(self):
        meta, body = wiki.parse_frontmatter("just a body, no frontmatter\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "just a body, no frontmatter\n")

    def test_missing_sources(self):
        meta, _ = wiki.parse_frontmatter("---\ntitle: Foo\n---\nbody\n")
        self.assertNotIn("sources", meta)


class ExtractLinksTests(unittest.TestCase):
    def test_plain_and_display_links(self):
        body = "See [[Other Page]] and [[Other Page|here]] and [[Third]]."
        self.assertEqual(wiki.extract_links(body), ["Other Page", "Other Page", "Third"])

    def test_ignores_links_inside_html_comments(self):
        body = "<!-- e.g. a line like - [[Page Title]] -->\nReal text with [[Real Page]]."
        self.assertEqual(wiki.extract_links(body), ["Real Page"])


class InitTests(unittest.TestCase):
    def test_creates_expected_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wikiroot"
            rc = wiki.main(["init", str(root)])
            self.assertEqual(rc, 0)
            self.assertTrue((root / "raw").is_dir())
            self.assertTrue((root / "wiki").is_dir())
            self.assertTrue((root / "index.md").is_file())
            self.assertTrue((root / "log.md").is_file())
            self.assertTrue((root / "SCHEMA.md").is_file())

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wikiroot"
            wiki.main(["init", str(root)])
            (root / "index.md").write_text("# Index\n- [[Foo]]\n", encoding="utf-8")
            rc = wiki.main(["init", str(root)])
            self.assertEqual(rc, 0)
            # existing file must not be overwritten
            self.assertEqual((root / "index.md").read_text(encoding="utf-8"), "# Index\n- [[Foo]]\n")


class LintTests(unittest.TestCase):
    def _init(self, tmp):
        root = Path(tmp) / "wikiroot"
        wiki.main(["init", str(root)])
        return root

    def test_freshly_initialized_empty_wiki_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._init(tmp)
            rc = wiki.cmd_lint(argparse_namespace(str(root)))
            self.assertEqual(rc, 0)

    def test_clean_wiki_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._init(tmp)
            write(
                root / "wiki" / "Foo.md",
                "---\ntitle: Foo\nsources:\n  - raw/foo.md\n---\nSee [[Bar]].\n",
            )
            write(
                root / "wiki" / "Bar.md",
                "---\ntitle: Bar\nsources:\n  - raw/bar.md\n---\nSee [[Foo]].\n",
            )
            write(root / "index.md", "# Index\n- [[Foo]]\n- [[Bar]]\n")

            rc = wiki.cmd_lint(argparse_namespace(str(root)))
            self.assertEqual(rc, 0)

    def test_broken_link_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._init(tmp)
            write(
                root / "wiki" / "Foo.md",
                "---\ntitle: Foo\nsources:\n  - raw/foo.md\n---\nSee [[Nope]].\n",
            )
            write(root / "index.md", "# Index\n- [[Foo]]\n")

            rc = wiki.cmd_lint(argparse_namespace(str(root)))
            self.assertEqual(rc, 1)

    def test_orphan_page_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._init(tmp)
            write(
                root / "wiki" / "Foo.md",
                "---\ntitle: Foo\nsources:\n  - raw/foo.md\n---\nNo links here.\n",
            )
            write(root / "index.md", "# Index\n(nothing linked yet)\n")

            rc = wiki.cmd_lint(argparse_namespace(str(root)))
            self.assertEqual(rc, 1)

    def test_page_reachable_via_other_page_but_missing_from_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._init(tmp)
            write(
                root / "wiki" / "Foo.md",
                "---\ntitle: Foo\nsources:\n  - raw/foo.md\n---\nSee [[Bar]].\n",
            )
            write(
                root / "wiki" / "Bar.md",
                "---\ntitle: Bar\nsources:\n  - raw/bar.md\n---\nNo further links.\n",
            )
            # index only lists Foo; Bar is reachable via Foo but not in the TOC
            write(root / "index.md", "# Index\n- [[Foo]]\n")

            rc = wiki.cmd_lint(argparse_namespace(str(root)))
            self.assertEqual(rc, 1)

    def test_missing_sources_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._init(tmp)
            write(root / "wiki" / "Foo.md", "---\ntitle: Foo\n---\nNo sources.\n")
            write(root / "index.md", "# Index\n- [[Foo]]\n")

            rc = wiki.cmd_lint(argparse_namespace(str(root)))
            self.assertEqual(rc, 1)

    def test_self_link_does_not_prevent_orphan_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._init(tmp)
            write(
                root / "wiki" / "Foo.md",
                "---\ntitle: Foo\nsources:\n  - raw/foo.md\n---\nSee [[Foo]] (itself).\n",
            )
            # Foo is not linked from index.md or from any other page - only
            # from itself.
            write(root / "index.md", "# Index\n(nothing linked yet)\n")

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = wiki.cmd_lint(argparse_namespace(str(root)))
            self.assertEqual(rc, 1)

            report_lines = out.getvalue().splitlines()
            orphan_label = next(i for i, l in enumerate(report_lines) if "orphan pages" in l)
            orphan_items = []
            for line in report_lines[orphan_label + 1:]:
                if not line.startswith("  - "):
                    break
                orphan_items.append(line)
            self.assertTrue(
                any("Foo.md" in item for item in orphan_items),
                f"expected Foo.md under the orphan pages section, got: {orphan_items}",
            )


class StatsTests(unittest.TestCase):
    def test_stats_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wikiroot"
            wiki.main(["init", str(root)])
            write(root / "raw" / "a.md", "raw content")
            write(
                root / "wiki" / "Foo.md",
                "---\ntitle: Foo\nsources:\n  - raw/a.md\n---\nSee [[Bar]] and [[Baz]].\n",
            )
            write(root / "log.md", "# Log\n2026-01-01 - created Foo\n")

            rc = wiki.main(["stats", str(root)])
            self.assertEqual(rc, 0)

    def test_fresh_log_template_is_not_counted_as_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wikiroot"
            wiki.main(["init", str(root)])  # log.md only has the boilerplate

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = wiki.main(["stats", str(root)])
            self.assertEqual(rc, 0)
            report = out.getvalue()
            self.assertIn("log entries: 0", report)
            self.assertNotIn("last log entry", report)

    def test_log_entry_count_ignores_boilerplate_even_with_real_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wikiroot"
            wiki.main(["init", str(root)])
            with (root / "log.md").open("a", encoding="utf-8") as f:
                f.write("2026-11-14 - created Foo - testing\n")

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = wiki.main(["stats", str(root)])
            self.assertEqual(rc, 0)
            report = out.getvalue()
            self.assertIn("log entries: 1", report)
            self.assertIn("last log entry: 2026-11-14 - created Foo - testing", report)


def argparse_namespace(directory: str):
    class NS:
        pass

    ns = NS()
    ns.dir = directory
    return ns


if __name__ == "__main__":
    unittest.main()
