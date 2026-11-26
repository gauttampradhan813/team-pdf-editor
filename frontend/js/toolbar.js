/* =====================================================================
   TeamPDF Studio — Toolbar module
   Viewer controls: page navigation, zoom, rotate, toggle thumbnails.
   ===================================================================== */

const Toolbar = (() => {
  let elements = {};
  let callbacks = {};

  function init(refs, cb) {
    elements = refs;
    callbacks = cb || {};
    _bindEvents();
  }

  function _bindEvents() {
    // Page navigation
    elements.btnPrev.addEventListener("click", () => {
      if (callbacks.onPrevPage) callbacks.onPrevPage();
    });
    elements.btnNext.addEventListener("click", () => {
      if (callbacks.onNextPage) callbacks.onNextPage();
    });

    // Page input
    elements.pageInput.addEventListener("change", () => {
      const val = parseInt(elements.pageInput.value, 10);
      if (!isNaN(val) && callbacks.onPageChange) {
        callbacks.onPageChange(val);
      }
    });
    elements.pageInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const val = parseInt(elements.pageInput.value, 10);
        if (!isNaN(val) && callbacks.onPageChange) {
          callbacks.onPageChange(val);
        }
      }
    });

    // Zoom controls
    elements.btnZoomOut.addEventListener("click", () => {
      if (callbacks.onZoomOut) callbacks.onZoomOut();
    });
    elements.btnZoomIn.addEventListener("click", () => {
      if (callbacks.onZoomIn) callbacks.onZoomIn();
    });
    elements.btnFitWidth.addEventListener("click", () => {
      if (callbacks.onFitWidth) callbacks.onFitWidth();
    });
    elements.btnFitPage.addEventListener("click", () => {
      if (callbacks.onFitPage) callbacks.onFitPage();
    });
    elements.btnActualSize.addEventListener("click", () => {
      if (callbacks.onActualSize) callbacks.onActualSize();
    });

    // Rotate selected
    elements.btnRotate.addEventListener("click", () => {
      if (callbacks.onRotateSelected) callbacks.onRotateSelected();
    });

    // Delete selected
    elements.btnDeletePage.addEventListener("click", () => {
      if (callbacks.onDeleteSelected) callbacks.onDeleteSelected();
    });

    // Extract selected
    elements.btnExtractPage.addEventListener("click", () => {
      if (callbacks.onExtractSelected) callbacks.onExtractSelected();
    });

    // Duplicate selected
    elements.btnDuplicatePage.addEventListener("click", () => {
      if (callbacks.onDuplicateSelected) callbacks.onDuplicateSelected();
    });

    // Toggle thumbnails
    elements.btnToggleThumbnails.addEventListener("click", () => {
      if (callbacks.onToggleThumbnails) callbacks.onToggleThumbnails();
    });
  }

  // ------------------------------------------------------------------
  // State updates
  // ------------------------------------------------------------------

  function updatePagination(currentPage, totalPages) {
    if (!elements) return;
    if (elements.pageInput) {
      elements.pageInput.value = currentPage;
      elements.pageInput.max = totalPages;
    }
    if (elements.pageOfTotal) {
      elements.pageOfTotal.textContent = totalPages;
    }
    if (elements.btnPrev) {
      elements.btnPrev.disabled = currentPage <= 1;
    }
    if (elements.btnNext) {
      elements.btnNext.disabled = currentPage >= totalPages || totalPages === 0;
    }
  }

  function updateZoom(percent, fitMode) {
    if (!elements) return;
    if (elements.toolbarZoom) {
      elements.toolbarZoom.textContent = `${percent}%`;
    }

    const toggles = [elements.btnFitWidth, elements.btnFitPage, elements.btnActualSize];
    toggles.forEach((btn) => {
      if (!btn) return;
      const mode = btn.dataset.mode;
      if (mode === fitMode) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });
  }

  function setSelectionCount(count) {
    if (!elements) return;
    if (elements.btnRotate) {
      elements.btnRotate.disabled = count === 0;
    }
    if (elements.btnDeletePage) {
      elements.btnDeletePage.disabled = count === 0;
    }
    if (elements.btnExtractPage) {
      elements.btnExtractPage.disabled = count === 0;
    }
    if (elements.btnDuplicatePage) {
      elements.btnDuplicatePage.disabled = count === 0;
    }
  }

  function setLoading(loading) {
    if (elements.btnPrev) elements.btnPrev.disabled = loading;
    if (elements.btnNext) elements.btnNext.disabled = loading;
    if (elements.btnZoomIn) elements.btnZoomIn.disabled = loading;
    if (elements.btnZoomOut) elements.btnZoomOut.disabled = loading;
    if (elements.btnRotate) elements.btnRotate.disabled = loading;
    if (elements.btnDeletePage) elements.btnDeletePage.disabled = loading;
    if (elements.btnExtractPage) elements.btnExtractPage.disabled = loading;
    if (elements.btnDuplicatePage) elements.btnDuplicatePage.disabled = loading;
  }

  return {
    init,
    updatePagination,
    updateZoom,
    setSelectionCount,
    setLoading,
  };
})();
