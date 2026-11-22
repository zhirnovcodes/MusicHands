// Dev page (index.html + src/dev.ts): runs the plugin without IvanDAW.
// Serves the runtime files at the same relative paths the DAW build puts them.

import { createReadStream } from 'node:fs';
import { defineConfig, type Plugin } from 'vite';
import { runtimeAssets } from './assets.ts';

const TYPES: Record<string, string> = {
  '.js': 'text/javascript',
  '.wasm': 'application/wasm',
  '.task': 'application/octet-stream',
};

function serveAssets(): Plugin {
  return {
    name: 'musichands-dev-assets',
    async configureServer(server) {
      const assets = await runtimeAssets();
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? '').split('?')[0]?.replace(/^\//, '') ?? '';
        const file = assets[path];
        if (!file) return next();
        const ext = path.slice(path.lastIndexOf('.'));
        res.setHeader('Content-Type', TYPES[ext] ?? 'application/octet-stream');
        createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  plugins: [serveAssets()],
});
