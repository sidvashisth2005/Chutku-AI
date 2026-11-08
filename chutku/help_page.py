"""The in-app Help (2026-11-08 launch review: /help showed raw Markdown). Turns docs/USER_GUIDE.md into one plain HTML
page with the dashboard's own styles. Only the few constructs the guide uses: headings, paragraphs, lists, tables,
quotes, rules, **bold**, `code` and [links](url). Every piece of text is HTML-escaped first.
"""
from __future__ import annotations

import html
import re

_INLINE = ((re.compile(r"`([^`]+)`"), r"<code>\1</code>"), (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
           (re.compile(r"(?<![*\w])\*([^*\s][^*]*)\*(?![*\w])"), r"<em>\1</em>"),
           (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"), r'<a href="\2" target="_blank" rel="noopener">\1</a>'))


def _inline(text):
    text = html.escape(text, quote=False)
    for pattern, replacement in _INLINE:
        text = pattern.sub(replacement, text)
    return text


def render(markdown):
    out, paragraph, list_tag, table, items = [], [], None, [], []

    def flush():
        nonlocal list_tag
        out.extend("<li>" + _inline(text) + "</li>" for text in items)
        items.clear()
        if paragraph:
            out.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None
        if table:
            rows = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in table
                    if not re.fullmatch(r"\|[\s:|-]+\|", row.strip())]
            head, body = rows[0], rows[1:]
            out.append('<table class="reliability"><tr>' + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</table>")
            table.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        heading = re.match(r"(#{1,4})\s+(.*)", stripped)
        item = re.match(r"(?:[-*]|(\d+)\.)\s+(.*)", stripped)
        if not stripped or stripped == "---":
            flush()
            if stripped == "---":
                out.append("<hr>")
        elif heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif stripped.startswith("|"):
            if paragraph or list_tag:
                flush()
            table.append(stripped)
        elif stripped.startswith(">"):
            flush()
            out.append("<blockquote>" + _inline(stripped.lstrip("> ")) + "</blockquote>")
        elif item and not line.startswith("    "):
            tag = "ol" if item.group(1) else "ul"
            if paragraph or table or list_tag != tag:
                flush()
                out.append(f"<{tag}>")
                list_tag = tag
            out.extend("<li>" + _inline(text) + "</li>" for text in items)
            items[:] = [item.group(2)]
        elif list_tag and items:   # a wrapped list line (bold may span the break)
            items[-1] += " " + stripped
        else:
            paragraph.append(stripped)
    flush()
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>Chutku Help</title>'
            '<link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/theme.css">'
            '<link rel="icon" href="/chutku.ico"></head><body><main class="help-page">'
            + "\n".join(out) + "</main></body></html>")
