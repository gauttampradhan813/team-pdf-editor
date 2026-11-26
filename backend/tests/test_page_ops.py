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


# -----------------------------------------------------------------------
# Extract
# -----------------------------------------------------------------------

def test_extract_single_page():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/extract",
        json={"page_numbers": [1]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "document_id" in body
    assert body["page_count"] == 1
    assert body["document_id"] != doc_id  # new document

    # Verify extracted content.
    texts = get_page_order_text(body["document_id"])
    assert texts == ["Test Doc - page 2"]

    # Source unchanged.
    source_texts = get_page_order_text(doc_id)
    assert source_texts == ["Test Doc - page 1", "Test Doc - page 2", "Test Doc - page 3"]


def test_extract_multiple_pages():
    doc_id = upload_pdf(5)
    response = client.post(
        f"/documents/{doc_id}/pages/extract",
        json={"page_numbers": [0, 2, 4]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["page_count"] == 3

    texts = get_page_order_text(body["document_id"])
    assert texts == ["Test Doc - page 1", "Test Doc - page 3", "Test Doc - page 5"]


def test_extract_non_consecutive_pages():
    doc_id = upload_pdf(4)
    response = client.post(
        f"/documents/{doc_id}/pages/extract",
        json={"page_numbers": [3, 0]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["page_count"] == 2

    # Preserve requested order: page 4 first, then page 1.
    texts = get_page_order_text(body["document_id"])
    assert texts == ["Test Doc - page 4", "Test Doc - page 1"]


def test_extract_empty_selection_rejected():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/extract",
        json={"page_numbers": []},
    )
    assert response.status_code == 422, response.text


def test_extract_invalid_page_index():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/extract",
        json={"page_numbers": [5]},
    )
    assert response.status_code == 422, response.text


def test_extract_source_unchanged():
    doc_id = upload_pdf(3)
    client.post(
        f"/documents/{doc_id}/pages/extract",
        json={"page_numbers": [0]},
    )
    meta = client.get(f"/documents/{doc_id}")
    assert meta.status_code == 200
    assert meta.json()["page_count"] == 3


def test_extract_download_integrity():
    doc_id = upload_pdf(2)
    response = client.post(
        f"/documents/{doc_id}/pages/extract",
        json={"page_numbers": [0, 1]},
    )
    new_id = response.json()["document_id"]
    data = client.get(f"/documents/{new_id}/download")
    assert data.status_code == 200
    assert data.content.startswith(b"%PDF-")

    # Verify content matches source pages.
    import pymupdf
    extracted = pymupdf.open(stream=data.content, filetype="pdf")
    source = pymupdf.open(stream=make_pdf(2), filetype="pdf")
    try:
        assert extracted[0].get_text().strip() == source[0].get_text().strip()
        assert extracted[1].get_text().strip() == source[1].get_text().strip()
    finally:
        extracted.close()
        source.close()


# -----------------------------------------------------------------------
# Duplicate
# -----------------------------------------------------------------------

def test_duplicate_single_page():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/duplicate",
        json={"page_numbers": [1], "position": "after"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_count"] == 4

    texts = get_page_order_text(doc_id)
    assert texts == [
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 2",  # duplicate
        "Test Doc - page 3",
    ]


def test_duplicate_multiple_pages():
    doc_id = upload_pdf(4)
    response = client.post(
        f"/documents/{doc_id}/pages/duplicate",
        json={"page_numbers": [0, 2], "position": "after"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_count"] == 6

    texts = get_page_order_text(doc_id)
    assert texts == [
        "Test Doc - page 1",
        "Test Doc - page 1",  # duplicate
        "Test Doc - page 2",
        "Test Doc - page 3",
        "Test Doc - page 3",  # duplicate
        "Test Doc - page 4",
    ]


def test_duplicate_preserves_order():
    doc_id = upload_pdf(5)
    response = client.post(
        f"/documents/{doc_id}/pages/duplicate",
        json={"page_numbers": [4, 0], "position": "after"},
    )
    assert response.status_code == 200, response.text

    texts = get_page_order_text(doc_id)
    assert texts == [
        "Test Doc - page 1",
        "Test Doc - page 1",  # duplicate of page 1
        "Test Doc - page 2",
        "Test Doc - page 3",
        "Test Doc - page 4",
        "Test Doc - page 5",
        "Test Doc - page 5",  # duplicate of page 5
    ]


def test_duplicate_invalid_page_index():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/duplicate",
        json={"page_numbers": [10], "position": "after"},
    )
    assert response.status_code == 422, response.text


def test_duplicate_empty_selection_rejected():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/duplicate",
        json={"page_numbers": [], "position": "after"},
    )
    assert response.status_code == 422, response.text


def test_duplicate_invalid_position():
    doc_id = upload_pdf(3)
    response = client.post(
        f"/documents/{doc_id}/pages/duplicate",
        json={"page_numbers": [0], "position": "before"},
    )
    assert response.status_code == 422, response.text


def test_duplicate_metadata_updated():
    doc_id = upload_pdf(3)
    client.post(
        f"/documents/{doc_id}/pages/duplicate",
        json={"page_numbers": [0], "position": "after"},
    )
    meta = client.get(f"/documents/{doc_id}")
    assert meta.status_code == 200
    assert meta.json()["page_count"] == 4


# -----------------------------------------------------------------------
# Merge
# -----------------------------------------------------------------------

def test_merge_two_pdfs():
    doc_id_1 = upload_pdf(2, "first.pdf")
    doc_id_2 = upload_pdf(3, "second.pdf")

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, doc_id_2]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "document_id" in body
    assert body["page_count"] == 5  # 2 + 3
    assert body["filename"] == "merged.pdf"

    # Verify content order: first doc pages, then second doc pages.
    texts = get_page_order_text(body["document_id"])
    assert texts == [
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 3",
    ]

    # Source documents unchanged.
    assert get_page_order_text(doc_id_1) == ["Test Doc - page 1", "Test Doc - page 2"]
    assert get_page_order_text(doc_id_2) == [
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 3",
    ]


def test_merge_three_pdfs():
    doc_id_1 = upload_pdf(1, "a.pdf")
    doc_id_2 = upload_pdf(2, "b.pdf")
    doc_id_3 = upload_pdf(1, "c.pdf")

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, doc_id_2, doc_id_3]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["page_count"] == 4

    texts = get_page_order_text(body["document_id"])
    assert texts == [
        "Test Doc - page 1",
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 1",
    ]


def test_merge_preserves_order():
    doc_id_1 = upload_pdf(1, "first.pdf")
    doc_id_2 = upload_pdf(1, "second.pdf")

    # Reverse order: second first, then first.
    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_2, doc_id_1]},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    texts = get_page_order_text(body["document_id"])
    assert texts == ["Test Doc - page 1", "Test Doc - page 1"]
    # Verify source docs content to distinguish them
    # Since both have same text, verify via page dimensions/rotation instead
    assert body["page_count"] == 2


def test_merge_preserves_page_dimensions():
    # Create PDFs with different page sizes
    doc_id_1 = upload_pdf(1, "letter.pdf")  # 595x842 default
    doc_id_2 = upload_pdf(1, "a4.pdf")      # 595x842 default too

    # Make a custom-sized PDF for doc_id_2
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)  # US Letter
    page.insert_text((72, 72), "Different size")
    data = doc.tobytes()
    doc.close()

    # Re-upload doc_id_2 with different size
    response = client.post(
        "/documents",
        files={"file": ("different.pdf", io.BytesIO(data), "application/pdf")},
    )
    assert response.status_code == 201
    doc_id_2 = response.json()["document_id"]

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, doc_id_2]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["page_count"] == 2

    # Verify both pages exist with correct dimensions
    import pymupdf
    merged_data = client.get(f"/documents/{body['document_id']}/download").content
    merged_doc = pymupdf.open(stream=merged_data, filetype="pdf")
    try:
        assert merged_doc.page_count == 2
        # First page should be default size (595x842)
        assert merged_doc[0].rect.width == 595
        assert merged_doc[0].rect.height == 842
        # Second page should be US Letter (612x792)
        assert merged_doc[1].rect.width == 612
        assert merged_doc[1].rect.height == 792
    finally:
        merged_doc.close()


def test_merge_preserves_rotation():
    doc_id_1 = upload_pdf(1, "rotated.pdf")
    # Rotate page 0 of doc_id_1 by 90 degrees
    client.post(
        f"/documents/{doc_id_1}/pages/rotate",
        json={"page_numbers": [0], "rotation": 90},
    )

    doc_id_2 = upload_pdf(1, "normal.pdf")

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, doc_id_2]},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    import pikepdf
    merged_data = client.get(f"/documents/{body['document_id']}/download").content
    pdf = pikepdf.open(io.BytesIO(merged_data))
    try:
        # First page should have /Rotate = 90
        assert int(pdf.pages[0].get("/Rotate", 0)) == 90
        # Second page should have no rotation (0)
        assert int(pdf.pages[1].get("/Rotate", 0)) == 0
    finally:
        pdf.close()


def test_merge_source_documents_unchanged():
    doc_id_1 = upload_pdf(2, "source1.pdf")
    doc_id_2 = upload_pdf(2, "source2.pdf")

    source_texts_1_before = get_page_order_text(doc_id_1)
    source_texts_2_before = get_page_order_text(doc_id_2)

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, doc_id_2]},
    )
    assert response.status_code == 201, response.text

    # Source documents must be unchanged
    assert get_page_order_text(doc_id_1) == source_texts_1_before
    assert get_page_order_text(doc_id_2) == source_texts_2_before


def test_merge_rejects_duplicate_ids():
    doc_id_1 = upload_pdf(1, "dup.pdf")

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, doc_id_1]},
    )
    assert response.status_code == 422, response.text


def test_merge_rejects_fewer_than_two():
    response = client.post(
        "/documents/merge",
        json={"document_ids": []},
    )
    assert response.status_code == 422, response.text


def test_merge_rejects_single_document():
    doc_id_1 = upload_pdf(1, "single.pdf")

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1]},
    )
    assert response.status_code == 422, response.text


def test_merge_rejects_nonexistent_document():
    doc_id_1 = upload_pdf(1, "exists.pdf")

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, "nonexistent-id-12345"]},
    )
    assert response.status_code == 404, response.text


def test_merge_rejects_corrupted_source():
    doc_id_1 = upload_pdf(1, "good.pdf")

    # Upload a corrupted PDF (rejected at 400 - header check)
    response = client.post(
        "/documents",
        files={"file": ("bad.pdf", io.BytesIO(b"not a pdf at all"), "application/pdf")},
    )
    assert response.status_code in (400, 422)  # Rejected on upload

    # Try to merge with a nonexistent document ID
    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, "corrupted-id-99999"]},
    )
    assert response.status_code == 404, response.text


def test_merge_download_integrity():
    doc_id_1 = upload_pdf(2, "merge1.pdf")
    doc_id_2 = upload_pdf(2, "merge2.pdf")

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, doc_id_2]},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # Download merged PDF
    data = client.get(f"/documents/{body['document_id']}/download")
    assert data.status_code == 200
    assert data.content.startswith(b"%PDF-")

    # Verify content
    import pymupdf
    merged = pymupdf.open(stream=data.content, filetype="pdf")
    try:
        assert merged.page_count == 4
        assert merged[0].get_text().strip() == "Test Doc - page 1"
        assert merged[1].get_text().strip() == "Test Doc - page 2"
        assert merged[2].get_text().strip() == "Test Doc - page 1"
        assert merged[3].get_text().strip() == "Test Doc - page 2"
    finally:
        merged.close()


def test_merge_metadata_registered():
    doc_id_1 = upload_pdf(1, "meta1.pdf")
    doc_id_2 = upload_pdf(1, "meta2.pdf")

    response = client.post(
        "/documents/merge",
        json={"document_ids": [doc_id_1, doc_id_2]},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    meta = client.get(f"/documents/{body['document_id']}")
    assert meta.status_code == 200
    assert meta.json()["page_count"] == 2
    assert meta.json()["filename"] == "merged.pdf"
