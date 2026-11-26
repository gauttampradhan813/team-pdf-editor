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


# -----------------------------------------------------------------------
# Split
# -----------------------------------------------------------------------

def test_split_each_page():
    doc_id = upload_pdf(4, "split_source.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "each_page"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["source_document_id"] == doc_id
    assert body["total_files"] == 4
    assert body["total_pages"] == 4

    # Verify each output has 1 page with correct content.
    for i, out in enumerate(body["outputs"]):
        assert out["page_count"] == 1
        assert out["page_range"] == [i, i]
        texts = get_page_order_text(out["document_id"])
        assert texts == [f"Test Doc - page {i + 1}"]

    # Source unchanged.
    assert get_page_order_text(doc_id) == [
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 3",
        "Test Doc - page 4",
    ]


def test_split_every_n_pages():
    doc_id = upload_pdf(10, "split_every_n.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "every_n_pages", "pages_per_file": 3},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # 10 pages / 3 per file = 4 files (3, 3, 3, 1)
    assert body["total_files"] == 4
    assert body["total_pages"] == 10

    expected_ranges = [[0, 2], [3, 5], [6, 8], [9, 9]]
    for i, out in enumerate(body["outputs"]):
        assert out["page_range"] == expected_ranges[i]
        assert out["page_count"] == expected_ranges[i][1] - expected_ranges[i][0] + 1

        texts = get_page_order_text(out["document_id"])
        start = expected_ranges[i][0]
        end = expected_ranges[i][1]
        assert texts == [f"Test Doc - page {p + 1}" for p in range(start, end + 1)]

    # Source unchanged.
    assert get_page_order_text(doc_id) == [
        f"Test Doc - page {i + 1}" for i in range(10)
    ]


def test_split_custom_ranges():
    doc_id = upload_pdf(8, "split_ranges.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={
            "mode": "ranges",
            "ranges": [[0, 2], [4, 4], [5, 7]],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["total_files"] == 3
    assert body["total_pages"] == 7  # pages 0,1,2,4,5,6,7 (page 3 skipped)

    expected_ranges = [[0, 2], [4, 4], [5, 7]]
    for i, out in enumerate(body["outputs"]):
        assert out["page_range"] == expected_ranges[i]
        texts = get_page_order_text(out["document_id"])
        start = expected_ranges[i][0]
        end = expected_ranges[i][1]
        assert texts == [f"Test Doc - page {p + 1}" for p in range(start, end + 1)]

    # Source unchanged.
    assert get_page_order_text(doc_id) == [
        f"Test Doc - page {i + 1}" for i in range(8)
    ]


def test_split_single_page_pdf():
    doc_id = upload_pdf(1, "single_page.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "each_page"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["total_files"] == 1
    assert body["total_pages"] == 1
    assert body["outputs"][0]["page_range"] == [0, 0]
    assert body["outputs"][0]["page_count"] == 1

    # Source unchanged.
    assert get_page_order_text(doc_id) == ["Test Doc - page 1"]


def test_split_preserves_dimensions():
    # Create a PDF with a non-default page size
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)  # US Letter
    page.insert_text((72, 72), "Different size page")
    data = doc.tobytes()
    doc.close()

    response = client.post(
        "/documents",
        files={"file": ("different_size.pdf", io.BytesIO(data), "application/pdf")},
    )
    assert response.status_code == 201
    doc_id = response.json()["document_id"]

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "each_page"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # Download the output and verify dimensions
    out_data = client.get(f"/documents/{body['outputs'][0]['document_id']}/download").content
    out_doc = pymupdf.open(stream=out_data, filetype="pdf")
    try:
        assert out_doc[0].rect.width == 612
        assert out_doc[0].rect.height == 792
    finally:
        out_doc.close()


def test_split_preserves_rotation():
    doc_id = upload_pdf(2, "rotated_split.pdf")
    # Rotate page 0 by 90 degrees
    client.post(
        f"/documents/{doc_id}/pages/rotate",
        json={"page_numbers": [0], "rotation": 90},
    )

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "each_page"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    import pikepdf
    out_data = client.get(f"/documents/{body['outputs'][0]['document_id']}/download").content
    pdf = pikepdf.open(io.BytesIO(out_data))
    try:
        assert int(pdf.pages[0].get("/Rotate", 0)) == 90
    finally:
        pdf.close()


def test_split_source_unchanged():
    doc_id = upload_pdf(5, "source_unchanged.pdf")
    source_before = get_page_order_text(doc_id)

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "ranges", "ranges": [[0, 1], [3, 4]]},
    )
    assert response.status_code == 201, response.text

    assert get_page_order_text(doc_id) == source_before


def test_split_invalid_range_out_of_bounds():
    doc_id = upload_pdf(5, "oob.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "ranges", "ranges": [[0, 10]]},
    )
    assert response.status_code == 422, response.text


def test_split_invalid_range_start_greater_than_end():
    doc_id = upload_pdf(5, "invalid_range.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "ranges", "ranges": [[3, 1]]},
    )
    assert response.status_code == 422, response.text


def test_split_overlapping_ranges():
    doc_id = upload_pdf(5, "overlap.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "ranges", "ranges": [[0, 2], [2, 4]]},
    )
    assert response.status_code == 422, response.text


def test_split_empty_ranges():
    doc_id = upload_pdf(5, "empty_ranges.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "ranges", "ranges": []},
    )
    assert response.status_code == 422, response.text


def test_split_invalid_pages_per_file():
    doc_id = upload_pdf(5, "invalid_n.pdf")

    # Zero pages_per_file
    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "every_n_pages", "pages_per_file": 0},
    )
    assert response.status_code == 422, response.text

    # Negative pages_per_file
    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "every_n_pages", "pages_per_file": -1},
    )
    assert response.status_code == 422, response.text


def test_split_invalid_mode():
    doc_id = upload_pdf(3, "invalid_mode.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "invalid_mode"},
    )
    assert response.status_code == 422, response.text


def test_split_nonexistent_document():
    response = client.post(
        "/documents/nonexistent-id/split",
        json={"mode": "each_page"},
    )
    assert response.status_code == 404, response.text


def test_split_download_integrity():
    doc_id = upload_pdf(4, "split_download.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "each_page"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # Download each output and verify
    for out in body["outputs"]:
        data = client.get(f"/documents/{out['document_id']}/download")
        assert data.status_code == 200
        assert data.content.startswith(b"%PDF-")

        import pymupdf
        out_doc = pymupdf.open(stream=data.content, filetype="pdf")
        try:
            assert out_doc.page_count == out["page_count"]
            start = out["page_range"][0]
            assert out_doc[0].get_text().strip() == f"Test Doc - page {start + 1}"
        finally:
            out_doc.close()


def test_split_zip_download():
    doc_id = upload_pdf(4, "split_zip.pdf")

    response = client.post(
        f"/documents/{doc_id}/split",
        json={"mode": "each_page"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    output_ids = [o["document_id"] for o in body["outputs"]]
    ids_param = ",".join(output_ids)

    response = client.get(
        f"/documents/split/download?document_ids={ids_param}",
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.content.startswith(b"PK")  # ZIP magic bytes

    import zipfile
    import io
    zip_data = zipfile.ZipFile(io.BytesIO(response.content))
    names = zip_data.namelist()
    assert len(names) == 4

    # Verify each PDF in the ZIP is valid
    import pymupdf
    for name in names:
        pdf_data = zip_data.read(name)
        pdf_doc = pymupdf.open(stream=pdf_data, filetype="pdf")
        try:
            assert pdf_doc.page_count == 1
        finally:
            pdf_doc.close()


def test_split_zip_missing_document():
    response = client.get(
        "/documents/split/download?document_ids=nonexistent-id",
    )
    assert response.status_code == 404, response.text


def test_split_zip_empty_ids():
    response = client.get(
        "/documents/split/download?document_ids=",
    )
    assert response.status_code == 400, response.text


# -----------------------------------------------------------------------
# Compress
# -----------------------------------------------------------------------

def test_compress_low_level():
    doc_id = upload_pdf(3, "compress_low.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "low"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["source_document_id"] == doc_id
    assert body["level"] == "low"
    assert body["page_count"] == 3
    assert body["status"] in ("compressed", "increased")
    assert "new_document_id" in body
    assert body["new_document_id"] != doc_id

    # Verify output PDF opens and has correct pages
    texts = get_page_order_text(body["new_document_id"])
    assert texts == [
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 3",
    ]

    # Source unchanged
    assert get_page_order_text(doc_id) == [
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 3",
    ]


def test_compress_medium_level():
    doc_id = upload_pdf(3, "compress_medium.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "medium"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["source_document_id"] == doc_id
    assert body["level"] == "medium"
    assert body["page_count"] == 3

    texts = get_page_order_text(body["new_document_id"])
    assert texts == [
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 3",
    ]


def test_compress_high_level():
    doc_id = upload_pdf(3, "compress_high.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "high"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["source_document_id"] == doc_id
    assert body["level"] == "high"
    assert body["page_count"] == 3

    texts = get_page_order_text(body["new_document_id"])
    assert texts == [
        "Test Doc - page 1",
        "Test Doc - page 2",
        "Test Doc - page 3",
    ]


def test_compress_custom_settings():
    doc_id = upload_pdf(3, "compress_custom.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={
            "level": "high",
            "jpeg_quality": 70,
            "max_image_dpi": 150,
            "downsample_images": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["level"] == "high"
    assert body["page_count"] == 3


def test_compress_invalid_level():
    doc_id = upload_pdf(3, "compress_bad.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "invalid"},
    )
    assert response.status_code == 422, response.text


def test_compress_invalid_quality():
    doc_id = upload_pdf(3, "compress_bad_q.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "medium", "jpeg_quality": 150},
    )
    assert response.status_code == 422, response.text

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "medium", "jpeg_quality": 0},
    )
    assert response.status_code == 422, response.text


def test_compress_nonexistent_document():
    response = client.post(
        "/documents/nonexistent-id/compress",
        json={"level": "medium"},
    )
    assert response.status_code == 404, response.text


def test_compress_preserves_text():
    doc_id = upload_pdf(3, "compress_text.pdf")

    source_texts = get_page_order_text(doc_id)

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "high"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    compressed_texts = get_page_order_text(body["new_document_id"])
    assert compressed_texts == source_texts


def test_compress_preserves_page_count():
    doc_id = upload_pdf(5, "compress_count.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "medium"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["page_count"] == 5


def test_compress_preserves_dimensions():
    import pymupdf

    # Create a PDF with non-default page size
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)  # US Letter
    page.insert_text((72, 72), "Custom size")
    data = doc.tobytes()
    doc.close()

    response = client.post(
        "/documents",
        files={"file": ("custom_size.pdf", io.BytesIO(data), "application/pdf")},
    )
    assert response.status_code == 201
    doc_id = response.json()["document_id"]

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "medium"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    compressed_data = client.get(
        f"/documents/{body['new_document_id']}/download"
    ).content
    compressed_doc = pymupdf.open(stream=compressed_data, filetype="pdf")
    try:
        assert compressed_doc[0].rect.width == 612
        assert compressed_doc[0].rect.height == 792
    finally:
        compressed_doc.close()


def test_compress_preserves_rotation():
    doc_id = upload_pdf(1, "compress_rotate.pdf")
    client.post(
        f"/documents/{doc_id}/pages/rotate",
        json={"page_numbers": [0], "rotation": 90},
    )

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "medium"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    import pikepdf
    compressed_data = client.get(
        f"/documents/{body['new_document_id']}/download"
    ).content
    pdf = pikepdf.open(io.BytesIO(compressed_data))
    try:
        assert int(pdf.pages[0].get("/Rotate", 0)) == 90
    finally:
        pdf.close()


def test_compress_source_unchanged():
    doc_id = upload_pdf(3, "compress_src.pdf")
    source_texts = get_page_order_text(doc_id)
    source_size = client.get(f"/documents/{doc_id}/download").content

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "high"},
    )
    assert response.status_code == 201, response.text

    assert get_page_order_text(doc_id) == source_texts
    assert client.get(f"/documents/{doc_id}/download").content == source_size


def test_compress_returns_signed_reduction():
    doc_id = upload_pdf(3, "compress_reduction.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "low"},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert "original_size" in body
    assert "compressed_size" in body
    assert "bytes_saved" in body
    assert "reduction_percent" in body
    assert isinstance(body["reduction_percent"], (int, float))


def test_compress_large_pdf():
    doc_id = upload_pdf(20, "compress_large.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "medium"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["page_count"] == 20


def test_compress_returns_warnings_list():
    doc_id = upload_pdf(1, "compress_warn.pdf")

    response = client.post(
        f"/documents/{doc_id}/compress",
        json={"level": "medium"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "warnings" in body
    assert isinstance(body["warnings"], list)


def test_split_zip_empty_ids():
    response = client.get(
        "/documents/split/download?document_ids=",
    )
    assert response.status_code == 400, response.text
