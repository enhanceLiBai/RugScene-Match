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
    image.loading = 'lazy';
    image.src = item.image_url + '?preview=1';
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
  document.querySelectorAll('[data-scene-field]').forEach((select) => {
    select.value = payload.query_scene?.[select.dataset.sceneField] || '';
  });
  const labelText = (tags) => tags ? `空间：${tags.room} · 沙发：${tags.sofa_status === 'present' ? tags.sofa_color : tags.sofa_status} · 地板：${tags.floor_status === 'present' ? `${tags.floor_color} / ${tags.floor_material}` : tags.floor_status}` : '尚无场景标签';
  $('#queryScene').textContent = `客户场景识别：${labelText(payload.query_scene)}`;
  const deletedIds = new Set(JSON.parse(sessionStorage.getItem('deletedLibraryImageIds') || '[]'));
  const matches = (payload.results || []).filter((item) => !deletedIds.has(Number(item.buyer_image_id)));
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
      images.querySelector('.buyer-image').src = item.matched_buyer_image_url + '?preview=1';
      const productImage = images.querySelector('.product-image');
      if (item.product_image_url) productImage.src = item.product_image_url + '?preview=1';
      else {
        productImage.hidden = true;
        productImage.parentElement.querySelector('figcaption').textContent = '未提供商品主图';
      }
      images.querySelector('.buyer-download').href = item.matched_buyer_download_url || item.matched_buyer_image_url;
      const productDownload = images.querySelector('.product-download');
      if (productDownload) productDownload.href = item.product_download_url || item.product_image_url;
      images.querySelectorAll('img').forEach((image) => {
        image.onerror = () => { image.hidden = true; image.parentElement.querySelector('figcaption').textContent = `${image.alt}暂不可用`; };
      });
    } else fragment.querySelector('img').src = item.matched_buyer_image_url;
    fragment.querySelector('.score').textContent = `图片相似度分 ${item.similarity}`;
    fragment.querySelector('.match-reason').textContent = item.match_explanation || view.sourceLabel;
    fragment.querySelector('h4').textContent = `商品 ID：${view.productId}`;
    const copyId = document.createElement('button');
    copyId.textContent = '复制商品 ID';
    copyId.hidden = !item.product_id;
    copyId.onclick = async () => {
      try { await navigator.clipboard.writeText(view.productId); copyId.textContent = '已复制'; }
      catch { copyId.textContent = '复制失败，请手动复制上方 ID'; }
    };
    fragment.querySelector('.sku-line').replaceChildren(copyId);
    const copyImage = document.createElement('button');
    copyImage.type = 'button';
    copyImage.textContent = '复制图片';
    copyImage.onclick = async () => {
      try {
        const response = await fetch(item.matched_buyer_image_url);
        const blob = await response.blob();
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
        copyImage.textContent = '已复制';
        setTimeout(() => { copyImage.textContent = '复制图片'; }, 1400);
      } catch { copyImage.textContent = '复制失败'; }
    };
    fragment.querySelector('.sku-line').append(copyImage);
    const deleteButton = fragment.querySelector('.delete-image-button');
    deleteButton.onclick = async () => {
      if (!window.confirm('确定从图库删除这张图片吗？历史记录仍会保留，但图片将无法打开。')) return;
      deleteButton.disabled = true;
      try {
        await api.deleteLibraryImage(item.buyer_image_id);
        const deleted = new Set(JSON.parse(sessionStorage.getItem('deletedLibraryImageIds') || '[]'));
        deleted.add(Number(item.buyer_image_id));
        sessionStorage.setItem('deletedLibraryImageIds', JSON.stringify([...deleted]));
        card.remove();
        $('#matchHint').textContent = '图片已从图库删除；历史记录仍保留。';
      } catch (error) {
        deleteButton.disabled = false;
        $('#matchHint').textContent = error.message || '删除失败，请稍后重试。';
      }
    };
    deleteButton.hidden = !item.buyer_image_id;
    (view.chips || []).forEach((value) => {
      const chip = document.createElement('span');
      chip.textContent = value;
      chips.append(chip);
    });
    fragment.querySelector('.product-info').textContent = `买家秀场景：${labelText(item.scene_labels)}`;

    const words = `${item.product_id ? `商品 ID：${view.productId}，` : ''}这张买家秀与客户家居图相似，可作为搭配参考。`;
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
  $('#matchHint').textContent = payload.message || '通过场景属性筛选后，按图片相似度排序。';
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
  let historyCursor = null;
  const sceneOptions = {
    room: ['空间', ['客厅','卧室','玄关','餐厅','书房']],
    sofa_color: ['沙发颜色', ['黑色','白色','米色','浅灰色','深灰色','棕色','浅木色','深木色','蓝色','绿色','红色','黄色']],
    floor_color: ['地板颜色', ['黑色','白色','米色','浅灰色','深灰色','棕色','浅木色','深木色','蓝色','绿色','红色','黄色']],
    floor_material: ['地板材质', ['木纹','瓷砖/石材','水泥感']],
  };
  for (const [key, [title, values]] of Object.entries(sceneOptions)) {
    const label = document.createElement('label');
    label.textContent = title;
    const select = document.createElement('select');
    select.dataset.sceneField = key;
    for (const value of ['', ...values]) {
      const option = document.createElement('option');
      option.value = value; option.textContent = value || '待确认';
      select.append(option);
    }
    label.append(select); $('#sceneFields').append(label);
  }
  async function historyJson(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error('历史记录读取失败，请重试。');
    return response.json();
  }
  async function loadHistory(more = false) {
    const status = $('#historyStatus');
    $('#historyRefresh').disabled = $('#historyMore').disabled = true;
    status.textContent = '正在读取…';
    try {
      const data = await historyJson('/api/history' + (more && historyCursor ? `?before=${historyCursor}` : ''));
      if (!more) $('#historyList').replaceChildren();
      for (const item of data.items) {
        const button = document.createElement('button');
        button.className = 'history-record';
        const scene = item.query_scene;
        button.textContent = `${new Date(item.created_at).toLocaleString()} · ${item.result_count} 条结果 · ${scene ? [scene.room,scene.sofa_color,scene.floor_color,scene.floor_material].filter(Boolean).join(' / ') : '未识别场景'} · 查看`;
        if (item.query_image_url) {
          const thumbnail = document.createElement('img');
          thumbnail.src = item.query_image_url;
          thumbnail.alt = '客户照片';
          thumbnail.loading = 'lazy';
          button.prepend(thumbnail);
        } else {
          button.append(' · 未保存客户照片');
        }
        button.onclick = async () => {
          button.disabled = true;
          try {
            const detail = await historyJson(`/api/history/${item.id}`);
            document.querySelector('[data-view="match"]').click();
            queryFile = undefined;
            $('#useConfirmedScene').checked = false;
            $('#queryImage').value = '';
            clearPreview($('#queryPreview'), $('.dropzone-copy'));
            renderResults(detail.payload);
            const customerImage = $('#historyCustomerImage');
            customerImage.hidden = !detail.query_image_url;
            customerImage.removeAttribute('src');
            if (detail.query_image_url) customerImage.src = detail.query_image_url;
            customerImage.onerror = () => {
              customerImage.hidden = true;
              $('#historyViewing').textContent += ' 客户照片加载失败，请重新打开记录。';
            };
            $('#historyViewing').hidden = false;
            $('#historyViewing').textContent = `正在查看 ${new Date(detail.created_at).toLocaleString()} 的历史结果${detail.query_image_url ? '，下方为当时的客户照片。' : '（旧记录未保存客户照片）。'}`;
          } catch (error) { status.textContent = error.message; }
          finally { button.disabled = false; }
        };
        $('#historyList').append(button);
      }
      historyCursor = data.next_before;
      $('#historyMore').hidden = !historyCursor;
      status.textContent = $('#historyList').children.length ? '' : '暂无记录，完成一次检索后会自动保存。';
    } catch (error) { status.textContent = error.message; }
    finally { $('#historyRefresh').disabled = $('#historyMore').disabled = false; }
  }
  $('#historyRefresh').onclick = () => loadHistory();
  $('#historyMore').onclick = () => loadHistory(true);
  document.querySelector('[data-view="history"]').addEventListener('click', () => loadHistory());
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
    $('#useConfirmedScene').checked = false;
    document.querySelectorAll('[data-scene-field]').forEach((select) => { select.value = ''; });
    $('#historyCustomerImage').hidden = true;
    $('#historyViewing').hidden = true;
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
    let confirmed = null;
    if ($('#useConfirmedScene').checked) {
      confirmed = {sofa_status: 'present', floor_status: 'present'};
      document.querySelectorAll('[data-scene-field]').forEach((select) => { confirmed[select.dataset.sceneField] = select.value; });
      if (Object.keys(sceneOptions).some((key) => !confirmed[key])) {
        $('#matchHint').textContent = '请先确认全部四项场景属性。';
        $('#sceneConfirmation').open = true;
        return;
      }
    }
    $('#historyViewing').hidden = true;
    $('#historyCustomerImage').hidden = true;
    const input = $('#queryImage');
    const requestedFile = queryFile;
    setBusy(button, true, '匹配中…');
    input.disabled = true;
    $('#results').hidden = true;
    $('#matchHint').textContent = '正在识别场景并检索；高相似度但标签冲突的候选会进行双图复核，请稍候…';
    try {
      const payload = await api.searchSimilar(requestedFile, Number($('#topK').value), confirmed);
      renderResults(payload);
      if (!payload.results?.length) $('#sceneConfirmation').open = true;
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
    showEntryStatus('正在上传图片、生成向量并识别场景标签，请稍候…');
    try {
      const response = await api.uploadLibraryImage(file, readEntryMetadata());
      form.reset();
      clearPreview($('#entryPreview'), $('#entryImageText'));
      const tags = response.scene_labels;
      showEntryStatus((response.message || '图片已保存并加入图库。') + (tags ? ` 空间：${tags.room}；沙发：${tags.sofa_color}；地板：${tags.floor_color} / ${tags.floor_material}` : ''));
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
