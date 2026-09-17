let adminHistoryCursor = null;
let adminHistoryLoading = false;
let adminHistoryLoaded = false;
let adminHistoryDetailRequest = 0;

async function loadAdminHistory(more = false) {
  if (adminHistoryLoading) return;
  adminHistoryLoading = true;
  const status = document.querySelector('#historyStatus');
  const refresh = document.querySelector('#historyRefresh');
  const moreButton = document.querySelector('#historyMore');
  const list = document.querySelector('#historyList');
  const period = document.querySelector('#historyPeriod');
  refresh.disabled = moreButton.disabled = period.disabled = true;
  status.textContent = '正在读取历史记录…';
  if (!more) {
    adminHistoryCursor = null;
    list.replaceChildren();
    moreButton.hidden = true;
    ++adminHistoryDetailRequest;
    document.querySelector('#historyDetail').hidden = true;
  }
  try {
    const params = new URLSearchParams();
    if (period.value && period.value !== 'all') params.set('period', period.value);
    if (more && adminHistoryCursor) params.set('before', adminHistoryCursor);
    const data = await feedbackJson('/api/history' + (params.size ? `?${params}` : ''));
    for (const item of data.items) {
      const owner = item.user ? `${item.user.display_name}（${item.user.username}）` : '旧记录，未关联客服';
      const button = feedbackNode('button', `${owner} · ${new Date(item.created_at).toLocaleString()} · ${item.result_count} 条结果 · 查看`, 'history-record');
      button.type = 'button';
      if (item.query_image_url) {
        const image = feedbackNode('img');
        image.src = item.query_image_url;
        image.alt = '客户照片';
        image.loading = 'lazy';
        image.onerror = () => { image.hidden = true; };
        button.prepend(image);
      } else button.append(' · 未保存客户照片');
      button.onclick = async () => {
        const request = ++adminHistoryDetailRequest;
        const detail = document.querySelector('#historyDetail');
        detail.hidden = false;
        detail.textContent = '正在读取匹配详情…';
        button.disabled = true;
        try {
          const record = await feedbackJson(`/api/history/${item.id}`);
          if (request !== adminHistoryDetailRequest) return;
          renderFeedbackHistory(detail, record);
          detail.scrollIntoView({behavior: 'smooth', block: 'start'});
        } catch (error) {
          if (request === adminHistoryDetailRequest) detail.textContent = error.message || '读取失败，请重新点击记录重试。';
        } finally { button.disabled = false; }
      };
      list.append(button);
    }
    adminHistoryCursor = data.next_before;
    adminHistoryLoaded = true;
    moreButton.hidden = !adminHistoryCursor;
    status.textContent = list.children.length ? '' : '所选时间范围内暂无匹配记录。';
  } catch (error) { status.textContent = error.message || '读取失败，请刷新重试。'; }
  finally {
    adminHistoryLoading = false;
    refresh.disabled = moreButton.disabled = period.disabled = false;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tab').forEach((button) => {
    button.onclick = () => {
      document.querySelectorAll('.tab,.view').forEach((node) => node.classList.remove('active'));
      button.classList.add('active');
      document.querySelector(`#${button.dataset.view}`).classList.add('active');
      if (button.dataset.view === 'history' && !adminHistoryLoaded) loadAdminHistory();
      if (button.dataset.view === 'accounts') loadAccounts();
      if (button.dataset.view === 'monitor') loadMonitor();
    };
  });
  document.querySelector('#historyRefresh').onclick = () => loadAdminHistory();
  document.querySelector('#historyMore').onclick = () => loadAdminHistory(true);
  document.querySelector('#historyPeriod').onchange = () => loadAdminHistory();
  document.querySelector('#refreshAccounts').onclick = loadAccounts;
  document.querySelector('#accountForm').onsubmit = async (event) => {
    event.preventDefault();
    const status = document.querySelector('#accountCreateStatus');
    const button = document.querySelector('#createAccount');
    const password = document.querySelector('#newPassword').value;
    if (password !== document.querySelector('#confirmPassword').value) {
      status.textContent = '两次密码不一致。';
      return;
    }
    button.disabled = true;
    try {
      await CarpetApiClient.requestJson(fetch, '/api/accounts', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: document.querySelector('#newUsername').value.trim(), display_name: document.querySelector('#newDisplayName').value.trim(), password})});
      document.querySelector('#accountForm').reset();
      status.textContent = '账号已开通，请将账号信息告知对应客服。';
      await loadAccounts();
    } catch (error) { status.textContent = error.message || '开通失败，请重试。'; }
    finally { button.disabled = false; }
  };
  document.querySelector('#refreshMonitor').onclick = loadMonitor;
  document.querySelector('#monitorCustomer').onchange = loadMonitor;
  document.querySelector('#monitorPeriod').onchange = loadMonitor;
});

async function loadAccounts() {
  const status = document.querySelector('#accountsStatus');
  status.textContent = '正在读取…';
  try {
    const data = await feedbackJson('/api/accounts');
    const list = document.querySelector('#accountsList');
    list.replaceChildren();
    for (const user of data.items) {
      list.append(feedbackNode('p', `${user.display_name} · ${user.username} · ${user.role === 'admin' ? '管理员' : '客服'}`));
    }
    status.textContent = '';
  } catch (error) { status.textContent = error.message || '读取失败，请重试。'; }
}

async function loadMonitor() {
  const customer = document.querySelector('#monitorCustomer');
  const status = document.querySelector('#monitorStatus');
  const list = document.querySelector('#monitorList');
  const refresh = document.querySelector('#refreshMonitor');
  refresh.disabled = customer.disabled = document.querySelector('#monitorPeriod').disabled = true;
  status.textContent = '正在读取查询统计…';
  try {
    const params = new URLSearchParams({period: document.querySelector('#monitorPeriod').value});
    if (customer.value) params.set('customer_id', customer.value);
    const data = await feedbackJson(`/api/monitor?${params}`);
    const selected = customer.value;
    customer.replaceChildren(new Option('全部客服', ''));
    for (const user of data.customers) customer.append(new Option(`${user.display_name}（${user.username}）`, user.id));
    customer.value = selected;
    document.querySelector('#monitorSummary').textContent = `${selected ? '指定客服' : '全部客服'} · 查询 ${data.total_matches} 次 · 下单成功 ${data.converted_matches} 次 · 近七日转化率 ${data.conversion_rate}%${data.truncated ? '（仅展示最新500条）' : ''}`;
    list.replaceChildren();
    for (const item of data.items) {
      const owner = customer.value ? '' : ' · ' + (data.customers.find(user => user.id === item.user_id)?.display_name || '客服');
      const row = feedbackNode('p', `${new Date(item.created_at).toLocaleString()} · ${item.result_count} 条推荐${item.conversion ? ` · 已下单 Top ${item.conversion.rank} · 商品 ID ${item.conversion.product_id || '未填写'}` : ' · 未登记下单'}${owner}`, 'feedback-meta');
      list.append(row);
    }
    status.textContent = list.children.length ? '' : '所选范围内暂无查询记录。';
  } catch (error) { status.textContent = error.message || '统计读取失败，请重试。'; }
  finally { refresh.disabled = customer.disabled = document.querySelector('#monitorPeriod').disabled = false; }
}
