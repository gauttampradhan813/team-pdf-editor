"""Document upload, metadata, download and deletion endpoints."""

from __future__ import annotations

import io
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from app.config import get_settings
from app.storage import DocumentNotFoundError, DocumentStorage, StorageError

router = APIRouter(tags=["documents"])

storage = DocumentStorage()

# --- Allowed upload constraints ---
ALLOWED_EXTENSION = ".pdf"
ALLOWED_MIME_TYPES = {"application/pdf"}

# Try to use python-magic for content sniffing; fall back to header check.
try:
    import magic as _magic  # noqa: F401

    HAS_MAGIC = True
except ImportError:  # pragma: no cover - optional dependency
    HAS_MAGIC = False


def _looks_like_pdf(data: bytes) -> bool:
    """Cheap header check: PDF files start with %PDF-."""
    return data.startswith(b"%PDF-")


def _validate_pdf_content(data: bytes) -> tuple[int, dict]:
    """Strictly validate PDF structure and return (page_count, metadata).

    Uses pikepdf for structural integrity (catches truncated / garbage
    files that PyMuPDF may silently open) and PyMuPDF for page count.
    Raises ValueError on any invalid input.
    """
    import pikepdf
    import pymupdf

    # pikepdf is the strict gatekeeper.
    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            pikepdf_pages = len(pdf.pages)
    except Exception as exc:  # pikepdf.PikepdfError, PdfError, etc.
        raise ValueError("Invalid or corrupted PDF file") from exc

    # PyMuPDF confirms page count > 0 and gives us metadata.
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            page_count = doc.page_count
            metadata = dict(doc.metadata or {})
    except Exception as exc:  # pymupdf.FileDataError, EmptyFileError, etc.
        raise ValueError("Invalid or corrupted PDF file") from exc

    if page_count == 0:
        raise ValueError("PDF contains no pages")

    return page_count, metadata


@router.post(
    "/documents",
    summary="Upload a PDF document",
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(file: UploadFile = File(...)) -> JSONResponse:
    """Accept a PDF upload, validate it, store it, and return its record."""
    settings = get_settings()

    # --- 1. Extension check ---
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_EXTENSION):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted",
        )

    # --- 2. MIME type check ---
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid MIME type: {content_type or 'missing'}",
        )

    # --- 3. Read + size enforcement ---
    data = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File exceeds {settings.max_upload_size_mb} MB limit "
                f"(received {len(data) / 1024 / 1024:.1f} MB)"
            ),
        )

    # --- 4. Content sniffing (optional magic) ---
    if HAS_MAGIC:
        try:
            import magic

            detected = magic.from_buffer(data, mime=True)
            if detected not in ALLOWED_MIME_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Content does not look like a PDF (detected: {detected})",
                )
        except HTTPException:
            raise
        except Exception:
            # Magic library failure is not a reason to reject; fall through.
            pass
    elif not _looks_like_pdf(data):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File does not appear to be a PDF",
        )

    # --- 5. Strict PDF validation ---
    try:
        page_count, metadata = _validate_pdf_content(data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # --- 6. Store ---
    try:
        record = storage.store(filename, data, page_count, metadata)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "document_id": record.document_id,
            "filename": record.filename,
            "file_size": record.size,
            "page_count": record.page_count,
            "metadata": record.metadata,
            "created_at": record.created_at,
        },
    )


@router.get(
    "/documents/{document_id}",
    summary="Get document metadata",
)
def get_document(document_id: str) -> JSONResponse:
    """Return the stored record for a document id."""
    try:
        record = storage.get(document_id)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document not found: {document_id}",
        )
    return JSONResponse(content=record.to_dict())


@router.get(
    "/documents/{document_id}/download",
    summary="Download the original PDF",
)
def download_document(document_id: str) -> FileResponse:
    """Stream the original PDF file back to the client."""
    try:
        record = storage.get(document_id)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document not found: {document_id}",
        )

    path = storage._pdf_path(document_id)  # noqa: SLF001 - internal helper used deliberately
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file is missing",
        )

    return FileResponse(
        path=path,
        media_type="application/pdf",
        filename=record.filename,
    )


@router.delete(
    "/documents/{document_id}",
    summary="Delete a document",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(document_id: str) -> None:
    """Permanently delete a document and its cached pages."""
    try:
        storage.delete(document_id)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document not found: {document_id}",
        )
    return None
