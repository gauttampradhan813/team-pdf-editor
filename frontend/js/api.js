/* =====================================================================
   TeamPDF Studio — API client module
   Wraps all HTTP calls to the FastAPI backend.
   ===================================================================== */

const API = (() => {
  /**
   * Internal fetch wrapper with consistent error handling.
   * Backend errors follow {"error": {"code": "...", "message": "..."}}.
   */
  async function _request(method, url, options = {}) {
    const { headers = {}, body, signal } = options;
    const fetchOptions = { method, headers, signal };
    if (body !== undefined) {
      fetchOptions.body = body;
    }

    let response;
    try {
      response = await fetch(url, fetchOptions);
    } catch (err) {
      throw new Error(`Network error: ${err.message}`);
    }

    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const json = await response.json();
        if (json && json.error && json.error.message) {
          message = json.error.message;
        } else if (json && typeof json === "string") {
          message = json;
        }
      } catch (_) {
        message = response.statusText || message;
      }
      const err = new Error(message);
      err.status = response.status;
      throw err;
    }

    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return response.json();
    }
    return response;
  }

  /**
   * Upload a PDF file.
   * @param {File} file
   * @param {function} onProgress - (loaded, total) => void
   * @returns {Promise<{document_id, filename, file_size, page_count, metadata, created_at}>}
   */
  async function uploadPDF(file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();

      if (typeof onProgress === "function") {
        xhr.upload.addEventListener("progress", (event) => {
          if (event.lengthComputable) {
            onProgress(event.loaded, event.total);
          }
        });
      }

      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (err) {
            reject(new Error("Invalid upload response"));
          }
        } else {
          let message = `Upload failed (${xhr.status})`;
          try {
            const json = JSON.parse(xhr.responseText);
            if (json && json.error && json.error.message) {
              message = json.error.message;
            }
          } catch (_) { /* ignore */ }
          const err = new Error(message);
          err.status = xhr.status;
          reject(err);
        }
      });

      xhr.addEventListener("error", () => {
        reject(new Error("Network error during upload"));
      });

      xhr.addEventListener("abort", () => {
        reject(new Error("Upload aborted"));
      });

      xhr.open("POST", "/documents", true);
      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    });
  }

  /**
   * Get document metadata.
   * @param {string} documentId
   */
  async function getDocument(documentId) {
    return _request("GET", `/documents/${encodeURIComponent(documentId)}`);
  }

  /**
   * Download the original PDF file.
   * @param {string} documentId
   * @param {string} filename
   */
  async function downloadPDF(documentId, filename) {
    const response = await _request("GET", `/documents/${encodeURIComponent(documentId)}/download`);
    if (!(response instanceof Response)) {
      throw new Error("Unexpected download response");
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "document.pdf";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /**
   * Delete a document.
   * @param {string} documentId
   */
  async function deleteDocument(documentId) {
    return _request("DELETE", `/documents/${encodeURIComponent(documentId)}`);
  }

  /**
   * Render a page as PNG.
   * @param {string} documentId
   * @param {number} pageNumber
   * @param {number} scale
   * @returns {Promise<string>} - Blob URL of the rendered page image
   */
  async function renderPage(documentId, pageNumber, scale) {
    const url = `/documents/${encodeURIComponent(documentId)}/pages/${pageNumber}.png?scale=${scale}`;
    const response = await _request("GET", url);
    if (!(response instanceof Response)) {
      throw new Error("Unexpected render response");
    }
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  }

  /**
   * Rotate selected pages.
   * @param {string} documentId
   * @param {number[]} pageNumbers - Zero-based page indices.
   * @param {number} rotation - 90, 180, or 270.
   * @returns {Promise<{document_id, page_count, message}>}
   */
  async function rotatePages(documentId, pageNumbers, rotation) {
    const response = await _request("POST", `/documents/${encodeURIComponent(documentId)}/pages/rotate`, {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_numbers: pageNumbers, rotation }),
    });
    return response;
  }

  /**
   * Delete selected pages.
   * @param {string} documentId
   * @param {number[]} pageNumbers - Zero-based page indices.
   * @returns {Promise<{document_id, page_count, message}>}
   */
  async function deletePages(documentId, pageNumbers) {
    const response = await _request("POST", `/documents/${encodeURIComponent(documentId)}/pages/delete`, {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_numbers: pageNumbers }),
    });
    return response;
  }

  /**
   * Reorder pages.
   * @param {string} documentId
   * @param {number[]} pageOrder - Complete list of zero-based original indices.
   * @returns {Promise<{document_id, page_count, message}>}
   */
  async function reorderPages(documentId, pageOrder) {
    const response = await _request("POST", `/documents/${encodeURIComponent(documentId)}/pages/reorder`, {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_order: pageOrder }),
    });
    return response;
  }

  return {
    uploadPDF,
    getDocument,
    downloadPDF,
    deleteDocument,
    renderPage,
    rotatePages,
    deletePages,
    reorderPages,
  };
})();
