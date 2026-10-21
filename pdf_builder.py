import base64
import re
from pathlib import Path
import markdown
from xhtml2pdf import pisa

PDF_CSS = """
@page { size: A4; margin: 1.8cm; }
body { font-family: Helvetica; font-size: 10pt; line-height: 1.45; color: #0c0c0d; }
h1 { font-size: 18pt; color: #209dd7; border-bottom: 2px solid #0c0c0d; padding-bottom: 4px; }
h2 { font-size: 13pt; color: #753991; margin-top: 14px; }
h3 { font-size: 11pt; }
table { width: 100%; border: 1px solid #0c0c0d; margin: 6px 0; }
th { background-color: #f1f1ec; font-weight: bold; text-align: left; padding: 3px; }
td { padding: 3px; border-top: 1px solid #e1e1da; }
img { width: 16cm; }
.disclaimer { font-size: 8pt; color: #6f6f72; margin-top: 18px; }
"""


def _embed_images(html: str) -> str:
    """ Inline local images as base64, since xhtml2pdf blocks files outside the working folder """
    def to_data_uri(match):
        path = Path(match.group(1))
        if not path.is_file():
            return match.group(0)
        return f'src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}"'
    return re.sub(r'src="([^"]+\.png)"', to_data_uri, html)


def build_pdf(report_markdown: str, path: str) -> str:
    """ Convert the markdown report (with local image paths) into a PDF """
    body = _embed_images(markdown.markdown(report_markdown, extensions=["tables"]))
    html = f"<html><head><style>{PDF_CSS}</style></head><body>{body}</body></html>"
    with open(path, "wb") as f:
        result = pisa.CreatePDF(html, dest=f)
    if result.err:
        raise RuntimeError("PDF generation failed")
    return path
