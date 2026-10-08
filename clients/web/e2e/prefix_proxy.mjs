// Stands in for Caddy's `handle_path /hub/*`: strips the /hub prefix and forwards to the hub.
import http from 'node:http';

export function startPrefixProxy(listenPort, targetPort) {
  const server = http.createServer((req, res) => {
    if (!req.url.startsWith('/hub/')) {
      res.writeHead(404).end('not found');
      return;
    }
    const upstream = http.request(
      { host: '127.0.0.1', port: targetPort, path: req.url.slice('/hub'.length), method: req.method, headers: req.headers },
      (up) => {
        res.writeHead(up.statusCode ?? 502, up.headers);
        up.pipe(res);
      },
    );
    upstream.on('error', () => res.writeHead(502).end('bad gateway'));
    req.pipe(upstream);
  });
  return new Promise((resolve) => server.listen(listenPort, '127.0.0.1', () => resolve(server)));
}
