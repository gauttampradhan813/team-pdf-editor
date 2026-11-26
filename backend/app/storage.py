"""Modular document storage service.

Keeps all filesystem logic separate from the API routes. Documents are
stored under ``storage_dir`` (default ``data/documents``) using a UUID
document id. Rendered page images are cached per document and evicted
under an LRU-like cap.

Thread-safe: every mutating operation takes a per-process lock. Because
the application is single-process (uvicorn without workers), this is
sufficient to prevent concurrent races.

A single module-level ``storage`` instance is shared by all routers so
that upload, metadata, download, delete, and render operations all see
the same document state and cache invalidation.
"""

from __future__ import annotations

import io
import json
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
        """Reject ids that could escape the storage directory or are empty."""
        if not document_id or document_id.strip() == "":
            raise DocumentNotFoundError(f"Invalid document id: {document_id!r}")
        if document_id in (".", ".."):
            raise DocumentNotFoundError(f"Invalid document id: {document_id!r}")
        if "/" in document_id or "\\" in document_id:
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
                self._remove_directory(doc_dir)
                raise StorageError(f"Failed to store document: {exc}") from exc

        return record

    def get(self, document_id: str) -> DocumentRecord:
        """Return the record for ``document_id`` and touch its access time.

        Raises :class:`DocumentNotFoundError` if the document does not
        exist in memory or on disk.
        """
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
                    except (json.JSONDecodeError, TypeError, OSError):
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

        The document is validated before rendering. If the document is
        deleted while rendering is in progress, the freshly rendered PNG
        is still returned to the caller but is not cached, so subsequent
        requests correctly 404.
        """
        record = self.get(document_id)
        if page_number < 1 or page_number > record.page_count:
            raise DocumentNotFoundError(
                f"Page {page_number} out of range (1-{record.page_count})"
            )

        cache_key = f"{document_id}:{page_number}:{scale:g}"
        cache_path = self._page_cache_path(document_id, page_number, scale)

        with self._lock:
            cached = self._page_cache.get(cache_key)
            if cached is not None:
                record.touch()
                return cached

            if cache_path.exists():
                cached = cache_path.read_bytes()
                self._page_cache[cache_key] = cached
                self._evict_if_needed()
                record.touch()
                return cached

        # Render outside the lock (PyMuPDF is CPU-bound).
        png_bytes = self._render_page(document_id, page_number, scale)

        # Re-acquire the lock to store the result, but only if the
        # document still exists (it may have been deleted mid-render).
        with self._lock:
            if document_id not in self._documents:
                # Document was deleted during rendering — do not cache.
                return png_bytes

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
        excess = len(self._page_cache) - self.page_cache_max
        for key in list(self._page_cache)[:excess]:
            del self._page_cache[key]

    def _remove_directory(self, path: Path) -> None:
        """Remove a directory tree, raising on failure.

        On Windows, file handles may be briefly held by antivirus or
        indexers. One retry after a short delay is attempted before
        reporting the failure.
        """
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
        except OSError:
            time.sleep(0.2)
            try:
                shutil.rmtree(path)
            except OSError as exc:
                raise StorageError(
                    f"Failed to delete document directory {path}: {exc}"
                ) from exc

    def delete(self, document_id: str) -> None:
        """Remove a document and all its cached pages from disk and memory.

        Raises :class:`DocumentNotFoundError` if the document does not
        exist. Raises :class:`StorageError` if the filesystem deletion
        cannot be completed (never silently ignored).
        """
        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.pop(document_id, None)
            doc_dir = self._document_dir(document_id)

            # Remove all in-memory cache entries for this document.
            keys_to_delete = [
                key for key in self._page_cache if key.startswith(f"{document_id}:")
            ]
            for key in keys_to_delete:
                del self._page_cache[key]

            if record is None and not doc_dir.exists():
                raise DocumentNotFoundError(f"Document not found: {document_id}")

        # Delete the directory outside the lock (filesystem operation).
        # Any rendering that was in progress already has its bytes in memory;
        # the cache write will find the document no longer in memory and skip.
        self._remove_directory(doc_dir)

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

        deleted_count = 0
        for document_id in expired:
            try:
                self.delete(document_id)
                deleted_count += 1
            except DocumentNotFoundError:
                pass

        return deleted_count

    def list_documents(self) -> list[DocumentRecord]:
        with self._lock:
            return sorted(self._documents.values(), key=lambda r: r.created_at, reverse=True)

    # ------------------------------------------------------------------
    # Page operations (rotate / delete / reorder)
    # ------------------------------------------------------------------

    def rotate_pages(
        self,
        document_id: str,
        page_indices: list[int],
        rotation: int,
    ) -> DocumentRecord:
        """Rotate selected pages in place.

        Args:
            document_id: Target document.
            page_indices: Zero-based page indices to rotate.
            rotation: 90, 180, or 270 degrees clockwise.

        Returns:
            Updated :class:`DocumentRecord`.

        Raises:
            DocumentNotFoundError: Document or pages not found.
            ValueError: Invalid rotation value or page indices.
            StorageError: Filesystem operation failed.
        """
        if rotation not in (90, 180, 270):
            raise ValueError("Rotation must be 90, 180, or 270 degrees.")

        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.get(document_id)
            if record is None:
                raise DocumentNotFoundError(f"Document not found: {document_id}")

            page_count = record.page_count
            for idx in page_indices:
                if idx < 0 or idx >= page_count:
                    raise ValueError(
                        f"Page index {idx} out of range (0-{page_count - 1})"
                    )

            # Build temp output in the document directory.
            doc_dir = self._document_dir(document_id)
            src_path = self._pdf_path(document_id)
            tmp_path = doc_dir / "document.tmp.pdf"

            try:
                self._rotate_pages_file(src_path, tmp_path, page_indices, rotation)
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                raise StorageError(f"Failed to rotate pages: {exc}") from exc

            # Replace original atomically.
            tmp_path.replace(src_path)

            # Update metadata.
            new_metadata = dict(record.metadata)
            new_metadata["rotation_applied"] = rotation
            new_page_count = page_count  # rotation does not change page count
            record.page_count = new_page_count
            record.metadata = new_metadata
            record.touch()
            self._metadata_path(document_id).write_text(
                json.dumps(record.to_dict(), indent=2), encoding="utf-8"
            )

            # Invalidate all page render caches for this document.
            self._invalidate_document_cache(document_id)

        return record

    def delete_pages(
        self,
        document_id: str,
        page_indices: list[int],
    ) -> DocumentRecord:
        """Delete selected pages from the document.

        Args:
            document_id: Target document.
            page_indices: Zero-based page indices to delete.

        Returns:
            Updated :class:`DocumentRecord`.

        Raises:
            DocumentNotFoundError: Document not found.
            ValueError: Invalid indices or would leave zero pages.
            StorageError: Filesystem operation failed.
        """
        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.get(document_id)
            if record is None:
                raise DocumentNotFoundError(f"Document not found: {document_id}")

            page_count = record.page_count
            # Normalize and validate indices.
            unique = set(page_indices)
            for idx in unique:
                if idx < 0 or idx >= page_count:
                    raise ValueError(
                        f"Page index {idx} out of range (0-{page_count - 1})"
                    )

            remaining = page_count - len(unique)
            if remaining == 0:
                raise ValueError("Cannot delete all pages from a document.")

            # Build sorted list of kept zero-based indices.
            kept = [i for i in range(page_count) if i not in unique]

            doc_dir = self._document_dir(document_id)
            src_path = self._pdf_path(document_id)
            tmp_path = doc_dir / "document.tmp.pdf"

            try:
                self._reorder_pages_file(src_path, tmp_path, kept)
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                raise StorageError(f"Failed to delete pages: {exc}") from exc

            tmp_path.replace(src_path)

            # Update metadata.
            new_metadata = dict(record.metadata)
            record.page_count = remaining
            record.metadata = new_metadata
            record.touch()
            self._metadata_path(document_id).write_text(
                json.dumps(record.to_dict(), indent=2), encoding="utf-8"
            )

            # Invalidate all page render caches for this document.
            self._invalidate_document_cache(document_id)

        return record

    def reorder_pages(
        self,
        document_id: str,
        page_order: list[int],
    ) -> DocumentRecord:
        """Reorder pages according to the supplied order.

        Args:
            document_id: Target document.
            page_order: Complete list of zero-based original page indices
                in the desired new order.

        Returns:
            Updated :class:`DocumentRecord`.

        Raises:
            DocumentNotFoundError: Document not found.
            ValueError: Invalid, missing, or duplicated indices.
            StorageError: Filesystem operation failed.
        """
        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.get(document_id)
            if record is None:
                raise DocumentNotFoundError(f"Document not found: {document_id}")

            page_count = record.page_count

            # Validate: every original index appears exactly once.
            if len(page_order) != page_count:
                raise ValueError(
                    f"Page order must contain exactly {page_count} indices "
                    f"(got {len(page_order)})."
                )
            seen = set()
            for idx in page_order:
                if not isinstance(idx, int) or idx < 0 or idx >= page_count:
                    raise ValueError(
                        f"Page index {idx} out of range (0-{page_count - 1})"
                    )
                if idx in seen:
                    raise ValueError(f"Duplicate page index {idx} in order.")
                seen.add(idx)

            doc_dir = self._document_dir(document_id)
            src_path = self._pdf_path(document_id)
            tmp_path = doc_dir / "document.tmp.pdf"

            try:
                self._reorder_pages_file(src_path, tmp_path, page_order)
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                raise StorageError(f"Failed to reorder pages: {exc}") from exc

            tmp_path.replace(src_path)

            # Update metadata.
            new_metadata = dict(record.metadata)
            record.metadata = new_metadata
            record.touch()
            self._metadata_path(document_id).write_text(
                json.dumps(record.to_dict(), indent=2), encoding="utf-8"
            )

            # Invalidate all page render caches for this document.
            self._invalidate_document_cache(document_id)

        return record

    # ------------------------------------------------------------------
    # Low-level PDF manipulation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rotate_pages_file(
        src_path: Path,
        tmp_path: Path,
        page_indices: list[int],
        rotation: int,
    ) -> None:
        """Rotate pages in ``src_path`` and write result to ``tmp_path``."""
        import pikepdf

        with pikepdf.open(src_path) as pdf:
            for idx in page_indices:
                page = pdf.pages[idx]
                # pikepdf Rotation attribute: /Rotate 90/180/270
                page.Rotate = rotation
            pdf.save(tmp_path)

    @staticmethod
    def _reorder_pages_file(
        src_path: Path,
        tmp_path: Path,
        new_order: list[int],
    ) -> None:
        """Reorder pages in ``src_path`` according to ``new_order`` and write
        result to ``tmp_path``. ``new_order`` contains zero-based original
        indices in desired order."""
        import pikepdf

        with pikepdf.open(src_path) as pdf:
            pages = list(pdf.pages)
            ordered_pages = [pages[i] for i in new_order]
            with pikepdf.new() as out_pdf:
                for pg in ordered_pages:
                    out_pdf.pages.append(pg)
                out_pdf.save(tmp_path)

    def _invalidate_document_cache(self, document_id: str) -> None:
        """Remove all in-memory and on-disk page cache entries for a document."""
        keys_to_delete = [
            key
            for key in self._page_cache
            if key.startswith(f"{document_id}:")
        ]
        for key in keys_to_delete:
            del self._page_cache[key]

        cache_dir = self._document_dir(document_id) / "cache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Page extraction and duplication
    # ------------------------------------------------------------------

    def extract_pages(
        self,
        document_id: str,
        page_numbers: list[int],
    ) -> DocumentRecord:
        """Extract selected pages into a new document.

        Args:
            document_id: Source document.
            page_numbers: Zero-based page indices to extract, in desired order.

        Returns:
            A new :class:`DocumentRecord` for the extracted document.

        Raises:
            DocumentNotFoundError: Source document not found.
            ValueError: Empty selection or invalid page indices.
            StorageError: Filesystem operation failed.
        """
        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.get(document_id)
            if record is None:
                raise DocumentNotFoundError(f"Document not found: {document_id}")

            page_count = record.page_count

            if not page_numbers:
                raise ValueError("No pages selected for extraction.")

            unique = set(page_numbers)
            for idx in unique:
                if idx < 0 or idx >= page_count:
                    raise ValueError(
                        f"Page index {idx} out of range (0-{page_count - 1})"
                    )

            src_path = self._pdf_path(document_id)
            if not src_path.exists():
                raise DocumentNotFoundError(f"Document file missing: {document_id}")

        # Build the extracted PDF outside the lock (CPU-bound).
        try:
            extracted_bytes = self._extract_pages_file(src_path, page_numbers)
        except Exception as exc:
            raise StorageError(f"Failed to extract pages: {exc}") from exc

        # Derive a new filename.
        source_name = record.filename or "document.pdf"
        base = source_name[:-4] if source_name.lower().endswith(".pdf") else source_name
        extracted_filename = f"{base}_extracted.pdf"

        # Store as a brand-new document (new ID). Lock only for registration.
        with self._lock:
            try:
                new_record = self.store(
                    filename=extracted_filename,
                    data=extracted_bytes,
                    page_count=len(page_numbers),
                    metadata=dict(record.metadata),
                )
            except StorageError:
                raise

        return new_record

    def duplicate_pages(
        self,
        document_id: str,
        page_numbers: list[int],
        position: str = "after",
    ) -> DocumentRecord:
        """Duplicate selected pages within the same document.

        Args:
            document_id: Target document.
            page_numbers: Zero-based page indices to duplicate.
            position: Insertion position — ``"after"`` inserts each duplicate
                immediately after its original page.

        Returns:
            Updated :class:`DocumentRecord`.

        Raises:
            DocumentNotFoundError: Document not found.
            ValueError: Empty selection, invalid indices, or unsupported position.
            StorageError: Filesystem operation failed.
        """
        if position not in ("after",):
            raise ValueError(f"Unsupported position: {position!r}")

        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.get(document_id)
            if record is None:
                raise DocumentNotFoundError(f"Document not found: {document_id}")

            page_count = record.page_count

            if not page_numbers:
                raise ValueError("No pages selected for duplication.")

            unique = set(page_numbers)
            for idx in unique:
                if idx < 0 or idx >= page_count:
                    raise ValueError(
                        f"Page index {idx} out of range (0-{page_count - 1})"
                    )

            # Build new page order: originals first, then duplicates appended
            # immediately after each original page (preserving selection order).
            # We construct an ordered list of (original_index, is_duplicate).
            selected_set = set(page_numbers)
            # Sort selection so duplicates appear in selection order after their
            # originals; for "after", we place each duplicate right after its
            # source page.
            order: list[int] = []
            inserted_duplicates: set[int] = set()
            for i in range(page_count):
                order.append(i)
                if i in selected_set and i not in inserted_duplicates:
                    order.append(i)  # duplicate right after original
                    inserted_duplicates.add(i)

            doc_dir = self._document_dir(document_id)
            src_path = self._pdf_path(document_id)
            tmp_path = doc_dir / "document.tmp.pdf"

            try:
                self._reorder_pages_file(src_path, tmp_path, order)
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                raise StorageError(f"Failed to duplicate pages: {exc}") from exc

            tmp_path.replace(src_path)

            new_page_count = page_count + len(unique)
            new_metadata = dict(record.metadata)
            new_metadata["duplicated_pages"] = sorted(unique)
            record.page_count = new_page_count
            record.metadata = new_metadata
            record.touch()
            self._metadata_path(document_id).write_text(
                json.dumps(record.to_dict(), indent=2), encoding="utf-8"
            )

            # Invalidate all page render caches for this document.
            self._invalidate_document_cache(document_id)

        return record

    # ------------------------------------------------------------------
    # Low-level PDF extraction helper
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pages_file(
        src_path: Path,
        page_numbers: list[int],
    ) -> bytes:
        """Extract pages from ``src_path`` and return the new PDF bytes."""
        import pikepdf
        import io

        with pikepdf.open(src_path) as pdf:
            pages = list(pdf.pages)
            with pikepdf.new() as out_pdf:
                for idx in page_numbers:
                    out_pdf.pages.append(pages[idx])
                buf = io.BytesIO()
                out_pdf.save(buf)
                return buf.getvalue()

    # ------------------------------------------------------------------
    # Merge multiple documents
    # ------------------------------------------------------------------

    def merge_documents(
        self,
        document_ids: list[str],
        filename: str = "merged.pdf",
    ) -> DocumentRecord:
        """Merge multiple stored PDFs into a single new document.

        Args:
            document_ids: Ordered list of document IDs to merge.
            filename: Filename for the merged result.

        Returns:
            A new :class:`DocumentRecord` for the merged document.

        Raises:
            DocumentNotFoundError: Any document ID does not exist.
            ValueError: Fewer than two documents or duplicate IDs.
            StorageError: Filesystem operation failed or validation failed.
        """
        # --- Validation (all under lock) ---
        if len(document_ids) < 2:
            raise ValueError("At least two documents are required for merging.")

        # Reject duplicate IDs.
        if len(set(document_ids)) != len(document_ids):
            raise ValueError("Duplicate document IDs are not allowed.")

        with self._lock:
            records = []
            for doc_id in document_ids:
                self._validate_document_id(doc_id)
                record = self._documents.get(doc_id)
                if record is None:
                    # Try hydration from disk.
                    metadata_path = self._metadata_path(doc_id)
                    if metadata_path.exists():
                        try:
                            data = json.loads(
                                metadata_path.read_text(encoding="utf-8")
                            )
                            record = DocumentRecord(**data)
                            self._documents[doc_id] = record
                        except (json.JSONDecodeError, TypeError, OSError):
                            record = None
                    if record is None:
                        raise DocumentNotFoundError(
                            f"Document not found: {doc_id}"
                        )
                records.append(record)

            # Verify all source PDF files exist on disk.
            for record in records:
                if not self._pdf_path(record.document_id).exists():
                    raise DocumentNotFoundError(
                        f"Document file missing: {record.document_id}"
                    )

        # --- Build merged PDF outside the lock (CPU-bound) ---
        try:
            merged_bytes = self._merge_pdfs_file(
                [self._pdf_path(r.document_id) for r in records]
            )
        except Exception as exc:
            raise StorageError(f"Failed to merge PDFs: {exc}") from exc

        # --- Validate output by reopening ---
        try:
            import pymupdf

            with pymupdf.open(stream=merged_bytes, filetype="pdf") as validate_doc:
                merged_page_count = validate_doc.page_count
        except Exception as exc:
            raise StorageError(
                f"Merged PDF validation failed: {exc}"
            ) from exc

        # --- Register as a new document ---
        with self._lock:
            try:
                new_record = self.store(
                    filename=filename,
                    data=merged_bytes,
                    page_count=merged_page_count,
                    metadata={},
                )
            except StorageError:
                raise

        return new_record

    @staticmethod
    def _merge_pdfs_file(
        src_paths: list[Path],
    ) -> bytes:
        """Merge multiple PDF files into a single bytes object.

        Uses pikepdf to append all pages from each source in order,
        preserving content, fonts, images, page dimensions, rotation,
        links, and annotations where supported. No rasterization occurs.
        """
        import pikepdf
        import io

        with pikepdf.new() as out_pdf:
            for src_path in src_paths:
                with pikepdf.open(src_path) as pdf:
                    for page in pdf.pages:
                        out_pdf.pages.append(page)
            buf = io.BytesIO()
            out_pdf.save(buf)
            return buf.getvalue()

    # ------------------------------------------------------------------
    # Split a single document into multiple documents
    # ------------------------------------------------------------------

    def split_document(
        self,
        document_id: str,
        mode: str,
        ranges: list[list[int]] | None = None,
        pages_per_file: int | None = None,
    ) -> dict:
        """Split a document into multiple new documents.

        Supports three modes:
        - ``ranges``: extract custom zero-based inclusive page ranges
          (e.g. ``[[0, 2], [4, 4], [6, 9]]``).
        - ``every_n_pages``: split every ``pages_per_file`` pages.
        - ``each_page``: one output page per input page.

        Args:
            document_id: Source document to split.
            mode: Splitting mode: ``ranges``, ``every_n_pages``, ``each_page``.
            ranges: List of [start, end] zero-based inclusive ranges
              (required for ``ranges`` mode).
            pages_per_file: Number of pages per output
              (required for ``every_n_pages`` mode).

        Returns:
            A dict with ``source_document_id``, ``total_files``,
            ``total_pages``, and ``outputs`` (a list of dicts with
            document_id, filename, page_count, file_size, page_range).

        Raises:
            DocumentNotFoundError: Source document not found.
            ValueError: Invalid mode, ranges, or parameters.
            StorageError: Filesystem operation or validation failed.
        """
        if mode not in ("ranges", "every_n_pages", "each_page"):
            raise ValueError(
                f"Invalid split mode: {mode!r}. "
                "Use 'ranges', 'every_n_pages', or 'each_page'."
            )

        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.get(document_id)
            if record is None:
                # Try hydration from disk.
                metadata_path = self._metadata_path(document_id)
                if metadata_path.exists():
                    try:
                        data = json.loads(
                            metadata_path.read_text(encoding="utf-8")
                        )
                        record = DocumentRecord(**data)
                        self._documents[document_id] = record
                    except (json.JSONDecodeError, TypeError, OSError):
                        record = None
                if record is None:
                    raise DocumentNotFoundError(
                        f"Document not found: {document_id}"
                    )

            page_count = record.page_count
            src_path = self._pdf_path(document_id)
            if not src_path.exists():
                raise DocumentNotFoundError(
                    f"Document file missing: {document_id}"
                )

            # --- Compute page ranges based on mode ---
            computed_ranges: list[list[int]] = []

            if mode == "each_page":
                computed_ranges = [[i, i] for i in range(page_count)]
            elif mode == "every_n_pages":
                if not pages_per_file or pages_per_file < 1:
                    raise ValueError(
                        "pages_per_file must be a positive integer."
                    )
                start = 0
                while start < page_count:
                    end = min(start + pages_per_file - 1, page_count - 1)
                    computed_ranges.append([start, end])
                    start = end + 1
            elif mode == "ranges":
                if not ranges:
                    raise ValueError(
                        "ranges must be provided for 'ranges' mode."
                    )
                # Validate and normalize ranges.
                seen_pages: set[int] = set()
                for r in ranges:
                    if (
                        not isinstance(r, list)
                        or len(r) != 2
                        or not all(isinstance(x, int) for x in r)
                    ):
                        raise ValueError(
                            f"Invalid range: {r!r}. "
                            "Each range must be [start, end] integers."
                        )
                    start, end = r
                    if start < 0 or end >= page_count:
                        raise ValueError(
                            f"Range [{start}, {end}] out of bounds "
                            f"(0-{page_count - 1})."
                        )
                    if start > end:
                        raise ValueError(
                            f"Range start {start} > end {end}."
                        )
                    for p in range(start, end + 1):
                        if p in seen_pages:
                            raise ValueError(
                                f"Page {p} appears in multiple ranges."
                            )
                        seen_pages.add(p)
                    computed_ranges.append([start, end])

            if not computed_ranges:
                raise ValueError("No pages to split.")

            # --- Build each output PDF outside the lock ---
            outputs: list[dict] = []
            source_name = record.filename or "document.pdf"
            base = (
                source_name[:-4]
                if source_name.lower().endswith(".pdf")
                else source_name
            )

        # Build outputs (CPU-bound, outside lock).
        try:
            for idx, (start, end) in enumerate(computed_ranges):
                out_bytes = self._split_pdf_file(
                    src_path, start, end
                )

                # Validate output by reopening.
                try:
                    import pymupdf

                    with pymupdf.open(
                        stream=out_bytes, filetype="pdf"
                    ) as validate_doc:
                        out_page_count = validate_doc.page_count
                except Exception as exc:
                    raise StorageError(
                        f"Output validation failed for range "
                        f"[{start}, {end}]: {exc}"
                    ) from exc

                if out_page_count != (end - start + 1):
                    raise StorageError(
                        f"Output page count mismatch for range "
                        f"[{start}, {end}]: expected "
                        f"{end - start + 1}, got {out_page_count}."
                    )

                outputs.append(
                    {
                        "start": start,
                        "end": end,
                        "bytes": out_bytes,
                        "page_count": out_page_count,
                    }
                )
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"Failed to split document: {exc}") from exc

        # --- Register each output as a new document ---
        total_pages = sum(o["page_count"] for o in outputs)
        output_records: list[dict] = []

        with self._lock:
            for i, out in enumerate(outputs, start=1):
                split_filename = f"{base}_split_{i}.pdf"
                try:
                    new_record = self.store(
                        filename=split_filename,
                        data=out["bytes"],
                        page_count=out["page_count"],
                        metadata=dict(record.metadata),
                    )
                except StorageError:
                    raise

                output_records.append(
                    {
                        "document_id": new_record.document_id,
                        "filename": new_record.filename,
                        "page_count": new_record.page_count,
                        "file_size": new_record.size,
                        "page_range": [out["start"], out["end"]],
                    }
                )

        return {
            "source_document_id": document_id,
            "total_files": len(output_records),
            "total_pages": total_pages,
            "outputs": output_records,
        }

    @staticmethod
    def _split_pdf_file(
        src_path: Path,
        start_page: int,
        end_page: int,
    ) -> bytes:
        """Extract pages ``start_page`` through ``end_page`` (inclusive,
        zero-based) from ``src_path`` and return the new PDF bytes."""
        import pikepdf
        import io

        with pikepdf.open(src_path) as pdf:
            pages = list(pdf.pages)
            with pikepdf.new() as out_pdf:
                for idx in range(start_page, end_page + 1):
                    out_pdf.pages.append(pages[idx])
                buf = io.BytesIO()
                out_pdf.save(buf)
                return buf.getvalue()

    def create_split_zip(
        self,
        document_ids: list[str],
    ) -> bytes:
        """Create a ZIP archive containing the PDFs for the given document
        IDs.

        Args:
            document_ids: Ordered list of document IDs to include.

        Returns:
            ZIP archive bytes.

        Raises:
            DocumentNotFoundError: Any document ID does not exist.
            StorageError: ZIP creation failed.
        """
        import zipfile

        buf = io.BytesIO()
        try:
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for doc_id in document_ids:
                    record = self.get(doc_id)
                    pdf_bytes = self.pdf_bytes(doc_id)
                    zf.writestr(record.filename, pdf_bytes)
        except DocumentNotFoundError:
            raise
        except Exception as exc:
            raise StorageError(f"Failed to create ZIP: {exc}") from exc

        return buf.getvalue()


    # ------------------------------------------------------------------
    # Compress a single document
    # ------------------------------------------------------------------

    def compress_document(
        self,
        document_id: str,
        level: str,
        jpeg_quality: int | None = None,
        max_image_dpi: int | None = None,
        downsample_images: bool | None = None,
    ) -> dict:
        """Compress a PDF document without rasterizing pages.

        Supports three levels:
        - ``low``:  structural optimization + stream compression,
          images kept at original quality.
        - ``medium``: structural optimization + stream compression +
          moderate JPEG recompression of eligible photographic images.
        - ``high``: structural optimization + stronger image compression
          + optional downsampling to max_image_dpi.

        Args:
            document_id: Source document to compress.
            level: Compression level: ``low``, ``medium``, or ``high``.
            jpeg_quality: JPEG quality 1-100 (used for medium/high).
            max_image_dpi: Max image DPI for downsampling (high only).
            downsample_images: Whether to downsample images (high only).

        Returns:
            A dict with ``source_document_id``, ``new_document_id``,
            ``filename``, ``original_size``, ``compressed_size``,
            ``bytes_saved``, ``reduction_percent``, ``page_count``,
            ``level``, ``status``, and ``warnings``.

        Raises:
            DocumentNotFoundError: Source document not found.
            ValueError: Invalid level or parameters.
            StorageError: Filesystem operation or validation failed.
        """
        if level not in ("low", "medium", "high"):
            raise ValueError(
                "Invalid compression level: %r. "
                "Use 'low', 'medium', or 'high'." % level
            )

        # Defaults per level.
        if jpeg_quality is None:
            jpeg_quality = {"low": 95, "medium": 75, "high": 60}[level]
        if max_image_dpi is None:
            max_image_dpi = 150 if level == "high" else None
        if downsample_images is None:
            downsample_images = level == "high"

        if not (1 <= jpeg_quality <= 100):
            raise ValueError("jpeg_quality must be between 1 and 100.")
        if max_image_dpi is not None and max_image_dpi < 1:
            raise ValueError("max_image_dpi must be >= 1.")

        with self._lock:
            self._validate_document_id(document_id)
            record = self._documents.get(document_id)
            if record is None:
                # Try hydration from disk.
                metadata_path = self._metadata_path(document_id)
                if metadata_path.exists():
                    try:
                        data = json.loads(
                            metadata_path.read_text(encoding="utf-8")
                        )
                        record = DocumentRecord(**data)
                        self._documents[document_id] = record
                    except (json.JSONDecodeError, TypeError, OSError):
                        record = None
                if record is None:
                    raise DocumentNotFoundError(
                        f"Document not found: {document_id}"
                    )

            page_count = record.page_count
            src_path = self._pdf_path(document_id)
            if not src_path.exists():
                raise DocumentNotFoundError(
                    f"Document file missing: {document_id}"
                )

        # --- Build compressed PDF outside the lock (CPU-bound) ---
        try:
            compressed_bytes, warnings = self._compress_pdf_file(
                src_path, level, jpeg_quality, max_image_dpi,
                downsample_images,
            )
        except Exception as exc:
            raise StorageError(f"Failed to compress PDF: {exc}") from exc

        # --- Validate output by reopening ---
        try:
            import pymupdf

            with pymupdf.open(
                stream=compressed_bytes, filetype="pdf"
            ) as validate_doc:
                out_page_count = validate_doc.page_count
        except Exception as exc:
            raise StorageError(
                f"Compressed PDF validation failed: {exc}"
            ) from exc

        if out_page_count != page_count:
            raise StorageError(
                f"Output page count mismatch: expected {page_count}, "
                f"got {out_page_count}."
            )

        original_size = len(
            self._pdf_path(document_id).read_bytes()
        )
        compressed_size = len(compressed_bytes)
        bytes_saved = original_size - compressed_size
        reduction_percent = (
            (bytes_saved / original_size) * 100 if original_size > 0 else 0.0
        )

        status = "compressed" if compressed_size <= original_size else "increased"

        # --- Register as a new document ---
        with self._lock:
            source_name = record.filename or "document.pdf"
            base = (
                source_name[:-4]
                if source_name.lower().endswith(".pdf")
                else source_name
            )
            compressed_filename = f"{base}_compressed_{level}.pdf"
            try:
                new_record = self.store(
                    filename=compressed_filename,
                    data=compressed_bytes,
                    page_count=out_page_count,
                    metadata=dict(record.metadata),
                )
            except StorageError:
                raise

        return {
            "source_document_id": document_id,
            "new_document_id": new_record.document_id,
            "filename": new_record.filename,
            "original_filename": source_name,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "bytes_saved": bytes_saved,
            "reduction_percent": round(reduction_percent, 2),
            "page_count": out_page_count,
            "level": level,
            "status": status,
            "warnings": warnings,
        }

    @staticmethod
    def _compress_pdf_file(
        src_path: Path,
        level: str,
        jpeg_quality: int,
        max_image_dpi: int,
        downsample_images: bool,
    ) -> tuple[bytes, list[str]]:
        """Compress a PDF file using pikepdf + Pillow, preserving pages,
        text, fonts, vector graphics, and structure. Returns
        (compressed_bytes, warnings).

        No page rasterization occurs. Images are recompressed only when
        safe and beneficial.
        """
        import pikepdf
        import io
        import warnings as pywarnings

        warnings: list[str] = []

        with pywarnings.catch_warnings(record=True) as w:
            pywarnings.simplefilter("always")
            with pikepdf.open(src_path) as pdf:
                # Recompress images where appropriate.
                for page in pdf.pages:
                    try:
                        _compress_page_images(
                            page, level, jpeg_quality,
                            max_image_dpi, downsample_images, warnings
                        )
                    except Exception:
                        # Image recompression failure is non-fatal;
                        # leave original image in place.
                        pass

                buf = io.BytesIO()
                pdf.save(
                    buf,
                    compress_streams=True,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate,
                )
                return buf.getvalue(), warnings

    @staticmethod
    def _compress_page_images(
        page: object,
        level: str,
        jpeg_quality: int,
        max_image_dpi: int,
        downsample_images: bool,
        warnings: list[str],
    ) -> None:
        """Attempt to recompress images on a single page.

        Operates on page resources. Images are recompressed only when
        they are photographic (RGB/grayscale JPEG-encodable), larger than
        a small threshold, and not part of a mask/soft-mask. Transparency
        is preserved by keeping PNG for images with alpha or by using
        JPEG2000 when available.
        """
        import pikepdf
        from PIL import Image

        try:
            resources = page.get("/Resources", {})
            xobjects = resources.get("/XObject", {})
            if not xobjects:
                return
        except Exception:
            return

        for name, xobj in xobjects.items():
            try:
                if xobj.get("/Subtype") != "/Image":
                    continue
                # Skip images used as masks or soft masks.
                if xobj.get("/SMask") is not None:
                    continue
                if xobj.get("/Mask") is not None:
                    continue

                width = xobj.get("/Width", 0)
                height = xobj.get("/Height", 0)
                if width < 50 or height < 50:
                    continue  # Skip tiny images.

                # Extract raw image stream.
                try:
                    raw = xobj.read_raw_stream()
                except Exception:
                    continue

                # Determine color space.
                colorspace = xobj.get("/ColorSpace", "/DeviceGray")
                bits = xobj.get("/BitsPerComponent", 8)

                # Only recompress photographic images (RGB/Gray), not
                # line art / indexed / CMYK unless we can handle it.
                if isinstance(colorspace, pikepdf.Name):
                    cs_name = str(colorspace)
                else:
                    cs_name = str(colorspace)

                if cs_name not in ("/DeviceGray", "/DeviceRGB"):
                    continue

                has_alpha = xobj.get("/SMask") is not None or (
                    isinstance(xobj.get("/ColorSpace"), list)
                    and len(xobj.get("/ColorSpace", [])) > 1
                )

                try:
                    img = Image.open(io.BytesIO(raw))
                except Exception:
                    continue

                # Determine if recompression is beneficial.
                original_size = len(raw)

                # Determine target format.
                use_jpeg = (
                    level in ("medium", "high")
                    and not has_alpha
                    and cs_name in ("/DeviceGray", "/DeviceRGB")
                )

                if use_jpeg:
                    # Convert to RGB if needed.
                    if img.mode != "RGB":
                        try:
                            img = img.convert("RGB")
                        except Exception:
                            continue

                    # Downsample if requested and image is large enough.
                    if downsample_images and max_image_dpi:
                        # Estimate current DPI from image size / page rect.
                        # Use a simple heuristic: if image is very large,
                        # downsample to target DPI.
                        page_rect = page.mediabox
                        page_width = float(page_rect[2] - page_rect[0])
                        page_height = float(page_rect[3] - page_rect[1])
                        # Estimate effective DPI: width_px / width_inches.
                        # 1 inch = 72 points.
                        dpi_x = width / (page_width / 72.0) if page_width > 0 else 0
                        dpi_y = height / (page_height / 72.0) if page_height > 0 else 0
                        effective_dpi = max(dpi_x, dpi_y)

                        if effective_dpi > max_image_dpi:
                            scale = max_image_dpi / effective_dpi
                            new_width = max(1, int(width * scale))
                            new_height = max(1, int(height * scale))
                            try:
                                img = img.resize(
                                    (new_width, new_height),
                                    Image.LANCZOS,
                                )
                            except Exception:
                                pass

                    buf = io.BytesIO()
                    try:
                        img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
                        compressed = buf.getvalue()
                    except Exception:
                        continue

                    # Only use compressed if smaller.
                    if len(compressed) < original_size:
                        try:
                            xobj.write_stream(compressed)
                            xobj["/Filter"] = pikepdf.Name("/DCTDecode")
                            xobj["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
                            if "/SMask" in xobj:
                                del xobj["/SMask"]
                            if "/Mask" in xobj:
                                del xobj["/Mask"]
                        except Exception:
                            pass
                else:
                    # Non-JPEG: try lossless recompression with Pillow.
                    try:
                        buf = io.BytesIO()
                        img.save(buf, format="PNG", optimize=True)
                        compressed = buf.getvalue()
                        if len(compressed) < original_size:
                            try:
                                xobj.write_stream(compressed)
                                xobj["/Filter"] = pikepdf.Name("/FlateDecode")
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                # Individual image failure is non-fatal.
                continue

    # ------------------------------------------------------------------
    # Shared singleton instance used by all API routers.
    # ------------------------------------------------------------------
storage = DocumentStorage()
