"""
Document Ingestion, Classification, and Extraction Endpoints.

Supports:
1. Mixed Document Upload: Automatically classifies any mixture of POs, Invoices, and Receipts.
2. Individual Document Upload: Explicit document_type override (INVOICE, PURCHASE_ORDER, RECEIPT).
3. Server-side Directory Ingestion: Batch ingest all documents from a folder.
"""
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Depends, Query
from fastapi.responses import FileResponse

from ingestion import ingest_document, classify_document
from extraction import extract_document
from schemas.document_classification import DocumentType
from validation import (
    verify_invoice_math,
    verify_purchase_order_math,
    verify_receipt_math,
)
from api.schemas import (
    DocumentItemSchema,
    DocumentUploadResponse,
    IngestDirectoryRequest,
    SupportedTypesResponse,
    DocumentContentResponse,
)

router = APIRouter(prefix="/documents", tags=["Documents"])

UPLOAD_CACHE_DIR = Path("data") / "uploads"
UPLOAD_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _process_single_file(
    file_path: Path,
    original_name: str,
    doc_type_override: Optional[str] = None,
) -> DocumentItemSchema:
    """Ingests, classifies, extracts, and validates arithmetic on a single document."""
    # 1. Ingestion
    try:
        raw_doc = ingest_document(file_path)
    except Exception as exc:
        return DocumentItemSchema(
            file_name=original_name,
            file_path=str(file_path),
            document_type=DocumentType.UNKNOWN.value,
            confidence=0.0,
            extracted_data={},
            validation_status="INGESTION_ERROR",
            validation_errors=[str(exc)],
        )

    # 2. Classification
    if doc_type_override and doc_type_override.upper() not in ("AUTO", "UNKNOWN", ""):
        doc_type = doc_type_override.upper()
        confidence = 1.0
    else:
        try:
            class_res = classify_document(raw_doc)
            doc_type = class_res.document_type.value.upper()
            confidence = class_res.confidence
        except Exception:
            doc_type = DocumentType.UNKNOWN.value.upper()
            confidence = 0.0

    if doc_type == DocumentType.UNKNOWN.value.upper():
        return DocumentItemSchema(
            file_name=original_name,
            file_path=str(file_path),
            document_type=doc_type,
            confidence=confidence,
            extracted_data={},
            validation_status="INVALID_DOCUMENT",
            validation_errors=["Invalid file: Unrelated or unrecognized document type."],
        )

    # 3. Extraction
    extracted = {}
    try:
        extracted = extract_document(raw_doc, doc_type)
        if isinstance(extracted, dict):
            extracted["_source_file"] = str(file_path)
    except Exception as exc:
        return DocumentItemSchema(
            file_name=original_name,
            file_path=str(file_path),
            document_type=doc_type,
            confidence=confidence,
            extracted_data={},
            validation_status="EXTRACTION_ERROR",
            validation_errors=[str(exc)],
        )

    # 4. Arithmetic Validation
    val_status = "VALID"
    val_errors: List[str] = []
    try:
        if doc_type == DocumentType.INVOICE.value.upper() and extracted:
            val_res = verify_invoice_math(extracted)
            if not val_res.get("is_valid", True):
                val_status = "INVALID_MATH"
                val_errors = [d.get("message", str(d)) if isinstance(d, dict) else str(d) for d in val_res.get("discrepancies", [])]
        elif doc_type == DocumentType.PURCHASE_ORDER.value.upper() and extracted:
            val_res = verify_purchase_order_math(extracted)
            if not val_res.get("is_valid", True):
                val_status = "INVALID_MATH"
                val_errors = [d.get("message", str(d)) if isinstance(d, dict) else str(d) for d in val_res.get("discrepancies", [])]
        elif doc_type == DocumentType.RECEIPT.value.upper() and extracted:
            val_res = verify_receipt_math(extracted)
            if not val_res.get("is_valid", True):
                val_status = "INVALID_MATH"
                val_errors = [d.get("message", str(d)) if isinstance(d, dict) else str(d) for d in val_res.get("discrepancies", [])]
    except Exception as exc:
        val_status = "VALIDATION_ERROR"
        val_errors = [str(exc)]

    return DocumentItemSchema(
        file_name=original_name,
        file_path=str(file_path),
        document_type=doc_type,
        confidence=confidence,
        extracted_data=extracted,
        validation_status=val_status,
        validation_errors=val_errors,
    )


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_documents(
    files: List[UploadFile] = File(
        ...,
        description="One or more files (mixed PO, Invoice, Receipt or individual files).",
    ),
    document_type: Optional[str] = Form(
        None,
        description="Optional explicit type: 'PURCHASE_ORDER', 'INVOICE', 'RECEIPT', or 'AUTO'",
    ),
):
    """
    Ingest, classify, and extract structured data from uploaded files.
    - If `document_type` is specified, enforces that type on individual uploads.
    - If `document_type` is omitted or 'AUTO', automatically classifies each document.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided for upload.")

    results: List[DocumentItemSchema] = []
    for upload in files:
        temp_dest = UPLOAD_CACHE_DIR / upload.filename
        with open(temp_dest, "wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)

        item = _process_single_file(
            file_path=temp_dest,
            original_name=upload.filename,
            doc_type_override=document_type,
        )
        results.append(item)

    return DocumentUploadResponse(
        total_uploaded=len(results),
        documents=results,
    )


@router.post("/ingest-directory", response_model=DocumentUploadResponse)
def ingest_directory(payload: IngestDirectoryRequest):
    """
    Ingests and processes all matching documents from a server-side directory.
    """
    dir_p = Path(payload.directory_path)
    if not dir_p.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Directory '{payload.directory_path}' does not exist.",
        )

    matching_files = sorted(dir_p.glob(payload.file_pattern))
    if not matching_files:
        return DocumentUploadResponse(total_uploaded=0, documents=[])

    results: List[DocumentItemSchema] = []
    for p in matching_files:
        if p.is_file():
            item = _process_single_file(
                file_path=p,
                original_name=p.name,
            )
            results.append(item)

    return DocumentUploadResponse(
        total_uploaded=len(results),
        documents=results,
    )


@router.get("/supported-types", response_model=SupportedTypesResponse)
def get_supported_types():
    """Returns the supported document categories and file formats."""
    return SupportedTypesResponse(
        supported_types=["PURCHASE_ORDER", "INVOICE", "RECEIPT"],
        supported_extensions=[".txt", ".pdf", ".png", ".jpg", ".jpeg", ".tiff"],
    )


def _locate_document_file(file_name: Optional[str] = None, file_path: Optional[str] = None) -> Optional[Path]:
    """Resolves a document file path across uploads, mock datasets, and data roots."""
    search_dirs = [
        UPLOAD_CACHE_DIR,
        Path("data") / "uploads",
        Path("dataset") / "mock_reconciliation_100" / "mixed_documents",
        Path("dataset") / "mock_reconciliation",
        Path("data"),
        Path("dataset"),
    ]

    if file_path:
        p = Path(file_path)
        if p.is_file():
            return p
        for sdir in search_dirs:
            cand = sdir / p.name
            if cand.is_file():
                return cand

    if file_name:
        fn = Path(file_name).name
        for sdir in search_dirs:
            if sdir.is_dir():
                cand = sdir / fn
                if cand.is_file():
                    return cand
                for match in sdir.glob(fn):
                    if match.is_file():
                        return match

    search_name = Path(file_name).name if file_name else (Path(file_path).name if file_path else None)
    if search_name:
        for sdir in search_dirs:
            if sdir.is_dir():
                for match in sdir.rglob(search_name):
                    if match.is_file():
                        return match

    return None


@router.get("/raw")
def get_document_raw(
    file_name: Optional[str] = Query(None),
    file_path: Optional[str] = Query(None),
):
    """
    Streams the raw document file (PDF, image, text) for inline in-browser inspection.
    """
    target = _locate_document_file(file_name, file_path)
    if not target or not target.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Document '{file_name or file_path}' was not found on server.",
        )

    suf = target.suffix.lower()
    media_types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".txt": "text/plain; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json",
    }
    media_type = media_types.get(suf, "application/octet-stream")

    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=target.name,
        content_disposition_type="inline",
    )


@router.get("/content", response_model=DocumentContentResponse)
def get_document_content(
    file_path: Optional[str] = None,
    file_name: Optional[str] = None,
):
    """
    Safely retrieves the text content of a source document for in-browser inspection.
    Searches by explicit path or by file name within the project data/ directory.
    """
    target = _locate_document_file(file_name, file_path)

    if not target or not target.exists():
        fname = file_name or (Path(file_path).name if file_path else "document.txt")
        lname = fname.lower()
        if "po" in lname or "purchase" in lname:
            doc_type = "PURCHASE_ORDER"
        elif "inv" in lname or "invoice" in lname:
            doc_type = "INVOICE"
        elif "rec" in lname or "receipt" in lname or "gr" in lname:
            doc_type = "RECEIPT"
        else:
            doc_type = "UNKNOWN"

        content = (
            f"================================================================================\n"
            f"SOURCE DOCUMENT: {fname}\n"
            f"Category: {doc_type}\n"
            f"--------------------------------------------------------------------------------\n"
            f"[Document text is unavailable for preview: File '{fname}' was not found\n"
            f" in local storage or upload cache. Upload this document via the upload panel.]\n"
            f"================================================================================\n"
        )

        return DocumentContentResponse(
            file_name=fname,
            file_path=str(Path("data") / fname),
            content=content,
            file_size_bytes=len(content.encode("utf-8")),
            is_binary=False,
            document_type=doc_type,
        )

    try:
        if target.suffix.lower() == ".pdf":
            try:
                ingested = ingest_document(target)
                content = ingested.text
                is_binary = False
            except Exception:
                content = target.read_text(encoding="utf-8", errors="replace")
                is_binary = False
        else:
            content = target.read_text(encoding="utf-8", errors="replace")
            is_binary = False
    except Exception:
        content = f"[Binary or unreadable content for {target.name}]"
        is_binary = True

    lname = target.name.lower()
    doc_type = "UNKNOWN"
    if "po" in lname or "purchase" in lname:
        doc_type = "PURCHASE_ORDER"
    elif "inv" in lname or "invoice" in lname:
        doc_type = "INVOICE"
    elif "rec" in lname or "receipt" in lname or "gr" in lname:
        doc_type = "RECEIPT"

    return DocumentContentResponse(
        file_name=target.name,
        file_path=str(target),
        content=content,
        file_size_bytes=target.stat().st_size if target.exists() else len(content),
        is_binary=is_binary,
        document_type=doc_type,
    )

