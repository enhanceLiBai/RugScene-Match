(function exposeCarpetApiClient(root, factory) {
  const api = factory(root);
  // 同时保留直接导出和命名空间导出，方便页面与 Node 测试共用同一入口。
  api.CarpetApiClient = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.CarpetApiClient = api;
})(typeof globalThis !== 'undefined' ? globalThis : window, (root) => {
  const GENERIC_ERROR = '服务响应异常，请稍后重试。';

  class ApiError extends Error {
    constructor(message) {
      super(message);
      this.name = 'ApiError';
    }
  }

  async function requestJson(fetchImpl, url, options) {
    const response = await fetchImpl(url, options);
    const contentType = response.headers?.get('content-type') || '';
    const isJson = contentType.includes('application/json');
    let payload = null;

    if (isJson) {
      try {
        payload = await response.json();
      } catch (_error) {
        payload = null;
      }
    }

    if (!response.ok) throw new ApiError(payload?.detail || GENERIC_ERROR);
    if (!isJson) throw new ApiError(GENERIC_ERROR);
    return payload;
  }

  function isNonEmpty(value) {
    return value !== undefined && value !== null
      && (typeof value !== 'string' || value.trim() !== '');
  }

  function create({ fetchImpl, FormDataImpl } = {}) {
    const fetcher = fetchImpl || (typeof root.fetch === 'function' ? root.fetch.bind(root) : null);
    const FormDataClass = FormDataImpl || root.FormData;
    if (!fetcher) throw new Error('缺少 fetch 实现。');
    if (!FormDataClass) throw new Error('缺少 FormData 实现。');

    async function listLibrary() {
      return requestJson(fetcher, '/api/library', { method: 'GET' });
    }

    async function uploadLibraryImage(file, metadata = {}) {
      const body = new FormDataClass();
      body.append('image', file);
      Object.entries(metadata).forEach(([key, value]) => {
        if (isNonEmpty(value)) body.append(key, value);
      });
      return requestJson(fetcher, '/api/library', { method: 'POST', body });
    }

    async function searchSimilar(file, topK = 10) {
      const body = new FormDataClass();
      body.append('image', file);
      return requestJson(fetcher, `/api/search?top_k=${encodeURIComponent(topK)}`, {
        method: 'POST',
        body,
      });
    }

    function uploadWorkbook(file, onProgress) {
      return new Promise((resolve, reject) => {
        const xhr = new root.XMLHttpRequest();
        xhr.open('POST', '/api/imports');
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100));
        };
        xhr.onerror = () => reject(new ApiError('上传失败，请检查网络后重试。'));
        xhr.onload = () => {
          try {
            const payload = JSON.parse(xhr.responseText);
            if (xhr.status < 200 || xhr.status >= 300) throw new ApiError(payload.detail || GENERIC_ERROR);
            resolve(payload);
          } catch (error) { reject(error); }
        };
        const body = new FormDataClass();
        body.append('workbook', file);
        xhr.send(body);
      });
    }
    const importStatus = (jobId) => requestJson(fetcher, `/api/imports/${encodeURIComponent(jobId)}`, { method: 'GET' });
    return { listLibrary, uploadLibraryImage, searchSimilar, uploadWorkbook, importStatus };
  }

  return { ApiError, requestJson, create };
});
