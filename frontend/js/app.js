/* =====================================================================
   TeamPDF Studio — Main application module
   Coordinates API, Viewer, Thumbnails, Toolbar, and UI state.
   ===================================================================== */

const App = (() => {
  // DOM elements
  const els = {
    container: document.getElementById("document-area"),
    viewport: document.getElementById("pages-viewport"),
    sidebar: document.getElementById("sidebar"),
    thumbnailsList: document.getElementById("thumbnails-list"),
    emptyState: document.getElementById("empty-state"),
    viewerContainer: document.getElementById("viewer-container"),
    viewerToolbar: document.getElementById("viewer-toolbar"),
    navFilename: document.getElementById("nav-filename"),
    navStatus: document.getElementById("nav-status"),
    btnOpen: document.getElementById("btn-open"),
    btnDownload: document.getElementById("btn-download"),
    fileInput: document.getElementById("file-input"),
    sidebarToggle: document.getElementById("sidebar-toggle"),
    btnToggleThumbnails: document.getElementById("btn-toggle-thumbnails"),
    uploadOverlay: document.getElementById("upload-overlay"),
    uploadMessage: document.getElementById("upload-message"),
    uploadProgressBar: document.getElementById("upload-progress-bar"),
    errorToast: document.getElementById("error-toast"),
    errorToastMessage: document.getElementById("error-toast-message"),
    errorToastClose: document.getElementById("error-toast-close"),
    // Confirm dialog refs
    confirmDialog: document.getElementById("confirm-dialog"),
    confirmCancel: document.getElementById("confirm-cancel"),
    confirmDelete: document.getElementById("confirm-delete"),
    confirmMessage: document.getElementById("confirm-message"),
    // Extract dialog refs
    extractDialog: document.getElementById("extract-dialog"),
    extractCancel: document.getElementById("extract-cancel"),
    extractOk: document.getElementById("extract-ok"),
    extractRanges: document.getElementById("extract-ranges"),
    extractSelectedCount: document.getElementById("extract-selected-count"),
    // Duplicate dialog refs
    duplicateDialog: document.getElementById("duplicate-dialog"),
    duplicateCancel: document.getElementById("duplicate-cancel"),
    duplicateOk: document.getElementById("duplicate-ok"),
    duplicateCount: document.getElementById("duplicate-count"),
    // Success toast refs
    successToast: document.getElementById("success-toast"),
    successToastMessage: document.getElementById("success-toast-message"),
    successToastClose: document.getElementById("success-toast-close"),
    // Merge workspace refs
    btnMerge: document.getElementById("btn-merge"),
    mergeOverlay: document.getElementById("merge-overlay"),
    mergeClose: document.getElementById("merge-close"),
    mergeFileInput: document.getElementById("merge-file-input"),
    mergeBtnAdd: document.getElementById("merge-btn-add"),
    mergeBtnClear: document.getElementById("merge-btn-clear"),
    mergeBtnMerge: document.getElementById("merge-btn-merge"),
    mergeList: document.getElementById("merge-list"),
    mergeProgress: document.getElementById("merge-progress"),
    mergeProgressMessage: document.getElementById("merge-progress-message"),
    mergeProgressFill: document.getElementById("merge-progress-fill"),
    // Split workspace refs
    btnSplit: document.getElementById("btn-split"),
    splitOverlay: document.getElementById("split-overlay"),
    splitClose: document.getElementById("split-close"),
    splitEveryN: document.getElementById("split-every-n"),
    splitRanges: document.getElementById("split-ranges"),
    splitBtnSplit: document.getElementById("split-btn-split"),
    splitProgress: document.getElementById("split-progress"),
    splitProgressMessage: document.getElementById("split-progress-message"),
    splitProgressFill: document.getElementById("split-progress-fill"),
    splitResults: document.getElementById("split-results"),
    splitResultsCount: document.getElementById("split-results-count"),
    splitResultsList: document.getElementById("split-results-list"),
    splitBtnDownloadAll: document.getElementById("split-btn-download-all"),
    splitBtnCloseResults: document.getElementById("split-btn-close-results"),
    splitEveryNSection: document.getElementById("split-every-n-section"),
    splitRangesSection: document.getElementById("split-ranges-section"),
    splitPreviewSection: document.getElementById("split-preview-section"),
    // Compress workspace refs
    btnCompress: document.getElementById("btn-compress"),
    compressOverlay: document.getElementById("compress-overlay"),
    compressClose: document.getElementById("compress-close"),
    compressBtnCompress: document.getElementById("compress-btn-compress"),
    compressProgress: document.getElementById("compress-progress"),
    compressProgressMessage: document.getElementById("compress-progress-message"),
    compressProgressFill: document.getElementById("compress-progress-fill"),
    compressResults: document.getElementById("compress-results"),
    compressResultFilename: document.getElementById("compress-result-filename"),
    compressResultDetails: document.getElementById("compress-result-details"),
    compressSizeOriginal: document.getElementById("compress-size-original"),
    compressSizeCompressed: document.getElementById("compress-size-compressed"),
    compressSizeSaved: document.getElementById("compress-size-saved"),
    compressSizeReduction: document.getElementById("compress-size-reduction"),
    compressBtnDownload: document.getElementById("compress-btn-download"),
    compressBtnOpen: document.getElementById("compress-btn-open"),
    compressBtnCloseResults: document.getElementById("compress-btn-close-results"),
    // Toolbar refs
    btnPrev: document.getElementById("btn-prev"),
    btnNext: document.getElementById("btn-next"),
    pageInput: document.getElementById("page-input"),
    pageOfTotal: document.getElementById("total-pages"),
    btnZoomOut: document.getElementById("btn-zoom-out"),
    btnZoomIn: document.getElementById("btn-zoom-in"),
    btnFitWidth: document.getElementById("btn-fit-width"),
    btnFitPage: document.getElementById("btn-fit-page"),
    btnActualSize: document.getElementById("btn-actual-size"),
    btnRotate: document.getElementById("btn-rotate"),
    btnDeletePage: document.getElementById("btn-delete-page"),
    toolbarZoom: document.getElementById("toolbar-zoom"),
  };

  // Application state
  let state = {
    documentId: null,
    filename: null,
    pageCount: 0,
    currentPage: 1,
    isLoading: false,
    sidebarVisible: true,
    pendingDeletePages: null, // zero-based indices awaiting confirmation
    extractedDocuments: [], // [{ document_id, filename, page_count }]
    mergeList: [], // [{ document_id, filename, page_count }]
    mergeInProgress: false,
    splitState: {
      mode: "each_page",
      everyN: 1,
      ranges: "",
      outputs: [],
      inProgress: false,
    },
    compressState: {
      level: "medium",
      jpegQuality: null,
      maxImageDpi: null,
      downsampleImages: null,
      outputs: [],
      inProgress: false,
    },
  };

  // ------------------------------------------------------------------
  // Initialization
  // ------------------------------------------------------------------

  function init() {
    _bindUIEvents();
    _bindKeyboard();
    _showEmptyState();

    // Initialize modules
    Viewer.init({
      container: els.container,
      viewport: els.viewport,
      onPageRendered: (pageNumber, fromCache) => {
        // Page rendered; could trigger thumbnail update
        Thumbnails.setCurrentPage(state.currentPage);
      },
      onError: (err, pageNumber) => {
        console.error(`Failed to render page ${pageNumber}:`, err);
      },
    });

    Thumbnails.init({
      listElement: els.thumbnailsList,
      onPageClick: (pageNumber) => {
        Viewer.setCurrentPage(pageNumber);
        Toolbar.updatePagination(pageNumber, state.pageCount);
      },
      onPageSelect: (selected) => {
        Toolbar.setSelectionCount(selected.length);
      },
    });

    Toolbar.init(
      {
        btnPrev: els.btnPrev,
        btnNext: els.btnNext,
        pageInput: els.pageInput,
        pageOfTotal: els.pageOfTotal,
        btnZoomOut: els.btnZoomOut,
        btnZoomIn: els.btnZoomIn,
        btnFitWidth: els.btnFitWidth,
        btnFitPage: els.btnFitPage,
        btnActualSize: els.btnActualSize,
        btnRotate: els.btnRotate,
        btnDeletePage: els.btnDeletePage,
        btnExtractPage: els.btnExtractPage,
        btnDuplicatePage: els.btnDuplicatePage,
        btnToggleThumbnails: els.btnToggleThumbnails,
      },
      {
        onPrevPage: () => _goToPage(state.currentPage - 1),
        onNextPage: () => _goToPage(state.currentPage + 1),
        onPageChange: (pageNumber) => _goToPage(pageNumber),
        onZoomOut: () => _zoomOut(),
        onZoomIn: () => _zoomIn(),
        onFitWidth: () => _fitWidth(),
        onFitPage: () => _fitPage(),
        onActualSize: () => _actualSize(),
        onRotateSelected: () => _rotateSelected(),
        onDeleteSelected: () => _confirmDelete(),
        onExtractSelected: () => _confirmExtract(),
        onDuplicateSelected: () => _confirmDuplicate(),
        onToggleThumbnails: _toggleSidebar,
      }
    );

    // Confirm dialog events
    els.confirmCancel.addEventListener("click", _hideConfirm);
    els.confirmDelete.addEventListener("click", _executeDelete);

    // Extract dialog events
    els.extractCancel.addEventListener("click", _hideExtract);
    els.extractOk.addEventListener("click", _executeExtract);

    // Duplicate dialog events
    els.duplicateCancel.addEventListener("click", _hideDuplicate);
    els.duplicateOk.addEventListener("click", _executeDuplicate);

    // Success toast close
    els.successToastClose.addEventListener("click", _hideSuccess);

    // Merge workspace events
    els.btnMerge.addEventListener("click", _openMergeWorkspace);
    els.mergeClose.addEventListener("click", _closeMergeWorkspace);
    els.mergeBtnAdd.addEventListener("click", () => {
      els.mergeFileInput.value = "";
      els.mergeFileInput.click();
    });
    els.mergeFileInput.addEventListener("change", (e) => {
      const files = Array.from(e.target.files || []);
      if (files.length) {
        _addFilesToMergeList(files);
      }
    });
    els.mergeBtnClear.addEventListener("click", _clearMergeList);
    els.mergeBtnMerge.addEventListener("click", _executeMerge);
  }

  // ------------------------------------------------------------------
  // UI event bindings
  // ------------------------------------------------------------------

  function _bindUIEvents() {
    // Open PDF
    els.btnOpen.addEventListener("click", () => {
      els.fileInput.value = "";
      els.fileInput.click();
    });

    els.fileInput.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (file) {
        _uploadFile(file);
      }
    });

    // Download
    els.btnDownload.addEventListener("click", () => {
      if (state.documentId && state.filename) {
        _downloadDocument();
      }
    });

    // Sidebar toggle
    els.sidebarToggle.addEventListener("click", _toggleSidebar);

    // Error toast close
    els.errorToastClose.addEventListener("click", () => {
      _hideError();
    });

    // Click outside upload overlay to close? No, keep it forced.
  }

  function _bindKeyboard() {
    document.addEventListener("keydown", (e) => {
      // Ignore if typing in an input
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
        if (e.key === "Enter") return;
      }

      // Ctrl + O: Open
      if (e.ctrlKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        els.fileInput.value = "";
        els.fileInput.click();
        return;
      }

      if (!state.documentId) return;

      // Ctrl + Plus: Zoom in
      if (e.ctrlKey && (e.key === "+" || e.key === "=")) {
        e.preventDefault();
        _zoomIn();
        return;
      }

      // Ctrl + Minus: Zoom out
      if (e.ctrlKey && e.key === "-") {
        e.preventDefault();
        _zoomOut();
        return;
      }

      // Page navigation
      if (e.key === "ArrowDown" || e.key === "PageDown") {
        e.preventDefault();
        _goToPage(state.currentPage + 1);
        return;
      }
      if (e.key === "ArrowUp" || e.key === "PageUp") {
        e.preventDefault();
        _goToPage(state.currentPage - 1);
        return;
      }
      if (e.key === "Home") {
        e.preventDefault();
        _goToPage(1);
        return;
      }
      if (e.key === "End") {
        e.preventDefault();
        _goToPage(state.pageCount);
        return;
      }
    });

    // Split workspace events
    els.btnSplit.addEventListener("click", _openSplitWorkspace);
    els.splitClose.addEventListener("click", _closeSplitWorkspace);

    // Split mode radio changes
    document.querySelectorAll('input[name="split-mode"]').forEach((radio) => {
      radio.addEventListener("change", (e) => {
        state.splitState.mode = e.target.value;
        _updateSplitModeUI();
      });
    });

    // Split every N input change
    els.splitEveryN.addEventListener("input", () => {
      state.splitState.everyN = parseInt(els.splitEveryN.value, 10) || 1;
      _updateSplitPreview();
    });

    // Split ranges input change
    els.splitRanges.addEventListener("input", () => {
      state.splitState.ranges = els.splitRanges.value.trim();
      _updateSplitPreview();
    });

    // Split button
    els.splitBtnSplit.addEventListener("click", _executeSplit);

    // Split results actions
    els.splitBtnDownloadAll.addEventListener("click", _downloadSplitZip);
    els.splitBtnCloseResults.addEventListener("click", _closeSplitResults);

    // Compress workspace events
    els.btnCompress.addEventListener("click", _openCompressWorkspace);
    els.compressClose.addEventListener("click", _closeCompressWorkspace);
    els.compressBtnCompress.addEventListener("click", _executeCompress);
    els.compressBtnDownload.addEventListener("click", _downloadCompressedPdf);
    els.compressBtnOpen.addEventListener("click", _openCompressedInViewer);
    els.compressBtnCloseResults.addEventListener("click", _closeCompressResults);
  }

  // ------------------------------------------------------------------
  // Document operations
  // ------------------------------------------------------------------

  async function _uploadFile(file) {
    if (!file.type || !file.type.includes("pdf")) {
      // Let the backend validate, but give a quick hint
    }

    _setLoading(true);
    _showUploadOverlay(true);
    _hideError();

    try {
      const result = await API.uploadPDF(file, (loaded, total) => {
        const pct = total ? Math.round((loaded / total) * 100) : 0;
        els.uploadProgressBar.style.width = `${pct}%`;
        els.uploadMessage.textContent = `Uploading document… ${pct}%`;
      });

      _applyDocument(result);
    } catch (err) {
      _showError(err.message || "Failed to upload document");
    } finally {
      _setLoading(false);
      _showUploadOverlay(false);
      els.uploadProgressBar.style.width = "0%";
    }
  }

  function _applyDocument(result) {
    state.documentId = result.document_id;
    state.filename = result.filename;
    state.pageCount = result.page_count || 0;
    state.currentPage = 1;

    // Update UI
    els.navFilename.textContent = state.filename;
    els.navFilename.title = state.filename;
    els.navStatus.textContent = "Document loaded";

    els.btnDownload.disabled = false;

    // Show viewer, hide empty state
    _showViewer();

    // Load into viewer and thumbnails modules
    Viewer.loadDocument(state.documentId, state.pageCount);
    Thumbnails.loadDocument(state.documentId, state.pageCount);

    Toolbar.updatePagination(state.currentPage, state.pageCount);
    Toolbar.updateZoom(Viewer.getZoomPercent(), Viewer.getState().fitMode);
  }

  async function _downloadDocument() {
    if (!state.documentId) return;
    try {
      await API.downloadPDF(state.documentId, state.filename);
    } catch (err) {
      _showError(err.message || "Failed to download document");
    }
  }

  function _closeDocument() {
    if (state.documentId) {
      // Delete from server
      API.deleteDocument(state.documentId).catch(() => {
        // Ignore errors on cleanup
      });
    }

    Viewer.unloadDocument();
    Thumbnails.unloadDocument();

    state.documentId = null;
    state.filename = null;
    state.pageCount = 0;
    state.currentPage = 1;

    els.navFilename.textContent = "No document";
    els.navFilename.title = "No document loaded";
    els.navStatus.textContent = "Ready";
    els.btnDownload.disabled = true;

    _showEmptyState();
  }

  // ------------------------------------------------------------------
  // Navigation
  // ------------------------------------------------------------------

  function _goToPage(pageNumber) {
    if (!state.documentId) return;
    if (Viewer.setCurrentPage(pageNumber)) {
      state.currentPage = pageNumber;
      Thumbnails.setCurrentPage(pageNumber);
      Toolbar.updatePagination(pageNumber, state.pageCount);
    }
  }

  function _zoomIn() {
    Viewer.zoomIn();
    const s = Viewer.getState();
    state.currentPage = s.currentPage;
    Toolbar.updateZoom(Viewer.getZoomPercent(), s.fitMode);
  }

  function _zoomOut() {
    Viewer.zoomOut();
    const s = Viewer.getState();
    Toolbar.updateZoom(Viewer.getZoomPercent(), s.fitMode);
  }

  function _fitWidth() {
    Viewer.setFitWidth();
    const s = Viewer.getState();
    Toolbar.updateZoom(Viewer.getZoomPercent(), s.fitMode);
  }

  function _fitPage() {
    Viewer.setFitPage();
    const s = Viewer.getState();
    Toolbar.updateZoom(Viewer.getZoomPercent(), s.fitMode);
  }

  function _actualSize() {
    Viewer.setActualSize();
    const s = Viewer.getState();
    Toolbar.updateZoom(Viewer.getZoomPercent(), s.fitMode);
  }

  // ------------------------------------------------------------------
  // Page operations (rotate / delete)
  // ------------------------------------------------------------------

  async function _rotateSelected() {
    const selected = Viewer.getSelectedZeroBased();
    if (!selected.length) return;

    _setLoading(true);
    _hideError();

    try {
      const result = await API.rotatePages(state.documentId, selected, 90);
      _applyDocumentUpdate(result);
    } catch (err) {
      _showError(err.message || "Failed to rotate pages");
    } finally {
      _setLoading(false);
    }
  }

  async function _confirmDelete() {
    const selected = Viewer.getSelectedZeroBased();
    if (!selected.length) return;

    state.pendingDeletePages = selected;
    const count = selected.length;
    els.confirmMessage.textContent = `Delete ${count} page${count === 1 ? "" : "s"}?`;
    els.confirmDialog.style.display = "flex";
  }

  function _hideConfirm() {
    els.confirmDialog.style.display = "none";
    state.pendingDeletePages = null;
  }

  async function _executeDelete() {
    const pages = state.pendingDeletePages;
    if (!pages || !pages.length) {
      _hideConfirm();
      return;
    }

    _hideConfirm();
    _setLoading(true);
    _hideError();

    try {
      const result = await API.deletePages(state.documentId, pages);
      _applyDocumentUpdate(result);
      Viewer.clearPageSelection();
      Thumbnails.clearSelection();
      Toolbar.setSelectionCount(0);
    } catch (err) {
      _showError(err.message || "Failed to delete pages");
    } finally {
      _setLoading(false);
    }
  }

  function _applyDocumentUpdate(result) {
    if (!result || !result.page_count) return;

    state.pageCount = result.page_count;

    // Refresh viewer (clears cache, rebuilds elements)
    Viewer.refreshDocument(state.pageCount).then(() => {
      // Re-render thumbnails
      Thumbnails.loadDocument(state.documentId, state.pageCount);
      // Update toolbar
      Toolbar.updatePagination(state.currentPage, state.pageCount);
      Toolbar.updateZoom(Viewer.getZoomPercent(), Viewer.getState().fitMode);
      Toolbar.setSelectionCount(0);
      // Ensure current page is valid
      if (state.currentPage > state.pageCount) {
        _goToPage(state.pageCount);
      }
    });

    // Refresh metadata
    _refreshMetadata();
  }

  async function _refreshMetadata() {
    try {
      const meta = await API.getDocument(state.documentId);
      state.pageCount = meta.page_count || state.page_count;
      state.filename = meta.filename || state.filename;
      els.navFilename.textContent = state.filename;
      els.navFilename.title = state.filename;
      Toolbar.updatePagination(state.currentPage, state.pageCount);
    } catch (_) {
      // Metadata refresh is non-critical
    }
  }

  function _rotate() {
    Viewer.setRotation(90);
  }

  // ------------------------------------------------------------------
  // Page operations (extract / duplicate)
  // ------------------------------------------------------------------

  async function _confirmExtract() {
    const selected = Viewer.getSelectedZeroBased();
    if (!selected.length) return;

    // Show extract dialog with selected count pre-filled
    els.extractSelectedCount.textContent = selected.length;
    els.extractRanges.value = "";
    els.extractDialog.style.display = "flex";
  }

  function _hideExtract() {
    els.extractDialog.style.display = "none";
    els.extractRanges.value = "";
  }

  async function _executeExtract() {
    const rangesText = els.extractRanges.value.trim();
    let pageNumbers;

    if (rangesText) {
      // Parse custom ranges like "1-3, 5, 7-9" (1-based input, convert to 0-based)
      pageNumbers = _parsePageRanges(rangesText, state.pageCount);
      if (pageNumbers === null) {
        _showError("Invalid page range format. Use e.g. 1-3, 5, 7-9");
        return;
      }
    } else {
      // Use currently selected pages
      pageNumbers = Viewer.getSelectedZeroBased();
      if (!pageNumbers.length) {
        _hideExtract();
        return;
      }
    }

    _hideExtract();
    _setLoading(true);
    _hideError();

    try {
      const result = await API.extractPages(state.documentId, pageNumbers);
      state.extractedDocuments.push({
        document_id: result.document_id,
        filename: result.filename,
        page_count: result.page_count,
      });
      _showSuccess(`Extracted ${result.page_count} page(s) to "${result.filename}".`);
      Viewer.clearPageSelection();
      Thumbnails.clearSelection();
      Toolbar.setSelectionCount(0);
    } catch (err) {
      _showError(err.message || "Failed to extract pages");
    } finally {
      _setLoading(false);
    }
  }

  async function _confirmDuplicate() {
    const selected = Viewer.getSelectedZeroBased();
    if (!selected.length) return;

    els.duplicateCount.textContent = selected.length;
    els.duplicateDialog.style.display = "flex";
  }

  function _hideDuplicate() {
    els.duplicateDialog.style.display = "none";
  }

  async function _executeDuplicate() {
    const pages = Viewer.getSelectedZeroBased();
    if (!pages.length) {
      _hideDuplicate();
      return;
    }

    _hideDuplicate();
    _setLoading(true);
    _hideError();

    try {
      const result = await API.duplicatePages(state.documentId, pages, "after");
      _applyDocumentUpdate(result);
      Viewer.clearPageSelection();
      Thumbnails.clearSelection();
      Toolbar.setSelectionCount(0);
      _showSuccess(`Duplicated ${pages.length} page(s).`);
    } catch (err) {
      _showError(err.message || "Failed to duplicate pages");
    } finally {
      _setLoading(false);
    }
  }

  /**
   * Parse a page range string like "1-3, 5, 7-9" (1-based) into
   * zero-based page indices. Validates bounds against pageCount.
   * Returns null on invalid input.
   */
  function _parsePageRanges(text, pageCount) {
    const result = [];
    const parts = text.split(",");
    for (const part of parts) {
      const trimmed = part.trim();
      if (!trimmed) continue;
      const range = trimmed.split("-");
      if (range.length === 1) {
        const n = parseInt(range[0].trim(), 10);
        if (isNaN(n) || n < 1 || n > pageCount) return null;
        result.push(n - 1);
      } else if (range.length === 2) {
        const start = parseInt(range[0].trim(), 10);
        const end = parseInt(range[1].trim(), 10);
        if (
          isNaN(start) ||
          isNaN(end) ||
          start < 1 ||
          end > pageCount ||
          start > end
        ) {
          return null;
        }
        for (let i = start; i <= end; i++) {
          result.push(i - 1);
        }
      } else {
        return null;
      }
    }
    // Remove duplicates while preserving order
    const seen = new Set();
    const unique = [];
    for (const n of result) {
      if (!seen.has(n)) {
        seen.add(n);
        unique.push(n);
      }
    }
    return unique;
  }

  // Split workspace operations
  // ------------------------------------------------------------------

  function _openSplitWorkspace() {
    if (!state.documentId) {
      _showError("No document loaded. Open a PDF first.");
      return;
    }
    state.splitState = {
      mode: "each_page",
      everyN: 1,
      ranges: "",
      outputs: [],
      inProgress: false,
    };
    els.splitOverlay.style.display = "flex";
    els.splitResults.style.display = "none";
    els.splitProgress.style.display = "none";
    els.splitRanges.value = "";
    els.splitEveryN.value = "1";
    els.splitBtnSplit.disabled = true;
    _updateSplitModeUI();
    _updateSplitPreview();
  }

  function _closeSplitWorkspace() {
    els.splitOverlay.style.display = "none";
    els.splitResults.style.display = "none";
    els.splitProgress.style.display = "none";
    state.splitState = {
      mode: "each_page",
      everyN: 1,
      ranges: "",
      outputs: [],
      inProgress: false,
    };
  }

  function _updateSplitModeUI() {
    const mode = state.splitState.mode;
    els.splitEveryNSection.style.display = mode === "every_n_pages" ? "block" : "none";
    els.splitRangesSection.style.display = mode === "ranges" ? "block" : "none";
    els.splitPreviewSection.style.display = mode === "ranges" || mode === "every_n_pages" ? "block" : "none";
    if (mode === "each_page") {
      _updateSplitPreview();
    }
    _updateSplitButtonState();
  }

  function _updateSplitPreview() {
    const mode = state.splitState.mode;
    const pageCount = state.pageCount;
    const previewList = els.splitPreviewList;
    previewList.innerHTML = "";

    if (mode === "each_page") {
      for (let i = 1; i <= pageCount; i++) {
        const item = document.createElement("div");
        item.className = "split-preview-item";
        item.innerHTML = `<span>Page ${i}</span><span>${i}</span>`;
        previewList.appendChild(item);
      }
      els.splitBtnSplit.disabled = false;
      return;
    }

    let ranges;
    if (mode === "every_n_pages") {
      const n = state.splitState.everyN;
      ranges = [];
      for (let i = 0; i < pageCount; i += n) {
        ranges.push([i, Math.min(i + n - 1, pageCount - 1)]);
      }
    } else if (mode === "ranges") {
      const text = els.splitRanges.value.trim();
      if (!text) {
        els.splitBtnSplit.disabled = true;
        return;
      }
      const parsed = _parsePageRanges(text, pageCount);
      if (parsed === null) {
        els.splitBtnSplit.disabled = true;
        return;
      }
      ranges = [];
      for (let i = 0; i < parsed.length; ) {
        const start = parsed[i];
        let end = start;
        while (i + 1 < parsed.length && parsed[i + 1] === end + 1) {
          end = parsed[i + 1];
          i++;
        }
        ranges.push([start, end]);
        i++;
      }
    }

    if (!ranges || ranges.length === 0) {
      els.splitBtnSplit.disabled = true;
      return;
    }

    ranges.forEach(([start, end]) => {
      const pageCount = end - start + 1;
      const item = document.createElement("div");
      item.className = "split-preview-item";
      const start1 = start + 1;
      const end1 = end + 1;
      const label = start === end ? `Page ${start1}` : `Pages ${start1}-${end1}`;
      item.innerHTML = `<span>${label}</span><span>${pageCount}</span>`;
      previewList.appendChild(item);
    });

    els.splitBtnSplit.disabled = false;
  }

  function _updateSplitButtonState() {
    if (state.splitState.mode === "each_page") {
      els.splitBtnSplit.disabled = state.pageCount === 0;
    }
  }

  async function _executeSplit() {
    const mode = state.splitState.mode;
    let ranges = null;
    let pagesPerFile = null;

    if (mode === "ranges") {
      const parsed = _parsePageRanges(els.splitRanges.value.trim(), state.pageCount);
      if (parsed === null || parsed.length === 0) {
        _showError("Invalid page range format.");
        return;
      }
      ranges = [];
      for (let i = 0; i < parsed.length; ) {
        const start = parsed[i];
        let end = start;
        while (i + 1 < parsed.length && parsed[i + 1] === end + 1) {
          end = parsed[i + 1];
          i++;
        }
        ranges.push([start, end]);
        i++;
      }
    } else if (mode === "every_n_pages") {
      pagesPerFile = state.splitState.everyN;
    }

    state.splitState.inProgress = true;
    els.splitProgress.style.display = "block";
    els.splitProgressFill.style.width = "0%";
    els.splitProgressMessage.textContent = "Splitting PDF...";
    _setLoading(true);
    _hideError();

    try {
      const result = await API.splitDocument(state.documentId, mode, ranges, pagesPerFile);
      state.splitState.outputs = result.outputs;

      els.splitProgress.style.display = "none";
      els.splitResults.style.display = "block";
      els.splitResultsCount.textContent = `${result.total_files} file${result.total_files !== 1 ? "s" : ""}`;

      els.splitResultsList.innerHTML = "";
      result.outputs.forEach((out) => {
        const item = document.createElement("div");
        item.className = "split-result-item";
        const start1 = out.page_range[0] + 1;
        const end1 = out.page_range[1] + 1;
        const rangeLabel = start1 === end1 ? `Page ${start1}` : `Pages ${start1}-${end1}`;
        item.innerHTML = `
          <div class="split-result-info">
            <div class="split-result-filename">${out.filename}</div>
            <div class="split-result-details">${out.page_count} page${out.page_count !== 1 ? "s" : ""} &#8226; ${rangeLabel}</div>
          </div>
          <div class="split-result-actions">
            <button type="button" class="split-result-download" data-id="${out.document_id}" title="Download">
              Download
            </button>
          </div>
        `;
        els.splitResultsList.appendChild(item);
      });

      els.splitResultsList.querySelectorAll(".split-result-download").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const docId = e.currentTarget.getAttribute("data-id");
          _downloadSplitPdf(docId);
        });
      });

      _showSuccess(`Split into ${result.total_files} document${result.total_files !== 1 ? "s" : ""}.`);

    } catch (err) {
      _showError(err.message || "Failed to split PDF");
    } finally {
      _setLoading(false);
      state.splitState.inProgress = false;
    }
  }

  async function _downloadSplitPdf(documentId) {
    try {
      await API.downloadPDF(documentId, "split_output.pdf");
    } catch (err) {
      _showError(err.message || "Failed to download split PDF");
    }
  }

  async function _downloadSplitZip() {
    const ids = state.splitState.outputs.map((o) => o.document_id);
    try {
      await API.downloadSplitZip(ids);
      _showSuccess("Downloaded all split PDFs as ZIP.");
    } catch (err) {
      _showError(err.message || "Failed to download ZIP");
    }
  }

  function _closeSplitResults() {
    els.splitResults.style.display = "none";
    _closeSplitWorkspace();
  }

  // ------------------------------------------------------------------
  // Compress workspace operations
  // ------------------------------------------------------------------

  function _openCompressWorkspace() {
    if (!state.documentId) {
      _showError("No document loaded. Open a PDF first.");
      return;
    }
    state.compressState = {
      level: "medium",
      jpegQuality: null,
      maxImageDpi: null,
      downsampleImages: null,
      outputs: [],
      inProgress: false,
    };
    els.compressOverlay.style.display = "flex";
    els.compressResults.style.display = "none";
    els.compressProgress.style.display = "none";
    els.compressBtnCompress.disabled = false;
    _updateCompressModeUI();
  }

  function _closeCompressWorkspace() {
    els.compressOverlay.style.display = "none";
    els.compressResults.style.display = "none";
    els.compressProgress.style.display = "none";
    state.compressState = {
      level: "medium",
      jpegQuality: null,
      maxImageDpi: null,
      downsampleImages: null,
      outputs: [],
      inProgress: false,
    };
  }

  function _updateCompressModeUI() {
    const mode = state.compressState.level;
    const hints = {
      low: "Best quality with minimal size reduction. Preserves images at original quality.",
      medium: "Good size reduction while maintaining visual quality.",
      high: "Maximum compression with acceptable visual trade-offs.",
    };
    els.compressHint.textContent = hints[mode] || hints.medium;
  }

  async function _executeCompress() {
    const level = state.compressState.level;
    state.compressState.inProgress = true;
    els.compressProgress.style.display = "block";
    els.compressProgressFill.style.width = "0%";
    els.compressProgressMessage.textContent = "Compressing PDF...";
    _setLoading(true);
    _hideError();

    try {
      const result = await API.compressDocument(
        state.documentId,
        level,
        state.compressState.jpegQuality,
        state.compressState.maxImageDpi,
        state.compressState.downsampleImages
      );
      state.compressState.outputs = [result];

      els.compressProgress.style.display = "none";
      els.compressResults.style.display = "block";

      // Show results
      els.compressResultFilename.textContent = result.filename;
      els.compressResultDetails.textContent = `${result.level} level — ${result.page_count} page${result.page_count !== 1 ? "s" : ""}`;
      els.compressSizeOriginal.textContent = formatBytes(result.original_size);
      els.compressSizeCompressed.textContent = formatBytes(result.compressed_size);
      els.compressSizeSaved.textContent = formatBytes(result.bytes_saved);
      els.compressSizeReduction.textContent = `${result.reduction_percent}%`;

      _showSuccess(`Compressed ${result.original_filename} — ${result.reduction_percent}% reduction.`);

    } catch (err) {
      _showError(err.message || "Failed to compress PDF");
    } finally {
      _setLoading(false);
      state.compressState.inProgress = false;
    }
  }

  async function _downloadCompressedPdf() {
    const docId = state.compressState.outputs[0]?.document_id;
    if (!docId) return;
    try {
      await API.downloadPDF(docId, "compressed.pdf");
    } catch (err) {
      _showError(err.message || "Failed to download compressed PDF");
    }
  }

  async function _openCompressedInViewer() {
    const docId = state.compressState.outputs[0]?.document_id;
    if (!docId) return;
    _closeCompressWorkspace();
    state.documentId = docId;
    state.filename = state.compressState.outputs[0].filename;
    state.pageCount = state.compressState.outputs[0].page_count || 0;
    state.currentPage = 1;

    els.navFilename.textContent = state.filename;
    els.navFilename.title = state.filename;
    els.navStatus.textContent = "Document loaded";
    els.btnDownload.disabled = false;

    _showViewer();
    Viewer.loadDocument(state.documentId, state.pageCount);
    Thumbnails.loadDocument(state.documentId, state.pageCount);
    Toolbar.updatePagination(state.currentPage, state.pageCount);
    Toolbar.updateZoom(Viewer.getZoomPercent(), Viewer.getState().fitMode);
  }

  function formatBytes(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  }

  // UI helpers

  // ------------------------------------------------------------------
  // Merge workspace operations
  // ------------------------------------------------------------------

  function _openMergeWorkspace() {
    els.mergeOverlay.style.display = "flex";
    _renderMergeList();
  }

  function _closeMergeWorkspace() {
    els.mergeOverlay.style.display = "none";
  }

  async function _addFilesToMergeList(files) {
    _setLoading(true);
    _hideError();

    try {
      for (const file of files) {
        if (!file.type || !file.type.includes("pdf")) {
          _showError(`"${file.name}" is not a PDF file.`);
          continue;
        }

        try {
          const result = await API.uploadPDF(file);
          // Check if already in merge list
          const alreadyExists = state.mergeList.some(
            (item) => item.document_id === result.document_id
          );
          if (!alreadyExists) {
            state.mergeList.push({
              document_id: result.document_id,
              filename: result.filename,
              page_count: result.page_count,
            });
          }
        } catch (err) {
          _showError(`Failed to upload "${file.name}": ${err.message}`);
        }
      }

      _renderMergeList();
      _updateMergeButtonState();
    } finally {
      _setLoading(false);
    }
  }

  function _removeFromMergeList(index) {
    state.mergeList.splice(index, 1);
    _renderMergeList();
    _updateMergeButtonState();
  }

  function _clearMergeList() {
    state.mergeList = [];
    _renderMergeList();
    _updateMergeButtonState();
  }

  function _renderMergeList() {
    if (!els.mergeList) return;

    els.mergeList.innerHTML = "";

    if (state.mergeList.length === 0) {
      const empty = document.createElement("div");
      empty.className = "merge-list-empty";
      empty.textContent = "No documents added yet.";
      els.mergeList.appendChild(empty);
      return;
    }

    state.mergeList.forEach((item, index) => {
      const mergeItem = document.createElement("div");
      mergeItem.className = "merge-item";
      mergeItem.dataset.index = index;
      mergeItem.draggable = true;

      // Order badge
      const orderBadge = document.createElement("span");
      orderBadge.className = "merge-item-order";
      orderBadge.textContent = index + 1;
      mergeItem.appendChild(orderBadge);

      // Info
      const info = document.createElement("div");
      info.className = "merge-item-info";

      const filename = document.createElement("div");
      filename.className = "merge-item-filename";
      filename.textContent = item.filename;
      info.appendChild(filename);

      const pages = document.createElement("div");
      pages.className = "merge-item-pages";
      pages.textContent = `${item.page_count} page${item.page_count !== 1 ? "s" : ""}`;
      info.appendChild(pages);

      mergeItem.appendChild(info);

      // Actions
      const actions = document.createElement("div");
      actions.className = "merge-item-actions";

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "merge-item-remove";
      removeBtn.title = "Remove from merge list";
      removeBtn.textContent = "Remove";
      removeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        _removeFromMergeList(index);
      });
      actions.appendChild(removeBtn);

      mergeItem.appendChild(actions);

      // Drag and drop
      mergeItem.addEventListener("dragstart", (e) => {
        mergeItem.classList.add("drag-source");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(index));
      });

      mergeItem.addEventListener("dragend", () => {
        mergeItem.classList.remove("drag-source");
        document.querySelectorAll(".merge-item").forEach((el) => {
          el.classList.remove("drag-over");
        });
      });

      mergeItem.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        mergeItem.classList.add("drag-over");
      });

      mergeItem.addEventListener("dragleave", () => {
        mergeItem.classList.remove("drag-over");
      });

      mergeItem.addEventListener("drop", (e) => {
        e.preventDefault();
        mergeItem.classList.remove("drag-over");

        const sourceIndex = parseInt(e.dataTransfer.getData("text/plain"), 10);
        const targetIndex = index;
        if (sourceIndex !== targetIndex) {
          const [moved] = state.mergeList.splice(sourceIndex, 1);
          state.mergeList.splice(targetIndex, 0, moved);
          _renderMergeList();
          _updateMergeButtonState();
        }
      });

      els.mergeList.appendChild(mergeItem);
    });
  }

  function _updateMergeButtonState() {
    if (els.mergeBtnMerge) {
      els.mergeBtnMerge.disabled = state.mergeList.length < 2;
    }
  }

  async function _executeMerge() {
    if (state.mergeList.length < 2) return;

    const documentIds = state.mergeList.map((item) => item.document_id);

    _setLoading(true);
    els.mergeProgress.style.display = "block";
    els.mergeProgressFill.style.width = "0%";
    els.mergeProgressMessage.textContent = "Merging documents...";
    _hideError();

    try {
      const result = await API.mergeDocuments(documentIds);
      els.mergeProgressFill.style.width = "100%";
      _showSuccess(`Merged ${state.mergeList.length} document(s) into "${result.filename}".`);

      // Close merge workspace after a brief delay
      setTimeout(() => {
        _closeMergeWorkspace();
        els.mergeProgress.style.display = "none";
      }, 800);

      // Load the merged document into the viewer
      state.documentId = result.document_id;
      state.filename = result.filename;
      state.pageCount = result.page_count || 0;
      state.currentPage = 1;

      els.navFilename.textContent = state.filename;
      els.navFilename.title = state.filename;
      els.navStatus.textContent = "Document loaded";
      els.btnDownload.disabled = false;

      _showViewer();
      Viewer.loadDocument(state.documentId, state.pageCount);
      Thumbnails.loadDocument(state.documentId, state.pageCount);
      Toolbar.updatePagination(state.currentPage, state.pageCount);
      Toolbar.updateZoom(Viewer.getZoomPercent(), Viewer.getState().fitMode);

      // Clear merge list
      state.mergeList = [];
      _renderMergeList();
      _updateMergeButtonState();
    } catch (err) {
      _showError(err.message || "Failed to merge documents");
    } finally {
      _setLoading(false);
      if (!els.mergeOverlay.style.display || els.mergeOverlay.style.display === "none") {
        els.mergeProgress.style.display = "none";
      }
    }
  }

  // ------------------------------------------------------------------
  // UI helpers
  // ------------------------------------------------------------------

  function _showViewer() {
    els.emptyState.style.display = "none";
    els.viewerContainer.style.display = "flex";
    els.viewerToolbar.style.display = "flex";
  }

  function _showEmptyState() {
    els.emptyState.style.display = "flex";
    els.viewerContainer.style.display = "none";
    els.viewerToolbar.style.display = "none";
  }

  function _setLoading(loading) {
    state.isLoading = loading;
    els.btnOpen.disabled = loading;
    if (els.btnMerge) els.btnMerge.disabled = loading;
    Toolbar.setLoading(loading);
    if (loading) {
      els.navStatus.textContent = "Loading…";
    } else if (state.documentId) {
      els.navStatus.textContent = "Document loaded";
    } else {
      els.navStatus.textContent = "Ready";
    }
  }

  function _showUploadOverlay(show) {
    els.uploadOverlay.style.display = show ? "flex" : "none";
  }

  function _showError(message) {
    els.errorToastMessage.textContent = message;
    els.errorToast.style.display = "flex";
    // Auto-dismiss after 8 seconds
    setTimeout(() => _hideError(), 8000);
  }

  function _hideError() {
    els.errorToast.style.display = "none";
  }

  function _showSuccess(message) {
    els.successToastMessage.textContent = message;
    els.successToast.style.display = "flex";
    setTimeout(() => _hideSuccess(), 5000);
  }

  function _hideSuccess() {
    els.successToast.style.display = "none";
  }

  function _toggleSidebar() {
    state.sidebarVisible = !state.sidebarVisible;
    if (state.sidebarVisible) {
      els.sidebar.classList.remove("collapsed");
      els.sidebarToggle.textContent = "&#9664;";
      els.sidebarToggle.title = "Hide thumbnails";
      els.btnToggleThumbnails.title = "Hide thumbnails";
    } else {
      els.sidebar.classList.add("collapsed");
      els.sidebarToggle.textContent = "&#9654;";
      els.sidebarToggle.title = "Show thumbnails";
      els.btnToggleThumbnails.title = "Show thumbnails";
    }
    // Re-layout after toggle
    setTimeout(() => Viewer.getState() && null, 50);
  }

  // ------------------------------------------------------------------
  // Public
  // ------------------------------------------------------------------

  return {
    init,
  };
})();

// ------------------------------------------------------------------
// Boot
// ------------------------------------------------------------------
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => App.init());
} else {
  App.init();
}
