/* =====================================================================
   TeamPDF Studio — Viewer module
   Renders PDF pages on demand, manages zoom and viewport.
   ===================================================================== */

const Viewer = (() => {
  // Default render scale (matches backend default: 1.5 = ~108 DPI)
  const DEFAULT_SCALE = 1.5;
  const MIN_SCALE = 0.5;
  const MAX_SCALE = 4.0;
  const ZOOM_STEP = 0.25;

  // Page padding between rendered pages (in CSS pixels at 1:1 scale)
  const PAGE_PADDING = 24;

  // Resolved via init()
  let container;
  let viewport;
  let onPageRendered;
  let onError;

  // State
  let documentId = null;
  let pageCount = 0;
  let currentPage = 1;
  let rotation = 0; // 0, 90, 180, 270
  let scale = DEFAULT_SCALE;
  let fitMode = "fit-width"; // fit-width | fit-page | actual
  const selectedPages = new Set(); // 1-based page numbers

  // Browser-side cache: key = "${pageNumber}:${scale}:${rotation}" -> blob URL
  const pageCache = new Map();

  // In-flight renders keyed by cache key
  const inFlight = new Map();

  // DOM page elements
  const pageElements = new Map(); // pageNumber -> { el, img }

  // ------------------------------------------------------------------
  // Initialization
  // ------------------------------------------------------------------

  function init(options) {
    container = options.container;
    viewport = options.viewport;
    onPageRendered = options.onPageRendered || (() => {});
    onError = options.onError || (() => {});
  }

  // ------------------------------------------------------------------
  // Document lifecycle
  // ------------------------------------------------------------------

  function loadDocument(docId, count) {
    unloadDocument();
    documentId = docId;
    pageCount = count;
    currentPage = 1;
    rotation = 0;
    scale = DEFAULT_SCALE;
    fitMode = "fit-width";

    _createPageElements();
    _layoutPages();
  }

  function unloadDocument() {
    // Revoke all cached blob URLs
    for (const url of pageCache.values()) {
      URL.revokeObjectURL(url);
    }
    pageCache.clear();
    inFlight.clear();

    // Remove page elements
    for (const entry of pageElements.values()) {
      if (entry.el && entry.el.parentNode) {
        entry.el.parentNode.removeChild(entry.el);
      }
    }
    pageElements.clear();

    documentId = null;
    pageCount = 0;
    currentPage = 1;
    rotation = 0;
    scale = DEFAULT_SCALE;
    fitMode = "fit-width";
  }

  function _createPageElements() {
    viewport.innerHTML = "";
    for (let i = 1; i <= pageCount; i++) {
      const pageEl = document.createElement("div");
      pageEl.className = "pdf-page";
      pageEl.dataset.page = i;

      const img = document.createElement("img");
      img.alt = `Page ${i}`;
      img.style.display = "block";
      pageEl.appendChild(img);

      const badge = document.createElement("span");
      badge.className = "page-selection-badge";
      badge.textContent = "✓";
      badge.style.display = "none";
      pageEl.appendChild(badge);

      viewport.appendChild(pageEl);
      pageElements.set(i, { el: pageEl, img, badge });
    }
  }

  // ------------------------------------------------------------------
  // Public state accessors
  // ------------------------------------------------------------------

  function getState() {
    return {
      documentId,
      pageCount,
      currentPage,
      rotation,
      scale,
      fitMode,
    };
  }

  function setCurrentPage(pageNumber) {
    if (pageNumber < 1 || pageNumber > pageCount) return false;
    currentPage = pageNumber;
    _updateActiveStates();
    _renderVisiblePages();
    return true;
  }

  function nextPage() {
    return setCurrentPage(currentPage + 1);
  }

  function prevPage() {
    return setCurrentPage(currentPage - 1);
  }

  function setRotation(degrees) {
    rotation = ((rotation + degrees) % 360 + 360) % 360;
    _applyRotation();
    _renderVisiblePages();
  }

  // ------------------------------------------------------------------
  // Page selection
  // ------------------------------------------------------------------

  function togglePageSelection(pageNumber) {
    if (selectedPages.has(pageNumber)) {
      selectedPages.delete(pageNumber);
    } else {
      selectedPages.add(pageNumber);
    }
    _updatePageSelectionUI(pageNumber);
    return selectedPages.has(pageNumber);
  }

  function selectAllPages() {
    for (let i = 1; i <= pageCount; i++) {
      selectedPages.add(i);
    }
    _updateAllPageSelectionUI();
    return selectedPages.size;
  }

  function clearPageSelection() {
    selectedPages.clear();
    _updateAllPageSelectionUI();
  }

  function getSelectedPages() {
    return [...selectedPages].sort((a, b) => a - b);
  }

  function getSelectedZeroBased() {
    return [...selectedPages].map((p) => p - 1).sort((a, b) => a - b);
  }

  function isPageSelected(pageNumber) {
    return selectedPages.has(pageNumber);
  }

  function _updatePageSelectionUI(pageNumber) {
    const entry = pageElements.get(pageNumber);
    if (!entry) return;
    if (selectedPages.has(pageNumber)) {
      entry.el.classList.add("selected");
      entry.badge.style.display = "block";
    } else {
      entry.el.classList.remove("selected");
      entry.badge.style.display = "none";
    }
  }

  function _updateAllPageSelectionUI() {
    for (const [pageNum, entry] of pageElements.entries()) {
      if (selectedPages.has(pageNum)) {
        entry.el.classList.add("selected");
        entry.badge.style.display = "block";
      } else {
        entry.el.classList.remove("selected");
        entry.badge.style.display = "none";
      }
    }
  }

  // ------------------------------------------------------------------
  // Document refresh after operations
  // ------------------------------------------------------------------

  /**
   * Refresh the viewer after a document modification.
   * Clears browser-side render cache, rebuilds page elements, and
   * re-renders visible pages.
   */
  async function refreshDocument(newPageCount) {
    // Revoke all cached blob URLs
    for (const url of pageCache.values()) {
      URL.revokeObjectURL(url);
    }
    pageCache.clear();
    inFlight.clear();

    pageCount = newPageCount;
    selectedPages.clear();

    // Rebuild page elements to match new count
    _createPageElements();
    _applyRotation();
    _updateAllPageSelectionUI();
    _renderVisiblePages();
  }

  function getState() {
    return {
      documentId,
      pageCount,
      currentPage,
      rotation,
      scale,
      fitMode,
      selectedPages: [...selectedPages],
    };
  }

  function zoomIn() {
    if (fitMode !== "actual") {
      fitMode = "actual";
    }
    scale = Math.min(MAX_SCALE, scale + ZOOM_STEP);
    _renderVisiblePages();
  }

  function zoomOut() {
    if (fitMode !== "actual") {
      fitMode = "actual";
    }
    scale = Math.max(MIN_SCALE, scale - ZOOM_STEP);
    _renderVisiblePages();
  }

  function setFitWidth() {
    fitMode = "fit-width";
    _calculateFitScale();
    _renderVisiblePages();
  }

  function setFitPage() {
    fitMode = "fit-page";
    _calculateFitScale();
    _renderVisiblePages();
  }

  function setActualSize() {
    fitMode = "actual";
    scale = DEFAULT_SCALE;
    _renderVisiblePages();
  }

  function getZoomPercent() {
    return Math.round(scale * 100);
  }

  function isFitModeActive(mode) {
    return fitMode === mode;
  }

  // ------------------------------------------------------------------
  // Internal: layout and rendering
  // ------------------------------------------------------------------

  function _layoutPages() {
    const containerWidth = container.clientWidth;
    const availableWidth = containerWidth - 40; // padding

    if (fitMode === "fit-width") {
      _calculateFitScale();
    } else if (fitMode === "fit-page") {
      _calculateFitScale();
    }

    _applyRotation();
    _renderVisiblePages();
  }

  function _calculateFitScale() {
    if (!documentId || pageCount === 0) return;

    // Use page 1 dimensions as reference (all pages same size in most PDFs)
    const entry = pageElements.get(1);
    if (!entry) return;

    const pageEl = entry.el;
    const pageRect = pageEl.getBoundingClientRect();

    // If page has no rendered size yet, estimate from default 595x842 at scale 1.5
    // This is a fallback; actual size is set after first render.
    const containerWidth = container.clientWidth;
    const containerHeight = container.clientHeight;
    const availWidth = containerWidth - 40;
    const availHeight = containerHeight - 40;

    const baseWidth = 595 * DEFAULT_SCALE;
    const baseHeight = 842 * DEFAULT_SCALE;

    if (fitMode === "fit-width") {
      scale = availWidth / baseWidth;
    } else if (fitMode === "fit-page") {
      const wScale = availWidth / baseWidth;
      const hScale = availHeight / baseHeight;
      scale = Math.min(wScale, hScale);
    }

    scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale));
  }

  function _applyRotation() {
    for (const entry of pageElements.values()) {
      entry.el.className = `pdf-page${rotation ? ` rotate-${rotation}` : ""}`;
    }
  }

  function _updateActiveStates() {
    for (const [pageNum, entry] of pageElements.entries()) {
      if (pageNum === currentPage) {
        entry.el.classList.add("active");
      } else {
        entry.el.classList.remove("active");
      }
    }
  }

  // Determine which pages should be rendered based on viewport
  function _getVisiblePageRange() {
    if (!viewport) return { start: 1, end: pageCount };

    const rect = viewport.getBoundingClientRect();
    const viewportTop = rect.top + window.scrollY;
    const viewportBottom = viewportBottom = rect.bottom + window.scrollY;

    // Render current page plus neighbors (pre-render up to 2 pages before/after)
    const start = Math.max(1, currentPage - 2);
    const end = Math.min(pageCount, currentPage + 2);
    return { start, end };
  }

  async function _renderVisiblePages() {
    if (!documentId) return;

    const { start, end } = _getVisiblePageRange();

    // Render pages in range
    for (let i = start; i <= end; i++) {
      await _ensurePageRendered(i);
    }
  }

  async function _ensurePageRendered(pageNumber) {
    const entry = pageElements.get(pageNumber);
    if (!entry) return;

    const cacheKey = `${pageNumber}:${scale}:${rotation}`;

    // If already cached in-memory, use it
    if (pageCache.has(cacheKey)) {
      _setPageImage(entry, pageCache.get(cacheKey));
      entry.el.classList.remove("loading");
      onPageRendered(pageNumber, true);
      return;
    }

    // If already in flight, wait for it
    if (inFlight.has(cacheKey)) {
      try {
        const blobUrl = await inFlight.get(cacheKey);
        _setPageImage(entry, blobUrl);
        entry.el.classList.remove("loading");
        onPageRendered(pageNumber, true);
      } catch (err) {
        entry.el.classList.remove("loading");
        onError(err, pageNumber);
      }
      return;
    }

    // Mark loading
    entry.el.classList.add("loading");

    const promise = API.renderPage(documentId, pageNumber, scale)
      .then((blobUrl) => {
        pageCache.set(cacheKey, blobUrl);
        _setPageImage(entry, blobUrl);
        entry.el.classList.remove("loading");
        onPageRendered(pageNumber, true);
        return blobUrl;
      })
      .catch((err) => {
        entry.el.classList.remove("loading");
        onError(err, pageNumber);
        throw err;
      })
      .finally(() => {
        inFlight.delete(cacheKey);
      });

    inFlight.set(cacheKey, promise);
    return promise;
  }

  function _setPageImage(entry, blobUrl) {
    entry.img.src = blobUrl;
    // Set intrinsic dimensions based on scale and rotation
    const baseW = 595 * scale;
    const baseH = 842 * scale;
    const isRotated = rotation === 90 || rotation === 270;
    entry.img.style.width = `${isRotated ? baseH : baseW}px`;
    entry.img.style.height = `${isRotated ? baseW : baseH}px`;
    entry.el.style.width = `${isRotated ? baseH : baseW}px`;
    entry.el.style.height = `${isRotated ? baseW : baseH}px`;
  }

  // ------------------------------------------------------------------
  // Expose specific page render (for thumbnails / on-demand)
  // ------------------------------------------------------------------

  async function renderPageOnDemand(pageNumber) {
    if (!documentId) return;
    await _ensurePageRendered(pageNumber);
  }

  function getPageElement(pageNumber) {
    return pageElements.get(pageNumber);
  }

  // Clear cache when scale/rotation changes
  function _onScaleChanged() {
    // Page cache is keyed by scale, so changing scale naturally creates new keys.
    // Old URLs should be revoked periodically; for now we let them GC.
    _renderVisiblePages();
  }

  // Public: called when scale changes externally
  function setScale(newScale) {
    fitMode = "actual";
    scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, newScale));
    _renderVisiblePages();
  }

  return {
    init,
    loadDocument,
    unloadDocument,
    getState,
    setCurrentPage,
    nextPage,
    prevPage,
    setRotation,
    zoomIn,
    zoomOut,
    setFitWidth,
    setFitPage,
    setActualSize,
    setScale,
    getZoomPercent,
    isFitModeActive,
    renderPageOnDemand,
    getPageElement,
    togglePageSelection,
    selectAllPages,
    clearPageSelection,
    getSelectedPages,
    getSelectedZeroBased,
    isPageSelected,
    refreshDocument,
  };
})();
