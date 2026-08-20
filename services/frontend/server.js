/*
 * TraceFlix frontend host.
 *
 * Serves the Vite build and routes /api/* to the service that owns each prefix
 * (see routes.js), so the browser talks to one origin. Unknown paths fall back
 * to index.html so client-side routes survive a reload or a deep link.
 *
 *   npm run build && node server.js [--port 5173] [--host 127.0.0.1]
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { portForPath } from './routes.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function arg(name, fallback) {
  const i = process.argv.indexOf('--' + name);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const PORT = Number(arg('port', 5173));
const HOST = arg('host', '127.0.0.1');
const ROOT = path.join(__dirname, 'dist');

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

function sendFile(res, file, status = 200) {
  fs.readFile(file, (err, buf) => {
    if (err) {
      res.writeHead(404, { 'content-type': 'text/plain' }).end('not found');
      return;
    }
    res.writeHead(status, {
      'content-type': TYPES[path.extname(file)] || 'application/octet-stream',
      'cache-control': 'no-store',
    });
    res.end(buf);
  });
}

function serveStatic(req, res) {
  if (!fs.existsSync(ROOT)) {
    res.writeHead(500, { 'content-type': 'text/plain' });
    res.end('No build found. Run "npm install && npm run build" in services/frontend.');
    return;
  }

  const pathname = req.url.split('?')[0];
  const file = path.join(ROOT, path.normalize(pathname).replace(/^([/\\])+/, ''));

  if (!file.startsWith(ROOT)) {
    res.writeHead(403).end('forbidden');
    return;
  }

  // A real file wins; anything else is a client-side route.
  fs.stat(file, (err, stat) => {
    if (!err && stat.isFile()) sendFile(res, file);
    else sendFile(res, path.join(ROOT, 'index.html'));
  });
}

function proxy(req, res, port) {
  const started = process.hrtime.bigint();
  const upstream = http.request(
    {
      hostname: '127.0.0.1',
      port,
      path: req.url,
      method: req.method,
      headers: { ...req.headers, host: `127.0.0.1:${port}` },
    },
    (up) => {
      const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
      res.writeHead(up.statusCode, {
        ...up.headers,
        // measured at the host, so every timing on screen comes off one clock
        'x-traceflix-upstream-ms': elapsedMs.toFixed(1),
      });
      up.pipe(res);
    }
  );
  upstream.on('error', (e) => {
    res.writeHead(502, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: 'service unreachable', port, detail: e.message }));
  });
  req.pipe(upstream);
}

http
  .createServer((req, res) => {
    const pathname = req.url.split('?')[0];
    if (pathname.startsWith('/api/')) {
      const port = portForPath(pathname);
      if (port === null) {
        res.writeHead(404, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ error: 'no service owns this path', path: pathname }));
        return;
      }
      proxy(req, res, port);
      return;
    }
    serveStatic(req, res);
  })
  .listen(PORT, HOST, () => {
    console.log(`TraceFlix frontend  http://${HOST}:${PORT}`);
  });
