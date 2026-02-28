#!/usr/bin/env python3
"""Generate styled HTML pages from the BetVector master plan and build plan markdown files.

Produces self-contained HTML with inline CSS/JS matching the BetVector dark theme.
Run: python3 generate_html_docs.py
"""

import re
import html as html_lib
from pathlib import Path

# ---------------------------------------------------------------------------
# Theme constants (matching index.html / CLAUDE.md design system)
# ---------------------------------------------------------------------------
BG = "#0D1117"
SURFACE = "#161B22"
TEXT = "#E6EDF3"
MUTED = "#8B949E"
GREEN = "#3FB950"
BLUE = "#58a6ff"
RED = "#F85149"
BORDER = "#30363D"
YELLOW = "#D29922"

# Completed issues for build plan progress indicators
COMPLETED_ISSUES = {
    "E1-01", "E1-02", "E1-03",
    "E2-01", "E2-02", "E2-03", "E2-04",
    "E3-01", "E3-02", "E3-03", "E3-04",
    "E4-01", "E4-02", "E4-03",
    "E5-01", "E5-02", "E5-03",
}

# SQL keywords for syntax highlighting
SQL_KEYWORDS = {
    "CREATE", "TABLE", "INDEX", "ON", "INTEGER", "TEXT", "REAL", "NOT",
    "NULL", "PRIMARY", "KEY", "AUTOINCREMENT", "REFERENCES", "DEFAULT",
    "CHECK", "IN", "UNIQUE", "INSERT", "OR", "IGNORE", "SELECT", "FROM",
    "WHERE", "AND", "JOIN", "LEFT", "INNER", "ORDER", "BY", "DESC", "ASC",
    "GROUP", "HAVING", "LIMIT", "OFFSET", "AS", "SET", "UPDATE", "DELETE",
    "DROP", "ALTER", "ADD", "CONSTRAINT", "FOREIGN", "CASCADE", "IF",
    "EXISTS", "VALUES", "INTO", "PRAGMA",
}

# Python keywords for syntax highlighting
PY_KEYWORDS = {
    "def", "class", "import", "from", "return", "if", "elif", "else",
    "for", "while", "with", "as", "try", "except", "finally", "raise",
    "yield", "lambda", "pass", "break", "continue", "and", "or", "not",
    "in", "is", "None", "True", "False", "self", "async", "await",
    "property", "staticmethod", "classmethod",
}


def escape(text: str) -> str:
    return html_lib.escape(text)


def highlight_sql(code: str) -> str:
    """Basic SQL syntax highlighting."""
    lines = code.split("\n")
    result = []
    for line in lines:
        # Comments
        if line.strip().startswith("--"):
            result.append(f'<span class="code-comment">{escape(line)}</span>')
            continue
        tokens = re.split(r'(\b\w+\b|[^\w\s]+|\s+)', line)
        highlighted = []
        for token in tokens:
            upper = token.upper()
            if upper in SQL_KEYWORDS:
                highlighted.append(f'<span class="code-keyword">{escape(token)}</span>')
            elif token.startswith("'") and token.endswith("'"):
                highlighted.append(f'<span class="code-string">{escape(token)}</span>')
            else:
                highlighted.append(escape(token))
        result.append("".join(highlighted))
    return "\n".join(result)


def highlight_python(code: str) -> str:
    """Basic Python syntax highlighting."""
    lines = code.split("\n")
    result = []
    for line in lines:
        if line.strip().startswith("#"):
            result.append(f'<span class="code-comment">{escape(line)}</span>')
            continue
        # Handle strings, keywords, decorators
        tokens = re.split(r'(\b\w+\b|\"[^\"]*\"|\'[^\']*\'|[^\w\s]+|\s+)', line)
        highlighted = []
        for token in tokens:
            if token in PY_KEYWORDS:
                highlighted.append(f'<span class="code-keyword">{escape(token)}</span>')
            elif token.startswith("@"):
                highlighted.append(f'<span class="code-decorator">{escape(token)}</span>')
            elif (token.startswith('"') and token.endswith('"')) or \
                 (token.startswith("'") and token.endswith("'")):
                highlighted.append(f'<span class="code-string">{escape(token)}</span>')
            else:
                highlighted.append(escape(token))
        result.append("".join(highlighted))
    return "\n".join(result)


def highlight_code(code: str, lang: str) -> str:
    if lang in ("sql", "sqlite"):
        return highlight_sql(code)
    elif lang in ("python", "py"):
        return highlight_python(code)
    else:
        return escape(code)


# ---------------------------------------------------------------------------
# Markdown → HTML conversion
# ---------------------------------------------------------------------------

def md_to_html(md_text: str, doc_type: str = "masterplan") -> tuple:
    """Convert markdown text to HTML content and extract TOC entries.

    Returns (html_content, toc_entries) where toc_entries is a list of
    (level, id, title) tuples.
    """
    lines = md_text.split("\n")
    html_parts = []
    toc = []
    i = 0
    in_code_block = False
    code_lang = ""
    code_lines = []
    in_table = False
    table_rows = []
    in_list = False
    list_type = "ul"
    list_items = []

    def flush_list():
        nonlocal in_list, list_items, list_type
        if in_list and list_items:
            tag = list_type
            items_html = "\n".join(f"<li>{item}</li>" for item in list_items)
            html_parts.append(f"<{tag} class='md-list'>{items_html}</{tag}>")
            list_items = []
            in_list = False

    def flush_table():
        nonlocal in_table, table_rows
        if in_table and table_rows:
            thead = ""
            tbody_rows = []
            for idx, row in enumerate(table_rows):
                cells = [c.strip() for c in row.strip("|").split("|")]
                if idx == 0:
                    ths = "".join(f"<th>{inline_format(c)}</th>" for c in cells)
                    thead = f"<thead><tr>{ths}</tr></thead>"
                elif idx == 1 and all(set(c.strip()) <= {"-", ":", " "} for c in cells):
                    continue  # separator row
                else:
                    tds = "".join(f"<td>{inline_format(c)}</td>" for c in cells)
                    tbody_rows.append(f"<tr>{tds}</tr>")
            tbody = f"<tbody>{''.join(tbody_rows)}</tbody>"
            html_parts.append(f"<div class='table-wrapper'><table>{thead}{tbody}</table></div>")
            table_rows = []
            in_table = False

    def inline_format(text: str) -> str:
        """Handle inline markdown: bold, italic, code, links."""
        # Code spans first (to avoid processing their contents)
        text = re.sub(r'`([^`]+)`', r'<code class="inline-code">\1</code>', text)
        # Bold + italic
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        # Links
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" class="md-link">\1</a>', text)
        # Em dash
        text = text.replace(" — ", " &mdash; ")
        return text

    def make_id(title: str) -> str:
        clean = re.sub(r'[^\w\s-]', '', title.lower())
        return re.sub(r'[\s]+', '-', clean).strip('-')

    while i < len(lines):
        line = lines[i]

        # Code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                # End code block
                code_text = "\n".join(code_lines)
                highlighted = highlight_code(code_text, code_lang)
                lang_label = code_lang.upper() if code_lang else ""
                label_html = f'<span class="code-lang">{lang_label}</span>' if lang_label else ""
                html_parts.append(
                    f'<div class="code-block">{label_html}'
                    f'<pre><code>{highlighted}</code></pre></div>'
                )
                in_code_block = False
                code_lines = []
                code_lang = ""
            else:
                flush_list()
                flush_table()
                in_code_block = True
                code_lang = line.strip().lstrip("`").strip().lower()
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # Horizontal rule
        if line.strip() in ("---", "***", "___"):
            flush_list()
            flush_table()
            html_parts.append("<hr class='md-hr'>")
            i += 1
            continue

        # Headers
        header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if header_match:
            flush_list()
            flush_table()
            level = len(header_match.group(1))
            title = header_match.group(2)
            hid = make_id(title)

            # Check if this is a completed issue in the build plan
            completed_badge = ""
            if doc_type == "buildplan":
                issue_match = re.match(r'(E\d+-\d+)', title)
                if issue_match and issue_match.group(1) in COMPLETED_ISSUES:
                    completed_badge = ' <span class="badge badge-completed">Completed</span>'

            # Add green border for h2
            extra_class = ""
            if level == 2:
                extra_class = " section-header"
                toc.append((level, hid, title))
            elif level == 3:
                extra_class = " subsection-header"
                toc.append((level, hid, title))

            html_parts.append(
                f'<h{level} id="{hid}" class="md-h{level}{extra_class}">'
                f'{inline_format(title)}{completed_badge}</h{level}>'
            )
            i += 1
            continue

        # Tables
        if "|" in line and line.strip().startswith("|"):
            flush_list()
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(line)
            i += 1
            continue
        elif in_table:
            flush_table()

        # Ordered lists
        ol_match = re.match(r'^(\d+)\.\s+(.+)$', line)
        if ol_match:
            flush_table()
            if not in_list or list_type != "ol":
                flush_list()
                in_list = True
                list_type = "ol"
            list_items.append(inline_format(ol_match.group(2)))
            i += 1
            continue

        # Unordered lists
        ul_match = re.match(r'^[\s]*[-*+]\s+(.+)$', line)
        if ul_match:
            flush_table()
            if not in_list or list_type != "ul":
                flush_list()
                in_list = True
                list_type = "ul"
            # Handle checkbox syntax
            item_text = ul_match.group(1)
            if item_text.startswith("[ ] "):
                item_text = f'<span class="checkbox">☐</span> {inline_format(item_text[4:])}'
            elif item_text.startswith("[x] ") or item_text.startswith("[X] "):
                item_text = f'<span class="checkbox checked">☑</span> {inline_format(item_text[4:])}'
            else:
                item_text = inline_format(item_text)
            list_items.append(item_text)
            i += 1
            continue

        # If we were in a list and hit a non-list line
        if in_list and line.strip() == "":
            flush_list()
            i += 1
            continue
        elif in_list:
            flush_list()

        # Blockquotes
        if line.strip().startswith(">"):
            flush_table()
            quote_text = line.strip().lstrip(">").strip()
            html_parts.append(f'<blockquote class="md-blockquote">{inline_format(quote_text)}</blockquote>')
            i += 1
            continue

        # Empty lines
        if line.strip() == "":
            i += 1
            continue

        # Regular paragraphs
        flush_table()
        html_parts.append(f'<p class="md-p">{inline_format(line)}</p>')
        i += 1

    flush_list()
    flush_table()

    return "\n".join(html_parts), toc


def build_toc_html(toc: list) -> str:
    """Build sidebar table of contents HTML."""
    items = []
    for level, hid, title in toc:
        indent_class = "toc-h3" if level == 3 else "toc-h2"
        items.append(f'<a href="#{hid}" class="toc-item {indent_class}">{title}</a>')
    return "\n".join(items)


def get_css() -> str:
    return f"""
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    * {{ margin: 0; padding: 0; box-sizing: border-box; }}

    html {{ scroll-behavior: smooth; }}

    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: {BG};
      color: {TEXT};
      line-height: 1.7;
      font-size: 16px;
    }}

    /* --- Top Nav --- */
    .top-nav {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: {BG};
      border-bottom: 1px solid {BORDER};
      padding: 0.75rem 1.5rem;
      display: flex;
      align-items: center;
      gap: 1.5rem;
      backdrop-filter: blur(12px);
    }}
    .top-nav .logo {{
      font-size: 1.3rem;
      font-weight: 700;
      background: linear-gradient(135deg, {GREEN}, {BLUE});
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      text-decoration: none;
    }}
    .top-nav .page-title {{
      color: {MUTED};
      font-size: 1rem;
      font-weight: 500;
    }}
    .hamburger {{
      display: none;
      background: none;
      border: none;
      color: {TEXT};
      font-size: 1.5rem;
      cursor: pointer;
      margin-left: auto;
    }}

    /* --- Layout --- */
    .layout {{
      display: flex;
      max-width: 1400px;
      margin: 0 auto;
    }}

    /* --- Sidebar TOC --- */
    .sidebar {{
      width: 280px;
      min-width: 280px;
      position: sticky;
      top: 52px;
      height: calc(100vh - 52px);
      overflow-y: auto;
      border-right: 1px solid {BORDER};
      padding: 1.5rem 0;
      scrollbar-width: thin;
      scrollbar-color: {BORDER} transparent;
    }}
    .sidebar::-webkit-scrollbar {{ width: 4px; }}
    .sidebar::-webkit-scrollbar-track {{ background: transparent; }}
    .sidebar::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 2px; }}
    .sidebar .toc-title {{
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: {MUTED};
      padding: 0 1.25rem;
      margin-bottom: 0.75rem;
    }}
    .toc-item {{
      display: block;
      padding: 0.35rem 1.25rem;
      color: {MUTED};
      text-decoration: none;
      font-size: 0.85rem;
      border-left: 2px solid transparent;
      transition: all 0.15s;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .toc-item:hover {{
      color: {TEXT};
      background: {SURFACE};
    }}
    .toc-item.active {{
      color: {GREEN};
      border-left-color: {GREEN};
    }}
    .toc-h3 {{ padding-left: 2.25rem; font-size: 0.8rem; }}

    /* --- Main Content --- */
    .content {{
      flex: 1;
      min-width: 0;
      padding: 2rem 3rem;
      max-width: 900px;
    }}

    /* --- Typography --- */
    .md-h2.section-header {{
      font-size: 1.75rem;
      font-weight: 700;
      margin: 2.5rem 0 1rem;
      padding: 0.5rem 0 0.5rem 1rem;
      border-left: 4px solid {GREEN};
    }}
    .md-h3.subsection-header {{
      font-size: 1.3rem;
      font-weight: 600;
      margin: 2rem 0 0.75rem;
      color: {BLUE};
    }}
    .md-h4 {{ font-size: 1.1rem; font-weight: 600; margin: 1.5rem 0 0.5rem; }}
    .md-h5 {{ font-size: 1rem; font-weight: 600; margin: 1rem 0 0.5rem; color: {MUTED}; }}
    .md-p {{ margin-bottom: 1rem; }}
    .md-p strong {{ color: #fff; }}

    /* --- Links --- */
    .md-link {{ color: {BLUE}; text-decoration: none; }}
    .md-link:hover {{ text-decoration: underline; }}

    /* --- Lists --- */
    .md-list {{
      margin: 0.5rem 0 1rem 1.5rem;
    }}
    .md-list li {{
      margin-bottom: 0.4rem;
      padding-left: 0.25rem;
    }}

    /* --- Checkboxes --- */
    .checkbox {{
      font-family: 'JetBrains Mono', monospace;
      color: {MUTED};
      margin-right: 0.3rem;
    }}
    .checkbox.checked {{ color: {GREEN}; }}

    /* --- Code --- */
    .inline-code {{
      font-family: 'JetBrains Mono', monospace;
      background: {SURFACE};
      border: 1px solid {BORDER};
      padding: 0.15rem 0.4rem;
      border-radius: 4px;
      font-size: 0.88em;
      color: {BLUE};
    }}
    .code-block {{
      position: relative;
      background: {SURFACE};
      border: 1px solid {BORDER};
      border-radius: 8px;
      margin: 1rem 0;
      overflow-x: auto;
    }}
    .code-block pre {{
      padding: 1.25rem;
      margin: 0;
      overflow-x: auto;
    }}
    .code-block code {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.85rem;
      line-height: 1.6;
      color: {TEXT};
    }}
    .code-lang {{
      position: absolute;
      top: 0.5rem;
      right: 0.75rem;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.7rem;
      color: {MUTED};
      text-transform: uppercase;
    }}
    .code-keyword {{ color: #ff7b72; font-weight: 500; }}
    .code-string {{ color: #a5d6ff; }}
    .code-comment {{ color: {MUTED}; font-style: italic; }}
    .code-decorator {{ color: {YELLOW}; }}

    /* --- Tables --- */
    .table-wrapper {{
      overflow-x: auto;
      margin: 1rem 0;
      border-radius: 8px;
      border: 1px solid {BORDER};
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}
    thead th {{
      background: {SURFACE};
      padding: 0.75rem 1rem;
      text-align: left;
      font-weight: 600;
      color: {TEXT};
      border-bottom: 1px solid {BORDER};
      white-space: nowrap;
    }}
    tbody td {{
      padding: 0.6rem 1rem;
      border-bottom: 1px solid {BORDER};
    }}
    tbody tr:nth-child(even) {{
      background: rgba(22, 27, 34, 0.5);
    }}
    tbody tr:hover {{
      background: rgba(63, 185, 80, 0.05);
    }}

    /* --- Blockquotes --- */
    .md-blockquote {{
      border-left: 3px solid {BLUE};
      padding: 0.75rem 1.25rem;
      margin: 1rem 0;
      background: {SURFACE};
      border-radius: 0 8px 8px 0;
      color: {MUTED};
      font-style: italic;
    }}

    /* --- Horizontal rules --- */
    .md-hr {{
      border: none;
      border-top: 1px solid {BORDER};
      margin: 2rem 0;
    }}

    /* --- Badges --- */
    .badge {{
      display: inline-block;
      font-size: 0.7rem;
      font-weight: 600;
      padding: 0.2rem 0.6rem;
      border-radius: 12px;
      vertical-align: middle;
      margin-left: 0.5rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .badge-completed {{
      background: rgba(63, 185, 80, 0.15);
      color: {GREEN};
      border: 1px solid rgba(63, 185, 80, 0.3);
    }}

    /* --- Back to top --- */
    .back-to-top {{
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: {GREEN};
      color: {BG};
      border: none;
      cursor: pointer;
      font-size: 1.25rem;
      display: none;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      transition: transform 0.2s;
      z-index: 50;
    }}
    .back-to-top:hover {{ transform: scale(1.1); }}
    .back-to-top.visible {{ display: flex; }}

    /* --- Mobile --- */
    @media (max-width: 768px) {{
      .hamburger {{ display: block; }}
      .sidebar {{
        position: fixed;
        top: 52px;
        left: -300px;
        width: 280px;
        min-width: 280px;
        height: calc(100vh - 52px);
        background: {BG};
        z-index: 90;
        transition: left 0.3s ease;
        border-right: 1px solid {BORDER};
      }}
      .sidebar.open {{ left: 0; }}
      .sidebar-overlay {{
        display: none;
        position: fixed;
        top: 52px;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0,0,0,0.5);
        z-index: 80;
      }}
      .sidebar-overlay.open {{ display: block; }}
      .content {{
        padding: 1.5rem 1rem;
      }}
      .md-h2.section-header {{ font-size: 1.4rem; }}
    }}
    """


def get_js() -> str:
    return """
    // Hamburger toggle
    const hamburger = document.getElementById('hamburger');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('overlay');

    if (hamburger) {
      hamburger.addEventListener('click', () => {
        sidebar.classList.toggle('open');
        overlay.classList.toggle('open');
      });
    }
    if (overlay) {
      overlay.addEventListener('click', () => {
        sidebar.classList.remove('open');
        overlay.classList.remove('open');
      });
    }

    // Close sidebar on link click (mobile)
    document.querySelectorAll('.toc-item').forEach(link => {
      link.addEventListener('click', () => {
        sidebar.classList.remove('open');
        overlay.classList.remove('open');
      });
    });

    // Back to top
    const btt = document.getElementById('backToTop');
    window.addEventListener('scroll', () => {
      if (window.scrollY > 400) {
        btt.classList.add('visible');
      } else {
        btt.classList.remove('visible');
      }
    });
    btt.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // Active TOC highlighting
    const tocLinks = document.querySelectorAll('.toc-item');
    const headings = [];
    tocLinks.forEach(link => {
      const id = link.getAttribute('href').substring(1);
      const el = document.getElementById(id);
      if (el) headings.push({ el, link });
    });

    function updateActiveToc() {
      let current = null;
      for (const h of headings) {
        if (h.el.getBoundingClientRect().top <= 100) {
          current = h;
        }
      }
      tocLinks.forEach(l => l.classList.remove('active'));
      if (current) current.link.classList.add('active');
    }
    window.addEventListener('scroll', updateActiveToc);
    updateActiveToc();
    """


def build_page(title: str, page_subtitle: str, content_html: str, toc_html: str) -> str:
    css = get_css()
    js = get_js()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>BetVector — {title}</title>
  <style>{css}</style>
</head>
<body>
  <nav class="top-nav">
    <a href="index.html" class="logo">BetVector</a>
    <span class="page-title">{page_subtitle}</span>
    <button class="hamburger" id="hamburger">&#9776;</button>
  </nav>

  <div class="sidebar-overlay" id="overlay"></div>

  <div class="layout">
    <aside class="sidebar" id="sidebar">
      <div class="toc-title">Contents</div>
      {toc_html}
    </aside>
    <main class="content">
      {content_html}
    </main>
  </div>

  <button class="back-to-top" id="backToTop" title="Back to top">&uarr;</button>

  <script>{js}</script>
</body>
</html>"""


def main():
    root = Path(__file__).parent

    # --- Master Plan ---
    mp_path = root / "betvector_masterplan.md"
    mp_md = mp_path.read_text(encoding="utf-8")
    mp_content, mp_toc = md_to_html(mp_md, doc_type="masterplan")
    mp_toc_html = build_toc_html(mp_toc)
    mp_html = build_page("Master Plan", "Master Plan · v1.0", mp_content, mp_toc_html)
    out_mp = root / "betvector_masterplan.html"
    out_mp.write_text(mp_html, encoding="utf-8")
    print(f"Written: {out_mp}  ({len(mp_html):,} bytes)")

    # --- Build Plan ---
    bp_path = root / "betvector_buildplan.md"
    bp_md = bp_path.read_text(encoding="utf-8")
    bp_content, bp_toc = md_to_html(bp_md, doc_type="buildplan")
    bp_toc_html = build_toc_html(bp_toc)
    bp_html = build_page("Build Plan", "Build Plan · v1.0", bp_content, bp_toc_html)
    out_bp = root / "betvector_buildplan.html"
    out_bp.write_text(bp_html, encoding="utf-8")
    print(f"Written: {out_bp}  ({len(bp_html):,} bytes)")


if __name__ == "__main__":
    main()
