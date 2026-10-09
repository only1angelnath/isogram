// IsoStyles.tsx — styles for the charts, tables, pills and tabs added with the metrics
// layer. Self-contained and `iso-` prefixed so it cannot collide with globals.css; uses
// only the brand variables already defined there (--accent, --data-2, --ink-dim) and the
// font variables set in app/layout.tsx. Rendered once from the root layout.

const CSS = `
@keyframes iso-draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
@keyframes iso-pulse { 0%,100% { opacity:.35; transform: scale(1); } 50% { opacity:1; transform: scale(1.9); } }
@keyframes iso-fade { from { opacity:0; transform: translateY(4px); } to { opacity:1; transform:none; } }
@keyframes iso-rise { from { opacity:0; transform: translateY(10px); } to { opacity:1; transform:none; } }

.iso-spark-line { stroke-dasharray: 1; stroke-dashoffset: 1; animation: iso-draw 1.8s cubic-bezier(.3,.7,.2,1) forwards; }
.iso-spark-end { transform-box: fill-box; transform-origin: center; animation: iso-pulse 1.8s ease-in-out infinite; }

/* ---- interactive chart ---- */
.iso-ytitle { font: 500 10px var(--font-mono), monospace; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-dim); margin-bottom: 8px; }
.iso-chart { display: grid; grid-template-columns: 48px 1fr; column-gap: 10px; }
.iso-yaxis { position: relative; font: 10px var(--font-mono), monospace; color: var(--ink-dim); }
.iso-yaxis span { position: absolute; right: 0; transform: translateY(50%); white-space: nowrap; }
.iso-plot { position: relative; border-left: 1px solid rgba(255,255,255,.14); border-bottom: 1px solid rgba(255,255,255,.14); }
.iso-grid { position: absolute; left: 0; right: 0; border-top: 1px dashed rgba(255,255,255,.07); pointer-events: none; }
.iso-cols { position: absolute; inset: 0; display: flex; }
.iso-col { flex: 1; position: relative; display: flex; align-items: flex-end; justify-content: center; cursor: crosshair; }
.iso-col:hover, .iso-col[data-active="true"] { background: rgba(255,255,255,.04); }
.iso-bar { width: 62%; max-width: 46px; border-radius: 4px 4px 0 0; transition: height .9s cubic-bezier(.2,.8,.2,1), filter .15s; }
.iso-col:hover .iso-bar, .iso-col[data-active="true"] .iso-bar { filter: brightness(1.3); }
.iso-nodata { position: absolute; bottom: 6px; left: 50%; transform: translateX(-50%); width: 38%; height: 0; border-top: 2px dotted rgba(255,255,255,.22); }
.iso-linesvg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible; }
.iso-dot { position: absolute; width: 7px; height: 7px; margin: -3.5px 0 0 -3.5px; border-radius: 50%; pointer-events: none; transition: transform .12s; }
.iso-cross { position: absolute; top: 0; bottom: 0; width: 0; border-left: 1px solid rgba(255,255,255,.25); pointer-events: none; }
.iso-tip { position: absolute; z-index: 6; top: 6px; pointer-events: none; background: #17171a; border: 1px solid rgba(255,255,255,.2); border-radius: 10px; padding: 9px 12px; min-width: 130px; font: 12px var(--font-body), sans-serif; box-shadow: 0 10px 28px rgba(0,0,0,.5); animation: iso-fade .12s ease-out; white-space: nowrap; }
.iso-tip b { display: block; font: 500 11px var(--font-mono), monospace; color: var(--ink-dim); margin-bottom: 3px; letter-spacing: .04em; }
.iso-tip .v { font: 500 15px var(--font-mono), monospace; }
.iso-tip small { display: block; color: var(--ink-dim); margin-top: 2px; font-size: 11px; }
.iso-xaxis { grid-column: 2; display: flex; margin-top: 7px; font: 10px var(--font-mono), monospace; color: var(--ink-dim); }
.iso-xaxis span { flex: 1; text-align: center; white-space: nowrap; overflow: visible; }

/* ---- tables ---- */
.iso-table-wrap { border: 1px solid rgba(255,255,255,.1); border-radius: 16px; overflow-x: auto; background: rgba(23,23,26,.78); backdrop-filter: blur(6px); }
.iso-table { width: 100%; border-collapse: separate; border-spacing: 0; font: 13px var(--font-body), sans-serif; }
.iso-table th { text-align: right; font: 500 10px var(--font-mono), monospace; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-dim); padding: 13px 16px; background: rgba(255,255,255,.035); border-bottom: 1px solid rgba(255,255,255,.09); white-space: nowrap; }
.iso-table td { padding: 12px 16px; text-align: right; border-bottom: 1px solid rgba(255,255,255,.05); font-variant-numeric: tabular-nums; white-space: nowrap; }
.iso-table th:first-child, .iso-table td:first-child { text-align: left; }
.iso-table tbody tr { transition: background .12s; animation: iso-rise .45s ease-out both; }
.iso-table tbody tr:hover { background: rgba(255,255,255,.045); }
.iso-table tbody tr:last-child td { border-bottom: none; }
.iso-table a { color: inherit; text-decoration: none; }
.iso-table a:hover { text-decoration: underline; text-underline-offset: 3px; }
.iso-num { font-family: var(--font-mono), monospace; }
.iso-dim { color: var(--ink-dim); }
.iso-table th a.iso-sort { color: inherit; text-decoration: none; white-space: nowrap; }
.iso-table th a.iso-sort:hover { color: #f2f0ea; text-decoration: none; }
.iso-table th a.iso-sort.on { color: var(--accent); }
.iso-pager { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; font: 12px var(--font-mono), monospace; }
.iso-pager-links { display: flex; flex-wrap: wrap; gap: 6px; }
.iso-pager-links a, .iso-pager-links .off { padding: 6px 11px; border-radius: 999px; border: 1px solid rgba(255,255,255,.13); text-decoration: none; color: var(--ink-dim); }
.iso-pager-links a:hover { color: #f2f0ea; border-color: rgba(255,255,255,.3); }
.iso-pager-links a[aria-current="page"] { background: rgba(255,91,46,.14); border-color: rgba(255,91,46,.55); color: #f2f0ea; }
.iso-pager-links .off { opacity: .4; border-style: dashed; }
.iso-bartd { background-repeat: no-repeat; background-size: var(--w, 0%) 100%; background-image: linear-gradient(90deg, var(--bar, rgba(255,91,46,.2)), var(--bar, rgba(255,91,46,.2))); }
.iso-pill { display: inline-block; padding: 2px 9px; border-radius: 999px; font: 500 10px var(--font-mono), monospace; letter-spacing: .05em; text-transform: uppercase; border: 1px solid rgba(255,255,255,.16); color: var(--ink-dim); vertical-align: middle; }
.iso-pill.good { color: #5FC9C0; border-color: rgba(95,201,192,.45); background: rgba(95,201,192,.09); }
.iso-pill.warn { color: #e3b45c; border-color: rgba(227,180,92,.45); background: rgba(227,180,92,.09); }
.iso-pill.bad { color: #FF5B2E; border-color: rgba(255,91,46,.5); background: rgba(255,91,46,.11); }
.iso-pill.dashed { border-style: dashed; }
.iso-avatar { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 9px; font: 600 11px var(--font-mono), monospace; color: #101012; flex: none; }
.iso-cell-main { display: flex; align-items: center; gap: 12px; min-width: 0; }
.iso-rank { width: 22px; color: var(--ink-dim); font: 12px var(--font-mono), monospace; text-align: right; }

/* ---- tabs / cards ---- */
.iso-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 22px; }
.iso-tab { padding: 8px 15px; border-radius: 999px; border: 1px solid rgba(255,255,255,.13); font-size: 13px; text-decoration: none; color: var(--ink-dim); transition: border-color .15s, color .15s, background .15s; }
.iso-tab:hover { color: #f2f0ea; border-color: rgba(255,255,255,.3); }
.iso-tab[aria-current="page"] { background: rgba(255,91,46,.14); border-color: rgba(255,91,46,.55); color: #f2f0ea; }
.iso-tab small { opacity: .6; margin-left: 6px; font: 11px var(--font-mono), monospace; }
.iso-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin-bottom: 26px; }
.iso-card { display: block; border: 1px solid rgba(255,255,255,.1); border-radius: 16px; padding: 16px 18px; background: rgba(23,23,26,.78); text-decoration: none; color: inherit; transition: transform .15s, border-color .15s; animation: iso-rise .5s ease-out both; }
.iso-card:hover { transform: translateY(-3px); border-color: rgba(255,255,255,.26); }
.iso-card[aria-current="page"] { border-color: rgba(255,91,46,.55); }
.iso-card .k { font: 500 10px var(--font-mono), monospace; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-dim); }
.iso-card .big { font: 500 24px var(--font-mono), monospace; margin: 8px 0 4px; }
.iso-card .sub { font-size: 12px; color: var(--ink-dim); }
.iso-podium { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; margin-bottom: 22px; }
.iso-podium .iso-card .place { font: 500 11px var(--font-mono), monospace; color: var(--accent); }
.iso-podium .iso-card .nm { font-size: 17px; font-weight: 600; margin: 6px 0 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.iso-meter { height: 6px; border-radius: 999px; background: rgba(255,255,255,.08); overflow: hidden; margin-top: 12px; }
.iso-meter i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--accent), #ff8a4a); }
`;

export function IsoStyles() {
  return <style dangerouslySetInnerHTML={{ __html: CSS }} />;
}

