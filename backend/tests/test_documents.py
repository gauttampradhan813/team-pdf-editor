"""Tests for document upload, management, page rendering and storage.

All PDFs are generated programmatically with PyMuPDF; no external sample
files are required.
"""

from __future__ import annotations

import io
import time

import pymupdf
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.storage import DocumentStorage

client = TestClient(app)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def make_pdf(pages: int = 1, title: str = "Test Doc") -> bytes:
    """Return a valid multi-page PDF as bytes."""
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"{title} - page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def upload_pdf(pages: int = 1, filename: str = "test.pdf", content_type: str = "application/pdf"):
    """POST a PDF and return the response + parsed JSON."""
    data = make_pdf(pages)
    response = client.post(
        "/documents",
        files={"file": (filename, io.BytesIO(data), content_type)},
    )
    return response, response.json()


# -----------------------------------------------------------------------
# Task 2 — POST /documents
# -----------------------------------------------------------------------

def test_valid_pdf_upload_returns_record():
    response, body = upload_pdf(pages=3)
    assert response.status_code == 201, body
    assert "document_id" in body
    assert body["filename"] == "test.pdf"
    assert body["file_size"] > 0
    assert body["page_count"] == 3
    assert "metadata" in body
    assert isinstance(body["document_id"], str)
    assert len(body["document_id"]) >= 16  # unpredictable, hex uuid


def test_upload_wrong_extension_rejected():
    data = make_pdf()
    response = client.post(
        "/documents",
        files={"file": ("document.txt", io.BytesIO(data), "application/pdf")},
    )
    assert response.status_code == 400, response.json()
    body = response.json()
    assert "error" in body


def test_upload_wrong_mime_rejected():
    data = make_pdf()
    response = client.post(
        "/documents",
        files={"file": ("document.pdf", io.BytesIO(data), "text/plain")},
    )
    assert response.status_code == 400, response.json()


def test_upload_empty_file_rejected():
    response = client.post(
        "/documents",
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert response.status_code == 400, response.json()


def test_upload_corrupted_pdf_rejected():
    # Starts with %PDF- (passes header check) but is garbage to pikepdf.
    corrupted = b"%PDF-1.7\nthis is not a valid pdf structure at all"
    response = client.post(
        "/documents",
        files={"file": ("bad.pdf", io.BytesIO(corrupted), "application/pdf")},
    )
    assert response.status_code == 422, response.json()


def test_upload_truncated_pdf_rejected():
    truncated = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    response = client.post(
        "/documents",
        files={"file": ("truncated.pdf", io.BytesIO(truncated), "application/pdf")},
    )
    assert response.status_code == 422, response.json()


# -----------------------------------------------------------------------
# Task 3 — Document management
# -----------------------------------------------------------------------

def test_get_document_metadata():
    _, body = upload_pdf(pages=2)
    doc_id = body["document_id"]

    response = client.get(f"/documents/{doc_id}")
    assert response.status_code == 200, response.json()
    meta = response.json()
    assert meta["document_id"] == doc_id
    assert meta["page_count"] == 2
    assert meta["filename"] == "test.pdf"


def test_get_missing_document_404():
    response = client.get("/documents/nonexistent-id-12345")
    assert response.status_code == 404, response.json()
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "not_found"


def test_download_document():
    _, body = upload_pdf(pages=1)
    doc_id = body["document_id"]

    response = client.get(f"/documents/{doc_id}/download")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")


def test_download_missing_document_404():
    response = client.get("/documents/nonexistent-id/download")
    assert response.status_code == 404, response.json()


def test_delete_document():
    _, body = upload_pdf(pages=1)
    doc_id = body["document_id"]

    response = client.delete(f"/documents/{doc_id}")
    assert response.status_code == 204, response.text

    # Gone for good.
    response = client.get(f"/documents/{doc_id}")
    assert response.status_code == 404


def test_delete_missing_document_404():
    response = client.delete("/documents/nonexistent-id-12345")
    assert response.status_code == 404, response.json()


# -----------------------------------------------------------------------
# Task 4 — Page rendering
# -----------------------------------------------------------------------

def test_render_page_returns_png():
    _, body = upload_pdf(pages=2)
    doc_id = body["document_id"]

    response = client.get(f"/documents/{doc_id}/pages/1.png")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_page_second_page():
    _, body = upload_pdf(pages=3)
    doc_id = body["document_id"]

    response = client.get(f"/documents/{doc_id}/pages/3.png")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_invalid_page_number_404():
    _, body = upload_pdf(pages=2)
    doc_id = body["document_id"]

    response = client.get(f"/documents/{doc_id}/pages/99.png")
    assert response.status_code == 404, response.json()
    body = response.json()
    assert "error" in body

    response = client.get(f"/documents/{doc_id}/pages/0.png")
    assert response.status_code == 404, response.json()


def test_render_missing_document_404():
    response = client.get("/documents/nonexistent-id/pages/1.png")
    assert response.status_code == 404, response.json()


def test_render_scale_parameter():
    _, body = upload_pdf(pages=1)
    doc_id = body["document_id"]

    response_default = client.get(f"/documents/{doc_id}/pages/1.png")
    response_zoom = client.get(f"/documents/{doc_id}/pages/1.png?scale=2.0")

    assert response_default.status_code == 200
    assert response_zoom.status_code == 200
    # Higher scale = larger image
    assert len(response_zoom.content) > len(response_default.content)


# -----------------------------------------------------------------------
# Task 5 — Storage cleanup
# -----------------------------------------------------------------------

def test_storage_cleanup_removes_expired():
    """Documents older than TTL are removed by cleanup_expired."""
    storage = DocumentStorage()
    storage.ttl_seconds = 1  # expires after 1 second

    data = make_pdf()
    record = storage.store("cleanup-test.pdf", data, 1, {})
    assert storage.exists(record.document_id)

    time.sleep(1.1)  # let it age past the TTL
    deleted = storage.cleanup_expired()
    assert deleted >= 1
    assert not storage.exists(record.document_id)


def test_storage_cleanup_keeps_recent():
    """Recently stored documents survive cleanup with a long TTL."""
    storage = DocumentStorage()
    storage.ttl_seconds = 86400  # 1 day

    data = make_pdf()
    record = storage.store("recent.pdf", data, 1, {})
    assert storage.exists(record.document_id)

    deleted = storage.cleanup_expired()
    assert deleted == 0
    assert storage.exists(record.document_id)


def test_document_id_uniqueness():
    _, body1 = upload_pdf(filename="a.pdf")
    _, body2 = upload_pdf(filename="b.pdf")
    assert body1["document_id"] != body2["document_id"]


def test_metadata_is_dict():
    _, body = upload_pdf(pages=1)
    assert isinstance(body["metadata"], dict)
