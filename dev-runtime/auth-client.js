document.addEventListener('DOMContentLoaded', async () => {
  const admin = location.pathname === '/admin' || location.pathname === '/feedback';
  const login = admin ? '/admin/login' : '/login';
  const status = document.querySelector('#accountStatus');
  try {
    const response = await fetch('/api/auth/me');
    if (response.status === 401) { location.replace(login); return; }
    if (!response.ok) throw new Error();
    const {user} = await response.json();
    status.textContent = `${user.display_name}（${user.username}）`;
  } catch { status.textContent = '账号状态暂不可用，请刷新重试。'; }
  document.querySelector('#logoutButton').onclick = async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await fetch('/api/auth/logout', {method: 'POST'});
      if (!response.ok && response.status !== 401) throw new Error();
      location.replace(login);
    } catch { button.disabled = false; status.textContent = '退出失败，请重试。'; }
  };
});
