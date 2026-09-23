const adminLogin = location.pathname.startsWith('/admin');
document.querySelector('#loginTitle').textContent = adminLogin ? '管理员登录' : '客服登录';
const otherLogin = document.querySelector('#otherLogin');
otherLogin.href = adminLogin ? '/login' : '/admin/login';
otherLogin.textContent = adminLogin ? '返回客服登录' : '管理员登录（仅内网）';
document.querySelector('#loginForm').onsubmit = async (event) => {
  event.preventDefault();
  const button = document.querySelector('#loginSubmit');
  const status = document.querySelector('#loginStatus');
  button.disabled = true;
  status.textContent = '正在登录…';
  try {
    const response = await fetch(adminLogin ? '/api/auth/admin-login' : '/api/auth/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: document.querySelector('#username').value.trim(), password: document.querySelector('#password').value}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请检查账号和密码。');
    location.replace(adminLogin ? '/admin' : '/');
  } catch (error) {
    status.className = 'status-message error';
    status.textContent = error.message || '登录失败，请重试。';
    button.disabled = false;
  }
};
