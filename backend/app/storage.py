"""Modular document storage service.

Keeps all filesystem logic separate from the API routes. Documents are
stored under ``storage_dir`` (default ``data/documents``) using a UUID
document id. Rendered page images are cached per document and evicted
under an LRU-like cap.

Thread-safe: every mutating operation takes a per-process lock. Because
the application is single-process (uvicorn without workers), this is
sufficient to prevent concurrent races.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

from app.config import get_settings


@dataclass
class DocumentRecord:
    """In-memory representation of a stored document."""

    document_id: str
    filename: str
    file_path: str
    size: int
    page_count: int
    metadata: Dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return asdict(self)

    def touch(self) -> None:
        """Update last_accessed to now."""
        self.last_accessed = time.time()


class StorageError(Exception):
    """Raised when the storage layer cannot complete an operation."""


class DocumentNotFoundError(StorageError):
    """Raised when a document id does not exist in storage."""


class DocumentStorage:
    """Filesystem-backed document store with page rendering cache."""

    def __init__(self, storage_dir: Optional[str | Path] = None) -> None:
        settings = get_settings()
        self.storage_dir = Path(storage_dir or settings.storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.ttl_seconds: int = settings.document_ttl_seconds
        self.page_cache_max: int = settings.page_cache_max_entries

        self._lock = threading.RLock()
        self._documents: Dict[str, DocumentRecord] = {}
        self._page_cache: Dict[str, bytes] = {}  # key -> png bytes

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _document_dir(self, document_id: str) -> Path:
        return self.storage_dir / document_id

    def _pdf_path(self, document_id: str) -> Path:
        return self._document_dir(document_id) / "document.pdf"

    def _metadata_path(self, document_id: str) -> Path:
        return self._document_dir(document_id) / "metadata.json"

    def _page_cache_path(self, document_id: str, page_number: int, scale: float) -> Path:
        safe_scale = f"{scale:g}"
        return (
            self._document_dir(document_id)
            / "cache"
            / f"page_{page_number}_scale_{safe_scale}.png"
        )

    def _validate_document_id(self, document_id: str) -> None:
        """Reject ids that could escape the storage directory."""
        if not document_id or document_id in (".", "..") or "/" in document_id or "\\" in document_id:
            raise DocumentNotFoundError(f"Invalid document id: {document_id!r}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        filename: str,
        data: bytes,
        page_count: int,
        metadata: Dict[str, str],
    ) -> DocumentRecord:
        """Write a PDF to disk and register it.

        Returns the created :class:`DocumentRecord`.
        """
        document_id = uuid.uuid4().hex
        doc_dir = self._document_dir(document_id)

        with self._lock:
            try:
                doc_dir.mkdir(parents=True, exist_ok=True)

                pdf_path = self._pdf_path(document_id)
                pdf_path.write_bytes(data)

                record = DocumentRecord(
                    document_id=document_id,
                    filename=filename,
                    file_path=str(pdf_path),
                    size=len(data),
                    page_count=page_count,
                    metadata=metadata or {},
                )
                self._metadata_path(document_id).write_text(
                    json.dumps(record.to_dict(), indent=2), encoding="utf-8"
                )
                self._documents[document_id] = record
            except Exception as exc:
                # Best-effort rollback on failure.
                shutil.rmtree(doc_dir, ignore_errors=True)
                raise StorageError(f"Failed to store document: {exc}") from exc

        return record

    def get(self, document_id: str) -> DocumentRecord:
        """Return the record for ``document_id`` and touch its access time."""
        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.get(document_id)
            if record is None:
                # Try to hydrate from disk (survives process restart).
                metadata_path = self._metadata_path(document_id)
                if metadata_path.exists():
                    try:
                        data = json.loads(metadata_path.read_text(encoding="utf-8"))
                        record = DocumentRecord(**data)
                        self._documents[document_id] = record
                    except (json.JSONDecodeError, TypeError):
                        record = None
                if record is None:
                    raise DocumentNotFoundError(f"Document not found: {document_id}")
            record.touch()
            return record

    def exists(self, document_id: str) -> bool:
        try:
            self.get(document_id)
            return True
        except DocumentNotFoundError:
            return False

    def pdf_bytes(self, document_id: str) -> bytes:
        """Return the raw PDF bytes for ``document_id``."""
        record = self.get(document_id)
        path = self._pdf_path(document_id)
        if not path.exists():
            raise DocumentNotFoundError(f"Document file missing: {document_id}")
        return path.read_bytes()

    def page_png(self, document_id: str, page_number: int, scale: float) -> bytes:
        """Return cached or freshly rendered PNG bytes for a page.

        Renders on first request and caches to disk. Cache key includes
        page number and scale so different renders coexist.
        """
        record = self.get(document_id)
        if page_number < 1 or page_number > record.page_count:
            raise DocumentNotFoundError(
                f"Page {page_number} out of range (1-{record.page_count})"
            )

        cache_key = f"{document_id}:{page_number}:{scale:g}"
        with self._lock:
            cached = self._page_cache.get(cache_key)
            if cached is not None:
                record.touch()
                return cached

            cache_path = self._page_cache_path(document_id, page_number, scale)
            if cache_path.exists():
                cached = cache_path.read_bytes()
                self._page_cache[cache_key] = cached
                self._evict_if_needed()
                record.touch()
                return cached

        # Render outside the lock (PyMuPDF is CPU-bound; releases GIL partially).
        png_bytes = self._render_page(document_id, page_number, scale)

        with self._lock:
            self._page_cache[cache_key] = png_bytes
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(png_bytes)
            except OSError:
                # Disk cache is a best-effort optimization; keep in-memory.
                pass
            self._evict_if_needed()
            record.touch()

        return png_bytes

    def _render_page(self, document_id: str, page_number: int, scale: float) -> bytes:
        """Render a single page with PyMuPDF and return PNG bytes."""
        import pymupdf  # deferred import so module loads without PDF libs present

        pdf_bytes = self.pdf_bytes(document_id)
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            page = doc.load_page(page_number - 1)  # 0-based internally
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return pix.tobytes("png")

    def _evict_if_needed(self) -> None:
        """Drop oldest in-memory cache entries when over the cap."""
        if len(self._page_cache) <= self.page_cache_max:
            return
        # Sort by insertion order (dict preserves it) and drop the oldest.
        excess = len(self._page_cache) - self.page_cache_max
        for key in list(self._page_cache)[:excess]:
            del self._page_cache[key]

    def delete(self, document_id: str) -> None:
        """Remove a document and all its cached pages from disk and memory."""
        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.pop(document_id, None)
            doc_dir = self._document_dir(document_id)

        if record is None:
            # Hydrate check: maybe it exists only on disk.
            if not doc_dir.exists():
                raise DocumentNotFoundError(f"Document not found: {document_id}")
        else:
            # Drop in-memory page cache entries for this document.
            with self._lock:
                for key in list(self._page_cache):
                    if key.startswith(f"{document_id}:"):
                        del self._page_cache[key]

        shutil.rmtree(doc_dir, ignore_errors=True)

    def cleanup_expired(self) -> int:
        """Remove documents whose age exceeds TTL.

        Returns the number of documents deleted. Never deletes a document
        that was accessed within the TTL window.
        """
        if self.ttl_seconds <= 0:
            return 0

        now = time.time()
        expired: list[str] = []

        with self._lock:
            for document_id, record in list(self._documents.items()):
                age = now - record.created_at
                idle = now - record.last_accessed
                if age > self.ttl_seconds or idle > self.ttl_seconds:
                    expired.append(document_id)

        for document_id in expired:
            try:
                self.delete(document_id)
            except DocumentNotFoundError:
                pass

        return len(expired)

    def list_documents(self) -> list[DocumentRecord]:
        with self._lock:
            return sorted(self._documents.values(), key=lambda r: r.created_at, reverse=True)
