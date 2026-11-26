"""Tests for page operations: rotate, delete, reorder.

All PDFs are generated programmatically with PyMuPDF; no external sample
files are required.
"""

from __future__ import annotations

import io

import pikepdf
import pymupdf
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def make_pdf(pages: int = 3, title: str = "Test Doc") -> bytes:
    """Return a valid multi-page PDF as bytes."""
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"{title} - page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def upload_pdf(pages: int = 3, filename: str = "test.pdf"):
    data = make_pdf(pages)
    response = client.post(
        "/documents",
        files={"file": (filename, io.BytesIO(data), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["document_id"]


def get_page_rotation(document_id: str, page_index: int) -> int:
    """Return the /Rotate value of a page in the stored PDF."""
    response = client.get(f"/documents/{document_id}/download")
    assert response.status_code == 200, response.text
    pdf = pikepdf.open(io.BytesIO(response.content))
    try:
        page = pdf.pages[page_index]
        rotate = page.get("/Rotate", 0)
        return int(rotate)
    finally:
        pdf.close()


def get_page_order_text(document_id: str) -> list[str]:
    """Return the text content of each page in the stored PDF."""
    response = client.get(f"/documents/{document_id}/download")
    assert response.status_code == 200, response.text
    doc = pymupdf.open(stream=response.content, filetype="pdf")
    try:
        return [doc[i].get_text().strip() for i in range(doc.page_count)]
    finally:
        doc.close()


# -----------------------------------------------------------------------
# Rotate
# -----------------------------------------------------------------------

def test_rotate_single_page():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/rotate",
        json={"page_numbers": [0], "rotation": 90},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_count"] == 3

    assert get_page_rotation(doc_id, 0) == 90
    assert get_page_rotation(doc_id, 1) == 0
    assert get_page_rotation(doc_id, 2) == 0


def test_rotate_multiple_pages():
    doc_id = upload_pdf(4)
    response = client.post(
        f"/documents/{doc_id}/pages/rotate",
        json={"page_numbers": [0, 2], "rotation": 180},
    )
    assert response.status_code == 200, response.text

    assert get_page_rotation(doc_id, 0) == 180
    assert get_page_rotation(doc_id, 1) == 0
    assert get_page_rotation(doc_id, 2) == 180
    assert get_page_rotation(doc_id, 3) == 0


def test_rotate_invalid_value():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/rotate",
        json={"page_numbers": [0], "rotation": 45},
    )
    assert response.status_code == 422, response.text


def test_rotate_invalid_page_index():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/rotate",
        json={"page_numbers": [5], "rotation": 90},
    )
    assert response.status_code == 422, response.text


# -----------------------------------------------------------------------
# Delete
# -----------------------------------------------------------------------

def test_delete_single_page():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/delete",
        json={"page_numbers": [1]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_count"] == 2

    # Verify remaining pages are correct.
    texts = get_page_order_text(doc_id)
    assert texts == ["Test Doc - page 1", "Test Doc - page 3"]


def test_delete_multiple_pages():
    doc_id = upload_pdf(5)
    response = client.post(
        f"/documents/{doc_id}/pages/delete",
        json={"page_numbers": [0, 2, 4]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_count"] == 2

    texts = get_page_order_text(doc_id)
    assert texts == ["Test Doc - page 2", "Test Doc - page 4"]


def test_delete_all_pages_rejected():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/delete",
        json={"page_numbers": [0, 1, 2]},
    )
    assert response.status_code == 422, response.text

    # Document unchanged.
    meta = client.get(f"/documents/{doc_id}")
    assert meta.status_code == 200
    assert meta.json()["page_count"] == 3


def test_delete_invalid_page_index():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/delete",
        json={"page_numbers": [10]},
    )
    assert response.status_code == 422, response.text


# -----------------------------------------------------------------------
# Reorder
# -----------------------------------------------------------------------

def test_reorder_pages():
    doc_id = upload_pdf(4)
    response = client.post(
        f"/documents/{doc_id}/pages/reorder",
        json={"page_order": [3, 2, 1, 0]},
    )
    assert response.status_code == 200, response.text

    texts = get_page_order_text(doc_id)
    assert texts == [
        "Test Doc - page 4",
        "Test Doc - page 3",
        "Test Doc - page 2",
        "Test Doc - page 1",
    ]


def test_reorder_duplicate_indices_rejected():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/reorder",
        json={"page_order": [0, 0, 1]},
    )
    assert response.status_code == 422, response.text


def test_reorder_missing_indices_rejected():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/reorder",
        json={"page_order": [0, 1]},
    )
    assert response.status_code == 422, response.text


def test_reorder_invalid_index_rejected():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/reorder",
        json={"page_order": [0, 1, 5]},
    )
    assert response.status_code == 422, response.text


# -----------------------------------------------------------------------
# Document integrity after operations
# -----------------------------------------------------------------------

def test_download_after_modification():
    doc_id = upload_pdf(3)
    client.post(
        f"/documents/{doc_id}/pages/reorder",
        json={"page_order": [2, 0, 1]},
    )
    response = client.get(f"/documents/{doc_id}/download")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF-")


def test_metadata_updated_after_operation():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/delete",
        json={"page_numbers": [0]},
    )
    assert response.status_code == 200, response.text

    meta = client.get(f"/documents/{doc_id}")
    assert meta.status_code == 200
    assert meta.json()["page_count"] == 2
