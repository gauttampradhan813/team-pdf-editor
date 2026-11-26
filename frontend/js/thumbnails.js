/* =====================================================================
   TeamPDF Studio — Thumbnails module
   Generates and manages page thumbnail navigation.
   ===================================================================== */

const Thumbnails = (() => {
  let listElement;
  let onPageClick;
  let onPageSelect;
  let onPageReorder;

  let documentId = null;
  let pageCount = 0;
  let currentPage = 1;
  const selectedPages = new Set();

  const thumbnailCache = new Map(); // pageNumber -> blob URL
  const inFlight = new Map();

  // Drag-and-drop state
  let dragSourcePage = null;

  function init(options) {
    listElement = options.listElement;
    onPageClick = options.onPageClick || (() => {});
    onPageSelect = options.onPageSelect || (() => {});
    onPageReorder = options.onPageReorder || (() => {});
  }

  function loadDocument(docId, count) {
    clear();
    documentId = docId;
    pageCount = count;
    currentPage = 1;
    selectedPages.clear();
    _renderList();
  }

  function unloadDocument() {
    for (const url of thumbnailCache.values()) {
      URL.revokeObjectURL(url);
    }
    thumbnailCache.clear();
    inFlight.clear();
    clear();
    selectedPages.clear();
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

  function getSelectedPages() {
    return [...selectedPages].sort((a, b) => a - b);
  }

  function clearSelection() {
    selectedPages.clear();
    _updateSelectionUI();
  }

  // ------------------------------------------------------------------
  // Internal rendering
  // ------------------------------------------------------------------

  function _renderList() {
    if (!listElement) return;
    listElement.innerHTML = "";

    for (let i = 1; i <= pageCount; i++) {
      const item = document.createElement("div");
      item.className = `thumbnail-item${i === currentPage ? " active" : ""}${
        selectedPages.has(i) ? " selected" : ""
      }`;
      item.dataset.page = i;
      item.setAttribute("role", "option");
      item.setAttribute("aria-label", `Page ${i}`);
      item.tabIndex = i === currentPage ? 0 : -1;
      item.draggable = true;

      // Checkbox for selection
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "thumbnail-checkbox";
      checkbox.checked = selectedPages.has(i);
      checkbox.dataset.page = i;
      checkbox.addEventListener("change", (e) => {
        e.stopPropagation();
        const page = parseInt(e.target.dataset.page, 10);
        _toggleSelection(page);
      });

      const img = document.createElement("img");
      img.className = "thumbnail-img";
      img.alt = `Page ${i}`;
      item.appendChild(img);

      const num = document.createElement("span");
      num.className = "thumbnail-page-number";
      num.textContent = i;
      item.appendChild(num);

      item.insertBefore(checkbox, item.firstChild);

      // Click to navigate (if not selecting via checkbox)
      item.addEventListener("click", (e) => {
        if (e.target.tagName === "INPUT") return;
        onPageClick(i);
      });

      item.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onPageClick(i);
        }
      });

      // Drag and drop
      item.addEventListener("dragstart", (e) => {
        dragSourcePage = i;
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(i));
        item.classList.add("drag-source");
      });

      item.addEventListener("dragend", () => {
        item.classList.remove("drag-source");
        dragSourcePage = null;
      });

      item.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        item.classList.add("drag-over");
      });

      item.addEventListener("dragleave", () => {
        item.classList.remove("drag-over");
      });

      item.addEventListener("drop", (e) => {
        e.preventDefault();
        item.classList.remove("drag-over");
        const targetPage = parseInt(item.dataset.page, 10);
        if (dragSourcePage !== null && dragSourcePage !== targetPage) {
          onPageReorder(dragSourcePage, targetPage);
        }
      });

      listElement.appendChild(item);

      // Render thumbnail on demand (low priority)
      _renderThumbnail(i);
    }
  }

  function _toggleSelection(pageNumber) {
    if (selectedPages.has(pageNumber)) {
      selectedPages.delete(pageNumber);
    } else {
      selectedPages.add(pageNumber);
    }
    _updateSelectionUI();
    if (onPageSelect) onPageSelect([...selectedPages].sort((a, b) => a - b));
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

  function _updateSelectionUI() {
    const checkboxes = listElement.querySelectorAll(".thumbnail-checkbox");
    checkboxes.forEach((cb) => {
      const page = parseInt(cb.dataset.page, 10);
      cb.checked = selectedPages.has(page);
    });

    const items = listElement.querySelectorAll(".thumbnail-item");
    items.forEach((item) => {
      const page = parseInt(item.dataset.page, 10);
      if (selectedPages.has(page)) {
        item.classList.add("selected");
      } else {
        item.classList.remove("selected");
      }
    });
  }

  // Apply a new page order (after reorder operation)
  function applyNewOrder(newOrder) {
    // newOrder is zero-based original indices in desired order
    // Rebuild the list to reflect new order
    const items = [];
    for (let i = 1; i <= pageCount; i++) {
      const item = listElement.querySelector(`.thumbnail-item[data-page="${i}"]`);
      if (item) items.push(item);
    }

    // Clear and re-append in new order
    listElement.innerHTML = "";
    for (const origIdx of newOrder) {
      const pageNum = origIdx + 1;
      const item = items.find((el) => parseInt(el.dataset.page, 10) === pageNum);
      if (item) listElement.appendChild(item);
    }

    // Re-render thumbnails for all pages
    for (let i = 1; i <= pageCount; i++) {
      _renderThumbnail(i);
    }
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
    getSelectedPages,
    clearSelection,
    applyNewOrder,
  };
})();
