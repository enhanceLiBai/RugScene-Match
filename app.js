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
    const view = CarpetMatcherCore.buildPresentation(item);
    const card = fragment.querySelector('.result-card');
    const chips = fragment.querySelector('.chips');

    fragment.querySelector('img').src = item.image_url;
    fragment.querySelector('.score').textContent = `匹配度 ${item.similarity}%`;
    fragment.querySelector('.match-reason').textContent = view.matchReason;
    fragment.querySelector('h4').textContent = view.productName;
    fragment.querySelector('.sku-line').textContent = `SKU：${view.sku}`;
    view.chips.forEach((value) => {
      const chip = document.createElement('span');
      chip.textContent = value;
      chips.append(chip);
    });
    fragment.querySelector('.product-info').textContent = view.productInfo;

    const words = CarpetMatcherCore.buildRecommendationScript(item);
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
  $('#matchHint').textContent = '结果按 OpenCLIP 图片向量相似度排序。';
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
      renderResults(await api.searchSimilar(requestedFile, 5));
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
});
