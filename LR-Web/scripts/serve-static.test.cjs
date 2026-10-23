const assert = require('node:assert/strict');
const { once } = require('node:events');
const http = require('node:http');
const { spawn } = require('node:child_process');
const path = require('node:path');
const test = require('node:test');

async function listen(server) {
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return server.address().port;
}

// Exercise the real production middleware and its credential substitution.
// The companion API tests exercise the role/path rules behind this check.
test('private arm proxy verifies each browser session before forwarding', async (t) => {
  let forwarded = 0;
  const arm = http.createServer((req, res) => {
    forwarded += 1;
    assert.equal(req.headers.authorization, 'Bearer private-test-device-token');
    assert.equal(req.url, '/api/v1/studio/library?limit=1');
    res.setHeader('Content-Type', 'application/json');
    res.end('{"ok":true}');
  });
  const api = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/api/v1/system/network/confirm') {
      assert.match(req.headers['x-lr-local-address'], /^(::ffff:)?127\.0\.0\.1$/);
      res.end('{}');
      return;
    }
    assert.equal(url.pathname, '/api/v1/auth/bookarm-access');
    assert.equal(url.searchParams.get('method'), 'GET');
    if (req.headers.authorization !== 'Bearer public-test-session') res.statusCode = 401;
    else if (url.searchParams.get('path') !== '/v1/studio/library') res.statusCode = 403;
    res.end('{}');
  });
  const armPort = await listen(arm);
  const apiPort = await listen(api);
  const reserved = http.createServer();
  const webPort = await listen(reserved);
  await new Promise((resolve) => reserved.close(resolve));
  const server = spawn(process.execPath, [path.join(__dirname, 'serve-static.cjs'), '--port', String(webPort)], {
    env: { ...process.env, LR_API_TARGET: `127.0.0.1:${apiPort}`, LR_BOOKARM_TARGET: `127.0.0.1:${armPort}`, LR_BOOKARM_TOKEN: 'private-test-device-token' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(async () => {
    server.kill();
    arm.closeAllConnections();
    api.closeAllConnections();
    await Promise.all([new Promise((resolve) => arm.close(resolve)), new Promise((resolve) => api.close(resolve))]);
  });
  await once(server.stdout, 'data');
  // Clients cannot spoof the target network address used for confirmation.
  const confirm = await fetch(`http://127.0.0.1:${webPort}/api/v1/system/network/confirm`, {
    method: 'POST', headers: { 'X-LR-Local-Address': '192.168.4.1' }, body: '{}',
  });
  assert.equal(confirm.status, 200);
  const base = `http://127.0.0.1:${webPort}/bookarm-api`;
  assert.equal((await fetch(`${base}/v1/studio/library`)).status, 401);
  assert.equal(forwarded, 0);
  const headers = { Authorization: 'Bearer public-test-session' };
  assert.equal((await fetch(`${base}/v1/studio/joints`, { headers })).status, 403);
  assert.equal(forwarded, 0);
  const allowed = await fetch(`${base}/v1/studio/library?limit=1`, { headers });
  assert.equal(allowed.status, 200);
  assert.deepEqual(await allowed.json(), { ok: true });
  assert.equal(forwarded, 1);
  assert.equal((await fetch(`${base}/v1/studio/library/%E0%A4%A`, { headers })).status, 400);
  assert.equal((await fetch(`${base}/v1/studio/library/%252f../joints`, { headers })).status, 400);
  api.closeAllConnections();
  await new Promise((resolve) => api.close(resolve));
  assert.equal((await fetch(`${base}/v1/studio/library`, { headers })).status, 503);
  assert.equal(forwarded, 1);
});
