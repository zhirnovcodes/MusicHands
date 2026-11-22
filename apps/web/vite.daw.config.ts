// IvanDAW build → dist-daw/: index.js (everything bundled), manifest.json, mediapipe/*, models/*.
// The folder works from any URL: the plugin finds its files with host.assetUrl().

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig, type Plugin } from 'vite';
import { runtimeAssets } from './assets.ts';
import { manifest } from './src/manifest.ts';

const root = import.meta.dirname;

function pluginFolder(): Plugin {
  let assets: Record<string, string> = {};
  return {
    name: 'musichands-daw-folder',
    async buildStart() {
      assets = await runtimeAssets();
    },
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'manifest.json',
        source: `${JSON.stringify(manifest, null, 2)}\n`,
      });
      for (const [fileName, file] of Object.entries(assets)) {
        this.emitFile({ type: 'asset', fileName, source: readFileSync(file) });
      }
    },
  };
}

export default defineConfig({
  publicDir: false,
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    target: 'es2022',
    outDir: resolve(root, 'dist-daw'),
    emptyOutDir: true,
    lib: { entry: resolve(root, 'src/plugin.ts'), formats: ['es'], fileName: () => 'index.js' },
  },
  plugins: [pluginFolder()],
});
