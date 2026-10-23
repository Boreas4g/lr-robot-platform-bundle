#!/usr/bin/env node
/**
 * LR-Web 静态产物服务 + 反向代理（低内存替代 dev server）。
 *
 * 用法：node scripts/serve-static.cjs [--port 8000]
 *
 * - 静态托管 dist/（SPA 回退 index.html）
 * - /api/、/health → http://127.0.0.1:8080（含 WebSocket 升级转发）
 * - /bookarm-api/ → BookArm 私有 Unix socket 的 /api/（去前缀）
 *   （仅显式设置 LR_BOOKARM_TARGET 时才兼容旧 TCP 目标）
 */

const express = require('express');
const expressHttpProxy = require('express-http-proxy');
const http = require('http');
const net = require('net');
const path = require('path');
const url = require('url');

const PORT = Number(process.argv[process.argv.indexOf('--port') + 1] || 8000);
const DIST = path.join(__dirname, '..', 'dist');
const API_TARGET = process.env.LR_API_TARGET || '127.0.0.1:8080';
const BOOKARM_SOCKET =
  process.env.LR_BOOKARM_SOCKET || '/run/lr-bookarm/bookarm.sock';
const LEGACY_BOOKARM_TARGET = process.env.LR_BOOKARM_TARGET;
// BookArm 服务以 --token 运行时所有接口（含 /health）强制 Bearer 鉴权；
// 浏览器不持有 token，由本代理代为附加（socket 本身仅本机 boreas 组可达）。
const BOOKARM_TOKEN = process.env.LR_BOOKARM_TOKEN || '';

function bookarmProxyOptions() {
  const options = {
    proxyReqPathResolver: (req) => '/api' + (url.parse(req.url).path || '/'),
    proxyReqOptDecorator: (requestOptions) => {
      const next = { ...requestOptions };
      if (BOOKARM_TOKEN) {
        next.headers = {
          ...next.headers,
          Authorization: `Bearer ${BOOKARM_TOKEN}`,
        };
      }
      if (!LEGACY_BOOKARM_TARGET) {
        next.socketPath = BOOKARM_SOCKET;
        next.host = 'localhost';
        next.port = undefined;
      }
      return next;
    },
  };
  return options;
}

const app = express();

// Verify the browser session with control-api before using the private device
// credential. Fail closed if authentication is unavailable; never trust a role
// or a token supplied directly to the BookArm service by the browser.
function authorizeBookarm(req, res, next) {
  let pathname;
  try {
    pathname = decodeURIComponent(
      new URL(req.url, 'http://localhost').pathname,
    );
    if (
      pathname
        .split('/')
        .some(
          (segment) =>
            segment === '.' || segment === '..' || segment.includes('%'),
        )
    ) {
      return res.status(400).json({ detail: '无效的请求路径' });
    }
  } catch {
    return res.status(400).json({ detail: '无效的请求路径' });
  }
  const query = new URLSearchParams({
    path: pathname,
    method: req.method,
  });
  const check = http.get(
    `http://${API_TARGET}/api/v1/auth/bookarm-access?${query}`,
    {
      headers: { Authorization: req.headers.authorization || '' },
      timeout: 5000,
    },
    (response) => {
      response.resume();
      if (response.statusCode === 200) next();
      else
        res.status(response.statusCode === 401 ? 401 : 403).json({
          detail:
            response.statusCode === 401 ? '需要登录' : '当前账号没有调试权限',
        });
    },
  );
  check.on('timeout', () => check.destroy());
  check.on('error', () => {
    if (!res.headersSent)
      res.status(503).json({ detail: '登录服务暂时不可用，请稍后重试' });
  });
}

// /bookarm-api/v1/... → BookArm /api/v1/... through its managed Unix socket.
// LR_BOOKARM_TARGET is intentionally opt-in for an on-site legacy TCP daemon.
app.use(
  '/bookarm-api',
  authorizeBookarm,
  expressHttpProxy(LEGACY_BOOKARM_TARGET || 'localhost', bookarmProxyOptions()),
);

// /api/、/health → control-api（WebSocket 在下方 server.on('upgrade') 处理）
app.use(
  ['/api', '/health'],
  expressHttpProxy(API_TARGET, {
    proxyReqPathResolver: (req) => url.parse(req.originalUrl).path || '/',
    proxyReqOptDecorator: (options, req) => ({
      ...options,
      headers: {
        ...options.headers,
        'x-lr-local-address': req.socket.localAddress || '',
      },
    }),
  }),
);

// 带内容哈希的静态资源可缓存 1 小时；index.html 必须每次回源校验，
// 否则重新构建后浏览器仍长期引用旧哈希的 JS，页面看不到新版本。
app.use(
  express.static(DIST, {
    maxAge: '1h',
    index: 'index.html',
    setHeaders: (res, filePath) => {
      if (filePath.endsWith('.html')) {
        res.setHeader('Cache-Control', 'no-cache');
      }
    },
  }),
);
app.use((_req, res) => {
  res.setHeader('Cache-Control', 'no-cache');
  res.sendFile(path.join(DIST, 'index.html'));
});

const server = http.createServer(app);

// WebSocket 升级转发（/api/v1/realtime/robots 等），透传子协议鉴权头。
server.on('upgrade', (req, socket, head) => {
  const pathname = url.parse(req.url).pathname || '/';
  if (!pathname.startsWith('/api/')) {
    socket.destroy();
    return;
  }
  const [host, port] = API_TARGET.split(':');
  const upstream = net.connect(Number(port), host, () => {
    const headers = Object.entries(req.headers)
      .map(([key, value]) => `${key}: ${value}`)
      .join('\r\n');
    upstream.write(
      `${req.method} ${req.url} HTTP/${req.httpVersion}\r\n${headers}\r\n\r\n`,
    );
    if (head && head.length) upstream.write(head);
    upstream.pipe(socket);
    socket.pipe(upstream);
  });
  upstream.on('error', () => socket.destroy());
  socket.on('error', () => upstream.destroy());
});

server.listen(PORT, () => {
  console.log(`LR-Web static server: http://0.0.0.0:${PORT} (dist=${DIST})`);
  const bookarmTarget = LEGACY_BOOKARM_TARGET
    ? `${LEGACY_BOOKARM_TARGET}/api (legacy TCP override)`
    : `${BOOKARM_SOCKET} (Unix socket)`;
  console.log(`proxy /api→${API_TARGET}  /bookarm-api→${bookarmTarget}`);
});
