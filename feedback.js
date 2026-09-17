const feedbackQuery = (selector) => document.querySelector(selector);
const feedbackJson = (url) => CarpetApiClient.requestJson(fetch, url, {method: 'GET'});
let feedbackCursor = null;
let feedbackLoading = false;

function feedbackNode(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function feedbackPhoto(url, label, className) {
  const figure = feedbackNode('figure');
  const caption = feedbackNode('figcaption', url ? label : `${label}未保存`);
  if (url) {
    const image = feedbackNode('img');
    image.src = url;
    image.alt = label;
    image.loading = 'lazy';
    if (className) image.className = className;
    image.onerror = () => { image.hidden = true; caption.textContent = `${label}暂不可用（图片可能已删除）`; };
    figure.append(image);
  }
  figure.append(caption);
  return figure;
}

function feedbackScene(tags) {
  if (!tags) return '未保存场景标签';
  return `空间：${tags.room || '未知'} · 沙发：${tags.sofa_status === 'present' ? tags.sofa_color || '未知' : tags.sofa_status || '未知'} · 地板：${tags.floor_status === 'present' ? [tags.floor_color, tags.floor_material].filter(Boolean).join(' / ') : tags.floor_status || '未知'}`;
}

function historyCopyActions(item, image) {
  const actions = feedbackNode('div', undefined, 'feedback-toolbar');
  if (item.product_id) {
    const button = feedbackNode('button', '复制商品 ID', 'ghost');
    button.type = 'button';
    button.onclick = async () => {
      try {
        const text = String(item.product_id);
        if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
        else {
          const input = document.createElement('textarea');
          input.value = text;
          input.style.cssText = 'position:fixed;left:-9999px;top:0';
          document.body.append(input);
          try {
            input.select();
            if (!document.execCommand('copy')) throw new Error('复制失败');
          } finally { input.remove(); button.focus(); }
        }
        button.textContent = '已复制';
      } catch { button.textContent = '复制失败，请手动复制上方 ID'; }
    };
    actions.append(button);
  }
  if (image) {
    const button = feedbackNode('button', '复制图片', 'ghost');
    button.type = 'button';
    button.onclick = async () => {
      if (button.disabled) return;
      if (!window.isSecureContext || !navigator.clipboard?.write || !window.ClipboardItem) {
        button.textContent = '请右键买家秀图片选择复制';
        return;
      }
      button.disabled = true;
      button.textContent = '正在复制…';
      try {
        // 与客服页面一致，点击时立即写入剪贴板，异步准备 PNG。
        const png = (async () => {
          await image.decode();
          const canvas = document.createElement('canvas');
          canvas.width = image.naturalWidth;
          canvas.height = image.naturalHeight;
          canvas.getContext('2d').drawImage(image, 0, 0);
          return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('图片转换失败')), 'image/png'));
        })();
        await navigator.clipboard.write([new window.ClipboardItem({'image/png': png})]);
        button.textContent = '已复制';
      } catch { button.textContent = '复制失败，请右键买家秀图片复制'; }
      finally { button.disabled = false; }
    };
    actions.append(button);
  }
  return actions;
}

function historyDeleteAction(item, card) {
  if (!item.buyer_image_id) return null;
  const button = feedbackNode('button', '从图库删除买家秀', 'ghost danger');
  button.type = 'button';
  button.onclick = async () => {
    if (button.disabled) return;
    if (!window.confirm('确定删除这张不合格买家秀吗？删除后将从图库和后续匹配中移除，历史记录仍保留。')) return;
    button.disabled = true;
    button.textContent = '正在删除…';
    try {
      await CarpetApiClient.requestJson(fetch, `/api/library/${encodeURIComponent(item.buyer_image_id)}`, {method: 'DELETE'});
      card.replaceChildren(feedbackNode('p', '已从图库删除，历史记录仍保留。', 'status-message'));
    } catch (error) {
      button.disabled = false;
      button.textContent = '从图库删除买家秀';
      window.alert(error.message || '删除失败，请重试。');
    }
  };
  return button;
}

function renderFeedbackHistory(container, detail) {
  container.replaceChildren();
  container.append(feedbackNode('p', detail.user ? `查询客服：${detail.user.display_name}（${detail.user.username}）` : '旧记录，未关联客服', 'feedback-meta'));
  container.append(feedbackNode('p', `匹配时间：${new Date(detail.created_at).toLocaleString()}`, 'feedback-meta'));
  container.append(feedbackNode('h4', '客户照片'));
  container.append(feedbackPhoto(detail.query_image_url, '本次匹配的客户照片', 'feedback-customer'));
  container.append(feedbackNode('p', feedbackScene(detail.payload.query_scene), 'feedback-scene'));
  if (detail.payload.message) container.append(feedbackNode('p', detail.payload.message));
  container.append(feedbackNode('h4', '当时的推荐结果'));
  const grid = feedbackNode('div', undefined, 'feedback-results');
  for (const item of detail.payload.results || []) {
    const card = feedbackNode('article', undefined, 'feedback-result');
    card.append(feedbackNode('h4', `Top ${item.rank} · 商品 ID：${item.product_id || '未填写'}`));
    if (item.style?.trim()) card.append(feedbackNode('p', `款式：${item.style.trim()}`, 'product-info'));
    card.append(feedbackNode('p', `图片相似度分：${item.similarity}`));
    const buyerPhoto = feedbackPhoto(item.matched_buyer_image_url ? `${item.matched_buyer_image_url}?preview=1` : null, '相似买家秀');
    const comparison = feedbackNode('div', undefined, 'result-images');
    comparison.append(feedbackPhoto(detail.query_image_url, '客户照片'), buyerPhoto);
    card.append(comparison);
    card.append(feedbackNode('p', feedbackScene(item.scene_labels), 'feedback-scene'));
    if (item.match_explanation) card.append(feedbackNode('p', item.match_explanation));
    const toolbar = historyCopyActions(item, item.matched_buyer_image_url ? buyerPhoto.children[0] : null);
    const deleteButton = historyDeleteAction(item, card);
    if (deleteButton) toolbar.append(deleteButton);
    card.append(toolbar);
    grid.append(card);
  }
  container.append(grid);
  if (!detail.payload.results?.length) container.append(feedbackNode('p', '当次匹配没有推荐结果。'));
}

function feedbackEntry(item) {
  const entry = feedbackNode('article', undefined, 'feedback-entry');
  entry.append(feedbackNode('h3', `下单成功 · Top ${item.rank}`, 'feedback-verdict')); 
  entry.append(feedbackNode('p', `登记时间：${new Date(item.created_at).toLocaleString()} · 匹配记录 #${item.history_id}`, 'feedback-meta'));
  entry.append(feedbackNode('p', `商品 ID：${item.product_id || '未填写'}`, 'feedback-reason'));
  entry.append(feedbackNode('p', `匹配时间：${new Date(item.matched_at).toLocaleString()}`, 'feedback-meta'));
  entry.append(feedbackNode('p', item.user ? `成交客服：${item.user.display_name}（${item.user.username}）` : '未关联客服', 'feedback-meta'));
  const details = feedbackNode('details');
  details.append(feedbackNode('summary', '查看客户照片与本次匹配结果'));
  const content = feedbackNode('div');
  details.append(content);
  let loaded = false;
  let loading = false;
  async function loadDetail() {
    if (loaded || loading) return;
    loading = true;
    content.replaceChildren(feedbackNode('p', '正在读取匹配记录…'));
    try {
      renderFeedbackHistory(content, await feedbackJson(`/api/history/${item.history_id}`));
      loaded = true;
    } catch (error) {
      const retry = feedbackNode('button', '重试', 'ghost');
      retry.type = 'button';
      retry.onclick = loadDetail;
      content.replaceChildren(feedbackNode('p', error.message || '读取失败，请重试。', 'status-message error'), retry);
    } finally { loading = false; }
  }
  details.ontoggle = () => { if (details.open) loadDetail(); };
  entry.append(details);
  return entry;
}

async function loadFeedback(more = false) {
  if (feedbackLoading) return;
  feedbackLoading = true;
  const status = feedbackQuery('#adminFeedbackStatus');
  const refresh = feedbackQuery('#refreshFeedback');
  const moreButton = feedbackQuery('#moreFeedback');
  const list = feedbackQuery('#feedbackList');
  refresh.disabled = moreButton.disabled = true;
  status.className = 'status-message';
  status.textContent = '正在读取下单记录…';
  if (!more) {
    list.replaceChildren();
    feedbackCursor = null;
    moreButton.hidden = true;
  }
  try {
    const params = new URLSearchParams();
    if (more && feedbackCursor) params.set('before', feedbackCursor);
    const data = await feedbackJson(`/api/conversions?${params}`);
    feedbackQuery('#conversionSummary').textContent = `查询 ${data.total_matches} 次 · 下单成功 ${data.converted_matches} 次 · 转化率 ${data.conversion_rate}%`;
    for (const item of data.items) list.append(feedbackEntry(item));
    feedbackCursor = data.next_before;
    moreButton.hidden = !feedbackCursor;
    status.textContent = list.children.length ? '' : '暂无下单成功记录。';
  } catch (error) {
    status.className = 'status-message error';
    status.textContent = error.message || '读取失败，请刷新重试。';
  } finally {
    feedbackLoading = false;
    refresh.disabled = moreButton.disabled = false;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  feedbackQuery('#refreshFeedback').onclick = () => loadFeedback();
  feedbackQuery('#moreFeedback').onclick = () => loadFeedback(true);
  loadFeedback();
});
