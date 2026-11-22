// The manifest alone, so vite.daw.config.ts can write manifest.json without loading the plugin.

import type { PluginManifest } from 'ivandaw-core';

export const ID = 'com.ivandaw.musichands';
export const VERSION = '0.1.0';

export const manifest: PluginManifest = {
  id: ID,
  name: 'MusicHands',
  vendor: 'zhirnovcodes',
  version: VERSION,
  apiVersion: 2,
  kind: 'modulator',
  ports: [
    { id: 'notes', label: 'Notes', kind: 'events', direction: 'out', accepts: ['midi'] },
    { id: 'l-x', label: 'L X', kind: 'modulation', direction: 'out' },
    { id: 'l-y', label: 'L Y', kind: 'modulation', direction: 'out' },
    { id: 'l-z', label: 'L Z', kind: 'modulation', direction: 'out' },
    { id: 'r-x', label: 'R X', kind: 'modulation', direction: 'out' },
    { id: 'r-y', label: 'R Y', kind: 'modulation', direction: 'out' },
    { id: 'r-z', label: 'R Z', kind: 'modulation', direction: 'out' },
  ],
  ui: { width: 560, height: 340, resizable: false },
  features: ['state'],
};
