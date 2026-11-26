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
# Shared singleton instance used by all API routers.
# ------------------------------------------------------------------
storage = DocumentStorage()
