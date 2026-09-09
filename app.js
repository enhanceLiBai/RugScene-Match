const api = CarpetApiClient.create();
let queryFile;
let latestLibraryRequest = 0;
let hasLoadedLibrary = false;
const previewUrls = new WeakMap();
const $ = (selector) => document.querySelector(selector);

function statusClass(kind) {
  return kind === 'error' ? 'status-message error' : 'status-message';
}

function setStatus(element, message, kind) {
  element.textContent = message;
  element.className = statusClass(kind);
  element.hidden = !message;
}

/** 从后端刷新图库；失败时保留可见重试入口。 */
async function refreshLibrary() {
  const requestId = ++latestLibraryRequest;
  const button = $('#reloadLibraryButton');
  setBusy(button, true, '刷新中…');
  setStatus($('#libraryStatus'), '正在读取图库…');
  try {
    const payload = await api.listLibrary();
    if (requestId !== latestLibraryRequest) return;
    renderLibrary(payload.images || []);
    hasLoadedLibrary = true;
    setStatus($('#libraryStatus'), '');
  } catch (error) {
    if (requestId !== latestLibraryRequest) return;
    if (!hasLoadedLibrary) $('#libraryCount').textContent = '—';
    setStatus($('#libraryStatus'), error.message || '图库加载失败，请稍后重试。', 'error');
  } finally {
    if (requestId === latestLibraryRequest) setBusy(button, false, '刷新中…');
  }
}

function renderLibrary(images) {
  const grid = $('#libraryGrid');
  grid.replaceChildren();
  $('#libraryCount').textContent = String(images.length);

  if (!images.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = '还没有买家秀。请先录入真实图片，商品信息可以稍后补充。';
    grid.append(empty);
    return;
  }

  images.forEach((item) => {
    const view = CarpetMatcherCore.buildPresentation(item);
    const entry = document.createElement('div');
    const image = document.createElement('img');
    const details = document.createElement('div');
    const name = document.createElement('strong');
    const sku = document.createElement('small');
    const chips = document.createElement('small');

    entry.className = 'library-item';
    image.src = item.image_url;
    image.alt = view.productName;
    name.textContent = view.productName;
    sku.textContent = `SKU：${view.sku}`;
    chips.textContent = view.chips.join(' · ') || '元数据未填写';
    details.append(name, sku, chips);
    entry.append(image, details);
    grid.append(entry);
  });
}

function renderResults(payload) {
  const labelText = (tags) => tags ? `空间：${tags.room} · 沙发：${tags.sofa_status === 'present' ? tags.sofa_color : tags.sofa_status} · 地板：${tags.floor_status === 'present' ? `${tags.floor_color} / ${tags.floor_material}` : tags.floor_status}` : '尚无场景标签';
  $('#queryScene').textContent = `客户场景识别：${labelText(payload.query_scene)}`;
  const matches = payload.results || [];
  const grid = $('#resultGrid');
  grid.replaceChildren();

  if (!matches.length) {
    $('#results').hidden = true;
    $('#matchHint').textContent = payload.message || '没有找到可用的相似买家秀。';
    return;
  }

  matches.forEach((item) => {
    const fragment = $('#resultTemplate').content.cloneNode(true);
    const view = CarpetMatcherCore.buildApiPresentation(item);
    const card = fragment.querySelector('.result-card');
    const chips = fragment.querySelector('.chips');

    const images = fragment.querySelector('.result-images');
    if (images) {
      images.querySelector('.buyer-image').src = item.matched_buyer_image_url;
      images.querySelector('.product-image').src = item.product_image_url;
      images.querySelector('.buyer-download').href = item.matched_buyer_download_url || item.matched_buyer_image_url;
      images.querySelector('.product-download').href = item.product_download_url || item.product_image_url;
      images.querySelectorAll('img').forEach((image) => {
        image.onerror = () => { image.hidden = true; image.parentElement.querySelector('figcaption').textContent = `${image.alt}暂不可用`; };
      });
    } else fragment.querySelector('img').src = item.matched_buyer_image_url;
    fragment.querySelector('.score').textContent = `搭配参考分 ${item.similarity}`;
    fragment.querySelector('.match-reason').textContent = view.sourceLabel;
    fragment.querySelector('h4').textContent = `商品 ID：${view.productId}`;
    const copyId = document.createElement('button');
    copyId.textContent = '复制商品 ID';
    copyId.onclick = async () => {
      try { await navigator.clipboard.writeText(view.productId); copyId.textContent = '已复制'; }
      catch { copyId.textContent = '复制失败，请手动复制上方 ID'; }
    };
    fragment.querySelector('.sku-line').replaceChildren(copyId);
    (view.chips || []).forEach((value) => {
      const chip = document.createElement('span');
      chip.textContent = value;
      chips.append(chip);
    });
    fragment.querySelector('.product-info').textContent = `买家秀场景：${labelText(item.scene_labels)}`;

    const words = `商品 ID：${view.productId}，这张买家秀与客户家居图相似，可作为搭配参考。`;
    fragment.querySelector('blockquote').textContent = words;
    fragment.querySelector('.copy-button').onclick = async (event) => {
      await navigator.clipboard.writeText(words);
      event.currentTarget.textContent = '已复制';
      setTimeout(() => { event.currentTarget.textContent = '复制话术'; }, 1400);
    };
    fragment.querySelectorAll('[data-feedback]').forEach((button) => {
      button.onclick = () => {
        const message = document.createElement('span');
        message.textContent = '反馈已记录，后续会用于优化排序。';
        button.parentElement.replaceChildren(message);
      };
    });
    grid.append(card);
  });

  $('#resultCount').textContent = `展示 Top ${matches.length}`;
  $('#results').hidden = false;
  $('#matchHint').textContent = payload.message || '按场景属性与图片相似度综合排序；缺失标签的属性使用图片相似度作为参考。';
}

function readEntryMetadata() {
  return {
    sku: $('#sku').value.trim(),
    product_name: $('#productName').value.trim(),
    size: $('#size').value.trim(),
    price: $('#price').value.trim(),
    room: $('#room').value,
    style: $('#style').value,
    color: $('#color').value.trim(),
    stock: $('#stock').value,
    selling_point: $('#sellingPoint').value.trim(),
  };
}

function setBusy(button, busy, busyText) {
  if (!button.dataset.idleText) button.dataset.idleText = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? busyText : button.dataset.idleText;
}

function showEntryStatus(message, kind) {
  setStatus($('#entryStatus'), message, kind);
}

function revokePreview(image) {
  const url = previewUrls.get(image);
  if (!url) return;
  URL.revokeObjectURL(url);
  previewUrls.delete(image);
}

function clearPreview(image, copy) {
  revokePreview(image);
  image.hidden = true;
  if (copy) copy.hidden = false;
}

function preview(input, image, copy) {
  const file = input.files[0];
  if (!file) return;
  revokePreview(image);
  const url = URL.createObjectURL(file);
  previewUrls.set(image, url);
  image.src = url;
  image.hidden = false;
  if (copy) copy.hidden = true;
}

function setEntryFormBusy(form, busy) {
  Array.from(form.elements).forEach((control) => {
    if (busy) {
      control.dataset.entryWasDisabled = String(control.disabled);
      control.disabled = true;
      return;
    }
    control.disabled = control.dataset.entryWasDisabled === 'true';
    delete control.dataset.entryWasDisabled;
  });
}

document.addEventListener('DOMContentLoaded', () => {
  $('#labelExisting').onclick = async () => {
    const button = $('#labelExisting'); button.disabled = true;
    const output = $('#labelStatus'); output.textContent = '正在补充场景标签…';
    try {
      const response = await fetch('/api/scene-labels/backfill', {method:'POST'});
      if (!response.ok) throw new Error();
      const {job_id} = await response.json();
      let state;
      do {
        state = await api.importStatus(job_id);
        output.textContent = `已处理 ${state.processed}/${state.total}，失败 ${state.summary?.skipped || 0}`;
        if (!['completed','failed'].includes(state.status)) await new Promise(resolve=>setTimeout(resolve,1000));
      } while (!['completed','failed'].includes(state.status));
      output.textContent += state.status === 'completed' ? '，处理结束。可再次补充失败项。' : '，任务失败。';
    } catch { output.textContent = '无法查询补标任务，请稍后重试。'; }
    finally { button.disabled = false; }
  };
  refreshLibrary();

  document.querySelectorAll('.tab').forEach((button) => {
    button.onclick = () => {
      document.querySelectorAll('.tab,.view').forEach((element) => element.classList.remove('active'));
      button.classList.add('active');
      $(`#${button.dataset.view}`).classList.add('active');
    };
  });

  $('#queryImage').onchange = (event) => {
    queryFile = event.target.files[0];
    preview(event.target, $('#queryPreview'), $('.dropzone-copy'));
  };
  $('#entryImage').onchange = (event) => preview(event.target, $('#entryPreview'), $('#entryImageText'));
  $('#reloadLibraryButton').onclick = refreshLibrary;
  window.addEventListener('beforeunload', () => {
    revokePreview($('#queryPreview'));
    revokePreview($('#entryPreview'));
  });

  $('#matchButton').onclick = async () => {
    if (!queryFile) {
      $('#matchHint').textContent = '请先上传客户家的照片。';
      return;
    }

    const button = $('#matchButton');
    const input = $('#queryImage');
    const requestedFile = queryFile;
    setBusy(button, true, '匹配中…');
    input.disabled = true;
    $('#results').hidden = true;
    $('#matchHint').textContent = '正在计算 OpenCLIP 图片向量相似度…';
    try {
      renderResults(await api.searchSimilar(requestedFile, 10));
    } catch (error) {
      $('#results').hidden = true;
      $('#matchHint').textContent = error.message || '匹配失败，请稍后重试。';
    } finally {
      input.disabled = false;
      setBusy(button, false, '匹配中…');
    }
  };

  $('#entryForm').onsubmit = async (event) => {
    event.preventDefault();
    const file = $('#entryImage').files[0];
    if (!file) {
      showEntryStatus('请先选择买家秀图片。', 'error');
      return;
    }

    const button = $('#entrySubmitButton');
    const form = event.target;
    setEntryFormBusy(form, true);
    setBusy(button, true, '保存中…');
    showEntryStatus('正在上传图片并生成向量…');
    try {
      const response = await api.uploadLibraryImage(file, readEntryMetadata());
      form.reset();
      clearPreview($('#entryPreview'), $('#entryImageText'));
      showEntryStatus(response.status === 'duplicate' ? '图库已有这张图片，商品信息已补充。' : '图片已保存并加入图库。');
      await refreshLibrary();
    } catch (error) {
      showEntryStatus(error.message || '图片入库失败，请稍后重试。', 'error');
    } finally {
      setBusy(button, false, '保存中…');
      setEntryFormBusy(form, false);
    }
  };

  let importJobId = sessionStorage.getItem('importJobId');
  let polling = false;
  const importBusy = (busy) => {
    $('#excelButton').disabled = busy;
    $('#excelFile').disabled = busy;
    $('#excelResume').hidden = busy || !importJobId;
  };
  async function pollImport() {
    if (polling || !importJobId) return;
    polling = true;
    importBusy(true);
    try {
      let status;
      do {
        status = await api.importStatus(importJobId);
        const stages = { parsing: '解析工作簿', importing: '提取图片并建立检索索引', completed: '导入完成', failed: '导入失败' };
        $('#excelStatus').textContent = `${stages[status.status] || '处理中'}，已处理 ${status.processed} 张图片`;
        const summary = status.summary || {};
        $('#excelSummary').textContent = `新增 ${summary.imported || 0} 张，复用 ${summary.reused || 0} 张，跳过 ${summary.skipped || 0} 张。`;
        (summary.errors || []).forEach((error) => {
          const line = document.createElement('p');
          line.textContent = `商品 ${error.product_id}，${error.source_column} 列：${error.message}`;
          $('#excelSummary').append(line);
        });
        if (!['completed', 'failed'].includes(status.status)) await new Promise(resolve => setTimeout(resolve, 1000));
      } while (!['completed', 'failed'].includes(status.status));
      $('#excelStatus').textContent = status.error || '导入完成，可以开始匹配。';
      importJobId = null;
      sessionStorage.removeItem('importJobId');
      await refreshLibrary();
    } catch { $('#excelStatus').textContent = '暂时无法查询进度，可点击“继续查询进度”。'; }
    finally { polling = false; importBusy(false); }
  }
  $('#excelResume').onclick = pollImport;
  if (importJobId) pollImport();
  $('#excelForm').onsubmit = async (event) => {
    event.preventDefault();
    const file = $('#excelFile').files[0];
    if (!file) return;
    importBusy(true);
    $('#excelProgress').hidden = false;
    $('#excelStatus').textContent = '正在上传 Excel…';
    try {
      const { job_id } = await api.uploadWorkbook(file, (value) => { $('#excelProgress').value = value; });
      importJobId = job_id;
      sessionStorage.setItem('importJobId', job_id);
      await pollImport();
    } catch (error) { $('#excelStatus').textContent = error.message || '导入失败'; }
    finally { importBusy(false); }
  };
});
