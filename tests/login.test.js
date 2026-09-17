const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '..', 'login.js'), 'utf8');

test('客服与管理员各自登录，成功跳转；失败保留输入并允许重试', async () => {
  for (const [pathname, endpoint, target] of [['/login', '/api/auth/login', '/'], ['/admin/login', '/api/auth/admin-login', '/admin']]) {
    const nodes = Object.fromEntries(['loginTitle', 'otherLogin', 'loginForm', 'loginSubmit', 'loginStatus', 'username', 'password'].map(id => ['#' + id, {value: ''}]));
    nodes['#username'].value = 'cs_test';
    nodes['#password'].value = 'test-only-password';
    let success = false;
    let destination;
    const requests = [];
    const context = {document: {querySelector: s => nodes[s]}, location: {pathname, replace: url => {destination = url;}},
      fetch: async (url, options) => {
        requests.push({url, body: JSON.parse(options.body)});
        return {ok: success, json: async () => success ? {user: {id: 1}} : {detail: '账号或密码错误'}};
      }};
    vm.runInNewContext(script, context);
    await nodes['#loginForm'].onsubmit({preventDefault() {}});
    assert.equal(destination, undefined);
    assert.equal(nodes['#loginSubmit'].disabled, false);
    assert.equal(nodes['#loginStatus'].textContent, '账号或密码错误');
    success = true;
    await nodes['#loginForm'].onsubmit({preventDefault() {}});
    assert.equal(destination, target);
    assert.equal(requests[1].url, endpoint);
    assert.deepEqual(requests[1].body, {username: 'cs_test', password: 'test-only-password'});
  }
});
