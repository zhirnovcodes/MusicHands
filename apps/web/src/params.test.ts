import { describe, expect, it } from 'vitest';
import { NOTE_PARAM, noteName, PARAMS, paramInfo, toNormalized, toPlain } from './params';
import { manifest } from './manifest';
import { SLIDER_PORT } from './core/catalog';

describe('params', () => {
  it('ids are unique and defaults are in range', () => {
    expect(new Set(PARAMS.map((p) => p.id)).size).toBe(PARAMS.length);
    for (const p of PARAMS) {
      expect(p.default).toBeGreaterThanOrEqual(p.min);
      expect(p.default).toBeLessThanOrEqual(p.max);
    }
  });

  it('every note parameter exists', () => {
    for (const id of Object.values(NOTE_PARAM)) expect(paramInfo(id)).toBeDefined();
  });

  it('normalized ↔ plain round-trips, whole numbers rounded', () => {
    const v = paramInfo('velocity');
    if (!v) throw new Error('velocity');
    expect(toPlain(v, toNormalized(v, 100))).toBe(100);
    expect(toPlain(v, 0.501)).toBe(64);
  });

  it('note names: C3 = 60', () => {
    expect(noteName(60)).toBe('C3');
    expect(noteName(49)).toBe('C#2');
  });
});

describe('manifest', () => {
  it('has a modulation port for every slider and a notes port', () => {
    const ids = manifest.ports.map((p) => p.id);
    for (const port of Object.values(SLIDER_PORT)) expect(ids).toContain(port);
    expect(ids).toContain('notes');
    expect(new Set(ids).size).toBe(ids.length);
  });
});
