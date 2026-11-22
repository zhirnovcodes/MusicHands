// Scoped by the `mh-` class prefix. Injected once per mount.

export const CSS = `
.mh-root {
  --mh-bg: #17191d;
  --mh-panel: #22252b;
  --mh-line: #33373f;
  --mh-text: #e7e9ee;
  --mh-dim: #8b919c;
  --mh-l: #f0565c;
  --mh-r: #4c95ff;
  --mh-ok: #3ccf7a;
  --mh-warn: #f2b33d;
  box-sizing: border-box;
  width: 560px;
  height: 340px;
  display: grid;
  grid-template-rows: 36px 1fr;
  gap: 4px;
  padding: 0 4px 4px;
  background: var(--mh-bg);
  color: var(--mh-text);
  font: 12px/1.3 system-ui, -apple-system, "Segoe UI", sans-serif;
  user-select: none;
}
.mh-root *, .mh-root *::before, .mh-root *::after { box-sizing: border-box; }
.mh-head { display: flex; align-items: center; gap: 8px; padding: 0 4px; }
.mh-status { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--mh-dim); }
.mh-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--mh-dim); flex: none; }
.mh-dot[data-state="on"] { background: var(--mh-ok); }
.mh-dot[data-state="starting"] { background: var(--mh-warn); }
.mh-dot[data-state="error"] { background: var(--mh-l); }
.mh-select {
  max-width: 190px; height: 24px; padding: 0 6px;
  background: var(--mh-panel); color: var(--mh-text);
  border: 1px solid var(--mh-line); border-radius: 4px; font: inherit;
}
.mh-check { display: flex; align-items: center; gap: 4px; cursor: pointer; color: var(--mh-text); }
.mh-check input { margin: 0; accent-color: var(--mh-ok); }
.mh-body { display: grid; grid-template-columns: 400px 1fr; gap: 6px; min-height: 0; }
.mh-stage { position: relative; width: 400px; height: 300px; background: #000; border-radius: 4px; overflow: hidden; }
.mh-canvas { display: block; width: 400px; height: 300px; touch-action: none; }
.mh-canvas[data-edit="1"] { cursor: move; }
.mh-msg {
  position: absolute; inset: 0; display: flex; flex-direction: column; gap: 10px;
  align-items: center; justify-content: center; padding: 24px; text-align: center;
  color: var(--mh-dim); background: rgba(0, 0, 0, 0.55);
}
.mh-msg[hidden] { display: none; }
.mh-btn {
  height: 26px; padding: 0 12px; border-radius: 4px; cursor: pointer; font: inherit;
  background: var(--mh-panel); color: var(--mh-text); border: 1px solid var(--mh-line);
}
.mh-btn:hover { border-color: var(--mh-dim); }
.mh-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; align-content: start; }
.mh-hand { font-weight: 600; padding: 2px 4px 4px; border-bottom: 2px solid; }
.mh-hand[data-hand="L"] { border-color: var(--mh-l); }
.mh-hand[data-hand="R"] { border-color: var(--mh-r); }
.mh-ctl {
  display: grid; grid-template-columns: 30px 1fr; align-items: center; gap: 4px;
  width: 100%; height: 26px; padding: 0 5px; margin-top: 4px; cursor: pointer; text-align: left;
  background: var(--mh-panel); color: var(--mh-text); font: inherit;
  border: 1px solid var(--mh-line); border-radius: 4px;
}
.mh-ctl:hover { border-color: var(--mh-dim); }
.mh-ctl[aria-pressed="false"] { opacity: 0.4; }
.mh-ctl[aria-pressed="false"] .mh-name { text-decoration: line-through; }
.mh-bar { height: 6px; border-radius: 3px; background: var(--mh-line); overflow: hidden; }
.mh-fill { display: block; height: 100%; width: 0%; background: currentColor; }
.mh-ctl[data-hand="L"] { color: var(--mh-l); }
.mh-ctl[data-hand="R"] { color: var(--mh-r); }
.mh-name { color: var(--mh-text); }
.mh-lamp { width: 12px; height: 12px; border-radius: 50%; border: 1px solid currentColor; justify-self: end; }
.mh-lamp[data-on="1"] { background: currentColor; }
.mh-hint { grid-column: 1 / -1; margin-top: 6px; color: var(--mh-dim); font-size: 11px; }
`;
