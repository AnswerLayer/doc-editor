from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib import request as urlrequest, error as urlerror
from html import escape
import os
import json
import subprocess
import re
import tempfile
import time
import unicodedata
import shutil
import hashlib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PANDOC_PATH = "/opt/homebrew/bin/pandoc"
TEMPLATES_DIR = os.path.join(SCRIPT_DIR, "templates")
COMMENTS_DIR = os.path.join(SCRIPT_DIR, "comment_data")
DEFAULT_AI_BASE_URL = os.getenv("DOC_EDITOR_AI_BASE_URL") or os.getenv("RLMKIT_BASE_URL") or "http://127.0.0.1:8082/v1"
DEFAULT_AI_API_KEY = os.getenv("DOC_EDITOR_AI_API_KEY") or os.getenv("RLMKIT_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
DEFAULT_AI_MODEL = os.getenv("DOC_EDITOR_AI_MODEL") or os.getenv("DOC_EDITOR_MODEL") or ""

def parse_frontmatter(content):
    """Extract YAML frontmatter and body from markdown."""
    frontmatter = {}
    body = content
    body_start = 0

    if content.startswith('---'):
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n?', content, flags=re.DOTALL)
        if match:
            yaml_str = match.group(1)
            body_start = match.end()
            body = content[body_start:]
            for line in yaml_str.split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    frontmatter[key.strip()] = val.strip()

    return frontmatter, body, body_start

def inline_markdown_to_html(text):
    """Convert a markdown inline string to HTML."""
    placeholders = {}

    def replace_code(match):
        key = f'@@INLINECODE{len(placeholders)}@@'
        placeholders[key] = f'<code>{escape(match.group(1))}</code>'
        return key

    html = re.sub(r'`([^`\n]+)`', replace_code, text)
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    html = re.sub(r'__(.+?)__', r'<strong>\1</strong>', html)
    html = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<em>\1</em>', html)

    for key, value in placeholders.items():
        html = html.replace(key, value)

    return html

def wrap_source_block(html, start, end, block_type):
    """Wrap a rendered block with source span metadata."""
    return (
        f'<div class="source-block" style="display: contents;" '
        f'data-source-start="{start}" data-source-end="{end}" data-source-type="{block_type}">{html}</div>'
    )

def split_markdown_blocks(md, source_offset=0):
    """Split markdown into coarse source-addressable blocks."""
    lines = md.splitlines(True)
    blocks = []
    position = source_offset
    index = 0

    def stripped(index_value):
        return lines[index_value].rstrip('\n')

    while index < len(lines):
        line = lines[index]
        line_start = position
        line_end = position + len(line)
        bare = stripped(index)
        trimmed = bare.strip()

        if trimmed == '':
            position = line_end
            index += 1
            continue

        if trimmed.startswith('```'):
            block_lines = [line]
            position = line_end
            index += 1
            while index < len(lines):
                next_line = lines[index]
                block_lines.append(next_line)
                position += len(next_line)
                closing = next_line.rstrip('\n').strip()
                index += 1
                if closing.startswith('```'):
                    break
            raw = ''.join(block_lines)
            blocks.append({'type': 'code', 'start': line_start, 'end': line_start + len(raw), 'raw': raw})
            continue

        if re.match(r'^#{1,6}\s+', bare):
            raw = line
            blocks.append({'type': 'heading', 'start': line_start, 'end': line_end, 'raw': raw})
            position = line_end
            index += 1
            continue

        if re.match(r'^---+\s*$', trimmed):
            raw = line
            blocks.append({'type': 'hr', 'start': line_start, 'end': line_end, 'raw': raw})
            position = line_end
            index += 1
            continue

        if bare.lstrip().startswith('>'):
            block_lines = [line]
            position = line_end
            index += 1
            while index < len(lines):
                next_bare = stripped(index)
                if next_bare.strip() == '' or not next_bare.lstrip().startswith('>'):
                    break
                next_line = lines[index]
                block_lines.append(next_line)
                position += len(next_line)
                index += 1
            raw = ''.join(block_lines)
            blocks.append({'type': 'blockquote', 'start': line_start, 'end': line_start + len(raw), 'raw': raw})
            continue

        if bare.strip().startswith('|') and index + 1 < len(lines) and re.match(r'^[\|\s\-:]+$', stripped(index + 1).strip()):
            block_lines = [line]
            position = line_end
            index += 1
            while index < len(lines):
                next_bare = stripped(index)
                if not next_bare.strip().startswith('|'):
                    break
                next_line = lines[index]
                block_lines.append(next_line)
                position += len(next_line)
                index += 1
            raw = ''.join(block_lines)
            blocks.append({'type': 'table', 'start': line_start, 'end': line_start + len(raw), 'raw': raw})
            continue

        if re.match(r'^(\s*)([-*]|\d+(?:\.\d+)*\.?)\s+', bare):
            block_lines = [line]
            position = line_end
            index += 1
            while index < len(lines):
                next_bare = stripped(index)
                if next_bare.strip() == '':
                    break
                if not re.match(r'^(\s*)([-*]|\d+(?:\.\d+)*\.?)\s+', next_bare):
                    break
                next_line = lines[index]
                block_lines.append(next_line)
                position += len(next_line)
                index += 1
            raw = ''.join(block_lines)
            blocks.append({'type': 'list', 'start': line_start, 'end': line_start + len(raw), 'raw': raw})
            continue

        block_lines = [line]
        position = line_end
        index += 1
        while index < len(lines):
            next_bare = stripped(index)
            if next_bare.strip() == '':
                break
            if re.match(r'^#{1,6}\s+', next_bare) or re.match(r'^---+\s*$', next_bare.strip()) or next_bare.lstrip().startswith('>') or next_bare.strip().startswith('```'):
                break
            if next_bare.strip().startswith('|') and index + 1 < len(lines) and re.match(r'^[\|\s\-:]+$', stripped(index + 1).strip()):
                break
            if re.match(r'^(\s*)([-*]|\d+(?:\.\d+)*\.?)\s+', next_bare):
                break
            next_line = lines[index]
            block_lines.append(next_line)
            position += len(next_line)
            index += 1

        raw = ''.join(block_lines)
        blocks.append({'type': 'paragraph', 'start': line_start, 'end': line_start + len(raw), 'raw': raw})

    return blocks

def render_code_block(raw):
    """Render a fenced code block."""
    lines = raw.splitlines()
    language = ''
    if lines:
        opening = lines[0].strip()
        language = opening[3:].strip() if opening.startswith('```') else ''
    code_lines = lines[1:-1] if len(lines) >= 2 and lines[-1].strip().startswith('```') else lines[1:]
    language_attr = f' class="language-{escape(language)}"' if language else ''
    return f'<pre><code{language_attr}>{escape("\n".join(code_lines))}</code></pre>'

def render_blockquote_block(raw):
    """Render a blockquote block."""
    parts = []
    for line in raw.splitlines():
        content = re.sub(r'^\s*>\s?', '', line)
        parts.append(f'<p>{inline_markdown_to_html(content)}</p>')
    return '<blockquote>' + ''.join(parts) + '</blockquote>'

def render_table_block(raw):
    """Render a markdown table block."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return ''

    rows = [[inline_markdown_to_html(cell.strip()) for cell in line.strip('|').split('|')] for line in lines]
    header = rows[0]
    body_rows = rows[2:] if len(rows) > 1 and re.match(r'^[\|\s\-:]+$', lines[1]) else rows[1:]

    html = ['<table>', '<tr>' + ''.join(f'<th>{cell}</th>' for cell in header) + '</tr>']
    html.extend('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in body_rows)
    html.append('</table>')
    return ''.join(html)

def render_list_block(raw):
    """Render a markdown list block."""
    lines = raw.splitlines()
    result = []
    list_stack = []

    def close_lists(min_indent=-1):
        while list_stack and list_stack[-1]['indent'] >= min_indent:
            current = list_stack.pop()
            if current['li_open']:
                result.append('</li>')
            result.append(f"</{current['type']}>")

    def ensure_list(indent, list_type):
        if not list_stack:
            result.append(f'<{list_type}>')
            list_stack.append({'indent': indent, 'type': list_type, 'li_open': False})
            return

        current = list_stack[-1]
        if indent > current['indent']:
            result.append(f'<{list_type}>')
            list_stack.append({'indent': indent, 'type': list_type, 'li_open': False})
            return

        while list_stack and indent < list_stack[-1]['indent']:
            current = list_stack.pop()
            if current['li_open']:
                result.append('</li>')
            result.append(f"</{current['type']}>")

        if not list_stack:
            result.append(f'<{list_type}>')
            list_stack.append({'indent': indent, 'type': list_type, 'li_open': False})
            return

        current = list_stack[-1]
        if current['type'] != list_type:
            if current['li_open']:
                result.append('</li>')
            result.append(f"</{current['type']}>")
            list_stack.pop()
            result.append(f'<{list_type}>')
            list_stack.append({'indent': indent, 'type': list_type, 'li_open': False})

    for line in lines:
        list_match = re.match(r'^(\s*)([-*]|\d+(?:\.\d+)*\.?)\s+(.+)$', line)
        if not list_match:
            continue

        indent = len(list_match.group(1).replace('\t', '    '))
        marker = list_match.group(2)
        list_type = 'ul' if marker in ('-', '*') else 'ol'
        content = inline_markdown_to_html(list_match.group(3))

        ensure_list(indent, list_type)
        current = list_stack[-1]
        if current['li_open']:
            result.append('</li>')
        marker_attr = f' data-marker="{escape(marker)}"' if list_type == 'ol' else ''
        result.append(f'<li{marker_attr}>{content}')
        current['li_open'] = True

    if list_stack:
        close_lists(0)

    return ''.join(result)

def markdown_to_html(md, source_offset=0):
    """Convert markdown to HTML with source span metadata."""
    slug_counts = {}
    blocks = split_markdown_blocks(md, source_offset=source_offset)
    rendered_blocks = []

    for block in blocks:
        raw = block['raw']
        block_type = block['type']

        if block_type == 'heading':
            match = re.match(r'^(#{1,6})\s+(.+?)\s*$', raw.rstrip('\n'))
            if not match:
                continue
            level = len(match.group(1))
            html = render_heading(level, inline_markdown_to_html(match.group(2)), slug_counts)
        elif block_type == 'paragraph':
            lines = [inline_markdown_to_html(line) for line in raw.rstrip('\n').split('\n')]
            html = '<p>' + '<br>\n'.join(lines) + '</p>'
        elif block_type == 'blockquote':
            html = render_blockquote_block(raw)
        elif block_type == 'table':
            html = render_table_block(raw)
        elif block_type == 'list':
            html = render_list_block(raw)
        elif block_type == 'code':
            html = render_code_block(raw)
        elif block_type == 'hr':
            html = '<hr>'
        else:
            continue

        rendered_blocks.append(wrap_source_block(html, block['start'], block['end'], block_type))

    return '\n'.join(rendered_blocks)

def extract_fenced_code_blocks(text):
    """Replace fenced code blocks with placeholders until paragraph wrapping is done."""
    placeholders = {}

    def replace(match):
        key = f'@@BLOCKCODE{len(placeholders)}@@'
        language = match.group(1).strip().split()[0] if match.group(1).strip() else ''
        language_attr = f' class="language-{escape(language)}"' if language else ''
        code_html = f'<pre><code{language_attr}>{escape(match.group(2))}</code></pre>'
        placeholders[key] = code_html
        return key

    pattern = re.compile(r'^```([^\n`]*)\n(.*?)\n```[ \t]*$', flags=re.MULTILINE | re.DOTALL)
    return pattern.sub(replace, text), placeholders

def restore_placeholders(text, placeholders):
    """Restore placeholder HTML after markdown block processing."""
    for placeholder, html in placeholders.items():
        text = text.replace(placeholder, html)
    return text

def slugify_heading(text):
    """Generate a stable anchor slug similar to markdown heading IDs."""
    normalized = unicodedata.normalize('NFKD', text)
    ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
    slug = ascii_text.lower()
    slug = re.sub(r'<[^>]+>', '', slug)
    slug = re.sub(r'[`*_~\[\]()]+', '', slug)
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug).strip('-')
    return slug or 'section'

def render_heading(level, text, slug_counts):
    """Render a heading tag with a deterministic ID for TOC anchors."""
    base_slug = slugify_heading(text)
    count = slug_counts.get(base_slug, 0)
    slug_counts[base_slug] = count + 1
    slug = base_slug if count == 0 else f'{base_slug}-{count}'
    return f'<h{level} id="{slug}">{text}</h{level}>'

def convert_tables(html):
    """Convert markdown tables to HTML."""
    lines = html.split('\n')
    result = []
    in_table = False
    header_done = False

    for i, line in enumerate(lines):
        if '|' in line and line.strip().startswith('|'):
            cells = [c.strip() for c in line.strip().strip('|').split('|')]

            # Check if next line is separator
            if not in_table:
                if i + 1 < len(lines) and re.match(r'^[\|\s\-:]+$', lines[i + 1]):
                    result.append('<table>')
                    result.append('<tr>' + ''.join(f'<th>{c}</th>' for c in cells) + '</tr>')
                    in_table = True
                    header_done = False
                    continue

            # Skip separator line
            if re.match(r'^[\|\s\-:]+$', line):
                header_done = True
                continue

            if in_table:
                result.append('<tr>' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr>')
        else:
            if in_table:
                result.append('</table>')
                in_table = False
                header_done = False
            result.append(line)

    if in_table:
        result.append('</table>')

    return '\n'.join(result)

def convert_lists(html):
    """Convert markdown lists to HTML, preserving nested indentation."""
    lines = html.split('\n')
    result = []
    list_stack = []

    def close_lists(min_indent=-1):
        while list_stack and list_stack[-1]['indent'] >= min_indent:
            current = list_stack.pop()
            if current['li_open']:
                result.append('</li>')
            result.append(f"</{current['type']}>")

    def ensure_list(indent, list_type):
        if not list_stack:
            result.append(f'<{list_type}>')
            list_stack.append({'indent': indent, 'type': list_type, 'li_open': False})
            return

        current = list_stack[-1]
        if indent > current['indent']:
            if current['li_open']:
                result.append(f'<{list_type}>')
                list_stack.append({'indent': indent, 'type': list_type, 'li_open': False})
            else:
                result.append(f'<{list_type}>')
                list_stack.append({'indent': indent, 'type': list_type, 'li_open': False})
            return

        while list_stack and indent < list_stack[-1]['indent']:
            current = list_stack.pop()
            if current['li_open']:
                result.append('</li>')
            result.append(f"</{current['type']}>")

        if not list_stack:
            result.append(f'<{list_type}>')
            list_stack.append({'indent': indent, 'type': list_type, 'li_open': False})
            return

        current = list_stack[-1]
        if current['type'] != list_type:
            if current['li_open']:
                result.append('</li>')
            result.append(f"</{current['type']}>")
            list_stack.pop()
            result.append(f'<{list_type}>')
            list_stack.append({'indent': indent, 'type': list_type, 'li_open': False})

    for line in lines:
        list_match = re.match(r'^(\s*)([-*]|\d+(?:\.\d+)*\.?) (.+)$', line)

        if list_match:
            indent = len(list_match.group(1).replace('\t', '    '))
            marker = list_match.group(2)
            list_type = 'ul' if marker in ('-', '*') else 'ol'
            content = list_match.group(3)

            ensure_list(indent, list_type)

            current = list_stack[-1]
            if current['li_open']:
                result.append('</li>')
            marker_attr = f' data-marker="{escape(marker)}"' if list_type == 'ol' else ''
            result.append(f'<li{marker_attr}>{content}')
            current['li_open'] = True
        else:
            if list_stack:
                close_lists(0)
            result.append(line)

    if list_stack:
        close_lists(0)

    return '\n'.join(result)

def wrap_paragraphs(html):
    """Wrap plain text lines in <p> tags, grouping consecutive lines."""
    lines = html.split('\n')
    result = []
    current_para = []

    # Block-level elements that shouldn't be wrapped in <p>
    block_tags = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'li',
                  'table', 'tr', 'td', 'th', 'blockquote', 'hr', 'div', 'pre')

    def is_block_element(line):
        s = line.strip().lower()
        if s.startswith('@@blockcode'):
            return True
        if not s.startswith('<'):
            return False
        # Check if it starts with a block tag
        for tag in block_tags:
            if s.startswith(f'<{tag}') or s.startswith(f'</{tag}'):
                return True
        return False

    def flush_para():
        if current_para:
            # Join lines with <br> for line breaks within paragraph
            result.append('<p>' + '<br>\n'.join(current_para) + '</p>')
            current_para.clear()

    for line in lines:
        stripped = line.strip()
        # Check if line is a block element or header marker
        if is_block_element(line) or stripped.startswith('#'):
            flush_para()
            result.append(line)
        elif stripped == '':
            flush_para()
            # Keep empty line for spacing
            result.append('')
        else:
            current_para.append(line)

    flush_para()
    return '\n'.join(result)

def render_template(template_name, markdown_content):
    """Render markdown content through a template."""
    template_path = os.path.join(TEMPLATES_DIR, template_name)

    if not os.path.exists(template_path):
        return None, f"Template not found: {template_name}"

    with open(template_path, 'r') as f:
        template = f.read()

    # Parse frontmatter
    frontmatter, body, body_start = parse_frontmatter(markdown_content)

    # Convert markdown to HTML
    content_html = markdown_to_html(body, source_offset=body_start)

    prepared_for = frontmatter.get('prepared for') or frontmatter.get('client')

    # Build meta section
    meta_html = ''
    if prepared_for:
        meta_html += f"<strong>Prepared for:</strong> {prepared_for}<br>"
    if frontmatter.get('date'):
        meta_html += f"<strong>Date:</strong> {frontmatter['date']}<br>"
    if frontmatter.get('status'):
        meta_html += f"<strong>Status:</strong> {frontmatter['status']}<br>"
    if frontmatter.get('version'):
        meta_html += f"<strong>Version:</strong> {frontmatter['version']}"

    # Replace placeholders
    title = frontmatter.get('title', 'Document')
    html = template.replace('{{title}}', title)
    html = html.replace('{{content}}', content_html)

    # Inject meta
    html = html.replace('<!-- Populated from frontmatter -->', meta_html)

    # Footer meta
    footer_parts = []
    if prepared_for:
        footer_parts.append(f"Prepared for {prepared_for}")
    if frontmatter.get('date'):
        footer_parts.append(frontmatter['date'])
    if frontmatter.get('status'):
        footer_parts.append(frontmatter['status'])
    footer_meta = ' · '.join(footer_parts)
    html = re.sub(r'<span id="footer-meta"></span>', f'<span id="footer-meta">{footer_meta}</span>', html)

    return html, None

def generate_pdf_from_html(html_path, pdf_path):
    """Render a PDF from an HTML file with headless Chrome."""
    subprocess.run([
        CHROME_PATH,
        "--headless=new",
        "--disable-gpu",
        f"--print-to-pdf={pdf_path}",
        "--no-pdf-header-footer",
        "--no-margins",
        html_path
    ], capture_output=True, text=True, timeout=30)

def get_pdf_page_count(pdf_path):
    """Read PDF page count through Spotlight metadata, with a raw PDF fallback."""
    result = subprocess.run([
        "/usr/bin/mdls",
        "-raw",
        "-name",
        "kMDItemNumberOfPages",
        pdf_path
    ], capture_output=True, text=True, timeout=10)

    value = result.stdout.strip()
    if value.isdigit():
        return int(value)

    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()

    # Fallback for non-indexed files such as temp PDFs in /tmp.
    page_matches = re.findall(rb'/Type\s*/Page\b', pdf_bytes)
    if page_matches:
        return len(page_matches)

    raise ValueError(f"Unable to determine page count for {pdf_path}: {value or result.stderr.strip()}")

def render_markdown_to_temp_html(template_name, markdown_content):
    """Render markdown through a template into a temporary HTML file."""
    html, error = render_template(template_name, markdown_content)
    if error:
        return None, error

    temp_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
    temp_html.write(html)
    temp_html.close()
    return temp_html.name, None

def estimate_pdf_pages(template_name, markdown_content):
    """Estimate PDF page count by rendering the templated markdown to a temporary PDF."""
    temp_html_path, error = render_markdown_to_temp_html(template_name, markdown_content)
    if error:
        return None, error

    temp_pdf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    temp_pdf.close()

    try:
        generate_pdf_from_html(temp_html_path, temp_pdf.name)

        # Spotlight metadata can lag slightly after file creation.
        last_error = None
        for _ in range(10):
            try:
                return get_pdf_page_count(temp_pdf.name), None
            except Exception as exc:
                last_error = exc
                time.sleep(0.1)

        return None, str(last_error or 'Unable to determine PDF page count')
    except subprocess.TimeoutExpired:
        return None, 'PDF estimation timed out'
    except Exception as exc:
        return None, str(exc)
    finally:
        if os.path.exists(temp_html_path):
            os.unlink(temp_html_path)
        if os.path.exists(temp_pdf.name):
            os.unlink(temp_pdf.name)

def read_json_body(handler):
    """Read a JSON request body from the HTTP handler."""
    length = int(handler.headers.get('Content-Length', 0))
    if length <= 0:
        raise ValueError('No request body provided')
    body = handler.rfile.read(length).decode('utf-8')
    return json.loads(body)

def sanitize_comment_records(raw_comments):
    """Normalize a comment list to the fields the editor supports."""
    if not isinstance(raw_comments, list):
        raise ValueError('Comments payload must be an array')

    comments = []
    for item in raw_comments:
        if not isinstance(item, dict):
            continue

        comment_id = item.get('id')
        comment_text = item.get('comment')
        start = item.get('start')
        end = item.get('end')

        if not isinstance(comment_id, str) or not isinstance(comment_text, str):
            continue
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start < 0 or end <= start:
            continue

        comments.append({
            'id': comment_id,
            'start': start,
            'end': end,
            'excerpt': item.get('excerpt') if isinstance(item.get('excerpt'), str) else '',
            'comment': comment_text,
            'createdAt': item.get('createdAt') if isinstance(item.get('createdAt'), str) else '',
        })

    comments.sort(key=lambda item: item.get('createdAt') or '', reverse=True)
    return comments

def get_comment_store_path(file_path):
    """Build a stable sidecar JSON path for a source document."""
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError('A file path is required to persist comments')

    normalized_path = os.path.abspath(file_path)
    digest = hashlib.sha256(normalized_path.encode('utf-8')).hexdigest()[:12]
    basename = os.path.basename(normalized_path)
    stem, _ = os.path.splitext(basename)
    safe_stem = re.sub(r'[^A-Za-z0-9._-]+', '-', stem).strip('-') or 'document'
    os.makedirs(COMMENTS_DIR, exist_ok=True)
    return os.path.join(COMMENTS_DIR, f'{safe_stem}-{digest}.comments.json')

def load_comment_store(file_path):
    """Load the persisted comment sidecar for a document."""
    comments_path = get_comment_store_path(file_path)
    if not os.path.exists(comments_path):
        return {
            'version': 1,
            'sourceFile': os.path.abspath(file_path),
            'commentsPath': comments_path,
            'updatedAt': None,
            'comments': [],
        }

    with open(comments_path, 'r') as f:
        payload = json.load(f)

    comments = sanitize_comment_records(payload.get('comments', []))
    return {
        'version': 1,
        'sourceFile': payload.get('sourceFile') or os.path.abspath(file_path),
        'commentsPath': comments_path,
        'updatedAt': payload.get('updatedAt'),
        'comments': comments,
    }

def save_comment_store(file_path, comments):
    """Persist comments for a document to a sidecar JSON file."""
    normalized_path = os.path.abspath(file_path)
    comments_path = get_comment_store_path(normalized_path)
    payload = {
        'version': 1,
        'sourceFile': normalized_path,
        'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'comments': sanitize_comment_records(comments),
    }

    temp_path = comments_path + '.tmp'
    with open(temp_path, 'w') as f:
        json.dump(payload, f, indent=2)
        f.write('\n')
    os.replace(temp_path, comments_path)

    payload['commentsPath'] = comments_path
    return payload

def get_openai_compatible_model(base_url, api_key):
    """Resolve a model name from an OpenAI-compatible /models endpoint."""
    return get_openai_compatible_models(base_url, api_key)[0]

def get_openai_compatible_models(base_url, api_key):
    """Fetch model ids from an OpenAI-compatible /models endpoint."""
    models_url = base_url.rstrip('/') + '/models'
    req = urlrequest.Request(models_url, method='GET')
    if api_key:
        req.add_header('Authorization', f'Bearer {api_key}')

    with urlrequest.urlopen(req, timeout=10) as response:
        payload = json.loads(response.read().decode('utf-8'))

    data = payload.get('data')
    if not isinstance(data, list) or not data:
        raise ValueError('No models returned by AI endpoint')

    model_ids = [item.get('id') for item in data if isinstance(item, dict) and item.get('id')]
    if not model_ids:
        raise ValueError('Model list did not include an id')
    return model_ids

def normalize_model_output(content):
    """Normalize chat completion content to a plain string."""
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get('text')
                if text:
                    parts.append(text)
        return ''.join(parts).strip()

    return str(content).strip()

def build_comment_edit_prompt(full_text, selected_text, comment, file_path=None):
    """Build a prompt for rewriting selected text according to an editor comment."""
    return (
        "You are editing a document. Rewrite only the selected text so it addresses the editor comment.\n"
        "Preserve surrounding document consistency, formatting style, and markdown conventions when relevant.\n"
        "Return only the replacement text, with no explanation, no code fences, and no quotation marks around it.\n\n"
        f"File path: {file_path or 'unknown'}\n\n"
        f"Editor comment:\n{comment}\n\n"
        f"Selected text to rewrite:\n<<<SELECTED>>>\n{selected_text}\n<<<END_SELECTED>>>\n\n"
        f"Full document for context:\n<<<DOCUMENT>>>\n{full_text}\n<<<END_DOCUMENT>>>"
    )

def run_claude_subscription_edit(prompt, model=None):
    """Use Claude Code CLI with claude.ai subscription auth."""
    env = os.environ.copy()
    env.pop('ANTHROPIC_API_KEY', None)
    command = ['claude', '-p']
    if model:
        command.extend(['--model', model])
    command.append(prompt)

    result = subprocess.run(command, capture_output=True, text=True, timeout=180, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Claude CLI failed')
    output = result.stdout.strip()
    if not output:
        raise RuntimeError('Claude CLI returned empty output')
    return output

def run_codex_subscription_edit(prompt, model=None):
    """Use Codex CLI with ChatGPT login auth."""
    env = os.environ.copy()
    env.pop('OPENAI_API_KEY', None)
    temp_output = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    temp_output.close()

    command = [
        'codex', 'exec',
        '--skip-git-repo-check',
        '-C', SCRIPT_DIR,
        '--color', 'never',
        '-o', temp_output.name,
    ]
    if model:
        command.extend(['--model', model])
    command.append(prompt)

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=240, env=env)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Codex CLI failed')
        with open(temp_output.name, 'r') as f:
            output = f.read().strip()
        if not output:
            raise RuntimeError('Codex CLI returned empty output')
        return output
    finally:
        if os.path.exists(temp_output.name):
            os.unlink(temp_output.name)

def run_openai_compatible_edit(prompt, model=None):
    """Use an OpenAI-compatible endpoint such as the local MLX server."""
    base_url = DEFAULT_AI_BASE_URL.rstrip('/')
    api_key = DEFAULT_AI_API_KEY
    resolved_model = model or DEFAULT_AI_MODEL or get_openai_compatible_model(base_url, api_key)

    payload = {
        'model': resolved_model,
        'temperature': 0.2,
        'messages': [
            {
                'role': 'user',
                'content': prompt,
            },
        ],
    }

    req = urlrequest.Request(
        base_url + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    if api_key:
        req.add_header('Authorization', f'Bearer {api_key}')

    try:
        with urlrequest.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode('utf-8'))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'AI request failed: {detail or exc.reason}') from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f'AI endpoint unavailable at {base_url}: {exc.reason}') from exc

    choices = result.get('choices')
    if not choices:
        raise RuntimeError('AI response did not include any choices')

    message = choices[0].get('message') or {}
    replacement_text = normalize_model_output(message.get('content'))
    if not replacement_text:
        raise RuntimeError('AI response was empty')

    return replacement_text

def get_ai_model_catalog():
    """Return available editor AI providers and models."""
    providers = []

    claude_path = shutil.which('claude')
    if claude_path:
        auth_method = 'unknown'
        authenticated = False
        subscription = None
        try:
            result = subprocess.run(['claude', 'auth', 'status'], capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                payload = json.loads(result.stdout)
                authenticated = bool(payload.get('loggedIn'))
                auth_method = payload.get('authMethod') or auth_method
                subscription = payload.get('subscriptionType')
        except Exception:
            pass

        providers.append({
            'id': 'claude-code',
            'label': 'Claude',
            'kind': 'subscription-cli',
            'available': authenticated,
            'detail': f'Claude Code via {auth_method}' + (f' ({subscription})' if subscription else ''),
            'models': [
                {'id': '', 'label': 'Default'},
                {'id': 'sonnet', 'label': 'Sonnet'},
                {'id': 'opus', 'label': 'Opus'},
            ],
        })

    codex_path = shutil.which('codex')
    if codex_path:
        authenticated = False
        detail = 'Codex CLI'
        try:
            result = subprocess.run(['codex', 'login', 'status'], capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                combined_output = (result.stdout + result.stderr).strip()
                authenticated = 'Logged in' in combined_output
                detail = combined_output or detail
        except Exception:
            pass

        providers.append({
            'id': 'codex',
            'label': 'Codex',
            'kind': 'subscription-cli',
            'available': authenticated,
            'detail': detail,
            'models': [
                {'id': '', 'label': 'Default'},
                {'id': 'gpt-5.4', 'label': 'GPT-5.4'},
                {'id': 'gpt-5.4-mini', 'label': 'GPT-5.4 Mini'},
            ],
        })

    mlx_models = []
    mlx_detail = f'OpenAI-compatible endpoint at {DEFAULT_AI_BASE_URL}'
    mlx_available = False
    try:
        mlx_models = get_openai_compatible_models(DEFAULT_AI_BASE_URL.rstrip('/'), DEFAULT_AI_API_KEY)
        mlx_available = True
    except Exception as exc:
        mlx_detail = f'{mlx_detail} ({exc})'

    providers.append({
        'id': 'mlx',
        'label': 'Local MLX',
        'kind': 'openai-compatible',
        'available': mlx_available,
        'detail': mlx_detail,
        'models': [{'id': model_id, 'label': model_id} for model_id in mlx_models],
    })

    return providers

def address_comment_with_ai(full_text, selection_start, selection_end, selected_text, comment, provider='mlx', model=None, file_path=None):
    """Rewrite a selected passage according to an editor comment."""
    span_text = full_text[selection_start:selection_end]
    if span_text != selected_text:
        raise ValueError('Selected text no longer matches the document.')

    if not selected_text.strip():
        raise ValueError('Selected text is empty.')

    prompt = build_comment_edit_prompt(
        full_text=full_text,
        selected_text=selected_text,
        comment=comment,
        file_path=file_path,
    )

    if provider == 'claude-code':
        return run_claude_subscription_edit(prompt, model=model or None)
    if provider == 'codex':
        return run_codex_subscription_edit(prompt, model=model or None)
    if provider == 'mlx':
        return run_openai_compatible_edit(prompt, model=model or None)

    raise ValueError(f'Unknown AI provider: {provider}')

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/load':
            params = parse_qs(parsed.query)
            filepath = params.get('file', [None])[0]
            if filepath and os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'File not found')

        elif parsed.path == '/preview-html':
            # Serve HTML file content for iframe preview
            params = parse_qs(parsed.query)
            filepath = params.get('file', [None])[0]
            if filepath and os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'File not found')

        elif parsed.path == '/render-markdown':
            # Render markdown through a template
            params = parse_qs(parsed.query)
            template = params.get('template', ['answerlayer-branded.html'])[0]
            # Content comes via POST, but we also support GET with file param
            filepath = params.get('file', [None])[0]

            if filepath and os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    markdown_content = f.read()
                html, error = render_template(template, markdown_content)
                if error:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(error.encode('utf-8'))
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.end_headers()
                    self.wfile.write(html.encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'File not found')

        elif parsed.path == '/templates':
            # List available templates
            templates = [f for f in os.listdir(TEMPLATES_DIR) if f.endswith('.html')]
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(templates).encode('utf-8'))

        elif parsed.path == '/ai-models':
            providers = get_ai_model_catalog()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(providers).encode('utf-8'))

        elif parsed.path == '/comments':
            params = parse_qs(parsed.query)
            filepath = params.get('file', [None])[0]

            try:
                if not filepath:
                    raise ValueError('Missing file parameter')

                payload = load_comment_store(filepath)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, **payload}).encode('utf-8'))
            except Exception as exc:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(exc)}).encode('utf-8'))

        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == '/save':
            params = parse_qs(parsed.query)
            filepath = params.get('file', [None])[0]

            if filepath:
                length = int(self.headers['Content-Length'])
                content = self.rfile.read(length).decode('utf-8')
                with open(filepath, 'w') as f:
                    f.write(content)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'OK')
                print(f'Saved: {filepath}')
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'No file specified')

        elif parsed.path == '/generate-pdf':
            params = parse_qs(parsed.query)
            html_path = params.get('html', [None])[0]
            pdf_path = params.get('pdf', [None])[0]

            if not html_path or not pdf_path:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing html or pdf parameter')
                return

            if not os.path.exists(html_path):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'HTML file not found')
                return

            try:
                generate_pdf_from_html(html_path, pdf_path)

                if os.path.exists(pdf_path):
                    size = os.path.getsize(pdf_path)
                    page_count = get_pdf_page_count(pdf_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'path': pdf_path, 'size': size, 'pageCount': page_count})
                    self.wfile.write(response.encode('utf-8'))
                    print(f'Generated PDF: {pdf_path} ({size} bytes)')
                else:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'PDF generation failed')
            except subprocess.TimeoutExpired:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'PDF generation timed out')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))

        elif parsed.path == '/render-markdown':
            # Render markdown through template (POST with body)
            params = parse_qs(parsed.query)
            template = params.get('template', ['answerlayer-branded.html'])[0]

            length = int(self.headers.get('Content-Length', 0))
            if length > 0:
                markdown_content = self.rfile.read(length).decode('utf-8')
                html, error = render_template(template, markdown_content)
                if error:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(error.encode('utf-8'))
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.end_headers()
                    self.wfile.write(html.encode('utf-8'))
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'No content provided')

        elif parsed.path == '/estimate-pdf-pages':
            params = parse_qs(parsed.query)
            template = params.get('template', ['midas-branded.html'])[0]

            length = int(self.headers.get('Content-Length', 0))
            if length > 0:
                markdown_content = self.rfile.read(length).decode('utf-8')
            else:
                md_path = params.get('file', [None])[0]
                if md_path and os.path.exists(md_path):
                    with open(md_path, 'r') as f:
                        markdown_content = f.read()
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'No content provided')
                    return

            page_count, error = estimate_pdf_pages(template, markdown_content)
            if error:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(error.encode('utf-8'))
            else:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': True, 'pageCount': page_count})
                self.wfile.write(response.encode('utf-8'))

        elif parsed.path == '/generate-pdf-from-markdown':
            # Generate PDF from markdown using a template
            params = parse_qs(parsed.query)
            md_path = params.get('file', [None])[0]
            pdf_path = params.get('pdf', [None])[0]
            template = params.get('template', ['answerlayer-branded.html'])[0]

            if not md_path or not pdf_path:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing file or pdf parameter')
                return

            # Read markdown content (may have been updated via POST body)
            length = int(self.headers.get('Content-Length', 0))
            if length > 0:
                markdown_content = self.rfile.read(length).decode('utf-8')
                # Save the markdown file
                with open(md_path, 'w') as f:
                    f.write(markdown_content)
            elif os.path.exists(md_path):
                with open(md_path, 'r') as f:
                    markdown_content = f.read()
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Markdown file not found')
                return

            # Render through template
            temp_html_path, error = render_markdown_to_temp_html(template, markdown_content)
            if error:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(error.encode('utf-8'))
                return

            try:
                generate_pdf_from_html(temp_html_path, pdf_path)

                if os.path.exists(pdf_path):
                    size = os.path.getsize(pdf_path)
                    page_count = get_pdf_page_count(pdf_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'path': pdf_path, 'size': size, 'pageCount': page_count})
                    self.wfile.write(response.encode('utf-8'))
                    print(f'Generated PDF from markdown: {pdf_path} ({size} bytes)')
                else:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'PDF generation failed')
            except subprocess.TimeoutExpired:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'PDF generation timed out')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
            finally:
                os.unlink(temp_html_path)

        elif parsed.path == '/generate-png':
            params = parse_qs(parsed.query)
            html_path = params.get('html', [None])[0]
            png_path = params.get('png', [None])[0]
            width = params.get('width', ['1200'])[0]
            height = params.get('height', ['800'])[0]

            if not html_path or not png_path:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing html or png parameter')
                return

            if not os.path.exists(html_path):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'HTML file not found')
                return

            try:
                result = subprocess.run([
                    CHROME_PATH,
                    "--headless=new",
                    "--disable-gpu",
                    f"--screenshot={png_path}",
                    f"--window-size={width},{height}",
                    html_path
                ], capture_output=True, text=True, timeout=30)

                if os.path.exists(png_path):
                    size = os.path.getsize(png_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'path': png_path, 'size': size})
                    self.wfile.write(response.encode('utf-8'))
                    print(f'Generated PNG: {png_path} ({size} bytes)')
                else:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'PNG generation failed')
            except subprocess.TimeoutExpired:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'PNG generation timed out')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))

        elif parsed.path == '/generate-png-from-markdown':
            params = parse_qs(parsed.query)
            md_path = params.get('file', [None])[0]
            png_path = params.get('png', [None])[0]
            template = params.get('template', ['answerlayer-branded.html'])[0]
            width = params.get('width', ['1200'])[0]
            height = params.get('height', ['800'])[0]

            if not md_path or not png_path:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing file or png parameter')
                return

            length = int(self.headers.get('Content-Length', 0))
            if length > 0:
                markdown_content = self.rfile.read(length).decode('utf-8')
                with open(md_path, 'w') as f:
                    f.write(markdown_content)
            elif os.path.exists(md_path):
                with open(md_path, 'r') as f:
                    markdown_content = f.read()
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Markdown file not found')
                return

            html, error = render_template(template, markdown_content)
            if error:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(error.encode('utf-8'))
                return

            temp_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            temp_html.write(html)
            temp_html.close()

            try:
                result = subprocess.run([
                    CHROME_PATH,
                    "--headless=new",
                    "--disable-gpu",
                    f"--screenshot={png_path}",
                    f"--window-size={width},{height}",
                    temp_html.name
                ], capture_output=True, text=True, timeout=30)

                if os.path.exists(png_path):
                    size = os.path.getsize(png_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'path': png_path, 'size': size})
                    self.wfile.write(response.encode('utf-8'))
                    print(f'Generated PNG from markdown: {png_path} ({size} bytes)')
                else:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'PNG generation failed')
            except subprocess.TimeoutExpired:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'PNG generation timed out')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
            finally:
                os.unlink(temp_html.name)

        elif parsed.path == '/generate-docx':
            params = parse_qs(parsed.query)
            html_path = params.get('html', [None])[0]
            docx_path = params.get('docx', [None])[0]

            if not html_path or not docx_path:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing html or docx parameter')
                return

            if not os.path.exists(html_path):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'HTML file not found')
                return

            try:
                result = subprocess.run([
                    PANDOC_PATH,
                    html_path,
                    "-o", docx_path
                ], capture_output=True, text=True, timeout=30)

                if os.path.exists(docx_path):
                    size = os.path.getsize(docx_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'path': docx_path, 'size': size})
                    self.wfile.write(response.encode('utf-8'))
                    print(f'Generated DOCX: {docx_path} ({size} bytes)')
                else:
                    self.send_response(500)
                    self.end_headers()
                    error_msg = result.stderr if result.stderr else 'DOCX generation failed'
                    self.wfile.write(error_msg.encode('utf-8'))
            except subprocess.TimeoutExpired:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'DOCX generation timed out')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))

        elif parsed.path == '/generate-docx-from-markdown':
            params = parse_qs(parsed.query)
            md_path = params.get('file', [None])[0]
            docx_path = params.get('docx', [None])[0]

            if not md_path or not docx_path:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing file or docx parameter')
                return

            length = int(self.headers.get('Content-Length', 0))
            if length > 0:
                markdown_content = self.rfile.read(length).decode('utf-8')
                with open(md_path, 'w') as f:
                    f.write(markdown_content)
            elif os.path.exists(md_path):
                pass  # Use existing file
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Markdown file not found')
                return

            try:
                # Pandoc can convert markdown directly to docx
                result = subprocess.run([
                    PANDOC_PATH,
                    md_path,
                    "-o", docx_path
                ], capture_output=True, text=True, timeout=30)

                if os.path.exists(docx_path):
                    size = os.path.getsize(docx_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'path': docx_path, 'size': size})
                    self.wfile.write(response.encode('utf-8'))
                    print(f'Generated DOCX from markdown: {docx_path} ({size} bytes)')
                else:
                    self.send_response(500)
                    self.end_headers()
                    error_msg = result.stderr if result.stderr else 'DOCX generation failed'
                    self.wfile.write(error_msg.encode('utf-8'))
            except subprocess.TimeoutExpired:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'DOCX generation timed out')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))

        elif parsed.path == '/ai-address-comment':
            try:
                payload = read_json_body(self)
                full_text = payload.get('fullText')
                selection_start = payload.get('selectionStart')
                selection_end = payload.get('selectionEnd')
                selected_text = payload.get('selectedText')
                comment = payload.get('comment')
                file_path = payload.get('filePath')
                provider = payload.get('provider') or 'mlx'
                model = payload.get('model') or None

                if not isinstance(full_text, str) or not isinstance(selected_text, str) or not isinstance(comment, str):
                    raise ValueError('Invalid request payload')
                if not isinstance(selection_start, int) or not isinstance(selection_end, int):
                    raise ValueError('Selection offsets must be integers')
                if selection_start < 0 or selection_end <= selection_start or selection_end > len(full_text):
                    raise ValueError('Selection offsets are out of range')

                replacement_text = address_comment_with_ai(
                    full_text=full_text,
                    selection_start=selection_start,
                    selection_end=selection_end,
                    selected_text=selected_text,
                    comment=comment,
                    provider=provider,
                    model=model,
                    file_path=file_path,
                )

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': True, 'replacementText': replacement_text, 'provider': provider, 'model': model})
                self.wfile.write(response.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                response = json.dumps({'success': False, 'error': str(e)})
                self.wfile.write(response.encode('utf-8'))

        elif parsed.path == '/comments':
            try:
                payload = read_json_body(self)
                file_path = payload.get('filePath')
                comments = payload.get('comments')
                if not isinstance(file_path, str) or not file_path:
                    raise ValueError('filePath is required')

                saved = save_comment_store(file_path, comments)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, **saved}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))

        else:
            self.send_response(404)
            self.end_headers()

os.chdir(SCRIPT_DIR)
print('Doc editor running at http://localhost:8888')
print('Usage: http://localhost:8888/doc-editor.html?file=/path/to/file.md')
HTTPServer(('0.0.0.0', 8888), Handler).serve_forever()
