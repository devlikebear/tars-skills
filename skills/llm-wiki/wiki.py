#!/usr/bin/env python3
"""llm-wiki companion CLI.

Standard-library only. Scaffolds and lints a small markdown wiki that an LLM
reads and writes directly:

    <dir>/
      raw/        source material, never edited by this script or the skill
      wiki/       pages the LLM writes (one .md file per topic)
      index.md    table of contents (links into wiki/)
      log.md      append-only change log
      SCHEMA.md   describes the page frontmatter and link syntax

Subcommands: init, lint, stats.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

INDEX_TEMPLATE = """# Index

Table of contents for this wiki. Every page in `wiki/` must be linked here
so it can be found.

<!-- add pages below, e.g. - [[Page Title]] -->
"""

LOG_TEMPLATE = """# Log

Append-only record of changes to this wiki. One line per change, newest
last. Suggested format:

    YYYY-MM-DD - created/updated "Page Title" - why
"""

# Non-blank, non-heading lines of LOG_TEMPLATE, so `stats` can tell the
# scaffolded explanation apart from real log entries appended later.
_LOG_TEMPLATE_BOILERPLATE = {
    line.strip()
    for line in LOG_TEMPLATE.splitlines()
    if line.strip() and not line.startswith("#")
}

SCHEMA_TEMPLATE = """# Page schema

Each file in `wiki/` is a markdown page with YAML-ish frontmatter:

    ---
    title: Page Title
    sources:
      - raw/some-file.md
      - https://example.com/article
    ---
    Body text here. Link to other pages with [[Other Page]] or
    [[Other Page|display text]].

Rules:

- `sources` is required and must list at least one entry (a path under
  `raw/`, or a URL) that backs this page's claims.
- Link targets in `[[...]]` must match another page's filename (without
  the `.md` extension), case-insensitive.
- Every page must be linked from `index.md`, directly or through another
  linked page, so it is reachable from the table of contents.
- `raw/` is never edited by the skill or this script — it holds source
  material as ingested.
"""


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_frontmatter(text: str) -> Tuple[Dict[str, object], str]:
    """Parse a minimal YAML-ish frontmatter block.

    Supports scalar `key: value` lines, inline flow lists `key: [a, b]`,
    and block lists:

        key:
          - a
          - b
    """
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[4:end]
    body = text[end + 4:]
    if body.startswith("\n"):
        body = body[1:]
    elif body.startswith("\r\n"):
        body = body[2:]

    meta: Dict[str, object] = {}
    current_key = None
    for raw_line in fm_text.splitlines():
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_key is not None:
            item = line.lstrip()[2:].strip().strip("\"'")
            existing = meta.get(current_key)
            if isinstance(existing, list):
                existing.append(item)
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                meta[key] = []
                current_key = key
            elif val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                items = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()]
                meta[key] = items
                current_key = None
            else:
                meta[key] = val.strip("\"'")
                current_key = None
    return meta, body


def extract_links(body: str) -> List[str]:
    """[[links]] in body, ignoring anything inside an HTML comment (used for
    placeholder examples like `<!-- - [[Page Title]] -->`)."""
    without_comments = COMMENT_RE.sub("", body)
    return [m.group(1).strip() for m in LINK_RE.finditer(without_comments)]


def wiki_pages(wiki_dir: Path) -> Dict[str, Path]:
    """Map lowercase filename stem -> page path for every page in wiki_dir."""
    pages: Dict[str, Path] = {}
    if not wiki_dir.is_dir():
        return pages
    for path in sorted(wiki_dir.glob("*.md")):
        pages[path.stem.lower()] = path
    return pages


def resolve_link(target: str, pages: Dict[str, Path]) -> bool:
    key = target.strip().lower()
    if key in pages:
        return True
    return slugify(target) in {slugify(stem) for stem in pages}


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.dir)
    created = []

    raw_dir = root / "raw"
    wiki_dir = root / "wiki"
    for d in (raw_dir, wiki_dir):
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    files = {
        root / "index.md": INDEX_TEMPLATE,
        root / "log.md": LOG_TEMPLATE,
        root / "SCHEMA.md": SCHEMA_TEMPLATE,
    }
    for path, content in files.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(str(path))

    if created:
        print("created:")
        for item in created:
            print(f"  {item}")
    else:
        print(f"already initialized: {root}")
    return 0


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

def cmd_lint(args: argparse.Namespace) -> int:
    root = Path(args.dir)
    wiki_dir = root / "wiki"
    index_path = root / "index.md"

    pages = wiki_pages(wiki_dir)

    index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    index_links = {t.lower() for t in extract_links(index_text)}

    broken_links: List[str] = []
    missing_sources: List[str] = []
    linked_from: Dict[str, set] = {stem: set() for stem in pages}

    for stem, path in pages.items():
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)

        sources = meta.get("sources")
        if not sources:
            missing_sources.append(path.name)

        for target in extract_links(body):
            if not resolve_link(target, pages):
                broken_links.append(f"{path.name}: [[{target}]]")
            else:
                key = target.strip().lower()
                if key not in pages:
                    # matched via slug only; find the real stem
                    for s in pages:
                        if slugify(s) == slugify(target):
                            key = s
                            break
                if key != stem:
                    # a self-link doesn't make a page reachable from
                    # "another" page
                    linked_from.setdefault(key, set()).add(stem)

    for target in extract_links(index_text):
        if not resolve_link(target, pages):
            broken_links.append(f"index.md: [[{target}]]")

    not_in_index: List[str] = []
    orphans: List[str] = []
    for stem, path in pages.items():
        in_index = stem in index_links or any(
            slugify(stem) == slugify(t) for t in index_links
        )
        if not in_index:
            not_in_index.append(path.name)
        if not in_index and not linked_from.get(stem):
            orphans.append(path.name)

    problems = {
        "broken links": sorted(broken_links),
        "orphan pages (not reachable from index.md or any other page)": sorted(orphans),
        "pages missing from index.md": sorted(not_in_index),
        "pages without a sources entry": sorted(missing_sources),
    }

    had_problem = False
    for label, items in problems.items():
        if items:
            had_problem = True
            print(f"{label}:")
            for item in items:
                print(f"  - {item}")

    if had_problem:
        return 1

    print(f"ok: {len(pages)} page(s), no problems found")
    return 0


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def cmd_stats(args: argparse.Namespace) -> int:
    root = Path(args.dir)
    raw_dir = root / "raw"
    wiki_dir = root / "wiki"
    log_path = root / "log.md"

    raw_count = sum(1 for p in raw_dir.rglob("*") if p.is_file()) if raw_dir.is_dir() else 0
    pages = wiki_pages(wiki_dir)

    link_count = 0
    for path in pages.values():
        _, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        link_count += len(extract_links(body))

    log_lines = 0
    last_log_line = ""
    if log_path.exists():
        lines = [
            l
            for l in log_path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#") and l.strip() not in _LOG_TEMPLATE_BOILERPLATE
        ]
        log_lines = len(lines)
        if lines:
            last_log_line = lines[-1]

    print(f"raw files: {raw_count}")
    print(f"wiki pages: {len(pages)}")
    print(f"links: {link_count}")
    print(f"log entries: {log_lines}")
    if last_log_line:
        print(f"last log entry: {last_log_line}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wiki.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create raw/, wiki/, index.md, log.md, SCHEMA.md")
    p_init.add_argument("dir", help="wiki root directory")
    p_init.set_defaults(func=cmd_init)

    p_lint = sub.add_parser("lint", help="check for broken links, orphans, missing index entries, missing sources")
    p_lint.add_argument("dir", help="wiki root directory")
    p_lint.set_defaults(func=cmd_lint)

    p_stats = sub.add_parser("stats", help="print page/link/log counts")
    p_stats.add_argument("dir", help="wiki root directory")
    p_stats.set_defaults(func=cmd_stats)

    return parser


def main(argv: List[str] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
