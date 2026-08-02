#!/usr/bin/env python3
"""Render the project documentation as the GitHub Pages landing page.

This deliberately supports the small Markdown subset used by
PLUGIN_DOCUMENTATION.md, avoiding a build-time third-party dependency.
"""

from __future__ import annotations

import argparse
import html
import re
from collections import Counter
from pathlib import Path


HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
UNORDERED_ITEM = re.compile(r"^[-*+]\s+(.+?)\s*$")
ORDERED_ITEM = re.compile(r"^\d+[.)]\s+(.+?)\s*$")
LINK = re.compile(r"\[([^\]]+)\]\(([^\s)]+)\)")
CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*([^*]+)\*\*")


def slugify(value: str, seen: Counter[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "section"
    seen[slug] += 1
    return slug if seen[slug] == 1 else f"{slug}-{seen[slug]}"


def inline(value: str) -> str:
    """Escape Markdown text then render the supported inline syntax."""
    value = html.escape(value, quote=False)
    value = LINK.sub(
        lambda match: (
            f'<a href="{html.escape(html.unescape(match.group(2)), quote=True)}">'
            f"{match.group(1)}</a>"
        ),
        value,
    )
    value = CODE.sub(r"<code>\1</code>", value)
    return BOLD.sub(r"<strong>\1</strong>", value)


def render(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_type: str | None = None
    code_lines: list[str] = []
    in_code_block = False
    seen: Counter[str] = Counter()

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            output.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items, list_type
        if list_items and list_type:
            output.append(
                f"<{list_type}>"
                + "".join(f"<li>{inline(item)}</li>" for item in list_items)
                + f"</{list_type}>"
            )
        list_items = []
        list_type = None

    for line in lines:
        if line.strip().startswith("```"):
            flush_paragraph()
            flush_list()
            if in_code_block:
                output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = []
            in_code_block = not in_code_block
            continue
        if in_code_block:
            code_lines.append(line)
            continue

        heading = HEADING.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            title = heading.group(2)
            output.append(f'<h{level} id="{slugify(title, seen)}">{inline(title)}</h{level}>')
            continue
        if line.strip() == "---":
            flush_paragraph()
            flush_list()
            output.append("<hr>")
            continue

        unordered = UNORDERED_ITEM.match(line)
        ordered = ORDERED_ITEM.match(line)
        if unordered or ordered:
            item_type = "ul" if unordered else "ol"
            if list_type and list_type != item_type:
                flush_list()
            flush_paragraph()
            list_type = item_type
            list_items.append((unordered or ordered).group(1))
            continue
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue

        if list_type:
            flush_list()
        paragraph.append(line.strip())

    if in_code_block:
        raise ValueError("Unclosed fenced code block in documentation.")
    flush_paragraph()
    flush_list()
    return "\n".join(output)


def page(body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="AIOStreams Kodi add-on documentation and installation instructions.">
  <title>AIOStreams Kodi</title>
  <style>
    :root {{ color-scheme: light dark; --bg: #ffffff; --surface: #f6f8fa; --text: #1f2328; --muted: #59636e; --border: #d0d7de; --link: #0969da; --code: #f1f3f5; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --bg: #0d1117; --surface: #161b22; --text: #e6edf3; --muted: #9da7b3; --border: #30363d; --link: #58a6ff; --code: #161b22; }} }}
    * {{ box-sizing: border-box; }}
    body {{ max-width: 52rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; background: var(--bg); color: var(--text); font: 1rem/1.6 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    h1, h2, h3, h4 {{ line-height: 1.25; margin: 2.25rem 0 0.75rem; }}
    h1 {{ margin-top: 0; font-size: clamp(2rem, 6vw, 3rem); }}
    h2 {{ border-bottom: 1px solid var(--border); padding-bottom: .35rem; }}
    p, ul, ol {{ margin: .75rem 0; }}
    li + li {{ margin-top: .35rem; }}
    a {{ color: var(--link); }}
    code {{ padding: .12rem .32rem; border-radius: .25rem; background: var(--code); font: .9em ui-monospace, SFMono-Regular, Consolas, monospace; }}
    pre {{ overflow-x: auto; padding: 1rem; border: 1px solid var(--border); border-radius: .5rem; background: var(--surface); }}
    pre code {{ padding: 0; background: transparent; }}
    hr {{ border: 0; border-top: 1px solid var(--border); margin: 2rem 0; }}
  </style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repository-zip", required=True)
    args = parser.parse_args()

    markdown = args.input.read_text(encoding="utf-8")
    markdown = markdown.replace("{{REPOSITORY_ZIP}}", args.repository_zip)
    rendered = page(render(markdown))
    expected_link = f'<a href="{args.repository_zip}">{args.repository_zip}</a>'
    if expected_link not in rendered:
        raise ValueError("The landing page must contain a Kodi-compatible repository ZIP link.")
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
