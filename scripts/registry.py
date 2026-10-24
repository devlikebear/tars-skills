#!/usr/bin/env python3
"""Maintain registry.json for the TARS Hub.

  python3 scripts/registry.py check
      Fail when a registry entry's files or sha256 checksums do not match the
      repository, or a focus template would not load in TARS. CI runs this.

  python3 scripts/registry.py sync
      Rewrite every entry's `files` from disk: add the package manifest when
      it is missing and recompute each sha256. Run it after editing a package.

  python3 scripts/registry.py add-focus-template <file> [--version X.Y.Z]
                                                 [--author NAME] [--tags a,b]
      Copy a TARS focus template (a file from <workspace>/focus-templates)
      to focus-templates/<id>/template.yaml and add or update its registry
      entry. Changing an existing template bumps its patch version unless
      --version is given.

TARS verifies every downloaded file against these checksums, so an entry
whose files changed without a sync cannot be installed.

Only the standard library is required. Full focus template validation needs
PyYAML (`pip install pyyaml`); without it `check` validates the registry
entries and checksums and says the template structure was not checked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "registry.json"

FOCUS_TEMPLATE_DIR = "focus-templates"
FOCUS_TEMPLATE_MANIFEST = "template.yaml"

# The file TARS requires in each package kind's `files` (internal/skillhub).
MANIFESTS = {
    "skills": lambda entry: "SKILL.md",
    "plugins": lambda entry: "tars.plugin.json",
    "mcp_servers": lambda entry: entry.get("manifest") or "tars.mcp.json",
    "focus_templates": lambda entry: FOCUS_TEMPLATE_MANIFEST,
}

# Mirrors focuspipeline.Template.Validate in TARS.
TEMPLATE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
STAGE_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
STAGE_KINDS = {"plan", "build", "review", "pr", "pr_review", "merge"}
FIXED_KINDS = {"plan", "pr", "pr_review", "merge"}
MAX_STAGES = 12
MAX_INSTRUCTION_BYTES = 4000
MAX_TEMPLATE_BYTES = 64 << 10
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def dump_json(value, indent: int = 0) -> str:
    """JSON with two-space indentation and short scalar lists kept on one
    line, the way registry.json is written by hand."""
    pad = "  " * indent
    inner = "  " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {dump_json(v, indent + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(not isinstance(v, (dict, list)) for v in value):
            one_line = "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
            if len(one_line) + len(pad) <= 100:
                return one_line
        items = [f"{inner}{dump_json(v, indent + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    return json.dumps(value, ensure_ascii=False)


def save_registry(registry: dict) -> None:
    REGISTRY.write_text(dump_json(registry) + "\n", encoding="utf-8")


def file_paths(entry: dict) -> list[str]:
    paths = []
    for item in entry.get("files") or []:
        paths.append(item if isinstance(item, str) else item.get("path", ""))
    return paths


def expected_files(kind: str, entry: dict) -> tuple[list[dict], list[str]]:
    """The `files` list an entry should have, and the problems found."""
    problems = []
    base = ROOT / entry.get("path", "")
    paths = file_paths(entry)
    manifest = MANIFESTS[kind](entry)
    if manifest not in paths:
        paths.insert(0, manifest)
    files = []
    for rel in paths:
        target = (base / rel).resolve()
        if base.resolve() not in target.parents:
            problems.append(f"file {rel!r} leaves the package directory")
            continue
        if not target.is_file():
            problems.append(f"file {rel!r} does not exist at {target.relative_to(ROOT)}")
            continue
        files.append({"path": rel, "sha256": sha256(target)})
    return files, problems


def load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate_template(data, expected_id: str | None = None) -> list[str]:
    if not isinstance(data, dict):
        return ["the template is not a mapping"]
    problems = []
    template_id = str(data.get("id") or "").strip()
    if not TEMPLATE_ID.match(template_id):
        problems.append(f"id {template_id!r} must be lower-case letters, digits, - or _ (at most 32)")
    if expected_id is not None and template_id != expected_id:
        problems.append(f"id {template_id!r} does not match the registry name {expected_id!r}")
    if not str(data.get("name") or "").strip():
        problems.append("name is required")
    stages = data.get("stages") or []
    if not isinstance(stages, list) or len(stages) < 2:
        return problems + ["a template needs the plan stage and at least one more"]
    if len(stages) > MAX_STAGES:
        problems.append(f"at most {MAX_STAGES} stages")
    seen: dict[str, int] = {}
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            problems.append(f"stage {index + 1} is not a mapping")
            continue
        stage_id = str(stage.get("id") or "").strip()
        kind = str(stage.get("kind") or "").strip() or stage_id
        if not STAGE_ID.match(stage_id):
            problems.append(f"stage id {stage_id!r} must be lower-case letters, digits or _ (at most 32)")
        if stage_id in seen:
            problems.append(f"stage {stage_id!r} is listed twice")
        seen[stage_id] = index
        if kind not in STAGE_KINDS:
            problems.append(f"stage {stage_id!r}: kind {kind!r} is not one of {', '.join(sorted(STAGE_KINDS))}")
        if (kind in FIXED_KINDS or stage_id in FIXED_KINDS) and kind != stage_id:
            problems.append(f"stage {stage_id!r}: the {kind} stage keeps its own id and kind")
        for field in ("instructions", "fix_instructions"):
            text = str(stage.get(field) or "")
            if len(text.encode("utf-8")) > MAX_INSTRUCTION_BYTES:
                problems.append(f"stage {stage_id!r}: {field} is longer than {MAX_INSTRUCTION_BYTES} bytes")
            if "<focus-" in text or "</focus-" in text:
                problems.append(f"stage {stage_id!r}: {field} must not contain <focus-…> tags")
    first = stages[0] if isinstance(stages[0], dict) else {}
    if str(first.get("id") or "").strip() != "plan":
        problems.append("the first stage must be plan")
    pr = seen.get("pr")
    for later in ("pr_review", "merge"):
        if later in seen and (pr is None or seen[later] < pr):
            problems.append(f"the {later} stage needs the pr stage before it")
    if "pr_review" in seen and "merge" in seen and seen["merge"] < seen["pr_review"]:
        problems.append("the merge stage comes after pr_review")
    return problems


def mcp_manifest_problems(entry: dict, files: list[dict]) -> list[str]:
    """Files the MCP manifest runs (${MCP_DIR}/…) that the entry does not
    ship: TARS downloads only `files`, so the server could not start."""
    manifest = ROOT / entry.get("path", "") / MANIFESTS["mcp_servers"](entry)
    if not manifest.is_file():
        return []
    shipped = {f["path"] for f in files}
    referenced = set(re.findall(r"\$\{MCP_DIR\}/([^\s\"']+)", manifest.read_text(encoding="utf-8")))
    return [f"manifest runs {ref!r}, which is not in files" for ref in sorted(referenced - shipped)]


def check_entries(registry: dict) -> tuple[list[str], bool]:
    """Every problem in the registry, and whether templates were parsed."""
    problems = []
    templates_parsed = True
    for kind in MANIFESTS:
        names = set()
        for entry in registry.get(kind) or []:
            name = entry.get("name", "")
            label = f"{kind}/{name}"
            if not PACKAGE_NAME.match(name) or ".." in name:
                problems.append(f"{label}: name is not a safe package name")
            if name.lower() in names:
                problems.append(f"{label}: listed twice")
            names.add(name.lower())
            files, file_problems = expected_files(kind, entry)
            problems += [f"{label}: {p}" for p in file_problems]
            if entry.get("files") != files and not file_problems:
                problems.append(f"{label}: files or checksums are stale (run scripts/registry.py sync)")
            if kind == "mcp_servers":
                problems += [f"{label}: {p}" for p in mcp_manifest_problems(entry, files)]
            if kind == "focus_templates":
                manifest = ROOT / entry.get("path", "") / FOCUS_TEMPLATE_MANIFEST
                if manifest.is_file():
                    if manifest.stat().st_size > MAX_TEMPLATE_BYTES:
                        problems.append(f"{label}: template.yaml is larger than {MAX_TEMPLATE_BYTES} bytes")
                    data = load_yaml(manifest)
                    if data is None:
                        templates_parsed = False
                    else:
                        problems += [f"{label}: {p}" for p in validate_template(data, name)]
    known = {kind: {e.get("name", "").lower() for e in registry.get(kind) or []} for kind in MANIFESTS}
    for pack in registry.get("packs") or []:
        for kind in MANIFESTS:
            for member in pack.get(kind) or []:
                if member.lower() not in known[kind]:
                    problems.append(f"packs/{pack.get('name')}: {kind} member {member!r} is not in the registry")
    return problems, templates_parsed


def cmd_check(_args) -> int:
    problems, templates_parsed = check_entries(load_registry())
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if not templates_parsed:
        print("warning: PyYAML is not installed; focus template structure was not validated", file=sys.stderr)
    if problems:
        return 1
    print("registry.json is consistent with the repository")
    return 0


def cmd_sync(_args) -> int:
    registry = load_registry()
    failed = False
    for kind in MANIFESTS:
        for entry in registry.get(kind) or []:
            files, problems = expected_files(kind, entry)
            for problem in problems:
                print(f"error: {kind}/{entry.get('name')}: {problem}", file=sys.stderr)
                failed = True
            if not problems:
                entry["files"] = files
    if failed:
        return 1
    save_registry(registry)
    print("registry.json files and checksums updated")
    return 0


def top_level_scalar(text: str, key: str) -> str:
    """A top-level `key: value` scalar, for when PyYAML is not installed.
    TARS writes these on one line, plain or quoted."""
    match = re.search(rf"^{re.escape(key)}:[ \t]*(.*)$", text, re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return json.loads(value)
    return value


def bump_patch(version: str) -> str:
    parts = version.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
    return version


def default_author() -> str:
    for key in ("github.user", "user.name"):
        try:
            out = subprocess.run(["git", "config", key], capture_output=True, text=True, cwd=ROOT).stdout.strip()
        except OSError:
            out = ""
        if out:
            return out
    return ""


def cmd_add_focus_template(args) -> int:
    source = Path(args.file).expanduser()
    if not source.is_file():
        print(f"error: {source} is not a file", file=sys.stderr)
        return 1
    if source.stat().st_size > MAX_TEMPLATE_BYTES:
        print(f"error: {source} is larger than {MAX_TEMPLATE_BYTES} bytes", file=sys.stderr)
        return 1
    text = source.read_text(encoding="utf-8")
    data = load_yaml(source)
    if data is not None:
        problems = validate_template(data)
        if problems:
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1
        template_id = str(data.get("id") or "").strip()
        name = str(data.get("name") or "").strip()
        description = str(data.get("description") or "").strip()
    else:
        template_id = top_level_scalar(text, "id") or source.stem
        name = top_level_scalar(text, "name")
        description = top_level_scalar(text, "description")
        print("warning: PyYAML is not installed; only the id and name were checked (TARS validates the rest at install)", file=sys.stderr)
    if not TEMPLATE_ID.match(template_id):
        print(f"error: template id {template_id!r} must be lower-case letters, digits, - or _", file=sys.stderr)
        return 1

    target_dir = ROOT / FOCUS_TEMPLATE_DIR / template_id
    target = target_dir / FOCUS_TEMPLATE_MANIFEST
    registry = load_registry()
    entries = registry.setdefault("focus_templates", [])
    entry = next((e for e in entries if e.get("name") == template_id), None)
    changed = not target.is_file() or target.read_bytes() != source.read_bytes()

    target_dir.mkdir(parents=True, exist_ok=True)
    if changed:
        shutil.copyfile(source, target)

    if entry is None:
        entry = {"name": template_id}
        entries.append(entry)
        version = args.version or "0.1.0"
    else:
        version = args.version or (bump_patch(entry.get("version", "0.1.0")) if changed else entry.get("version", "0.1.0"))
    entry["description"] = description or entry.get("description") or name
    entry["version"] = version
    entry["author"] = args.author or entry.get("author") or default_author()
    if args.tags is not None:
        entry["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    entry.setdefault("tags", ["focus-template"])
    entry["path"] = f"{FOCUS_TEMPLATE_DIR}/{template_id}"
    entry["files"] = [{"path": FOCUS_TEMPLATE_MANIFEST, "sha256": sha256(target)}]
    # Keep the documented key order: name, description, version, ….
    order = ["name", "description", "version", "author", "tags", "path", "files", "quality"]
    entries[entries.index(entry)] = {k: entry[k] for k in order if k in entry} | {k: v for k, v in entry.items() if k not in order}
    save_registry(registry)
    action = "updated" if changed else "unchanged"
    print(f"focus template {template_id!r} ({name}) {action}: {target.relative_to(ROOT)} @ {version}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify registry.json against the repository").set_defaults(func=cmd_check)
    sub.add_parser("sync", help="rewrite files and checksums from disk").set_defaults(func=cmd_sync)
    add = sub.add_parser("add-focus-template", help="publish a TARS focus template file")
    add.add_argument("file")
    add.add_argument("--version")
    add.add_argument("--author")
    add.add_argument("--tags", help="comma-separated tags")
    add.set_defaults(func=cmd_add_focus_template)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
