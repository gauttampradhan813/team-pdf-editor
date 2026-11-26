/* =====================================================================
   TeamPDF Studio — Thumbnails module
   Generates and manages page thumbnail navigation.
   ===================================================================== */

const Thumbnails = (() => {
  let listElement;
  let onPageClick;
  let onToggle;

  let documentId = null;
  let pageCount = 0;
  let currentPage = 1;

  const thumbnailCache = new Map(); // pageNumber -> blob URL
  const inFlight = new Map();

  function init(options) {
    listElement = options.listElement;
    onPageClick = options.onPageClick || (() => {});
    onToggle = options.onToggle || (() => {});
  }

  function loadDocument(docId, count) {
    clear();
    documentId = docId;
    pageCount = count;
    currentPage = 1;
    _renderList();
  }

  function unloadDocument() {
    for (const url of thumbnailCache.values()) {
      URL.revokeObjectURL(url);
    }
    thumbnailCache.clear();
    inFlight.clear();
    clear();
    documentId = null;
    pageCount = 0;
    currentPage = 1;
  }

  function clear() {
    if (!listElement) return;
    listElement.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "thumbnails-empty";
    empty.textContent = "Open a document to see pages";
    listElement.appendChild(empty);
  }

  function setCurrentPage(pageNumber) {
    currentPage = pageNumber;
    _updateActive();
  }

  // ------------------------------------------------------------------
  // Internal rendering
  // ------------------------------------------------------------------

  function _renderList() {
    if (!listElement) return;
    listElement.innerHTML = "";

    for (let i = 1; i <= pageCount; i++) {
      const item = document.createElement("div");
      item.className = `thumbnail-item${i === currentPage ? " active" : ""}`;
      item.dataset.page = i;
      item.setAttribute("role", "option");
      item.setAttribute("aria-label", `Page ${i}`);
      item.tabIndex = i === currentPage ? 0 : -1;

      const img = document.createElement("img");
      img.className = "thumbnail-img";
      img.alt = `Page ${i}`;
      item.appendChild(img);

      const num = document.createElement("span");
      num.className = "thumbnail-page-number";
      num.textContent = i;
      item.appendChild(num);

      item.addEventListener("click", () => {
        onPageClick(i);
      });

      item.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onPageClick(i);
        }
      });

      listElement.appendChild(item);

      // Render thumbnail on demand (low priority)
      _renderThumbnail(i);
    }
  }

  function _updateActive() {
    const items = listElement.querySelectorAll(".thumbnail-item");
    items.forEach((item) => {
      const page = parseInt(item.dataset.page, 10);
      if (page === currentPage) {
        item.classList.add("active");
        item.tabIndex = 0;
      } else {
        item.classList.remove("active");
        item.tabIndex = -1;
      }
    });
  }

  async function _renderThumbnail(pageNumber) {
    if (!documentId) return;

    const cacheKey = `thumb:${pageNumber}:1.0`;

    if (thumbnailCache.has(cacheKey)) {
      _setThumbnailImage(pageNumber, thumbnailCache.get(cacheKey));
      return;
    }

    if (inFlight.has(cacheKey)) {
      try {
        const url = await inFlight.get(cacheKey);
        _setThumbnailImage(pageNumber, url);
      } catch (_) { /* ignore thumbnail failures */ }
      return;
    }

    const item = listElement.querySelector(`.thumbnail-item[data-page="${pageNumber}"]`);
    const img = item ? item.querySelector(".thumbnail-img") : null;

    // Show placeholder
    if (img) {
      img.style.backgroundColor = "#f0f0f0";
      img.style.width = "62px";
      img.style.height = "80px";
    }

    const promise = API.renderPage(documentId, pageNumber, 1.0)
      .then((blobUrl) => {
        thumbnailCache.set(cacheKey, blobUrl);
        _setThumbnailImage(pageNumber, blobUrl);
        return blobUrl;
      })
      .catch((err) => {
        // Thumbnails are non-critical; fail silently
        if (img) {
          img.style.backgroundColor = "#e8e8e8";
          img.textContent = "?";
        }
      })
      .finally(() => {
        inFlight.delete(cacheKey);
      });

    inFlight.set(cacheKey, promise);
  }

  function _setThumbnailImage(pageNumber, blobUrl) {
    const item = listElement.querySelector(`.thumbnail-item[data-page="${pageNumber}"]`);
    if (!item) return;
    const img = item.querySelector(".thumbnail-img");
    if (!img) return;
    img.src = blobUrl;
    img.style.width = "62px";
    img.style.height = "80px";
  }

  return {
    init,
    loadDocument,
    unloadDocument,
    setCurrentPage,
    renderPageOnDemand: (pageNumber) => {
      // Placeholder for external trigger if needed
    },
  };
})();
