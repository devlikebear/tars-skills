#!/usr/bin/env python3
"""Tests for scripts/registry.py: python3 -m unittest scripts/test_registry.py"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import registry  # noqa: E402


def template(**overrides):
    data = {
        "id": "hotfix",
        "name": "Hotfix",
        "stages": [{"id": "plan"}, {"id": "build"}, {"id": "pr"}, {"id": "merge"}],
    }
    data.update(overrides)
    return data


class ValidateTemplateTest(unittest.TestCase):
    def test_valid_template(self):
        self.assertEqual(registry.validate_template(template(), "hotfix"), [])

    def test_mirrors_tars_rules(self):
        cases = {
            "first stage must be plan": template(stages=[{"id": "build"}, {"id": "plan"}]),
            "needs the pr stage": template(stages=[{"id": "plan"}, {"id": "merge"}]),
            "keeps its own id": template(stages=[{"id": "plan"}, {"id": "ship", "kind": "pr"}]),
            "is not one of": template(stages=[{"id": "plan"}, {"id": "x", "kind": "deploy"}]),
            "listed twice": template(stages=[{"id": "plan"}, {"id": "build"}, {"id": "build"}]),
            "<focus-": template(stages=[{"id": "plan"}, {"id": "build", "instructions": "<focus-plan>"}]),
            "does not match the registry name": template(id="other"),
            "name is required": template(name=" "),
        }
        for want, data in cases.items():
            with self.subTest(want=want):
                problems = registry.validate_template(data, "hotfix")
                self.assertTrue(any(want in p for p in problems), problems)


class HelpersTest(unittest.TestCase):
    def test_top_level_scalar_reads_plain_and_quoted_values(self):
        text = "id: hotfix\nname: \"Hot \\\"fix\\\"\"\ndescription: 'it''s quick'\nstages:\n    - id: plan\n"
        self.assertEqual(registry.top_level_scalar(text, "id"), "hotfix")
        self.assertEqual(registry.top_level_scalar(text, "name"), 'Hot "fix"')
        self.assertEqual(registry.top_level_scalar(text, "description"), "it's quick")
        self.assertEqual(registry.top_level_scalar(text, "missing"), "")

    def test_dump_json_keeps_short_lists_inline(self):
        out = registry.dump_json({"tags": ["a", "b"], "files": [{"path": "x"}]})
        self.assertIn('"tags": ["a", "b"]', out)
        self.assertEqual(json.loads(out), {"tags": ["a", "b"], "files": [{"path": "x"}]})

    def test_bump_patch(self):
        self.assertEqual(registry.bump_patch("0.1.9"), "0.1.10")
        self.assertEqual(registry.bump_patch("dev"), "dev")


class MCPManifestTest(unittest.TestCase):
    def test_reports_files_the_manifest_runs_but_the_entry_does_not_ship(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "mcp-servers" / "time"
            pkg.mkdir(parents=True)
            (pkg / "tars.mcp.json").write_text('{"server": {"name": "time", "args": ["${MCP_DIR}/server.cjs"]}}')
            old_root = registry.ROOT
            registry.ROOT = root
            try:
                entry = {"name": "time", "path": "mcp-servers/time"}
                problems = registry.mcp_manifest_problems(entry, [{"path": "tars.mcp.json"}, {"path": "server.js"}])
                self.assertEqual(problems, ["manifest runs 'server.cjs', which is not in files"])
                self.assertEqual(registry.mcp_manifest_problems(entry, [{"path": "server.cjs"}]), [])
            finally:
                registry.ROOT = old_root


if __name__ == "__main__":
    unittest.main()
