let conversionVersion = 0;
let myHistoryCursor = null;
let myHistoryBusy = false;
let myHistoryOpening = false;
const orderNode = id => document.querySelector(id);
const orderJson = (url, options = {method: 'GET'}) => CarpetApiClient.requestJson(fetch, url, options);

function renderConversionForm(payload) {
  const version = ++conversionVersion;
  const form = orderNode('#conversionForm');
  const fields = orderNode('#conversionFields');
  const rank = orderNode('#conversionRank');
  const product = orderNode('#conversionProduct');
  const button = orderNode('#conversionSubmit');
  const status = orderNode('#conversionStatus');
  form.reset();
  rank.replaceChildren();
  const placeholder = document.createElement('option');
  placeholder.value = ''; placeholder.textContent = '请选择本次 Top 排名'; rank.append(placeholder);
  for (const item of payload.results || []) {
    const option = document.createElement('option');
    option.value = String(item.rank); option.textContent = `Top ${item.rank}`; rank.append(option);
  }
  rank.onchange = () => {
    const item = (payload.results || []).find(item => item.rank === Number(rank.value));
    product.value = item ? item.product_id || '未填写' : '';
  };
  function showSaved(conversion) {
    rank.value = String(conversion.rank);
    product.value = conversion.product_id || '未填写';
    fields.disabled = true;
    button.textContent = '已登记';
    status.hidden = false;
    status.textContent = `已登记 Top ${conversion.rank} 下单成功，本次匹配只计一次转化。`;
  }
  button.textContent = '登记下单成功';
  fields.disabled = !payload.history_id;
  status.hidden = Boolean(payload.history_id);
  status.textContent = payload.history_id ? '' : '本次查询记录未保存，暂不能登记，请重新匹配。';
  if (payload.conversion) showSaved(payload.conversion);
  form.onsubmit = async event => {
    event.preventDefault();
    if (fields.disabled) return;
    if (!rank.value) { status.hidden = false; status.textContent = '请选择本次 Top 排名。'; return; }
    fields.disabled = true; button.textContent = '正在登记…'; status.hidden = true;
    try {
      const data = await orderJson('/api/conversions', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({history_id: payload.history_id, rank: Number(rank.value)})});
      if (version !== conversionVersion) return;
      showSaved(data.conversion);
    } catch (error) {
      if (version !== conversionVersion) return;
      fields.disabled = false; button.textContent = '登记下单成功'; status.hidden = false;
      status.textContent = error.message || '登记失败，请重试。';
    }
  };
}

async function loadMyHistory(more = false) {
  if (myHistoryBusy) return;
  myHistoryBusy = true;
  const list = orderNode('#myHistoryList');
  const status = orderNode('#myHistoryStatus');
  const refresh = orderNode('#myHistoryRefresh');
  const moreButton = orderNode('#myHistoryMore');
  refresh.disabled = moreButton.disabled = true;
  status.textContent = '正在读取我的查询记录…';
  try {
    const data = await orderJson('/api/my-history' + (more && myHistoryCursor ? `?before=${myHistoryCursor}` : ''));
    if (!more) list.replaceChildren();
    for (const item of data.items) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'history-record';
      button.textContent = `${new Date(item.created_at).toLocaleString()} · ${item.result_count} 条推荐 · ${item.conversion ? `已登记 Top ${item.conversion.rank}` : '查看 / 补登记下单'}`;
      if (item.query_image_url) {
        const image = document.createElement('img'); image.src = item.query_image_url; image.alt = '客户照片'; image.loading = 'lazy';
        image.onerror = () => { image.hidden = true; }; button.prepend(image);
      }
      button.onclick = async () => {
        if (myHistoryOpening || orderNode('#matchButton').disabled) return;
        myHistoryOpening = true; button.disabled = true;
        orderNode('#matchButton').disabled = true;
        orderNode('#queryImage').disabled = true;
        try {
          const detail = await orderJson(`/api/my-history/${item.id}`);
          queryFile = undefined;
          orderNode('#queryImage').value = '';
          clearPreview(orderNode('#queryPreview'), orderNode('.dropzone-copy'));
          orderNode('#useConfirmedScene').checked = false;
          renderResults({...detail.payload, history_id: detail.id, conversion: detail.conversion}, null, detail.query_image_url);
          const viewing = orderNode('#viewingMyHistory');
          viewing.hidden = false;
          viewing.textContent = `正在查看 ${new Date(detail.created_at).toLocaleString()} 的查询记录 #${detail.id}`;
          orderNode('#myHistory').open = false;
          viewing.scrollIntoView({behavior: 'smooth', block: 'start'});
        } catch (error) { status.textContent = error.message || '记录读取失败，请重试。'; }
        finally {
          button.disabled = false; myHistoryOpening = false;
          orderNode('#matchButton').disabled = false; orderNode('#queryImage').disabled = false;
        }
      };
      list.append(button);
    }
    myHistoryCursor = data.next_before; moreButton.hidden = !myHistoryCursor;
    status.textContent = list.children.length ? '' : '暂无个人查询记录。';
  } catch (error) { status.textContent = error.message || '读取失败，请刷新重试。'; }
  finally { myHistoryBusy = false; refresh.disabled = moreButton.disabled = false; }
}

document.addEventListener('DOMContentLoaded', () => {
  orderNode('#myHistory').ontoggle = () => { if (orderNode('#myHistory').open) loadMyHistory(); };
  orderNode('#myHistoryRefresh').onclick = () => loadMyHistory();
  orderNode('#myHistoryMore').onclick = () => loadMyHistory(true);
  orderNode('#queryImage').addEventListener('change', () => { orderNode('#viewingMyHistory').hidden = true; });
});
