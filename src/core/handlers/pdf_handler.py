"""
PDF content handler -- extracted from summarize_news5.py.

Downloads a PDF from a URL and extracts text using PyPDF2.
"""

import asyncio
import io
import logging
import re
import traceback
from urllib.parse import urlparse

import certifi
import requests

from src.security.url_validator import SecurityError, validate_url

try:
    import PyPDF2

    PDF_LIBRARY = "pypdf2"
except ImportError:
    PDF_LIBRARY = None

logger = logging.getLogger(__name__)


def normalize_pdf_url(url: str) -> str:
    """Return a direct PDF URL when a hosting page wraps the PDF.

    GitHub ``/blob/`` URLs render an HTML file viewer.  Convert them to the
    corresponding raw URL so the PDF extractor receives actual PDF bytes.
    """
    parsed = urlparse(url)
    if parsed.netloc.lower() == "github.com":
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 5 and parts[2] == "blob" and parts[-1].lower().endswith(".pdf"):
            owner, repo, _, branch = parts[:4]
            rest = "/".join(parts[4:])
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{rest}"
    return url


def is_pdf_url(url: str) -> bool:
    """Return True when *url* points to a PDF or a known PDF wrapper page."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith(".pdf"):
        return True
    return normalize_pdf_url(url) != url


async def get_pdf_content(url: str) -> str:
    """Extract text from a PDF at *url*.

    Returns the full text of all pages joined by double newlines,
    or an empty string on failure.
    """
    url = normalize_pdf_url(url)

    # SSRF protection: validate URL before fetching
    try:
        validate_url(url)
    except (SecurityError, ValueError) as e:
        logger.warning(f"[PDF] URL validation failed | {e} | url={url[:80]}")
        return ""

    if PDF_LIBRARY is None:
        logger.warning("[PDF] PyPDF2 not installed")
        return ""

    logger.info(f"[PDF] starting extraction | URL: {url[:80]}...")

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/pdf,*/*",
        }

        # Download with retries
        max_retries = 3
        response = None
        for attempt in range(max_retries):
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.get(url, headers=headers, verify=certifi.where(), timeout=30, stream=True),
                )

                if response.status_code == 200:
                    logger.info(f"[PDF] download OK | attempt:{attempt + 1}/{max_retries}")
                    break
                else:
                    logger.warning(
                        f"[PDF] download failed | status:{response.status_code} | attempt:{attempt + 1}/{max_retries}"
                    )
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                logger.warning(f"[PDF] download error | attempt:{attempt + 1}/{max_retries} | err:{e}")

            if attempt < max_retries - 1:
                await asyncio.sleep(2)
        else:
            status = response.status_code if response else "N/A"
            logger.error(f"[PDF] all retries exhausted | status:{status}")
            return ""

        # Verify content type
        content_type = response.headers.get("Content-Type", "").lower()
        if "pdf" not in content_type:
            logger.warning(f"[PDF] not a PDF | Content-Type:{content_type}")
            return ""

        # Extract text with PyPDF2
        pdf_file = io.BytesIO(response.content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)

        text_content: list[str] = []
        total_pages = len(pdf_reader.pages)
        logger.info(f"[PDF] {total_pages} pages")

        for page_num in range(total_pages):
            page = pdf_reader.pages[page_num]
            text = page.extract_text()
            if text:
                text_content.append(text)

        full_text = "\n\n".join(text_content)

        # Clean
        full_text = re.sub(r"\s+", " ", full_text).strip()
        full_text = "".join(ch for ch in full_text if ch.isprintable() or ch.isspace())

        logger.info(f"[PDF] extraction OK | len:{len(full_text)}")
        return full_text

    except Exception as e:
        logger.error(f"[PDF] extraction error: {e}")
        traceback.print_exc()
        return ""
