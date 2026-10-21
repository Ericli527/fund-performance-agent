import base64
import re
from pathlib import Path
from xhtml2pdf import pisa


def _embed_images(html: str) -> str:
    """ Inline local images as base64, since xhtml2pdf blocks files outside the working folder """
    def to_data_uri(match):
        path = Path(match.group(1))
        if not path.is_file():
            return match.group(0)
        return f'src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}"'
    return re.sub(r'src="([^"]+\.png)"', to_data_uri, html)


def build_pdf(html: str, path: str) -> str:
    """ Convert the report HTML (with local image paths) into a PDF """
    with open(path, "wb") as f:
        result = pisa.CreatePDF(_embed_images(html), dest=f)
    if result.err:
        raise RuntimeError("PDF generation failed")
    return path
