"""
Document Ingestion Boundary for ReconAgent.

Provides a unified ingestion layer that abstracts file formats and physical data reading
away from downstream classification, extraction, and orchestration components.

Handles:
- Plain text (.txt) decoding with UTF-8 and fallback encodings.
- Digital PDF (.pdf) text layer extraction and page counting via pypdf.
- Scanned PDF detection (empty text layer flagging for multimodal/OCR handling).
- Image files (.jpg, .jpeg, .png, .webp) validation via PIL.
- Corrupt/unsupported file containment and structured metadata tracking.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Union, Dict, Any, Tuple

from pydantic import BaseModel, Field
from pypdf import PdfReader
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger("DocumentIngestion")

# Maximum permitted file size before skipping (25 MB)
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
TEXT_EXTENSIONS = {".txt", ".csv", ".tsv", ".json", ".log"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
PDF_EXTENSIONS = {".pdf"}


class IngestedDocument(BaseModel):
    """
    Standardized in-memory representation of an ingested physical document.
    """
    file_path: Path = Field(description="Resolved path to the local document file.")
    file_name: str = Field(description="Name of the file including extension.")
    file_type: str = Field(description="Normalized file type: 'txt', 'pdf', 'image', or 'unknown'.")
    extension: str = Field(description="Lowercase file extension, e.g. '.pdf'.")
    text_content: Optional[str] = Field(default=None, description="Extracted digital text content if available.")
    page_count: int = Field(default=1, ge=0, description="Total number of document pages.")
    has_text: bool = Field(default=False, description="True if substantial digital text is extracted.")
    is_scanned: bool = Field(default=False, description="True if document has no text layer or is an image.")
    file_size_bytes: int = Field(default=0, ge=0, description="Size of file on disk in bytes.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Technical metadata (PDF headers, dimensions, etc.)")

    class Config:
        arbitrary_types_allowed = True

    def get_raw_bytes(self) -> bytes:
        """Reads and returns the raw file bytes on demand."""
        return self.file_path.read_bytes()


def extract_pdf_text(file_path: Union[str, Path]) -> Tuple[Optional[str], int, Dict[str, Any]]:
    """
    Extracts digital text, page count, and metadata from a PDF file using pypdf.
    Returns (extracted_text, page_count, metadata_dict).
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found: {path}")

    try:
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        pages_text = []

        for idx, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text()
                if page_text:
                    pages_text.append(page_text)
            except Exception as page_err:
                logger.warning(f"Error extracting text from page {idx+1} of {path.name}: {page_err}")

        full_text = "\n\n".join(pages_text).strip() if pages_text else None
        
        pdf_metadata = {}
        if reader.metadata:
            for k, v in reader.metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    pdf_metadata[str(k)] = v

        return full_text, page_count, pdf_metadata

    except Exception as exc:
        logger.error(f"Failed to read PDF '{path.name}' with pypdf: {exc}")
        return None, 0, {"error": str(exc)}


def ingest_document(
    file_path: Union[str, Path],
    extract_text: bool = True
) -> IngestedDocument:
    """
    Ingests a document from disk, normalizes its file type, extracts digital text layers
    when present, detects scanned files/images, and gathers structural metadata.

    Args:
        file_path: Absolute or relative path to the physical document.
        extract_text: If True, automatically extracts digital text from TXT and PDF documents.

    Returns:
        IngestedDocument containing structured text and metadata.
    """
    path = Path(file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Document does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Path is not a regular file: {path}")

    file_size = path.stat().st_size
    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File '{path.name}' exceeds maximum allowed size ({file_size} > {MAX_FILE_SIZE_BYTES} bytes)"
        )

    ext = path.suffix.lower()
    file_name = path.name

    # -------------------------------------------------------------------------
    # 1. Plain Text Documents (.txt, .csv, .json, etc.)
    # -------------------------------------------------------------------------
    if ext in TEXT_EXTENSIONS:
        text: Optional[str] = None
        encoding_used = "utf-8"
        if extract_text:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    text = path.read_text(encoding="latin1")
                    encoding_used = "latin1"
                except Exception:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    encoding_used = "utf-8-replace"

        has_substantive_text = bool(text and len(text.strip()) >= 15)
        return IngestedDocument(
            file_path=path,
            file_name=file_name,
            file_type="txt",
            extension=ext,
            text_content=text,
            page_count=1,
            has_text=has_substantive_text,
            is_scanned=False,
            file_size_bytes=file_size,
            metadata={"encoding": encoding_used},
        )

    # -------------------------------------------------------------------------
    # 2. PDF Documents (.pdf)
    # -------------------------------------------------------------------------
    elif ext in PDF_EXTENSIONS:
        text = None
        page_count = 1
        pdf_meta: Dict[str, Any] = {}

        if extract_text:
            text, page_count, pdf_meta = extract_pdf_text(path)

        # If text is extracted and has >= 20 non-whitespace characters, it's digital
        has_substantive_text = bool(text and len(text.strip()) >= 20)
        is_scanned = not has_substantive_text

        return IngestedDocument(
            file_path=path,
            file_name=file_name,
            file_type="pdf",
            extension=ext,
            text_content=text,
            page_count=page_count,
            has_text=has_substantive_text,
            is_scanned=is_scanned,
            file_size_bytes=file_size,
            metadata=pdf_meta,
        )

    # -------------------------------------------------------------------------
    # 3. Image Documents (.jpg, .png, .webp, etc.)
    # -------------------------------------------------------------------------
    elif ext in IMAGE_EXTENSIONS:
        img_meta: Dict[str, Any] = {}
        try:
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img:
                img_meta = {
                    "format": img.format,
                    "mode": img.mode,
                    "width": img.width,
                    "height": img.height,
                }
        except (UnidentifiedImageError, Exception) as img_err:
            logger.warning(f"Unidentified or corrupted image '{path.name}': {img_err}")
            img_meta = {"corrupted": True, "error": str(img_err)}

        return IngestedDocument(
            file_path=path,
            file_name=file_name,
            file_type="image",
            extension=ext,
            text_content=None,
            page_count=1,
            has_text=False,
            is_scanned=True,  # Images require OCR / Gemini Vision for text extraction
            file_size_bytes=file_size,
            metadata=img_meta,
        )

    # -------------------------------------------------------------------------
    # 4. Unknown / Fallback
    # -------------------------------------------------------------------------
    else:
        # Attempt fallback text read for arbitrary extensions
        text = None
        has_text = False
        if extract_text:
            try:
                raw_head = path.read_bytes()[:512]
                # If bytes don't contain excessive null bytes, try text decode
                if b"\x00" not in raw_head:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    has_text = bool(text and len(text.strip()) >= 15)
            except Exception:
                pass

        return IngestedDocument(
            file_path=path,
            file_name=file_name,
            file_type="unknown",
            extension=ext,
            text_content=text,
            page_count=1,
            has_text=has_text,
            is_scanned=not has_text,
            file_size_bytes=file_size,
            metadata={"unknown_format": True},
        )

