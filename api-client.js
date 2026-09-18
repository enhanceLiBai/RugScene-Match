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

    if (response.status === 401 && root.location) {
      root.location.replace(['/admin', '/feedback'].includes(root.location.pathname) ? '/admin/login' : '/login');
    }
    if (!isJson && [502, 503, 504, 520, 521, 522, 523, 524, 530].includes(response.status)) {
      throw new ApiError(`访问链路或网关暂不可用（HTTP ${response.status}），请稍后重试；若刚才已提交匹配，可先查看历史记录。`);
    }
    if (!response.ok) throw new ApiError(typeof payload?.detail === 'string' ? payload.detail : GENERIC_ERROR);
    if (!isJson) throw new ApiError(GENERIC_ERROR);
    return payload;
  }

  function isNonEmpty(value) {
    return value !== undefined && value !== null
      && (typeof value !== 'string' || value.trim() !== '');
  }

  function create({ fetchImpl, FormDataImpl, searchTimeoutMs = 180000 } = {}) {
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

    async function searchSimilar(file, topK = 10, confirmedScene = null) {
      const body = new FormDataClass();
      body.append('image', file);
      if (confirmedScene) body.append('confirmed_scene', JSON.stringify(confirmedScene));
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), searchTimeoutMs);
      try {
        return await requestJson(fetcher, `/api/search?top_k=${encodeURIComponent(topK)}`, {
          method: 'POST', body, signal: controller.signal,
        });
      } catch (error) {
        if (controller.signal.aborted) throw new ApiError('检索请求超时，请检查网络后重试；本次后台处理可能仍在继续，可先查看历史记录。');
        throw error;
      } finally {
        clearTimeout(timer);
      }
    }

    async function deleteLibraryImage(imageId) {
      return requestJson(fetcher, `/api/library/${encodeURIComponent(imageId)}`, { method: 'DELETE' });
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
    const submitFeedback = (feedback) => requestJson(fetcher, '/api/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(feedback),
    });
    return { listLibrary, uploadLibraryImage, searchSimilar, deleteLibraryImage, uploadWorkbook, importStatus, submitFeedback };
  }

  return { ApiError, requestJson, create };
});
