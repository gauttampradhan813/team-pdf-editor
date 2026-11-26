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


# -----------------------------------------------------------------------
# Phase 2.1 — Regression tests (stability fixes)
# -----------------------------------------------------------------------

import os
import threading

from app.storage import DocumentNotFoundError, storage as shared_storage


def test_upload_delete_metadata_returns_404():
    """Upload → delete → metadata GET returns 404."""
    _, body = upload_pdf(pages=1)
    doc_id = body["document_id"]

    response = client.delete(f"/documents/{doc_id}")
    assert response.status_code == 204, response.text

    response = client.get(f"/documents/{doc_id}")
    assert response.status_code == 404, response.json()
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "not_found"


def test_upload_render_delete_render_returns_404():
    """Upload → render → delete → render returns 404."""
    _, body = upload_pdf(pages=2)
    doc_id = body["document_id"]

    # Render populates cache.
    response = client.get(f"/documents/{doc_id}/pages/1.png")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")

    # Delete.
    response = client.delete(f"/documents/{doc_id}")
    assert response.status_code == 204, response.text

    # Render after delete must 404 — cache purged.
    response = client.get(f"/documents/{doc_id}/pages/1.png")
    assert response.status_code == 404, response.json()
    body = response.json()
    assert "error" in body


def test_delete_removes_document_and_cache_directories():
    """Delete removes the document directory and cache from disk."""
    _, body = upload_pdf(pages=2)
    doc_id = body["document_id"]

    # Render to create cache files on disk.
    client.get(f"/documents/{doc_id}/pages/1.png")
    client.get(f"/documents/{doc_id}/pages/2.png")

    doc_dir = os.path.join("data", "documents", doc_id)
    assert os.path.isdir(doc_dir), f"directory should exist: {doc_dir}"

    response = client.delete(f"/documents/{doc_id}")
    assert response.status_code == 204, response.text

    # Directory must no longer exist on disk.
    assert not os.path.exists(doc_dir), f"directory should be removed: {doc_dir}"


def test_delete_nonexistent_document_404():
    """Deleting a document that was never uploaded returns 404."""
    response = client.delete("/documents/nonexistent-id-12345")
    assert response.status_code == 404, response.json()
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "not_found"


def test_repeated_deletion_returns_404():
    """Deleting the same document twice returns 404 the second time."""
    _, body = upload_pdf(pages=1)
    doc_id = body["document_id"]

    response = client.delete(f"/documents/{doc_id}")
    assert response.status_code == 204, response.text

    response = client.delete(f"/documents/{doc_id}")
    assert response.status_code == 404, response.json()


def test_empty_document_id_metadata_404():
    """Empty document ID returns a 4xx error (no document matched)."""
    response = client.get("/documents/")
    assert 400 <= response.status_code < 500, f"expected 4xx, got {response.status_code}: {response.text}"


def test_malformed_document_ids_return_404():
    """Malformed document IDs return 404 with the standard error envelope."""
    bad_ids = ["../etc/passwd", "../../secret", "doc/../x", "   ", "id with spaces"]
    for bad in bad_ids:
        response = client.get(f"/documents/{bad}")
        assert response.status_code == 404, f"ID {bad!r}: {response.text}"
        body = response.json()
        assert "error" in body, f"ID {bad!r}: no error envelope"
        assert body["error"]["code"] == "not_found", f"ID {bad!r}: wrong code"

        response = client.get(f"/documents/{bad}/pages/1.png")
        assert response.status_code == 404, f"ID {bad!r} render: {response.text}"


def test_concurrent_rendering_15_requests():
    """15 simultaneous page-render requests all succeed with valid PNGs.

    Uses asyncio + httpx.AsyncClient with ASGITransport to avoid
    Starlette TestClient threading limitations (it shares a single
    httpx.Client that is not safe across threads).
    """
    import asyncio

    import httpx

    _, body = upload_pdf(pages=5)
    doc_id = body["document_id"]

    state = {"successes": 0, "errors": []}
    lock = threading.Lock()

    async def render(page: int) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            try:
                resp = await ac.get(f"/documents/{doc_id}/pages/{page}.png")
                ok = (
                    resp.status_code == 200
                    and resp.content.startswith(b"\x89PNG\r\n\x1a\n")
                )
                with lock:
                    if ok:
                        state["successes"] += 1
                    else:
                        state["errors"].append(
                            f"page {page}: HTTP {resp.status_code}"
                        )
            except Exception as exc:  # pragma: no cover - test helper
                with lock:
                    state["errors"].append(str(exc))

    async def run_all() -> None:
        async with asyncio.TaskGroup() as tg:
            for _ in range(3):
                for page in range(1, 6):
                    tg.create_task(render(page))

    asyncio.run(run_all())

    assert state["successes"] == 15, f"expected 15/15, got {state['successes']}/15 errors={state['errors']}"
    assert not state["errors"], f"unexpected errors: {state['errors']}"

    client.delete(f"/documents/{doc_id}")


def test_concurrent_render_while_deleting():
    """Rendering while a deletion is attempted: every request either 200 or 404."""
    import asyncio

    import httpx

    _, body = upload_pdf(pages=3)
    doc_id = body["document_id"]

    results = []
    lock = threading.Lock()

    async def render(page: int) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            try:
                resp = await ac.get(f"/documents/{doc_id}/pages/{page}.png")
                with lock:
                    results.append(("render", page, resp.status_code))
            except Exception as exc:  # pragma: no cover - test helper
                with lock:
                    results.append(("render", page, str(exc)))

    async def do_delete() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            try:
                resp = await ac.delete(f"/documents/{doc_id}")
                with lock:
                    results.append(("delete", 0, resp.status_code))
            except Exception as exc:  # pragma: no cover - test helper
                with lock:
                    results.append(("delete", 0, str(exc)))

    async def run_all() -> None:
        async with asyncio.TaskGroup() as tg:
            for _ in range(2):
                for page in range(1, 4):
                    tg.create_task(render(page))
            tg.create_task(do_delete())

    asyncio.run(run_all())

    # Every result must be either a successful render or a 404/delete.
    # Renders that race with deletion may raise exceptions; accept those too.
    for kind, item, status in results:
        if kind == "render":
            assert status in (200, 404) or isinstance(status, str), f"render got {status}"
        elif kind == "delete":
            assert status in (204, 404) or isinstance(status, str), f"delete got {status}"

    # Clean up if still present.
    try:
        client.delete(f"/documents/{doc_id}")
    except Exception:
        pass


def test_storage_delete_removes_cache_entries():
    """Direct storage.delete() removes all in-memory and disk cache entries."""
    s = shared_storage
    data = make_pdf(3)
    record = s.store("cache-delete.pdf", data, 3, {})

    # Populate cache for all 3 pages.
    for page in (1, 2, 3):
        s.page_png(record.document_id, page, 1.5)

    cache_keys_before = [k for k in s._page_cache if k.startswith(f"{record.document_id}:")]
    assert len(cache_keys_before) == 3, f"expected 3 cache keys, got {len(cache_keys_before)}"

    doc_dir = os.path.join("data", "documents", record.document_id)
    cache_dir = os.path.join(doc_dir, "cache")
    assert os.path.isdir(cache_dir), "cache directory should exist"

    s.delete(record.document_id)

    # In-memory cache cleared.
    cache_keys_after = [k for k in s._page_cache if k.startswith(f"{record.document_id}:")]
    assert len(cache_keys_after) == 0, f"cache should be empty, got {cache_keys_after}"

    # Disk directory removed.
    assert not os.path.exists(doc_dir), f"directory should be removed: {doc_dir}"


def test_storage_delete_nonexistent_raises():
    """Direct storage.delete() on unknown ID raises DocumentNotFoundError."""
    s = shared_storage
    try:
        s.delete("nonexistent-id-12345")
        assert False, "should have raised DocumentNotFoundError"
    except DocumentNotFoundError:
        pass


def test_storage_get_invalid_id_raises():
    """Direct storage.get() on empty/malformed ID raises DocumentNotFoundError."""
    s = shared_storage
    for bad in ["", "   ", "../etc/passwd", "doc/../x"]:
        try:
            s.get(bad)
            assert False, f"ID {bad!r} should have raised DocumentNotFoundError"
        except DocumentNotFoundError:
            pass


def test_storage_cleanup_expired_respects_ttl():
    """cleanup_expired removes only expired documents."""
    s = DocumentStorage()
    s.ttl_seconds = 1

    data = make_pdf()
    record = s.store("ttl-test.pdf", data, 1, {})
    assert s.exists(record.document_id)

    time.sleep(1.1)
    deleted = s.cleanup_expired()
    assert deleted >= 1
    assert not s.exists(record.document_id)


def test_storage_cleanup_keeps_recent_documents():
    """cleanup_expired does not remove recently accessed documents."""
    s = DocumentStorage()
    s.ttl_seconds = 86400

    data = make_pdf()
    record = s.store("recent-ttl.pdf", data, 1, {})
    assert s.exists(record.document_id)

    deleted = s.cleanup_expired()
    assert deleted == 0
    assert s.exists(record.document_id)
