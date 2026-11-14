---
name: llm-wiki
description: "Builds and maintains a markdown wiki by reading raw source material yourself and writing linked, sourced pages — Karpathy-style LLM wiki. Use when the user wants to collect notes on a topic into a browsable, cross-linked knowledge base, or asks you to look something up in a wiki you already built them."
user-invocable: true
recommended_tools:
  - bash
  - read_file
  - write_file
  - web_fetch
---

# LLM Wiki

A small markdown wiki you write and maintain directly — no database, no
embeddings, no server. You read the raw material, decide what's worth a
page, write it with real prose and citations, and link it to the rest of
the wiki. A companion script (`wiki.py`, ships next to this file) only
checks the result; it never writes a page itself.

This is **not** TARS's built-in `memory/` system (daily logs, experiences,
semantic recall) and does not touch `memory/wiki` if that legacy folder
exists in the workspace. It is a separate, opt-in knowledge base for a
topic the user wants collected — e.g. "build me a wiki on X", "add this
article to my Y wiki", "what does my wiki say about Z".

## Location

Default root: `<workspace>/wiki/` (the TARS workspace root, not the repo
you happen to be working in). If the user names a different place — a
project folder, a path they give you — use that instead, and remember
which one across the conversation.

## Layout

```
<root>/
  raw/        source material as ingested — you NEVER edit files here
  wiki/       one markdown page per topic, written by you
  index.md    table of contents, links into wiki/
  log.md      append-only: what changed and why
  SCHEMA.md   the page format, written once by `wiki.py init`
```

First use in a given root: run `python3 <skill_dir>/wiki.py init <root>`.
It is idempotent — safe to run again, it only creates what's missing and
never overwrites an existing file.

## Page format

Every page in `wiki/` is markdown with frontmatter:

```
---
title: Page Title
sources:
  - raw/some-file.md
  - https://example.com/article
---
Body text. Link other pages with [[Other Page]] or [[Other Page|text]].
```

Rules, enforced by `wiki.py lint` (deterministic, not graded by a model):

- `sources` is required — at least one entry, a path under `raw/` or a
  URL, that backs the page's claims. Don't write a page you can't source.
- `[[Link]]` targets must match another page's filename (case-insensitive,
  `-`/`_`/spaces treated as equivalent).
- Every page must be reachable from `index.md` — linked there directly,
  or linked from a page that is.
- `raw/` is read-only from your side. If the user gives you a new article,
  save it under `raw/` first, unmodified, then write pages from it.

## Ingest (adding material)

1. Get the material into `raw/` unchanged:
   - Pasted text or a local file → write it under `raw/` as-is (pick a
     clear filename).
   - A URL → fetch it, save the extracted text under `raw/` with the
     source URL recorded at the top of the file.
2. Decide what deserves a page. Don't make one page per source — make one
   page per topic/entity/question, pulling from however many sources it
   needs. Reuse an existing page (edit it) rather than duplicating a
   near-identical one.
3. Write or update the page(s) in `wiki/` per the format above. Link to
   related existing pages; create short stub pages for topics you
   reference but haven't written up yet (still needs real `sources`).
4. Add the new/changed pages to `index.md` if they aren't reachable yet.
5. Append one line to `log.md`: date, page, what changed, why.
6. Run `python3 <skill_dir>/wiki.py lint <root>`. Fix anything it reports
   before telling the user you're done — don't leave broken links,
   orphans, or unsourced pages for them to find.

## Query (answering from the wiki)

1. Read `index.md` first to find the relevant page(s) — don't grep the
   whole `wiki/` directory blindly if the index already points the way.
2. Read the page(s), and follow `[[links]]` to related pages if the
   answer needs them.
3. Answer with the page's own content, and name which page(s) you used
   (e.g. "per wiki/Foo.md"). If the page's `sources` disagree with each
   other or look stale, say so instead of picking silently.
4. If nothing in the wiki covers the question, say that plainly — don't
   invent a page to answer from and don't fall back to general knowledge
   while implying it came from the wiki.

## Maintenance

- `python3 <skill_dir>/wiki.py lint <root>` — run after any edit batch.
  Non-zero exit means something needs fixing before you report success.
- `python3 <skill_dir>/wiki.py stats <root>` — quick counts (pages, raw
  files, links, log entries) if the user asks how big the wiki has grown.
- Keep `raw/` untouched. If a source turns out to be wrong, write that
  into the page's prose (or drop it from `sources`) — don't edit the raw
  file to match.
