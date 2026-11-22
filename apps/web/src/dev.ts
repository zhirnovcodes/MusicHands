// Dev page: loads the plugin from source with a stand-in host, shows each modulation port's value,
// logs every event, and plays the notes on a small sine synth.

import type { HostContext, PluginEvent } from 'ivandaw-core';
import { manifest } from './manifest';
import factory from './plugin';

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;
const log = $<HTMLPreElement>('log');
const lines: string[] = [];

function write(line: string): void {
  lines.push(line);
  if (lines.length > 200) lines.shift();
  log.textContent = lines.join('\n');
  log.scrollTop = log.scrollHeight;
}

const meters = new Map<string, { fill: HTMLDivElement; text: HTMLSpanElement }>();
for (const p of manifest.ports) {
  if (p.kind !== 'modulation') continue;
  const ports = $('ports');
  const name = document.createElement('span');
  name.textContent = p.label;
  const meter = document.createElement('div');
  meter.className = 'meter';
  const fill = document.createElement('div');
  meter.append(fill);
  const text = document.createElement('span');
  text.textContent = '–';
  ports.append(name, meter, text);
  meters.set(p.id, { fill, text });
}

function synth(ctx: AudioContext): (bytes: [number, number, number]) => void {
  const voices = new Map<number, { osc: OscillatorNode; gain: GainNode }>();
  return ([status, note, velocity]) => {
    const t = ctx.currentTime;
    const on = (status & 0xf0) === 0x90 && velocity > 0;
    const old = voices.get(note);
    if (old) {
      old.gain.gain.cancelScheduledValues(t);
      old.gain.gain.setTargetAtTime(0, t, 0.05);
      old.osc.stop(t + 0.5);
      voices.delete(note);
    }
    if (!on || !$<HTMLInputElement>('synth').checked) return;
    const osc = new OscillatorNode(ctx, { frequency: 440 * 2 ** ((note - 69) / 12) });
    const gain = new GainNode(ctx, { gain: 0 });
    gain.gain.setTargetAtTime((0.2 * velocity) / 127, t, 0.01);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    voices.set(note, { osc, gain });
  };
}

$('start').addEventListener(
  'click',
  async () => {
    $<HTMLButtonElement>('start').disabled = true;
    const ctx = new AudioContext();
    const play = synth(ctx);
    const host: HostContext = {
      audioContext: ctx,
      apiVersion: 2,
      slotId: 'dev',
      transport: () => ({ playing: false, bpm: 120, beat: 0, numerator: 4, denominator: 4, loop: null }),
      notify: (level, message) => write(`[${level}] ${message}`),
      markDirty: () => {},
      assetUrl: (path) => new URL(path, location.href).href,
    };
    write('loading MediaPipe…');
    const plugin = await factory.create(host, null);
    write('ready');
    plugin.listen((e: PluginEvent) => {
      if (e.type === 'midi') {
        const on = (e.bytes[0] & 0xf0) === 0x90 && e.bytes[2] > 0;
        write(`${e.time.toFixed(3)} ${e.port} note ${on ? 'on ' : 'off'} ${e.bytes[1]} vel ${e.bytes[2]}`);
        play(e.bytes);
      } else if (e.type === 'automation') {
        const m = meters.get(e.port ?? '');
        if (m) {
          m.fill.style.width = `${e.value * 100}%`;
          m.text.textContent = e.value.toFixed(2);
        }
      }
    });
    plugin.subscribe((c) => write(`param ${c.id} = ${c.value.toFixed(3)} (${c.source})`));
    plugin.mount($('plugin'));
    Object.assign(window, { plugin });
  },
  { once: true },
);
