# Doc Editor

A browser-based document editor with live preview and PDF generation.

## Features

- **Markdown mode**: Edit `.md` files with live preview
- **HTML mode**: Edit `.html` files with iframe preview
- **Template mode**: Edit markdown and render through styled HTML templates for PDF generation
- **PDF generation**: Uses headless Chrome to generate PDFs from HTML or templated markdown
- **PDF page estimate**: Shows a live estimated PDF page count for Markdown files
- **Keyboard shortcuts**: `Cmd+S` to save, `Cmd+P` to generate PDF

## Usage

Start the server:

```bash
python3 server.py
```

Then open in browser:

```
# Markdown editing
http://localhost:8888/doc-editor.html?file=/path/to/file.md

# HTML editing
http://localhost:8888/doc-editor.html?file=/path/to/file.html

# Template mode (markdown → styled PDF)
http://localhost:8888/doc-editor.html?file=/path/to/file.md&template=answerlayer-branded.html
```

## Templates

Templates live in the `templates/` directory. They're HTML files with placeholders:

- `{{title}}` - Document title from frontmatter
- `{{content}}` - Rendered markdown content
- `<!-- Populated from frontmatter -->` - Meta info (client, date, version)

Current templates include:

- `answerlayer-sow.html` - Original branded proposal/SOW template
- `answerlayer-sow-readable.html` - Same branded styling with serif headings and sans-serif body text
- `answerlayer-legal.html` - Legal/document-heavy template

### Frontmatter

Markdown files can include YAML frontmatter:

```markdown
---
title: Project Proposal
client: Acme Corp
date: 2026-03-18
version: 1.0
---

# Document content here...
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/load?file=PATH` | GET | Load file content |
| `/save?file=PATH` | POST | Save file content |
| `/preview-html?file=PATH` | GET | Serve HTML file for preview |
| `/render-markdown?template=NAME` | POST | Render markdown through template |
| `/estimate-pdf-pages?template=NAME` | POST | Estimate PDF page count for markdown |
| `/templates` | GET | List available templates |
| `/generate-pdf?html=PATH&pdf=PATH` | POST | Generate PDF from HTML |
| `/generate-pdf-from-markdown?file=PATH&pdf=PATH&template=NAME` | POST | Generate PDF from markdown |

## Requirements

- Python 3
- Google Chrome (for PDF generation)

## Configuration

Edit `server.py` to change:
- `CHROME_PATH` - Path to Chrome executable
- `TEMPLATES_DIR` - Path to templates directory
- Port (default: 8888)
