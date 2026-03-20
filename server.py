from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os
import json
import subprocess
import re
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PANDOC_PATH = "/usr/local/bin/pandoc"
TEMPLATES_DIR = os.path.join(SCRIPT_DIR, "templates")

def parse_frontmatter(content):
    """Extract YAML frontmatter and body from markdown."""
    frontmatter = {}
    body = content

    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            yaml_str = parts[1].strip()
            body = parts[2].strip()
            # Simple YAML parsing (key: value)
            for line in yaml_str.split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    frontmatter[key.strip()] = val.strip()

    return frontmatter, body

def markdown_to_html(md):
    """Convert markdown to HTML (basic conversion)."""
    html = md

    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

    # Links - must be done before bold/italic to avoid conflicts
    # Handle markdown links [text](url) - URL can contain special chars like ? # & =
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html)

    # Bold
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)

    # Italic
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)

    # Blockquotes (for highlight boxes)
    lines = html.split('\n')
    in_blockquote = False
    result = []
    for line in lines:
        if line.startswith('> '):
            if not in_blockquote:
                result.append('<blockquote>')
                in_blockquote = True
            result.append('<p>' + line[2:] + '</p>')
        else:
            if in_blockquote:
                result.append('</blockquote>')
                in_blockquote = False
            result.append(line)
    if in_blockquote:
        result.append('</blockquote>')
    html = '\n'.join(result)

    # Horizontal rules
    html = re.sub(r'^---+$', '<hr>', html, flags=re.MULTILINE)

    # Tables
    html = convert_tables(html)

    # Lists
    html = convert_lists(html)

    # Paragraphs - wrap remaining text blocks
    html = wrap_paragraphs(html)

    return html

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
    """Convert markdown lists to HTML."""
    lines = html.split('\n')
    result = []
    in_list = False
    list_type = None

    for line in lines:
        # Unordered list
        ul_match = re.match(r'^[\-\*] (.+)$', line.strip())
        # Ordered list
        ol_match = re.match(r'^\d+\. (.+)$', line.strip())

        if ul_match:
            if not in_list or list_type != 'ul':
                if in_list:
                    result.append(f'</{list_type}>')
                result.append('<ul>')
                in_list = True
                list_type = 'ul'
            result.append(f'<li>{ul_match.group(1)}</li>')
        elif ol_match:
            if not in_list or list_type != 'ol':
                if in_list:
                    result.append(f'</{list_type}>')
                result.append('<ol>')
                in_list = True
                list_type = 'ol'
            result.append(f'<li>{ol_match.group(1)}</li>')
        else:
            if in_list and line.strip() == '':
                result.append(f'</{list_type}>')
                in_list = False
                list_type = None
            result.append(line)

    if in_list:
        result.append(f'</{list_type}>')

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
    frontmatter, body = parse_frontmatter(markdown_content)

    # Convert markdown to HTML
    content_html = markdown_to_html(body)

    # Build meta section
    meta_html = ''
    if frontmatter.get('client'):
        meta_html += f"<strong>Prepared for:</strong> {frontmatter['client']}<br>"
    if frontmatter.get('date'):
        meta_html += f"<strong>Date:</strong> {frontmatter['date']}<br>"
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
    if frontmatter.get('client'):
        footer_parts.append(f"Prepared for {frontmatter['client']}")
    if frontmatter.get('date'):
        footer_parts.append(frontmatter['date'])
    footer_meta = ' · '.join(footer_parts)
    html = re.sub(r'<span id="footer-meta"></span>', f'<span id="footer-meta">{footer_meta}</span>', html)

    return html, None

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
            template = params.get('template', ['answerlayer-sow.html'])[0]
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
                result = subprocess.run([
                    CHROME_PATH,
                    "--headless=new",
                    "--disable-gpu",
                    f"--print-to-pdf={pdf_path}",
                    "--no-pdf-header-footer",
                    "--no-margins",
                    html_path
                ], capture_output=True, text=True, timeout=30)

                if os.path.exists(pdf_path):
                    size = os.path.getsize(pdf_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'path': pdf_path, 'size': size})
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
            template = params.get('template', ['answerlayer-sow.html'])[0]

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

        elif parsed.path == '/generate-pdf-from-markdown':
            # Generate PDF from markdown using a template
            params = parse_qs(parsed.query)
            md_path = params.get('file', [None])[0]
            pdf_path = params.get('pdf', [None])[0]
            template = params.get('template', ['answerlayer-sow.html'])[0]

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
            html, error = render_template(template, markdown_content)
            if error:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(error.encode('utf-8'))
                return

            # Write to temp HTML file
            temp_html = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
            temp_html.write(html)
            temp_html.close()

            try:
                result = subprocess.run([
                    CHROME_PATH,
                    "--headless=new",
                    "--disable-gpu",
                    f"--print-to-pdf={pdf_path}",
                    "--no-pdf-header-footer",
                    "--no-margins",
                    temp_html.name
                ], capture_output=True, text=True, timeout=30)

                if os.path.exists(pdf_path):
                    size = os.path.getsize(pdf_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = json.dumps({'success': True, 'path': pdf_path, 'size': size})
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
                os.unlink(temp_html.name)

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
            template = params.get('template', ['answerlayer-sow.html'])[0]
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

        else:
            self.send_response(404)
            self.end_headers()

os.chdir(SCRIPT_DIR)
print('Doc editor running at http://localhost:8888')
print('Usage: http://localhost:8888/doc-editor.html?file=/path/to/file.md')
HTTPServer(('0.0.0.0', 8888), Handler).serve_forever()
