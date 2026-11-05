// Minimal static server for the evidence base: no dependencies, read-only.
import http from 'node:http';
import { createReadStream, statSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';

const ROOT = new URL('./site/', import.meta.url).pathname;
const PORT = +(process.env.PORT || 5660);
const HOST = process.env.HOST || '0.0.0.0';
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.geojson': 'application/geo+json; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml', '.csv': 'text/csv; charset=utf-8', '.zip': 'application/zip', '.txt': 'text/plain; charset=utf-8' };
const SECURITY = {
  'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin', 'X-Frame-Options': 'SAMEORIGIN',
  'Content-Security-Policy': "default-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self' https://api.postcodes.io; frame-ancestors 'self'",
};

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  if (url.pathname === '/health') { res.writeHead(200, { 'Content-Type': 'text/plain' }); return res.end('ok'); }
  if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405); return res.end(); }
  let p = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, '');
  if (p.endsWith('/')) p += 'index.html';
  const file = join(ROOT, p);
  if (!file.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  let st; try { st = statSync(file); } catch { res.writeHead(404, { 'Content-Type': 'text/plain' }); return res.end('Not found'); }
  if (!st.isFile()) { res.writeHead(404); return res.end(); }
  const ext = extname(file);
  res.writeHead(200, Object.assign({ 'Content-Type': TYPES[ext] || 'application/octet-stream', 'Content-Length': st.size,
    'Cache-Control': ext === '.html' ? 'no-cache' : p.includes('/vendor/') ? 'public, max-age=604800' : 'public, max-age=300' }, SECURITY));
  if (req.method === 'HEAD') return res.end();
  createReadStream(file).pipe(res);
}).listen(PORT, HOST, () => console.log(`beds-analysis on http://${HOST}:${PORT}`));
