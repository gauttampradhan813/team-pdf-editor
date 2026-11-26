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
        onRotate: () => _rotate(),
        onToggleThumbnails: _toggleSidebar,
      }
    );
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

  function _rotate() {
    Viewer.setRotation(90);
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
