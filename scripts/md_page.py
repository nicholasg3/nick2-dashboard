#!/usr/bin/env python3
"""Minimal markdown → standalone HTML pages for GitHub Pages."""
from __future__ import annotations

import html
import re

PAGE_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #0f1419; color: #e8edf4; line-height: 1.55; margin: 0; }
.wrap { max-width: 720px; margin: 0 auto; padding: 1.5rem; }
a { color: #4f9cf9; }
.nav { margin-bottom: 1.25rem; font-size: 0.9rem; }
h1 { font-size: 1.55rem; letter-spacing: -0.02em; margin: 1rem 0 0.75rem; }
h2 { font-size: 1.15rem; margin: 1.35rem 0 0.5rem; color: #c5d4e8; }
h3 { font-size: 1rem; margin: 1rem 0 0.4rem; color: #a8b8cc; }
p { margin: 0.55rem 0; }
ul, ol { margin: 0.5rem 0 0.5rem 1.25rem; }
li { margin: 0.25rem 0; }
code { background: #243044; padding: 0.12em 0.38em; border-radius: 4px; font-size: 0.9em; }
pre { background: #1a2332; border: 1px solid #2d3a4f; padding: 1rem; border-radius: 8px;
  overflow-x: auto; font-size: 0.85rem; }
pre code { background: none; padding: 0; }
table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; font-size: 0.92rem; }
th, td { border: 1px solid #2d3a4f; padding: 0.45rem 0.6rem; text-align: left; }
th { color: #8b9cb3; }
em { color: #8b9cb3; }
strong { color: #fff; }
"""


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def md_to_html_body(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    in_code = False
    code_buf: list[str] = []
    table_buf: list[str] = []

    def flush_table() -> None:
        nonlocal table_buf
        if not table_buf:
            return
        rows = table_buf
        table_buf = []
        if len(rows) < 2:
            for r in rows:
                out.append(f"<p>{_inline(r)}</p>")
            return
        header = [_inline(c.strip()) for c in rows[0].strip("|").split("|")]
        body_rows = rows[2:] if len(rows) > 1 and re.match(r"^[\s|:-]+$", rows[1]) else rows[1:]
        out.append("<table><thead><tr>" + "".join(f"<th>{c}</th>" for c in header) + "</tr></thead><tbody>")
        for row in body_rows:
            cells = [_inline(c.strip()) for c in row.strip("|").split("|")]
            out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        out.append("</tbody></table>")

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                flush_table()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        if "|" in line and line.strip().startswith("|"):
            table_buf.append(line)
            i += 1
            continue
        flush_table()
        if not line.strip():
            i += 1
            continue
        if line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:].strip())}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{_inline(line[4:].strip())}</h3>")
        elif re.match(r"^[-*] ", line):
            items = []
            while i < len(lines) and re.match(r"^[-*] ", lines[i]):
                items.append(f"<li>{_inline(lines[i][2:].strip())}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif re.match(r"^\d+\. ", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\. ", lines[i]):
                items.append(f"<li>{_inline(re.sub(r'^\\d+\\. ', '', lines[i]).strip())}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        else:
            out.append(f"<p>{_inline(line)}</p>")
        i += 1
    flush_table()
    if in_code and code_buf:
        out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
    return "\n".join(out)


def wrap_page(title: str, body_html: str, back_href: str = "../index.html") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)} — Nick2</title>
  <style>{PAGE_CSS}</style>
</head>
<body>
  <div class="wrap">
    <p class="nav"><a href="{html.escape(back_href, quote=True)}">← Dashboard</a></p>
    {body_html}
  </div>
</body>
</html>
"""


def write_html(path, md: str, title: str, back_href: str = "../index.html") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(wrap_page(title, md_to_html_body(md), back_href), encoding="utf-8")