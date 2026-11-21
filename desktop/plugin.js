// src/lib/sdk.js
import { host, haptic, useQuery, useQueryClient, ROUTES_AREA, SIDEBAR_NAV_AREA, SandboxedFrame } from "@hermes/plugin-sdk";
import { useState, useEffect } from "react";
import { jsx, jsxs } from "react/jsx-runtime";

// src/lib/a11y.js
var NATIVE = /* @__PURE__ */ new Set(["button", "a", "input", "select", "textarea", "summary", "label", "option"]);
var WORD = /[\p{L}\p{N}]/u;
function textOf(children) {
  if (children == null || typeof children === "boolean") return "";
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(textOf).join("");
  return children.props ? textOf(children.props.children) : "";
}
var iconOnly = (children) => !WORD.test(textOf(children));
function pressable(tag, props, children) {
  if (typeof tag !== "string" || !props) return props;
  if (tag === "button") {
    return props.title && !props["aria-label"] && iconOnly(children) ? { ...props, "aria-label": props.title } : props;
  }
  if (typeof props.onClick !== "function" || NATIVE.has(tag) || props.role) return props;
  const { onClick, onKeyDown } = props;
  return {
    role: "button",
    tabIndex: 0,
    ...props,
    onKeyDown: (e) => {
      if (onKeyDown) onKeyDown(e);
      if (e.defaultPrevented || e.target !== e.currentTarget || e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      onClick(e);
    }
  };
}

// src/lib/sdk.js
var CTX = null;
var KEY = ["cockpit", "list"];
var OPEN = /* @__PURE__ */ new Set(["pending", "endorsed", "held", "returned", "posted"]);
var POLL_MS = 1e4;
var h = (tag, props, ...children) => {
  const given = pressable(tag, props, children);
  return children.length > 1 ? jsxs(tag, { ...given, children }) : jsx(tag, { ...given, children: children[0] });
};
var sub = { color: "var(--ui-text-tertiary)" };
var mono = { fontFamily: "var(--ui-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)" };
var stroke = "var(--ui-stroke-secondary)";
function ClearableTextarea(props) {
  const has = Boolean(props.value && String(props.value).length);
  const clear = () => {
    if (props.onChange) props.onChange({ target: { value: "" } });
  };
  return h(
    "div",
    { className: "relative min-w-0 w-full" },
    h("textarea", { ...props, className: (props.className || "") + " w-full", style: { ...props.style || {}, paddingRight: "1.6rem" } }),
    has ? h("button", { type: "button", tabIndex: -1, onMouseDown: (e) => e.preventDefault(), onClick: clear, title: "clear", className: "absolute right-1 top-1 rounded px-1 leading-4 text-xs", style: { color: "var(--ui-text-tertiary)", background: "rgba(127,127,127,.15)" } }, "\u2715") : null
  );
}
var btn = (label, onClick, extra = {}) => h("button", {
  type: "button",
  onClick: (e) => {
    e.stopPropagation();
    haptic("tap");
    onClick();
  },
  className: "rounded border px-2 py-0.5 text-xs hover:bg-(--ui-bg-hover,rgba(127,127,127,.12))",
  style: { borderColor: extra.accent ? "var(--ui-accent)" : stroke, color: extra.danger ? "var(--ui-danger, #d33)" : extra.accent ? "var(--ui-accent)" : "var(--ui-text-secondary)", ...extra.style || {} },
  title: extra.title || ""
}, label);
var selectBox = (value, onChange, options, extra = {}) => h("select", { value, onChange: (e) => onChange(e.target.value), className: "cockpit-input", ...extra }, ...options.map(([v, l]) => h("option", { key: v, value: v }, l)));
var seg = (active, id, label, set) => h("button", {
  type: "button",
  onClick: () => set(id),
  className: "px-2 py-0.5 text-xs rounded",
  style: { background: active === id ? "var(--ui-accent)" : "transparent", color: active === id ? "var(--ui-on-accent, #fff)" : "var(--ui-text-secondary)" }
}, label);
var CSS = `
.cockpit-spin{display:inline-block;animation:cockpitSpin 1s linear infinite}@keyframes cockpitSpin{to{transform:rotate(360deg)}}
@keyframes cockpitPulse{0%{opacity:.9;r:inherit}50%{opacity:.25}100%{opacity:.9}}.cockpit-glow{animation:cockpitPulse 1.8s ease-in-out infinite}
[data-plugin-root='cockpit'] button,[data-plugin-root='cockpit'] .select-none,[data-plugin-root='cockpit'] .cockpit-row{-webkit-user-select:none;user-select:none}
.cockpit-brief{display:grid;grid-template-columns:6.5rem 1fr;gap:.45rem .9rem;align-items:start;font-size:.8rem;line-height:1.45}
.cockpit-brief .k{font-size:.6875rem;text-transform:uppercase;letter-spacing:.04em;color:var(--ui-accent);font-weight:600;padding-top:.15rem}
.cockpit-brief .v{min-width:0}.cockpit-brief .v .t{margin:0}.cockpit-brief ul{list-style:disc;padding-left:1.1rem;margin:.15rem 0 0}.cockpit-brief li{margin:.15rem 0}.cockpit-brief li+li{padding-top:.1rem}
.cockpit-brief .k:nth-of-type(n+2){border-top:1px solid var(--ui-stroke-secondary);padding-top:.5rem}.cockpit-brief .v:nth-of-type(n+2){border-top:1px solid var(--ui-stroke-secondary);padding-top:.45rem}
.cockpit-section{display:flex;flex-direction:column;gap:.5rem}
.cockpit-row{transition:background .08s}.cockpit-row:hover{background:rgba(127,127,127,.09)!important}.cockpit-head{font-size:.6875rem;text-transform:uppercase;letter-spacing:.04em;color:var(--ui-text-tertiary)}
.cockpit-md{font-size:.8rem;line-height:1.5;min-width:0;max-width:100%;overflow-wrap:anywhere}.cockpit-md img{max-width:100%}.cockpit-table{max-width:100%;overflow-x:auto;margin:.5em 0;padding-bottom:2px}.cockpit-table table{margin:0;width:max-content;max-width:none}
/* horizontal scrollers (markdown and ADF tables, grid tables, the board's lanes, code blocks, panes): a thin rounded bar in the host's
   tertiary tone that stays visible while the content is wider \u2014 the ::-webkit-scrollbar styling makes Chromium draw a classic bar
   instead of macOS's overlay one that hides until you scroll (the standard scrollbar-* properties would switch that styling off) */
.cockpit-table::-webkit-scrollbar,.cockpit-scroll::-webkit-scrollbar,.cockpit-kb-lanes::-webkit-scrollbar,.cockpit-md pre::-webkit-scrollbar{height:8px;width:8px}
.cockpit-table::-webkit-scrollbar-track,.cockpit-scroll::-webkit-scrollbar-track,.cockpit-kb-lanes::-webkit-scrollbar-track,.cockpit-md pre::-webkit-scrollbar-track{background:color-mix(in srgb,var(--ui-text-tertiary) 10%,transparent);border-radius:999px}
.cockpit-table::-webkit-scrollbar-thumb,.cockpit-scroll::-webkit-scrollbar-thumb,.cockpit-kb-lanes::-webkit-scrollbar-thumb,.cockpit-md pre::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--ui-text-tertiary) 50%,transparent);border-radius:999px;border:2px solid transparent;background-clip:padding-box}
.cockpit-table::-webkit-scrollbar-thumb:hover,.cockpit-scroll::-webkit-scrollbar-thumb:hover,.cockpit-kb-lanes::-webkit-scrollbar-thumb:hover,.cockpit-md pre::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb,var(--ui-text-tertiary) 75%,transparent)}
.cockpit-table::-webkit-scrollbar-corner,.cockpit-scroll::-webkit-scrollbar-corner{background:transparent}
.cockpit-scroll{overflow-x:auto}
/* tracker document preview (render.render_adf): panels, collapsed expands and status lozenges in the tracker's colours */
.cockpit-doc .cockpit-doc-panel{display:flex;gap:.5rem;align-items:flex-start;border-radius:.375rem;padding:.5rem .625rem;margin:.375rem 0;border:1px solid transparent}.cockpit-doc .cockpit-doc-panel p{margin:0}
.cockpit-doc-info{background:color-mix(in srgb,#388bfd 12%,transparent);border-color:color-mix(in srgb,#388bfd 35%,transparent)!important}.cockpit-doc-note{background:color-mix(in srgb,#a78bfa 12%,transparent);border-color:color-mix(in srgb,#a78bfa 35%,transparent)!important}
.cockpit-doc-warning{background:color-mix(in srgb,#e2a400 14%,transparent);border-color:color-mix(in srgb,#e2a400 40%,transparent)!important}.cockpit-doc-error{background:color-mix(in srgb,#f85149 13%,transparent);border-color:color-mix(in srgb,#f85149 40%,transparent)!important}
.cockpit-doc-success{background:color-mix(in srgb,#2a9d5c 14%,transparent);border-color:color-mix(in srgb,#2a9d5c 40%,transparent)!important}
.cockpit-doc-expand{border:1px solid var(--ui-stroke-tertiary,var(--ui-stroke-secondary));border-radius:.375rem;padding:.25rem .5rem;margin:.375rem 0}.cockpit-doc-expand>summary{cursor:pointer;font-weight:500}.cockpit-doc-expand[open]>summary{margin-bottom:.25rem}
.cockpit-doc-status{display:inline-block;border-radius:.1875rem;padding:0 .3rem;font-size:.6875rem;font-weight:700;letter-spacing:.02em}.cockpit-doc-s-neutral{background:rgba(127,127,127,.2)}.cockpit-doc-s-purple{background:color-mix(in srgb,#a78bfa 25%,transparent);color:#a78bfa}
.cockpit-doc-s-blue{background:color-mix(in srgb,#388bfd 22%,transparent);color:#58a6ff}.cockpit-doc-s-red{background:color-mix(in srgb,#f85149 22%,transparent);color:#f85149}.cockpit-doc-s-yellow{background:color-mix(in srgb,#e2a400 25%,transparent);color:#c98a00}.cockpit-doc-s-green{background:color-mix(in srgb,#2a9d5c 22%,transparent);color:#2a9d5c}
.cockpit-doc-date,.cockpit-doc-mention,.cockpit-doc-media{border-radius:.1875rem;padding:0 .25rem;background:rgba(127,127,127,.15);font-size:.75rem}.cockpit-doc-tasks{list-style:none;padding-left:.5rem}
.cockpit-brief .v{overflow-wrap:anywhere}.cockpit-brief .v pre,.cockpit-brief .v code{white-space:pre-wrap}.cockpit-md h1,.cockpit-md h2,.cockpit-md h3,.cockpit-md h4{font-weight:600;margin:.9em 0 .35em}.cockpit-md h1{font-size:1.05rem}.cockpit-md h2{font-size:.95rem}.cockpit-md h3{font-size:.875rem}
.cockpit-md p{margin:.4em 0}.cockpit-md ul,.cockpit-md ol{padding-left:1.4em;margin:.4em 0}.cockpit-md ul{list-style:disc}.cockpit-md ol{list-style:decimal}.cockpit-md li{margin:.15em 0}
.cockpit-md code{font-family:var(--ui-font-mono,ui-monospace,Menlo,monospace);font-size:.75rem;background:rgba(127,127,127,.14);padding:.05em .3em;border-radius:3px}
.cockpit-md pre{background:rgba(127,127,127,.1);border:1px solid var(--ui-stroke-secondary);border-radius:4px;padding:.5em .7em;overflow:auto;margin:.5em 0}.cockpit-md pre code{background:none;padding:0}
.cockpit-md blockquote{border-left:3px solid var(--ui-stroke-secondary);margin:.5em 0;padding:.1em .8em;color:var(--ui-text-secondary)}.cockpit-md a{color:var(--ui-accent);text-decoration:underline}
.cockpit-md table{border-collapse:collapse;margin:.5em 0;font-size:.75rem}.cockpit-md th,.cockpit-md td{border:1px solid var(--ui-stroke-secondary);padding:.2em .5em;text-align:left}.cockpit-md th{font-weight:600}.cockpit-md hr{border:0;border-top:1px solid var(--ui-stroke-secondary);margin:.8em 0}
.cockpit-diff{font-family:var(--ui-font-mono,ui-monospace,Menlo,monospace);font-size:.72rem;line-height:1.35}.cockpit-diff .f{border:1px solid var(--ui-stroke-secondary);border-radius:4px;margin:.4em 0;overflow:hidden}
.cockpit-diff .fh{display:flex;gap:.6em;align-items:center;padding:.3em .6em;background:rgba(127,127,127,.1);cursor:pointer;font-weight:600}.cockpit-diff .fh .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cockpit-diff .l{display:grid;grid-template-columns:3.2em 3.2em 1fr;white-space:pre;overflow-x:auto}.cockpit-diff .l .no{text-align:right;padding:0 .4em;color:var(--ui-text-quaternary);user-select:none}
.cockpit-diff .l.a{background:rgba(46,160,67,.16)}.cockpit-diff .l.d{background:rgba(248,81,73,.16)}.cockpit-diff .l.hk{background:rgba(56,139,253,.12);color:var(--ui-text-secondary)}.cockpit-diff .l .t{padding:0 .5em}
.cockpit-diff .l.a .t::before{content:'+';color:#2ea043;margin-right:.3em}.cockpit-diff .l.d .t::before{content:'-';color:#f85149;margin-right:.3em}.cockpit-diff .l.c .t::before{content:' ';margin-right:.3em}
/* Board: the host kanban column and card chrome, read-only */
.cockpit-kb-lanes{display:flex;flex:1;min-height:0;gap:.5rem;overflow-x:auto;padding:.25rem 1rem .75rem}
.cockpit-kb-col{display:flex;flex-direction:column;height:100%;width:16rem;flex-shrink:0;border-radius:.5rem;padding:.5rem;background:color-mix(in srgb,var(--ui-bg-quinary,rgba(127,127,127,.14)) 50%,transparent);transition:background-color .15s}
.cockpit-kb-colhead{display:flex;height:1.25rem;align-items:center;gap:.375rem;padding:0 .25rem;margin-bottom:.375rem}
.cockpit-kb-dot{width:.375rem;height:.375rem;border-radius:9999px;flex-shrink:0}
.cockpit-kb-collabel{font-size:.6875rem;font-weight:500;text-transform:uppercase;letter-spacing:.025em;color:var(--ui-text-tertiary)}
.cockpit-kb-count,.cockpit-kb-age,.cockpit-kb-id{font-size:.625rem;font-variant-numeric:tabular-nums;color:var(--ui-text-quaternary)}
.cockpit-kb-body{position:relative;display:flex;min-height:0;flex:1;flex-direction:column;gap:.5rem;overflow-y:auto;overflow-x:hidden;padding:2px}
.cockpit-kb-empty{pointer-events:none;position:absolute;inset:0;display:grid;place-items:center;font-size:.6875rem;color:var(--ui-text-quaternary)}
.cockpit-kb-card{position:relative;display:flex;flex-direction:column;gap:.5rem;border-radius:.375rem;border:1px solid var(--ui-stroke-tertiary,var(--ui-stroke-secondary));border-left-width:2px;background:var(--ui-bg-elevated);padding:.625rem;cursor:pointer;animation:cockpitKbIn .18s ease-out;transition:background-color .15s,border-color .15s,transform .15s,box-shadow .15s,opacity .18s}
.cockpit-kb-card:hover{background:color-mix(in srgb,var(--ui-accent) 6%,var(--ui-bg-elevated));transform:translateY(-1px);box-shadow:0 2px 10px rgba(0,0,0,.18)}
.cockpit-kb-card.sel{border-color:var(--ui-accent);background:color-mix(in srgb,var(--ui-accent) 7%,transparent)}
.cockpit-kb-card.closed{opacity:.72}.cockpit-kb-card.closed:hover{opacity:1}
.cockpit-kb-card.out{animation:cockpitKbOut .2s ease-in forwards;pointer-events:none}
/* Done: one stacked card per ticket; two offset layers drawn with box-shadow (the card's own surface and stroke), lifted on hover */
.cockpit-kb-stackwrap{display:flex;flex-shrink:0;flex-direction:column;gap:.375rem;margin-bottom:6px}.cockpit-kb-stackwrap.out{animation:cockpitKbOut .2s ease-in forwards;pointer-events:none}
.cockpit-kb-stack{box-shadow:0 3px 0 -1px var(--ui-bg-elevated),0 3px 0 0 var(--ui-stroke-tertiary,var(--ui-stroke-secondary)),0 6px 0 -2px var(--ui-bg-elevated),0 6px 0 -1px var(--ui-stroke-tertiary,var(--ui-stroke-secondary))}
.cockpit-kb-stack:hover{box-shadow:0 3px 0 -1px var(--ui-bg-elevated),0 3px 0 0 var(--ui-stroke-secondary),0 6px 0 -2px var(--ui-bg-elevated),0 6px 0 -1px var(--ui-stroke-secondary),0 2px 10px rgba(0,0,0,.18)}
.cockpit-kb-stack.open{box-shadow:none;opacity:1}.cockpit-kb-stackn{border-radius:999px;padding:0 .375rem;font-size:.625rem;color:var(--ui-text-secondary);background:color-mix(in srgb,var(--ui-text-tertiary) 14%,transparent)}
.cockpit-kb-stackbody{display:flex;flex-direction:column;gap:.375rem;margin-left:.5rem;padding-left:.5rem;border-left:1px dashed var(--ui-stroke-secondary)}
@keyframes cockpitKbIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@keyframes cockpitKbOut{to{opacity:0;transform:translateY(-4px)}}
.cockpit-kb-title{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:.8125rem;font-weight:500;line-height:1.375}
.cockpit-kb-sum{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:.6875rem;line-height:1.375;color:var(--ui-text-tertiary)}
.cockpit-kb-line{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.6875rem;line-height:1.375}
.cockpit-kb-foot{display:flex;align-items:center;gap:.5rem;white-space:nowrap;font-size:.625rem;color:var(--ui-text-tertiary)}
.cockpit-kb-ticket{font-size:.625rem;color:var(--ui-accent);background:color-mix(in srgb,var(--ui-accent) 12%,transparent);border-radius:.25rem;padding:.05rem .35rem;white-space:nowrap}
.cockpit-cap{font-size:.5625rem;line-height:1rem;font-weight:600;letter-spacing:.02em;border:1px solid;border-radius:999px;padding:0 .4rem;white-space:nowrap;font-variant-numeric:tabular-nums}
.cockpit-kb-flow{font-size:.5625rem;line-height:1rem;color:var(--ui-text-tertiary);background:color-mix(in srgb,var(--ui-text-tertiary) 12%,transparent);border-radius:.25rem;padding:0 .3rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:5.5rem;flex:0 1 auto}
.cockpit-kb-sub{font-size:.625rem;font-weight:500;text-transform:uppercase;letter-spacing:.025em}
.cockpit-kb-status{display:inline-flex;align-items:center;gap:.375rem;border-radius:.25rem;padding:.2rem .5rem;font-size:.6875rem;font-weight:600;text-transform:uppercase;letter-spacing:.025em;white-space:nowrap}
.cockpit-kb-lane{display:inline-flex;min-width:0;align-items:center;gap:.25rem;border-radius:9999px;padding:.1rem .45rem .1rem .1rem;font-size:.625rem;font-weight:500}
.cockpit-kb-ava{display:grid;place-items:center;flex-shrink:0;border-radius:9999px;font-size:.5625rem;font-weight:600}
.cockpit-kb-more{flex-shrink:0;border-radius:.375rem;border:1px dashed var(--ui-stroke-secondary);padding:.375rem;font-size:.6875rem;color:var(--ui-text-tertiary);transition:color .15s,border-color .15s,background-color .15s}
.cockpit-kb-more:hover{border-color:var(--ui-text-quaternary);background:var(--chrome-action-hover,rgba(127,127,127,.12));color:var(--ui-text-primary,inherit)}
.cockpit-kb-filter{display:flex;flex-wrap:wrap;align-items:center;gap:.375rem;padding:.375rem .75rem;border-bottom:1px solid var(--ui-stroke-secondary)}
.cockpit-kb-total{border-radius:9999px;background:var(--ui-bg-quaternary,rgba(127,127,127,.18));padding:1px .375rem;font-size:.625rem;font-variant-numeric:tabular-nums;color:var(--ui-text-tertiary)}
.cockpit-kb-chip{border-radius:9999px;border:1px solid;padding:.05rem .5rem;font-size:.6875rem;transition:background-color .15s,color .15s,border-color .15s}
.cockpit-kb-input{min-width:14rem}
@property --cockpit-kb-arc{syntax:'<angle>';inherits:false;initial-value:0deg}
.cockpit-kb-arc{pointer-events:none;position:absolute;inset:-1px;border-radius:inherit;padding:1.5px;background:conic-gradient(from var(--cockpit-kb-arc),transparent 0deg,var(--cockpit-kb-tone,var(--ui-stroke-primary)) 55deg,transparent 110deg);-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;animation:cockpitKbArc 2.2s linear infinite}
.cockpit-kb-arc.stale{--cockpit-kb-tone:#fbbf24;animation-duration:6s}
@keyframes cockpitKbArc{to{--cockpit-kb-arc:360deg}}
.cockpit-input{border:1px solid var(--ui-stroke-secondary);border-radius:4px;background:var(--ui-bg-elevated,transparent);color:var(--ui-text-primary);padding:.1rem .4rem;font-size:.75rem}
/* the picker's open list is drawn by the system unless its options are given the theme's colours */
select.cockpit-input{color-scheme:light dark}
select.cockpit-input option{background:var(--ui-bg-elevated,Canvas);color:var(--ui-text-primary,CanvasText)}
`;
var fmtDur = (s) => {
  if (s == null || isNaN(s) || s < 0) return "\u2013";
  s = Math.round(s);
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const hh = Math.floor(m / 60);
  const mm = m % 60;
  if (hh < 24) return `${hh}h ${String(mm).padStart(2, "0")}m`;
  const d = Math.floor(hh / 24);
  return `${d}d ${hh % 24}h`;
};
var toMs = (v) => {
  if (v === null || v === void 0 || v === "") return NaN;
  const n = typeof v === "number" ? v : /^\d+(\.\d+)?$/.test(String(v)) ? Number(v) : NaN;
  return Number.isNaN(n) ? new Date(v).getTime() : n < 1e12 ? n * 1e3 : n;
};
var ago = (iso) => {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - toMs(iso)) / 1e3);
  return s < 3600 ? `${Math.round(s / 60)} min` : s < 86400 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d`;
};
var REPEATABLE = /* @__PURE__ */ new Set(["/chat-open", "/chat-write", "/chat-resize", "/chat-end", "/open-file", "/open-ide", "/fetch", "/platform-seen", "/pr-seen", "/sweep", "/digest", "/pr-scan", "/platform-scan", "/verify", "/ack", "/bumps-dismiss", "/ci-dismiss", "/vault-reveal"]);
var inflight = /* @__PURE__ */ new Map();
var COOLDOWN_MS = 2e3;
var post = (path, body) => {
  if (REPEATABLE.has(path)) return CTX.rest(path, { method: "POST", body });
  const key = path + JSON.stringify(body ?? {});
  if (inflight.has(key)) return Promise.reject(new Error(`${path.slice(1)}: already running \u2014 wait for it to finish`));
  const p = CTX.rest(path, { method: "POST", body });
  inflight.set(key, p);
  p.then(() => setTimeout(() => inflight.delete(key), COOLDOWN_MS), () => inflight.delete(key));
  return p;
};
var isWeb = (url) => {
  try {
    const u = new URL(String(url == null ? "" : url));
    return (u.protocol === "http:" || u.protocol === "https:") && Boolean(u.host);
  } catch (e) {
    return false;
  }
};
var openWeb = (url) => {
  if (!isWeb(url)) return false;
  CTX.os.openExternal(String(url));
  return true;
};
var openIde = async (body) => {
  try {
    const r = await post("/open-ide", body);
    host.notify({ kind: "info", message: r.out || "IDE opened" });
  } catch (e) {
    host.notifyError(e, "open IDE failed");
  }
};
var openFile = async (path) => {
  try {
    await post("/open-file", { path });
  } catch (e) {
    host.notifyError(e, "open file failed");
  }
};
var prButtons = (prs) => (prs || []).length ? h("span", { className: "flex flex-wrap items-center gap-1" }, ...prs.map((p) => h(
  "button",
  {
    key: p.repo + p.number,
    type: "button",
    onClick: (e) => {
      e.stopPropagation();
      haptic("tap");
      openWeb(p.url);
    },
    title: `${p.title || ""}
${p.url}`,
    className: "rounded border px-2 py-0.5 text-xs whitespace-nowrap",
    style: { borderColor: p.merged ? "var(--ui-text-quaternary)" : p.approvals && p.approvals.length ? "var(--ui-success, #2a9d5c)" : stroke, color: p.merged ? "var(--ui-text-tertiary)" : "var(--ui-text-secondary)" }
  },
  `${p.repo} #${p.number} \u2197`,
  p.role === "reviewer" ? h(
    "span",
    { style: sub },
    p.my_threads ? ` \xB7 you review \xB7 ${p.my_threads.resolved}/${p.my_threads.total} resolved` : " \xB7 you review"
  ) : null,
  p.merged ? h("span", { style: sub }, " merged") : p.approvals && p.approvals.length ? h(
    "span",
    { style: { color: "var(--ui-success, #2a9d5c)" } },
    " \u{1F44D}"
  ) : null,
  p.new_count ? h(
    "span",
    { className: "ml-1 rounded px-1", style: { background: "var(--ui-warning, #c98a00)", color: "#fff" } },
    `${p.new_count} new`
  ) : null
))) : null;
var prList = (prs) => {
  const open = (prs || []).filter((p) => !p.closed);
  const shut = (prs || []).filter((p) => p.closed);
  return open.length || shut.length ? h(
    "span",
    { className: "flex flex-wrap items-center gap-1" },
    prButtons(open),
    shut.length ? h("details", { className: "text-xs" }, h("summary", { className: "cursor-pointer", style: sub }, `closed (${shut.length})`), prButtons(shut)) : null
  ) : null;
};
var useList = () => useQuery({ queryKey: KEY, queryFn: () => CTX.rest("/list"), refetchInterval: POLL_MS, retry: 1 });
var thead = (cols, labels) => h("div", { className: "cockpit-head grid items-center gap-2 px-3 py-1 border-b leading-4", style: { gridTemplateColumns: cols, borderColor: stroke } }, ...labels.map((l, i) => h("div", { key: i, className: typeof l === "string" && l.startsWith(">") ? "text-right" : "" }, typeof l === "string" ? l.replace(/^>/, "") : l)));
var trow = (cols, { key, onClick, selected, title, children }) => h("div", { key, onClick, title, className: "cockpit-row grid items-center gap-2 px-3 py-1.5 text-xs border-b" + (onClick ? " cursor-pointer" : ""), style: { gridTemplateColumns: cols, borderColor: stroke, background: selected ? "var(--ui-bg-selected, rgba(127,127,127,.15))" : "transparent" } }, ...children);
var closeBtn = (onClose) => h("button", { type: "button", onClick: () => {
  haptic("tap");
  onClose();
}, title: "close (Esc)", className: "cockpit-head rounded px-1.5 leading-4", style: { background: "rgba(127,127,127,.12)" } }, "\u2715 close");
function Pane({ onClose, children }) {
  useEffect(() => {
    const k = (e) => {
      if (e.key === "Escape" && !window.__cockpitModalOpen) onClose();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return h(
    "div",
    { className: "min-w-0 flex-1 flex flex-col", style: { minHeight: 0 } },
    h("div", { className: "cockpit-head flex items-center justify-end px-3 py-1 border-b leading-4", style: { borderColor: stroke } }, closeBtn(onClose)),
    h("div", { className: "cockpit-scroll min-h-0 flex-1 overflow-auto flex flex-col" }, children)
  );
}
function SplitList({ cols, labels, rows, renderRow, selected, onSelect, onClose, empty, detail, detailWidth, footer }) {
  const close = onClose || (() => onSelect(null));
  return h(
    "div",
    { className: "flex min-h-0 flex-1" },
    h(
      "div",
      { className: "cockpit-scroll flex min-w-0 flex-col overflow-auto", style: { flex: selected ? `0 0 ${detailWidth || "46%"}` : "1 1 auto", borderRight: selected ? `1px solid ${stroke}` : "none" } },
      thead(cols, labels),
      rows.length ? rows.map((r) => renderRow(r)) : h("div", { className: "p-6 text-center text-xs", style: sub }, empty),
      footer ? h("div", { className: "cockpit-footer", style: { marginTop: "auto", paddingTop: "2rem" } }, footer) : null
    ),
    selected ? h(Pane, { onClose: close }, detail) : null
  );
}
var detailHead = (title, status, right) => h("div", { className: "flex items-baseline gap-2" }, h("div", { className: "font-medium text-sm" }, title), status ? h("div", { className: "text-xs", style: { color: status.color } }, status.text) : null, right ? h("div", { className: "ml-auto text-xs", style: sub }, right) : null);
var tabs = (tab, setTab, items) => h("div", { className: "flex items-center gap-1 self-start rounded border p-0.5", style: { borderColor: stroke } }, ...items.filter(Boolean).map(([id, label]) => seg(tab, id, label, setTab)));
function BriefGrid({ fields }) {
  return h("div", { className: "cockpit-brief" }, ...fields.filter((f) => f.text || f.items && f.items.length).flatMap((f, i) => [
    h("div", { key: "k" + i, className: "k" }, f.label),
    h("div", { key: "v" + i, className: "v" }, f.text ? h("div", { className: "t", style: f.color ? { color: f.color } : {} }, f.text) : null, f.items && f.items.length ? h("ul", null, ...f.items.map((it, j) => h("li", { key: j }, it))) : null)
  ]));
}
function Section({ title, open: initial = false, color, extra, children }) {
  const [open, setOpen] = useState(Boolean(initial));
  return h(
    "div",
    { className: "rounded border", style: { borderColor: color || stroke } },
    h(
      "div",
      { className: "flex items-center gap-2 px-2 py-1 cursor-pointer select-none", onClick: () => setOpen(!open), style: { background: "rgba(127,127,127,.06)" } },
      h("span", { style: sub }, open ? "\u25BE" : "\u25B8"),
      h("span", { className: "font-medium", style: color ? { color } : {} }, title),
      extra ? h("span", { className: "ml-auto flex gap-1", role: "presentation", onClick: (e) => e.stopPropagation() }, extra) : null
    ),
    open ? h("div", { className: "px-2.5 py-2 cockpit-section" }, children) : null
  );
}
function setCTX(ctx) {
  CTX = ctx;
}
var gateOf = () => "gatekeeper";
var endorserOf = (r) => r && r.endorsed && r.endorsed.by || "gatekeeper";

// src/app.js
import { useState as useState20, useEffect as useEffect12 } from "react";

// src/lib/packwords.js
var RUN_NAMES = { title: "Test run", results: "test-results.md", evidence: "evidence", plan: "test-plan.md" };
var runNames = (names) => ({ ...RUN_NAMES, ...Object.fromEntries(Object.entries(names || {}).filter(([k, v]) => k in RUN_NAMES && typeof v === "string" && v)) });
var escapeRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
var evidenceRel = (rel, evidence) => String(rel).replace(new RegExp("^\\.?\\/?" + escapeRe(evidence) + "\\/"), "");
var HINTS = {
  "bumps_tab": "Bumps \u2192 reviewer",
  "review": "The reviewer checks each PR head out in a worktree, reviews it against the real code, leaves the findings on the card and writes one review intent per PR. You publish them from the Outbox; nothing reaches the forge before that.",
  "bumps": "Tick the repos. Per repo a reviewer card lists its open dependency-bot pull requests and asks you which; every write it then prepares comes back here for you to publish. The weekday scan offers the candidates in the Inbox by itself.",
  "rereview": "the reviewer lane checks whether each of your threads was answered, reviews only the diff since your last review, and writes one review intent for your publish",
  "bumps_start": "Nothing has started. Pick the batch and Start: a reviewer card works through it, and every write comes back here for you to publish. Dismiss what a colleague takes."
};
var hintsOf = (hints) => ({ ...HINTS, ...Object.fromEntries(Object.entries(hints || {}).filter(([k, v]) => k in HINTS && typeof v === "string" && v)) });
var JIRA_KINDS = ["jira", "connector"];
var trackerWord = (kind) => JIRA_KINDS.includes(kind) ? "Jira" : "Tracker";
var TOOL_PROFILE = "claude";
var MODEL_PREFIX = "claude-";
var LANES_BEFORE = ["intake", "orchestrator", "worker-1", "worker-2", "worker-3", "tester-1", "tester-2", "tester-3", "reviewer", "gatekeeper", "analyst", TOOL_PROFILE, "advisor", "default"];
var AFTER_KIND = { orchestrator: "intake", [TOOL_PROFILE]: "analyst" };
var ROOT_PROFILE = "default";
var kindOf = (lane) => String(lane).replace(/-\d+$/, "");
function laneOrder(seats) {
  if (!Array.isArray(seats) || !seats.length) return LANES_BEFORE;
  const out = seats.filter((s) => typeof s === "string" && s);
  for (const [name, kind] of Object.entries(AFTER_KIND)) {
    if (out.includes(name)) continue;
    let at = -1;
    out.forEach((s, i) => {
      if (kindOf(s) === kind) at = i;
    });
    if (at < 0) at = kind === "intake" ? -1 : out.length - 1 - (out.includes("advisor") ? 1 : 0);
    out.splice(at + 1, 0, name);
  }
  if (!out.includes(ROOT_PROFILE)) out.push(ROOT_PROFILE);
  return out;
}
var sortLanes = (names, seats) => {
  const order = laneOrder(seats);
  return [...names].sort((a, b) => (order.indexOf(a) + 1 || order.length + 1) - (order.indexOf(b) + 1 || order.length + 1) || a.localeCompare(b));
};

// src/views/inbox.js
import { useState as useState13, useEffect as useEffect8 } from "react";

// src/lib/markdown.js
import { useState as useState2, useEffect as useEffect2, useMemo } from "react";
var useMermaidUrl = () => {
  const q2 = useQuery({ queryKey: ["cockpit", "repos"], queryFn: () => CTX.rest("/repos"), refetchInterval: POLL_MS * 6, retry: 0 });
  return q2.data && q2.data.mermaid_url || "";
};
var mermaidPage = (url, id, source, pad, size, dark) => `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:${pad}px;background:transparent;color:#ddd;font:${size}px -apple-system,system-ui,sans-serif}.mermaid{display:flex;justify-content:center}svg{max-width:100%;height:auto}pre{white-space:pre-wrap}</style></head><body>` + (url ? `<pre class="mermaid">${source.replace(/</g, "&lt;")}</pre>
<script type="module">
import mermaid from ${JSON.stringify(url)};
const post = (m) => parent.postMessage(Object.assign({ cockpitMermaid: ${JSON.stringify(id)} }, m), '*');
try { mermaid.initialize({ startOnLoad: false, theme: ${dark ? "'dark'" : "'default'"}, securityLevel: 'strict', flowchart: { useMaxWidth: true, htmlLabels: true }, sequence: { useMaxWidth: true } });
  await mermaid.run({ querySelector: '.mermaid' }); post({ height: document.body.scrollHeight });
  new ResizeObserver(() => post({ height: document.body.scrollHeight })).observe(document.body);
} catch (e) { post({ error: String(e && e.message || e), height: document.body.scrollHeight }) }
<\/script>` : `<pre>${source.replace(/</g, "&lt;")}</pre>`) + "</body></html>";
var unescapeHtml = (t) => t.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
var escapeHtml = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
var MERMAID_RE = /<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g;
var mermaidSeq = 0;
function MermaidModal({ source, onClose }) {
  useEffect2(() => {
    window.__cockpitModalOpen = true;
    return () => {
      window.__cockpitModalOpen = false;
    };
  }, []);
  const [id] = useState2(() => "mmf" + ++mermaidSeq);
  const [height, setHeight] = useState2(400);
  const url = useMermaidUrl();
  useEffect2(() => {
    const onMsg = (e) => {
      const d = e.data || {};
      if (d.cockpitMermaid !== id) return;
      if (d.height) setHeight(Math.max(300, Math.ceil(d.height) + 24));
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [id]);
  const page = mermaidPage(url, id, source, 12, 14, true);
  const src = "data:text/html;charset=utf-8," + encodeURIComponent(page);
  return h(
    "div",
    { role: "presentation", onClick: onClose, style: { position: "fixed", inset: 0, zIndex: 1e3, background: "rgba(0,0,0,.72)", display: "flex", alignItems: "center", justifyContent: "center", padding: "2vh 2vw" } },
    h(
      "div",
      { role: "presentation", onClick: (e) => e.stopPropagation(), className: "rounded-lg border flex flex-col", style: { borderColor: stroke, background: "var(--ui-bg-elevated, #1e1e1e)", width: "96vw", height: "96vh", overflow: "hidden" } },
      h("div", { className: "flex items-center gap-2 px-3 py-1.5 text-xs", style: { borderBottom: `1px solid ${stroke}` } }, h("span", { className: "font-medium" }, "Diagram"), h("span", { style: sub }, "Esc or click outside to close"), h("span", { className: "ml-auto" }, btn("\u2715 close", onClose))),
      h("div", { style: { flex: 1, overflow: "auto" } }, h(SandboxedFrame, { src, title: "diagram full " + id, style: { width: "100%", height: height + "px", border: 0, display: "block" } }))
    )
  );
}
function MermaidFrame({ source }) {
  const [id] = useState2(() => "mm" + ++mermaidSeq);
  const [height, setHeight] = useState2(220);
  const [err, setErr] = useState2(null);
  const url = useMermaidUrl();
  useEffect2(() => {
    const onMsg = (e) => {
      const d = e.data || {};
      if (d.cockpitMermaid !== id) return;
      if (d.error) setErr(d.error);
      else if (d.height) setHeight(Math.min(900, Math.max(80, Math.ceil(d.height) + 16)));
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [id]);
  const dark = (getComputedStyle(document.documentElement).colorScheme || "").includes("dark") || true;
  const page = mermaidPage(url, id, source, 6, 12, dark);
  const src = "data:text/html;charset=utf-8," + encodeURIComponent(page);
  const [full, setFull] = useState2(false);
  useEffect2(() => {
    if (!full) return;
    const k = (e) => {
      if (e.key === "Escape") setFull(false);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [full]);
  return h(
    "div",
    { className: "my-1 rounded border relative", style: { borderColor: stroke, background: "rgba(127,127,127,.06)" } },
    h("button", { type: "button", onClick: () => setFull(true), title: "full screen (Esc closes)", className: "absolute right-1 top-1 rounded px-1.5 text-xs", style: { background: "rgba(127,127,127,.25)", zIndex: 2 } }, "\u2922"),
    full ? h(MermaidModal, { source, onClose: () => setFull(false) }) : null,
    h(SandboxedFrame, { src, title: "diagram " + id, style: { width: "100%", height: height + "px", border: 0, display: "block" } }),
    err ? h("details", { className: "px-2 pb-1 text-[0.6875rem]", style: { color: "var(--ui-danger, #d33)" } }, h("summary", { className: "cursor-pointer" }, "diagram did not render: " + err.slice(0, 120)), h("pre", { className: "whitespace-pre-wrap", style: mono }, source)) : null
  );
}
function RichMd({ html, className, style }) {
  const parts = useMemo(() => {
    const out = [];
    let last = 0;
    let m;
    MERMAID_RE.lastIndex = 0;
    while (m = MERMAID_RE.exec(html || "")) {
      if (m.index > last) out.push({ html: html.slice(last, m.index) });
      out.push({ mermaid: unescapeHtml(m[1]) });
      last = m.index + m[0].length;
    }
    if (last < (html || "").length) out.push({ html: html.slice(last) });
    return out;
  }, [html]);
  return h("div", { className: "cockpit-md " + (className || ""), style }, ...parts.map((p, i) => p.mermaid != null ? h(MermaidFrame, { key: i, source: p.mermaid }) : h("div", { key: i, dangerouslySetInnerHTML: { __html: p.html } })));
}

// src/lib/diff.js
import { useState as useState3, useMemo as useMemo2 } from "react";
function parseDiff(text) {
  const files = [];
  let f = null, oldN = 0, newN = 0;
  for (const line of (text || "").split("\n")) {
    if (line.startsWith("diff --git ")) {
      const m = /^diff --git a\/(.+?) b\/(.+)$/.exec(line);
      f = { path: m ? m[2] : line.slice(11), old: m ? m[1] : "", lines: [], add: 0, del: 0, kind: "" };
      files.push(f);
      continue;
    }
    if (!f) continue;
    if (line.startsWith("new file")) {
      f.kind = "added";
      continue;
    }
    if (line.startsWith("deleted file")) {
      f.kind = "deleted";
      continue;
    }
    if (line.startsWith("rename ") || line.startsWith("similarity ")) {
      f.kind = "renamed";
      continue;
    }
    if (line.startsWith("index ") || line.startsWith("--- ") || line.startsWith("+++ ") || line.startsWith("Binary ")) {
      if (line.startsWith("Binary ")) f.lines.push({ k: "hk", t: line });
      continue;
    }
    if (line.startsWith("@@")) {
      const m = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      oldN = m ? +m[1] : 0;
      newN = m ? +m[2] : 0;
      f.lines.push({ k: "hk", t: line });
      continue;
    }
    if (line.startsWith("+")) {
      f.add++;
      f.lines.push({ k: "a", n: newN++, t: line.slice(1) });
      continue;
    }
    if (line.startsWith("-")) {
      f.del++;
      f.lines.push({ k: "d", o: oldN++, t: line.slice(1) });
      continue;
    }
    if (line.startsWith("\\")) continue;
    f.lines.push({ k: "c", o: oldN++, n: newN++, t: line.slice(1) });
  }
  return files;
}
var TEST_PATH = /(^|\/)(tests?|__tests__|__mocks__|spec|specs|cypress|fixtures|__snapshots__|testing)\/|\.(test|spec|cy)\.[jt]sx?$|Test\.php$|\.snap$|\/factories\/|\/seeders\/|\/stories\//;
var isTestFile = (path) => TEST_PATH.test(path || "");
function DiffFile({ f, repoDir, ticket, startOpen }) {
  const [open, setOpen] = useState3(startOpen && !isTestFile(f.path));
  const kind = f.kind ? ` \xB7 ${f.kind}` : "";
  return h(
    "div",
    { className: "f" },
    h(
      "div",
      { className: "fh", onClick: () => setOpen(!open) },
      h("span", null, open ? "\u25BE" : "\u25B8"),
      h("span", { className: "n", title: f.path }, f.path + kind + (isTestFile(f.path) ? " \xB7 test" : "")),
      h("span", { style: { color: "#2ea043" } }, `+${f.add}`),
      h("span", { style: { color: "#f85149" } }, `\u2212${f.del}`),
      repoDir ? btn("open", () => openIde({ ticket, file: `${repoDir}/${f.path}` }), { title: "open this file in the ticket workspace" }) : null
    ),
    open ? h("div", null, ...f.lines.map((l, i) => h(
      "div",
      { key: i, className: "l " + l.k },
      h("span", { className: "no" }, l.k === "hk" ? "" : l.o ?? ""),
      h("span", { className: "no" }, l.k === "hk" ? "" : l.n ?? ""),
      h("span", { className: "t" }, l.t)
    ))) : null
  );
}
var baseCommits = (data) => data.commits_base || [];
function DiffView({ data, onFetch }) {
  const codeFirst = (fs) => [...fs.filter((f) => !isTestFile(f.path)), ...fs.filter((f) => isTestFile(f.path))];
  const files = useMemo2(() => codeFirst(parseDiff(data.diff)), [data.diff]);
  const unc = useMemo2(() => codeFirst(parseDiff(data.uncommitted_diff)), [data.uncommitted_diff]);
  const many = files.filter((f) => !isTestFile(f.path)).length > 25;
  const origin = data.mode === "origin" || data.mode === "rebase" || data.mode === "change";
  const dropped = data.dropped || [];
  return h(
    "div",
    { className: "cockpit-diff flex flex-col gap-2" },
    data.rebase ? h(
      "div",
      { className: "rounded border p-2 text-xs flex flex-col gap-1", style: { borderColor: "var(--ui-accent)" } },
      h("div", { className: "font-medium" }, `Rebase only \xB7 ${data.rebase.proof}`),
      h("div", { style: sub }, "What the push changes is the base, not the patches. Commits that move under the branch (other people's work already on the base branch):"),
      h("pre", { className: "whitespace-pre-wrap text-xs", style: mono }, data.rebase.base_log || "(none)"),
      h("details", null, h("summary", { className: "cursor-pointer", style: sub }, 'git range-diff (every row should read "=" : identical patch)'), h("pre", { className: "whitespace-pre-wrap text-xs", style: mono }, data.rebase.range_diff))
    ) : null,
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2 text-xs", style: sub },
      h("span", null, `${data.repo} \xB7 ${data.range} \xB7 ${files.length} files`),
      origin ? h(
        "span",
        { style: { color: data.remote_exists ? data.fast_forward ? "var(--ui-success, #2a9d5c)" : "var(--ui-warning, #c98a00)" : "var(--ui-text-tertiary)" } },
        data.mode === "change" ? "\xB7 only this ticket's change on top of the rebase step" : data.remote_exists ? data.fast_forward ? "\xB7 fast-forward: origin keeps every commit it has" : "\xB7 NOT a fast-forward: a force push rewrites origin" : "\xB7 branch not known locally"
      ) : null,
      origin ? h("span", null, `\xB7 origin as of ${data.last_fetch ? new Date(data.last_fetch).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "unknown"}`) : null,
      origin && onFetch ? btn("Refresh from origin", onFetch, { title: "git fetch origin <branch> \u2014 a read; nothing is pushed" }) : null
    ),
    origin && data.note ? h("div", { className: "text-xs", style: sub }, data.note) : null,
    origin && dropped.length ? (() => {
      const st = (x) => typeof x === "string" ? "lost" : x.state || (x.replaced ? "replaced" : "lost");
      const line = (x) => typeof x === "string" ? x : x.line;
      const lost = dropped.filter((x) => st(x) === "lost");
      const rewritten = dropped.filter((x) => st(x) === "rewritten");
      const replaced = dropped.filter((x) => st(x) === "replaced");
      return h(
        "div",
        { className: "flex flex-col gap-1" },
        lost.length ? h(
          "div",
          { className: "rounded border p-2 text-xs", style: { borderColor: "var(--ui-danger, #d33)" } },
          h("div", { className: "font-medium", style: { color: "var(--ui-danger, #d33)" } }, `${lost.length} commit(s) on origin that no local commit carries \u2014 a force push LOSES them`),
          h("pre", { className: "whitespace-pre-wrap text-xs", style: mono }, lost.map(line).join("\n"))
        ) : null,
        rewritten.length ? h(
          "div",
          { className: "rounded border p-2 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)" } },
          h("div", { className: "font-medium", style: { color: "var(--ui-warning, #c98a00)" } }, `${rewritten.length} commit(s) on origin rewritten with changed content (a fixup squashed into them) \u2014 see "the change" for what changed`),
          h("pre", { className: "whitespace-pre-wrap text-xs", style: { ...mono, ...sub } }, rewritten.map(line).join("\n"))
        ) : null,
        replaced.length ? h(
          "div",
          { className: "rounded border p-2 text-xs", style: { borderColor: stroke } },
          h("div", { className: "font-medium", style: sub }, `${replaced.length} commit(s) on origin replaced by equivalents with the same patch (new base) \u2014 nothing is lost`),
          h("pre", { className: "whitespace-pre-wrap text-xs", style: { ...mono, ...sub } }, replaced.map(line).join("\n"))
        ) : null
      );
    })() : null,
    data.mode === "change" && data.range_diff ? h("details", { className: "text-xs" }, h("summary", { className: "cursor-pointer", style: sub }, "per-commit range-diff: rebase step \u2192 this push (which commits changed, and how)"), h("pre", { className: "whitespace-pre-wrap text-xs", style: mono }, data.range_diff)) : null,
    origin ? h("div", { className: "text-xs font-medium" }, data.mode === "change" ? `The branch's commits after this push (${(data.commits || []).length}); the file diff below is only what changed since the rebase step` : `This branch's own commits the push adds to origin (${(data.commits || []).length})`) : null,
    data.commits && data.commits.length ? h("pre", { className: "whitespace-pre-wrap text-xs", style: mono }, data.commits.join("\n")) : origin && data.remote_exists ? h("div", { className: "text-xs", style: sub }, "None: origin already has every own commit.") : null,
    origin && baseCommits(data).length ? h("div", null, h("div", { className: "text-xs font-medium", style: sub }, `Commits that arrive under the branch from the base branch through the rebase (${baseCommits(data).length}) \u2014 not this ticket's work`), h("pre", { className: "whitespace-pre-wrap text-xs", style: { ...mono, ...sub } }, baseCommits(data).join("\n"))) : null,
    data.mode === "origin" && data.remote_exists ? h("div", { className: "text-xs", style: sub }, "The file diff below is origin's tip \u2192 the local tip: everything the force push changes on the branch.") : null,
    data.stat ? h("pre", { className: "whitespace-pre-wrap text-xs", style: { ...mono, ...sub } }, data.stat) : null,
    ...files.flatMap((f, i) => [
      isTestFile(f.path) && (i === 0 || !isTestFile(files[i - 1].path)) ? h("div", { key: "tests-divider", className: "mt-1 text-xs", style: sub }, `tests (${files.length - i} file(s), collapsed)`) : null,
      h(DiffFile, { key: f.path, f, repoDir: data.repo_dir, ticket: data.ticket, startOpen: !many })
    ]),
    !files.length && !origin ? h("div", { className: "text-xs", style: sub }, "No committed changes in this range.") : null,
    data.uncommitted_status ? h(
      "div",
      { className: "mt-2" },
      h("div", { className: "text-xs font-medium", style: { color: "var(--ui-warning, #c98a00)" } }, `Uncommitted in the worktree (${data.uncommitted_status.split("\n").length} entries) \u2014 ${data.intent ? "not part of the intent" : "not committed or pushed yet"}`),
      h("pre", { className: "whitespace-pre-wrap text-xs", style: { ...mono, ...sub } }, data.uncommitted_status),
      ...unc.map((f) => h(DiffFile, { key: "u" + f.path, f, repoDir: data.repo_dir, ticket: data.ticket, startOpen: !data.intent }))
    ) : null
  );
}
function DiffPanel({ params, defaultMode, chained, rebaseOnly }) {
  const [mode, setMode] = useState3(defaultMode || "base");
  const qc = useQueryClient();
  const qs = Object.entries({ ...params, mode }).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  const q2 = useQuery({ queryKey: ["cockpit", "diff", qs], queryFn: () => CTX.rest("/diff?" + qs), staleTime: 15e3, retry: 0 });
  const fetchOrigin = async () => {
    const d = q2.data;
    if (!d) return;
    const branch = (d.remote || "").replace(/^origin\//, "");
    try {
      const r = await post("/fetch", { ticket: d.ticket, repo: d.repo, branch });
      host.notify({ kind: "info", message: r.out || "fetched" });
      qc.invalidateQueries({ queryKey: ["cockpit", "diff"] });
    } catch (e) {
      host.notifyError(e, "fetch failed");
    }
  };
  const toggle = h(
    "div",
    { className: "flex items-center gap-1 self-start rounded border p-0.5", style: { borderColor: stroke } },
    chained ? seg(mode, "change", "the change (this push adds, rebase excluded)", setMode) : seg(mode, "origin", rebaseOnly ? "origin \u2192 local (the rebase)" : "origin \u2192 local (what the push overwrites)", setMode),
    seg(mode, "base", "vs base (what the whole branch changes)", setMode),
    chained ? seg(mode, "rebase", "the rebase (what the base branch brings under the branch)", setMode) : null
  );
  if (q2.isLoading) return h("div", { className: "flex flex-col gap-2" }, toggle, h("div", { className: "text-xs p-2", style: sub }, "computing diff"));
  if (q2.error) return h("div", { className: "flex flex-col gap-2" }, toggle, h("div", { className: "text-xs p-2", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error)));
  return h("div", { className: "flex flex-col gap-2" }, toggle, h(DiffView, { data: q2.data, onFetch: mode === "origin" || mode === "rebase" ? fetchOrigin : null }));
}

// src/views/outbox.js
import { useState as useState9, useEffect as useEffect6 } from "react";

// src/views/qa.js
import { useState as useState4, useEffect as useEffect3 } from "react";
var fmtSize = (n) => n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : n > 1e3 ? Math.round(n / 1e3) + " KB" : n + " B";
var verdictMark = (v) => v === "pass" ? { t: "\u2705 pass", c: "var(--ui-success, #2a9d5c)" } : v === "fail" ? { t: "\u274C fail", c: "var(--ui-danger, #d33)" } : v === "warn" ? { t: "\u26A0 partial", c: "var(--ui-warning, #c98a00)" } : { t: v, c: "var(--ui-text-tertiary)" };
var blobCache = /* @__PURE__ */ new Map();
async function mediaUrl(path) {
  if (blobCache.has(path)) return blobCache.get(path);
  const f = await CTX.rest("/qa-file?path=" + encodeURIComponent(path));
  if (f.kind !== "media") return f;
  const bin = atob(f.b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([arr], { type: f.mime }));
  const v = { kind: "media", url, mime: f.mime, size: f.size };
  blobCache.set(path, v);
  return v;
}
function Viewer({ file, onClose }) {
  const [data, setData] = useState4(null);
  const [err, setErr] = useState4(null);
  useEffect3(() => {
    setData(null);
    setErr(null);
    mediaUrl(file.path).then(setData).catch((e) => setErr(String(e.message || e)));
  }, [file.path]);
  const body = err ? h("div", { className: "text-xs", style: { color: "var(--ui-danger, #d33)" } }, err) : !data ? h("div", { className: "text-xs", style: sub }, "loading") : data.kind === "media" && data.mime.startsWith("image/") ? h("img", { src: data.url, style: { maxWidth: "100%", maxHeight: "70vh", objectFit: "contain", border: `1px solid ${stroke}`, borderRadius: 4 } }) : data.kind === "media" && data.mime.startsWith("video/") ? h("video", { src: data.url, controls: true, autoPlay: false, style: { maxWidth: "100%", maxHeight: "70vh", border: `1px solid ${stroke}`, borderRadius: 4 } }) : data.kind === "media" ? h("iframe", { src: data.url, title: file.rel, style: { width: "100%", height: "70vh", border: `1px solid ${stroke}`, borderRadius: 4 } }) : data.html ? h(RichMd, { className: "rounded border px-3 py-1", style: { borderColor: stroke }, html: data.html }) : h("pre", { className: "whitespace-pre-wrap rounded border p-2 text-xs", style: { ...mono, borderColor: stroke, maxHeight: "70vh", overflow: "auto" } }, data.text);
  return h(
    "div",
    { className: "flex flex-col gap-1 rounded border p-2", style: { borderColor: "var(--ui-accent)" } },
    h(
      "div",
      { className: "flex items-center gap-2 text-xs" },
      h("span", { className: "font-medium truncate", style: mono, title: file.path }, file.rel || file.path.split("/").slice(-2).join("/")),
      h("span", { style: sub }, fmtSize(file.size || 0)),
      h("span", { className: "ml-auto flex gap-1" }, btn("Reveal", () => CTX.os.revealPath(file.path)), btn("Open", () => openFile(file.path)), btn("\u2715", onClose))
    ),
    body
  );
}
function Run({ run, ticket, onView, selected, names }) {
  const [open, setOpen] = useState4(true);
  const named = runNames(names);
  const r = run.results;
  const byRel = Object.fromEntries(run.files.map((f) => [f.rel, f]));
  const resolve = (rel) => {
    const k = evidenceRel(rel, named.evidence);
    if (byRel[k]) return byRel[k];
    const pre = k.replace(/\*.*$/, "");
    const hit = run.files.find((f) => f.rel.startsWith(pre) || f.rel.split("/").pop().startsWith(pre));
    return hit || { path: run.dir + "/" + rel.replace(/^\.?\//, ""), rel: k, kind: "other", size: 0 };
  };
  const counts = r ? { pass: r.rows.filter((x) => x.verdict === "pass").length, fail: r.rows.filter((x) => x.verdict === "fail").length, warn: r.rows.filter((x) => x.verdict === "warn").length } : null;
  const media = run.files.filter((f) => f.kind === "image" || f.kind === "video" || f.kind === "pdf");
  return h(
    "div",
    { className: "rounded border", style: { borderColor: stroke } },
    h(
      "div",
      { className: "flex items-center gap-2 px-2 py-1 text-xs cursor-pointer", onClick: () => setOpen(!open), style: { background: "rgba(127,127,127,.08)" } },
      h("span", null, open ? "\u25BE" : "\u25B8"),
      h("span", { className: "font-medium" }, run.name),
      r ? h("span", { style: sub, title: r.date_detail || "" }, r.date || "") : h("span", { style: sub }, "no " + named.results),
      counts ? h(Counts, { c: counts, total: r.rows.length }) : null,
      h("span", { className: "ml-auto", style: sub }, `${run.files.length} files \xB7 ${media.length} media`),
      btn("Reveal", () => CTX.os.revealPath(run.dir)),
      btn("Open", () => openFile(run.dir + "/" + named.results))
    ),
    open ? h(
      "div",
      { className: "flex flex-col gap-2 p-2" },
      r && (r.meta.Environment || r.meta["Under test"]) ? h(
        "div",
        { className: "text-xs flex flex-col gap-0.5" },
        r.meta["Under test"] ? h("div", null, h("span", { style: sub }, "under test: "), r.meta["Under test"]) : null,
        r.meta.Environment ? h("div", null, h("span", { style: sub }, "environment: "), r.meta.Environment) : null,
        r.meta["Cypress gate"] ? h("div", null, h("span", { style: sub }, "cypress gate: "), r.meta["Cypress gate"]) : null
      ) : null,
      r && r.rows.length ? h(
        "div",
        { className: "grid gap-x-2 gap-y-1 text-xs", style: { gridTemplateColumns: "1.5rem 1fr 5rem minmax(10rem, 1fr)" } },
        h("div", { style: sub }, "#"),
        h("div", { style: sub }, "scenario"),
        h("div", { style: sub }, "result"),
        h("div", { style: sub }, "evidence"),
        ...r.rows.flatMap((row) => {
          const m = verdictMark(row.verdict);
          return [
            h("div", { key: "n" + row.n, style: mono }, row.n),
            h("div", { key: "s" + row.n, title: row.note }, row.scenario, row.note ? h("span", { style: sub }, " \u2014 " + row.note) : null),
            h("div", { key: "r" + row.n, style: { color: m.c } }, m.t),
            h("div", { key: "e" + row.n, className: "flex flex-wrap gap-1" }, ...row.evidence.map((e) => {
              const f = resolve(e.rel);
              const active = selected && selected.path === f.path;
              return h(
                "button",
                {
                  key: e.rel,
                  type: "button",
                  onClick: () => onView(f),
                  title: f.path,
                  className: "rounded border px-1 text-[0.6875rem]",
                  style: {
                    borderColor: active ? "var(--ui-accent)" : stroke,
                    color: f.kind === "image" ? "var(--ui-accent)" : f.kind === "video" ? "var(--ui-success, #2a9d5c)" : "var(--ui-text-secondary)"
                  }
                },
                (f.kind === "image" ? "\u{1F5BC} " : f.kind === "video" ? "\u25B6 " : f.kind === "pdf" ? "\u{1F4C4} " : "") + e.label
              );
            }))
          ];
        })
      ) : null,
      media.length ? h(
        "div",
        { className: "flex flex-wrap gap-1 text-xs" },
        h("span", { style: sub }, "all media:"),
        ...media.map((f) => h(
          "button",
          {
            key: f.rel,
            type: "button",
            onClick: () => onView(f),
            title: `${f.rel} \xB7 ${fmtSize(f.size)}`,
            className: "rounded border px-1 text-[0.6875rem]",
            style: { borderColor: selected && selected.path === f.path ? "var(--ui-accent)" : stroke }
          },
          (f.kind === "image" ? "\u{1F5BC} " : f.kind === "video" ? "\u25B6 " : "\u{1F4C4} ") + f.rel.split("/").pop()
        ))
      ) : null,
      run.readme ? h(RichMd, { className: "text-xs", html: run.readme }) : null,
      r ? Object.entries(r.sections).map(([k, html]) => h("details", { key: k, className: "text-xs" }, h("summary", { className: "cursor-pointer", style: sub }, k), h(RichMd, { className: "pl-2", html }))) : null
    ) : null
  );
}
function Evidence({ ticket }) {
  const q2 = useQuery({ queryKey: ["cockpit", "qa", ticket], queryFn: () => CTX.rest("/qa?ticket=" + encodeURIComponent(ticket)), refetchInterval: 3e4, retry: 1 });
  const [file, setFile] = useState4(null);
  if (q2.isLoading) return h("div", { className: "p-2 text-xs", style: sub }, "loading evidence");
  if (q2.error) return h("div", { className: "p-2 text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  const d = q2.data;
  if (!d.dir) return h("div", { className: "p-2 text-xs", style: sub }, `No qa/${ticket} folder yet: the tester lane has not run a plan for this ticket.`);
  return h(
    "div",
    { className: "flex flex-col gap-2" },
    h(
      "div",
      { className: "text-xs flex items-center gap-2" },
      h("span", { style: sub }, d.dir),
      btn("Reveal", () => CTX.os.revealPath(d.dir)),
      d.scenarios ? h("details", { className: "ml-auto" }, h("summary", { className: "cursor-pointer", style: sub }, `test plan (${runNames(d.names).plan})`), h(RichMd, { className: "rounded border px-3 py-1 mt-1", style: { borderColor: stroke }, html: d.scenarios })) : null
    ),
    file ? h(Viewer, { file, onClose: () => setFile(null) }) : null,
    ...d.runs.map((run) => h(Run, { key: run.name, run, ticket, onView: setFile, selected: file, names: d.names })),
    !d.runs.length ? h("div", { className: "text-xs", style: sub }, "No test runs yet.") : null,
    d.review.length ? h("div", { className: "text-xs flex flex-wrap gap-1 items-center" }, h("span", { style: sub }, "review files:"), ...d.review.map((f) => h("button", { key: f.rel, type: "button", onClick: () => setFile(f), className: "rounded border px-1 text-[0.6875rem]", style: { borderColor: stroke } }, f.rel))) : null
  );
}
var QA_COLS = "6rem 3.5rem 4.5rem 6.5rem 1fr 4rem";
function Counts({ c, total }) {
  const cell = (n, glyph, color) => h("div", { className: "text-right whitespace-nowrap", style: { color: n ? color : "var(--ui-text-quaternary)", fontVariantNumeric: "tabular-nums" } }, n ? `${n} ${glyph}` : "\u2013");
  return h(
    "div",
    { className: "grid gap-x-3", style: { gridTemplateColumns: "3rem 3rem 3rem 3.5rem" } },
    cell(c.pass || 0, "\u2705", "var(--ui-success, #2a9d5c)"),
    cell(c.fail || 0, "\u274C", "var(--ui-danger, #d33)"),
    cell(c.warn || 0, "\u26A0", "var(--ui-warning, #c98a00)"),
    h("div", { className: "text-right whitespace-nowrap", style: { ...sub, fontVariantNumeric: "tabular-nums" } }, total ? `of ${total}` : "\u2013")
  );
}
function QaIndex() {
  const q2 = useQuery({ queryKey: ["cockpit", "qa", ""], queryFn: () => CTX.rest("/qa"), refetchInterval: 6e4, retry: 1 });
  const [selected, setSelected] = useState4(null);
  if (q2.isLoading) return h("div", { className: "p-3 text-xs", style: sub }, "loading");
  if (q2.error) return h("div", { className: "p-3 text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  return h(SplitList, {
    cols: QA_COLS,
    labels: [
      "ticket",
      ">runs",
      "last run",
      "date",
      h(
        "div",
        { className: "grid gap-x-3", style: { gridTemplateColumns: "3rem 3rem 3rem 3.5rem" } },
        h("div", { className: "text-right" }, "pass"),
        h("div", { className: "text-right" }, "fail"),
        h("div", { className: "text-right" }, "partial"),
        h("div", { className: "text-right" }, "total")
      ),
      ">age"
    ],
    rows: q2.data.tickets,
    selected,
    onSelect: setSelected,
    empty: "No test runs under qa/.",
    renderRow: (t) => trow(QA_COLS, { key: t.ticket, onClick: () => setSelected(selected === t.ticket ? null : t.ticket), selected: selected === t.ticket, children: [
      h("div", { key: "t", className: "font-medium truncate" }, (t.ticket || "").toUpperCase()),
      h("div", { key: "r", className: "text-right", style: mono }, t.runs || 0),
      h("div", { key: "l", style: mono }, (t.last_run || "").replace("test_run_", "#")),
      h("div", { key: "d", className: "truncate", style: sub, title: t.date_detail || t.date }, t.date || "\u2013"),
      h("div", { key: "s" }, h(Counts, { c: t.counts || {}, total: t.scenarios })),
      h("div", { key: "a", className: "text-right truncate", style: sub }, t.mtime ? ago(new Date(t.mtime * 1e3).toISOString()) : "")
    ] }),
    detail: selected ? h("div", { className: "flex flex-col gap-3 p-3" }, detailHead(selected.toUpperCase(), null, "test runs and evidence"), h(Evidence, { ticket: selected })) : null
  });
}

// src/views/demo.js
import { useState as useState7 } from "react";

// src/views/chat.js
import { useState as useState5, useEffect as useEffect4, useRef, useMemo as useMemo3 } from "react";

// node_modules/@xterm/xterm/lib/xterm.js
var xterm_default = '!function(e,t){if("object"==typeof exports&&"object"==typeof module)module.exports=t();else if("function"==typeof define&&define.amd)define([],t);else{var i=t();for(var s in i)("object"==typeof exports?exports:e)[s]=i[s]}}(globalThis,(()=>(()=>{"use strict";var e={4567:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.AccessibilityManager=void 0;const n=i(9042),o=i(9924),a=i(844),h=i(4725),c=i(2585),l=i(3656);let d=t.AccessibilityManager=class extends a.Disposable{constructor(e,t,i,s){super(),this._terminal=e,this._coreBrowserService=i,this._renderService=s,this._rowColumns=new WeakMap,this._liveRegionLineCount=0,this._charsToConsume=[],this._charsToAnnounce="",this._accessibilityContainer=this._coreBrowserService.mainDocument.createElement("div"),this._accessibilityContainer.classList.add("xterm-accessibility"),this._rowContainer=this._coreBrowserService.mainDocument.createElement("div"),this._rowContainer.setAttribute("role","list"),this._rowContainer.classList.add("xterm-accessibility-tree"),this._rowElements=[];for(let e=0;e<this._terminal.rows;e++)this._rowElements[e]=this._createAccessibilityTreeNode(),this._rowContainer.appendChild(this._rowElements[e]);if(this._topBoundaryFocusListener=e=>this._handleBoundaryFocus(e,0),this._bottomBoundaryFocusListener=e=>this._handleBoundaryFocus(e,1),this._rowElements[0].addEventListener("focus",this._topBoundaryFocusListener),this._rowElements[this._rowElements.length-1].addEventListener("focus",this._bottomBoundaryFocusListener),this._refreshRowsDimensions(),this._accessibilityContainer.appendChild(this._rowContainer),this._liveRegion=this._coreBrowserService.mainDocument.createElement("div"),this._liveRegion.classList.add("live-region"),this._liveRegion.setAttribute("aria-live","assertive"),this._accessibilityContainer.appendChild(this._liveRegion),this._liveRegionDebouncer=this.register(new o.TimeBasedDebouncer(this._renderRows.bind(this))),!this._terminal.element)throw new Error("Cannot enable accessibility before Terminal.open");this._terminal.element.insertAdjacentElement("afterbegin",this._accessibilityContainer),this.register(this._terminal.onResize((e=>this._handleResize(e.rows)))),this.register(this._terminal.onRender((e=>this._refreshRows(e.start,e.end)))),this.register(this._terminal.onScroll((()=>this._refreshRows()))),this.register(this._terminal.onA11yChar((e=>this._handleChar(e)))),this.register(this._terminal.onLineFeed((()=>this._handleChar("\\n")))),this.register(this._terminal.onA11yTab((e=>this._handleTab(e)))),this.register(this._terminal.onKey((e=>this._handleKey(e.key)))),this.register(this._terminal.onBlur((()=>this._clearLiveRegion()))),this.register(this._renderService.onDimensionsChange((()=>this._refreshRowsDimensions()))),this.register((0,l.addDisposableDomListener)(document,"selectionchange",(()=>this._handleSelectionChange()))),this.register(this._coreBrowserService.onDprChange((()=>this._refreshRowsDimensions()))),this._refreshRows(),this.register((0,a.toDisposable)((()=>{this._accessibilityContainer.remove(),this._rowElements.length=0})))}_handleTab(e){for(let t=0;t<e;t++)this._handleChar(" ")}_handleChar(e){this._liveRegionLineCount<21&&(this._charsToConsume.length>0?this._charsToConsume.shift()!==e&&(this._charsToAnnounce+=e):this._charsToAnnounce+=e,"\\n"===e&&(this._liveRegionLineCount++,21===this._liveRegionLineCount&&(this._liveRegion.textContent+=n.tooMuchOutput)))}_clearLiveRegion(){this._liveRegion.textContent="",this._liveRegionLineCount=0}_handleKey(e){this._clearLiveRegion(),/\\p{Control}/u.test(e)||this._charsToConsume.push(e)}_refreshRows(e,t){this._liveRegionDebouncer.refresh(e,t,this._terminal.rows)}_renderRows(e,t){const i=this._terminal.buffer,s=i.lines.length.toString();for(let r=e;r<=t;r++){const e=i.lines.get(i.ydisp+r),t=[],n=e?.translateToString(!0,void 0,void 0,t)||"",o=(i.ydisp+r+1).toString(),a=this._rowElements[r];a&&(0===n.length?(a.innerText="\xA0",this._rowColumns.set(a,[0,1])):(a.textContent=n,this._rowColumns.set(a,t)),a.setAttribute("aria-posinset",o),a.setAttribute("aria-setsize",s))}this._announceCharacters()}_announceCharacters(){0!==this._charsToAnnounce.length&&(this._liveRegion.textContent+=this._charsToAnnounce,this._charsToAnnounce="")}_handleBoundaryFocus(e,t){const i=e.target,s=this._rowElements[0===t?1:this._rowElements.length-2];if(i.getAttribute("aria-posinset")===(0===t?"1":`${this._terminal.buffer.lines.length}`))return;if(e.relatedTarget!==s)return;let r,n;if(0===t?(r=i,n=this._rowElements.pop(),this._rowContainer.removeChild(n)):(r=this._rowElements.shift(),n=i,this._rowContainer.removeChild(r)),r.removeEventListener("focus",this._topBoundaryFocusListener),n.removeEventListener("focus",this._bottomBoundaryFocusListener),0===t){const e=this._createAccessibilityTreeNode();this._rowElements.unshift(e),this._rowContainer.insertAdjacentElement("afterbegin",e)}else{const e=this._createAccessibilityTreeNode();this._rowElements.push(e),this._rowContainer.appendChild(e)}this._rowElements[0].addEventListener("focus",this._topBoundaryFocusListener),this._rowElements[this._rowElements.length-1].addEventListener("focus",this._bottomBoundaryFocusListener),this._terminal.scrollLines(0===t?-1:1),this._rowElements[0===t?1:this._rowElements.length-2].focus(),e.preventDefault(),e.stopImmediatePropagation()}_handleSelectionChange(){if(0===this._rowElements.length)return;const e=document.getSelection();if(!e)return;if(e.isCollapsed)return void(this._rowContainer.contains(e.anchorNode)&&this._terminal.clearSelection());if(!e.anchorNode||!e.focusNode)return void console.error("anchorNode and/or focusNode are null");let t={node:e.anchorNode,offset:e.anchorOffset},i={node:e.focusNode,offset:e.focusOffset};if((t.node.compareDocumentPosition(i.node)&Node.DOCUMENT_POSITION_PRECEDING||t.node===i.node&&t.offset>i.offset)&&([t,i]=[i,t]),t.node.compareDocumentPosition(this._rowElements[0])&(Node.DOCUMENT_POSITION_CONTAINED_BY|Node.DOCUMENT_POSITION_FOLLOWING)&&(t={node:this._rowElements[0].childNodes[0],offset:0}),!this._rowContainer.contains(t.node))return;const s=this._rowElements.slice(-1)[0];if(i.node.compareDocumentPosition(s)&(Node.DOCUMENT_POSITION_CONTAINED_BY|Node.DOCUMENT_POSITION_PRECEDING)&&(i={node:s,offset:s.textContent?.length??0}),!this._rowContainer.contains(i.node))return;const r=({node:e,offset:t})=>{const i=e instanceof Text?e.parentNode:e;let s=parseInt(i?.getAttribute("aria-posinset"),10)-1;if(isNaN(s))return console.warn("row is invalid. Race condition?"),null;const r=this._rowColumns.get(i);if(!r)return console.warn("columns is null. Race condition?"),null;let n=t<r.length?r[t]:r.slice(-1)[0]+1;return n>=this._terminal.cols&&(++s,n=0),{row:s,column:n}},n=r(t),o=r(i);if(n&&o){if(n.row>o.row||n.row===o.row&&n.column>=o.column)throw new Error("invalid range");this._terminal.select(n.column,n.row,(o.row-n.row)*this._terminal.cols-n.column+o.column)}}_handleResize(e){this._rowElements[this._rowElements.length-1].removeEventListener("focus",this._bottomBoundaryFocusListener);for(let e=this._rowContainer.children.length;e<this._terminal.rows;e++)this._rowElements[e]=this._createAccessibilityTreeNode(),this._rowContainer.appendChild(this._rowElements[e]);for(;this._rowElements.length>e;)this._rowContainer.removeChild(this._rowElements.pop());this._rowElements[this._rowElements.length-1].addEventListener("focus",this._bottomBoundaryFocusListener),this._refreshRowsDimensions()}_createAccessibilityTreeNode(){const e=this._coreBrowserService.mainDocument.createElement("div");return e.setAttribute("role","listitem"),e.tabIndex=-1,this._refreshRowDimensions(e),e}_refreshRowsDimensions(){if(this._renderService.dimensions.css.cell.height){this._accessibilityContainer.style.width=`${this._renderService.dimensions.css.canvas.width}px`,this._rowElements.length!==this._terminal.rows&&this._handleResize(this._terminal.rows);for(let e=0;e<this._terminal.rows;e++)this._refreshRowDimensions(this._rowElements[e])}}_refreshRowDimensions(e){e.style.height=`${this._renderService.dimensions.css.cell.height}px`}};t.AccessibilityManager=d=s([r(1,c.IInstantiationService),r(2,h.ICoreBrowserService),r(3,h.IRenderService)],d)},3614:(e,t)=>{function i(e){return e.replace(/\\r?\\n/g,"\\r")}function s(e,t){return t?"\x1B[200~"+e+"\x1B[201~":e}function r(e,t,r,n){e=s(e=i(e),r.decPrivateModes.bracketedPasteMode&&!0!==n.rawOptions.ignoreBracketedPasteMode),r.triggerDataEvent(e,!0),t.value=""}function n(e,t,i){const s=i.getBoundingClientRect(),r=e.clientX-s.left-10,n=e.clientY-s.top-10;t.style.width="20px",t.style.height="20px",t.style.left=`${r}px`,t.style.top=`${n}px`,t.style.zIndex="1000",t.focus()}Object.defineProperty(t,"__esModule",{value:!0}),t.rightClickHandler=t.moveTextAreaUnderMouseCursor=t.paste=t.handlePasteEvent=t.copyHandler=t.bracketTextForPaste=t.prepareTextForTerminal=void 0,t.prepareTextForTerminal=i,t.bracketTextForPaste=s,t.copyHandler=function(e,t){e.clipboardData&&e.clipboardData.setData("text/plain",t.selectionText),e.preventDefault()},t.handlePasteEvent=function(e,t,i,s){e.stopPropagation(),e.clipboardData&&r(e.clipboardData.getData("text/plain"),t,i,s)},t.paste=r,t.moveTextAreaUnderMouseCursor=n,t.rightClickHandler=function(e,t,i,s,r){n(e,t,i),r&&s.rightClickSelect(e),t.value=s.selectionText,t.select()}},7239:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ColorContrastCache=void 0;const s=i(1505);t.ColorContrastCache=class{constructor(){this._color=new s.TwoKeyMap,this._css=new s.TwoKeyMap}setCss(e,t,i){this._css.set(e,t,i)}getCss(e,t){return this._css.get(e,t)}setColor(e,t,i){this._color.set(e,t,i)}getColor(e,t){return this._color.get(e,t)}clear(){this._color.clear(),this._css.clear()}}},3656:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.addDisposableDomListener=void 0,t.addDisposableDomListener=function(e,t,i,s){e.addEventListener(t,i,s);let r=!1;return{dispose:()=>{r||(r=!0,e.removeEventListener(t,i,s))}}}},3551:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.Linkifier=void 0;const n=i(3656),o=i(8460),a=i(844),h=i(2585),c=i(4725);let l=t.Linkifier=class extends a.Disposable{get currentLink(){return this._currentLink}constructor(e,t,i,s,r){super(),this._element=e,this._mouseService=t,this._renderService=i,this._bufferService=s,this._linkProviderService=r,this._linkCacheDisposables=[],this._isMouseOut=!0,this._wasResized=!1,this._activeLine=-1,this._onShowLinkUnderline=this.register(new o.EventEmitter),this.onShowLinkUnderline=this._onShowLinkUnderline.event,this._onHideLinkUnderline=this.register(new o.EventEmitter),this.onHideLinkUnderline=this._onHideLinkUnderline.event,this.register((0,a.getDisposeArrayDisposable)(this._linkCacheDisposables)),this.register((0,a.toDisposable)((()=>{this._lastMouseEvent=void 0,this._activeProviderReplies?.clear()}))),this.register(this._bufferService.onResize((()=>{this._clearCurrentLink(),this._wasResized=!0}))),this.register((0,n.addDisposableDomListener)(this._element,"mouseleave",(()=>{this._isMouseOut=!0,this._clearCurrentLink()}))),this.register((0,n.addDisposableDomListener)(this._element,"mousemove",this._handleMouseMove.bind(this))),this.register((0,n.addDisposableDomListener)(this._element,"mousedown",this._handleMouseDown.bind(this))),this.register((0,n.addDisposableDomListener)(this._element,"mouseup",this._handleMouseUp.bind(this)))}_handleMouseMove(e){this._lastMouseEvent=e;const t=this._positionFromMouseEvent(e,this._element,this._mouseService);if(!t)return;this._isMouseOut=!1;const i=e.composedPath();for(let e=0;e<i.length;e++){const t=i[e];if(t.classList.contains("xterm"))break;if(t.classList.contains("xterm-hover"))return}this._lastBufferCell&&t.x===this._lastBufferCell.x&&t.y===this._lastBufferCell.y||(this._handleHover(t),this._lastBufferCell=t)}_handleHover(e){if(this._activeLine!==e.y||this._wasResized)return this._clearCurrentLink(),this._askForLink(e,!1),void(this._wasResized=!1);this._currentLink&&this._linkAtPosition(this._currentLink.link,e)||(this._clearCurrentLink(),this._askForLink(e,!0))}_askForLink(e,t){this._activeProviderReplies&&t||(this._activeProviderReplies?.forEach((e=>{e?.forEach((e=>{e.link.dispose&&e.link.dispose()}))})),this._activeProviderReplies=new Map,this._activeLine=e.y);let i=!1;for(const[s,r]of this._linkProviderService.linkProviders.entries())if(t){const t=this._activeProviderReplies?.get(s);t&&(i=this._checkLinkProviderResult(s,e,i))}else r.provideLinks(e.y,(t=>{if(this._isMouseOut)return;const r=t?.map((e=>({link:e})));this._activeProviderReplies?.set(s,r),i=this._checkLinkProviderResult(s,e,i),this._activeProviderReplies?.size===this._linkProviderService.linkProviders.length&&this._removeIntersectingLinks(e.y,this._activeProviderReplies)}))}_removeIntersectingLinks(e,t){const i=new Set;for(let s=0;s<t.size;s++){const r=t.get(s);if(r)for(let t=0;t<r.length;t++){const s=r[t],n=s.link.range.start.y<e?0:s.link.range.start.x,o=s.link.range.end.y>e?this._bufferService.cols:s.link.range.end.x;for(let e=n;e<=o;e++){if(i.has(e)){r.splice(t--,1);break}i.add(e)}}}}_checkLinkProviderResult(e,t,i){if(!this._activeProviderReplies)return i;const s=this._activeProviderReplies.get(e);let r=!1;for(let t=0;t<e;t++)this._activeProviderReplies.has(t)&&!this._activeProviderReplies.get(t)||(r=!0);if(!r&&s){const e=s.find((e=>this._linkAtPosition(e.link,t)));e&&(i=!0,this._handleNewLink(e))}if(this._activeProviderReplies.size===this._linkProviderService.linkProviders.length&&!i)for(let e=0;e<this._activeProviderReplies.size;e++){const s=this._activeProviderReplies.get(e)?.find((e=>this._linkAtPosition(e.link,t)));if(s){i=!0,this._handleNewLink(s);break}}return i}_handleMouseDown(){this._mouseDownLink=this._currentLink}_handleMouseUp(e){if(!this._currentLink)return;const t=this._positionFromMouseEvent(e,this._element,this._mouseService);t&&this._mouseDownLink===this._currentLink&&this._linkAtPosition(this._currentLink.link,t)&&this._currentLink.link.activate(e,this._currentLink.link.text)}_clearCurrentLink(e,t){this._currentLink&&this._lastMouseEvent&&(!e||!t||this._currentLink.link.range.start.y>=e&&this._currentLink.link.range.end.y<=t)&&(this._linkLeave(this._element,this._currentLink.link,this._lastMouseEvent),this._currentLink=void 0,(0,a.disposeArray)(this._linkCacheDisposables))}_handleNewLink(e){if(!this._lastMouseEvent)return;const t=this._positionFromMouseEvent(this._lastMouseEvent,this._element,this._mouseService);t&&this._linkAtPosition(e.link,t)&&(this._currentLink=e,this._currentLink.state={decorations:{underline:void 0===e.link.decorations||e.link.decorations.underline,pointerCursor:void 0===e.link.decorations||e.link.decorations.pointerCursor},isHovered:!0},this._linkHover(this._element,e.link,this._lastMouseEvent),e.link.decorations={},Object.defineProperties(e.link.decorations,{pointerCursor:{get:()=>this._currentLink?.state?.decorations.pointerCursor,set:e=>{this._currentLink?.state&&this._currentLink.state.decorations.pointerCursor!==e&&(this._currentLink.state.decorations.pointerCursor=e,this._currentLink.state.isHovered&&this._element.classList.toggle("xterm-cursor-pointer",e))}},underline:{get:()=>this._currentLink?.state?.decorations.underline,set:t=>{this._currentLink?.state&&this._currentLink?.state?.decorations.underline!==t&&(this._currentLink.state.decorations.underline=t,this._currentLink.state.isHovered&&this._fireUnderlineEvent(e.link,t))}}}),this._linkCacheDisposables.push(this._renderService.onRenderedViewportChange((e=>{if(!this._currentLink)return;const t=0===e.start?0:e.start+1+this._bufferService.buffer.ydisp,i=this._bufferService.buffer.ydisp+1+e.end;if(this._currentLink.link.range.start.y>=t&&this._currentLink.link.range.end.y<=i&&(this._clearCurrentLink(t,i),this._lastMouseEvent)){const e=this._positionFromMouseEvent(this._lastMouseEvent,this._element,this._mouseService);e&&this._askForLink(e,!1)}}))))}_linkHover(e,t,i){this._currentLink?.state&&(this._currentLink.state.isHovered=!0,this._currentLink.state.decorations.underline&&this._fireUnderlineEvent(t,!0),this._currentLink.state.decorations.pointerCursor&&e.classList.add("xterm-cursor-pointer")),t.hover&&t.hover(i,t.text)}_fireUnderlineEvent(e,t){const i=e.range,s=this._bufferService.buffer.ydisp,r=this._createLinkUnderlineEvent(i.start.x-1,i.start.y-s-1,i.end.x,i.end.y-s-1,void 0);(t?this._onShowLinkUnderline:this._onHideLinkUnderline).fire(r)}_linkLeave(e,t,i){this._currentLink?.state&&(this._currentLink.state.isHovered=!1,this._currentLink.state.decorations.underline&&this._fireUnderlineEvent(t,!1),this._currentLink.state.decorations.pointerCursor&&e.classList.remove("xterm-cursor-pointer")),t.leave&&t.leave(i,t.text)}_linkAtPosition(e,t){const i=e.range.start.y*this._bufferService.cols+e.range.start.x,s=e.range.end.y*this._bufferService.cols+e.range.end.x,r=t.y*this._bufferService.cols+t.x;return i<=r&&r<=s}_positionFromMouseEvent(e,t,i){const s=i.getCoords(e,t,this._bufferService.cols,this._bufferService.rows);if(s)return{x:s[0],y:s[1]+this._bufferService.buffer.ydisp}}_createLinkUnderlineEvent(e,t,i,s,r){return{x1:e,y1:t,x2:i,y2:s,cols:this._bufferService.cols,fg:r}}};t.Linkifier=l=s([r(1,c.IMouseService),r(2,c.IRenderService),r(3,h.IBufferService),r(4,c.ILinkProviderService)],l)},9042:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.tooMuchOutput=t.promptLabel=void 0,t.promptLabel="Terminal input",t.tooMuchOutput="Too much output to announce, navigate to rows manually to read"},3730:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.OscLinkProvider=void 0;const n=i(511),o=i(2585);let a=t.OscLinkProvider=class{constructor(e,t,i){this._bufferService=e,this._optionsService=t,this._oscLinkService=i}provideLinks(e,t){const i=this._bufferService.buffer.lines.get(e-1);if(!i)return void t(void 0);const s=[],r=this._optionsService.rawOptions.linkHandler,o=new n.CellData,a=i.getTrimmedLength();let c=-1,l=-1,d=!1;for(let t=0;t<a;t++)if(-1!==l||i.hasContent(t)){if(i.loadCell(t,o),o.hasExtendedAttrs()&&o.extended.urlId){if(-1===l){l=t,c=o.extended.urlId;continue}d=o.extended.urlId!==c}else-1!==l&&(d=!0);if(d||-1!==l&&t===a-1){const i=this._oscLinkService.getLinkData(c)?.uri;if(i){const n={start:{x:l+1,y:e},end:{x:t+(d||t!==a-1?0:1),y:e}};let o=!1;if(!r?.allowNonHttpProtocols)try{const e=new URL(i);["http:","https:"].includes(e.protocol)||(o=!0)}catch(e){o=!0}o||s.push({text:i,range:n,activate:(e,t)=>r?r.activate(e,t,n):h(0,t),hover:(e,t)=>r?.hover?.(e,t,n),leave:(e,t)=>r?.leave?.(e,t,n)})}d=!1,o.hasExtendedAttrs()&&o.extended.urlId?(l=t,c=o.extended.urlId):(l=-1,c=-1)}}t(s)}};function h(e,t){if(confirm(`Do you want to navigate to ${t}?\\n\\nWARNING: This link could potentially be dangerous`)){const e=window.open();if(e){try{e.opener=null}catch{}e.location.href=t}else console.warn("Opening link blocked as opener could not be cleared")}}t.OscLinkProvider=a=s([r(0,o.IBufferService),r(1,o.IOptionsService),r(2,o.IOscLinkService)],a)},6193:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.RenderDebouncer=void 0,t.RenderDebouncer=class{constructor(e,t){this._renderCallback=e,this._coreBrowserService=t,this._refreshCallbacks=[]}dispose(){this._animationFrame&&(this._coreBrowserService.window.cancelAnimationFrame(this._animationFrame),this._animationFrame=void 0)}addRefreshCallback(e){return this._refreshCallbacks.push(e),this._animationFrame||(this._animationFrame=this._coreBrowserService.window.requestAnimationFrame((()=>this._innerRefresh()))),this._animationFrame}refresh(e,t,i){this._rowCount=i,e=void 0!==e?e:0,t=void 0!==t?t:this._rowCount-1,this._rowStart=void 0!==this._rowStart?Math.min(this._rowStart,e):e,this._rowEnd=void 0!==this._rowEnd?Math.max(this._rowEnd,t):t,this._animationFrame||(this._animationFrame=this._coreBrowserService.window.requestAnimationFrame((()=>this._innerRefresh())))}_innerRefresh(){if(this._animationFrame=void 0,void 0===this._rowStart||void 0===this._rowEnd||void 0===this._rowCount)return void this._runRefreshCallbacks();const e=Math.max(this._rowStart,0),t=Math.min(this._rowEnd,this._rowCount-1);this._rowStart=void 0,this._rowEnd=void 0,this._renderCallback(e,t),this._runRefreshCallbacks()}_runRefreshCallbacks(){for(const e of this._refreshCallbacks)e(0);this._refreshCallbacks=[]}}},3236:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Terminal=void 0;const s=i(3614),r=i(3656),n=i(3551),o=i(9042),a=i(3730),h=i(1680),c=i(3107),l=i(5744),d=i(2950),_=i(1296),u=i(428),f=i(4269),v=i(5114),p=i(8934),g=i(3230),m=i(9312),S=i(4725),C=i(6731),b=i(8055),w=i(8969),y=i(8460),E=i(844),k=i(6114),L=i(8437),D=i(2584),R=i(7399),x=i(5941),A=i(9074),B=i(2585),T=i(5435),M=i(4567),O=i(779);class P extends w.CoreTerminal{get onFocus(){return this._onFocus.event}get onBlur(){return this._onBlur.event}get onA11yChar(){return this._onA11yCharEmitter.event}get onA11yTab(){return this._onA11yTabEmitter.event}get onWillOpen(){return this._onWillOpen.event}constructor(e={}){super(e),this.browser=k,this._keyDownHandled=!1,this._keyDownSeen=!1,this._keyPressHandled=!1,this._unprocessedDeadKey=!1,this._accessibilityManager=this.register(new E.MutableDisposable),this._onCursorMove=this.register(new y.EventEmitter),this.onCursorMove=this._onCursorMove.event,this._onKey=this.register(new y.EventEmitter),this.onKey=this._onKey.event,this._onRender=this.register(new y.EventEmitter),this.onRender=this._onRender.event,this._onSelectionChange=this.register(new y.EventEmitter),this.onSelectionChange=this._onSelectionChange.event,this._onTitleChange=this.register(new y.EventEmitter),this.onTitleChange=this._onTitleChange.event,this._onBell=this.register(new y.EventEmitter),this.onBell=this._onBell.event,this._onFocus=this.register(new y.EventEmitter),this._onBlur=this.register(new y.EventEmitter),this._onA11yCharEmitter=this.register(new y.EventEmitter),this._onA11yTabEmitter=this.register(new y.EventEmitter),this._onWillOpen=this.register(new y.EventEmitter),this._setup(),this._decorationService=this._instantiationService.createInstance(A.DecorationService),this._instantiationService.setService(B.IDecorationService,this._decorationService),this._linkProviderService=this._instantiationService.createInstance(O.LinkProviderService),this._instantiationService.setService(S.ILinkProviderService,this._linkProviderService),this._linkProviderService.registerLinkProvider(this._instantiationService.createInstance(a.OscLinkProvider)),this.register(this._inputHandler.onRequestBell((()=>this._onBell.fire()))),this.register(this._inputHandler.onRequestRefreshRows(((e,t)=>this.refresh(e,t)))),this.register(this._inputHandler.onRequestSendFocus((()=>this._reportFocus()))),this.register(this._inputHandler.onRequestReset((()=>this.reset()))),this.register(this._inputHandler.onRequestWindowsOptionsReport((e=>this._reportWindowsOptions(e)))),this.register(this._inputHandler.onColor((e=>this._handleColorEvent(e)))),this.register((0,y.forwardEvent)(this._inputHandler.onCursorMove,this._onCursorMove)),this.register((0,y.forwardEvent)(this._inputHandler.onTitleChange,this._onTitleChange)),this.register((0,y.forwardEvent)(this._inputHandler.onA11yChar,this._onA11yCharEmitter)),this.register((0,y.forwardEvent)(this._inputHandler.onA11yTab,this._onA11yTabEmitter)),this.register(this._bufferService.onResize((e=>this._afterResize(e.cols,e.rows)))),this.register((0,E.toDisposable)((()=>{this._customKeyEventHandler=void 0,this.element?.parentNode?.removeChild(this.element)})))}_handleColorEvent(e){if(this._themeService)for(const t of e){let e,i="";switch(t.index){case 256:e="foreground",i="10";break;case 257:e="background",i="11";break;case 258:e="cursor",i="12";break;default:e="ansi",i="4;"+t.index}switch(t.type){case 0:const s=b.color.toColorRGB("ansi"===e?this._themeService.colors.ansi[t.index]:this._themeService.colors[e]);this.coreService.triggerDataEvent(`${D.C0.ESC}]${i};${(0,x.toRgbString)(s)}${D.C1_ESCAPED.ST}`);break;case 1:if("ansi"===e)this._themeService.modifyColors((e=>e.ansi[t.index]=b.channels.toColor(...t.color)));else{const i=e;this._themeService.modifyColors((e=>e[i]=b.channels.toColor(...t.color)))}break;case 2:this._themeService.restoreColor(t.index)}}}_setup(){super._setup(),this._customKeyEventHandler=void 0}get buffer(){return this.buffers.active}focus(){this.textarea&&this.textarea.focus({preventScroll:!0})}_handleScreenReaderModeOptionChange(e){e?!this._accessibilityManager.value&&this._renderService&&(this._accessibilityManager.value=this._instantiationService.createInstance(M.AccessibilityManager,this)):this._accessibilityManager.clear()}_handleTextAreaFocus(e){this.coreService.decPrivateModes.sendFocus&&this.coreService.triggerDataEvent(D.C0.ESC+"[I"),this.element.classList.add("focus"),this._showCursor(),this._onFocus.fire()}blur(){return this.textarea?.blur()}_handleTextAreaBlur(){this.textarea.value="",this.refresh(this.buffer.y,this.buffer.y),this.coreService.decPrivateModes.sendFocus&&this.coreService.triggerDataEvent(D.C0.ESC+"[O"),this.element.classList.remove("focus"),this._onBlur.fire()}_syncTextArea(){if(!this.textarea||!this.buffer.isCursorInViewport||this._compositionHelper.isComposing||!this._renderService)return;const e=this.buffer.ybase+this.buffer.y,t=this.buffer.lines.get(e);if(!t)return;const i=Math.min(this.buffer.x,this.cols-1),s=this._renderService.dimensions.css.cell.height,r=t.getWidth(i),n=this._renderService.dimensions.css.cell.width*r,o=this.buffer.y*this._renderService.dimensions.css.cell.height,a=i*this._renderService.dimensions.css.cell.width;this.textarea.style.left=a+"px",this.textarea.style.top=o+"px",this.textarea.style.width=n+"px",this.textarea.style.height=s+"px",this.textarea.style.lineHeight=s+"px",this.textarea.style.zIndex="-5"}_initGlobal(){this._bindKeys(),this.register((0,r.addDisposableDomListener)(this.element,"copy",(e=>{this.hasSelection()&&(0,s.copyHandler)(e,this._selectionService)})));const e=e=>(0,s.handlePasteEvent)(e,this.textarea,this.coreService,this.optionsService);this.register((0,r.addDisposableDomListener)(this.textarea,"paste",e)),this.register((0,r.addDisposableDomListener)(this.element,"paste",e)),k.isFirefox?this.register((0,r.addDisposableDomListener)(this.element,"mousedown",(e=>{2===e.button&&(0,s.rightClickHandler)(e,this.textarea,this.screenElement,this._selectionService,this.options.rightClickSelectsWord)}))):this.register((0,r.addDisposableDomListener)(this.element,"contextmenu",(e=>{(0,s.rightClickHandler)(e,this.textarea,this.screenElement,this._selectionService,this.options.rightClickSelectsWord)}))),k.isLinux&&this.register((0,r.addDisposableDomListener)(this.element,"auxclick",(e=>{1===e.button&&(0,s.moveTextAreaUnderMouseCursor)(e,this.textarea,this.screenElement)})))}_bindKeys(){this.register((0,r.addDisposableDomListener)(this.textarea,"keyup",(e=>this._keyUp(e)),!0)),this.register((0,r.addDisposableDomListener)(this.textarea,"keydown",(e=>this._keyDown(e)),!0)),this.register((0,r.addDisposableDomListener)(this.textarea,"keypress",(e=>this._keyPress(e)),!0)),this.register((0,r.addDisposableDomListener)(this.textarea,"compositionstart",(()=>this._compositionHelper.compositionstart()))),this.register((0,r.addDisposableDomListener)(this.textarea,"compositionupdate",(e=>this._compositionHelper.compositionupdate(e)))),this.register((0,r.addDisposableDomListener)(this.textarea,"compositionend",(()=>this._compositionHelper.compositionend()))),this.register((0,r.addDisposableDomListener)(this.textarea,"input",(e=>this._inputEvent(e)),!0)),this.register(this.onRender((()=>this._compositionHelper.updateCompositionElements())))}open(e){if(!e)throw new Error("Terminal requires a parent element.");if(e.isConnected||this._logService.debug("Terminal.open was called on an element that was not attached to the DOM"),this.element?.ownerDocument.defaultView&&this._coreBrowserService)return void(this.element.ownerDocument.defaultView!==this._coreBrowserService.window&&(this._coreBrowserService.window=this.element.ownerDocument.defaultView));this._document=e.ownerDocument,this.options.documentOverride&&this.options.documentOverride instanceof Document&&(this._document=this.optionsService.rawOptions.documentOverride),this.element=this._document.createElement("div"),this.element.dir="ltr",this.element.classList.add("terminal"),this.element.classList.add("xterm"),e.appendChild(this.element);const t=this._document.createDocumentFragment();this._viewportElement=this._document.createElement("div"),this._viewportElement.classList.add("xterm-viewport"),t.appendChild(this._viewportElement),this._viewportScrollArea=this._document.createElement("div"),this._viewportScrollArea.classList.add("xterm-scroll-area"),this._viewportElement.appendChild(this._viewportScrollArea),this.screenElement=this._document.createElement("div"),this.screenElement.classList.add("xterm-screen"),this.register((0,r.addDisposableDomListener)(this.screenElement,"mousemove",(e=>this.updateCursorStyle(e)))),this._helperContainer=this._document.createElement("div"),this._helperContainer.classList.add("xterm-helpers"),this.screenElement.appendChild(this._helperContainer),t.appendChild(this.screenElement),this.textarea=this._document.createElement("textarea"),this.textarea.classList.add("xterm-helper-textarea"),this.textarea.setAttribute("aria-label",o.promptLabel),k.isChromeOS||this.textarea.setAttribute("aria-multiline","false"),this.textarea.setAttribute("autocorrect","off"),this.textarea.setAttribute("autocapitalize","off"),this.textarea.setAttribute("spellcheck","false"),this.textarea.tabIndex=0,this._coreBrowserService=this.register(this._instantiationService.createInstance(v.CoreBrowserService,this.textarea,e.ownerDocument.defaultView??window,this._document??"undefined"!=typeof window?window.document:null)),this._instantiationService.setService(S.ICoreBrowserService,this._coreBrowserService),this.register((0,r.addDisposableDomListener)(this.textarea,"focus",(e=>this._handleTextAreaFocus(e)))),this.register((0,r.addDisposableDomListener)(this.textarea,"blur",(()=>this._handleTextAreaBlur()))),this._helperContainer.appendChild(this.textarea),this._charSizeService=this._instantiationService.createInstance(u.CharSizeService,this._document,this._helperContainer),this._instantiationService.setService(S.ICharSizeService,this._charSizeService),this._themeService=this._instantiationService.createInstance(C.ThemeService),this._instantiationService.setService(S.IThemeService,this._themeService),this._characterJoinerService=this._instantiationService.createInstance(f.CharacterJoinerService),this._instantiationService.setService(S.ICharacterJoinerService,this._characterJoinerService),this._renderService=this.register(this._instantiationService.createInstance(g.RenderService,this.rows,this.screenElement)),this._instantiationService.setService(S.IRenderService,this._renderService),this.register(this._renderService.onRenderedViewportChange((e=>this._onRender.fire(e)))),this.onResize((e=>this._renderService.resize(e.cols,e.rows))),this._compositionView=this._document.createElement("div"),this._compositionView.classList.add("composition-view"),this._compositionHelper=this._instantiationService.createInstance(d.CompositionHelper,this.textarea,this._compositionView),this._helperContainer.appendChild(this._compositionView),this._mouseService=this._instantiationService.createInstance(p.MouseService),this._instantiationService.setService(S.IMouseService,this._mouseService),this.linkifier=this.register(this._instantiationService.createInstance(n.Linkifier,this.screenElement)),this.element.appendChild(t);try{this._onWillOpen.fire(this.element)}catch{}this._renderService.hasRenderer()||this._renderService.setRenderer(this._createRenderer()),this.viewport=this._instantiationService.createInstance(h.Viewport,this._viewportElement,this._viewportScrollArea),this.viewport.onRequestScrollLines((e=>this.scrollLines(e.amount,e.suppressScrollEvent,1))),this.register(this._inputHandler.onRequestSyncScrollBar((()=>this.viewport.syncScrollArea()))),this.register(this.viewport),this.register(this.onCursorMove((()=>{this._renderService.handleCursorMove(),this._syncTextArea()}))),this.register(this.onResize((()=>this._renderService.handleResize(this.cols,this.rows)))),this.register(this.onBlur((()=>this._renderService.handleBlur()))),this.register(this.onFocus((()=>this._renderService.handleFocus()))),this.register(this._renderService.onDimensionsChange((()=>this.viewport.syncScrollArea()))),this._selectionService=this.register(this._instantiationService.createInstance(m.SelectionService,this.element,this.screenElement,this.linkifier)),this._instantiationService.setService(S.ISelectionService,this._selectionService),this.register(this._selectionService.onRequestScrollLines((e=>this.scrollLines(e.amount,e.suppressScrollEvent)))),this.register(this._selectionService.onSelectionChange((()=>this._onSelectionChange.fire()))),this.register(this._selectionService.onRequestRedraw((e=>this._renderService.handleSelectionChanged(e.start,e.end,e.columnSelectMode)))),this.register(this._selectionService.onLinuxMouseSelection((e=>{this.textarea.value=e,this.textarea.focus(),this.textarea.select()}))),this.register(this._onScroll.event((e=>{this.viewport.syncScrollArea(),this._selectionService.refresh()}))),this.register((0,r.addDisposableDomListener)(this._viewportElement,"scroll",(()=>this._selectionService.refresh()))),this.register(this._instantiationService.createInstance(c.BufferDecorationRenderer,this.screenElement)),this.register((0,r.addDisposableDomListener)(this.element,"mousedown",(e=>this._selectionService.handleMouseDown(e)))),this.coreMouseService.areMouseEventsActive?(this._selectionService.disable(),this.element.classList.add("enable-mouse-events")):this._selectionService.enable(),this.options.screenReaderMode&&(this._accessibilityManager.value=this._instantiationService.createInstance(M.AccessibilityManager,this)),this.register(this.optionsService.onSpecificOptionChange("screenReaderMode",(e=>this._handleScreenReaderModeOptionChange(e)))),this.options.overviewRulerWidth&&(this._overviewRulerRenderer=this.register(this._instantiationService.createInstance(l.OverviewRulerRenderer,this._viewportElement,this.screenElement))),this.optionsService.onSpecificOptionChange("overviewRulerWidth",(e=>{!this._overviewRulerRenderer&&e&&this._viewportElement&&this.screenElement&&(this._overviewRulerRenderer=this.register(this._instantiationService.createInstance(l.OverviewRulerRenderer,this._viewportElement,this.screenElement)))})),this._charSizeService.measure(),this.refresh(0,this.rows-1),this._initGlobal(),this.bindMouse()}_createRenderer(){return this._instantiationService.createInstance(_.DomRenderer,this,this._document,this.element,this.screenElement,this._viewportElement,this._helperContainer,this.linkifier)}bindMouse(){const e=this,t=this.element;function i(t){const i=e._mouseService.getMouseReportCoords(t,e.screenElement);if(!i)return!1;let s,r;switch(t.overrideType||t.type){case"mousemove":r=32,void 0===t.buttons?(s=3,void 0!==t.button&&(s=t.button<3?t.button:3)):s=1&t.buttons?0:4&t.buttons?1:2&t.buttons?2:3;break;case"mouseup":r=0,s=t.button<3?t.button:3;break;case"mousedown":r=1,s=t.button<3?t.button:3;break;case"wheel":if(e._customWheelEventHandler&&!1===e._customWheelEventHandler(t))return!1;if(0===e.viewport.getLinesScrolled(t))return!1;r=t.deltaY<0?0:1,s=4;break;default:return!1}return!(void 0===r||void 0===s||s>4)&&e.coreMouseService.triggerMouseEvent({col:i.col,row:i.row,x:i.x,y:i.y,button:s,action:r,ctrl:t.ctrlKey,alt:t.altKey,shift:t.shiftKey})}const s={mouseup:null,wheel:null,mousedrag:null,mousemove:null},n={mouseup:e=>(i(e),e.buttons||(this._document.removeEventListener("mouseup",s.mouseup),s.mousedrag&&this._document.removeEventListener("mousemove",s.mousedrag)),this.cancel(e)),wheel:e=>(i(e),this.cancel(e,!0)),mousedrag:e=>{e.buttons&&i(e)},mousemove:e=>{e.buttons||i(e)}};this.register(this.coreMouseService.onProtocolChange((e=>{e?("debug"===this.optionsService.rawOptions.logLevel&&this._logService.debug("Binding to mouse events:",this.coreMouseService.explainEvents(e)),this.element.classList.add("enable-mouse-events"),this._selectionService.disable()):(this._logService.debug("Unbinding from mouse events."),this.element.classList.remove("enable-mouse-events"),this._selectionService.enable()),8&e?s.mousemove||(t.addEventListener("mousemove",n.mousemove),s.mousemove=n.mousemove):(t.removeEventListener("mousemove",s.mousemove),s.mousemove=null),16&e?s.wheel||(t.addEventListener("wheel",n.wheel,{passive:!1}),s.wheel=n.wheel):(t.removeEventListener("wheel",s.wheel),s.wheel=null),2&e?s.mouseup||(s.mouseup=n.mouseup):(this._document.removeEventListener("mouseup",s.mouseup),s.mouseup=null),4&e?s.mousedrag||(s.mousedrag=n.mousedrag):(this._document.removeEventListener("mousemove",s.mousedrag),s.mousedrag=null)}))),this.coreMouseService.activeProtocol=this.coreMouseService.activeProtocol,this.register((0,r.addDisposableDomListener)(t,"mousedown",(e=>{if(e.preventDefault(),this.focus(),this.coreMouseService.areMouseEventsActive&&!this._selectionService.shouldForceSelection(e))return i(e),s.mouseup&&this._document.addEventListener("mouseup",s.mouseup),s.mousedrag&&this._document.addEventListener("mousemove",s.mousedrag),this.cancel(e)}))),this.register((0,r.addDisposableDomListener)(t,"wheel",(e=>{if(!s.wheel){if(this._customWheelEventHandler&&!1===this._customWheelEventHandler(e))return!1;if(!this.buffer.hasScrollback){const t=this.viewport.getLinesScrolled(e);if(0===t)return;const i=D.C0.ESC+(this.coreService.decPrivateModes.applicationCursorKeys?"O":"[")+(e.deltaY<0?"A":"B");let s="";for(let e=0;e<Math.abs(t);e++)s+=i;return this.coreService.triggerDataEvent(s,!0),this.cancel(e,!0)}return this.viewport.handleWheel(e)?this.cancel(e):void 0}}),{passive:!1})),this.register((0,r.addDisposableDomListener)(t,"touchstart",(e=>{if(!this.coreMouseService.areMouseEventsActive)return this.viewport.handleTouchStart(e),this.cancel(e)}),{passive:!0})),this.register((0,r.addDisposableDomListener)(t,"touchmove",(e=>{if(!this.coreMouseService.areMouseEventsActive)return this.viewport.handleTouchMove(e)?void 0:this.cancel(e)}),{passive:!1}))}refresh(e,t){this._renderService?.refreshRows(e,t)}updateCursorStyle(e){this._selectionService?.shouldColumnSelect(e)?this.element.classList.add("column-select"):this.element.classList.remove("column-select")}_showCursor(){this.coreService.isCursorInitialized||(this.coreService.isCursorInitialized=!0,this.refresh(this.buffer.y,this.buffer.y))}scrollLines(e,t,i=0){1===i?(super.scrollLines(e,t,i),this.refresh(0,this.rows-1)):this.viewport?.scrollLines(e)}paste(e){(0,s.paste)(e,this.textarea,this.coreService,this.optionsService)}attachCustomKeyEventHandler(e){this._customKeyEventHandler=e}attachCustomWheelEventHandler(e){this._customWheelEventHandler=e}registerLinkProvider(e){return this._linkProviderService.registerLinkProvider(e)}registerCharacterJoiner(e){if(!this._characterJoinerService)throw new Error("Terminal must be opened first");const t=this._characterJoinerService.register(e);return this.refresh(0,this.rows-1),t}deregisterCharacterJoiner(e){if(!this._characterJoinerService)throw new Error("Terminal must be opened first");this._characterJoinerService.deregister(e)&&this.refresh(0,this.rows-1)}get markers(){return this.buffer.markers}registerMarker(e){return this.buffer.addMarker(this.buffer.ybase+this.buffer.y+e)}registerDecoration(e){return this._decorationService.registerDecoration(e)}hasSelection(){return!!this._selectionService&&this._selectionService.hasSelection}select(e,t,i){this._selectionService.setSelection(e,t,i)}getSelection(){return this._selectionService?this._selectionService.selectionText:""}getSelectionPosition(){if(this._selectionService&&this._selectionService.hasSelection)return{start:{x:this._selectionService.selectionStart[0],y:this._selectionService.selectionStart[1]},end:{x:this._selectionService.selectionEnd[0],y:this._selectionService.selectionEnd[1]}}}clearSelection(){this._selectionService?.clearSelection()}selectAll(){this._selectionService?.selectAll()}selectLines(e,t){this._selectionService?.selectLines(e,t)}_keyDown(e){if(this._keyDownHandled=!1,this._keyDownSeen=!0,this._customKeyEventHandler&&!1===this._customKeyEventHandler(e))return!1;const t=this.browser.isMac&&this.options.macOptionIsMeta&&e.altKey;if(!t&&!this._compositionHelper.keydown(e))return this.options.scrollOnUserInput&&this.buffer.ybase!==this.buffer.ydisp&&this.scrollToBottom(),!1;t||"Dead"!==e.key&&"AltGraph"!==e.key||(this._unprocessedDeadKey=!0);const i=(0,R.evaluateKeyboardEvent)(e,this.coreService.decPrivateModes.applicationCursorKeys,this.browser.isMac,this.options.macOptionIsMeta);if(this.updateCursorStyle(e),3===i.type||2===i.type){const t=this.rows-1;return this.scrollLines(2===i.type?-t:t),this.cancel(e,!0)}return 1===i.type&&this.selectAll(),!!this._isThirdLevelShift(this.browser,e)||(i.cancel&&this.cancel(e,!0),!i.key||!!(e.key&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&1===e.key.length&&e.key.charCodeAt(0)>=65&&e.key.charCodeAt(0)<=90)||(this._unprocessedDeadKey?(this._unprocessedDeadKey=!1,!0):(i.key!==D.C0.ETX&&i.key!==D.C0.CR||(this.textarea.value=""),this._onKey.fire({key:i.key,domEvent:e}),this._showCursor(),this.coreService.triggerDataEvent(i.key,!0),!this.optionsService.rawOptions.screenReaderMode||e.altKey||e.ctrlKey?this.cancel(e,!0):void(this._keyDownHandled=!0))))}_isThirdLevelShift(e,t){const i=e.isMac&&!this.options.macOptionIsMeta&&t.altKey&&!t.ctrlKey&&!t.metaKey||e.isWindows&&t.altKey&&t.ctrlKey&&!t.metaKey||e.isWindows&&t.getModifierState("AltGraph");return"keypress"===t.type?i:i&&(!t.keyCode||t.keyCode>47)}_keyUp(e){this._keyDownSeen=!1,this._customKeyEventHandler&&!1===this._customKeyEventHandler(e)||(function(e){return 16===e.keyCode||17===e.keyCode||18===e.keyCode}(e)||this.focus(),this.updateCursorStyle(e),this._keyPressHandled=!1)}_keyPress(e){let t;if(this._keyPressHandled=!1,this._keyDownHandled)return!1;if(this._customKeyEventHandler&&!1===this._customKeyEventHandler(e))return!1;if(this.cancel(e),e.charCode)t=e.charCode;else if(null===e.which||void 0===e.which)t=e.keyCode;else{if(0===e.which||0===e.charCode)return!1;t=e.which}return!(!t||(e.altKey||e.ctrlKey||e.metaKey)&&!this._isThirdLevelShift(this.browser,e)||(t=String.fromCharCode(t),this._onKey.fire({key:t,domEvent:e}),this._showCursor(),this.coreService.triggerDataEvent(t,!0),this._keyPressHandled=!0,this._unprocessedDeadKey=!1,0))}_inputEvent(e){if(e.data&&"insertText"===e.inputType&&(!e.composed||!this._keyDownSeen)&&!this.optionsService.rawOptions.screenReaderMode){if(this._keyPressHandled)return!1;this._unprocessedDeadKey=!1;const t=e.data;return this.coreService.triggerDataEvent(t,!0),this.cancel(e),!0}return!1}resize(e,t){e!==this.cols||t!==this.rows?super.resize(e,t):this._charSizeService&&!this._charSizeService.hasValidSize&&this._charSizeService.measure()}_afterResize(e,t){this._charSizeService?.measure(),this.viewport?.syncScrollArea(!0)}clear(){if(0!==this.buffer.ybase||0!==this.buffer.y){this.buffer.clearAllMarkers(),this.buffer.lines.set(0,this.buffer.lines.get(this.buffer.ybase+this.buffer.y)),this.buffer.lines.length=1,this.buffer.ydisp=0,this.buffer.ybase=0,this.buffer.y=0;for(let e=1;e<this.rows;e++)this.buffer.lines.push(this.buffer.getBlankLine(L.DEFAULT_ATTR_DATA));this._onScroll.fire({position:this.buffer.ydisp,source:0}),this.viewport?.reset(),this.refresh(0,this.rows-1)}}reset(){this.options.rows=this.rows,this.options.cols=this.cols;const e=this._customKeyEventHandler;this._setup(),super.reset(),this._selectionService?.reset(),this._decorationService.reset(),this.viewport?.reset(),this._customKeyEventHandler=e,this.refresh(0,this.rows-1)}clearTextureAtlas(){this._renderService?.clearTextureAtlas()}_reportFocus(){this.element?.classList.contains("focus")?this.coreService.triggerDataEvent(D.C0.ESC+"[I"):this.coreService.triggerDataEvent(D.C0.ESC+"[O")}_reportWindowsOptions(e){if(this._renderService)switch(e){case T.WindowsOptionsReportType.GET_WIN_SIZE_PIXELS:const e=this._renderService.dimensions.css.canvas.width.toFixed(0),t=this._renderService.dimensions.css.canvas.height.toFixed(0);this.coreService.triggerDataEvent(`${D.C0.ESC}[4;${t};${e}t`);break;case T.WindowsOptionsReportType.GET_CELL_SIZE_PIXELS:const i=this._renderService.dimensions.css.cell.width.toFixed(0),s=this._renderService.dimensions.css.cell.height.toFixed(0);this.coreService.triggerDataEvent(`${D.C0.ESC}[6;${s};${i}t`)}}cancel(e,t){if(this.options.cancelEvents||t)return e.preventDefault(),e.stopPropagation(),!1}}t.Terminal=P},9924:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.TimeBasedDebouncer=void 0,t.TimeBasedDebouncer=class{constructor(e,t=1e3){this._renderCallback=e,this._debounceThresholdMS=t,this._lastRefreshMs=0,this._additionalRefreshRequested=!1}dispose(){this._refreshTimeoutID&&clearTimeout(this._refreshTimeoutID)}refresh(e,t,i){this._rowCount=i,e=void 0!==e?e:0,t=void 0!==t?t:this._rowCount-1,this._rowStart=void 0!==this._rowStart?Math.min(this._rowStart,e):e,this._rowEnd=void 0!==this._rowEnd?Math.max(this._rowEnd,t):t;const s=Date.now();if(s-this._lastRefreshMs>=this._debounceThresholdMS)this._lastRefreshMs=s,this._innerRefresh();else if(!this._additionalRefreshRequested){const e=s-this._lastRefreshMs,t=this._debounceThresholdMS-e;this._additionalRefreshRequested=!0,this._refreshTimeoutID=window.setTimeout((()=>{this._lastRefreshMs=Date.now(),this._innerRefresh(),this._additionalRefreshRequested=!1,this._refreshTimeoutID=void 0}),t)}}_innerRefresh(){if(void 0===this._rowStart||void 0===this._rowEnd||void 0===this._rowCount)return;const e=Math.max(this._rowStart,0),t=Math.min(this._rowEnd,this._rowCount-1);this._rowStart=void 0,this._rowEnd=void 0,this._renderCallback(e,t)}}},1680:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.Viewport=void 0;const n=i(3656),o=i(4725),a=i(8460),h=i(844),c=i(2585);let l=t.Viewport=class extends h.Disposable{constructor(e,t,i,s,r,o,h,c){super(),this._viewportElement=e,this._scrollArea=t,this._bufferService=i,this._optionsService=s,this._charSizeService=r,this._renderService=o,this._coreBrowserService=h,this.scrollBarWidth=0,this._currentRowHeight=0,this._currentDeviceCellHeight=0,this._lastRecordedBufferLength=0,this._lastRecordedViewportHeight=0,this._lastRecordedBufferHeight=0,this._lastTouchY=0,this._lastScrollTop=0,this._wheelPartialScroll=0,this._refreshAnimationFrame=null,this._ignoreNextScrollEvent=!1,this._smoothScrollState={startTime:0,origin:-1,target:-1},this._onRequestScrollLines=this.register(new a.EventEmitter),this.onRequestScrollLines=this._onRequestScrollLines.event,this.scrollBarWidth=this._viewportElement.offsetWidth-this._scrollArea.offsetWidth||15,this.register((0,n.addDisposableDomListener)(this._viewportElement,"scroll",this._handleScroll.bind(this))),this._activeBuffer=this._bufferService.buffer,this.register(this._bufferService.buffers.onBufferActivate((e=>this._activeBuffer=e.activeBuffer))),this._renderDimensions=this._renderService.dimensions,this.register(this._renderService.onDimensionsChange((e=>this._renderDimensions=e))),this._handleThemeChange(c.colors),this.register(c.onChangeColors((e=>this._handleThemeChange(e)))),this.register(this._optionsService.onSpecificOptionChange("scrollback",(()=>this.syncScrollArea()))),setTimeout((()=>this.syncScrollArea()))}_handleThemeChange(e){this._viewportElement.style.backgroundColor=e.background.css}reset(){this._currentRowHeight=0,this._currentDeviceCellHeight=0,this._lastRecordedBufferLength=0,this._lastRecordedViewportHeight=0,this._lastRecordedBufferHeight=0,this._lastTouchY=0,this._lastScrollTop=0,this._coreBrowserService.window.requestAnimationFrame((()=>this.syncScrollArea()))}_refresh(e){if(e)return this._innerRefresh(),void(null!==this._refreshAnimationFrame&&this._coreBrowserService.window.cancelAnimationFrame(this._refreshAnimationFrame));null===this._refreshAnimationFrame&&(this._refreshAnimationFrame=this._coreBrowserService.window.requestAnimationFrame((()=>this._innerRefresh())))}_innerRefresh(){if(this._charSizeService.height>0){this._currentRowHeight=this._renderDimensions.device.cell.height/this._coreBrowserService.dpr,this._currentDeviceCellHeight=this._renderDimensions.device.cell.height,this._lastRecordedViewportHeight=this._viewportElement.offsetHeight;const e=Math.round(this._currentRowHeight*this._lastRecordedBufferLength)+(this._lastRecordedViewportHeight-this._renderDimensions.css.canvas.height);this._lastRecordedBufferHeight!==e&&(this._lastRecordedBufferHeight=e,this._scrollArea.style.height=this._lastRecordedBufferHeight+"px")}const e=this._bufferService.buffer.ydisp*this._currentRowHeight;this._viewportElement.scrollTop!==e&&(this._ignoreNextScrollEvent=!0,this._viewportElement.scrollTop=e),this._refreshAnimationFrame=null}syncScrollArea(e=!1){if(this._lastRecordedBufferLength!==this._bufferService.buffer.lines.length)return this._lastRecordedBufferLength=this._bufferService.buffer.lines.length,void this._refresh(e);this._lastRecordedViewportHeight===this._renderService.dimensions.css.canvas.height&&this._lastScrollTop===this._activeBuffer.ydisp*this._currentRowHeight&&this._renderDimensions.device.cell.height===this._currentDeviceCellHeight||this._refresh(e)}_handleScroll(e){if(this._lastScrollTop=this._viewportElement.scrollTop,!this._viewportElement.offsetParent)return;if(this._ignoreNextScrollEvent)return this._ignoreNextScrollEvent=!1,void this._onRequestScrollLines.fire({amount:0,suppressScrollEvent:!0});const t=Math.round(this._lastScrollTop/this._currentRowHeight)-this._bufferService.buffer.ydisp;this._onRequestScrollLines.fire({amount:t,suppressScrollEvent:!0})}_smoothScroll(){if(this._isDisposed||-1===this._smoothScrollState.origin||-1===this._smoothScrollState.target)return;const e=this._smoothScrollPercent();this._viewportElement.scrollTop=this._smoothScrollState.origin+Math.round(e*(this._smoothScrollState.target-this._smoothScrollState.origin)),e<1?this._coreBrowserService.window.requestAnimationFrame((()=>this._smoothScroll())):this._clearSmoothScrollState()}_smoothScrollPercent(){return this._optionsService.rawOptions.smoothScrollDuration&&this._smoothScrollState.startTime?Math.max(Math.min((Date.now()-this._smoothScrollState.startTime)/this._optionsService.rawOptions.smoothScrollDuration,1),0):1}_clearSmoothScrollState(){this._smoothScrollState.startTime=0,this._smoothScrollState.origin=-1,this._smoothScrollState.target=-1}_bubbleScroll(e,t){const i=this._viewportElement.scrollTop+this._lastRecordedViewportHeight;return!(t<0&&0!==this._viewportElement.scrollTop||t>0&&i<this._lastRecordedBufferHeight)||(e.cancelable&&e.preventDefault(),!1)}handleWheel(e){const t=this._getPixelsScrolled(e);return 0!==t&&(this._optionsService.rawOptions.smoothScrollDuration?(this._smoothScrollState.startTime=Date.now(),this._smoothScrollPercent()<1?(this._smoothScrollState.origin=this._viewportElement.scrollTop,-1===this._smoothScrollState.target?this._smoothScrollState.target=this._viewportElement.scrollTop+t:this._smoothScrollState.target+=t,this._smoothScrollState.target=Math.max(Math.min(this._smoothScrollState.target,this._viewportElement.scrollHeight),0),this._smoothScroll()):this._clearSmoothScrollState()):this._viewportElement.scrollTop+=t,this._bubbleScroll(e,t))}scrollLines(e){if(0!==e)if(this._optionsService.rawOptions.smoothScrollDuration){const t=e*this._currentRowHeight;this._smoothScrollState.startTime=Date.now(),this._smoothScrollPercent()<1?(this._smoothScrollState.origin=this._viewportElement.scrollTop,this._smoothScrollState.target=this._smoothScrollState.origin+t,this._smoothScrollState.target=Math.max(Math.min(this._smoothScrollState.target,this._viewportElement.scrollHeight),0),this._smoothScroll()):this._clearSmoothScrollState()}else this._onRequestScrollLines.fire({amount:e,suppressScrollEvent:!1})}_getPixelsScrolled(e){if(0===e.deltaY||e.shiftKey)return 0;let t=this._applyScrollModifier(e.deltaY,e);return e.deltaMode===WheelEvent.DOM_DELTA_LINE?t*=this._currentRowHeight:e.deltaMode===WheelEvent.DOM_DELTA_PAGE&&(t*=this._currentRowHeight*this._bufferService.rows),t}getBufferElements(e,t){let i,s="";const r=[],n=t??this._bufferService.buffer.lines.length,o=this._bufferService.buffer.lines;for(let t=e;t<n;t++){const e=o.get(t);if(!e)continue;const n=o.get(t+1)?.isWrapped;if(s+=e.translateToString(!n),!n||t===o.length-1){const e=document.createElement("div");e.textContent=s,r.push(e),s.length>0&&(i=e),s=""}}return{bufferElements:r,cursorElement:i}}getLinesScrolled(e){if(0===e.deltaY||e.shiftKey)return 0;let t=this._applyScrollModifier(e.deltaY,e);return e.deltaMode===WheelEvent.DOM_DELTA_PIXEL?(t/=this._currentRowHeight+0,this._wheelPartialScroll+=t,t=Math.floor(Math.abs(this._wheelPartialScroll))*(this._wheelPartialScroll>0?1:-1),this._wheelPartialScroll%=1):e.deltaMode===WheelEvent.DOM_DELTA_PAGE&&(t*=this._bufferService.rows),t}_applyScrollModifier(e,t){const i=this._optionsService.rawOptions.fastScrollModifier;return"alt"===i&&t.altKey||"ctrl"===i&&t.ctrlKey||"shift"===i&&t.shiftKey?e*this._optionsService.rawOptions.fastScrollSensitivity*this._optionsService.rawOptions.scrollSensitivity:e*this._optionsService.rawOptions.scrollSensitivity}handleTouchStart(e){this._lastTouchY=e.touches[0].pageY}handleTouchMove(e){const t=this._lastTouchY-e.touches[0].pageY;return this._lastTouchY=e.touches[0].pageY,0!==t&&(this._viewportElement.scrollTop+=t,this._bubbleScroll(e,t))}};t.Viewport=l=s([r(2,c.IBufferService),r(3,c.IOptionsService),r(4,o.ICharSizeService),r(5,o.IRenderService),r(6,o.ICoreBrowserService),r(7,o.IThemeService)],l)},3107:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.BufferDecorationRenderer=void 0;const n=i(4725),o=i(844),a=i(2585);let h=t.BufferDecorationRenderer=class extends o.Disposable{constructor(e,t,i,s,r){super(),this._screenElement=e,this._bufferService=t,this._coreBrowserService=i,this._decorationService=s,this._renderService=r,this._decorationElements=new Map,this._altBufferIsActive=!1,this._dimensionsChanged=!1,this._container=document.createElement("div"),this._container.classList.add("xterm-decoration-container"),this._screenElement.appendChild(this._container),this.register(this._renderService.onRenderedViewportChange((()=>this._doRefreshDecorations()))),this.register(this._renderService.onDimensionsChange((()=>{this._dimensionsChanged=!0,this._queueRefresh()}))),this.register(this._coreBrowserService.onDprChange((()=>this._queueRefresh()))),this.register(this._bufferService.buffers.onBufferActivate((()=>{this._altBufferIsActive=this._bufferService.buffer===this._bufferService.buffers.alt}))),this.register(this._decorationService.onDecorationRegistered((()=>this._queueRefresh()))),this.register(this._decorationService.onDecorationRemoved((e=>this._removeDecoration(e)))),this.register((0,o.toDisposable)((()=>{this._container.remove(),this._decorationElements.clear()})))}_queueRefresh(){void 0===this._animationFrame&&(this._animationFrame=this._renderService.addRefreshCallback((()=>{this._doRefreshDecorations(),this._animationFrame=void 0})))}_doRefreshDecorations(){for(const e of this._decorationService.decorations)this._renderDecoration(e);this._dimensionsChanged=!1}_renderDecoration(e){this._refreshStyle(e),this._dimensionsChanged&&this._refreshXPosition(e)}_createElement(e){const t=this._coreBrowserService.mainDocument.createElement("div");t.classList.add("xterm-decoration"),t.classList.toggle("xterm-decoration-top-layer","top"===e?.options?.layer),t.style.width=`${Math.round((e.options.width||1)*this._renderService.dimensions.css.cell.width)}px`,t.style.height=(e.options.height||1)*this._renderService.dimensions.css.cell.height+"px",t.style.top=(e.marker.line-this._bufferService.buffers.active.ydisp)*this._renderService.dimensions.css.cell.height+"px",t.style.lineHeight=`${this._renderService.dimensions.css.cell.height}px`;const i=e.options.x??0;return i&&i>this._bufferService.cols&&(t.style.display="none"),this._refreshXPosition(e,t),t}_refreshStyle(e){const t=e.marker.line-this._bufferService.buffers.active.ydisp;if(t<0||t>=this._bufferService.rows)e.element&&(e.element.style.display="none",e.onRenderEmitter.fire(e.element));else{let i=this._decorationElements.get(e);i||(i=this._createElement(e),e.element=i,this._decorationElements.set(e,i),this._container.appendChild(i),e.onDispose((()=>{this._decorationElements.delete(e),i.remove()}))),i.style.top=t*this._renderService.dimensions.css.cell.height+"px",i.style.display=this._altBufferIsActive?"none":"block",e.onRenderEmitter.fire(i)}}_refreshXPosition(e,t=e.element){if(!t)return;const i=e.options.x??0;"right"===(e.options.anchor||"left")?t.style.right=i?i*this._renderService.dimensions.css.cell.width+"px":"":t.style.left=i?i*this._renderService.dimensions.css.cell.width+"px":""}_removeDecoration(e){this._decorationElements.get(e)?.remove(),this._decorationElements.delete(e),e.dispose()}};t.BufferDecorationRenderer=h=s([r(1,a.IBufferService),r(2,n.ICoreBrowserService),r(3,a.IDecorationService),r(4,n.IRenderService)],h)},5871:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ColorZoneStore=void 0,t.ColorZoneStore=class{constructor(){this._zones=[],this._zonePool=[],this._zonePoolIndex=0,this._linePadding={full:0,left:0,center:0,right:0}}get zones(){return this._zonePool.length=Math.min(this._zonePool.length,this._zones.length),this._zones}clear(){this._zones.length=0,this._zonePoolIndex=0}addDecoration(e){if(e.options.overviewRulerOptions){for(const t of this._zones)if(t.color===e.options.overviewRulerOptions.color&&t.position===e.options.overviewRulerOptions.position){if(this._lineIntersectsZone(t,e.marker.line))return;if(this._lineAdjacentToZone(t,e.marker.line,e.options.overviewRulerOptions.position))return void this._addLineToZone(t,e.marker.line)}if(this._zonePoolIndex<this._zonePool.length)return this._zonePool[this._zonePoolIndex].color=e.options.overviewRulerOptions.color,this._zonePool[this._zonePoolIndex].position=e.options.overviewRulerOptions.position,this._zonePool[this._zonePoolIndex].startBufferLine=e.marker.line,this._zonePool[this._zonePoolIndex].endBufferLine=e.marker.line,void this._zones.push(this._zonePool[this._zonePoolIndex++]);this._zones.push({color:e.options.overviewRulerOptions.color,position:e.options.overviewRulerOptions.position,startBufferLine:e.marker.line,endBufferLine:e.marker.line}),this._zonePool.push(this._zones[this._zones.length-1]),this._zonePoolIndex++}}setPadding(e){this._linePadding=e}_lineIntersectsZone(e,t){return t>=e.startBufferLine&&t<=e.endBufferLine}_lineAdjacentToZone(e,t,i){return t>=e.startBufferLine-this._linePadding[i||"full"]&&t<=e.endBufferLine+this._linePadding[i||"full"]}_addLineToZone(e,t){e.startBufferLine=Math.min(e.startBufferLine,t),e.endBufferLine=Math.max(e.endBufferLine,t)}}},5744:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.OverviewRulerRenderer=void 0;const n=i(5871),o=i(4725),a=i(844),h=i(2585),c={full:0,left:0,center:0,right:0},l={full:0,left:0,center:0,right:0},d={full:0,left:0,center:0,right:0};let _=t.OverviewRulerRenderer=class extends a.Disposable{get _width(){return this._optionsService.options.overviewRulerWidth||0}constructor(e,t,i,s,r,o,h){super(),this._viewportElement=e,this._screenElement=t,this._bufferService=i,this._decorationService=s,this._renderService=r,this._optionsService=o,this._coreBrowserService=h,this._colorZoneStore=new n.ColorZoneStore,this._shouldUpdateDimensions=!0,this._shouldUpdateAnchor=!0,this._lastKnownBufferLength=0,this._canvas=this._coreBrowserService.mainDocument.createElement("canvas"),this._canvas.classList.add("xterm-decoration-overview-ruler"),this._refreshCanvasDimensions(),this._viewportElement.parentElement?.insertBefore(this._canvas,this._viewportElement);const c=this._canvas.getContext("2d");if(!c)throw new Error("Ctx cannot be null");this._ctx=c,this._registerDecorationListeners(),this._registerBufferChangeListeners(),this._registerDimensionChangeListeners(),this.register((0,a.toDisposable)((()=>{this._canvas?.remove()})))}_registerDecorationListeners(){this.register(this._decorationService.onDecorationRegistered((()=>this._queueRefresh(void 0,!0)))),this.register(this._decorationService.onDecorationRemoved((()=>this._queueRefresh(void 0,!0))))}_registerBufferChangeListeners(){this.register(this._renderService.onRenderedViewportChange((()=>this._queueRefresh()))),this.register(this._bufferService.buffers.onBufferActivate((()=>{this._canvas.style.display=this._bufferService.buffer===this._bufferService.buffers.alt?"none":"block"}))),this.register(this._bufferService.onScroll((()=>{this._lastKnownBufferLength!==this._bufferService.buffers.normal.lines.length&&(this._refreshDrawHeightConstants(),this._refreshColorZonePadding())})))}_registerDimensionChangeListeners(){this.register(this._renderService.onRender((()=>{this._containerHeight&&this._containerHeight===this._screenElement.clientHeight||(this._queueRefresh(!0),this._containerHeight=this._screenElement.clientHeight)}))),this.register(this._optionsService.onSpecificOptionChange("overviewRulerWidth",(()=>this._queueRefresh(!0)))),this.register(this._coreBrowserService.onDprChange((()=>this._queueRefresh(!0)))),this._queueRefresh(!0)}_refreshDrawConstants(){const e=Math.floor(this._canvas.width/3),t=Math.ceil(this._canvas.width/3);l.full=this._canvas.width,l.left=e,l.center=t,l.right=e,this._refreshDrawHeightConstants(),d.full=0,d.left=0,d.center=l.left,d.right=l.left+l.center}_refreshDrawHeightConstants(){c.full=Math.round(2*this._coreBrowserService.dpr);const e=this._canvas.height/this._bufferService.buffer.lines.length,t=Math.round(Math.max(Math.min(e,12),6)*this._coreBrowserService.dpr);c.left=t,c.center=t,c.right=t}_refreshColorZonePadding(){this._colorZoneStore.setPadding({full:Math.floor(this._bufferService.buffers.active.lines.length/(this._canvas.height-1)*c.full),left:Math.floor(this._bufferService.buffers.active.lines.length/(this._canvas.height-1)*c.left),center:Math.floor(this._bufferService.buffers.active.lines.length/(this._canvas.height-1)*c.center),right:Math.floor(this._bufferService.buffers.active.lines.length/(this._canvas.height-1)*c.right)}),this._lastKnownBufferLength=this._bufferService.buffers.normal.lines.length}_refreshCanvasDimensions(){this._canvas.style.width=`${this._width}px`,this._canvas.width=Math.round(this._width*this._coreBrowserService.dpr),this._canvas.style.height=`${this._screenElement.clientHeight}px`,this._canvas.height=Math.round(this._screenElement.clientHeight*this._coreBrowserService.dpr),this._refreshDrawConstants(),this._refreshColorZonePadding()}_refreshDecorations(){this._shouldUpdateDimensions&&this._refreshCanvasDimensions(),this._ctx.clearRect(0,0,this._canvas.width,this._canvas.height),this._colorZoneStore.clear();for(const e of this._decorationService.decorations)this._colorZoneStore.addDecoration(e);this._ctx.lineWidth=1;const e=this._colorZoneStore.zones;for(const t of e)"full"!==t.position&&this._renderColorZone(t);for(const t of e)"full"===t.position&&this._renderColorZone(t);this._shouldUpdateDimensions=!1,this._shouldUpdateAnchor=!1}_renderColorZone(e){this._ctx.fillStyle=e.color,this._ctx.fillRect(d[e.position||"full"],Math.round((this._canvas.height-1)*(e.startBufferLine/this._bufferService.buffers.active.lines.length)-c[e.position||"full"]/2),l[e.position||"full"],Math.round((this._canvas.height-1)*((e.endBufferLine-e.startBufferLine)/this._bufferService.buffers.active.lines.length)+c[e.position||"full"]))}_queueRefresh(e,t){this._shouldUpdateDimensions=e||this._shouldUpdateDimensions,this._shouldUpdateAnchor=t||this._shouldUpdateAnchor,void 0===this._animationFrame&&(this._animationFrame=this._coreBrowserService.window.requestAnimationFrame((()=>{this._refreshDecorations(),this._animationFrame=void 0})))}};t.OverviewRulerRenderer=_=s([r(2,h.IBufferService),r(3,h.IDecorationService),r(4,o.IRenderService),r(5,h.IOptionsService),r(6,o.ICoreBrowserService)],_)},2950:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CompositionHelper=void 0;const n=i(4725),o=i(2585),a=i(2584);let h=t.CompositionHelper=class{get isComposing(){return this._isComposing}constructor(e,t,i,s,r,n){this._textarea=e,this._compositionView=t,this._bufferService=i,this._optionsService=s,this._coreService=r,this._renderService=n,this._isComposing=!1,this._isSendingComposition=!1,this._compositionPosition={start:0,end:0},this._dataAlreadySent=""}compositionstart(){this._isComposing=!0,this._compositionPosition.start=this._textarea.value.length,this._compositionView.textContent="",this._dataAlreadySent="",this._compositionView.classList.add("active")}compositionupdate(e){this._compositionView.textContent=e.data,this.updateCompositionElements(),setTimeout((()=>{this._compositionPosition.end=this._textarea.value.length}),0)}compositionend(){this._finalizeComposition(!0)}keydown(e){if(this._isComposing||this._isSendingComposition){if(229===e.keyCode)return!1;if(16===e.keyCode||17===e.keyCode||18===e.keyCode)return!1;this._finalizeComposition(!1)}return 229!==e.keyCode||(this._handleAnyTextareaChanges(),!1)}_finalizeComposition(e){if(this._compositionView.classList.remove("active"),this._isComposing=!1,e){const e={start:this._compositionPosition.start,end:this._compositionPosition.end};this._isSendingComposition=!0,setTimeout((()=>{if(this._isSendingComposition){let t;this._isSendingComposition=!1,e.start+=this._dataAlreadySent.length,t=this._isComposing?this._textarea.value.substring(e.start,e.end):this._textarea.value.substring(e.start),t.length>0&&this._coreService.triggerDataEvent(t,!0)}}),0)}else{this._isSendingComposition=!1;const e=this._textarea.value.substring(this._compositionPosition.start,this._compositionPosition.end);this._coreService.triggerDataEvent(e,!0)}}_handleAnyTextareaChanges(){const e=this._textarea.value;setTimeout((()=>{if(!this._isComposing){const t=this._textarea.value,i=t.replace(e,"");this._dataAlreadySent=i,t.length>e.length?this._coreService.triggerDataEvent(i,!0):t.length<e.length?this._coreService.triggerDataEvent(`${a.C0.DEL}`,!0):t.length===e.length&&t!==e&&this._coreService.triggerDataEvent(t,!0)}}),0)}updateCompositionElements(e){if(this._isComposing){if(this._bufferService.buffer.isCursorInViewport){const e=Math.min(this._bufferService.buffer.x,this._bufferService.cols-1),t=this._renderService.dimensions.css.cell.height,i=this._bufferService.buffer.y*this._renderService.dimensions.css.cell.height,s=e*this._renderService.dimensions.css.cell.width;this._compositionView.style.left=s+"px",this._compositionView.style.top=i+"px",this._compositionView.style.height=t+"px",this._compositionView.style.lineHeight=t+"px",this._compositionView.style.fontFamily=this._optionsService.rawOptions.fontFamily,this._compositionView.style.fontSize=this._optionsService.rawOptions.fontSize+"px";const r=this._compositionView.getBoundingClientRect();this._textarea.style.left=s+"px",this._textarea.style.top=i+"px",this._textarea.style.width=Math.max(r.width,1)+"px",this._textarea.style.height=Math.max(r.height,1)+"px",this._textarea.style.lineHeight=r.height+"px"}e||setTimeout((()=>this.updateCompositionElements(!0)),0)}}};t.CompositionHelper=h=s([r(2,o.IBufferService),r(3,o.IOptionsService),r(4,o.ICoreService),r(5,n.IRenderService)],h)},9806:(e,t)=>{function i(e,t,i){const s=i.getBoundingClientRect(),r=e.getComputedStyle(i),n=parseInt(r.getPropertyValue("padding-left")),o=parseInt(r.getPropertyValue("padding-top"));return[t.clientX-s.left-n,t.clientY-s.top-o]}Object.defineProperty(t,"__esModule",{value:!0}),t.getCoords=t.getCoordsRelativeToElement=void 0,t.getCoordsRelativeToElement=i,t.getCoords=function(e,t,s,r,n,o,a,h,c){if(!o)return;const l=i(e,t,s);return l?(l[0]=Math.ceil((l[0]+(c?a/2:0))/a),l[1]=Math.ceil(l[1]/h),l[0]=Math.min(Math.max(l[0],1),r+(c?1:0)),l[1]=Math.min(Math.max(l[1],1),n),l):void 0}},9504:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.moveToCellSequence=void 0;const s=i(2584);function r(e,t,i,s){const r=e-n(e,i),a=t-n(t,i),l=Math.abs(r-a)-function(e,t,i){let s=0;const r=e-n(e,i),a=t-n(t,i);for(let n=0;n<Math.abs(r-a);n++){const a="A"===o(e,t)?-1:1,h=i.buffer.lines.get(r+a*n);h?.isWrapped&&s++}return s}(e,t,i);return c(l,h(o(e,t),s))}function n(e,t){let i=0,s=t.buffer.lines.get(e),r=s?.isWrapped;for(;r&&e>=0&&e<t.rows;)i++,s=t.buffer.lines.get(--e),r=s?.isWrapped;return i}function o(e,t){return e>t?"A":"B"}function a(e,t,i,s,r,n){let o=e,a=t,h="";for(;o!==i||a!==s;)o+=r?1:-1,r&&o>n.cols-1?(h+=n.buffer.translateBufferLineToString(a,!1,e,o),o=0,e=0,a++):!r&&o<0&&(h+=n.buffer.translateBufferLineToString(a,!1,0,e+1),o=n.cols-1,e=o,a--);return h+n.buffer.translateBufferLineToString(a,!1,e,o)}function h(e,t){const i=t?"O":"[";return s.C0.ESC+i+e}function c(e,t){e=Math.floor(e);let i="";for(let s=0;s<e;s++)i+=t;return i}t.moveToCellSequence=function(e,t,i,s){const o=i.buffer.x,l=i.buffer.y;if(!i.buffer.hasScrollback)return function(e,t,i,s,o,l){return 0===r(t,s,o,l).length?"":c(a(e,t,e,t-n(t,o),!1,o).length,h("D",l))}(o,l,0,t,i,s)+r(l,t,i,s)+function(e,t,i,s,o,l){let d;d=r(t,s,o,l).length>0?s-n(s,o):t;const _=s,u=function(e,t,i,s,o,a){let h;return h=r(i,s,o,a).length>0?s-n(s,o):t,e<i&&h<=s||e>=i&&h<s?"C":"D"}(e,t,i,s,o,l);return c(a(e,d,i,_,"C"===u,o).length,h(u,l))}(o,l,e,t,i,s);let d;if(l===t)return d=o>e?"D":"C",c(Math.abs(o-e),h(d,s));d=l>t?"D":"C";const _=Math.abs(l-t);return c(function(e,t){return t.cols-e}(l>t?e:o,i)+(_-1)*i.cols+1+((l>t?o:e)-1),h(d,s))}},1296:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.DomRenderer=void 0;const n=i(3787),o=i(2550),a=i(2223),h=i(6171),c=i(6052),l=i(4725),d=i(8055),_=i(8460),u=i(844),f=i(2585),v="xterm-dom-renderer-owner-",p="xterm-rows",g="xterm-fg-",m="xterm-bg-",S="xterm-focus",C="xterm-selection";let b=1,w=t.DomRenderer=class extends u.Disposable{constructor(e,t,i,s,r,a,l,d,f,g,m,S,w){super(),this._terminal=e,this._document=t,this._element=i,this._screenElement=s,this._viewportElement=r,this._helperContainer=a,this._linkifier2=l,this._charSizeService=f,this._optionsService=g,this._bufferService=m,this._coreBrowserService=S,this._themeService=w,this._terminalClass=b++,this._rowElements=[],this._selectionRenderModel=(0,c.createSelectionRenderModel)(),this.onRequestRedraw=this.register(new _.EventEmitter).event,this._rowContainer=this._document.createElement("div"),this._rowContainer.classList.add(p),this._rowContainer.style.lineHeight="normal",this._rowContainer.setAttribute("aria-hidden","true"),this._refreshRowElements(this._bufferService.cols,this._bufferService.rows),this._selectionContainer=this._document.createElement("div"),this._selectionContainer.classList.add(C),this._selectionContainer.setAttribute("aria-hidden","true"),this.dimensions=(0,h.createRenderDimensions)(),this._updateDimensions(),this.register(this._optionsService.onOptionChange((()=>this._handleOptionsChanged()))),this.register(this._themeService.onChangeColors((e=>this._injectCss(e)))),this._injectCss(this._themeService.colors),this._rowFactory=d.createInstance(n.DomRendererRowFactory,document),this._element.classList.add(v+this._terminalClass),this._screenElement.appendChild(this._rowContainer),this._screenElement.appendChild(this._selectionContainer),this.register(this._linkifier2.onShowLinkUnderline((e=>this._handleLinkHover(e)))),this.register(this._linkifier2.onHideLinkUnderline((e=>this._handleLinkLeave(e)))),this.register((0,u.toDisposable)((()=>{this._element.classList.remove(v+this._terminalClass),this._rowContainer.remove(),this._selectionContainer.remove(),this._widthCache.dispose(),this._themeStyleElement.remove(),this._dimensionsStyleElement.remove()}))),this._widthCache=new o.WidthCache(this._document,this._helperContainer),this._widthCache.setFont(this._optionsService.rawOptions.fontFamily,this._optionsService.rawOptions.fontSize,this._optionsService.rawOptions.fontWeight,this._optionsService.rawOptions.fontWeightBold),this._setDefaultSpacing()}_updateDimensions(){const e=this._coreBrowserService.dpr;this.dimensions.device.char.width=this._charSizeService.width*e,this.dimensions.device.char.height=Math.ceil(this._charSizeService.height*e),this.dimensions.device.cell.width=this.dimensions.device.char.width+Math.round(this._optionsService.rawOptions.letterSpacing),this.dimensions.device.cell.height=Math.floor(this.dimensions.device.char.height*this._optionsService.rawOptions.lineHeight),this.dimensions.device.char.left=0,this.dimensions.device.char.top=0,this.dimensions.device.canvas.width=this.dimensions.device.cell.width*this._bufferService.cols,this.dimensions.device.canvas.height=this.dimensions.device.cell.height*this._bufferService.rows,this.dimensions.css.canvas.width=Math.round(this.dimensions.device.canvas.width/e),this.dimensions.css.canvas.height=Math.round(this.dimensions.device.canvas.height/e),this.dimensions.css.cell.width=this.dimensions.css.canvas.width/this._bufferService.cols,this.dimensions.css.cell.height=this.dimensions.css.canvas.height/this._bufferService.rows;for(const e of this._rowElements)e.style.width=`${this.dimensions.css.canvas.width}px`,e.style.height=`${this.dimensions.css.cell.height}px`,e.style.lineHeight=`${this.dimensions.css.cell.height}px`,e.style.overflow="hidden";this._dimensionsStyleElement||(this._dimensionsStyleElement=this._document.createElement("style"),this._screenElement.appendChild(this._dimensionsStyleElement));const t=`${this._terminalSelector} .${p} span { display: inline-block; height: 100%; vertical-align: top;}`;this._dimensionsStyleElement.textContent=t,this._selectionContainer.style.height=this._viewportElement.style.height,this._screenElement.style.width=`${this.dimensions.css.canvas.width}px`,this._screenElement.style.height=`${this.dimensions.css.canvas.height}px`}_injectCss(e){this._themeStyleElement||(this._themeStyleElement=this._document.createElement("style"),this._screenElement.appendChild(this._themeStyleElement));let t=`${this._terminalSelector} .${p} { color: ${e.foreground.css}; font-family: ${this._optionsService.rawOptions.fontFamily}; font-size: ${this._optionsService.rawOptions.fontSize}px; font-kerning: none; white-space: pre}`;t+=`${this._terminalSelector} .${p} .xterm-dim { color: ${d.color.multiplyOpacity(e.foreground,.5).css};}`,t+=`${this._terminalSelector} span:not(.xterm-bold) { font-weight: ${this._optionsService.rawOptions.fontWeight};}${this._terminalSelector} span.xterm-bold { font-weight: ${this._optionsService.rawOptions.fontWeightBold};}${this._terminalSelector} span.xterm-italic { font-style: italic;}`;const i=`blink_underline_${this._terminalClass}`,s=`blink_bar_${this._terminalClass}`,r=`blink_block_${this._terminalClass}`;t+=`@keyframes ${i} { 50% {  border-bottom-style: hidden; }}`,t+=`@keyframes ${s} { 50% {  box-shadow: none; }}`,t+=`@keyframes ${r} { 0% {  background-color: ${e.cursor.css};  color: ${e.cursorAccent.css}; } 50% {  background-color: inherit;  color: ${e.cursor.css}; }}`,t+=`${this._terminalSelector} .${p}.${S} .xterm-cursor.xterm-cursor-blink.xterm-cursor-underline { animation: ${i} 1s step-end infinite;}${this._terminalSelector} .${p}.${S} .xterm-cursor.xterm-cursor-blink.xterm-cursor-bar { animation: ${s} 1s step-end infinite;}${this._terminalSelector} .${p}.${S} .xterm-cursor.xterm-cursor-blink.xterm-cursor-block { animation: ${r} 1s step-end infinite;}${this._terminalSelector} .${p} .xterm-cursor.xterm-cursor-block { background-color: ${e.cursor.css}; color: ${e.cursorAccent.css};}${this._terminalSelector} .${p} .xterm-cursor.xterm-cursor-block:not(.xterm-cursor-blink) { background-color: ${e.cursor.css} !important; color: ${e.cursorAccent.css} !important;}${this._terminalSelector} .${p} .xterm-cursor.xterm-cursor-outline { outline: 1px solid ${e.cursor.css}; outline-offset: -1px;}${this._terminalSelector} .${p} .xterm-cursor.xterm-cursor-bar { box-shadow: ${this._optionsService.rawOptions.cursorWidth}px 0 0 ${e.cursor.css} inset;}${this._terminalSelector} .${p} .xterm-cursor.xterm-cursor-underline { border-bottom: 1px ${e.cursor.css}; border-bottom-style: solid; height: calc(100% - 1px);}`,t+=`${this._terminalSelector} .${C} { position: absolute; top: 0; left: 0; z-index: 1; pointer-events: none;}${this._terminalSelector}.focus .${C} div { position: absolute; background-color: ${e.selectionBackgroundOpaque.css};}${this._terminalSelector} .${C} div { position: absolute; background-color: ${e.selectionInactiveBackgroundOpaque.css};}`;for(const[i,s]of e.ansi.entries())t+=`${this._terminalSelector} .${g}${i} { color: ${s.css}; }${this._terminalSelector} .${g}${i}.xterm-dim { color: ${d.color.multiplyOpacity(s,.5).css}; }${this._terminalSelector} .${m}${i} { background-color: ${s.css}; }`;t+=`${this._terminalSelector} .${g}${a.INVERTED_DEFAULT_COLOR} { color: ${d.color.opaque(e.background).css}; }${this._terminalSelector} .${g}${a.INVERTED_DEFAULT_COLOR}.xterm-dim { color: ${d.color.multiplyOpacity(d.color.opaque(e.background),.5).css}; }${this._terminalSelector} .${m}${a.INVERTED_DEFAULT_COLOR} { background-color: ${e.foreground.css}; }`,this._themeStyleElement.textContent=t}_setDefaultSpacing(){const e=this.dimensions.css.cell.width-this._widthCache.get("W",!1,!1);this._rowContainer.style.letterSpacing=`${e}px`,this._rowFactory.defaultSpacing=e}handleDevicePixelRatioChange(){this._updateDimensions(),this._widthCache.clear(),this._setDefaultSpacing()}_refreshRowElements(e,t){for(let e=this._rowElements.length;e<=t;e++){const e=this._document.createElement("div");this._rowContainer.appendChild(e),this._rowElements.push(e)}for(;this._rowElements.length>t;)this._rowContainer.removeChild(this._rowElements.pop())}handleResize(e,t){this._refreshRowElements(e,t),this._updateDimensions(),this.handleSelectionChanged(this._selectionRenderModel.selectionStart,this._selectionRenderModel.selectionEnd,this._selectionRenderModel.columnSelectMode)}handleCharSizeChanged(){this._updateDimensions(),this._widthCache.clear(),this._setDefaultSpacing()}handleBlur(){this._rowContainer.classList.remove(S),this.renderRows(0,this._bufferService.rows-1)}handleFocus(){this._rowContainer.classList.add(S),this.renderRows(this._bufferService.buffer.y,this._bufferService.buffer.y)}handleSelectionChanged(e,t,i){if(this._selectionContainer.replaceChildren(),this._rowFactory.handleSelectionChanged(e,t,i),this.renderRows(0,this._bufferService.rows-1),!e||!t)return;this._selectionRenderModel.update(this._terminal,e,t,i);const s=this._selectionRenderModel.viewportStartRow,r=this._selectionRenderModel.viewportEndRow,n=this._selectionRenderModel.viewportCappedStartRow,o=this._selectionRenderModel.viewportCappedEndRow;if(n>=this._bufferService.rows||o<0)return;const a=this._document.createDocumentFragment();if(i){const i=e[0]>t[0];a.appendChild(this._createSelectionElement(n,i?t[0]:e[0],i?e[0]:t[0],o-n+1))}else{const i=s===n?e[0]:0,h=n===r?t[0]:this._bufferService.cols;a.appendChild(this._createSelectionElement(n,i,h));const c=o-n-1;if(a.appendChild(this._createSelectionElement(n+1,0,this._bufferService.cols,c)),n!==o){const e=r===o?t[0]:this._bufferService.cols;a.appendChild(this._createSelectionElement(o,0,e))}}this._selectionContainer.appendChild(a)}_createSelectionElement(e,t,i,s=1){const r=this._document.createElement("div"),n=t*this.dimensions.css.cell.width;let o=this.dimensions.css.cell.width*(i-t);return n+o>this.dimensions.css.canvas.width&&(o=this.dimensions.css.canvas.width-n),r.style.height=s*this.dimensions.css.cell.height+"px",r.style.top=e*this.dimensions.css.cell.height+"px",r.style.left=`${n}px`,r.style.width=`${o}px`,r}handleCursorMove(){}_handleOptionsChanged(){this._updateDimensions(),this._injectCss(this._themeService.colors),this._widthCache.setFont(this._optionsService.rawOptions.fontFamily,this._optionsService.rawOptions.fontSize,this._optionsService.rawOptions.fontWeight,this._optionsService.rawOptions.fontWeightBold),this._setDefaultSpacing()}clear(){for(const e of this._rowElements)e.replaceChildren()}renderRows(e,t){const i=this._bufferService.buffer,s=i.ybase+i.y,r=Math.min(i.x,this._bufferService.cols-1),n=this._optionsService.rawOptions.cursorBlink,o=this._optionsService.rawOptions.cursorStyle,a=this._optionsService.rawOptions.cursorInactiveStyle;for(let h=e;h<=t;h++){const e=h+i.ydisp,t=this._rowElements[h],c=i.lines.get(e);if(!t||!c)break;t.replaceChildren(...this._rowFactory.createRow(c,e,e===s,o,a,r,n,this.dimensions.css.cell.width,this._widthCache,-1,-1))}}get _terminalSelector(){return`.${v}${this._terminalClass}`}_handleLinkHover(e){this._setCellUnderline(e.x1,e.x2,e.y1,e.y2,e.cols,!0)}_handleLinkLeave(e){this._setCellUnderline(e.x1,e.x2,e.y1,e.y2,e.cols,!1)}_setCellUnderline(e,t,i,s,r,n){i<0&&(e=0),s<0&&(t=0);const o=this._bufferService.rows-1;i=Math.max(Math.min(i,o),0),s=Math.max(Math.min(s,o),0),r=Math.min(r,this._bufferService.cols);const a=this._bufferService.buffer,h=a.ybase+a.y,c=Math.min(a.x,r-1),l=this._optionsService.rawOptions.cursorBlink,d=this._optionsService.rawOptions.cursorStyle,_=this._optionsService.rawOptions.cursorInactiveStyle;for(let o=i;o<=s;++o){const u=o+a.ydisp,f=this._rowElements[o],v=a.lines.get(u);if(!f||!v)break;f.replaceChildren(...this._rowFactory.createRow(v,u,u===h,d,_,c,l,this.dimensions.css.cell.width,this._widthCache,n?o===i?e:0:-1,n?(o===s?t:r)-1:-1))}}};t.DomRenderer=w=s([r(7,f.IInstantiationService),r(8,l.ICharSizeService),r(9,f.IOptionsService),r(10,f.IBufferService),r(11,l.ICoreBrowserService),r(12,l.IThemeService)],w)},3787:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.DomRendererRowFactory=void 0;const n=i(2223),o=i(643),a=i(511),h=i(2585),c=i(8055),l=i(4725),d=i(4269),_=i(6171),u=i(3734);let f=t.DomRendererRowFactory=class{constructor(e,t,i,s,r,n,o){this._document=e,this._characterJoinerService=t,this._optionsService=i,this._coreBrowserService=s,this._coreService=r,this._decorationService=n,this._themeService=o,this._workCell=new a.CellData,this._columnSelectMode=!1,this.defaultSpacing=0}handleSelectionChanged(e,t,i){this._selectionStart=e,this._selectionEnd=t,this._columnSelectMode=i}createRow(e,t,i,s,r,a,h,l,_,f,p){const g=[],m=this._characterJoinerService.getJoinedCharacters(t),S=this._themeService.colors;let C,b=e.getNoBgTrimmedLength();i&&b<a+1&&(b=a+1);let w=0,y="",E=0,k=0,L=0,D=!1,R=0,x=!1,A=0;const B=[],T=-1!==f&&-1!==p;for(let M=0;M<b;M++){e.loadCell(M,this._workCell);let b=this._workCell.getWidth();if(0===b)continue;let O=!1,P=M,I=this._workCell;if(m.length>0&&M===m[0][0]){O=!0;const t=m.shift();I=new d.JoinedCellData(this._workCell,e.translateToString(!0,t[0],t[1]),t[1]-t[0]),P=t[1]-1,b=I.getWidth()}const H=this._isCellInSelection(M,t),F=i&&M===a,W=T&&M>=f&&M<=p;let U=!1;this._decorationService.forEachDecorationAtCell(M,t,void 0,(e=>{U=!0}));let N=I.getChars()||o.WHITESPACE_CELL_CHAR;if(" "===N&&(I.isUnderline()||I.isOverline())&&(N="\xA0"),A=b*l-_.get(N,I.isBold(),I.isItalic()),C){if(w&&(H&&x||!H&&!x&&I.bg===E)&&(H&&x&&S.selectionForeground||I.fg===k)&&I.extended.ext===L&&W===D&&A===R&&!F&&!O&&!U){I.isInvisible()?y+=o.WHITESPACE_CELL_CHAR:y+=N,w++;continue}w&&(C.textContent=y),C=this._document.createElement("span"),w=0,y=""}else C=this._document.createElement("span");if(E=I.bg,k=I.fg,L=I.extended.ext,D=W,R=A,x=H,O&&a>=M&&a<=P&&(a=M),!this._coreService.isCursorHidden&&F&&this._coreService.isCursorInitialized)if(B.push("xterm-cursor"),this._coreBrowserService.isFocused)h&&B.push("xterm-cursor-blink"),B.push("bar"===s?"xterm-cursor-bar":"underline"===s?"xterm-cursor-underline":"xterm-cursor-block");else if(r)switch(r){case"outline":B.push("xterm-cursor-outline");break;case"block":B.push("xterm-cursor-block");break;case"bar":B.push("xterm-cursor-bar");break;case"underline":B.push("xterm-cursor-underline")}if(I.isBold()&&B.push("xterm-bold"),I.isItalic()&&B.push("xterm-italic"),I.isDim()&&B.push("xterm-dim"),y=I.isInvisible()?o.WHITESPACE_CELL_CHAR:I.getChars()||o.WHITESPACE_CELL_CHAR,I.isUnderline()&&(B.push(`xterm-underline-${I.extended.underlineStyle}`)," "===y&&(y="\xA0"),!I.isUnderlineColorDefault()))if(I.isUnderlineColorRGB())C.style.textDecorationColor=`rgb(${u.AttributeData.toColorRGB(I.getUnderlineColor()).join(",")})`;else{let e=I.getUnderlineColor();this._optionsService.rawOptions.drawBoldTextInBrightColors&&I.isBold()&&e<8&&(e+=8),C.style.textDecorationColor=S.ansi[e].css}I.isOverline()&&(B.push("xterm-overline")," "===y&&(y="\xA0")),I.isStrikethrough()&&B.push("xterm-strikethrough"),W&&(C.style.textDecoration="underline");let $=I.getFgColor(),j=I.getFgColorMode(),z=I.getBgColor(),K=I.getBgColorMode();const q=!!I.isInverse();if(q){const e=$;$=z,z=e;const t=j;j=K,K=t}let V,G,X,J=!1;switch(this._decorationService.forEachDecorationAtCell(M,t,void 0,(e=>{"top"!==e.options.layer&&J||(e.backgroundColorRGB&&(K=50331648,z=e.backgroundColorRGB.rgba>>8&16777215,V=e.backgroundColorRGB),e.foregroundColorRGB&&(j=50331648,$=e.foregroundColorRGB.rgba>>8&16777215,G=e.foregroundColorRGB),J="top"===e.options.layer)})),!J&&H&&(V=this._coreBrowserService.isFocused?S.selectionBackgroundOpaque:S.selectionInactiveBackgroundOpaque,z=V.rgba>>8&16777215,K=50331648,J=!0,S.selectionForeground&&(j=50331648,$=S.selectionForeground.rgba>>8&16777215,G=S.selectionForeground)),J&&B.push("xterm-decoration-top"),K){case 16777216:case 33554432:X=S.ansi[z],B.push(`xterm-bg-${z}`);break;case 50331648:X=c.channels.toColor(z>>16,z>>8&255,255&z),this._addStyle(C,`background-color:#${v((z>>>0).toString(16),"0",6)}`);break;default:q?(X=S.foreground,B.push(`xterm-bg-${n.INVERTED_DEFAULT_COLOR}`)):X=S.background}switch(V||I.isDim()&&(V=c.color.multiplyOpacity(X,.5)),j){case 16777216:case 33554432:I.isBold()&&$<8&&this._optionsService.rawOptions.drawBoldTextInBrightColors&&($+=8),this._applyMinimumContrast(C,X,S.ansi[$],I,V,void 0)||B.push(`xterm-fg-${$}`);break;case 50331648:const e=c.channels.toColor($>>16&255,$>>8&255,255&$);this._applyMinimumContrast(C,X,e,I,V,G)||this._addStyle(C,`color:#${v($.toString(16),"0",6)}`);break;default:this._applyMinimumContrast(C,X,S.foreground,I,V,G)||q&&B.push(`xterm-fg-${n.INVERTED_DEFAULT_COLOR}`)}B.length&&(C.className=B.join(" "),B.length=0),F||O||U?C.textContent=y:w++,A!==this.defaultSpacing&&(C.style.letterSpacing=`${A}px`),g.push(C),M=P}return C&&w&&(C.textContent=y),g}_applyMinimumContrast(e,t,i,s,r,n){if(1===this._optionsService.rawOptions.minimumContrastRatio||(0,_.treatGlyphAsBackgroundColor)(s.getCode()))return!1;const o=this._getContrastCache(s);let a;if(r||n||(a=o.getColor(t.rgba,i.rgba)),void 0===a){const e=this._optionsService.rawOptions.minimumContrastRatio/(s.isDim()?2:1);a=c.color.ensureContrastRatio(r||t,n||i,e),o.setColor((r||t).rgba,(n||i).rgba,a??null)}return!!a&&(this._addStyle(e,`color:${a.css}`),!0)}_getContrastCache(e){return e.isDim()?this._themeService.colors.halfContrastCache:this._themeService.colors.contrastCache}_addStyle(e,t){e.setAttribute("style",`${e.getAttribute("style")||""}${t};`)}_isCellInSelection(e,t){const i=this._selectionStart,s=this._selectionEnd;return!(!i||!s)&&(this._columnSelectMode?i[0]<=s[0]?e>=i[0]&&t>=i[1]&&e<s[0]&&t<=s[1]:e<i[0]&&t>=i[1]&&e>=s[0]&&t<=s[1]:t>i[1]&&t<s[1]||i[1]===s[1]&&t===i[1]&&e>=i[0]&&e<s[0]||i[1]<s[1]&&t===s[1]&&e<s[0]||i[1]<s[1]&&t===i[1]&&e>=i[0])}};function v(e,t,i){for(;e.length<i;)e=t+e;return e}t.DomRendererRowFactory=f=s([r(1,l.ICharacterJoinerService),r(2,h.IOptionsService),r(3,l.ICoreBrowserService),r(4,h.ICoreService),r(5,h.IDecorationService),r(6,l.IThemeService)],f)},2550:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.WidthCache=void 0,t.WidthCache=class{constructor(e,t){this._flat=new Float32Array(256),this._font="",this._fontSize=0,this._weight="normal",this._weightBold="bold",this._measureElements=[],this._container=e.createElement("div"),this._container.classList.add("xterm-width-cache-measure-container"),this._container.setAttribute("aria-hidden","true"),this._container.style.whiteSpace="pre",this._container.style.fontKerning="none";const i=e.createElement("span");i.classList.add("xterm-char-measure-element");const s=e.createElement("span");s.classList.add("xterm-char-measure-element"),s.style.fontWeight="bold";const r=e.createElement("span");r.classList.add("xterm-char-measure-element"),r.style.fontStyle="italic";const n=e.createElement("span");n.classList.add("xterm-char-measure-element"),n.style.fontWeight="bold",n.style.fontStyle="italic",this._measureElements=[i,s,r,n],this._container.appendChild(i),this._container.appendChild(s),this._container.appendChild(r),this._container.appendChild(n),t.appendChild(this._container),this.clear()}dispose(){this._container.remove(),this._measureElements.length=0,this._holey=void 0}clear(){this._flat.fill(-9999),this._holey=new Map}setFont(e,t,i,s){e===this._font&&t===this._fontSize&&i===this._weight&&s===this._weightBold||(this._font=e,this._fontSize=t,this._weight=i,this._weightBold=s,this._container.style.fontFamily=this._font,this._container.style.fontSize=`${this._fontSize}px`,this._measureElements[0].style.fontWeight=`${i}`,this._measureElements[1].style.fontWeight=`${s}`,this._measureElements[2].style.fontWeight=`${i}`,this._measureElements[3].style.fontWeight=`${s}`,this.clear())}get(e,t,i){let s=0;if(!t&&!i&&1===e.length&&(s=e.charCodeAt(0))<256){if(-9999!==this._flat[s])return this._flat[s];const t=this._measure(e,0);return t>0&&(this._flat[s]=t),t}let r=e;t&&(r+="B"),i&&(r+="I");let n=this._holey.get(r);if(void 0===n){let s=0;t&&(s|=1),i&&(s|=2),n=this._measure(e,s),n>0&&this._holey.set(r,n)}return n}_measure(e,t){const i=this._measureElements[t];return i.textContent=e.repeat(32),i.offsetWidth/32}}},2223:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.TEXT_BASELINE=t.DIM_OPACITY=t.INVERTED_DEFAULT_COLOR=void 0;const s=i(6114);t.INVERTED_DEFAULT_COLOR=257,t.DIM_OPACITY=.5,t.TEXT_BASELINE=s.isFirefox||s.isLegacyEdge?"bottom":"ideographic"},6171:(e,t)=>{function i(e){return 57508<=e&&e<=57558}function s(e){return e>=128512&&e<=128591||e>=127744&&e<=128511||e>=128640&&e<=128767||e>=9728&&e<=9983||e>=9984&&e<=10175||e>=65024&&e<=65039||e>=129280&&e<=129535||e>=127462&&e<=127487}Object.defineProperty(t,"__esModule",{value:!0}),t.computeNextVariantOffset=t.createRenderDimensions=t.treatGlyphAsBackgroundColor=t.allowRescaling=t.isEmoji=t.isRestrictedPowerlineGlyph=t.isPowerlineGlyph=t.throwIfFalsy=void 0,t.throwIfFalsy=function(e){if(!e)throw new Error("value must not be falsy");return e},t.isPowerlineGlyph=i,t.isRestrictedPowerlineGlyph=function(e){return 57520<=e&&e<=57527},t.isEmoji=s,t.allowRescaling=function(e,t,r,n){return 1===t&&r>Math.ceil(1.5*n)&&void 0!==e&&e>255&&!s(e)&&!i(e)&&!function(e){return 57344<=e&&e<=63743}(e)},t.treatGlyphAsBackgroundColor=function(e){return i(e)||function(e){return 9472<=e&&e<=9631}(e)},t.createRenderDimensions=function(){return{css:{canvas:{width:0,height:0},cell:{width:0,height:0}},device:{canvas:{width:0,height:0},cell:{width:0,height:0},char:{width:0,height:0,left:0,top:0}}}},t.computeNextVariantOffset=function(e,t,i=0){return(e-(2*Math.round(t)-i))%(2*Math.round(t))}},6052:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.createSelectionRenderModel=void 0;class i{constructor(){this.clear()}clear(){this.hasSelection=!1,this.columnSelectMode=!1,this.viewportStartRow=0,this.viewportEndRow=0,this.viewportCappedStartRow=0,this.viewportCappedEndRow=0,this.startCol=0,this.endCol=0,this.selectionStart=void 0,this.selectionEnd=void 0}update(e,t,i,s=!1){if(this.selectionStart=t,this.selectionEnd=i,!t||!i||t[0]===i[0]&&t[1]===i[1])return void this.clear();const r=e.buffers.active.ydisp,n=t[1]-r,o=i[1]-r,a=Math.max(n,0),h=Math.min(o,e.rows-1);a>=e.rows||h<0?this.clear():(this.hasSelection=!0,this.columnSelectMode=s,this.viewportStartRow=n,this.viewportEndRow=o,this.viewportCappedStartRow=a,this.viewportCappedEndRow=h,this.startCol=t[0],this.endCol=i[0])}isCellSelected(e,t,i){return!!this.hasSelection&&(i-=e.buffer.active.viewportY,this.columnSelectMode?this.startCol<=this.endCol?t>=this.startCol&&i>=this.viewportCappedStartRow&&t<this.endCol&&i<=this.viewportCappedEndRow:t<this.startCol&&i>=this.viewportCappedStartRow&&t>=this.endCol&&i<=this.viewportCappedEndRow:i>this.viewportStartRow&&i<this.viewportEndRow||this.viewportStartRow===this.viewportEndRow&&i===this.viewportStartRow&&t>=this.startCol&&t<this.endCol||this.viewportStartRow<this.viewportEndRow&&i===this.viewportEndRow&&t<this.endCol||this.viewportStartRow<this.viewportEndRow&&i===this.viewportStartRow&&t>=this.startCol)}}t.createSelectionRenderModel=function(){return new i}},456:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.SelectionModel=void 0,t.SelectionModel=class{constructor(e){this._bufferService=e,this.isSelectAllActive=!1,this.selectionStartLength=0}clearSelection(){this.selectionStart=void 0,this.selectionEnd=void 0,this.isSelectAllActive=!1,this.selectionStartLength=0}get finalSelectionStart(){return this.isSelectAllActive?[0,0]:this.selectionEnd&&this.selectionStart&&this.areSelectionValuesReversed()?this.selectionEnd:this.selectionStart}get finalSelectionEnd(){if(this.isSelectAllActive)return[this._bufferService.cols,this._bufferService.buffer.ybase+this._bufferService.rows-1];if(this.selectionStart){if(!this.selectionEnd||this.areSelectionValuesReversed()){const e=this.selectionStart[0]+this.selectionStartLength;return e>this._bufferService.cols?e%this._bufferService.cols==0?[this._bufferService.cols,this.selectionStart[1]+Math.floor(e/this._bufferService.cols)-1]:[e%this._bufferService.cols,this.selectionStart[1]+Math.floor(e/this._bufferService.cols)]:[e,this.selectionStart[1]]}if(this.selectionStartLength&&this.selectionEnd[1]===this.selectionStart[1]){const e=this.selectionStart[0]+this.selectionStartLength;return e>this._bufferService.cols?[e%this._bufferService.cols,this.selectionStart[1]+Math.floor(e/this._bufferService.cols)]:[Math.max(e,this.selectionEnd[0]),this.selectionEnd[1]]}return this.selectionEnd}}areSelectionValuesReversed(){const e=this.selectionStart,t=this.selectionEnd;return!(!e||!t)&&(e[1]>t[1]||e[1]===t[1]&&e[0]>t[0])}handleTrim(e){return this.selectionStart&&(this.selectionStart[1]-=e),this.selectionEnd&&(this.selectionEnd[1]-=e),this.selectionEnd&&this.selectionEnd[1]<0?(this.clearSelection(),!0):(this.selectionStart&&this.selectionStart[1]<0&&(this.selectionStart[1]=0),!1)}}},428:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CharSizeService=void 0;const n=i(2585),o=i(8460),a=i(844);let h=t.CharSizeService=class extends a.Disposable{get hasValidSize(){return this.width>0&&this.height>0}constructor(e,t,i){super(),this._optionsService=i,this.width=0,this.height=0,this._onCharSizeChange=this.register(new o.EventEmitter),this.onCharSizeChange=this._onCharSizeChange.event;try{this._measureStrategy=this.register(new d(this._optionsService))}catch{this._measureStrategy=this.register(new l(e,t,this._optionsService))}this.register(this._optionsService.onMultipleOptionChange(["fontFamily","fontSize"],(()=>this.measure())))}measure(){const e=this._measureStrategy.measure();e.width===this.width&&e.height===this.height||(this.width=e.width,this.height=e.height,this._onCharSizeChange.fire())}};t.CharSizeService=h=s([r(2,n.IOptionsService)],h);class c extends a.Disposable{constructor(){super(...arguments),this._result={width:0,height:0}}_validateAndSet(e,t){void 0!==e&&e>0&&void 0!==t&&t>0&&(this._result.width=e,this._result.height=t)}}class l extends c{constructor(e,t,i){super(),this._document=e,this._parentElement=t,this._optionsService=i,this._measureElement=this._document.createElement("span"),this._measureElement.classList.add("xterm-char-measure-element"),this._measureElement.textContent="W".repeat(32),this._measureElement.setAttribute("aria-hidden","true"),this._measureElement.style.whiteSpace="pre",this._measureElement.style.fontKerning="none",this._parentElement.appendChild(this._measureElement)}measure(){return this._measureElement.style.fontFamily=this._optionsService.rawOptions.fontFamily,this._measureElement.style.fontSize=`${this._optionsService.rawOptions.fontSize}px`,this._validateAndSet(Number(this._measureElement.offsetWidth)/32,Number(this._measureElement.offsetHeight)),this._result}}class d extends c{constructor(e){super(),this._optionsService=e,this._canvas=new OffscreenCanvas(100,100),this._ctx=this._canvas.getContext("2d");const t=this._ctx.measureText("W");if(!("width"in t&&"fontBoundingBoxAscent"in t&&"fontBoundingBoxDescent"in t))throw new Error("Required font metrics not supported")}measure(){this._ctx.font=`${this._optionsService.rawOptions.fontSize}px ${this._optionsService.rawOptions.fontFamily}`;const e=this._ctx.measureText("W");return this._validateAndSet(e.width,e.fontBoundingBoxAscent+e.fontBoundingBoxDescent),this._result}}},4269:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CharacterJoinerService=t.JoinedCellData=void 0;const n=i(3734),o=i(643),a=i(511),h=i(2585);class c extends n.AttributeData{constructor(e,t,i){super(),this.content=0,this.combinedData="",this.fg=e.fg,this.bg=e.bg,this.combinedData=t,this._width=i}isCombined(){return 2097152}getWidth(){return this._width}getChars(){return this.combinedData}getCode(){return 2097151}setFromCharData(e){throw new Error("not implemented")}getAsCharData(){return[this.fg,this.getChars(),this.getWidth(),this.getCode()]}}t.JoinedCellData=c;let l=t.CharacterJoinerService=class e{constructor(e){this._bufferService=e,this._characterJoiners=[],this._nextCharacterJoinerId=0,this._workCell=new a.CellData}register(e){const t={id:this._nextCharacterJoinerId++,handler:e};return this._characterJoiners.push(t),t.id}deregister(e){for(let t=0;t<this._characterJoiners.length;t++)if(this._characterJoiners[t].id===e)return this._characterJoiners.splice(t,1),!0;return!1}getJoinedCharacters(e){if(0===this._characterJoiners.length)return[];const t=this._bufferService.buffer.lines.get(e);if(!t||0===t.length)return[];const i=[],s=t.translateToString(!0);let r=0,n=0,a=0,h=t.getFg(0),c=t.getBg(0);for(let e=0;e<t.getTrimmedLength();e++)if(t.loadCell(e,this._workCell),0!==this._workCell.getWidth()){if(this._workCell.fg!==h||this._workCell.bg!==c){if(e-r>1){const e=this._getJoinedRanges(s,a,n,t,r);for(let t=0;t<e.length;t++)i.push(e[t])}r=e,a=n,h=this._workCell.fg,c=this._workCell.bg}n+=this._workCell.getChars().length||o.WHITESPACE_CELL_CHAR.length}if(this._bufferService.cols-r>1){const e=this._getJoinedRanges(s,a,n,t,r);for(let t=0;t<e.length;t++)i.push(e[t])}return i}_getJoinedRanges(t,i,s,r,n){const o=t.substring(i,s);let a=[];try{a=this._characterJoiners[0].handler(o)}catch(e){console.error(e)}for(let t=1;t<this._characterJoiners.length;t++)try{const i=this._characterJoiners[t].handler(o);for(let t=0;t<i.length;t++)e._mergeRanges(a,i[t])}catch(e){console.error(e)}return this._stringRangesToCellRanges(a,r,n),a}_stringRangesToCellRanges(e,t,i){let s=0,r=!1,n=0,a=e[s];if(a){for(let h=i;h<this._bufferService.cols;h++){const i=t.getWidth(h),c=t.getString(h).length||o.WHITESPACE_CELL_CHAR.length;if(0!==i){if(!r&&a[0]<=n&&(a[0]=h,r=!0),a[1]<=n){if(a[1]=h,a=e[++s],!a)break;a[0]<=n?(a[0]=h,r=!0):r=!1}n+=c}}a&&(a[1]=this._bufferService.cols)}}static _mergeRanges(e,t){let i=!1;for(let s=0;s<e.length;s++){const r=e[s];if(i){if(t[1]<=r[0])return e[s-1][1]=t[1],e;if(t[1]<=r[1])return e[s-1][1]=Math.max(t[1],r[1]),e.splice(s,1),e;e.splice(s,1),s--}else{if(t[1]<=r[0])return e.splice(s,0,t),e;if(t[1]<=r[1])return r[0]=Math.min(t[0],r[0]),e;t[0]<r[1]&&(r[0]=Math.min(t[0],r[0]),i=!0)}}return i?e[e.length-1][1]=t[1]:e.push(t),e}};t.CharacterJoinerService=l=s([r(0,h.IBufferService)],l)},5114:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CoreBrowserService=void 0;const s=i(844),r=i(8460),n=i(3656);class o extends s.Disposable{constructor(e,t,i){super(),this._textarea=e,this._window=t,this.mainDocument=i,this._isFocused=!1,this._cachedIsFocused=void 0,this._screenDprMonitor=new a(this._window),this._onDprChange=this.register(new r.EventEmitter),this.onDprChange=this._onDprChange.event,this._onWindowChange=this.register(new r.EventEmitter),this.onWindowChange=this._onWindowChange.event,this.register(this.onWindowChange((e=>this._screenDprMonitor.setWindow(e)))),this.register((0,r.forwardEvent)(this._screenDprMonitor.onDprChange,this._onDprChange)),this._textarea.addEventListener("focus",(()=>this._isFocused=!0)),this._textarea.addEventListener("blur",(()=>this._isFocused=!1))}get window(){return this._window}set window(e){this._window!==e&&(this._window=e,this._onWindowChange.fire(this._window))}get dpr(){return this.window.devicePixelRatio}get isFocused(){return void 0===this._cachedIsFocused&&(this._cachedIsFocused=this._isFocused&&this._textarea.ownerDocument.hasFocus(),queueMicrotask((()=>this._cachedIsFocused=void 0))),this._cachedIsFocused}}t.CoreBrowserService=o;class a extends s.Disposable{constructor(e){super(),this._parentWindow=e,this._windowResizeListener=this.register(new s.MutableDisposable),this._onDprChange=this.register(new r.EventEmitter),this.onDprChange=this._onDprChange.event,this._outerListener=()=>this._setDprAndFireIfDiffers(),this._currentDevicePixelRatio=this._parentWindow.devicePixelRatio,this._updateDpr(),this._setWindowResizeListener(),this.register((0,s.toDisposable)((()=>this.clearListener())))}setWindow(e){this._parentWindow=e,this._setWindowResizeListener(),this._setDprAndFireIfDiffers()}_setWindowResizeListener(){this._windowResizeListener.value=(0,n.addDisposableDomListener)(this._parentWindow,"resize",(()=>this._setDprAndFireIfDiffers()))}_setDprAndFireIfDiffers(){this._parentWindow.devicePixelRatio!==this._currentDevicePixelRatio&&this._onDprChange.fire(this._parentWindow.devicePixelRatio),this._updateDpr()}_updateDpr(){this._outerListener&&(this._resolutionMediaMatchList?.removeListener(this._outerListener),this._currentDevicePixelRatio=this._parentWindow.devicePixelRatio,this._resolutionMediaMatchList=this._parentWindow.matchMedia(`screen and (resolution: ${this._parentWindow.devicePixelRatio}dppx)`),this._resolutionMediaMatchList.addListener(this._outerListener))}clearListener(){this._resolutionMediaMatchList&&this._outerListener&&(this._resolutionMediaMatchList.removeListener(this._outerListener),this._resolutionMediaMatchList=void 0,this._outerListener=void 0)}}},779:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.LinkProviderService=void 0;const s=i(844);class r extends s.Disposable{constructor(){super(),this.linkProviders=[],this.register((0,s.toDisposable)((()=>this.linkProviders.length=0)))}registerLinkProvider(e){return this.linkProviders.push(e),{dispose:()=>{const t=this.linkProviders.indexOf(e);-1!==t&&this.linkProviders.splice(t,1)}}}}t.LinkProviderService=r},8934:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.MouseService=void 0;const n=i(4725),o=i(9806);let a=t.MouseService=class{constructor(e,t){this._renderService=e,this._charSizeService=t}getCoords(e,t,i,s,r){return(0,o.getCoords)(window,e,t,i,s,this._charSizeService.hasValidSize,this._renderService.dimensions.css.cell.width,this._renderService.dimensions.css.cell.height,r)}getMouseReportCoords(e,t){const i=(0,o.getCoordsRelativeToElement)(window,e,t);if(this._charSizeService.hasValidSize)return i[0]=Math.min(Math.max(i[0],0),this._renderService.dimensions.css.canvas.width-1),i[1]=Math.min(Math.max(i[1],0),this._renderService.dimensions.css.canvas.height-1),{col:Math.floor(i[0]/this._renderService.dimensions.css.cell.width),row:Math.floor(i[1]/this._renderService.dimensions.css.cell.height),x:Math.floor(i[0]),y:Math.floor(i[1])}}};t.MouseService=a=s([r(0,n.IRenderService),r(1,n.ICharSizeService)],a)},3230:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.RenderService=void 0;const n=i(6193),o=i(4725),a=i(8460),h=i(844),c=i(7226),l=i(2585);let d=t.RenderService=class extends h.Disposable{get dimensions(){return this._renderer.value.dimensions}constructor(e,t,i,s,r,o,l,d){super(),this._rowCount=e,this._charSizeService=s,this._renderer=this.register(new h.MutableDisposable),this._pausedResizeTask=new c.DebouncedIdleTask,this._observerDisposable=this.register(new h.MutableDisposable),this._isPaused=!1,this._needsFullRefresh=!1,this._isNextRenderRedrawOnly=!0,this._needsSelectionRefresh=!1,this._canvasWidth=0,this._canvasHeight=0,this._selectionState={start:void 0,end:void 0,columnSelectMode:!1},this._onDimensionsChange=this.register(new a.EventEmitter),this.onDimensionsChange=this._onDimensionsChange.event,this._onRenderedViewportChange=this.register(new a.EventEmitter),this.onRenderedViewportChange=this._onRenderedViewportChange.event,this._onRender=this.register(new a.EventEmitter),this.onRender=this._onRender.event,this._onRefreshRequest=this.register(new a.EventEmitter),this.onRefreshRequest=this._onRefreshRequest.event,this._renderDebouncer=new n.RenderDebouncer(((e,t)=>this._renderRows(e,t)),l),this.register(this._renderDebouncer),this.register(l.onDprChange((()=>this.handleDevicePixelRatioChange()))),this.register(o.onResize((()=>this._fullRefresh()))),this.register(o.buffers.onBufferActivate((()=>this._renderer.value?.clear()))),this.register(i.onOptionChange((()=>this._handleOptionsChanged()))),this.register(this._charSizeService.onCharSizeChange((()=>this.handleCharSizeChanged()))),this.register(r.onDecorationRegistered((()=>this._fullRefresh()))),this.register(r.onDecorationRemoved((()=>this._fullRefresh()))),this.register(i.onMultipleOptionChange(["customGlyphs","drawBoldTextInBrightColors","letterSpacing","lineHeight","fontFamily","fontSize","fontWeight","fontWeightBold","minimumContrastRatio","rescaleOverlappingGlyphs"],(()=>{this.clear(),this.handleResize(o.cols,o.rows),this._fullRefresh()}))),this.register(i.onMultipleOptionChange(["cursorBlink","cursorStyle"],(()=>this.refreshRows(o.buffer.y,o.buffer.y,!0)))),this.register(d.onChangeColors((()=>this._fullRefresh()))),this._registerIntersectionObserver(l.window,t),this.register(l.onWindowChange((e=>this._registerIntersectionObserver(e,t))))}_registerIntersectionObserver(e,t){if("IntersectionObserver"in e){const i=new e.IntersectionObserver((e=>this._handleIntersectionChange(e[e.length-1])),{threshold:0});i.observe(t),this._observerDisposable.value=(0,h.toDisposable)((()=>i.disconnect()))}}_handleIntersectionChange(e){this._isPaused=void 0===e.isIntersecting?0===e.intersectionRatio:!e.isIntersecting,this._isPaused||this._charSizeService.hasValidSize||this._charSizeService.measure(),!this._isPaused&&this._needsFullRefresh&&(this._pausedResizeTask.flush(),this.refreshRows(0,this._rowCount-1),this._needsFullRefresh=!1)}refreshRows(e,t,i=!1){this._isPaused?this._needsFullRefresh=!0:(i||(this._isNextRenderRedrawOnly=!1),this._renderDebouncer.refresh(e,t,this._rowCount))}_renderRows(e,t){this._renderer.value&&(e=Math.min(e,this._rowCount-1),t=Math.min(t,this._rowCount-1),this._renderer.value.renderRows(e,t),this._needsSelectionRefresh&&(this._renderer.value.handleSelectionChanged(this._selectionState.start,this._selectionState.end,this._selectionState.columnSelectMode),this._needsSelectionRefresh=!1),this._isNextRenderRedrawOnly||this._onRenderedViewportChange.fire({start:e,end:t}),this._onRender.fire({start:e,end:t}),this._isNextRenderRedrawOnly=!0)}resize(e,t){this._rowCount=t,this._fireOnCanvasResize()}_handleOptionsChanged(){this._renderer.value&&(this.refreshRows(0,this._rowCount-1),this._fireOnCanvasResize())}_fireOnCanvasResize(){this._renderer.value&&(this._renderer.value.dimensions.css.canvas.width===this._canvasWidth&&this._renderer.value.dimensions.css.canvas.height===this._canvasHeight||this._onDimensionsChange.fire(this._renderer.value.dimensions))}hasRenderer(){return!!this._renderer.value}setRenderer(e){this._renderer.value=e,this._renderer.value&&(this._renderer.value.onRequestRedraw((e=>this.refreshRows(e.start,e.end,!0))),this._needsSelectionRefresh=!0,this._fullRefresh())}addRefreshCallback(e){return this._renderDebouncer.addRefreshCallback(e)}_fullRefresh(){this._isPaused?this._needsFullRefresh=!0:this.refreshRows(0,this._rowCount-1)}clearTextureAtlas(){this._renderer.value&&(this._renderer.value.clearTextureAtlas?.(),this._fullRefresh())}handleDevicePixelRatioChange(){this._charSizeService.measure(),this._renderer.value&&(this._renderer.value.handleDevicePixelRatioChange(),this.refreshRows(0,this._rowCount-1))}handleResize(e,t){this._renderer.value&&(this._isPaused?this._pausedResizeTask.set((()=>this._renderer.value?.handleResize(e,t))):this._renderer.value.handleResize(e,t),this._fullRefresh())}handleCharSizeChanged(){this._renderer.value?.handleCharSizeChanged()}handleBlur(){this._renderer.value?.handleBlur()}handleFocus(){this._renderer.value?.handleFocus()}handleSelectionChanged(e,t,i){this._selectionState.start=e,this._selectionState.end=t,this._selectionState.columnSelectMode=i,this._renderer.value?.handleSelectionChanged(e,t,i)}handleCursorMove(){this._renderer.value?.handleCursorMove()}clear(){this._renderer.value?.clear()}};t.RenderService=d=s([r(2,l.IOptionsService),r(3,o.ICharSizeService),r(4,l.IDecorationService),r(5,l.IBufferService),r(6,o.ICoreBrowserService),r(7,o.IThemeService)],d)},9312:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.SelectionService=void 0;const n=i(9806),o=i(9504),a=i(456),h=i(4725),c=i(8460),l=i(844),d=i(6114),_=i(4841),u=i(511),f=i(2585),v=String.fromCharCode(160),p=new RegExp(v,"g");let g=t.SelectionService=class extends l.Disposable{constructor(e,t,i,s,r,n,o,h,d){super(),this._element=e,this._screenElement=t,this._linkifier=i,this._bufferService=s,this._coreService=r,this._mouseService=n,this._optionsService=o,this._renderService=h,this._coreBrowserService=d,this._dragScrollAmount=0,this._enabled=!0,this._workCell=new u.CellData,this._mouseDownTimeStamp=0,this._oldHasSelection=!1,this._oldSelectionStart=void 0,this._oldSelectionEnd=void 0,this._onLinuxMouseSelection=this.register(new c.EventEmitter),this.onLinuxMouseSelection=this._onLinuxMouseSelection.event,this._onRedrawRequest=this.register(new c.EventEmitter),this.onRequestRedraw=this._onRedrawRequest.event,this._onSelectionChange=this.register(new c.EventEmitter),this.onSelectionChange=this._onSelectionChange.event,this._onRequestScrollLines=this.register(new c.EventEmitter),this.onRequestScrollLines=this._onRequestScrollLines.event,this._mouseMoveListener=e=>this._handleMouseMove(e),this._mouseUpListener=e=>this._handleMouseUp(e),this._coreService.onUserInput((()=>{this.hasSelection&&this.clearSelection()})),this._trimListener=this._bufferService.buffer.lines.onTrim((e=>this._handleTrim(e))),this.register(this._bufferService.buffers.onBufferActivate((e=>this._handleBufferActivate(e)))),this.enable(),this._model=new a.SelectionModel(this._bufferService),this._activeSelectionMode=0,this.register((0,l.toDisposable)((()=>{this._removeMouseDownListeners()})))}reset(){this.clearSelection()}disable(){this.clearSelection(),this._enabled=!1}enable(){this._enabled=!0}get selectionStart(){return this._model.finalSelectionStart}get selectionEnd(){return this._model.finalSelectionEnd}get hasSelection(){const e=this._model.finalSelectionStart,t=this._model.finalSelectionEnd;return!(!e||!t||e[0]===t[0]&&e[1]===t[1])}get selectionText(){const e=this._model.finalSelectionStart,t=this._model.finalSelectionEnd;if(!e||!t)return"";const i=this._bufferService.buffer,s=[];if(3===this._activeSelectionMode){if(e[0]===t[0])return"";const r=e[0]<t[0]?e[0]:t[0],n=e[0]<t[0]?t[0]:e[0];for(let o=e[1];o<=t[1];o++){const e=i.translateBufferLineToString(o,!0,r,n);s.push(e)}}else{const r=e[1]===t[1]?t[0]:void 0;s.push(i.translateBufferLineToString(e[1],!0,e[0],r));for(let r=e[1]+1;r<=t[1]-1;r++){const e=i.lines.get(r),t=i.translateBufferLineToString(r,!0);e?.isWrapped?s[s.length-1]+=t:s.push(t)}if(e[1]!==t[1]){const e=i.lines.get(t[1]),r=i.translateBufferLineToString(t[1],!0,0,t[0]);e&&e.isWrapped?s[s.length-1]+=r:s.push(r)}}return s.map((e=>e.replace(p," "))).join(d.isWindows?"\\r\\n":"\\n")}clearSelection(){this._model.clearSelection(),this._removeMouseDownListeners(),this.refresh(),this._onSelectionChange.fire()}refresh(e){this._refreshAnimationFrame||(this._refreshAnimationFrame=this._coreBrowserService.window.requestAnimationFrame((()=>this._refresh()))),d.isLinux&&e&&this.selectionText.length&&this._onLinuxMouseSelection.fire(this.selectionText)}_refresh(){this._refreshAnimationFrame=void 0,this._onRedrawRequest.fire({start:this._model.finalSelectionStart,end:this._model.finalSelectionEnd,columnSelectMode:3===this._activeSelectionMode})}_isClickInSelection(e){const t=this._getMouseBufferCoords(e),i=this._model.finalSelectionStart,s=this._model.finalSelectionEnd;return!!(i&&s&&t)&&this._areCoordsInSelection(t,i,s)}isCellInSelection(e,t){const i=this._model.finalSelectionStart,s=this._model.finalSelectionEnd;return!(!i||!s)&&this._areCoordsInSelection([e,t],i,s)}_areCoordsInSelection(e,t,i){return e[1]>t[1]&&e[1]<i[1]||t[1]===i[1]&&e[1]===t[1]&&e[0]>=t[0]&&e[0]<i[0]||t[1]<i[1]&&e[1]===i[1]&&e[0]<i[0]||t[1]<i[1]&&e[1]===t[1]&&e[0]>=t[0]}_selectWordAtCursor(e,t){const i=this._linkifier.currentLink?.link?.range;if(i)return this._model.selectionStart=[i.start.x-1,i.start.y-1],this._model.selectionStartLength=(0,_.getRangeLength)(i,this._bufferService.cols),this._model.selectionEnd=void 0,!0;const s=this._getMouseBufferCoords(e);return!!s&&(this._selectWordAt(s,t),this._model.selectionEnd=void 0,!0)}selectAll(){this._model.isSelectAllActive=!0,this.refresh(),this._onSelectionChange.fire()}selectLines(e,t){this._model.clearSelection(),e=Math.max(e,0),t=Math.min(t,this._bufferService.buffer.lines.length-1),this._model.selectionStart=[0,e],this._model.selectionEnd=[this._bufferService.cols,t],this.refresh(),this._onSelectionChange.fire()}_handleTrim(e){this._model.handleTrim(e)&&this.refresh()}_getMouseBufferCoords(e){const t=this._mouseService.getCoords(e,this._screenElement,this._bufferService.cols,this._bufferService.rows,!0);if(t)return t[0]--,t[1]--,t[1]+=this._bufferService.buffer.ydisp,t}_getMouseEventScrollAmount(e){let t=(0,n.getCoordsRelativeToElement)(this._coreBrowserService.window,e,this._screenElement)[1];const i=this._renderService.dimensions.css.canvas.height;return t>=0&&t<=i?0:(t>i&&(t-=i),t=Math.min(Math.max(t,-50),50),t/=50,t/Math.abs(t)+Math.round(14*t))}shouldForceSelection(e){return d.isMac?e.altKey&&this._optionsService.rawOptions.macOptionClickForcesSelection:e.shiftKey}handleMouseDown(e){if(this._mouseDownTimeStamp=e.timeStamp,(2!==e.button||!this.hasSelection)&&0===e.button){if(!this._enabled){if(!this.shouldForceSelection(e))return;e.stopPropagation()}e.preventDefault(),this._dragScrollAmount=0,this._enabled&&e.shiftKey?this._handleIncrementalClick(e):1===e.detail?this._handleSingleClick(e):2===e.detail?this._handleDoubleClick(e):3===e.detail&&this._handleTripleClick(e),this._addMouseDownListeners(),this.refresh(!0)}}_addMouseDownListeners(){this._screenElement.ownerDocument&&(this._screenElement.ownerDocument.addEventListener("mousemove",this._mouseMoveListener),this._screenElement.ownerDocument.addEventListener("mouseup",this._mouseUpListener)),this._dragScrollIntervalTimer=this._coreBrowserService.window.setInterval((()=>this._dragScroll()),50)}_removeMouseDownListeners(){this._screenElement.ownerDocument&&(this._screenElement.ownerDocument.removeEventListener("mousemove",this._mouseMoveListener),this._screenElement.ownerDocument.removeEventListener("mouseup",this._mouseUpListener)),this._coreBrowserService.window.clearInterval(this._dragScrollIntervalTimer),this._dragScrollIntervalTimer=void 0}_handleIncrementalClick(e){this._model.selectionStart&&(this._model.selectionEnd=this._getMouseBufferCoords(e))}_handleSingleClick(e){if(this._model.selectionStartLength=0,this._model.isSelectAllActive=!1,this._activeSelectionMode=this.shouldColumnSelect(e)?3:0,this._model.selectionStart=this._getMouseBufferCoords(e),!this._model.selectionStart)return;this._model.selectionEnd=void 0;const t=this._bufferService.buffer.lines.get(this._model.selectionStart[1]);t&&t.length!==this._model.selectionStart[0]&&0===t.hasWidth(this._model.selectionStart[0])&&this._model.selectionStart[0]++}_handleDoubleClick(e){this._selectWordAtCursor(e,!0)&&(this._activeSelectionMode=1)}_handleTripleClick(e){const t=this._getMouseBufferCoords(e);t&&(this._activeSelectionMode=2,this._selectLineAt(t[1]))}shouldColumnSelect(e){return e.altKey&&!(d.isMac&&this._optionsService.rawOptions.macOptionClickForcesSelection)}_handleMouseMove(e){if(e.stopImmediatePropagation(),!this._model.selectionStart)return;const t=this._model.selectionEnd?[this._model.selectionEnd[0],this._model.selectionEnd[1]]:null;if(this._model.selectionEnd=this._getMouseBufferCoords(e),!this._model.selectionEnd)return void this.refresh(!0);2===this._activeSelectionMode?this._model.selectionEnd[1]<this._model.selectionStart[1]?this._model.selectionEnd[0]=0:this._model.selectionEnd[0]=this._bufferService.cols:1===this._activeSelectionMode&&this._selectToWordAt(this._model.selectionEnd),this._dragScrollAmount=this._getMouseEventScrollAmount(e),3!==this._activeSelectionMode&&(this._dragScrollAmount>0?this._model.selectionEnd[0]=this._bufferService.cols:this._dragScrollAmount<0&&(this._model.selectionEnd[0]=0));const i=this._bufferService.buffer;if(this._model.selectionEnd[1]<i.lines.length){const e=i.lines.get(this._model.selectionEnd[1]);e&&0===e.hasWidth(this._model.selectionEnd[0])&&this._model.selectionEnd[0]<this._bufferService.cols&&this._model.selectionEnd[0]++}t&&t[0]===this._model.selectionEnd[0]&&t[1]===this._model.selectionEnd[1]||this.refresh(!0)}_dragScroll(){if(this._model.selectionEnd&&this._model.selectionStart&&this._dragScrollAmount){this._onRequestScrollLines.fire({amount:this._dragScrollAmount,suppressScrollEvent:!1});const e=this._bufferService.buffer;this._dragScrollAmount>0?(3!==this._activeSelectionMode&&(this._model.selectionEnd[0]=this._bufferService.cols),this._model.selectionEnd[1]=Math.min(e.ydisp+this._bufferService.rows,e.lines.length-1)):(3!==this._activeSelectionMode&&(this._model.selectionEnd[0]=0),this._model.selectionEnd[1]=e.ydisp),this.refresh()}}_handleMouseUp(e){const t=e.timeStamp-this._mouseDownTimeStamp;if(this._removeMouseDownListeners(),this.selectionText.length<=1&&t<500&&e.altKey&&this._optionsService.rawOptions.altClickMovesCursor){if(this._bufferService.buffer.ybase===this._bufferService.buffer.ydisp){const t=this._mouseService.getCoords(e,this._element,this._bufferService.cols,this._bufferService.rows,!1);if(t&&void 0!==t[0]&&void 0!==t[1]){const e=(0,o.moveToCellSequence)(t[0]-1,t[1]-1,this._bufferService,this._coreService.decPrivateModes.applicationCursorKeys);this._coreService.triggerDataEvent(e,!0)}}}else this._fireEventIfSelectionChanged()}_fireEventIfSelectionChanged(){const e=this._model.finalSelectionStart,t=this._model.finalSelectionEnd,i=!(!e||!t||e[0]===t[0]&&e[1]===t[1]);i?e&&t&&(this._oldSelectionStart&&this._oldSelectionEnd&&e[0]===this._oldSelectionStart[0]&&e[1]===this._oldSelectionStart[1]&&t[0]===this._oldSelectionEnd[0]&&t[1]===this._oldSelectionEnd[1]||this._fireOnSelectionChange(e,t,i)):this._oldHasSelection&&this._fireOnSelectionChange(e,t,i)}_fireOnSelectionChange(e,t,i){this._oldSelectionStart=e,this._oldSelectionEnd=t,this._oldHasSelection=i,this._onSelectionChange.fire()}_handleBufferActivate(e){this.clearSelection(),this._trimListener.dispose(),this._trimListener=e.activeBuffer.lines.onTrim((e=>this._handleTrim(e)))}_convertViewportColToCharacterIndex(e,t){let i=t;for(let s=0;t>=s;s++){const r=e.loadCell(s,this._workCell).getChars().length;0===this._workCell.getWidth()?i--:r>1&&t!==s&&(i+=r-1)}return i}setSelection(e,t,i){this._model.clearSelection(),this._removeMouseDownListeners(),this._model.selectionStart=[e,t],this._model.selectionStartLength=i,this.refresh(),this._fireEventIfSelectionChanged()}rightClickSelect(e){this._isClickInSelection(e)||(this._selectWordAtCursor(e,!1)&&this.refresh(!0),this._fireEventIfSelectionChanged())}_getWordAt(e,t,i=!0,s=!0){if(e[0]>=this._bufferService.cols)return;const r=this._bufferService.buffer,n=r.lines.get(e[1]);if(!n)return;const o=r.translateBufferLineToString(e[1],!1);let a=this._convertViewportColToCharacterIndex(n,e[0]),h=a;const c=e[0]-a;let l=0,d=0,_=0,u=0;if(" "===o.charAt(a)){for(;a>0&&" "===o.charAt(a-1);)a--;for(;h<o.length&&" "===o.charAt(h+1);)h++}else{let t=e[0],i=e[0];0===n.getWidth(t)&&(l++,t--),2===n.getWidth(i)&&(d++,i++);const s=n.getString(i).length;for(s>1&&(u+=s-1,h+=s-1);t>0&&a>0&&!this._isCharWordSeparator(n.loadCell(t-1,this._workCell));){n.loadCell(t-1,this._workCell);const e=this._workCell.getChars().length;0===this._workCell.getWidth()?(l++,t--):e>1&&(_+=e-1,a-=e-1),a--,t--}for(;i<n.length&&h+1<o.length&&!this._isCharWordSeparator(n.loadCell(i+1,this._workCell));){n.loadCell(i+1,this._workCell);const e=this._workCell.getChars().length;2===this._workCell.getWidth()?(d++,i++):e>1&&(u+=e-1,h+=e-1),h++,i++}}h++;let f=a+c-l+_,v=Math.min(this._bufferService.cols,h-a+l+d-_-u);if(t||""!==o.slice(a,h).trim()){if(i&&0===f&&32!==n.getCodePoint(0)){const t=r.lines.get(e[1]-1);if(t&&n.isWrapped&&32!==t.getCodePoint(this._bufferService.cols-1)){const t=this._getWordAt([this._bufferService.cols-1,e[1]-1],!1,!0,!1);if(t){const e=this._bufferService.cols-t.start;f-=e,v+=e}}}if(s&&f+v===this._bufferService.cols&&32!==n.getCodePoint(this._bufferService.cols-1)){const t=r.lines.get(e[1]+1);if(t?.isWrapped&&32!==t.getCodePoint(0)){const t=this._getWordAt([0,e[1]+1],!1,!1,!0);t&&(v+=t.length)}}return{start:f,length:v}}}_selectWordAt(e,t){const i=this._getWordAt(e,t);if(i){for(;i.start<0;)i.start+=this._bufferService.cols,e[1]--;this._model.selectionStart=[i.start,e[1]],this._model.selectionStartLength=i.length}}_selectToWordAt(e){const t=this._getWordAt(e,!0);if(t){let i=e[1];for(;t.start<0;)t.start+=this._bufferService.cols,i--;if(!this._model.areSelectionValuesReversed())for(;t.start+t.length>this._bufferService.cols;)t.length-=this._bufferService.cols,i++;this._model.selectionEnd=[this._model.areSelectionValuesReversed()?t.start:t.start+t.length,i]}}_isCharWordSeparator(e){return 0!==e.getWidth()&&this._optionsService.rawOptions.wordSeparator.indexOf(e.getChars())>=0}_selectLineAt(e){const t=this._bufferService.buffer.getWrappedRangeForLine(e),i={start:{x:0,y:t.first},end:{x:this._bufferService.cols-1,y:t.last}};this._model.selectionStart=[0,t.first],this._model.selectionEnd=void 0,this._model.selectionStartLength=(0,_.getRangeLength)(i,this._bufferService.cols)}};t.SelectionService=g=s([r(3,f.IBufferService),r(4,f.ICoreService),r(5,h.IMouseService),r(6,f.IOptionsService),r(7,h.IRenderService),r(8,h.ICoreBrowserService)],g)},4725:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ILinkProviderService=t.IThemeService=t.ICharacterJoinerService=t.ISelectionService=t.IRenderService=t.IMouseService=t.ICoreBrowserService=t.ICharSizeService=void 0;const s=i(8343);t.ICharSizeService=(0,s.createDecorator)("CharSizeService"),t.ICoreBrowserService=(0,s.createDecorator)("CoreBrowserService"),t.IMouseService=(0,s.createDecorator)("MouseService"),t.IRenderService=(0,s.createDecorator)("RenderService"),t.ISelectionService=(0,s.createDecorator)("SelectionService"),t.ICharacterJoinerService=(0,s.createDecorator)("CharacterJoinerService"),t.IThemeService=(0,s.createDecorator)("ThemeService"),t.ILinkProviderService=(0,s.createDecorator)("LinkProviderService")},6731:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.ThemeService=t.DEFAULT_ANSI_COLORS=void 0;const n=i(7239),o=i(8055),a=i(8460),h=i(844),c=i(2585),l=o.css.toColor("#ffffff"),d=o.css.toColor("#000000"),_=o.css.toColor("#ffffff"),u=o.css.toColor("#000000"),f={css:"rgba(255, 255, 255, 0.3)",rgba:4294967117};t.DEFAULT_ANSI_COLORS=Object.freeze((()=>{const e=[o.css.toColor("#2e3436"),o.css.toColor("#cc0000"),o.css.toColor("#4e9a06"),o.css.toColor("#c4a000"),o.css.toColor("#3465a4"),o.css.toColor("#75507b"),o.css.toColor("#06989a"),o.css.toColor("#d3d7cf"),o.css.toColor("#555753"),o.css.toColor("#ef2929"),o.css.toColor("#8ae234"),o.css.toColor("#fce94f"),o.css.toColor("#729fcf"),o.css.toColor("#ad7fa8"),o.css.toColor("#34e2e2"),o.css.toColor("#eeeeec")],t=[0,95,135,175,215,255];for(let i=0;i<216;i++){const s=t[i/36%6|0],r=t[i/6%6|0],n=t[i%6];e.push({css:o.channels.toCss(s,r,n),rgba:o.channels.toRgba(s,r,n)})}for(let t=0;t<24;t++){const i=8+10*t;e.push({css:o.channels.toCss(i,i,i),rgba:o.channels.toRgba(i,i,i)})}return e})());let v=t.ThemeService=class extends h.Disposable{get colors(){return this._colors}constructor(e){super(),this._optionsService=e,this._contrastCache=new n.ColorContrastCache,this._halfContrastCache=new n.ColorContrastCache,this._onChangeColors=this.register(new a.EventEmitter),this.onChangeColors=this._onChangeColors.event,this._colors={foreground:l,background:d,cursor:_,cursorAccent:u,selectionForeground:void 0,selectionBackgroundTransparent:f,selectionBackgroundOpaque:o.color.blend(d,f),selectionInactiveBackgroundTransparent:f,selectionInactiveBackgroundOpaque:o.color.blend(d,f),ansi:t.DEFAULT_ANSI_COLORS.slice(),contrastCache:this._contrastCache,halfContrastCache:this._halfContrastCache},this._updateRestoreColors(),this._setTheme(this._optionsService.rawOptions.theme),this.register(this._optionsService.onSpecificOptionChange("minimumContrastRatio",(()=>this._contrastCache.clear()))),this.register(this._optionsService.onSpecificOptionChange("theme",(()=>this._setTheme(this._optionsService.rawOptions.theme))))}_setTheme(e={}){const i=this._colors;if(i.foreground=p(e.foreground,l),i.background=p(e.background,d),i.cursor=p(e.cursor,_),i.cursorAccent=p(e.cursorAccent,u),i.selectionBackgroundTransparent=p(e.selectionBackground,f),i.selectionBackgroundOpaque=o.color.blend(i.background,i.selectionBackgroundTransparent),i.selectionInactiveBackgroundTransparent=p(e.selectionInactiveBackground,i.selectionBackgroundTransparent),i.selectionInactiveBackgroundOpaque=o.color.blend(i.background,i.selectionInactiveBackgroundTransparent),i.selectionForeground=e.selectionForeground?p(e.selectionForeground,o.NULL_COLOR):void 0,i.selectionForeground===o.NULL_COLOR&&(i.selectionForeground=void 0),o.color.isOpaque(i.selectionBackgroundTransparent)){const e=.3;i.selectionBackgroundTransparent=o.color.opacity(i.selectionBackgroundTransparent,e)}if(o.color.isOpaque(i.selectionInactiveBackgroundTransparent)){const e=.3;i.selectionInactiveBackgroundTransparent=o.color.opacity(i.selectionInactiveBackgroundTransparent,e)}if(i.ansi=t.DEFAULT_ANSI_COLORS.slice(),i.ansi[0]=p(e.black,t.DEFAULT_ANSI_COLORS[0]),i.ansi[1]=p(e.red,t.DEFAULT_ANSI_COLORS[1]),i.ansi[2]=p(e.green,t.DEFAULT_ANSI_COLORS[2]),i.ansi[3]=p(e.yellow,t.DEFAULT_ANSI_COLORS[3]),i.ansi[4]=p(e.blue,t.DEFAULT_ANSI_COLORS[4]),i.ansi[5]=p(e.magenta,t.DEFAULT_ANSI_COLORS[5]),i.ansi[6]=p(e.cyan,t.DEFAULT_ANSI_COLORS[6]),i.ansi[7]=p(e.white,t.DEFAULT_ANSI_COLORS[7]),i.ansi[8]=p(e.brightBlack,t.DEFAULT_ANSI_COLORS[8]),i.ansi[9]=p(e.brightRed,t.DEFAULT_ANSI_COLORS[9]),i.ansi[10]=p(e.brightGreen,t.DEFAULT_ANSI_COLORS[10]),i.ansi[11]=p(e.brightYellow,t.DEFAULT_ANSI_COLORS[11]),i.ansi[12]=p(e.brightBlue,t.DEFAULT_ANSI_COLORS[12]),i.ansi[13]=p(e.brightMagenta,t.DEFAULT_ANSI_COLORS[13]),i.ansi[14]=p(e.brightCyan,t.DEFAULT_ANSI_COLORS[14]),i.ansi[15]=p(e.brightWhite,t.DEFAULT_ANSI_COLORS[15]),e.extendedAnsi){const s=Math.min(i.ansi.length-16,e.extendedAnsi.length);for(let r=0;r<s;r++)i.ansi[r+16]=p(e.extendedAnsi[r],t.DEFAULT_ANSI_COLORS[r+16])}this._contrastCache.clear(),this._halfContrastCache.clear(),this._updateRestoreColors(),this._onChangeColors.fire(this.colors)}restoreColor(e){this._restoreColor(e),this._onChangeColors.fire(this.colors)}_restoreColor(e){if(void 0!==e)switch(e){case 256:this._colors.foreground=this._restoreColors.foreground;break;case 257:this._colors.background=this._restoreColors.background;break;case 258:this._colors.cursor=this._restoreColors.cursor;break;default:this._colors.ansi[e]=this._restoreColors.ansi[e]}else for(let e=0;e<this._restoreColors.ansi.length;++e)this._colors.ansi[e]=this._restoreColors.ansi[e]}modifyColors(e){e(this._colors),this._onChangeColors.fire(this.colors)}_updateRestoreColors(){this._restoreColors={foreground:this._colors.foreground,background:this._colors.background,cursor:this._colors.cursor,ansi:this._colors.ansi.slice()}}};function p(e,t){if(void 0!==e)try{return o.css.toColor(e)}catch{}return t}t.ThemeService=v=s([r(0,c.IOptionsService)],v)},6349:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CircularList=void 0;const s=i(8460),r=i(844);class n extends r.Disposable{constructor(e){super(),this._maxLength=e,this.onDeleteEmitter=this.register(new s.EventEmitter),this.onDelete=this.onDeleteEmitter.event,this.onInsertEmitter=this.register(new s.EventEmitter),this.onInsert=this.onInsertEmitter.event,this.onTrimEmitter=this.register(new s.EventEmitter),this.onTrim=this.onTrimEmitter.event,this._array=new Array(this._maxLength),this._startIndex=0,this._length=0}get maxLength(){return this._maxLength}set maxLength(e){if(this._maxLength===e)return;const t=new Array(e);for(let i=0;i<Math.min(e,this.length);i++)t[i]=this._array[this._getCyclicIndex(i)];this._array=t,this._maxLength=e,this._startIndex=0}get length(){return this._length}set length(e){if(e>this._length)for(let t=this._length;t<e;t++)this._array[t]=void 0;this._length=e}get(e){return this._array[this._getCyclicIndex(e)]}set(e,t){this._array[this._getCyclicIndex(e)]=t}push(e){this._array[this._getCyclicIndex(this._length)]=e,this._length===this._maxLength?(this._startIndex=++this._startIndex%this._maxLength,this.onTrimEmitter.fire(1)):this._length++}recycle(){if(this._length!==this._maxLength)throw new Error("Can only recycle when the buffer is full");return this._startIndex=++this._startIndex%this._maxLength,this.onTrimEmitter.fire(1),this._array[this._getCyclicIndex(this._length-1)]}get isFull(){return this._length===this._maxLength}pop(){return this._array[this._getCyclicIndex(this._length---1)]}splice(e,t,...i){if(t){for(let i=e;i<this._length-t;i++)this._array[this._getCyclicIndex(i)]=this._array[this._getCyclicIndex(i+t)];this._length-=t,this.onDeleteEmitter.fire({index:e,amount:t})}for(let t=this._length-1;t>=e;t--)this._array[this._getCyclicIndex(t+i.length)]=this._array[this._getCyclicIndex(t)];for(let t=0;t<i.length;t++)this._array[this._getCyclicIndex(e+t)]=i[t];if(i.length&&this.onInsertEmitter.fire({index:e,amount:i.length}),this._length+i.length>this._maxLength){const e=this._length+i.length-this._maxLength;this._startIndex+=e,this._length=this._maxLength,this.onTrimEmitter.fire(e)}else this._length+=i.length}trimStart(e){e>this._length&&(e=this._length),this._startIndex+=e,this._length-=e,this.onTrimEmitter.fire(e)}shiftElements(e,t,i){if(!(t<=0)){if(e<0||e>=this._length)throw new Error("start argument out of range");if(e+i<0)throw new Error("Cannot shift elements in list beyond index 0");if(i>0){for(let s=t-1;s>=0;s--)this.set(e+s+i,this.get(e+s));const s=e+t+i-this._length;if(s>0)for(this._length+=s;this._length>this._maxLength;)this._length--,this._startIndex++,this.onTrimEmitter.fire(1)}else for(let s=0;s<t;s++)this.set(e+s+i,this.get(e+s))}}_getCyclicIndex(e){return(this._startIndex+e)%this._maxLength}}t.CircularList=n},1439:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.clone=void 0,t.clone=function e(t,i=5){if("object"!=typeof t)return t;const s=Array.isArray(t)?[]:{};for(const r in t)s[r]=i<=1?t[r]:t[r]&&e(t[r],i-1);return s}},8055:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.contrastRatio=t.toPaddedHex=t.rgba=t.rgb=t.css=t.color=t.channels=t.NULL_COLOR=void 0;let i=0,s=0,r=0,n=0;var o,a,h,c,l;function d(e){const t=e.toString(16);return t.length<2?"0"+t:t}function _(e,t){return e<t?(t+.05)/(e+.05):(e+.05)/(t+.05)}t.NULL_COLOR={css:"#00000000",rgba:0},function(e){e.toCss=function(e,t,i,s){return void 0!==s?`#${d(e)}${d(t)}${d(i)}${d(s)}`:`#${d(e)}${d(t)}${d(i)}`},e.toRgba=function(e,t,i,s=255){return(e<<24|t<<16|i<<8|s)>>>0},e.toColor=function(t,i,s,r){return{css:e.toCss(t,i,s,r),rgba:e.toRgba(t,i,s,r)}}}(o||(t.channels=o={})),function(e){function t(e,t){return n=Math.round(255*t),[i,s,r]=l.toChannels(e.rgba),{css:o.toCss(i,s,r,n),rgba:o.toRgba(i,s,r,n)}}e.blend=function(e,t){if(n=(255&t.rgba)/255,1===n)return{css:t.css,rgba:t.rgba};const a=t.rgba>>24&255,h=t.rgba>>16&255,c=t.rgba>>8&255,l=e.rgba>>24&255,d=e.rgba>>16&255,_=e.rgba>>8&255;return i=l+Math.round((a-l)*n),s=d+Math.round((h-d)*n),r=_+Math.round((c-_)*n),{css:o.toCss(i,s,r),rgba:o.toRgba(i,s,r)}},e.isOpaque=function(e){return 255==(255&e.rgba)},e.ensureContrastRatio=function(e,t,i){const s=l.ensureContrastRatio(e.rgba,t.rgba,i);if(s)return o.toColor(s>>24&255,s>>16&255,s>>8&255)},e.opaque=function(e){const t=(255|e.rgba)>>>0;return[i,s,r]=l.toChannels(t),{css:o.toCss(i,s,r),rgba:t}},e.opacity=t,e.multiplyOpacity=function(e,i){return n=255&e.rgba,t(e,n*i/255)},e.toColorRGB=function(e){return[e.rgba>>24&255,e.rgba>>16&255,e.rgba>>8&255]}}(a||(t.color=a={})),function(e){let t,a;try{const e=document.createElement("canvas");e.width=1,e.height=1;const i=e.getContext("2d",{willReadFrequently:!0});i&&(t=i,t.globalCompositeOperation="copy",a=t.createLinearGradient(0,0,1,1))}catch{}e.toColor=function(e){if(e.match(/#[\\da-f]{3,8}/i))switch(e.length){case 4:return i=parseInt(e.slice(1,2).repeat(2),16),s=parseInt(e.slice(2,3).repeat(2),16),r=parseInt(e.slice(3,4).repeat(2),16),o.toColor(i,s,r);case 5:return i=parseInt(e.slice(1,2).repeat(2),16),s=parseInt(e.slice(2,3).repeat(2),16),r=parseInt(e.slice(3,4).repeat(2),16),n=parseInt(e.slice(4,5).repeat(2),16),o.toColor(i,s,r,n);case 7:return{css:e,rgba:(parseInt(e.slice(1),16)<<8|255)>>>0};case 9:return{css:e,rgba:parseInt(e.slice(1),16)>>>0}}const h=e.match(/rgba?\\(\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*(,\\s*(0|1|\\d?\\.(\\d+))\\s*)?\\)/);if(h)return i=parseInt(h[1]),s=parseInt(h[2]),r=parseInt(h[3]),n=Math.round(255*(void 0===h[5]?1:parseFloat(h[5]))),o.toColor(i,s,r,n);if(!t||!a)throw new Error("css.toColor: Unsupported css format");if(t.fillStyle=a,t.fillStyle=e,"string"!=typeof t.fillStyle)throw new Error("css.toColor: Unsupported css format");if(t.fillRect(0,0,1,1),[i,s,r,n]=t.getImageData(0,0,1,1).data,255!==n)throw new Error("css.toColor: Unsupported css format");return{rgba:o.toRgba(i,s,r,n),css:e}}}(h||(t.css=h={})),function(e){function t(e,t,i){const s=e/255,r=t/255,n=i/255;return.2126*(s<=.03928?s/12.92:Math.pow((s+.055)/1.055,2.4))+.7152*(r<=.03928?r/12.92:Math.pow((r+.055)/1.055,2.4))+.0722*(n<=.03928?n/12.92:Math.pow((n+.055)/1.055,2.4))}e.relativeLuminance=function(e){return t(e>>16&255,e>>8&255,255&e)},e.relativeLuminance2=t}(c||(t.rgb=c={})),function(e){function t(e,t,i){const s=e>>24&255,r=e>>16&255,n=e>>8&255;let o=t>>24&255,a=t>>16&255,h=t>>8&255,l=_(c.relativeLuminance2(o,a,h),c.relativeLuminance2(s,r,n));for(;l<i&&(o>0||a>0||h>0);)o-=Math.max(0,Math.ceil(.1*o)),a-=Math.max(0,Math.ceil(.1*a)),h-=Math.max(0,Math.ceil(.1*h)),l=_(c.relativeLuminance2(o,a,h),c.relativeLuminance2(s,r,n));return(o<<24|a<<16|h<<8|255)>>>0}function a(e,t,i){const s=e>>24&255,r=e>>16&255,n=e>>8&255;let o=t>>24&255,a=t>>16&255,h=t>>8&255,l=_(c.relativeLuminance2(o,a,h),c.relativeLuminance2(s,r,n));for(;l<i&&(o<255||a<255||h<255);)o=Math.min(255,o+Math.ceil(.1*(255-o))),a=Math.min(255,a+Math.ceil(.1*(255-a))),h=Math.min(255,h+Math.ceil(.1*(255-h))),l=_(c.relativeLuminance2(o,a,h),c.relativeLuminance2(s,r,n));return(o<<24|a<<16|h<<8|255)>>>0}e.blend=function(e,t){if(n=(255&t)/255,1===n)return t;const a=t>>24&255,h=t>>16&255,c=t>>8&255,l=e>>24&255,d=e>>16&255,_=e>>8&255;return i=l+Math.round((a-l)*n),s=d+Math.round((h-d)*n),r=_+Math.round((c-_)*n),o.toRgba(i,s,r)},e.ensureContrastRatio=function(e,i,s){const r=c.relativeLuminance(e>>8),n=c.relativeLuminance(i>>8);if(_(r,n)<s){if(n<r){const n=t(e,i,s),o=_(r,c.relativeLuminance(n>>8));if(o<s){const t=a(e,i,s);return o>_(r,c.relativeLuminance(t>>8))?n:t}return n}const o=a(e,i,s),h=_(r,c.relativeLuminance(o>>8));if(h<s){const n=t(e,i,s);return h>_(r,c.relativeLuminance(n>>8))?o:n}return o}},e.reduceLuminance=t,e.increaseLuminance=a,e.toChannels=function(e){return[e>>24&255,e>>16&255,e>>8&255,255&e]}}(l||(t.rgba=l={})),t.toPaddedHex=d,t.contrastRatio=_},8969:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CoreTerminal=void 0;const s=i(844),r=i(2585),n=i(4348),o=i(7866),a=i(744),h=i(7302),c=i(6975),l=i(8460),d=i(1753),_=i(1480),u=i(7994),f=i(9282),v=i(5435),p=i(5981),g=i(2660);let m=!1;class S extends s.Disposable{get onScroll(){return this._onScrollApi||(this._onScrollApi=this.register(new l.EventEmitter),this._onScroll.event((e=>{this._onScrollApi?.fire(e.position)}))),this._onScrollApi.event}get cols(){return this._bufferService.cols}get rows(){return this._bufferService.rows}get buffers(){return this._bufferService.buffers}get options(){return this.optionsService.options}set options(e){for(const t in e)this.optionsService.options[t]=e[t]}constructor(e){super(),this._windowsWrappingHeuristics=this.register(new s.MutableDisposable),this._onBinary=this.register(new l.EventEmitter),this.onBinary=this._onBinary.event,this._onData=this.register(new l.EventEmitter),this.onData=this._onData.event,this._onLineFeed=this.register(new l.EventEmitter),this.onLineFeed=this._onLineFeed.event,this._onResize=this.register(new l.EventEmitter),this.onResize=this._onResize.event,this._onWriteParsed=this.register(new l.EventEmitter),this.onWriteParsed=this._onWriteParsed.event,this._onScroll=this.register(new l.EventEmitter),this._instantiationService=new n.InstantiationService,this.optionsService=this.register(new h.OptionsService(e)),this._instantiationService.setService(r.IOptionsService,this.optionsService),this._bufferService=this.register(this._instantiationService.createInstance(a.BufferService)),this._instantiationService.setService(r.IBufferService,this._bufferService),this._logService=this.register(this._instantiationService.createInstance(o.LogService)),this._instantiationService.setService(r.ILogService,this._logService),this.coreService=this.register(this._instantiationService.createInstance(c.CoreService)),this._instantiationService.setService(r.ICoreService,this.coreService),this.coreMouseService=this.register(this._instantiationService.createInstance(d.CoreMouseService)),this._instantiationService.setService(r.ICoreMouseService,this.coreMouseService),this.unicodeService=this.register(this._instantiationService.createInstance(_.UnicodeService)),this._instantiationService.setService(r.IUnicodeService,this.unicodeService),this._charsetService=this._instantiationService.createInstance(u.CharsetService),this._instantiationService.setService(r.ICharsetService,this._charsetService),this._oscLinkService=this._instantiationService.createInstance(g.OscLinkService),this._instantiationService.setService(r.IOscLinkService,this._oscLinkService),this._inputHandler=this.register(new v.InputHandler(this._bufferService,this._charsetService,this.coreService,this._logService,this.optionsService,this._oscLinkService,this.coreMouseService,this.unicodeService)),this.register((0,l.forwardEvent)(this._inputHandler.onLineFeed,this._onLineFeed)),this.register(this._inputHandler),this.register((0,l.forwardEvent)(this._bufferService.onResize,this._onResize)),this.register((0,l.forwardEvent)(this.coreService.onData,this._onData)),this.register((0,l.forwardEvent)(this.coreService.onBinary,this._onBinary)),this.register(this.coreService.onRequestScrollToBottom((()=>this.scrollToBottom()))),this.register(this.coreService.onUserInput((()=>this._writeBuffer.handleUserInput()))),this.register(this.optionsService.onMultipleOptionChange(["windowsMode","windowsPty"],(()=>this._handleWindowsPtyOptionChange()))),this.register(this._bufferService.onScroll((e=>{this._onScroll.fire({position:this._bufferService.buffer.ydisp,source:0}),this._inputHandler.markRangeDirty(this._bufferService.buffer.scrollTop,this._bufferService.buffer.scrollBottom)}))),this.register(this._inputHandler.onScroll((e=>{this._onScroll.fire({position:this._bufferService.buffer.ydisp,source:0}),this._inputHandler.markRangeDirty(this._bufferService.buffer.scrollTop,this._bufferService.buffer.scrollBottom)}))),this._writeBuffer=this.register(new p.WriteBuffer(((e,t)=>this._inputHandler.parse(e,t)))),this.register((0,l.forwardEvent)(this._writeBuffer.onWriteParsed,this._onWriteParsed))}write(e,t){this._writeBuffer.write(e,t)}writeSync(e,t){this._logService.logLevel<=r.LogLevelEnum.WARN&&!m&&(this._logService.warn("writeSync is unreliable and will be removed soon."),m=!0),this._writeBuffer.writeSync(e,t)}input(e,t=!0){this.coreService.triggerDataEvent(e,t)}resize(e,t){isNaN(e)||isNaN(t)||(e=Math.max(e,a.MINIMUM_COLS),t=Math.max(t,a.MINIMUM_ROWS),this._bufferService.resize(e,t))}scroll(e,t=!1){this._bufferService.scroll(e,t)}scrollLines(e,t,i){this._bufferService.scrollLines(e,t,i)}scrollPages(e){this.scrollLines(e*(this.rows-1))}scrollToTop(){this.scrollLines(-this._bufferService.buffer.ydisp)}scrollToBottom(){this.scrollLines(this._bufferService.buffer.ybase-this._bufferService.buffer.ydisp)}scrollToLine(e){const t=e-this._bufferService.buffer.ydisp;0!==t&&this.scrollLines(t)}registerEscHandler(e,t){return this._inputHandler.registerEscHandler(e,t)}registerDcsHandler(e,t){return this._inputHandler.registerDcsHandler(e,t)}registerCsiHandler(e,t){return this._inputHandler.registerCsiHandler(e,t)}registerOscHandler(e,t){return this._inputHandler.registerOscHandler(e,t)}_setup(){this._handleWindowsPtyOptionChange()}reset(){this._inputHandler.reset(),this._bufferService.reset(),this._charsetService.reset(),this.coreService.reset(),this.coreMouseService.reset()}_handleWindowsPtyOptionChange(){let e=!1;const t=this.optionsService.rawOptions.windowsPty;t&&void 0!==t.buildNumber&&void 0!==t.buildNumber?e=!!("conpty"===t.backend&&t.buildNumber<21376):this.optionsService.rawOptions.windowsMode&&(e=!0),e?this._enableWindowsWrappingHeuristics():this._windowsWrappingHeuristics.clear()}_enableWindowsWrappingHeuristics(){if(!this._windowsWrappingHeuristics.value){const e=[];e.push(this.onLineFeed(f.updateWindowsModeWrappedState.bind(null,this._bufferService))),e.push(this.registerCsiHandler({final:"H"},(()=>((0,f.updateWindowsModeWrappedState)(this._bufferService),!1)))),this._windowsWrappingHeuristics.value=(0,s.toDisposable)((()=>{for(const t of e)t.dispose()}))}}}t.CoreTerminal=S},8460:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.runAndSubscribe=t.forwardEvent=t.EventEmitter=void 0,t.EventEmitter=class{constructor(){this._listeners=[],this._disposed=!1}get event(){return this._event||(this._event=e=>(this._listeners.push(e),{dispose:()=>{if(!this._disposed)for(let t=0;t<this._listeners.length;t++)if(this._listeners[t]===e)return void this._listeners.splice(t,1)}})),this._event}fire(e,t){const i=[];for(let e=0;e<this._listeners.length;e++)i.push(this._listeners[e]);for(let s=0;s<i.length;s++)i[s].call(void 0,e,t)}dispose(){this.clearListeners(),this._disposed=!0}clearListeners(){this._listeners&&(this._listeners.length=0)}},t.forwardEvent=function(e,t){return e((e=>t.fire(e)))},t.runAndSubscribe=function(e,t){return t(void 0),e((e=>t(e)))}},5435:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.InputHandler=t.WindowsOptionsReportType=void 0;const n=i(2584),o=i(7116),a=i(2015),h=i(844),c=i(482),l=i(8437),d=i(8460),_=i(643),u=i(511),f=i(3734),v=i(2585),p=i(1480),g=i(6242),m=i(6351),S=i(5941),C={"(":0,")":1,"*":2,"+":3,"-":1,".":2},b=131072;function w(e,t){if(e>24)return t.setWinLines||!1;switch(e){case 1:return!!t.restoreWin;case 2:return!!t.minimizeWin;case 3:return!!t.setWinPosition;case 4:return!!t.setWinSizePixels;case 5:return!!t.raiseWin;case 6:return!!t.lowerWin;case 7:return!!t.refreshWin;case 8:return!!t.setWinSizeChars;case 9:return!!t.maximizeWin;case 10:return!!t.fullscreenWin;case 11:return!!t.getWinState;case 13:return!!t.getWinPosition;case 14:return!!t.getWinSizePixels;case 15:return!!t.getScreenSizePixels;case 16:return!!t.getCellSizePixels;case 18:return!!t.getWinSizeChars;case 19:return!!t.getScreenSizeChars;case 20:return!!t.getIconTitle;case 21:return!!t.getWinTitle;case 22:return!!t.pushTitle;case 23:return!!t.popTitle;case 24:return!!t.setWinLines}return!1}var y;!function(e){e[e.GET_WIN_SIZE_PIXELS=0]="GET_WIN_SIZE_PIXELS",e[e.GET_CELL_SIZE_PIXELS=1]="GET_CELL_SIZE_PIXELS"}(y||(t.WindowsOptionsReportType=y={}));let E=0;class k extends h.Disposable{getAttrData(){return this._curAttrData}constructor(e,t,i,s,r,h,_,f,v=new a.EscapeSequenceParser){super(),this._bufferService=e,this._charsetService=t,this._coreService=i,this._logService=s,this._optionsService=r,this._oscLinkService=h,this._coreMouseService=_,this._unicodeService=f,this._parser=v,this._parseBuffer=new Uint32Array(4096),this._stringDecoder=new c.StringToUtf32,this._utf8Decoder=new c.Utf8ToUtf32,this._workCell=new u.CellData,this._windowTitle="",this._iconName="",this._windowTitleStack=[],this._iconNameStack=[],this._curAttrData=l.DEFAULT_ATTR_DATA.clone(),this._eraseAttrDataInternal=l.DEFAULT_ATTR_DATA.clone(),this._onRequestBell=this.register(new d.EventEmitter),this.onRequestBell=this._onRequestBell.event,this._onRequestRefreshRows=this.register(new d.EventEmitter),this.onRequestRefreshRows=this._onRequestRefreshRows.event,this._onRequestReset=this.register(new d.EventEmitter),this.onRequestReset=this._onRequestReset.event,this._onRequestSendFocus=this.register(new d.EventEmitter),this.onRequestSendFocus=this._onRequestSendFocus.event,this._onRequestSyncScrollBar=this.register(new d.EventEmitter),this.onRequestSyncScrollBar=this._onRequestSyncScrollBar.event,this._onRequestWindowsOptionsReport=this.register(new d.EventEmitter),this.onRequestWindowsOptionsReport=this._onRequestWindowsOptionsReport.event,this._onA11yChar=this.register(new d.EventEmitter),this.onA11yChar=this._onA11yChar.event,this._onA11yTab=this.register(new d.EventEmitter),this.onA11yTab=this._onA11yTab.event,this._onCursorMove=this.register(new d.EventEmitter),this.onCursorMove=this._onCursorMove.event,this._onLineFeed=this.register(new d.EventEmitter),this.onLineFeed=this._onLineFeed.event,this._onScroll=this.register(new d.EventEmitter),this.onScroll=this._onScroll.event,this._onTitleChange=this.register(new d.EventEmitter),this.onTitleChange=this._onTitleChange.event,this._onColor=this.register(new d.EventEmitter),this.onColor=this._onColor.event,this._parseStack={paused:!1,cursorStartX:0,cursorStartY:0,decodedLength:0,position:0},this._specialColors=[256,257,258],this.register(this._parser),this._dirtyRowTracker=new L(this._bufferService),this._activeBuffer=this._bufferService.buffer,this.register(this._bufferService.buffers.onBufferActivate((e=>this._activeBuffer=e.activeBuffer))),this._parser.setCsiHandlerFallback(((e,t)=>{this._logService.debug("Unknown CSI code: ",{identifier:this._parser.identToString(e),params:t.toArray()})})),this._parser.setEscHandlerFallback((e=>{this._logService.debug("Unknown ESC code: ",{identifier:this._parser.identToString(e)})})),this._parser.setExecuteHandlerFallback((e=>{this._logService.debug("Unknown EXECUTE code: ",{code:e})})),this._parser.setOscHandlerFallback(((e,t,i)=>{this._logService.debug("Unknown OSC code: ",{identifier:e,action:t,data:i})})),this._parser.setDcsHandlerFallback(((e,t,i)=>{"HOOK"===t&&(i=i.toArray()),this._logService.debug("Unknown DCS code: ",{identifier:this._parser.identToString(e),action:t,payload:i})})),this._parser.setPrintHandler(((e,t,i)=>this.print(e,t,i))),this._parser.registerCsiHandler({final:"@"},(e=>this.insertChars(e))),this._parser.registerCsiHandler({intermediates:" ",final:"@"},(e=>this.scrollLeft(e))),this._parser.registerCsiHandler({final:"A"},(e=>this.cursorUp(e))),this._parser.registerCsiHandler({intermediates:" ",final:"A"},(e=>this.scrollRight(e))),this._parser.registerCsiHandler({final:"B"},(e=>this.cursorDown(e))),this._parser.registerCsiHandler({final:"C"},(e=>this.cursorForward(e))),this._parser.registerCsiHandler({final:"D"},(e=>this.cursorBackward(e))),this._parser.registerCsiHandler({final:"E"},(e=>this.cursorNextLine(e))),this._parser.registerCsiHandler({final:"F"},(e=>this.cursorPrecedingLine(e))),this._parser.registerCsiHandler({final:"G"},(e=>this.cursorCharAbsolute(e))),this._parser.registerCsiHandler({final:"H"},(e=>this.cursorPosition(e))),this._parser.registerCsiHandler({final:"I"},(e=>this.cursorForwardTab(e))),this._parser.registerCsiHandler({final:"J"},(e=>this.eraseInDisplay(e,!1))),this._parser.registerCsiHandler({prefix:"?",final:"J"},(e=>this.eraseInDisplay(e,!0))),this._parser.registerCsiHandler({final:"K"},(e=>this.eraseInLine(e,!1))),this._parser.registerCsiHandler({prefix:"?",final:"K"},(e=>this.eraseInLine(e,!0))),this._parser.registerCsiHandler({final:"L"},(e=>this.insertLines(e))),this._parser.registerCsiHandler({final:"M"},(e=>this.deleteLines(e))),this._parser.registerCsiHandler({final:"P"},(e=>this.deleteChars(e))),this._parser.registerCsiHandler({final:"S"},(e=>this.scrollUp(e))),this._parser.registerCsiHandler({final:"T"},(e=>this.scrollDown(e))),this._parser.registerCsiHandler({final:"X"},(e=>this.eraseChars(e))),this._parser.registerCsiHandler({final:"Z"},(e=>this.cursorBackwardTab(e))),this._parser.registerCsiHandler({final:"`"},(e=>this.charPosAbsolute(e))),this._parser.registerCsiHandler({final:"a"},(e=>this.hPositionRelative(e))),this._parser.registerCsiHandler({final:"b"},(e=>this.repeatPrecedingCharacter(e))),this._parser.registerCsiHandler({final:"c"},(e=>this.sendDeviceAttributesPrimary(e))),this._parser.registerCsiHandler({prefix:">",final:"c"},(e=>this.sendDeviceAttributesSecondary(e))),this._parser.registerCsiHandler({final:"d"},(e=>this.linePosAbsolute(e))),this._parser.registerCsiHandler({final:"e"},(e=>this.vPositionRelative(e))),this._parser.registerCsiHandler({final:"f"},(e=>this.hVPosition(e))),this._parser.registerCsiHandler({final:"g"},(e=>this.tabClear(e))),this._parser.registerCsiHandler({final:"h"},(e=>this.setMode(e))),this._parser.registerCsiHandler({prefix:"?",final:"h"},(e=>this.setModePrivate(e))),this._parser.registerCsiHandler({final:"l"},(e=>this.resetMode(e))),this._parser.registerCsiHandler({prefix:"?",final:"l"},(e=>this.resetModePrivate(e))),this._parser.registerCsiHandler({final:"m"},(e=>this.charAttributes(e))),this._parser.registerCsiHandler({final:"n"},(e=>this.deviceStatus(e))),this._parser.registerCsiHandler({prefix:"?",final:"n"},(e=>this.deviceStatusPrivate(e))),this._parser.registerCsiHandler({intermediates:"!",final:"p"},(e=>this.softReset(e))),this._parser.registerCsiHandler({intermediates:" ",final:"q"},(e=>this.setCursorStyle(e))),this._parser.registerCsiHandler({final:"r"},(e=>this.setScrollRegion(e))),this._parser.registerCsiHandler({final:"s"},(e=>this.saveCursor(e))),this._parser.registerCsiHandler({final:"t"},(e=>this.windowOptions(e))),this._parser.registerCsiHandler({final:"u"},(e=>this.restoreCursor(e))),this._parser.registerCsiHandler({intermediates:"\'",final:"}"},(e=>this.insertColumns(e))),this._parser.registerCsiHandler({intermediates:"\'",final:"~"},(e=>this.deleteColumns(e))),this._parser.registerCsiHandler({intermediates:\'"\',final:"q"},(e=>this.selectProtected(e))),this._parser.registerCsiHandler({intermediates:"$",final:"p"},(e=>this.requestMode(e,!0))),this._parser.registerCsiHandler({prefix:"?",intermediates:"$",final:"p"},(e=>this.requestMode(e,!1))),this._parser.setExecuteHandler(n.C0.BEL,(()=>this.bell())),this._parser.setExecuteHandler(n.C0.LF,(()=>this.lineFeed())),this._parser.setExecuteHandler(n.C0.VT,(()=>this.lineFeed())),this._parser.setExecuteHandler(n.C0.FF,(()=>this.lineFeed())),this._parser.setExecuteHandler(n.C0.CR,(()=>this.carriageReturn())),this._parser.setExecuteHandler(n.C0.BS,(()=>this.backspace())),this._parser.setExecuteHandler(n.C0.HT,(()=>this.tab())),this._parser.setExecuteHandler(n.C0.SO,(()=>this.shiftOut())),this._parser.setExecuteHandler(n.C0.SI,(()=>this.shiftIn())),this._parser.setExecuteHandler(n.C1.IND,(()=>this.index())),this._parser.setExecuteHandler(n.C1.NEL,(()=>this.nextLine())),this._parser.setExecuteHandler(n.C1.HTS,(()=>this.tabSet())),this._parser.registerOscHandler(0,new g.OscHandler((e=>(this.setTitle(e),this.setIconName(e),!0)))),this._parser.registerOscHandler(1,new g.OscHandler((e=>this.setIconName(e)))),this._parser.registerOscHandler(2,new g.OscHandler((e=>this.setTitle(e)))),this._parser.registerOscHandler(4,new g.OscHandler((e=>this.setOrReportIndexedColor(e)))),this._parser.registerOscHandler(8,new g.OscHandler((e=>this.setHyperlink(e)))),this._parser.registerOscHandler(10,new g.OscHandler((e=>this.setOrReportFgColor(e)))),this._parser.registerOscHandler(11,new g.OscHandler((e=>this.setOrReportBgColor(e)))),this._parser.registerOscHandler(12,new g.OscHandler((e=>this.setOrReportCursorColor(e)))),this._parser.registerOscHandler(104,new g.OscHandler((e=>this.restoreIndexedColor(e)))),this._parser.registerOscHandler(110,new g.OscHandler((e=>this.restoreFgColor(e)))),this._parser.registerOscHandler(111,new g.OscHandler((e=>this.restoreBgColor(e)))),this._parser.registerOscHandler(112,new g.OscHandler((e=>this.restoreCursorColor(e)))),this._parser.registerEscHandler({final:"7"},(()=>this.saveCursor())),this._parser.registerEscHandler({final:"8"},(()=>this.restoreCursor())),this._parser.registerEscHandler({final:"D"},(()=>this.index())),this._parser.registerEscHandler({final:"E"},(()=>this.nextLine())),this._parser.registerEscHandler({final:"H"},(()=>this.tabSet())),this._parser.registerEscHandler({final:"M"},(()=>this.reverseIndex())),this._parser.registerEscHandler({final:"="},(()=>this.keypadApplicationMode())),this._parser.registerEscHandler({final:">"},(()=>this.keypadNumericMode())),this._parser.registerEscHandler({final:"c"},(()=>this.fullReset())),this._parser.registerEscHandler({final:"n"},(()=>this.setgLevel(2))),this._parser.registerEscHandler({final:"o"},(()=>this.setgLevel(3))),this._parser.registerEscHandler({final:"|"},(()=>this.setgLevel(3))),this._parser.registerEscHandler({final:"}"},(()=>this.setgLevel(2))),this._parser.registerEscHandler({final:"~"},(()=>this.setgLevel(1))),this._parser.registerEscHandler({intermediates:"%",final:"@"},(()=>this.selectDefaultCharset())),this._parser.registerEscHandler({intermediates:"%",final:"G"},(()=>this.selectDefaultCharset()));for(const e in o.CHARSETS)this._parser.registerEscHandler({intermediates:"(",final:e},(()=>this.selectCharset("("+e))),this._parser.registerEscHandler({intermediates:")",final:e},(()=>this.selectCharset(")"+e))),this._parser.registerEscHandler({intermediates:"*",final:e},(()=>this.selectCharset("*"+e))),this._parser.registerEscHandler({intermediates:"+",final:e},(()=>this.selectCharset("+"+e))),this._parser.registerEscHandler({intermediates:"-",final:e},(()=>this.selectCharset("-"+e))),this._parser.registerEscHandler({intermediates:".",final:e},(()=>this.selectCharset("."+e))),this._parser.registerEscHandler({intermediates:"/",final:e},(()=>this.selectCharset("/"+e)));this._parser.registerEscHandler({intermediates:"#",final:"8"},(()=>this.screenAlignmentPattern())),this._parser.setErrorHandler((e=>(this._logService.error("Parsing error: ",e),e))),this._parser.registerDcsHandler({intermediates:"$",final:"q"},new m.DcsHandler(((e,t)=>this.requestStatusString(e,t))))}_preserveStack(e,t,i,s){this._parseStack.paused=!0,this._parseStack.cursorStartX=e,this._parseStack.cursorStartY=t,this._parseStack.decodedLength=i,this._parseStack.position=s}_logSlowResolvingAsync(e){this._logService.logLevel<=v.LogLevelEnum.WARN&&Promise.race([e,new Promise(((e,t)=>setTimeout((()=>t("#SLOW_TIMEOUT")),5e3)))]).catch((e=>{if("#SLOW_TIMEOUT"!==e)throw e;console.warn("async parser handler taking longer than 5000 ms")}))}_getCurrentLinkId(){return this._curAttrData.extended.urlId}parse(e,t){let i,s=this._activeBuffer.x,r=this._activeBuffer.y,n=0;const o=this._parseStack.paused;if(o){if(i=this._parser.parse(this._parseBuffer,this._parseStack.decodedLength,t))return this._logSlowResolvingAsync(i),i;s=this._parseStack.cursorStartX,r=this._parseStack.cursorStartY,this._parseStack.paused=!1,e.length>b&&(n=this._parseStack.position+b)}if(this._logService.logLevel<=v.LogLevelEnum.DEBUG&&this._logService.debug("parsing data"+("string"==typeof e?` "${e}"`:` "${Array.prototype.map.call(e,(e=>String.fromCharCode(e))).join("")}"`),"string"==typeof e?e.split("").map((e=>e.charCodeAt(0))):e),this._parseBuffer.length<e.length&&this._parseBuffer.length<b&&(this._parseBuffer=new Uint32Array(Math.min(e.length,b))),o||this._dirtyRowTracker.clearRange(),e.length>b)for(let t=n;t<e.length;t+=b){const n=t+b<e.length?t+b:e.length,o="string"==typeof e?this._stringDecoder.decode(e.substring(t,n),this._parseBuffer):this._utf8Decoder.decode(e.subarray(t,n),this._parseBuffer);if(i=this._parser.parse(this._parseBuffer,o))return this._preserveStack(s,r,o,t),this._logSlowResolvingAsync(i),i}else if(!o){const t="string"==typeof e?this._stringDecoder.decode(e,this._parseBuffer):this._utf8Decoder.decode(e,this._parseBuffer);if(i=this._parser.parse(this._parseBuffer,t))return this._preserveStack(s,r,t,0),this._logSlowResolvingAsync(i),i}this._activeBuffer.x===s&&this._activeBuffer.y===r||this._onCursorMove.fire();const a=this._dirtyRowTracker.end+(this._bufferService.buffer.ybase-this._bufferService.buffer.ydisp),h=this._dirtyRowTracker.start+(this._bufferService.buffer.ybase-this._bufferService.buffer.ydisp);h<this._bufferService.rows&&this._onRequestRefreshRows.fire(Math.min(h,this._bufferService.rows-1),Math.min(a,this._bufferService.rows-1))}print(e,t,i){let s,r;const n=this._charsetService.charset,o=this._optionsService.rawOptions.screenReaderMode,a=this._bufferService.cols,h=this._coreService.decPrivateModes.wraparound,d=this._coreService.modes.insertMode,u=this._curAttrData;let f=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);this._dirtyRowTracker.markDirty(this._activeBuffer.y),this._activeBuffer.x&&i-t>0&&2===f.getWidth(this._activeBuffer.x-1)&&f.setCellFromCodepoint(this._activeBuffer.x-1,0,1,u);let v=this._parser.precedingJoinState;for(let g=t;g<i;++g){if(s=e[g],s<127&&n){const e=n[String.fromCharCode(s)];e&&(s=e.charCodeAt(0))}const t=this._unicodeService.charProperties(s,v);r=p.UnicodeService.extractWidth(t);const i=p.UnicodeService.extractShouldJoin(t),m=i?p.UnicodeService.extractWidth(v):0;if(v=t,o&&this._onA11yChar.fire((0,c.stringFromCodePoint)(s)),this._getCurrentLinkId()&&this._oscLinkService.addLineToLink(this._getCurrentLinkId(),this._activeBuffer.ybase+this._activeBuffer.y),this._activeBuffer.x+r-m>a)if(h){const e=f;let t=this._activeBuffer.x-m;for(this._activeBuffer.x=m,this._activeBuffer.y++,this._activeBuffer.y===this._activeBuffer.scrollBottom+1?(this._activeBuffer.y--,this._bufferService.scroll(this._eraseAttrData(),!0)):(this._activeBuffer.y>=this._bufferService.rows&&(this._activeBuffer.y=this._bufferService.rows-1),this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y).isWrapped=!0),f=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y),m>0&&f instanceof l.BufferLine&&f.copyCellsFrom(e,t,0,m,!1);t<a;)e.setCellFromCodepoint(t++,0,1,u)}else if(this._activeBuffer.x=a-1,2===r)continue;if(i&&this._activeBuffer.x){const e=f.getWidth(this._activeBuffer.x-1)?1:2;f.addCodepointToCell(this._activeBuffer.x-e,s,r);for(let e=r-m;--e>=0;)f.setCellFromCodepoint(this._activeBuffer.x++,0,0,u)}else if(d&&(f.insertCells(this._activeBuffer.x,r-m,this._activeBuffer.getNullCell(u)),2===f.getWidth(a-1)&&f.setCellFromCodepoint(a-1,_.NULL_CELL_CODE,_.NULL_CELL_WIDTH,u)),f.setCellFromCodepoint(this._activeBuffer.x++,s,r,u),r>0)for(;--r;)f.setCellFromCodepoint(this._activeBuffer.x++,0,0,u)}this._parser.precedingJoinState=v,this._activeBuffer.x<a&&i-t>0&&0===f.getWidth(this._activeBuffer.x)&&!f.hasContent(this._activeBuffer.x)&&f.setCellFromCodepoint(this._activeBuffer.x,0,1,u),this._dirtyRowTracker.markDirty(this._activeBuffer.y)}registerCsiHandler(e,t){return"t"!==e.final||e.prefix||e.intermediates?this._parser.registerCsiHandler(e,t):this._parser.registerCsiHandler(e,(e=>!w(e.params[0],this._optionsService.rawOptions.windowOptions)||t(e)))}registerDcsHandler(e,t){return this._parser.registerDcsHandler(e,new m.DcsHandler(t))}registerEscHandler(e,t){return this._parser.registerEscHandler(e,t)}registerOscHandler(e,t){return this._parser.registerOscHandler(e,new g.OscHandler(t))}bell(){return this._onRequestBell.fire(),!0}lineFeed(){return this._dirtyRowTracker.markDirty(this._activeBuffer.y),this._optionsService.rawOptions.convertEol&&(this._activeBuffer.x=0),this._activeBuffer.y++,this._activeBuffer.y===this._activeBuffer.scrollBottom+1?(this._activeBuffer.y--,this._bufferService.scroll(this._eraseAttrData())):this._activeBuffer.y>=this._bufferService.rows?this._activeBuffer.y=this._bufferService.rows-1:this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y).isWrapped=!1,this._activeBuffer.x>=this._bufferService.cols&&this._activeBuffer.x--,this._dirtyRowTracker.markDirty(this._activeBuffer.y),this._onLineFeed.fire(),!0}carriageReturn(){return this._activeBuffer.x=0,!0}backspace(){if(!this._coreService.decPrivateModes.reverseWraparound)return this._restrictCursor(),this._activeBuffer.x>0&&this._activeBuffer.x--,!0;if(this._restrictCursor(this._bufferService.cols),this._activeBuffer.x>0)this._activeBuffer.x--;else if(0===this._activeBuffer.x&&this._activeBuffer.y>this._activeBuffer.scrollTop&&this._activeBuffer.y<=this._activeBuffer.scrollBottom&&this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y)?.isWrapped){this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y).isWrapped=!1,this._activeBuffer.y--,this._activeBuffer.x=this._bufferService.cols-1;const e=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);e.hasWidth(this._activeBuffer.x)&&!e.hasContent(this._activeBuffer.x)&&this._activeBuffer.x--}return this._restrictCursor(),!0}tab(){if(this._activeBuffer.x>=this._bufferService.cols)return!0;const e=this._activeBuffer.x;return this._activeBuffer.x=this._activeBuffer.nextStop(),this._optionsService.rawOptions.screenReaderMode&&this._onA11yTab.fire(this._activeBuffer.x-e),!0}shiftOut(){return this._charsetService.setgLevel(1),!0}shiftIn(){return this._charsetService.setgLevel(0),!0}_restrictCursor(e=this._bufferService.cols-1){this._activeBuffer.x=Math.min(e,Math.max(0,this._activeBuffer.x)),this._activeBuffer.y=this._coreService.decPrivateModes.origin?Math.min(this._activeBuffer.scrollBottom,Math.max(this._activeBuffer.scrollTop,this._activeBuffer.y)):Math.min(this._bufferService.rows-1,Math.max(0,this._activeBuffer.y)),this._dirtyRowTracker.markDirty(this._activeBuffer.y)}_setCursor(e,t){this._dirtyRowTracker.markDirty(this._activeBuffer.y),this._coreService.decPrivateModes.origin?(this._activeBuffer.x=e,this._activeBuffer.y=this._activeBuffer.scrollTop+t):(this._activeBuffer.x=e,this._activeBuffer.y=t),this._restrictCursor(),this._dirtyRowTracker.markDirty(this._activeBuffer.y)}_moveCursor(e,t){this._restrictCursor(),this._setCursor(this._activeBuffer.x+e,this._activeBuffer.y+t)}cursorUp(e){const t=this._activeBuffer.y-this._activeBuffer.scrollTop;return t>=0?this._moveCursor(0,-Math.min(t,e.params[0]||1)):this._moveCursor(0,-(e.params[0]||1)),!0}cursorDown(e){const t=this._activeBuffer.scrollBottom-this._activeBuffer.y;return t>=0?this._moveCursor(0,Math.min(t,e.params[0]||1)):this._moveCursor(0,e.params[0]||1),!0}cursorForward(e){return this._moveCursor(e.params[0]||1,0),!0}cursorBackward(e){return this._moveCursor(-(e.params[0]||1),0),!0}cursorNextLine(e){return this.cursorDown(e),this._activeBuffer.x=0,!0}cursorPrecedingLine(e){return this.cursorUp(e),this._activeBuffer.x=0,!0}cursorCharAbsolute(e){return this._setCursor((e.params[0]||1)-1,this._activeBuffer.y),!0}cursorPosition(e){return this._setCursor(e.length>=2?(e.params[1]||1)-1:0,(e.params[0]||1)-1),!0}charPosAbsolute(e){return this._setCursor((e.params[0]||1)-1,this._activeBuffer.y),!0}hPositionRelative(e){return this._moveCursor(e.params[0]||1,0),!0}linePosAbsolute(e){return this._setCursor(this._activeBuffer.x,(e.params[0]||1)-1),!0}vPositionRelative(e){return this._moveCursor(0,e.params[0]||1),!0}hVPosition(e){return this.cursorPosition(e),!0}tabClear(e){const t=e.params[0];return 0===t?delete this._activeBuffer.tabs[this._activeBuffer.x]:3===t&&(this._activeBuffer.tabs={}),!0}cursorForwardTab(e){if(this._activeBuffer.x>=this._bufferService.cols)return!0;let t=e.params[0]||1;for(;t--;)this._activeBuffer.x=this._activeBuffer.nextStop();return!0}cursorBackwardTab(e){if(this._activeBuffer.x>=this._bufferService.cols)return!0;let t=e.params[0]||1;for(;t--;)this._activeBuffer.x=this._activeBuffer.prevStop();return!0}selectProtected(e){const t=e.params[0];return 1===t&&(this._curAttrData.bg|=536870912),2!==t&&0!==t||(this._curAttrData.bg&=-536870913),!0}_eraseInBufferLine(e,t,i,s=!1,r=!1){const n=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);n.replaceCells(t,i,this._activeBuffer.getNullCell(this._eraseAttrData()),r),s&&(n.isWrapped=!1)}_resetBufferLine(e,t=!1){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i&&(i.fill(this._activeBuffer.getNullCell(this._eraseAttrData()),t),this._bufferService.buffer.clearMarkers(this._activeBuffer.ybase+e),i.isWrapped=!1)}eraseInDisplay(e,t=!1){let i;switch(this._restrictCursor(this._bufferService.cols),e.params[0]){case 0:for(i=this._activeBuffer.y,this._dirtyRowTracker.markDirty(i),this._eraseInBufferLine(i++,this._activeBuffer.x,this._bufferService.cols,0===this._activeBuffer.x,t);i<this._bufferService.rows;i++)this._resetBufferLine(i,t);this._dirtyRowTracker.markDirty(i);break;case 1:for(i=this._activeBuffer.y,this._dirtyRowTracker.markDirty(i),this._eraseInBufferLine(i,0,this._activeBuffer.x+1,!0,t),this._activeBuffer.x+1>=this._bufferService.cols&&(this._activeBuffer.lines.get(i+1).isWrapped=!1);i--;)this._resetBufferLine(i,t);this._dirtyRowTracker.markDirty(0);break;case 2:for(i=this._bufferService.rows,this._dirtyRowTracker.markDirty(i-1);i--;)this._resetBufferLine(i,t);this._dirtyRowTracker.markDirty(0);break;case 3:const e=this._activeBuffer.lines.length-this._bufferService.rows;e>0&&(this._activeBuffer.lines.trimStart(e),this._activeBuffer.ybase=Math.max(this._activeBuffer.ybase-e,0),this._activeBuffer.ydisp=Math.max(this._activeBuffer.ydisp-e,0),this._onScroll.fire(0))}return!0}eraseInLine(e,t=!1){switch(this._restrictCursor(this._bufferService.cols),e.params[0]){case 0:this._eraseInBufferLine(this._activeBuffer.y,this._activeBuffer.x,this._bufferService.cols,0===this._activeBuffer.x,t);break;case 1:this._eraseInBufferLine(this._activeBuffer.y,0,this._activeBuffer.x+1,!1,t);break;case 2:this._eraseInBufferLine(this._activeBuffer.y,0,this._bufferService.cols,!0,t)}return this._dirtyRowTracker.markDirty(this._activeBuffer.y),!0}insertLines(e){this._restrictCursor();let t=e.params[0]||1;if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const i=this._activeBuffer.ybase+this._activeBuffer.y,s=this._bufferService.rows-1-this._activeBuffer.scrollBottom,r=this._bufferService.rows-1+this._activeBuffer.ybase-s+1;for(;t--;)this._activeBuffer.lines.splice(r-1,1),this._activeBuffer.lines.splice(i,0,this._activeBuffer.getBlankLine(this._eraseAttrData()));return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.y,this._activeBuffer.scrollBottom),this._activeBuffer.x=0,!0}deleteLines(e){this._restrictCursor();let t=e.params[0]||1;if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const i=this._activeBuffer.ybase+this._activeBuffer.y;let s;for(s=this._bufferService.rows-1-this._activeBuffer.scrollBottom,s=this._bufferService.rows-1+this._activeBuffer.ybase-s;t--;)this._activeBuffer.lines.splice(i,1),this._activeBuffer.lines.splice(s,0,this._activeBuffer.getBlankLine(this._eraseAttrData()));return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.y,this._activeBuffer.scrollBottom),this._activeBuffer.x=0,!0}insertChars(e){this._restrictCursor();const t=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);return t&&(t.insertCells(this._activeBuffer.x,e.params[0]||1,this._activeBuffer.getNullCell(this._eraseAttrData())),this._dirtyRowTracker.markDirty(this._activeBuffer.y)),!0}deleteChars(e){this._restrictCursor();const t=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);return t&&(t.deleteCells(this._activeBuffer.x,e.params[0]||1,this._activeBuffer.getNullCell(this._eraseAttrData())),this._dirtyRowTracker.markDirty(this._activeBuffer.y)),!0}scrollUp(e){let t=e.params[0]||1;for(;t--;)this._activeBuffer.lines.splice(this._activeBuffer.ybase+this._activeBuffer.scrollTop,1),this._activeBuffer.lines.splice(this._activeBuffer.ybase+this._activeBuffer.scrollBottom,0,this._activeBuffer.getBlankLine(this._eraseAttrData()));return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}scrollDown(e){let t=e.params[0]||1;for(;t--;)this._activeBuffer.lines.splice(this._activeBuffer.ybase+this._activeBuffer.scrollBottom,1),this._activeBuffer.lines.splice(this._activeBuffer.ybase+this._activeBuffer.scrollTop,0,this._activeBuffer.getBlankLine(l.DEFAULT_ATTR_DATA));return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}scrollLeft(e){if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const t=e.params[0]||1;for(let e=this._activeBuffer.scrollTop;e<=this._activeBuffer.scrollBottom;++e){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i.deleteCells(0,t,this._activeBuffer.getNullCell(this._eraseAttrData())),i.isWrapped=!1}return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}scrollRight(e){if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const t=e.params[0]||1;for(let e=this._activeBuffer.scrollTop;e<=this._activeBuffer.scrollBottom;++e){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i.insertCells(0,t,this._activeBuffer.getNullCell(this._eraseAttrData())),i.isWrapped=!1}return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}insertColumns(e){if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const t=e.params[0]||1;for(let e=this._activeBuffer.scrollTop;e<=this._activeBuffer.scrollBottom;++e){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i.insertCells(this._activeBuffer.x,t,this._activeBuffer.getNullCell(this._eraseAttrData())),i.isWrapped=!1}return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}deleteColumns(e){if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const t=e.params[0]||1;for(let e=this._activeBuffer.scrollTop;e<=this._activeBuffer.scrollBottom;++e){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i.deleteCells(this._activeBuffer.x,t,this._activeBuffer.getNullCell(this._eraseAttrData())),i.isWrapped=!1}return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}eraseChars(e){this._restrictCursor();const t=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);return t&&(t.replaceCells(this._activeBuffer.x,this._activeBuffer.x+(e.params[0]||1),this._activeBuffer.getNullCell(this._eraseAttrData())),this._dirtyRowTracker.markDirty(this._activeBuffer.y)),!0}repeatPrecedingCharacter(e){const t=this._parser.precedingJoinState;if(!t)return!0;const i=e.params[0]||1,s=p.UnicodeService.extractWidth(t),r=this._activeBuffer.x-s,n=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y).getString(r),o=new Uint32Array(n.length*i);let a=0;for(let e=0;e<n.length;){const t=n.codePointAt(e)||0;o[a++]=t,e+=t>65535?2:1}let h=a;for(let e=1;e<i;++e)o.copyWithin(h,0,a),h+=a;return this.print(o,0,h),!0}sendDeviceAttributesPrimary(e){return e.params[0]>0||(this._is("xterm")||this._is("rxvt-unicode")||this._is("screen")?this._coreService.triggerDataEvent(n.C0.ESC+"[?1;2c"):this._is("linux")&&this._coreService.triggerDataEvent(n.C0.ESC+"[?6c")),!0}sendDeviceAttributesSecondary(e){return e.params[0]>0||(this._is("xterm")?this._coreService.triggerDataEvent(n.C0.ESC+"[>0;276;0c"):this._is("rxvt-unicode")?this._coreService.triggerDataEvent(n.C0.ESC+"[>85;95;0c"):this._is("linux")?this._coreService.triggerDataEvent(e.params[0]+"c"):this._is("screen")&&this._coreService.triggerDataEvent(n.C0.ESC+"[>83;40003;0c")),!0}_is(e){return 0===(this._optionsService.rawOptions.termName+"").indexOf(e)}setMode(e){for(let t=0;t<e.length;t++)switch(e.params[t]){case 4:this._coreService.modes.insertMode=!0;break;case 20:this._optionsService.options.convertEol=!0}return!0}setModePrivate(e){for(let t=0;t<e.length;t++)switch(e.params[t]){case 1:this._coreService.decPrivateModes.applicationCursorKeys=!0;break;case 2:this._charsetService.setgCharset(0,o.DEFAULT_CHARSET),this._charsetService.setgCharset(1,o.DEFAULT_CHARSET),this._charsetService.setgCharset(2,o.DEFAULT_CHARSET),this._charsetService.setgCharset(3,o.DEFAULT_CHARSET);break;case 3:this._optionsService.rawOptions.windowOptions.setWinLines&&(this._bufferService.resize(132,this._bufferService.rows),this._onRequestReset.fire());break;case 6:this._coreService.decPrivateModes.origin=!0,this._setCursor(0,0);break;case 7:this._coreService.decPrivateModes.wraparound=!0;break;case 12:this._optionsService.options.cursorBlink=!0;break;case 45:this._coreService.decPrivateModes.reverseWraparound=!0;break;case 66:this._logService.debug("Serial port requested application keypad."),this._coreService.decPrivateModes.applicationKeypad=!0,this._onRequestSyncScrollBar.fire();break;case 9:this._coreMouseService.activeProtocol="X10";break;case 1e3:this._coreMouseService.activeProtocol="VT200";break;case 1002:this._coreMouseService.activeProtocol="DRAG";break;case 1003:this._coreMouseService.activeProtocol="ANY";break;case 1004:this._coreService.decPrivateModes.sendFocus=!0,this._onRequestSendFocus.fire();break;case 1005:this._logService.debug("DECSET 1005 not supported (see #2507)");break;case 1006:this._coreMouseService.activeEncoding="SGR";break;case 1015:this._logService.debug("DECSET 1015 not supported (see #2507)");break;case 1016:this._coreMouseService.activeEncoding="SGR_PIXELS";break;case 25:this._coreService.isCursorHidden=!1;break;case 1048:this.saveCursor();break;case 1049:this.saveCursor();case 47:case 1047:this._bufferService.buffers.activateAltBuffer(this._eraseAttrData()),this._coreService.isCursorInitialized=!0,this._onRequestRefreshRows.fire(0,this._bufferService.rows-1),this._onRequestSyncScrollBar.fire();break;case 2004:this._coreService.decPrivateModes.bracketedPasteMode=!0}return!0}resetMode(e){for(let t=0;t<e.length;t++)switch(e.params[t]){case 4:this._coreService.modes.insertMode=!1;break;case 20:this._optionsService.options.convertEol=!1}return!0}resetModePrivate(e){for(let t=0;t<e.length;t++)switch(e.params[t]){case 1:this._coreService.decPrivateModes.applicationCursorKeys=!1;break;case 3:this._optionsService.rawOptions.windowOptions.setWinLines&&(this._bufferService.resize(80,this._bufferService.rows),this._onRequestReset.fire());break;case 6:this._coreService.decPrivateModes.origin=!1,this._setCursor(0,0);break;case 7:this._coreService.decPrivateModes.wraparound=!1;break;case 12:this._optionsService.options.cursorBlink=!1;break;case 45:this._coreService.decPrivateModes.reverseWraparound=!1;break;case 66:this._logService.debug("Switching back to normal keypad."),this._coreService.decPrivateModes.applicationKeypad=!1,this._onRequestSyncScrollBar.fire();break;case 9:case 1e3:case 1002:case 1003:this._coreMouseService.activeProtocol="NONE";break;case 1004:this._coreService.decPrivateModes.sendFocus=!1;break;case 1005:this._logService.debug("DECRST 1005 not supported (see #2507)");break;case 1006:case 1016:this._coreMouseService.activeEncoding="DEFAULT";break;case 1015:this._logService.debug("DECRST 1015 not supported (see #2507)");break;case 25:this._coreService.isCursorHidden=!0;break;case 1048:this.restoreCursor();break;case 1049:case 47:case 1047:this._bufferService.buffers.activateNormalBuffer(),1049===e.params[t]&&this.restoreCursor(),this._coreService.isCursorInitialized=!0,this._onRequestRefreshRows.fire(0,this._bufferService.rows-1),this._onRequestSyncScrollBar.fire();break;case 2004:this._coreService.decPrivateModes.bracketedPasteMode=!1}return!0}requestMode(e,t){const i=this._coreService.decPrivateModes,{activeProtocol:s,activeEncoding:r}=this._coreMouseService,o=this._coreService,{buffers:a,cols:h}=this._bufferService,{active:c,alt:l}=a,d=this._optionsService.rawOptions,_=e=>e?1:2,u=e.params[0];return f=u,v=t?2===u?4:4===u?_(o.modes.insertMode):12===u?3:20===u?_(d.convertEol):0:1===u?_(i.applicationCursorKeys):3===u?d.windowOptions.setWinLines?80===h?2:132===h?1:0:0:6===u?_(i.origin):7===u?_(i.wraparound):8===u?3:9===u?_("X10"===s):12===u?_(d.cursorBlink):25===u?_(!o.isCursorHidden):45===u?_(i.reverseWraparound):66===u?_(i.applicationKeypad):67===u?4:1e3===u?_("VT200"===s):1002===u?_("DRAG"===s):1003===u?_("ANY"===s):1004===u?_(i.sendFocus):1005===u?4:1006===u?_("SGR"===r):1015===u?4:1016===u?_("SGR_PIXELS"===r):1048===u?1:47===u||1047===u||1049===u?_(c===l):2004===u?_(i.bracketedPasteMode):0,o.triggerDataEvent(`${n.C0.ESC}[${t?"":"?"}${f};${v}$y`),!0;var f,v}_updateAttrColor(e,t,i,s,r){return 2===t?(e|=50331648,e&=-16777216,e|=f.AttributeData.fromColorRGB([i,s,r])):5===t&&(e&=-50331904,e|=33554432|255&i),e}_extractColor(e,t,i){const s=[0,0,-1,0,0,0];let r=0,n=0;do{if(s[n+r]=e.params[t+n],e.hasSubParams(t+n)){const i=e.getSubParams(t+n);let o=0;do{5===s[1]&&(r=1),s[n+o+1+r]=i[o]}while(++o<i.length&&o+n+1+r<s.length);break}if(5===s[1]&&n+r>=2||2===s[1]&&n+r>=5)break;s[1]&&(r=1)}while(++n+t<e.length&&n+r<s.length);for(let e=2;e<s.length;++e)-1===s[e]&&(s[e]=0);switch(s[0]){case 38:i.fg=this._updateAttrColor(i.fg,s[1],s[3],s[4],s[5]);break;case 48:i.bg=this._updateAttrColor(i.bg,s[1],s[3],s[4],s[5]);break;case 58:i.extended=i.extended.clone(),i.extended.underlineColor=this._updateAttrColor(i.extended.underlineColor,s[1],s[3],s[4],s[5])}return n}_processUnderline(e,t){t.extended=t.extended.clone(),(!~e||e>5)&&(e=1),t.extended.underlineStyle=e,t.fg|=268435456,0===e&&(t.fg&=-268435457),t.updateExtended()}_processSGR0(e){e.fg=l.DEFAULT_ATTR_DATA.fg,e.bg=l.DEFAULT_ATTR_DATA.bg,e.extended=e.extended.clone(),e.extended.underlineStyle=0,e.extended.underlineColor&=-67108864,e.updateExtended()}charAttributes(e){if(1===e.length&&0===e.params[0])return this._processSGR0(this._curAttrData),!0;const t=e.length;let i;const s=this._curAttrData;for(let r=0;r<t;r++)i=e.params[r],i>=30&&i<=37?(s.fg&=-50331904,s.fg|=16777216|i-30):i>=40&&i<=47?(s.bg&=-50331904,s.bg|=16777216|i-40):i>=90&&i<=97?(s.fg&=-50331904,s.fg|=16777224|i-90):i>=100&&i<=107?(s.bg&=-50331904,s.bg|=16777224|i-100):0===i?this._processSGR0(s):1===i?s.fg|=134217728:3===i?s.bg|=67108864:4===i?(s.fg|=268435456,this._processUnderline(e.hasSubParams(r)?e.getSubParams(r)[0]:1,s)):5===i?s.fg|=536870912:7===i?s.fg|=67108864:8===i?s.fg|=1073741824:9===i?s.fg|=2147483648:2===i?s.bg|=134217728:21===i?this._processUnderline(2,s):22===i?(s.fg&=-134217729,s.bg&=-134217729):23===i?s.bg&=-67108865:24===i?(s.fg&=-268435457,this._processUnderline(0,s)):25===i?s.fg&=-536870913:27===i?s.fg&=-67108865:28===i?s.fg&=-1073741825:29===i?s.fg&=2147483647:39===i?(s.fg&=-67108864,s.fg|=16777215&l.DEFAULT_ATTR_DATA.fg):49===i?(s.bg&=-67108864,s.bg|=16777215&l.DEFAULT_ATTR_DATA.bg):38===i||48===i||58===i?r+=this._extractColor(e,r,s):53===i?s.bg|=1073741824:55===i?s.bg&=-1073741825:59===i?(s.extended=s.extended.clone(),s.extended.underlineColor=-1,s.updateExtended()):100===i?(s.fg&=-67108864,s.fg|=16777215&l.DEFAULT_ATTR_DATA.fg,s.bg&=-67108864,s.bg|=16777215&l.DEFAULT_ATTR_DATA.bg):this._logService.debug("Unknown SGR attribute: %d.",i);return!0}deviceStatus(e){switch(e.params[0]){case 5:this._coreService.triggerDataEvent(`${n.C0.ESC}[0n`);break;case 6:const e=this._activeBuffer.y+1,t=this._activeBuffer.x+1;this._coreService.triggerDataEvent(`${n.C0.ESC}[${e};${t}R`)}return!0}deviceStatusPrivate(e){if(6===e.params[0]){const e=this._activeBuffer.y+1,t=this._activeBuffer.x+1;this._coreService.triggerDataEvent(`${n.C0.ESC}[?${e};${t}R`)}return!0}softReset(e){return this._coreService.isCursorHidden=!1,this._onRequestSyncScrollBar.fire(),this._activeBuffer.scrollTop=0,this._activeBuffer.scrollBottom=this._bufferService.rows-1,this._curAttrData=l.DEFAULT_ATTR_DATA.clone(),this._coreService.reset(),this._charsetService.reset(),this._activeBuffer.savedX=0,this._activeBuffer.savedY=this._activeBuffer.ybase,this._activeBuffer.savedCurAttrData.fg=this._curAttrData.fg,this._activeBuffer.savedCurAttrData.bg=this._curAttrData.bg,this._activeBuffer.savedCharset=this._charsetService.charset,this._coreService.decPrivateModes.origin=!1,!0}setCursorStyle(e){const t=e.params[0]||1;switch(t){case 1:case 2:this._optionsService.options.cursorStyle="block";break;case 3:case 4:this._optionsService.options.cursorStyle="underline";break;case 5:case 6:this._optionsService.options.cursorStyle="bar"}const i=t%2==1;return this._optionsService.options.cursorBlink=i,!0}setScrollRegion(e){const t=e.params[0]||1;let i;return(e.length<2||(i=e.params[1])>this._bufferService.rows||0===i)&&(i=this._bufferService.rows),i>t&&(this._activeBuffer.scrollTop=t-1,this._activeBuffer.scrollBottom=i-1,this._setCursor(0,0)),!0}windowOptions(e){if(!w(e.params[0],this._optionsService.rawOptions.windowOptions))return!0;const t=e.length>1?e.params[1]:0;switch(e.params[0]){case 14:2!==t&&this._onRequestWindowsOptionsReport.fire(y.GET_WIN_SIZE_PIXELS);break;case 16:this._onRequestWindowsOptionsReport.fire(y.GET_CELL_SIZE_PIXELS);break;case 18:this._bufferService&&this._coreService.triggerDataEvent(`${n.C0.ESC}[8;${this._bufferService.rows};${this._bufferService.cols}t`);break;case 22:0!==t&&2!==t||(this._windowTitleStack.push(this._windowTitle),this._windowTitleStack.length>10&&this._windowTitleStack.shift()),0!==t&&1!==t||(this._iconNameStack.push(this._iconName),this._iconNameStack.length>10&&this._iconNameStack.shift());break;case 23:0!==t&&2!==t||this._windowTitleStack.length&&this.setTitle(this._windowTitleStack.pop()),0!==t&&1!==t||this._iconNameStack.length&&this.setIconName(this._iconNameStack.pop())}return!0}saveCursor(e){return this._activeBuffer.savedX=this._activeBuffer.x,this._activeBuffer.savedY=this._activeBuffer.ybase+this._activeBuffer.y,this._activeBuffer.savedCurAttrData.fg=this._curAttrData.fg,this._activeBuffer.savedCurAttrData.bg=this._curAttrData.bg,this._activeBuffer.savedCharset=this._charsetService.charset,!0}restoreCursor(e){return this._activeBuffer.x=this._activeBuffer.savedX||0,this._activeBuffer.y=Math.max(this._activeBuffer.savedY-this._activeBuffer.ybase,0),this._curAttrData.fg=this._activeBuffer.savedCurAttrData.fg,this._curAttrData.bg=this._activeBuffer.savedCurAttrData.bg,this._charsetService.charset=this._savedCharset,this._activeBuffer.savedCharset&&(this._charsetService.charset=this._activeBuffer.savedCharset),this._restrictCursor(),!0}setTitle(e){return this._windowTitle=e,this._onTitleChange.fire(e),!0}setIconName(e){return this._iconName=e,!0}setOrReportIndexedColor(e){const t=[],i=e.split(";");for(;i.length>1;){const e=i.shift(),s=i.shift();if(/^\\d+$/.exec(e)){const i=parseInt(e);if(D(i))if("?"===s)t.push({type:0,index:i});else{const e=(0,S.parseColor)(s);e&&t.push({type:1,index:i,color:e})}}}return t.length&&this._onColor.fire(t),!0}setHyperlink(e){const t=e.split(";");return!(t.length<2)&&(t[1]?this._createHyperlink(t[0],t[1]):!t[0]&&this._finishHyperlink())}_createHyperlink(e,t){this._getCurrentLinkId()&&this._finishHyperlink();const i=e.split(":");let s;const r=i.findIndex((e=>e.startsWith("id=")));return-1!==r&&(s=i[r].slice(3)||void 0),this._curAttrData.extended=this._curAttrData.extended.clone(),this._curAttrData.extended.urlId=this._oscLinkService.registerLink({id:s,uri:t}),this._curAttrData.updateExtended(),!0}_finishHyperlink(){return this._curAttrData.extended=this._curAttrData.extended.clone(),this._curAttrData.extended.urlId=0,this._curAttrData.updateExtended(),!0}_setOrReportSpecialColor(e,t){const i=e.split(";");for(let e=0;e<i.length&&!(t>=this._specialColors.length);++e,++t)if("?"===i[e])this._onColor.fire([{type:0,index:this._specialColors[t]}]);else{const s=(0,S.parseColor)(i[e]);s&&this._onColor.fire([{type:1,index:this._specialColors[t],color:s}])}return!0}setOrReportFgColor(e){return this._setOrReportSpecialColor(e,0)}setOrReportBgColor(e){return this._setOrReportSpecialColor(e,1)}setOrReportCursorColor(e){return this._setOrReportSpecialColor(e,2)}restoreIndexedColor(e){if(!e)return this._onColor.fire([{type:2}]),!0;const t=[],i=e.split(";");for(let e=0;e<i.length;++e)if(/^\\d+$/.exec(i[e])){const s=parseInt(i[e]);D(s)&&t.push({type:2,index:s})}return t.length&&this._onColor.fire(t),!0}restoreFgColor(e){return this._onColor.fire([{type:2,index:256}]),!0}restoreBgColor(e){return this._onColor.fire([{type:2,index:257}]),!0}restoreCursorColor(e){return this._onColor.fire([{type:2,index:258}]),!0}nextLine(){return this._activeBuffer.x=0,this.index(),!0}keypadApplicationMode(){return this._logService.debug("Serial port requested application keypad."),this._coreService.decPrivateModes.applicationKeypad=!0,this._onRequestSyncScrollBar.fire(),!0}keypadNumericMode(){return this._logService.debug("Switching back to normal keypad."),this._coreService.decPrivateModes.applicationKeypad=!1,this._onRequestSyncScrollBar.fire(),!0}selectDefaultCharset(){return this._charsetService.setgLevel(0),this._charsetService.setgCharset(0,o.DEFAULT_CHARSET),!0}selectCharset(e){return 2!==e.length?(this.selectDefaultCharset(),!0):("/"===e[0]||this._charsetService.setgCharset(C[e[0]],o.CHARSETS[e[1]]||o.DEFAULT_CHARSET),!0)}index(){return this._restrictCursor(),this._activeBuffer.y++,this._activeBuffer.y===this._activeBuffer.scrollBottom+1?(this._activeBuffer.y--,this._bufferService.scroll(this._eraseAttrData())):this._activeBuffer.y>=this._bufferService.rows&&(this._activeBuffer.y=this._bufferService.rows-1),this._restrictCursor(),!0}tabSet(){return this._activeBuffer.tabs[this._activeBuffer.x]=!0,!0}reverseIndex(){if(this._restrictCursor(),this._activeBuffer.y===this._activeBuffer.scrollTop){const e=this._activeBuffer.scrollBottom-this._activeBuffer.scrollTop;this._activeBuffer.lines.shiftElements(this._activeBuffer.ybase+this._activeBuffer.y,e,1),this._activeBuffer.lines.set(this._activeBuffer.ybase+this._activeBuffer.y,this._activeBuffer.getBlankLine(this._eraseAttrData())),this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom)}else this._activeBuffer.y--,this._restrictCursor();return!0}fullReset(){return this._parser.reset(),this._onRequestReset.fire(),!0}reset(){this._curAttrData=l.DEFAULT_ATTR_DATA.clone(),this._eraseAttrDataInternal=l.DEFAULT_ATTR_DATA.clone()}_eraseAttrData(){return this._eraseAttrDataInternal.bg&=-67108864,this._eraseAttrDataInternal.bg|=67108863&this._curAttrData.bg,this._eraseAttrDataInternal}setgLevel(e){return this._charsetService.setgLevel(e),!0}screenAlignmentPattern(){const e=new u.CellData;e.content=1<<22|"E".charCodeAt(0),e.fg=this._curAttrData.fg,e.bg=this._curAttrData.bg,this._setCursor(0,0);for(let t=0;t<this._bufferService.rows;++t){const i=this._activeBuffer.ybase+this._activeBuffer.y+t,s=this._activeBuffer.lines.get(i);s&&(s.fill(e),s.isWrapped=!1)}return this._dirtyRowTracker.markAllDirty(),this._setCursor(0,0),!0}requestStatusString(e,t){const i=this._bufferService.buffer,s=this._optionsService.rawOptions;return(e=>(this._coreService.triggerDataEvent(`${n.C0.ESC}${e}${n.C0.ESC}\\\\`),!0))(\'"q\'===e?`P1$r${this._curAttrData.isProtected()?1:0}"q`:\'"p\'===e?\'P1$r61;1"p\':"r"===e?`P1$r${i.scrollTop+1};${i.scrollBottom+1}r`:"m"===e?"P1$r0m":" q"===e?`P1$r${{block:2,underline:4,bar:6}[s.cursorStyle]-(s.cursorBlink?1:0)} q`:"P0$r")}markRangeDirty(e,t){this._dirtyRowTracker.markRangeDirty(e,t)}}t.InputHandler=k;let L=class{constructor(e){this._bufferService=e,this.clearRange()}clearRange(){this.start=this._bufferService.buffer.y,this.end=this._bufferService.buffer.y}markDirty(e){e<this.start?this.start=e:e>this.end&&(this.end=e)}markRangeDirty(e,t){e>t&&(E=e,e=t,t=E),e<this.start&&(this.start=e),t>this.end&&(this.end=t)}markAllDirty(){this.markRangeDirty(0,this._bufferService.rows-1)}};function D(e){return 0<=e&&e<256}L=s([r(0,v.IBufferService)],L)},844:(e,t)=>{function i(e){for(const t of e)t.dispose();e.length=0}Object.defineProperty(t,"__esModule",{value:!0}),t.getDisposeArrayDisposable=t.disposeArray=t.toDisposable=t.MutableDisposable=t.Disposable=void 0,t.Disposable=class{constructor(){this._disposables=[],this._isDisposed=!1}dispose(){this._isDisposed=!0;for(const e of this._disposables)e.dispose();this._disposables.length=0}register(e){return this._disposables.push(e),e}unregister(e){const t=this._disposables.indexOf(e);-1!==t&&this._disposables.splice(t,1)}},t.MutableDisposable=class{constructor(){this._isDisposed=!1}get value(){return this._isDisposed?void 0:this._value}set value(e){this._isDisposed||e===this._value||(this._value?.dispose(),this._value=e)}clear(){this.value=void 0}dispose(){this._isDisposed=!0,this._value?.dispose(),this._value=void 0}},t.toDisposable=function(e){return{dispose:e}},t.disposeArray=i,t.getDisposeArrayDisposable=function(e){return{dispose:()=>i(e)}}},1505:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.FourKeyMap=t.TwoKeyMap=void 0;class i{constructor(){this._data={}}set(e,t,i){this._data[e]||(this._data[e]={}),this._data[e][t]=i}get(e,t){return this._data[e]?this._data[e][t]:void 0}clear(){this._data={}}}t.TwoKeyMap=i,t.FourKeyMap=class{constructor(){this._data=new i}set(e,t,s,r,n){this._data.get(e,t)||this._data.set(e,t,new i),this._data.get(e,t).set(s,r,n)}get(e,t,i,s){return this._data.get(e,t)?.get(i,s)}clear(){this._data.clear()}}},6114:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.isChromeOS=t.isLinux=t.isWindows=t.isIphone=t.isIpad=t.isMac=t.getSafariVersion=t.isSafari=t.isLegacyEdge=t.isFirefox=t.isNode=void 0,t.isNode="undefined"!=typeof process&&"title"in process;const i=t.isNode?"node":navigator.userAgent,s=t.isNode?"node":navigator.platform;t.isFirefox=i.includes("Firefox"),t.isLegacyEdge=i.includes("Edge"),t.isSafari=/^((?!chrome|android).)*safari/i.test(i),t.getSafariVersion=function(){if(!t.isSafari)return 0;const e=i.match(/Version\\/(\\d+)/);return null===e||e.length<2?0:parseInt(e[1])},t.isMac=["Macintosh","MacIntel","MacPPC","Mac68K"].includes(s),t.isIpad="iPad"===s,t.isIphone="iPhone"===s,t.isWindows=["Windows","Win16","Win32","WinCE"].includes(s),t.isLinux=s.indexOf("Linux")>=0,t.isChromeOS=/\\bCrOS\\b/.test(i)},6106:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.SortedList=void 0;let i=0;t.SortedList=class{constructor(e){this._getKey=e,this._array=[]}clear(){this._array.length=0}insert(e){0!==this._array.length?(i=this._search(this._getKey(e)),this._array.splice(i,0,e)):this._array.push(e)}delete(e){if(0===this._array.length)return!1;const t=this._getKey(e);if(void 0===t)return!1;if(i=this._search(t),-1===i)return!1;if(this._getKey(this._array[i])!==t)return!1;do{if(this._array[i]===e)return this._array.splice(i,1),!0}while(++i<this._array.length&&this._getKey(this._array[i])===t);return!1}*getKeyIterator(e){if(0!==this._array.length&&(i=this._search(e),!(i<0||i>=this._array.length)&&this._getKey(this._array[i])===e))do{yield this._array[i]}while(++i<this._array.length&&this._getKey(this._array[i])===e)}forEachByKey(e,t){if(0!==this._array.length&&(i=this._search(e),!(i<0||i>=this._array.length)&&this._getKey(this._array[i])===e))do{t(this._array[i])}while(++i<this._array.length&&this._getKey(this._array[i])===e)}values(){return[...this._array].values()}_search(e){let t=0,i=this._array.length-1;for(;i>=t;){let s=t+i>>1;const r=this._getKey(this._array[s]);if(r>e)i=s-1;else{if(!(r<e)){for(;s>0&&this._getKey(this._array[s-1])===e;)s--;return s}t=s+1}}return t}}},7226:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DebouncedIdleTask=t.IdleTaskQueue=t.PriorityTaskQueue=void 0;const s=i(6114);class r{constructor(){this._tasks=[],this._i=0}enqueue(e){this._tasks.push(e),this._start()}flush(){for(;this._i<this._tasks.length;)this._tasks[this._i]()||this._i++;this.clear()}clear(){this._idleCallback&&(this._cancelCallback(this._idleCallback),this._idleCallback=void 0),this._i=0,this._tasks.length=0}_start(){this._idleCallback||(this._idleCallback=this._requestCallback(this._process.bind(this)))}_process(e){this._idleCallback=void 0;let t=0,i=0,s=e.timeRemaining(),r=0;for(;this._i<this._tasks.length;){if(t=Date.now(),this._tasks[this._i]()||this._i++,t=Math.max(1,Date.now()-t),i=Math.max(t,i),r=e.timeRemaining(),1.5*i>r)return s-t<-20&&console.warn(`task queue exceeded allotted deadline by ${Math.abs(Math.round(s-t))}ms`),void this._start();s=r}this.clear()}}class n extends r{_requestCallback(e){return setTimeout((()=>e(this._createDeadline(16))))}_cancelCallback(e){clearTimeout(e)}_createDeadline(e){const t=Date.now()+e;return{timeRemaining:()=>Math.max(0,t-Date.now())}}}t.PriorityTaskQueue=n,t.IdleTaskQueue=!s.isNode&&"requestIdleCallback"in window?class extends r{_requestCallback(e){return requestIdleCallback(e)}_cancelCallback(e){cancelIdleCallback(e)}}:n,t.DebouncedIdleTask=class{constructor(){this._queue=new t.IdleTaskQueue}set(e){this._queue.clear(),this._queue.enqueue(e)}flush(){this._queue.flush()}}},9282:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.updateWindowsModeWrappedState=void 0;const s=i(643);t.updateWindowsModeWrappedState=function(e){const t=e.buffer.lines.get(e.buffer.ybase+e.buffer.y-1),i=t?.get(e.cols-1),r=e.buffer.lines.get(e.buffer.ybase+e.buffer.y);r&&i&&(r.isWrapped=i[s.CHAR_DATA_CODE_INDEX]!==s.NULL_CELL_CODE&&i[s.CHAR_DATA_CODE_INDEX]!==s.WHITESPACE_CELL_CODE)}},3734:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ExtendedAttrs=t.AttributeData=void 0;class i{constructor(){this.fg=0,this.bg=0,this.extended=new s}static toColorRGB(e){return[e>>>16&255,e>>>8&255,255&e]}static fromColorRGB(e){return(255&e[0])<<16|(255&e[1])<<8|255&e[2]}clone(){const e=new i;return e.fg=this.fg,e.bg=this.bg,e.extended=this.extended.clone(),e}isInverse(){return 67108864&this.fg}isBold(){return 134217728&this.fg}isUnderline(){return this.hasExtendedAttrs()&&0!==this.extended.underlineStyle?1:268435456&this.fg}isBlink(){return 536870912&this.fg}isInvisible(){return 1073741824&this.fg}isItalic(){return 67108864&this.bg}isDim(){return 134217728&this.bg}isStrikethrough(){return 2147483648&this.fg}isProtected(){return 536870912&this.bg}isOverline(){return 1073741824&this.bg}getFgColorMode(){return 50331648&this.fg}getBgColorMode(){return 50331648&this.bg}isFgRGB(){return 50331648==(50331648&this.fg)}isBgRGB(){return 50331648==(50331648&this.bg)}isFgPalette(){return 16777216==(50331648&this.fg)||33554432==(50331648&this.fg)}isBgPalette(){return 16777216==(50331648&this.bg)||33554432==(50331648&this.bg)}isFgDefault(){return 0==(50331648&this.fg)}isBgDefault(){return 0==(50331648&this.bg)}isAttributeDefault(){return 0===this.fg&&0===this.bg}getFgColor(){switch(50331648&this.fg){case 16777216:case 33554432:return 255&this.fg;case 50331648:return 16777215&this.fg;default:return-1}}getBgColor(){switch(50331648&this.bg){case 16777216:case 33554432:return 255&this.bg;case 50331648:return 16777215&this.bg;default:return-1}}hasExtendedAttrs(){return 268435456&this.bg}updateExtended(){this.extended.isEmpty()?this.bg&=-268435457:this.bg|=268435456}getUnderlineColor(){if(268435456&this.bg&&~this.extended.underlineColor)switch(50331648&this.extended.underlineColor){case 16777216:case 33554432:return 255&this.extended.underlineColor;case 50331648:return 16777215&this.extended.underlineColor;default:return this.getFgColor()}return this.getFgColor()}getUnderlineColorMode(){return 268435456&this.bg&&~this.extended.underlineColor?50331648&this.extended.underlineColor:this.getFgColorMode()}isUnderlineColorRGB(){return 268435456&this.bg&&~this.extended.underlineColor?50331648==(50331648&this.extended.underlineColor):this.isFgRGB()}isUnderlineColorPalette(){return 268435456&this.bg&&~this.extended.underlineColor?16777216==(50331648&this.extended.underlineColor)||33554432==(50331648&this.extended.underlineColor):this.isFgPalette()}isUnderlineColorDefault(){return 268435456&this.bg&&~this.extended.underlineColor?0==(50331648&this.extended.underlineColor):this.isFgDefault()}getUnderlineStyle(){return 268435456&this.fg?268435456&this.bg?this.extended.underlineStyle:1:0}getUnderlineVariantOffset(){return this.extended.underlineVariantOffset}}t.AttributeData=i;class s{get ext(){return this._urlId?-469762049&this._ext|this.underlineStyle<<26:this._ext}set ext(e){this._ext=e}get underlineStyle(){return this._urlId?5:(469762048&this._ext)>>26}set underlineStyle(e){this._ext&=-469762049,this._ext|=e<<26&469762048}get underlineColor(){return 67108863&this._ext}set underlineColor(e){this._ext&=-67108864,this._ext|=67108863&e}get urlId(){return this._urlId}set urlId(e){this._urlId=e}get underlineVariantOffset(){const e=(3758096384&this._ext)>>29;return e<0?4294967288^e:e}set underlineVariantOffset(e){this._ext&=536870911,this._ext|=e<<29&3758096384}constructor(e=0,t=0){this._ext=0,this._urlId=0,this._ext=e,this._urlId=t}clone(){return new s(this._ext,this._urlId)}isEmpty(){return 0===this.underlineStyle&&0===this._urlId}}t.ExtendedAttrs=s},9092:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Buffer=t.MAX_BUFFER_SIZE=void 0;const s=i(6349),r=i(7226),n=i(3734),o=i(8437),a=i(4634),h=i(511),c=i(643),l=i(4863),d=i(7116);t.MAX_BUFFER_SIZE=4294967295,t.Buffer=class{constructor(e,t,i){this._hasScrollback=e,this._optionsService=t,this._bufferService=i,this.ydisp=0,this.ybase=0,this.y=0,this.x=0,this.tabs={},this.savedY=0,this.savedX=0,this.savedCurAttrData=o.DEFAULT_ATTR_DATA.clone(),this.savedCharset=d.DEFAULT_CHARSET,this.markers=[],this._nullCell=h.CellData.fromCharData([0,c.NULL_CELL_CHAR,c.NULL_CELL_WIDTH,c.NULL_CELL_CODE]),this._whitespaceCell=h.CellData.fromCharData([0,c.WHITESPACE_CELL_CHAR,c.WHITESPACE_CELL_WIDTH,c.WHITESPACE_CELL_CODE]),this._isClearing=!1,this._memoryCleanupQueue=new r.IdleTaskQueue,this._memoryCleanupPosition=0,this._cols=this._bufferService.cols,this._rows=this._bufferService.rows,this.lines=new s.CircularList(this._getCorrectBufferLength(this._rows)),this.scrollTop=0,this.scrollBottom=this._rows-1,this.setupTabStops()}getNullCell(e){return e?(this._nullCell.fg=e.fg,this._nullCell.bg=e.bg,this._nullCell.extended=e.extended):(this._nullCell.fg=0,this._nullCell.bg=0,this._nullCell.extended=new n.ExtendedAttrs),this._nullCell}getWhitespaceCell(e){return e?(this._whitespaceCell.fg=e.fg,this._whitespaceCell.bg=e.bg,this._whitespaceCell.extended=e.extended):(this._whitespaceCell.fg=0,this._whitespaceCell.bg=0,this._whitespaceCell.extended=new n.ExtendedAttrs),this._whitespaceCell}getBlankLine(e,t){return new o.BufferLine(this._bufferService.cols,this.getNullCell(e),t)}get hasScrollback(){return this._hasScrollback&&this.lines.maxLength>this._rows}get isCursorInViewport(){const e=this.ybase+this.y-this.ydisp;return e>=0&&e<this._rows}_getCorrectBufferLength(e){if(!this._hasScrollback)return e;const i=e+this._optionsService.rawOptions.scrollback;return i>t.MAX_BUFFER_SIZE?t.MAX_BUFFER_SIZE:i}fillViewportRows(e){if(0===this.lines.length){void 0===e&&(e=o.DEFAULT_ATTR_DATA);let t=this._rows;for(;t--;)this.lines.push(this.getBlankLine(e))}}clear(){this.ydisp=0,this.ybase=0,this.y=0,this.x=0,this.lines=new s.CircularList(this._getCorrectBufferLength(this._rows)),this.scrollTop=0,this.scrollBottom=this._rows-1,this.setupTabStops()}resize(e,t){const i=this.getNullCell(o.DEFAULT_ATTR_DATA);let s=0;const r=this._getCorrectBufferLength(t);if(r>this.lines.maxLength&&(this.lines.maxLength=r),this.lines.length>0){if(this._cols<e)for(let t=0;t<this.lines.length;t++)s+=+this.lines.get(t).resize(e,i);let n=0;if(this._rows<t)for(let s=this._rows;s<t;s++)this.lines.length<t+this.ybase&&(this._optionsService.rawOptions.windowsMode||void 0!==this._optionsService.rawOptions.windowsPty.backend||void 0!==this._optionsService.rawOptions.windowsPty.buildNumber?this.lines.push(new o.BufferLine(e,i)):this.ybase>0&&this.lines.length<=this.ybase+this.y+n+1?(this.ybase--,n++,this.ydisp>0&&this.ydisp--):this.lines.push(new o.BufferLine(e,i)));else for(let e=this._rows;e>t;e--)this.lines.length>t+this.ybase&&(this.lines.length>this.ybase+this.y+1?this.lines.pop():(this.ybase++,this.ydisp++));if(r<this.lines.maxLength){const e=this.lines.length-r;e>0&&(this.lines.trimStart(e),this.ybase=Math.max(this.ybase-e,0),this.ydisp=Math.max(this.ydisp-e,0),this.savedY=Math.max(this.savedY-e,0)),this.lines.maxLength=r}this.x=Math.min(this.x,e-1),this.y=Math.min(this.y,t-1),n&&(this.y+=n),this.savedX=Math.min(this.savedX,e-1),this.scrollTop=0}if(this.scrollBottom=t-1,this._isReflowEnabled&&(this._reflow(e,t),this._cols>e))for(let t=0;t<this.lines.length;t++)s+=+this.lines.get(t).resize(e,i);this._cols=e,this._rows=t,this._memoryCleanupQueue.clear(),s>.1*this.lines.length&&(this._memoryCleanupPosition=0,this._memoryCleanupQueue.enqueue((()=>this._batchedMemoryCleanup())))}_batchedMemoryCleanup(){let e=!0;this._memoryCleanupPosition>=this.lines.length&&(this._memoryCleanupPosition=0,e=!1);let t=0;for(;this._memoryCleanupPosition<this.lines.length;)if(t+=this.lines.get(this._memoryCleanupPosition++).cleanupMemory(),t>100)return!0;return e}get _isReflowEnabled(){const e=this._optionsService.rawOptions.windowsPty;return e&&e.buildNumber?this._hasScrollback&&"conpty"===e.backend&&e.buildNumber>=21376:this._hasScrollback&&!this._optionsService.rawOptions.windowsMode}_reflow(e,t){this._cols!==e&&(e>this._cols?this._reflowLarger(e,t):this._reflowSmaller(e,t))}_reflowLarger(e,t){const i=(0,a.reflowLargerGetLinesToRemove)(this.lines,this._cols,e,this.ybase+this.y,this.getNullCell(o.DEFAULT_ATTR_DATA));if(i.length>0){const s=(0,a.reflowLargerCreateNewLayout)(this.lines,i);(0,a.reflowLargerApplyNewLayout)(this.lines,s.layout),this._reflowLargerAdjustViewport(e,t,s.countRemoved)}}_reflowLargerAdjustViewport(e,t,i){const s=this.getNullCell(o.DEFAULT_ATTR_DATA);let r=i;for(;r-- >0;)0===this.ybase?(this.y>0&&this.y--,this.lines.length<t&&this.lines.push(new o.BufferLine(e,s))):(this.ydisp===this.ybase&&this.ydisp--,this.ybase--);this.savedY=Math.max(this.savedY-i,0)}_reflowSmaller(e,t){const i=this.getNullCell(o.DEFAULT_ATTR_DATA),s=[];let r=0;for(let n=this.lines.length-1;n>=0;n--){let h=this.lines.get(n);if(!h||!h.isWrapped&&h.getTrimmedLength()<=e)continue;const c=[h];for(;h.isWrapped&&n>0;)h=this.lines.get(--n),c.unshift(h);const l=this.ybase+this.y;if(l>=n&&l<n+c.length)continue;const d=c[c.length-1].getTrimmedLength(),_=(0,a.reflowSmallerGetNewLineLengths)(c,this._cols,e),u=_.length-c.length;let f;f=0===this.ybase&&this.y!==this.lines.length-1?Math.max(0,this.y-this.lines.maxLength+u):Math.max(0,this.lines.length-this.lines.maxLength+u);const v=[];for(let e=0;e<u;e++){const e=this.getBlankLine(o.DEFAULT_ATTR_DATA,!0);v.push(e)}v.length>0&&(s.push({start:n+c.length+r,newLines:v}),r+=v.length),c.push(...v);let p=_.length-1,g=_[p];0===g&&(p--,g=_[p]);let m=c.length-u-1,S=d;for(;m>=0;){const e=Math.min(S,g);if(void 0===c[p])break;if(c[p].copyCellsFrom(c[m],S-e,g-e,e,!0),g-=e,0===g&&(p--,g=_[p]),S-=e,0===S){m--;const e=Math.max(m,0);S=(0,a.getWrappedLineTrimmedLength)(c,e,this._cols)}}for(let t=0;t<c.length;t++)_[t]<e&&c[t].setCell(_[t],i);let C=u-f;for(;C-- >0;)0===this.ybase?this.y<t-1?(this.y++,this.lines.pop()):(this.ybase++,this.ydisp++):this.ybase<Math.min(this.lines.maxLength,this.lines.length+r)-t&&(this.ybase===this.ydisp&&this.ydisp++,this.ybase++);this.savedY=Math.min(this.savedY+u,this.ybase+t-1)}if(s.length>0){const e=[],t=[];for(let e=0;e<this.lines.length;e++)t.push(this.lines.get(e));const i=this.lines.length;let n=i-1,o=0,a=s[o];this.lines.length=Math.min(this.lines.maxLength,this.lines.length+r);let h=0;for(let c=Math.min(this.lines.maxLength-1,i+r-1);c>=0;c--)if(a&&a.start>n+h){for(let e=a.newLines.length-1;e>=0;e--)this.lines.set(c--,a.newLines[e]);c++,e.push({index:n+1,amount:a.newLines.length}),h+=a.newLines.length,a=s[++o]}else this.lines.set(c,t[n--]);let c=0;for(let t=e.length-1;t>=0;t--)e[t].index+=c,this.lines.onInsertEmitter.fire(e[t]),c+=e[t].amount;const l=Math.max(0,i+r-this.lines.maxLength);l>0&&this.lines.onTrimEmitter.fire(l)}}translateBufferLineToString(e,t,i=0,s){const r=this.lines.get(e);return r?r.translateToString(t,i,s):""}getWrappedRangeForLine(e){let t=e,i=e;for(;t>0&&this.lines.get(t).isWrapped;)t--;for(;i+1<this.lines.length&&this.lines.get(i+1).isWrapped;)i++;return{first:t,last:i}}setupTabStops(e){for(null!=e?this.tabs[e]||(e=this.prevStop(e)):(this.tabs={},e=0);e<this._cols;e+=this._optionsService.rawOptions.tabStopWidth)this.tabs[e]=!0}prevStop(e){for(null==e&&(e=this.x);!this.tabs[--e]&&e>0;);return e>=this._cols?this._cols-1:e<0?0:e}nextStop(e){for(null==e&&(e=this.x);!this.tabs[++e]&&e<this._cols;);return e>=this._cols?this._cols-1:e<0?0:e}clearMarkers(e){this._isClearing=!0;for(let t=0;t<this.markers.length;t++)this.markers[t].line===e&&(this.markers[t].dispose(),this.markers.splice(t--,1));this._isClearing=!1}clearAllMarkers(){this._isClearing=!0;for(let e=0;e<this.markers.length;e++)this.markers[e].dispose(),this.markers.splice(e--,1);this._isClearing=!1}addMarker(e){const t=new l.Marker(e);return this.markers.push(t),t.register(this.lines.onTrim((e=>{t.line-=e,t.line<0&&t.dispose()}))),t.register(this.lines.onInsert((e=>{t.line>=e.index&&(t.line+=e.amount)}))),t.register(this.lines.onDelete((e=>{t.line>=e.index&&t.line<e.index+e.amount&&t.dispose(),t.line>e.index&&(t.line-=e.amount)}))),t.register(t.onDispose((()=>this._removeMarker(t)))),t}_removeMarker(e){this._isClearing||this.markers.splice(this.markers.indexOf(e),1)}}},8437:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferLine=t.DEFAULT_ATTR_DATA=void 0;const s=i(3734),r=i(511),n=i(643),o=i(482);t.DEFAULT_ATTR_DATA=Object.freeze(new s.AttributeData);let a=0;class h{constructor(e,t,i=!1){this.isWrapped=i,this._combined={},this._extendedAttrs={},this._data=new Uint32Array(3*e);const s=t||r.CellData.fromCharData([0,n.NULL_CELL_CHAR,n.NULL_CELL_WIDTH,n.NULL_CELL_CODE]);for(let t=0;t<e;++t)this.setCell(t,s);this.length=e}get(e){const t=this._data[3*e+0],i=2097151&t;return[this._data[3*e+1],2097152&t?this._combined[e]:i?(0,o.stringFromCodePoint)(i):"",t>>22,2097152&t?this._combined[e].charCodeAt(this._combined[e].length-1):i]}set(e,t){this._data[3*e+1]=t[n.CHAR_DATA_ATTR_INDEX],t[n.CHAR_DATA_CHAR_INDEX].length>1?(this._combined[e]=t[1],this._data[3*e+0]=2097152|e|t[n.CHAR_DATA_WIDTH_INDEX]<<22):this._data[3*e+0]=t[n.CHAR_DATA_CHAR_INDEX].charCodeAt(0)|t[n.CHAR_DATA_WIDTH_INDEX]<<22}getWidth(e){return this._data[3*e+0]>>22}hasWidth(e){return 12582912&this._data[3*e+0]}getFg(e){return this._data[3*e+1]}getBg(e){return this._data[3*e+2]}hasContent(e){return 4194303&this._data[3*e+0]}getCodePoint(e){const t=this._data[3*e+0];return 2097152&t?this._combined[e].charCodeAt(this._combined[e].length-1):2097151&t}isCombined(e){return 2097152&this._data[3*e+0]}getString(e){const t=this._data[3*e+0];return 2097152&t?this._combined[e]:2097151&t?(0,o.stringFromCodePoint)(2097151&t):""}isProtected(e){return 536870912&this._data[3*e+2]}loadCell(e,t){return a=3*e,t.content=this._data[a+0],t.fg=this._data[a+1],t.bg=this._data[a+2],2097152&t.content&&(t.combinedData=this._combined[e]),268435456&t.bg&&(t.extended=this._extendedAttrs[e]),t}setCell(e,t){2097152&t.content&&(this._combined[e]=t.combinedData),268435456&t.bg&&(this._extendedAttrs[e]=t.extended),this._data[3*e+0]=t.content,this._data[3*e+1]=t.fg,this._data[3*e+2]=t.bg}setCellFromCodepoint(e,t,i,s){268435456&s.bg&&(this._extendedAttrs[e]=s.extended),this._data[3*e+0]=t|i<<22,this._data[3*e+1]=s.fg,this._data[3*e+2]=s.bg}addCodepointToCell(e,t,i){let s=this._data[3*e+0];2097152&s?this._combined[e]+=(0,o.stringFromCodePoint)(t):2097151&s?(this._combined[e]=(0,o.stringFromCodePoint)(2097151&s)+(0,o.stringFromCodePoint)(t),s&=-2097152,s|=2097152):s=t|1<<22,i&&(s&=-12582913,s|=i<<22),this._data[3*e+0]=s}insertCells(e,t,i){if((e%=this.length)&&2===this.getWidth(e-1)&&this.setCellFromCodepoint(e-1,0,1,i),t<this.length-e){const s=new r.CellData;for(let i=this.length-e-t-1;i>=0;--i)this.setCell(e+t+i,this.loadCell(e+i,s));for(let s=0;s<t;++s)this.setCell(e+s,i)}else for(let t=e;t<this.length;++t)this.setCell(t,i);2===this.getWidth(this.length-1)&&this.setCellFromCodepoint(this.length-1,0,1,i)}deleteCells(e,t,i){if(e%=this.length,t<this.length-e){const s=new r.CellData;for(let i=0;i<this.length-e-t;++i)this.setCell(e+i,this.loadCell(e+t+i,s));for(let e=this.length-t;e<this.length;++e)this.setCell(e,i)}else for(let t=e;t<this.length;++t)this.setCell(t,i);e&&2===this.getWidth(e-1)&&this.setCellFromCodepoint(e-1,0,1,i),0!==this.getWidth(e)||this.hasContent(e)||this.setCellFromCodepoint(e,0,1,i)}replaceCells(e,t,i,s=!1){if(s)for(e&&2===this.getWidth(e-1)&&!this.isProtected(e-1)&&this.setCellFromCodepoint(e-1,0,1,i),t<this.length&&2===this.getWidth(t-1)&&!this.isProtected(t)&&this.setCellFromCodepoint(t,0,1,i);e<t&&e<this.length;)this.isProtected(e)||this.setCell(e,i),e++;else for(e&&2===this.getWidth(e-1)&&this.setCellFromCodepoint(e-1,0,1,i),t<this.length&&2===this.getWidth(t-1)&&this.setCellFromCodepoint(t,0,1,i);e<t&&e<this.length;)this.setCell(e++,i)}resize(e,t){if(e===this.length)return 4*this._data.length*2<this._data.buffer.byteLength;const i=3*e;if(e>this.length){if(this._data.buffer.byteLength>=4*i)this._data=new Uint32Array(this._data.buffer,0,i);else{const e=new Uint32Array(i);e.set(this._data),this._data=e}for(let i=this.length;i<e;++i)this.setCell(i,t)}else{this._data=this._data.subarray(0,i);const t=Object.keys(this._combined);for(let i=0;i<t.length;i++){const s=parseInt(t[i],10);s>=e&&delete this._combined[s]}const s=Object.keys(this._extendedAttrs);for(let t=0;t<s.length;t++){const i=parseInt(s[t],10);i>=e&&delete this._extendedAttrs[i]}}return this.length=e,4*i*2<this._data.buffer.byteLength}cleanupMemory(){if(4*this._data.length*2<this._data.buffer.byteLength){const e=new Uint32Array(this._data.length);return e.set(this._data),this._data=e,1}return 0}fill(e,t=!1){if(t)for(let t=0;t<this.length;++t)this.isProtected(t)||this.setCell(t,e);else{this._combined={},this._extendedAttrs={};for(let t=0;t<this.length;++t)this.setCell(t,e)}}copyFrom(e){this.length!==e.length?this._data=new Uint32Array(e._data):this._data.set(e._data),this.length=e.length,this._combined={};for(const t in e._combined)this._combined[t]=e._combined[t];this._extendedAttrs={};for(const t in e._extendedAttrs)this._extendedAttrs[t]=e._extendedAttrs[t];this.isWrapped=e.isWrapped}clone(){const e=new h(0);e._data=new Uint32Array(this._data),e.length=this.length;for(const t in this._combined)e._combined[t]=this._combined[t];for(const t in this._extendedAttrs)e._extendedAttrs[t]=this._extendedAttrs[t];return e.isWrapped=this.isWrapped,e}getTrimmedLength(){for(let e=this.length-1;e>=0;--e)if(4194303&this._data[3*e+0])return e+(this._data[3*e+0]>>22);return 0}getNoBgTrimmedLength(){for(let e=this.length-1;e>=0;--e)if(4194303&this._data[3*e+0]||50331648&this._data[3*e+2])return e+(this._data[3*e+0]>>22);return 0}copyCellsFrom(e,t,i,s,r){const n=e._data;if(r)for(let r=s-1;r>=0;r--){for(let e=0;e<3;e++)this._data[3*(i+r)+e]=n[3*(t+r)+e];268435456&n[3*(t+r)+2]&&(this._extendedAttrs[i+r]=e._extendedAttrs[t+r])}else for(let r=0;r<s;r++){for(let e=0;e<3;e++)this._data[3*(i+r)+e]=n[3*(t+r)+e];268435456&n[3*(t+r)+2]&&(this._extendedAttrs[i+r]=e._extendedAttrs[t+r])}const o=Object.keys(e._combined);for(let s=0;s<o.length;s++){const r=parseInt(o[s],10);r>=t&&(this._combined[r-t+i]=e._combined[r])}}translateToString(e,t,i,s){t=t??0,i=i??this.length,e&&(i=Math.min(i,this.getTrimmedLength())),s&&(s.length=0);let r="";for(;t<i;){const e=this._data[3*t+0],i=2097151&e,a=2097152&e?this._combined[t]:i?(0,o.stringFromCodePoint)(i):n.WHITESPACE_CELL_CHAR;if(r+=a,s)for(let e=0;e<a.length;++e)s.push(t);t+=e>>22||1}return s&&s.push(t),r}}t.BufferLine=h},4841:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.getRangeLength=void 0,t.getRangeLength=function(e,t){if(e.start.y>e.end.y)throw new Error(`Buffer range end (${e.end.x}, ${e.end.y}) cannot be before start (${e.start.x}, ${e.start.y})`);return t*(e.end.y-e.start.y)+(e.end.x-e.start.x+1)}},4634:(e,t)=>{function i(e,t,i){if(t===e.length-1)return e[t].getTrimmedLength();const s=!e[t].hasContent(i-1)&&1===e[t].getWidth(i-1),r=2===e[t+1].getWidth(0);return s&&r?i-1:i}Object.defineProperty(t,"__esModule",{value:!0}),t.getWrappedLineTrimmedLength=t.reflowSmallerGetNewLineLengths=t.reflowLargerApplyNewLayout=t.reflowLargerCreateNewLayout=t.reflowLargerGetLinesToRemove=void 0,t.reflowLargerGetLinesToRemove=function(e,t,s,r,n){const o=[];for(let a=0;a<e.length-1;a++){let h=a,c=e.get(++h);if(!c.isWrapped)continue;const l=[e.get(a)];for(;h<e.length&&c.isWrapped;)l.push(c),c=e.get(++h);if(r>=a&&r<h){a+=l.length-1;continue}let d=0,_=i(l,d,t),u=1,f=0;for(;u<l.length;){const e=i(l,u,t),r=e-f,o=s-_,a=Math.min(r,o);l[d].copyCellsFrom(l[u],f,_,a,!1),_+=a,_===s&&(d++,_=0),f+=a,f===e&&(u++,f=0),0===_&&0!==d&&2===l[d-1].getWidth(s-1)&&(l[d].copyCellsFrom(l[d-1],s-1,_++,1,!1),l[d-1].setCell(s-1,n))}l[d].replaceCells(_,s,n);let v=0;for(let e=l.length-1;e>0&&(e>d||0===l[e].getTrimmedLength());e--)v++;v>0&&(o.push(a+l.length-v),o.push(v)),a+=l.length-1}return o},t.reflowLargerCreateNewLayout=function(e,t){const i=[];let s=0,r=t[s],n=0;for(let o=0;o<e.length;o++)if(r===o){const i=t[++s];e.onDeleteEmitter.fire({index:o-n,amount:i}),o+=i-1,n+=i,r=t[++s]}else i.push(o);return{layout:i,countRemoved:n}},t.reflowLargerApplyNewLayout=function(e,t){const i=[];for(let s=0;s<t.length;s++)i.push(e.get(t[s]));for(let t=0;t<i.length;t++)e.set(t,i[t]);e.length=t.length},t.reflowSmallerGetNewLineLengths=function(e,t,s){const r=[],n=e.map(((s,r)=>i(e,r,t))).reduce(((e,t)=>e+t));let o=0,a=0,h=0;for(;h<n;){if(n-h<s){r.push(n-h);break}o+=s;const c=i(e,a,t);o>c&&(o-=c,a++);const l=2===e[a].getWidth(o-1);l&&o--;const d=l?s-1:s;r.push(d),h+=d}return r},t.getWrappedLineTrimmedLength=i},5295:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferSet=void 0;const s=i(8460),r=i(844),n=i(9092);class o extends r.Disposable{constructor(e,t){super(),this._optionsService=e,this._bufferService=t,this._onBufferActivate=this.register(new s.EventEmitter),this.onBufferActivate=this._onBufferActivate.event,this.reset(),this.register(this._optionsService.onSpecificOptionChange("scrollback",(()=>this.resize(this._bufferService.cols,this._bufferService.rows)))),this.register(this._optionsService.onSpecificOptionChange("tabStopWidth",(()=>this.setupTabStops())))}reset(){this._normal=new n.Buffer(!0,this._optionsService,this._bufferService),this._normal.fillViewportRows(),this._alt=new n.Buffer(!1,this._optionsService,this._bufferService),this._activeBuffer=this._normal,this._onBufferActivate.fire({activeBuffer:this._normal,inactiveBuffer:this._alt}),this.setupTabStops()}get alt(){return this._alt}get active(){return this._activeBuffer}get normal(){return this._normal}activateNormalBuffer(){this._activeBuffer!==this._normal&&(this._normal.x=this._alt.x,this._normal.y=this._alt.y,this._alt.clearAllMarkers(),this._alt.clear(),this._activeBuffer=this._normal,this._onBufferActivate.fire({activeBuffer:this._normal,inactiveBuffer:this._alt}))}activateAltBuffer(e){this._activeBuffer!==this._alt&&(this._alt.fillViewportRows(e),this._alt.x=this._normal.x,this._alt.y=this._normal.y,this._activeBuffer=this._alt,this._onBufferActivate.fire({activeBuffer:this._alt,inactiveBuffer:this._normal}))}resize(e,t){this._normal.resize(e,t),this._alt.resize(e,t),this.setupTabStops(e)}setupTabStops(e){this._normal.setupTabStops(e),this._alt.setupTabStops(e)}}t.BufferSet=o},511:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CellData=void 0;const s=i(482),r=i(643),n=i(3734);class o extends n.AttributeData{constructor(){super(...arguments),this.content=0,this.fg=0,this.bg=0,this.extended=new n.ExtendedAttrs,this.combinedData=""}static fromCharData(e){const t=new o;return t.setFromCharData(e),t}isCombined(){return 2097152&this.content}getWidth(){return this.content>>22}getChars(){return 2097152&this.content?this.combinedData:2097151&this.content?(0,s.stringFromCodePoint)(2097151&this.content):""}getCode(){return this.isCombined()?this.combinedData.charCodeAt(this.combinedData.length-1):2097151&this.content}setFromCharData(e){this.fg=e[r.CHAR_DATA_ATTR_INDEX],this.bg=0;let t=!1;if(e[r.CHAR_DATA_CHAR_INDEX].length>2)t=!0;else if(2===e[r.CHAR_DATA_CHAR_INDEX].length){const i=e[r.CHAR_DATA_CHAR_INDEX].charCodeAt(0);if(55296<=i&&i<=56319){const s=e[r.CHAR_DATA_CHAR_INDEX].charCodeAt(1);56320<=s&&s<=57343?this.content=1024*(i-55296)+s-56320+65536|e[r.CHAR_DATA_WIDTH_INDEX]<<22:t=!0}else t=!0}else this.content=e[r.CHAR_DATA_CHAR_INDEX].charCodeAt(0)|e[r.CHAR_DATA_WIDTH_INDEX]<<22;t&&(this.combinedData=e[r.CHAR_DATA_CHAR_INDEX],this.content=2097152|e[r.CHAR_DATA_WIDTH_INDEX]<<22)}getAsCharData(){return[this.fg,this.getChars(),this.getWidth(),this.getCode()]}}t.CellData=o},643:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.WHITESPACE_CELL_CODE=t.WHITESPACE_CELL_WIDTH=t.WHITESPACE_CELL_CHAR=t.NULL_CELL_CODE=t.NULL_CELL_WIDTH=t.NULL_CELL_CHAR=t.CHAR_DATA_CODE_INDEX=t.CHAR_DATA_WIDTH_INDEX=t.CHAR_DATA_CHAR_INDEX=t.CHAR_DATA_ATTR_INDEX=t.DEFAULT_EXT=t.DEFAULT_ATTR=t.DEFAULT_COLOR=void 0,t.DEFAULT_COLOR=0,t.DEFAULT_ATTR=256|t.DEFAULT_COLOR<<9,t.DEFAULT_EXT=0,t.CHAR_DATA_ATTR_INDEX=0,t.CHAR_DATA_CHAR_INDEX=1,t.CHAR_DATA_WIDTH_INDEX=2,t.CHAR_DATA_CODE_INDEX=3,t.NULL_CELL_CHAR="",t.NULL_CELL_WIDTH=1,t.NULL_CELL_CODE=0,t.WHITESPACE_CELL_CHAR=" ",t.WHITESPACE_CELL_WIDTH=1,t.WHITESPACE_CELL_CODE=32},4863:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Marker=void 0;const s=i(8460),r=i(844);class n{get id(){return this._id}constructor(e){this.line=e,this.isDisposed=!1,this._disposables=[],this._id=n._nextId++,this._onDispose=this.register(new s.EventEmitter),this.onDispose=this._onDispose.event}dispose(){this.isDisposed||(this.isDisposed=!0,this.line=-1,this._onDispose.fire(),(0,r.disposeArray)(this._disposables),this._disposables.length=0)}register(e){return this._disposables.push(e),e}}t.Marker=n,n._nextId=1},7116:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DEFAULT_CHARSET=t.CHARSETS=void 0,t.CHARSETS={},t.DEFAULT_CHARSET=t.CHARSETS.B,t.CHARSETS[0]={"`":"\u25C6",a:"\u2592",b:"\u2409",c:"\u240C",d:"\u240D",e:"\u240A",f:"\xB0",g:"\xB1",h:"\u2424",i:"\u240B",j:"\u2518",k:"\u2510",l:"\u250C",m:"\u2514",n:"\u253C",o:"\u23BA",p:"\u23BB",q:"\u2500",r:"\u23BC",s:"\u23BD",t:"\u251C",u:"\u2524",v:"\u2534",w:"\u252C",x:"\u2502",y:"\u2264",z:"\u2265","{":"\u03C0","|":"\u2260","}":"\xA3","~":"\xB7"},t.CHARSETS.A={"#":"\xA3"},t.CHARSETS.B=void 0,t.CHARSETS[4]={"#":"\xA3","@":"\xBE","[":"ij","\\\\":"\xBD","]":"|","{":"\xA8","|":"f","}":"\xBC","~":"\xB4"},t.CHARSETS.C=t.CHARSETS[5]={"[":"\xC4","\\\\":"\xD6","]":"\xC5","^":"\xDC","`":"\xE9","{":"\xE4","|":"\xF6","}":"\xE5","~":"\xFC"},t.CHARSETS.R={"#":"\xA3","@":"\xE0","[":"\xB0","\\\\":"\xE7","]":"\xA7","{":"\xE9","|":"\xF9","}":"\xE8","~":"\xA8"},t.CHARSETS.Q={"@":"\xE0","[":"\xE2","\\\\":"\xE7","]":"\xEA","^":"\xEE","`":"\xF4","{":"\xE9","|":"\xF9","}":"\xE8","~":"\xFB"},t.CHARSETS.K={"@":"\xA7","[":"\xC4","\\\\":"\xD6","]":"\xDC","{":"\xE4","|":"\xF6","}":"\xFC","~":"\xDF"},t.CHARSETS.Y={"#":"\xA3","@":"\xA7","[":"\xB0","\\\\":"\xE7","]":"\xE9","`":"\xF9","{":"\xE0","|":"\xF2","}":"\xE8","~":"\xEC"},t.CHARSETS.E=t.CHARSETS[6]={"@":"\xC4","[":"\xC6","\\\\":"\xD8","]":"\xC5","^":"\xDC","`":"\xE4","{":"\xE6","|":"\xF8","}":"\xE5","~":"\xFC"},t.CHARSETS.Z={"#":"\xA3","@":"\xA7","[":"\xA1","\\\\":"\xD1","]":"\xBF","{":"\xB0","|":"\xF1","}":"\xE7"},t.CHARSETS.H=t.CHARSETS[7]={"@":"\xC9","[":"\xC4","\\\\":"\xD6","]":"\xC5","^":"\xDC","`":"\xE9","{":"\xE4","|":"\xF6","}":"\xE5","~":"\xFC"},t.CHARSETS["="]={"#":"\xF9","@":"\xE0","[":"\xE9","\\\\":"\xE7","]":"\xEA","^":"\xEE",_:"\xE8","`":"\xF4","{":"\xE4","|":"\xF6","}":"\xFC","~":"\xFB"}},2584:(e,t)=>{var i,s,r;Object.defineProperty(t,"__esModule",{value:!0}),t.C1_ESCAPED=t.C1=t.C0=void 0,function(e){e.NUL="\\0",e.SOH="",e.STX="",e.ETX="",e.EOT="",e.ENQ="",e.ACK="",e.BEL="\x07",e.BS="\\b",e.HT="\\t",e.LF="\\n",e.VT="\\v",e.FF="\\f",e.CR="\\r",e.SO="",e.SI="",e.DLE="",e.DC1="",e.DC2="",e.DC3="",e.DC4="",e.NAK="",e.SYN="",e.ETB="",e.CAN="",e.EM="",e.SUB="",e.ESC="\x1B",e.FS="",e.GS="",e.RS="",e.US="",e.SP=" ",e.DEL="\x7F"}(i||(t.C0=i={})),function(e){e.PAD="\x80",e.HOP="\x81",e.BPH="\x82",e.NBH="\x83",e.IND="\x84",e.NEL="\x85",e.SSA="\x86",e.ESA="\x87",e.HTS="\x88",e.HTJ="\x89",e.VTS="\x8A",e.PLD="\x8B",e.PLU="\x8C",e.RI="\x8D",e.SS2="\x8E",e.SS3="\x8F",e.DCS="\x90",e.PU1="\x91",e.PU2="\x92",e.STS="\x93",e.CCH="\x94",e.MW="\x95",e.SPA="\x96",e.EPA="\x97",e.SOS="\x98",e.SGCI="\x99",e.SCI="\x9A",e.CSI="\x9B",e.ST="\x9C",e.OSC="\x9D",e.PM="\x9E",e.APC="\x9F"}(s||(t.C1=s={})),function(e){e.ST=`${i.ESC}\\\\`}(r||(t.C1_ESCAPED=r={}))},7399:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.evaluateKeyboardEvent=void 0;const s=i(2584),r={48:["0",")"],49:["1","!"],50:["2","@"],51:["3","#"],52:["4","$"],53:["5","%"],54:["6","^"],55:["7","&"],56:["8","*"],57:["9","("],186:[";",":"],187:["=","+"],188:[",","<"],189:["-","_"],190:[".",">"],191:["/","?"],192:["`","~"],219:["[","{"],220:["\\\\","|"],221:["]","}"],222:["\'",\'"\']};t.evaluateKeyboardEvent=function(e,t,i,n){const o={type:0,cancel:!1,key:void 0},a=(e.shiftKey?1:0)|(e.altKey?2:0)|(e.ctrlKey?4:0)|(e.metaKey?8:0);switch(e.keyCode){case 0:"UIKeyInputUpArrow"===e.key?o.key=t?s.C0.ESC+"OA":s.C0.ESC+"[A":"UIKeyInputLeftArrow"===e.key?o.key=t?s.C0.ESC+"OD":s.C0.ESC+"[D":"UIKeyInputRightArrow"===e.key?o.key=t?s.C0.ESC+"OC":s.C0.ESC+"[C":"UIKeyInputDownArrow"===e.key&&(o.key=t?s.C0.ESC+"OB":s.C0.ESC+"[B");break;case 8:o.key=e.ctrlKey?"\\b":s.C0.DEL,e.altKey&&(o.key=s.C0.ESC+o.key);break;case 9:if(e.shiftKey){o.key=s.C0.ESC+"[Z";break}o.key=s.C0.HT,o.cancel=!0;break;case 13:o.key=e.altKey?s.C0.ESC+s.C0.CR:s.C0.CR,o.cancel=!0;break;case 27:o.key=s.C0.ESC,e.altKey&&(o.key=s.C0.ESC+s.C0.ESC),o.cancel=!0;break;case 37:if(e.metaKey)break;a?(o.key=s.C0.ESC+"[1;"+(a+1)+"D",o.key===s.C0.ESC+"[1;3D"&&(o.key=s.C0.ESC+(i?"b":"[1;5D"))):o.key=t?s.C0.ESC+"OD":s.C0.ESC+"[D";break;case 39:if(e.metaKey)break;a?(o.key=s.C0.ESC+"[1;"+(a+1)+"C",o.key===s.C0.ESC+"[1;3C"&&(o.key=s.C0.ESC+(i?"f":"[1;5C"))):o.key=t?s.C0.ESC+"OC":s.C0.ESC+"[C";break;case 38:if(e.metaKey)break;a?(o.key=s.C0.ESC+"[1;"+(a+1)+"A",i||o.key!==s.C0.ESC+"[1;3A"||(o.key=s.C0.ESC+"[1;5A")):o.key=t?s.C0.ESC+"OA":s.C0.ESC+"[A";break;case 40:if(e.metaKey)break;a?(o.key=s.C0.ESC+"[1;"+(a+1)+"B",i||o.key!==s.C0.ESC+"[1;3B"||(o.key=s.C0.ESC+"[1;5B")):o.key=t?s.C0.ESC+"OB":s.C0.ESC+"[B";break;case 45:e.shiftKey||e.ctrlKey||(o.key=s.C0.ESC+"[2~");break;case 46:o.key=a?s.C0.ESC+"[3;"+(a+1)+"~":s.C0.ESC+"[3~";break;case 36:o.key=a?s.C0.ESC+"[1;"+(a+1)+"H":t?s.C0.ESC+"OH":s.C0.ESC+"[H";break;case 35:o.key=a?s.C0.ESC+"[1;"+(a+1)+"F":t?s.C0.ESC+"OF":s.C0.ESC+"[F";break;case 33:e.shiftKey?o.type=2:e.ctrlKey?o.key=s.C0.ESC+"[5;"+(a+1)+"~":o.key=s.C0.ESC+"[5~";break;case 34:e.shiftKey?o.type=3:e.ctrlKey?o.key=s.C0.ESC+"[6;"+(a+1)+"~":o.key=s.C0.ESC+"[6~";break;case 112:o.key=a?s.C0.ESC+"[1;"+(a+1)+"P":s.C0.ESC+"OP";break;case 113:o.key=a?s.C0.ESC+"[1;"+(a+1)+"Q":s.C0.ESC+"OQ";break;case 114:o.key=a?s.C0.ESC+"[1;"+(a+1)+"R":s.C0.ESC+"OR";break;case 115:o.key=a?s.C0.ESC+"[1;"+(a+1)+"S":s.C0.ESC+"OS";break;case 116:o.key=a?s.C0.ESC+"[15;"+(a+1)+"~":s.C0.ESC+"[15~";break;case 117:o.key=a?s.C0.ESC+"[17;"+(a+1)+"~":s.C0.ESC+"[17~";break;case 118:o.key=a?s.C0.ESC+"[18;"+(a+1)+"~":s.C0.ESC+"[18~";break;case 119:o.key=a?s.C0.ESC+"[19;"+(a+1)+"~":s.C0.ESC+"[19~";break;case 120:o.key=a?s.C0.ESC+"[20;"+(a+1)+"~":s.C0.ESC+"[20~";break;case 121:o.key=a?s.C0.ESC+"[21;"+(a+1)+"~":s.C0.ESC+"[21~";break;case 122:o.key=a?s.C0.ESC+"[23;"+(a+1)+"~":s.C0.ESC+"[23~";break;case 123:o.key=a?s.C0.ESC+"[24;"+(a+1)+"~":s.C0.ESC+"[24~";break;default:if(!e.ctrlKey||e.shiftKey||e.altKey||e.metaKey)if(i&&!n||!e.altKey||e.metaKey)!i||e.altKey||e.ctrlKey||e.shiftKey||!e.metaKey?e.key&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&e.keyCode>=48&&1===e.key.length?o.key=e.key:e.key&&e.ctrlKey&&("_"===e.key&&(o.key=s.C0.US),"@"===e.key&&(o.key=s.C0.NUL)):65===e.keyCode&&(o.type=1);else{const t=r[e.keyCode],i=t?.[e.shiftKey?1:0];if(i)o.key=s.C0.ESC+i;else if(e.keyCode>=65&&e.keyCode<=90){const t=e.ctrlKey?e.keyCode-64:e.keyCode+32;let i=String.fromCharCode(t);e.shiftKey&&(i=i.toUpperCase()),o.key=s.C0.ESC+i}else if(32===e.keyCode)o.key=s.C0.ESC+(e.ctrlKey?s.C0.NUL:" ");else if("Dead"===e.key&&e.code.startsWith("Key")){let t=e.code.slice(3,4);e.shiftKey||(t=t.toLowerCase()),o.key=s.C0.ESC+t,o.cancel=!0}}else e.keyCode>=65&&e.keyCode<=90?o.key=String.fromCharCode(e.keyCode-64):32===e.keyCode?o.key=s.C0.NUL:e.keyCode>=51&&e.keyCode<=55?o.key=String.fromCharCode(e.keyCode-51+27):56===e.keyCode?o.key=s.C0.DEL:219===e.keyCode?o.key=s.C0.ESC:220===e.keyCode?o.key=s.C0.FS:221===e.keyCode&&(o.key=s.C0.GS)}return o}},482:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Utf8ToUtf32=t.StringToUtf32=t.utf32ToString=t.stringFromCodePoint=void 0,t.stringFromCodePoint=function(e){return e>65535?(e-=65536,String.fromCharCode(55296+(e>>10))+String.fromCharCode(e%1024+56320)):String.fromCharCode(e)},t.utf32ToString=function(e,t=0,i=e.length){let s="";for(let r=t;r<i;++r){let t=e[r];t>65535?(t-=65536,s+=String.fromCharCode(55296+(t>>10))+String.fromCharCode(t%1024+56320)):s+=String.fromCharCode(t)}return s},t.StringToUtf32=class{constructor(){this._interim=0}clear(){this._interim=0}decode(e,t){const i=e.length;if(!i)return 0;let s=0,r=0;if(this._interim){const i=e.charCodeAt(r++);56320<=i&&i<=57343?t[s++]=1024*(this._interim-55296)+i-56320+65536:(t[s++]=this._interim,t[s++]=i),this._interim=0}for(let n=r;n<i;++n){const r=e.charCodeAt(n);if(55296<=r&&r<=56319){if(++n>=i)return this._interim=r,s;const o=e.charCodeAt(n);56320<=o&&o<=57343?t[s++]=1024*(r-55296)+o-56320+65536:(t[s++]=r,t[s++]=o)}else 65279!==r&&(t[s++]=r)}return s}},t.Utf8ToUtf32=class{constructor(){this.interim=new Uint8Array(3)}clear(){this.interim.fill(0)}decode(e,t){const i=e.length;if(!i)return 0;let s,r,n,o,a=0,h=0,c=0;if(this.interim[0]){let s=!1,r=this.interim[0];r&=192==(224&r)?31:224==(240&r)?15:7;let n,o=0;for(;(n=63&this.interim[++o])&&o<4;)r<<=6,r|=n;const h=192==(224&this.interim[0])?2:224==(240&this.interim[0])?3:4,l=h-o;for(;c<l;){if(c>=i)return 0;if(n=e[c++],128!=(192&n)){c--,s=!0;break}this.interim[o++]=n,r<<=6,r|=63&n}s||(2===h?r<128?c--:t[a++]=r:3===h?r<2048||r>=55296&&r<=57343||65279===r||(t[a++]=r):r<65536||r>1114111||(t[a++]=r)),this.interim.fill(0)}const l=i-4;let d=c;for(;d<i;){for(;!(!(d<l)||128&(s=e[d])||128&(r=e[d+1])||128&(n=e[d+2])||128&(o=e[d+3]));)t[a++]=s,t[a++]=r,t[a++]=n,t[a++]=o,d+=4;if(s=e[d++],s<128)t[a++]=s;else if(192==(224&s)){if(d>=i)return this.interim[0]=s,a;if(r=e[d++],128!=(192&r)){d--;continue}if(h=(31&s)<<6|63&r,h<128){d--;continue}t[a++]=h}else if(224==(240&s)){if(d>=i)return this.interim[0]=s,a;if(r=e[d++],128!=(192&r)){d--;continue}if(d>=i)return this.interim[0]=s,this.interim[1]=r,a;if(n=e[d++],128!=(192&n)){d--;continue}if(h=(15&s)<<12|(63&r)<<6|63&n,h<2048||h>=55296&&h<=57343||65279===h)continue;t[a++]=h}else if(240==(248&s)){if(d>=i)return this.interim[0]=s,a;if(r=e[d++],128!=(192&r)){d--;continue}if(d>=i)return this.interim[0]=s,this.interim[1]=r,a;if(n=e[d++],128!=(192&n)){d--;continue}if(d>=i)return this.interim[0]=s,this.interim[1]=r,this.interim[2]=n,a;if(o=e[d++],128!=(192&o)){d--;continue}if(h=(7&s)<<18|(63&r)<<12|(63&n)<<6|63&o,h<65536||h>1114111)continue;t[a++]=h}}return a}}},225:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.UnicodeV6=void 0;const s=i(1480),r=[[768,879],[1155,1158],[1160,1161],[1425,1469],[1471,1471],[1473,1474],[1476,1477],[1479,1479],[1536,1539],[1552,1557],[1611,1630],[1648,1648],[1750,1764],[1767,1768],[1770,1773],[1807,1807],[1809,1809],[1840,1866],[1958,1968],[2027,2035],[2305,2306],[2364,2364],[2369,2376],[2381,2381],[2385,2388],[2402,2403],[2433,2433],[2492,2492],[2497,2500],[2509,2509],[2530,2531],[2561,2562],[2620,2620],[2625,2626],[2631,2632],[2635,2637],[2672,2673],[2689,2690],[2748,2748],[2753,2757],[2759,2760],[2765,2765],[2786,2787],[2817,2817],[2876,2876],[2879,2879],[2881,2883],[2893,2893],[2902,2902],[2946,2946],[3008,3008],[3021,3021],[3134,3136],[3142,3144],[3146,3149],[3157,3158],[3260,3260],[3263,3263],[3270,3270],[3276,3277],[3298,3299],[3393,3395],[3405,3405],[3530,3530],[3538,3540],[3542,3542],[3633,3633],[3636,3642],[3655,3662],[3761,3761],[3764,3769],[3771,3772],[3784,3789],[3864,3865],[3893,3893],[3895,3895],[3897,3897],[3953,3966],[3968,3972],[3974,3975],[3984,3991],[3993,4028],[4038,4038],[4141,4144],[4146,4146],[4150,4151],[4153,4153],[4184,4185],[4448,4607],[4959,4959],[5906,5908],[5938,5940],[5970,5971],[6002,6003],[6068,6069],[6071,6077],[6086,6086],[6089,6099],[6109,6109],[6155,6157],[6313,6313],[6432,6434],[6439,6440],[6450,6450],[6457,6459],[6679,6680],[6912,6915],[6964,6964],[6966,6970],[6972,6972],[6978,6978],[7019,7027],[7616,7626],[7678,7679],[8203,8207],[8234,8238],[8288,8291],[8298,8303],[8400,8431],[12330,12335],[12441,12442],[43014,43014],[43019,43019],[43045,43046],[64286,64286],[65024,65039],[65056,65059],[65279,65279],[65529,65531]],n=[[68097,68099],[68101,68102],[68108,68111],[68152,68154],[68159,68159],[119143,119145],[119155,119170],[119173,119179],[119210,119213],[119362,119364],[917505,917505],[917536,917631],[917760,917999]];let o;t.UnicodeV6=class{constructor(){if(this.version="6",!o){o=new Uint8Array(65536),o.fill(1),o[0]=0,o.fill(0,1,32),o.fill(0,127,160),o.fill(2,4352,4448),o[9001]=2,o[9002]=2,o.fill(2,11904,42192),o[12351]=1,o.fill(2,44032,55204),o.fill(2,63744,64256),o.fill(2,65040,65050),o.fill(2,65072,65136),o.fill(2,65280,65377),o.fill(2,65504,65511);for(let e=0;e<r.length;++e)o.fill(0,r[e][0],r[e][1]+1)}}wcwidth(e){return e<32?0:e<127?1:e<65536?o[e]:function(e,t){let i,s=0,r=t.length-1;if(e<t[0][0]||e>t[r][1])return!1;for(;r>=s;)if(i=s+r>>1,e>t[i][1])s=i+1;else{if(!(e<t[i][0]))return!0;r=i-1}return!1}(e,n)?0:e>=131072&&e<=196605||e>=196608&&e<=262141?2:1}charProperties(e,t){let i=this.wcwidth(e),r=0===i&&0!==t;if(r){const e=s.UnicodeService.extractWidth(t);0===e?r=!1:e>i&&(i=e)}return s.UnicodeService.createPropertyValue(0,i,r)}}},5981:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.WriteBuffer=void 0;const s=i(8460),r=i(844);class n extends r.Disposable{constructor(e){super(),this._action=e,this._writeBuffer=[],this._callbacks=[],this._pendingData=0,this._bufferOffset=0,this._isSyncWriting=!1,this._syncCalls=0,this._didUserInput=!1,this._onWriteParsed=this.register(new s.EventEmitter),this.onWriteParsed=this._onWriteParsed.event}handleUserInput(){this._didUserInput=!0}writeSync(e,t){if(void 0!==t&&this._syncCalls>t)return void(this._syncCalls=0);if(this._pendingData+=e.length,this._writeBuffer.push(e),this._callbacks.push(void 0),this._syncCalls++,this._isSyncWriting)return;let i;for(this._isSyncWriting=!0;i=this._writeBuffer.shift();){this._action(i);const e=this._callbacks.shift();e&&e()}this._pendingData=0,this._bufferOffset=2147483647,this._isSyncWriting=!1,this._syncCalls=0}write(e,t){if(this._pendingData>5e7)throw new Error("write data discarded, use flow control to avoid losing data");if(!this._writeBuffer.length){if(this._bufferOffset=0,this._didUserInput)return this._didUserInput=!1,this._pendingData+=e.length,this._writeBuffer.push(e),this._callbacks.push(t),void this._innerWrite();setTimeout((()=>this._innerWrite()))}this._pendingData+=e.length,this._writeBuffer.push(e),this._callbacks.push(t)}_innerWrite(e=0,t=!0){const i=e||Date.now();for(;this._writeBuffer.length>this._bufferOffset;){const e=this._writeBuffer[this._bufferOffset],s=this._action(e,t);if(s){const e=e=>Date.now()-i>=12?setTimeout((()=>this._innerWrite(0,e))):this._innerWrite(i,e);return void s.catch((e=>(queueMicrotask((()=>{throw e})),Promise.resolve(!1)))).then(e)}const r=this._callbacks[this._bufferOffset];if(r&&r(),this._bufferOffset++,this._pendingData-=e.length,Date.now()-i>=12)break}this._writeBuffer.length>this._bufferOffset?(this._bufferOffset>50&&(this._writeBuffer=this._writeBuffer.slice(this._bufferOffset),this._callbacks=this._callbacks.slice(this._bufferOffset),this._bufferOffset=0),setTimeout((()=>this._innerWrite()))):(this._writeBuffer.length=0,this._callbacks.length=0,this._pendingData=0,this._bufferOffset=0),this._onWriteParsed.fire()}}t.WriteBuffer=n},5941:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.toRgbString=t.parseColor=void 0;const i=/^([\\da-f])\\/([\\da-f])\\/([\\da-f])$|^([\\da-f]{2})\\/([\\da-f]{2})\\/([\\da-f]{2})$|^([\\da-f]{3})\\/([\\da-f]{3})\\/([\\da-f]{3})$|^([\\da-f]{4})\\/([\\da-f]{4})\\/([\\da-f]{4})$/,s=/^[\\da-f]+$/;function r(e,t){const i=e.toString(16),s=i.length<2?"0"+i:i;switch(t){case 4:return i[0];case 8:return s;case 12:return(s+s).slice(0,3);default:return s+s}}t.parseColor=function(e){if(!e)return;let t=e.toLowerCase();if(0===t.indexOf("rgb:")){t=t.slice(4);const e=i.exec(t);if(e){const t=e[1]?15:e[4]?255:e[7]?4095:65535;return[Math.round(parseInt(e[1]||e[4]||e[7]||e[10],16)/t*255),Math.round(parseInt(e[2]||e[5]||e[8]||e[11],16)/t*255),Math.round(parseInt(e[3]||e[6]||e[9]||e[12],16)/t*255)]}}else if(0===t.indexOf("#")&&(t=t.slice(1),s.exec(t)&&[3,6,9,12].includes(t.length))){const e=t.length/3,i=[0,0,0];for(let s=0;s<3;++s){const r=parseInt(t.slice(e*s,e*s+e),16);i[s]=1===e?r<<4:2===e?r:3===e?r>>4:r>>8}return i}},t.toRgbString=function(e,t=16){const[i,s,n]=e;return`rgb:${r(i,t)}/${r(s,t)}/${r(n,t)}`}},5770:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.PAYLOAD_LIMIT=void 0,t.PAYLOAD_LIMIT=1e7},6351:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DcsHandler=t.DcsParser=void 0;const s=i(482),r=i(8742),n=i(5770),o=[];t.DcsParser=class{constructor(){this._handlers=Object.create(null),this._active=o,this._ident=0,this._handlerFb=()=>{},this._stack={paused:!1,loopPosition:0,fallThrough:!1}}dispose(){this._handlers=Object.create(null),this._handlerFb=()=>{},this._active=o}registerHandler(e,t){void 0===this._handlers[e]&&(this._handlers[e]=[]);const i=this._handlers[e];return i.push(t),{dispose:()=>{const e=i.indexOf(t);-1!==e&&i.splice(e,1)}}}clearHandler(e){this._handlers[e]&&delete this._handlers[e]}setHandlerFallback(e){this._handlerFb=e}reset(){if(this._active.length)for(let e=this._stack.paused?this._stack.loopPosition-1:this._active.length-1;e>=0;--e)this._active[e].unhook(!1);this._stack.paused=!1,this._active=o,this._ident=0}hook(e,t){if(this.reset(),this._ident=e,this._active=this._handlers[e]||o,this._active.length)for(let e=this._active.length-1;e>=0;e--)this._active[e].hook(t);else this._handlerFb(this._ident,"HOOK",t)}put(e,t,i){if(this._active.length)for(let s=this._active.length-1;s>=0;s--)this._active[s].put(e,t,i);else this._handlerFb(this._ident,"PUT",(0,s.utf32ToString)(e,t,i))}unhook(e,t=!0){if(this._active.length){let i=!1,s=this._active.length-1,r=!1;if(this._stack.paused&&(s=this._stack.loopPosition-1,i=t,r=this._stack.fallThrough,this._stack.paused=!1),!r&&!1===i){for(;s>=0&&(i=this._active[s].unhook(e),!0!==i);s--)if(i instanceof Promise)return this._stack.paused=!0,this._stack.loopPosition=s,this._stack.fallThrough=!1,i;s--}for(;s>=0;s--)if(i=this._active[s].unhook(!1),i instanceof Promise)return this._stack.paused=!0,this._stack.loopPosition=s,this._stack.fallThrough=!0,i}else this._handlerFb(this._ident,"UNHOOK",e);this._active=o,this._ident=0}};const a=new r.Params;a.addParam(0),t.DcsHandler=class{constructor(e){this._handler=e,this._data="",this._params=a,this._hitLimit=!1}hook(e){this._params=e.length>1||e.params[0]?e.clone():a,this._data="",this._hitLimit=!1}put(e,t,i){this._hitLimit||(this._data+=(0,s.utf32ToString)(e,t,i),this._data.length>n.PAYLOAD_LIMIT&&(this._data="",this._hitLimit=!0))}unhook(e){let t=!1;if(this._hitLimit)t=!1;else if(e&&(t=this._handler(this._data,this._params),t instanceof Promise))return t.then((e=>(this._params=a,this._data="",this._hitLimit=!1,e)));return this._params=a,this._data="",this._hitLimit=!1,t}}},2015:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.EscapeSequenceParser=t.VT500_TRANSITION_TABLE=t.TransitionTable=void 0;const s=i(844),r=i(8742),n=i(6242),o=i(6351);class a{constructor(e){this.table=new Uint8Array(e)}setDefault(e,t){this.table.fill(e<<4|t)}add(e,t,i,s){this.table[t<<8|e]=i<<4|s}addMany(e,t,i,s){for(let r=0;r<e.length;r++)this.table[t<<8|e[r]]=i<<4|s}}t.TransitionTable=a;const h=160;t.VT500_TRANSITION_TABLE=function(){const e=new a(4095),t=Array.apply(null,Array(256)).map(((e,t)=>t)),i=(e,i)=>t.slice(e,i),s=i(32,127),r=i(0,24);r.push(25),r.push.apply(r,i(28,32));const n=i(0,14);let o;for(o in e.setDefault(1,0),e.addMany(s,0,2,0),n)e.addMany([24,26,153,154],o,3,0),e.addMany(i(128,144),o,3,0),e.addMany(i(144,152),o,3,0),e.add(156,o,0,0),e.add(27,o,11,1),e.add(157,o,4,8),e.addMany([152,158,159],o,0,7),e.add(155,o,11,3),e.add(144,o,11,9);return e.addMany(r,0,3,0),e.addMany(r,1,3,1),e.add(127,1,0,1),e.addMany(r,8,0,8),e.addMany(r,3,3,3),e.add(127,3,0,3),e.addMany(r,4,3,4),e.add(127,4,0,4),e.addMany(r,6,3,6),e.addMany(r,5,3,5),e.add(127,5,0,5),e.addMany(r,2,3,2),e.add(127,2,0,2),e.add(93,1,4,8),e.addMany(s,8,5,8),e.add(127,8,5,8),e.addMany([156,27,24,26,7],8,6,0),e.addMany(i(28,32),8,0,8),e.addMany([88,94,95],1,0,7),e.addMany(s,7,0,7),e.addMany(r,7,0,7),e.add(156,7,0,0),e.add(127,7,0,7),e.add(91,1,11,3),e.addMany(i(64,127),3,7,0),e.addMany(i(48,60),3,8,4),e.addMany([60,61,62,63],3,9,4),e.addMany(i(48,60),4,8,4),e.addMany(i(64,127),4,7,0),e.addMany([60,61,62,63],4,0,6),e.addMany(i(32,64),6,0,6),e.add(127,6,0,6),e.addMany(i(64,127),6,0,0),e.addMany(i(32,48),3,9,5),e.addMany(i(32,48),5,9,5),e.addMany(i(48,64),5,0,6),e.addMany(i(64,127),5,7,0),e.addMany(i(32,48),4,9,5),e.addMany(i(32,48),1,9,2),e.addMany(i(32,48),2,9,2),e.addMany(i(48,127),2,10,0),e.addMany(i(48,80),1,10,0),e.addMany(i(81,88),1,10,0),e.addMany([89,90,92],1,10,0),e.addMany(i(96,127),1,10,0),e.add(80,1,11,9),e.addMany(r,9,0,9),e.add(127,9,0,9),e.addMany(i(28,32),9,0,9),e.addMany(i(32,48),9,9,12),e.addMany(i(48,60),9,8,10),e.addMany([60,61,62,63],9,9,10),e.addMany(r,11,0,11),e.addMany(i(32,128),11,0,11),e.addMany(i(28,32),11,0,11),e.addMany(r,10,0,10),e.add(127,10,0,10),e.addMany(i(28,32),10,0,10),e.addMany(i(48,60),10,8,10),e.addMany([60,61,62,63],10,0,11),e.addMany(i(32,48),10,9,12),e.addMany(r,12,0,12),e.add(127,12,0,12),e.addMany(i(28,32),12,0,12),e.addMany(i(32,48),12,9,12),e.addMany(i(48,64),12,0,11),e.addMany(i(64,127),12,12,13),e.addMany(i(64,127),10,12,13),e.addMany(i(64,127),9,12,13),e.addMany(r,13,13,13),e.addMany(s,13,13,13),e.add(127,13,0,13),e.addMany([27,156,24,26],13,14,0),e.add(h,0,2,0),e.add(h,8,5,8),e.add(h,6,0,6),e.add(h,11,0,11),e.add(h,13,13,13),e}();class c extends s.Disposable{constructor(e=t.VT500_TRANSITION_TABLE){super(),this._transitions=e,this._parseStack={state:0,handlers:[],handlerPos:0,transition:0,chunkPos:0},this.initialState=0,this.currentState=this.initialState,this._params=new r.Params,this._params.addParam(0),this._collect=0,this.precedingJoinState=0,this._printHandlerFb=(e,t,i)=>{},this._executeHandlerFb=e=>{},this._csiHandlerFb=(e,t)=>{},this._escHandlerFb=e=>{},this._errorHandlerFb=e=>e,this._printHandler=this._printHandlerFb,this._executeHandlers=Object.create(null),this._csiHandlers=Object.create(null),this._escHandlers=Object.create(null),this.register((0,s.toDisposable)((()=>{this._csiHandlers=Object.create(null),this._executeHandlers=Object.create(null),this._escHandlers=Object.create(null)}))),this._oscParser=this.register(new n.OscParser),this._dcsParser=this.register(new o.DcsParser),this._errorHandler=this._errorHandlerFb,this.registerEscHandler({final:"\\\\"},(()=>!0))}_identifier(e,t=[64,126]){let i=0;if(e.prefix){if(e.prefix.length>1)throw new Error("only one byte as prefix supported");if(i=e.prefix.charCodeAt(0),i&&60>i||i>63)throw new Error("prefix must be in range 0x3c .. 0x3f")}if(e.intermediates){if(e.intermediates.length>2)throw new Error("only two bytes as intermediates are supported");for(let t=0;t<e.intermediates.length;++t){const s=e.intermediates.charCodeAt(t);if(32>s||s>47)throw new Error("intermediate must be in range 0x20 .. 0x2f");i<<=8,i|=s}}if(1!==e.final.length)throw new Error("final must be a single byte");const s=e.final.charCodeAt(0);if(t[0]>s||s>t[1])throw new Error(`final must be in range ${t[0]} .. ${t[1]}`);return i<<=8,i|=s,i}identToString(e){const t=[];for(;e;)t.push(String.fromCharCode(255&e)),e>>=8;return t.reverse().join("")}setPrintHandler(e){this._printHandler=e}clearPrintHandler(){this._printHandler=this._printHandlerFb}registerEscHandler(e,t){const i=this._identifier(e,[48,126]);void 0===this._escHandlers[i]&&(this._escHandlers[i]=[]);const s=this._escHandlers[i];return s.push(t),{dispose:()=>{const e=s.indexOf(t);-1!==e&&s.splice(e,1)}}}clearEscHandler(e){this._escHandlers[this._identifier(e,[48,126])]&&delete this._escHandlers[this._identifier(e,[48,126])]}setEscHandlerFallback(e){this._escHandlerFb=e}setExecuteHandler(e,t){this._executeHandlers[e.charCodeAt(0)]=t}clearExecuteHandler(e){this._executeHandlers[e.charCodeAt(0)]&&delete this._executeHandlers[e.charCodeAt(0)]}setExecuteHandlerFallback(e){this._executeHandlerFb=e}registerCsiHandler(e,t){const i=this._identifier(e);void 0===this._csiHandlers[i]&&(this._csiHandlers[i]=[]);const s=this._csiHandlers[i];return s.push(t),{dispose:()=>{const e=s.indexOf(t);-1!==e&&s.splice(e,1)}}}clearCsiHandler(e){this._csiHandlers[this._identifier(e)]&&delete this._csiHandlers[this._identifier(e)]}setCsiHandlerFallback(e){this._csiHandlerFb=e}registerDcsHandler(e,t){return this._dcsParser.registerHandler(this._identifier(e),t)}clearDcsHandler(e){this._dcsParser.clearHandler(this._identifier(e))}setDcsHandlerFallback(e){this._dcsParser.setHandlerFallback(e)}registerOscHandler(e,t){return this._oscParser.registerHandler(e,t)}clearOscHandler(e){this._oscParser.clearHandler(e)}setOscHandlerFallback(e){this._oscParser.setHandlerFallback(e)}setErrorHandler(e){this._errorHandler=e}clearErrorHandler(){this._errorHandler=this._errorHandlerFb}reset(){this.currentState=this.initialState,this._oscParser.reset(),this._dcsParser.reset(),this._params.reset(),this._params.addParam(0),this._collect=0,this.precedingJoinState=0,0!==this._parseStack.state&&(this._parseStack.state=2,this._parseStack.handlers=[])}_preserveStack(e,t,i,s,r){this._parseStack.state=e,this._parseStack.handlers=t,this._parseStack.handlerPos=i,this._parseStack.transition=s,this._parseStack.chunkPos=r}parse(e,t,i){let s,r=0,n=0,o=0;if(this._parseStack.state)if(2===this._parseStack.state)this._parseStack.state=0,o=this._parseStack.chunkPos+1;else{if(void 0===i||1===this._parseStack.state)throw this._parseStack.state=1,new Error("improper continuation due to previous async handler, giving up parsing");const t=this._parseStack.handlers;let n=this._parseStack.handlerPos-1;switch(this._parseStack.state){case 3:if(!1===i&&n>-1)for(;n>=0&&(s=t[n](this._params),!0!==s);n--)if(s instanceof Promise)return this._parseStack.handlerPos=n,s;this._parseStack.handlers=[];break;case 4:if(!1===i&&n>-1)for(;n>=0&&(s=t[n](),!0!==s);n--)if(s instanceof Promise)return this._parseStack.handlerPos=n,s;this._parseStack.handlers=[];break;case 6:if(r=e[this._parseStack.chunkPos],s=this._dcsParser.unhook(24!==r&&26!==r,i),s)return s;27===r&&(this._parseStack.transition|=1),this._params.reset(),this._params.addParam(0),this._collect=0;break;case 5:if(r=e[this._parseStack.chunkPos],s=this._oscParser.end(24!==r&&26!==r,i),s)return s;27===r&&(this._parseStack.transition|=1),this._params.reset(),this._params.addParam(0),this._collect=0}this._parseStack.state=0,o=this._parseStack.chunkPos+1,this.precedingJoinState=0,this.currentState=15&this._parseStack.transition}for(let i=o;i<t;++i){switch(r=e[i],n=this._transitions.table[this.currentState<<8|(r<160?r:h)],n>>4){case 2:for(let s=i+1;;++s){if(s>=t||(r=e[s])<32||r>126&&r<h){this._printHandler(e,i,s),i=s-1;break}if(++s>=t||(r=e[s])<32||r>126&&r<h){this._printHandler(e,i,s),i=s-1;break}if(++s>=t||(r=e[s])<32||r>126&&r<h){this._printHandler(e,i,s),i=s-1;break}if(++s>=t||(r=e[s])<32||r>126&&r<h){this._printHandler(e,i,s),i=s-1;break}}break;case 3:this._executeHandlers[r]?this._executeHandlers[r]():this._executeHandlerFb(r),this.precedingJoinState=0;break;case 0:break;case 1:if(this._errorHandler({position:i,code:r,currentState:this.currentState,collect:this._collect,params:this._params,abort:!1}).abort)return;break;case 7:const o=this._csiHandlers[this._collect<<8|r];let a=o?o.length-1:-1;for(;a>=0&&(s=o[a](this._params),!0!==s);a--)if(s instanceof Promise)return this._preserveStack(3,o,a,n,i),s;a<0&&this._csiHandlerFb(this._collect<<8|r,this._params),this.precedingJoinState=0;break;case 8:do{switch(r){case 59:this._params.addParam(0);break;case 58:this._params.addSubParam(-1);break;default:this._params.addDigit(r-48)}}while(++i<t&&(r=e[i])>47&&r<60);i--;break;case 9:this._collect<<=8,this._collect|=r;break;case 10:const c=this._escHandlers[this._collect<<8|r];let l=c?c.length-1:-1;for(;l>=0&&(s=c[l](),!0!==s);l--)if(s instanceof Promise)return this._preserveStack(4,c,l,n,i),s;l<0&&this._escHandlerFb(this._collect<<8|r),this.precedingJoinState=0;break;case 11:this._params.reset(),this._params.addParam(0),this._collect=0;break;case 12:this._dcsParser.hook(this._collect<<8|r,this._params);break;case 13:for(let s=i+1;;++s)if(s>=t||24===(r=e[s])||26===r||27===r||r>127&&r<h){this._dcsParser.put(e,i,s),i=s-1;break}break;case 14:if(s=this._dcsParser.unhook(24!==r&&26!==r),s)return this._preserveStack(6,[],0,n,i),s;27===r&&(n|=1),this._params.reset(),this._params.addParam(0),this._collect=0,this.precedingJoinState=0;break;case 4:this._oscParser.start();break;case 5:for(let s=i+1;;s++)if(s>=t||(r=e[s])<32||r>127&&r<h){this._oscParser.put(e,i,s),i=s-1;break}break;case 6:if(s=this._oscParser.end(24!==r&&26!==r),s)return this._preserveStack(5,[],0,n,i),s;27===r&&(n|=1),this._params.reset(),this._params.addParam(0),this._collect=0,this.precedingJoinState=0}this.currentState=15&n}}}t.EscapeSequenceParser=c},6242:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.OscHandler=t.OscParser=void 0;const s=i(5770),r=i(482),n=[];t.OscParser=class{constructor(){this._state=0,this._active=n,this._id=-1,this._handlers=Object.create(null),this._handlerFb=()=>{},this._stack={paused:!1,loopPosition:0,fallThrough:!1}}registerHandler(e,t){void 0===this._handlers[e]&&(this._handlers[e]=[]);const i=this._handlers[e];return i.push(t),{dispose:()=>{const e=i.indexOf(t);-1!==e&&i.splice(e,1)}}}clearHandler(e){this._handlers[e]&&delete this._handlers[e]}setHandlerFallback(e){this._handlerFb=e}dispose(){this._handlers=Object.create(null),this._handlerFb=()=>{},this._active=n}reset(){if(2===this._state)for(let e=this._stack.paused?this._stack.loopPosition-1:this._active.length-1;e>=0;--e)this._active[e].end(!1);this._stack.paused=!1,this._active=n,this._id=-1,this._state=0}_start(){if(this._active=this._handlers[this._id]||n,this._active.length)for(let e=this._active.length-1;e>=0;e--)this._active[e].start();else this._handlerFb(this._id,"START")}_put(e,t,i){if(this._active.length)for(let s=this._active.length-1;s>=0;s--)this._active[s].put(e,t,i);else this._handlerFb(this._id,"PUT",(0,r.utf32ToString)(e,t,i))}start(){this.reset(),this._state=1}put(e,t,i){if(3!==this._state){if(1===this._state)for(;t<i;){const i=e[t++];if(59===i){this._state=2,this._start();break}if(i<48||57<i)return void(this._state=3);-1===this._id&&(this._id=0),this._id=10*this._id+i-48}2===this._state&&i-t>0&&this._put(e,t,i)}}end(e,t=!0){if(0!==this._state){if(3!==this._state)if(1===this._state&&this._start(),this._active.length){let i=!1,s=this._active.length-1,r=!1;if(this._stack.paused&&(s=this._stack.loopPosition-1,i=t,r=this._stack.fallThrough,this._stack.paused=!1),!r&&!1===i){for(;s>=0&&(i=this._active[s].end(e),!0!==i);s--)if(i instanceof Promise)return this._stack.paused=!0,this._stack.loopPosition=s,this._stack.fallThrough=!1,i;s--}for(;s>=0;s--)if(i=this._active[s].end(!1),i instanceof Promise)return this._stack.paused=!0,this._stack.loopPosition=s,this._stack.fallThrough=!0,i}else this._handlerFb(this._id,"END",e);this._active=n,this._id=-1,this._state=0}}},t.OscHandler=class{constructor(e){this._handler=e,this._data="",this._hitLimit=!1}start(){this._data="",this._hitLimit=!1}put(e,t,i){this._hitLimit||(this._data+=(0,r.utf32ToString)(e,t,i),this._data.length>s.PAYLOAD_LIMIT&&(this._data="",this._hitLimit=!0))}end(e){let t=!1;if(this._hitLimit)t=!1;else if(e&&(t=this._handler(this._data),t instanceof Promise))return t.then((e=>(this._data="",this._hitLimit=!1,e)));return this._data="",this._hitLimit=!1,t}}},8742:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Params=void 0;const i=2147483647;class s{static fromArray(e){const t=new s;if(!e.length)return t;for(let i=Array.isArray(e[0])?1:0;i<e.length;++i){const s=e[i];if(Array.isArray(s))for(let e=0;e<s.length;++e)t.addSubParam(s[e]);else t.addParam(s)}return t}constructor(e=32,t=32){if(this.maxLength=e,this.maxSubParamsLength=t,t>256)throw new Error("maxSubParamsLength must not be greater than 256");this.params=new Int32Array(e),this.length=0,this._subParams=new Int32Array(t),this._subParamsLength=0,this._subParamsIdx=new Uint16Array(e),this._rejectDigits=!1,this._rejectSubDigits=!1,this._digitIsSub=!1}clone(){const e=new s(this.maxLength,this.maxSubParamsLength);return e.params.set(this.params),e.length=this.length,e._subParams.set(this._subParams),e._subParamsLength=this._subParamsLength,e._subParamsIdx.set(this._subParamsIdx),e._rejectDigits=this._rejectDigits,e._rejectSubDigits=this._rejectSubDigits,e._digitIsSub=this._digitIsSub,e}toArray(){const e=[];for(let t=0;t<this.length;++t){e.push(this.params[t]);const i=this._subParamsIdx[t]>>8,s=255&this._subParamsIdx[t];s-i>0&&e.push(Array.prototype.slice.call(this._subParams,i,s))}return e}reset(){this.length=0,this._subParamsLength=0,this._rejectDigits=!1,this._rejectSubDigits=!1,this._digitIsSub=!1}addParam(e){if(this._digitIsSub=!1,this.length>=this.maxLength)this._rejectDigits=!0;else{if(e<-1)throw new Error("values lesser than -1 are not allowed");this._subParamsIdx[this.length]=this._subParamsLength<<8|this._subParamsLength,this.params[this.length++]=e>i?i:e}}addSubParam(e){if(this._digitIsSub=!0,this.length)if(this._rejectDigits||this._subParamsLength>=this.maxSubParamsLength)this._rejectSubDigits=!0;else{if(e<-1)throw new Error("values lesser than -1 are not allowed");this._subParams[this._subParamsLength++]=e>i?i:e,this._subParamsIdx[this.length-1]++}}hasSubParams(e){return(255&this._subParamsIdx[e])-(this._subParamsIdx[e]>>8)>0}getSubParams(e){const t=this._subParamsIdx[e]>>8,i=255&this._subParamsIdx[e];return i-t>0?this._subParams.subarray(t,i):null}getSubParamsAll(){const e={};for(let t=0;t<this.length;++t){const i=this._subParamsIdx[t]>>8,s=255&this._subParamsIdx[t];s-i>0&&(e[t]=this._subParams.slice(i,s))}return e}addDigit(e){let t;if(this._rejectDigits||!(t=this._digitIsSub?this._subParamsLength:this.length)||this._digitIsSub&&this._rejectSubDigits)return;const s=this._digitIsSub?this._subParams:this.params,r=s[t-1];s[t-1]=~r?Math.min(10*r+e,i):e}}t.Params=s},5741:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.AddonManager=void 0,t.AddonManager=class{constructor(){this._addons=[]}dispose(){for(let e=this._addons.length-1;e>=0;e--)this._addons[e].instance.dispose()}loadAddon(e,t){const i={instance:t,dispose:t.dispose,isDisposed:!1};this._addons.push(i),t.dispose=()=>this._wrappedAddonDispose(i),t.activate(e)}_wrappedAddonDispose(e){if(e.isDisposed)return;let t=-1;for(let i=0;i<this._addons.length;i++)if(this._addons[i]===e){t=i;break}if(-1===t)throw new Error("Could not dispose an addon that has not been loaded");e.isDisposed=!0,e.dispose.apply(e.instance),this._addons.splice(t,1)}}},8771:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferApiView=void 0;const s=i(3785),r=i(511);t.BufferApiView=class{constructor(e,t){this._buffer=e,this.type=t}init(e){return this._buffer=e,this}get cursorY(){return this._buffer.y}get cursorX(){return this._buffer.x}get viewportY(){return this._buffer.ydisp}get baseY(){return this._buffer.ybase}get length(){return this._buffer.lines.length}getLine(e){const t=this._buffer.lines.get(e);if(t)return new s.BufferLineApiView(t)}getNullCell(){return new r.CellData}}},3785:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferLineApiView=void 0;const s=i(511);t.BufferLineApiView=class{constructor(e){this._line=e}get isWrapped(){return this._line.isWrapped}get length(){return this._line.length}getCell(e,t){if(!(e<0||e>=this._line.length))return t?(this._line.loadCell(e,t),t):this._line.loadCell(e,new s.CellData)}translateToString(e,t,i){return this._line.translateToString(e,t,i)}}},8285:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferNamespaceApi=void 0;const s=i(8771),r=i(8460),n=i(844);class o extends n.Disposable{constructor(e){super(),this._core=e,this._onBufferChange=this.register(new r.EventEmitter),this.onBufferChange=this._onBufferChange.event,this._normal=new s.BufferApiView(this._core.buffers.normal,"normal"),this._alternate=new s.BufferApiView(this._core.buffers.alt,"alternate"),this._core.buffers.onBufferActivate((()=>this._onBufferChange.fire(this.active)))}get active(){if(this._core.buffers.active===this._core.buffers.normal)return this.normal;if(this._core.buffers.active===this._core.buffers.alt)return this.alternate;throw new Error("Active buffer is neither normal nor alternate")}get normal(){return this._normal.init(this._core.buffers.normal)}get alternate(){return this._alternate.init(this._core.buffers.alt)}}t.BufferNamespaceApi=o},7975:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ParserApi=void 0,t.ParserApi=class{constructor(e){this._core=e}registerCsiHandler(e,t){return this._core.registerCsiHandler(e,(e=>t(e.toArray())))}addCsiHandler(e,t){return this.registerCsiHandler(e,t)}registerDcsHandler(e,t){return this._core.registerDcsHandler(e,((e,i)=>t(e,i.toArray())))}addDcsHandler(e,t){return this.registerDcsHandler(e,t)}registerEscHandler(e,t){return this._core.registerEscHandler(e,t)}addEscHandler(e,t){return this.registerEscHandler(e,t)}registerOscHandler(e,t){return this._core.registerOscHandler(e,t)}addOscHandler(e,t){return this.registerOscHandler(e,t)}}},7090:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.UnicodeApi=void 0,t.UnicodeApi=class{constructor(e){this._core=e}register(e){this._core.unicodeService.register(e)}get versions(){return this._core.unicodeService.versions}get activeVersion(){return this._core.unicodeService.activeVersion}set activeVersion(e){this._core.unicodeService.activeVersion=e}}},744:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.BufferService=t.MINIMUM_ROWS=t.MINIMUM_COLS=void 0;const n=i(8460),o=i(844),a=i(5295),h=i(2585);t.MINIMUM_COLS=2,t.MINIMUM_ROWS=1;let c=t.BufferService=class extends o.Disposable{get buffer(){return this.buffers.active}constructor(e){super(),this.isUserScrolling=!1,this._onResize=this.register(new n.EventEmitter),this.onResize=this._onResize.event,this._onScroll=this.register(new n.EventEmitter),this.onScroll=this._onScroll.event,this.cols=Math.max(e.rawOptions.cols||0,t.MINIMUM_COLS),this.rows=Math.max(e.rawOptions.rows||0,t.MINIMUM_ROWS),this.buffers=this.register(new a.BufferSet(e,this))}resize(e,t){this.cols=e,this.rows=t,this.buffers.resize(e,t),this._onResize.fire({cols:e,rows:t})}reset(){this.buffers.reset(),this.isUserScrolling=!1}scroll(e,t=!1){const i=this.buffer;let s;s=this._cachedBlankLine,s&&s.length===this.cols&&s.getFg(0)===e.fg&&s.getBg(0)===e.bg||(s=i.getBlankLine(e,t),this._cachedBlankLine=s),s.isWrapped=t;const r=i.ybase+i.scrollTop,n=i.ybase+i.scrollBottom;if(0===i.scrollTop){const e=i.lines.isFull;n===i.lines.length-1?e?i.lines.recycle().copyFrom(s):i.lines.push(s.clone()):i.lines.splice(n+1,0,s.clone()),e?this.isUserScrolling&&(i.ydisp=Math.max(i.ydisp-1,0)):(i.ybase++,this.isUserScrolling||i.ydisp++)}else{const e=n-r+1;i.lines.shiftElements(r+1,e-1,-1),i.lines.set(n,s.clone())}this.isUserScrolling||(i.ydisp=i.ybase),this._onScroll.fire(i.ydisp)}scrollLines(e,t,i){const s=this.buffer;if(e<0){if(0===s.ydisp)return;this.isUserScrolling=!0}else e+s.ydisp>=s.ybase&&(this.isUserScrolling=!1);const r=s.ydisp;s.ydisp=Math.max(Math.min(s.ydisp+e,s.ybase),0),r!==s.ydisp&&(t||this._onScroll.fire(s.ydisp))}};t.BufferService=c=s([r(0,h.IOptionsService)],c)},7994:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CharsetService=void 0,t.CharsetService=class{constructor(){this.glevel=0,this._charsets=[]}reset(){this.charset=void 0,this._charsets=[],this.glevel=0}setgLevel(e){this.glevel=e,this.charset=this._charsets[e]}setgCharset(e,t){this._charsets[e]=t,this.glevel===e&&(this.charset=t)}}},1753:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CoreMouseService=void 0;const n=i(2585),o=i(8460),a=i(844),h={NONE:{events:0,restrict:()=>!1},X10:{events:1,restrict:e=>4!==e.button&&1===e.action&&(e.ctrl=!1,e.alt=!1,e.shift=!1,!0)},VT200:{events:19,restrict:e=>32!==e.action},DRAG:{events:23,restrict:e=>32!==e.action||3!==e.button},ANY:{events:31,restrict:e=>!0}};function c(e,t){let i=(e.ctrl?16:0)|(e.shift?4:0)|(e.alt?8:0);return 4===e.button?(i|=64,i|=e.action):(i|=3&e.button,4&e.button&&(i|=64),8&e.button&&(i|=128),32===e.action?i|=32:0!==e.action||t||(i|=3)),i}const l=String.fromCharCode,d={DEFAULT:e=>{const t=[c(e,!1)+32,e.col+32,e.row+32];return t[0]>255||t[1]>255||t[2]>255?"":`\x1B[M${l(t[0])}${l(t[1])}${l(t[2])}`},SGR:e=>{const t=0===e.action&&4!==e.button?"m":"M";return`\x1B[<${c(e,!0)};${e.col};${e.row}${t}`},SGR_PIXELS:e=>{const t=0===e.action&&4!==e.button?"m":"M";return`\x1B[<${c(e,!0)};${e.x};${e.y}${t}`}};let _=t.CoreMouseService=class extends a.Disposable{constructor(e,t){super(),this._bufferService=e,this._coreService=t,this._protocols={},this._encodings={},this._activeProtocol="",this._activeEncoding="",this._lastEvent=null,this._onProtocolChange=this.register(new o.EventEmitter),this.onProtocolChange=this._onProtocolChange.event;for(const e of Object.keys(h))this.addProtocol(e,h[e]);for(const e of Object.keys(d))this.addEncoding(e,d[e]);this.reset()}addProtocol(e,t){this._protocols[e]=t}addEncoding(e,t){this._encodings[e]=t}get activeProtocol(){return this._activeProtocol}get areMouseEventsActive(){return 0!==this._protocols[this._activeProtocol].events}set activeProtocol(e){if(!this._protocols[e])throw new Error(`unknown protocol "${e}"`);this._activeProtocol=e,this._onProtocolChange.fire(this._protocols[e].events)}get activeEncoding(){return this._activeEncoding}set activeEncoding(e){if(!this._encodings[e])throw new Error(`unknown encoding "${e}"`);this._activeEncoding=e}reset(){this.activeProtocol="NONE",this.activeEncoding="DEFAULT",this._lastEvent=null}triggerMouseEvent(e){if(e.col<0||e.col>=this._bufferService.cols||e.row<0||e.row>=this._bufferService.rows)return!1;if(4===e.button&&32===e.action)return!1;if(3===e.button&&32!==e.action)return!1;if(4!==e.button&&(2===e.action||3===e.action))return!1;if(e.col++,e.row++,32===e.action&&this._lastEvent&&this._equalEvents(this._lastEvent,e,"SGR_PIXELS"===this._activeEncoding))return!1;if(!this._protocols[this._activeProtocol].restrict(e))return!1;const t=this._encodings[this._activeEncoding](e);return t&&("DEFAULT"===this._activeEncoding?this._coreService.triggerBinaryEvent(t):this._coreService.triggerDataEvent(t,!0)),this._lastEvent=e,!0}explainEvents(e){return{down:!!(1&e),up:!!(2&e),drag:!!(4&e),move:!!(8&e),wheel:!!(16&e)}}_equalEvents(e,t,i){if(i){if(e.x!==t.x)return!1;if(e.y!==t.y)return!1}else{if(e.col!==t.col)return!1;if(e.row!==t.row)return!1}return e.button===t.button&&e.action===t.action&&e.ctrl===t.ctrl&&e.alt===t.alt&&e.shift===t.shift}};t.CoreMouseService=_=s([r(0,n.IBufferService),r(1,n.ICoreService)],_)},6975:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CoreService=void 0;const n=i(1439),o=i(8460),a=i(844),h=i(2585),c=Object.freeze({insertMode:!1}),l=Object.freeze({applicationCursorKeys:!1,applicationKeypad:!1,bracketedPasteMode:!1,origin:!1,reverseWraparound:!1,sendFocus:!1,wraparound:!0});let d=t.CoreService=class extends a.Disposable{constructor(e,t,i){super(),this._bufferService=e,this._logService=t,this._optionsService=i,this.isCursorInitialized=!1,this.isCursorHidden=!1,this._onData=this.register(new o.EventEmitter),this.onData=this._onData.event,this._onUserInput=this.register(new o.EventEmitter),this.onUserInput=this._onUserInput.event,this._onBinary=this.register(new o.EventEmitter),this.onBinary=this._onBinary.event,this._onRequestScrollToBottom=this.register(new o.EventEmitter),this.onRequestScrollToBottom=this._onRequestScrollToBottom.event,this.modes=(0,n.clone)(c),this.decPrivateModes=(0,n.clone)(l)}reset(){this.modes=(0,n.clone)(c),this.decPrivateModes=(0,n.clone)(l)}triggerDataEvent(e,t=!1){if(this._optionsService.rawOptions.disableStdin)return;const i=this._bufferService.buffer;t&&this._optionsService.rawOptions.scrollOnUserInput&&i.ybase!==i.ydisp&&this._onRequestScrollToBottom.fire(),t&&this._onUserInput.fire(),this._logService.debug(`sending data "${e}"`,(()=>e.split("").map((e=>e.charCodeAt(0))))),this._onData.fire(e)}triggerBinaryEvent(e){this._optionsService.rawOptions.disableStdin||(this._logService.debug(`sending binary "${e}"`,(()=>e.split("").map((e=>e.charCodeAt(0))))),this._onBinary.fire(e))}};t.CoreService=d=s([r(0,h.IBufferService),r(1,h.ILogService),r(2,h.IOptionsService)],d)},9074:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DecorationService=void 0;const s=i(8055),r=i(8460),n=i(844),o=i(6106);let a=0,h=0;class c extends n.Disposable{get decorations(){return this._decorations.values()}constructor(){super(),this._decorations=new o.SortedList((e=>e?.marker.line)),this._onDecorationRegistered=this.register(new r.EventEmitter),this.onDecorationRegistered=this._onDecorationRegistered.event,this._onDecorationRemoved=this.register(new r.EventEmitter),this.onDecorationRemoved=this._onDecorationRemoved.event,this.register((0,n.toDisposable)((()=>this.reset())))}registerDecoration(e){if(e.marker.isDisposed)return;const t=new l(e);if(t){const e=t.marker.onDispose((()=>t.dispose()));t.onDispose((()=>{t&&(this._decorations.delete(t)&&this._onDecorationRemoved.fire(t),e.dispose())})),this._decorations.insert(t),this._onDecorationRegistered.fire(t)}return t}reset(){for(const e of this._decorations.values())e.dispose();this._decorations.clear()}*getDecorationsAtCell(e,t,i){let s=0,r=0;for(const n of this._decorations.getKeyIterator(t))s=n.options.x??0,r=s+(n.options.width??1),e>=s&&e<r&&(!i||(n.options.layer??"bottom")===i)&&(yield n)}forEachDecorationAtCell(e,t,i,s){this._decorations.forEachByKey(t,(t=>{a=t.options.x??0,h=a+(t.options.width??1),e>=a&&e<h&&(!i||(t.options.layer??"bottom")===i)&&s(t)}))}}t.DecorationService=c;class l extends n.Disposable{get isDisposed(){return this._isDisposed}get backgroundColorRGB(){return null===this._cachedBg&&(this.options.backgroundColor?this._cachedBg=s.css.toColor(this.options.backgroundColor):this._cachedBg=void 0),this._cachedBg}get foregroundColorRGB(){return null===this._cachedFg&&(this.options.foregroundColor?this._cachedFg=s.css.toColor(this.options.foregroundColor):this._cachedFg=void 0),this._cachedFg}constructor(e){super(),this.options=e,this.onRenderEmitter=this.register(new r.EventEmitter),this.onRender=this.onRenderEmitter.event,this._onDispose=this.register(new r.EventEmitter),this.onDispose=this._onDispose.event,this._cachedBg=null,this._cachedFg=null,this.marker=e.marker,this.options.overviewRulerOptions&&!this.options.overviewRulerOptions.position&&(this.options.overviewRulerOptions.position="full")}dispose(){this._onDispose.fire(),super.dispose()}}},4348:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.InstantiationService=t.ServiceCollection=void 0;const s=i(2585),r=i(8343);class n{constructor(...e){this._entries=new Map;for(const[t,i]of e)this.set(t,i)}set(e,t){const i=this._entries.get(e);return this._entries.set(e,t),i}forEach(e){for(const[t,i]of this._entries.entries())e(t,i)}has(e){return this._entries.has(e)}get(e){return this._entries.get(e)}}t.ServiceCollection=n,t.InstantiationService=class{constructor(){this._services=new n,this._services.set(s.IInstantiationService,this)}setService(e,t){this._services.set(e,t)}getService(e){return this._services.get(e)}createInstance(e,...t){const i=(0,r.getServiceDependencies)(e).sort(((e,t)=>e.index-t.index)),s=[];for(const t of i){const i=this._services.get(t.id);if(!i)throw new Error(`[createInstance] ${e.name} depends on UNKNOWN service ${t.id}.`);s.push(i)}const n=i.length>0?i[0].index:t.length;if(t.length!==n)throw new Error(`[createInstance] First service dependency of ${e.name} at position ${n+1} conflicts with ${t.length} static arguments`);return new e(...[...t,...s])}}},7866:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.traceCall=t.setTraceLogger=t.LogService=void 0;const n=i(844),o=i(2585),a={trace:o.LogLevelEnum.TRACE,debug:o.LogLevelEnum.DEBUG,info:o.LogLevelEnum.INFO,warn:o.LogLevelEnum.WARN,error:o.LogLevelEnum.ERROR,off:o.LogLevelEnum.OFF};let h,c=t.LogService=class extends n.Disposable{get logLevel(){return this._logLevel}constructor(e){super(),this._optionsService=e,this._logLevel=o.LogLevelEnum.OFF,this._updateLogLevel(),this.register(this._optionsService.onSpecificOptionChange("logLevel",(()=>this._updateLogLevel()))),h=this}_updateLogLevel(){this._logLevel=a[this._optionsService.rawOptions.logLevel]}_evalLazyOptionalParams(e){for(let t=0;t<e.length;t++)"function"==typeof e[t]&&(e[t]=e[t]())}_log(e,t,i){this._evalLazyOptionalParams(i),e.call(console,(this._optionsService.options.logger?"":"xterm.js: ")+t,...i)}trace(e,...t){this._logLevel<=o.LogLevelEnum.TRACE&&this._log(this._optionsService.options.logger?.trace.bind(this._optionsService.options.logger)??console.log,e,t)}debug(e,...t){this._logLevel<=o.LogLevelEnum.DEBUG&&this._log(this._optionsService.options.logger?.debug.bind(this._optionsService.options.logger)??console.log,e,t)}info(e,...t){this._logLevel<=o.LogLevelEnum.INFO&&this._log(this._optionsService.options.logger?.info.bind(this._optionsService.options.logger)??console.info,e,t)}warn(e,...t){this._logLevel<=o.LogLevelEnum.WARN&&this._log(this._optionsService.options.logger?.warn.bind(this._optionsService.options.logger)??console.warn,e,t)}error(e,...t){this._logLevel<=o.LogLevelEnum.ERROR&&this._log(this._optionsService.options.logger?.error.bind(this._optionsService.options.logger)??console.error,e,t)}};t.LogService=c=s([r(0,o.IOptionsService)],c),t.setTraceLogger=function(e){h=e},t.traceCall=function(e,t,i){if("function"!=typeof i.value)throw new Error("not supported");const s=i.value;i.value=function(...e){if(h.logLevel!==o.LogLevelEnum.TRACE)return s.apply(this,e);h.trace(`GlyphRenderer#${s.name}(${e.map((e=>JSON.stringify(e))).join(", ")})`);const t=s.apply(this,e);return h.trace(`GlyphRenderer#${s.name} return`,t),t}}},7302:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.OptionsService=t.DEFAULT_OPTIONS=void 0;const s=i(8460),r=i(844),n=i(6114);t.DEFAULT_OPTIONS={cols:80,rows:24,cursorBlink:!1,cursorStyle:"block",cursorWidth:1,cursorInactiveStyle:"outline",customGlyphs:!0,drawBoldTextInBrightColors:!0,documentOverride:null,fastScrollModifier:"alt",fastScrollSensitivity:5,fontFamily:"courier-new, courier, monospace",fontSize:15,fontWeight:"normal",fontWeightBold:"bold",ignoreBracketedPasteMode:!1,lineHeight:1,letterSpacing:0,linkHandler:null,logLevel:"info",logger:null,scrollback:1e3,scrollOnUserInput:!0,scrollSensitivity:1,screenReaderMode:!1,smoothScrollDuration:0,macOptionIsMeta:!1,macOptionClickForcesSelection:!1,minimumContrastRatio:1,disableStdin:!1,allowProposedApi:!1,allowTransparency:!1,tabStopWidth:8,theme:{},rescaleOverlappingGlyphs:!1,rightClickSelectsWord:n.isMac,windowOptions:{},windowsMode:!1,windowsPty:{},wordSeparator:" ()[]{}\',\\"`",altClickMovesCursor:!0,convertEol:!1,termName:"xterm",cancelEvents:!1,overviewRulerWidth:0};const o=["normal","bold","100","200","300","400","500","600","700","800","900"];class a extends r.Disposable{constructor(e){super(),this._onOptionChange=this.register(new s.EventEmitter),this.onOptionChange=this._onOptionChange.event;const i={...t.DEFAULT_OPTIONS};for(const t in e)if(t in i)try{const s=e[t];i[t]=this._sanitizeAndValidateOption(t,s)}catch(e){console.error(e)}this.rawOptions=i,this.options={...i},this._setupOptions(),this.register((0,r.toDisposable)((()=>{this.rawOptions.linkHandler=null,this.rawOptions.documentOverride=null})))}onSpecificOptionChange(e,t){return this.onOptionChange((i=>{i===e&&t(this.rawOptions[e])}))}onMultipleOptionChange(e,t){return this.onOptionChange((i=>{-1!==e.indexOf(i)&&t()}))}_setupOptions(){const e=e=>{if(!(e in t.DEFAULT_OPTIONS))throw new Error(`No option with key "${e}"`);return this.rawOptions[e]},i=(e,i)=>{if(!(e in t.DEFAULT_OPTIONS))throw new Error(`No option with key "${e}"`);i=this._sanitizeAndValidateOption(e,i),this.rawOptions[e]!==i&&(this.rawOptions[e]=i,this._onOptionChange.fire(e))};for(const t in this.rawOptions){const s={get:e.bind(this,t),set:i.bind(this,t)};Object.defineProperty(this.options,t,s)}}_sanitizeAndValidateOption(e,i){switch(e){case"cursorStyle":if(i||(i=t.DEFAULT_OPTIONS[e]),!function(e){return"block"===e||"underline"===e||"bar"===e}(i))throw new Error(`"${i}" is not a valid value for ${e}`);break;case"wordSeparator":i||(i=t.DEFAULT_OPTIONS[e]);break;case"fontWeight":case"fontWeightBold":if("number"==typeof i&&1<=i&&i<=1e3)break;i=o.includes(i)?i:t.DEFAULT_OPTIONS[e];break;case"cursorWidth":i=Math.floor(i);case"lineHeight":case"tabStopWidth":if(i<1)throw new Error(`${e} cannot be less than 1, value: ${i}`);break;case"minimumContrastRatio":i=Math.max(1,Math.min(21,Math.round(10*i)/10));break;case"scrollback":if((i=Math.min(i,4294967295))<0)throw new Error(`${e} cannot be less than 0, value: ${i}`);break;case"fastScrollSensitivity":case"scrollSensitivity":if(i<=0)throw new Error(`${e} cannot be less than or equal to 0, value: ${i}`);break;case"rows":case"cols":if(!i&&0!==i)throw new Error(`${e} must be numeric, value: ${i}`);break;case"windowsPty":i=i??{}}return i}}t.OptionsService=a},2660:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.OscLinkService=void 0;const n=i(2585);let o=t.OscLinkService=class{constructor(e){this._bufferService=e,this._nextId=1,this._entriesWithId=new Map,this._dataByLinkId=new Map}registerLink(e){const t=this._bufferService.buffer;if(void 0===e.id){const i=t.addMarker(t.ybase+t.y),s={data:e,id:this._nextId++,lines:[i]};return i.onDispose((()=>this._removeMarkerFromLink(s,i))),this._dataByLinkId.set(s.id,s),s.id}const i=e,s=this._getEntryIdKey(i),r=this._entriesWithId.get(s);if(r)return this.addLineToLink(r.id,t.ybase+t.y),r.id;const n=t.addMarker(t.ybase+t.y),o={id:this._nextId++,key:this._getEntryIdKey(i),data:i,lines:[n]};return n.onDispose((()=>this._removeMarkerFromLink(o,n))),this._entriesWithId.set(o.key,o),this._dataByLinkId.set(o.id,o),o.id}addLineToLink(e,t){const i=this._dataByLinkId.get(e);if(i&&i.lines.every((e=>e.line!==t))){const e=this._bufferService.buffer.addMarker(t);i.lines.push(e),e.onDispose((()=>this._removeMarkerFromLink(i,e)))}}getLinkData(e){return this._dataByLinkId.get(e)?.data}_getEntryIdKey(e){return`${e.id};;${e.uri}`}_removeMarkerFromLink(e,t){const i=e.lines.indexOf(t);-1!==i&&(e.lines.splice(i,1),0===e.lines.length&&(void 0!==e.data.id&&this._entriesWithId.delete(e.key),this._dataByLinkId.delete(e.id)))}};t.OscLinkService=o=s([r(0,n.IBufferService)],o)},8343:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.createDecorator=t.getServiceDependencies=t.serviceRegistry=void 0;const i="di$target",s="di$dependencies";t.serviceRegistry=new Map,t.getServiceDependencies=function(e){return e[s]||[]},t.createDecorator=function(e){if(t.serviceRegistry.has(e))return t.serviceRegistry.get(e);const r=function(e,t,n){if(3!==arguments.length)throw new Error("@IServiceName-decorator can only be used to decorate a parameter");!function(e,t,r){t[i]===t?t[s].push({id:e,index:r}):(t[s]=[{id:e,index:r}],t[i]=t)}(r,e,n)};return r.toString=()=>e,t.serviceRegistry.set(e,r),r}},2585:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.IDecorationService=t.IUnicodeService=t.IOscLinkService=t.IOptionsService=t.ILogService=t.LogLevelEnum=t.IInstantiationService=t.ICharsetService=t.ICoreService=t.ICoreMouseService=t.IBufferService=void 0;const s=i(8343);var r;t.IBufferService=(0,s.createDecorator)("BufferService"),t.ICoreMouseService=(0,s.createDecorator)("CoreMouseService"),t.ICoreService=(0,s.createDecorator)("CoreService"),t.ICharsetService=(0,s.createDecorator)("CharsetService"),t.IInstantiationService=(0,s.createDecorator)("InstantiationService"),function(e){e[e.TRACE=0]="TRACE",e[e.DEBUG=1]="DEBUG",e[e.INFO=2]="INFO",e[e.WARN=3]="WARN",e[e.ERROR=4]="ERROR",e[e.OFF=5]="OFF"}(r||(t.LogLevelEnum=r={})),t.ILogService=(0,s.createDecorator)("LogService"),t.IOptionsService=(0,s.createDecorator)("OptionsService"),t.IOscLinkService=(0,s.createDecorator)("OscLinkService"),t.IUnicodeService=(0,s.createDecorator)("UnicodeService"),t.IDecorationService=(0,s.createDecorator)("DecorationService")},1480:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.UnicodeService=void 0;const s=i(8460),r=i(225);class n{static extractShouldJoin(e){return 0!=(1&e)}static extractWidth(e){return e>>1&3}static extractCharKind(e){return e>>3}static createPropertyValue(e,t,i=!1){return(16777215&e)<<3|(3&t)<<1|(i?1:0)}constructor(){this._providers=Object.create(null),this._active="",this._onChange=new s.EventEmitter,this.onChange=this._onChange.event;const e=new r.UnicodeV6;this.register(e),this._active=e.version,this._activeProvider=e}dispose(){this._onChange.dispose()}get versions(){return Object.keys(this._providers)}get activeVersion(){return this._active}set activeVersion(e){if(!this._providers[e])throw new Error(`unknown Unicode version "${e}"`);this._active=e,this._activeProvider=this._providers[e],this._onChange.fire(e)}register(e){this._providers[e.version]=e}wcwidth(e){return this._activeProvider.wcwidth(e)}getStringCellWidth(e){let t=0,i=0;const s=e.length;for(let r=0;r<s;++r){let o=e.charCodeAt(r);if(55296<=o&&o<=56319){if(++r>=s)return t+this.wcwidth(o);const i=e.charCodeAt(r);56320<=i&&i<=57343?o=1024*(o-55296)+i-56320+65536:t+=this.wcwidth(i)}const a=this.charProperties(o,i);let h=n.extractWidth(a);n.extractShouldJoin(a)&&(h-=n.extractWidth(i)),t+=h,i=a}return t}charProperties(e,t){return this._activeProvider.charProperties(e,t)}}t.UnicodeService=n}},t={};function i(s){var r=t[s];if(void 0!==r)return r.exports;var n=t[s]={exports:{}};return e[s].call(n.exports,n,n.exports,i),n.exports}var s={};return(()=>{var e=s;Object.defineProperty(e,"__esModule",{value:!0}),e.Terminal=void 0;const t=i(9042),r=i(3236),n=i(844),o=i(5741),a=i(8285),h=i(7975),c=i(7090),l=["cols","rows"];class d extends n.Disposable{constructor(e){super(),this._core=this.register(new r.Terminal(e)),this._addonManager=this.register(new o.AddonManager),this._publicOptions={...this._core.options};const t=e=>this._core.options[e],i=(e,t)=>{this._checkReadonlyOptions(e),this._core.options[e]=t};for(const e in this._core.options){const s={get:t.bind(this,e),set:i.bind(this,e)};Object.defineProperty(this._publicOptions,e,s)}}_checkReadonlyOptions(e){if(l.includes(e))throw new Error(`Option "${e}" can only be set in the constructor`)}_checkProposedApi(){if(!this._core.optionsService.rawOptions.allowProposedApi)throw new Error("You must set the allowProposedApi option to true to use proposed API")}get onBell(){return this._core.onBell}get onBinary(){return this._core.onBinary}get onCursorMove(){return this._core.onCursorMove}get onData(){return this._core.onData}get onKey(){return this._core.onKey}get onLineFeed(){return this._core.onLineFeed}get onRender(){return this._core.onRender}get onResize(){return this._core.onResize}get onScroll(){return this._core.onScroll}get onSelectionChange(){return this._core.onSelectionChange}get onTitleChange(){return this._core.onTitleChange}get onWriteParsed(){return this._core.onWriteParsed}get element(){return this._core.element}get parser(){return this._parser||(this._parser=new h.ParserApi(this._core)),this._parser}get unicode(){return this._checkProposedApi(),new c.UnicodeApi(this._core)}get textarea(){return this._core.textarea}get rows(){return this._core.rows}get cols(){return this._core.cols}get buffer(){return this._buffer||(this._buffer=this.register(new a.BufferNamespaceApi(this._core))),this._buffer}get markers(){return this._checkProposedApi(),this._core.markers}get modes(){const e=this._core.coreService.decPrivateModes;let t="none";switch(this._core.coreMouseService.activeProtocol){case"X10":t="x10";break;case"VT200":t="vt200";break;case"DRAG":t="drag";break;case"ANY":t="any"}return{applicationCursorKeysMode:e.applicationCursorKeys,applicationKeypadMode:e.applicationKeypad,bracketedPasteMode:e.bracketedPasteMode,insertMode:this._core.coreService.modes.insertMode,mouseTrackingMode:t,originMode:e.origin,reverseWraparoundMode:e.reverseWraparound,sendFocusMode:e.sendFocus,wraparoundMode:e.wraparound}}get options(){return this._publicOptions}set options(e){for(const t in e)this._publicOptions[t]=e[t]}blur(){this._core.blur()}focus(){this._core.focus()}input(e,t=!0){this._core.input(e,t)}resize(e,t){this._verifyIntegers(e,t),this._core.resize(e,t)}open(e){this._core.open(e)}attachCustomKeyEventHandler(e){this._core.attachCustomKeyEventHandler(e)}attachCustomWheelEventHandler(e){this._core.attachCustomWheelEventHandler(e)}registerLinkProvider(e){return this._core.registerLinkProvider(e)}registerCharacterJoiner(e){return this._checkProposedApi(),this._core.registerCharacterJoiner(e)}deregisterCharacterJoiner(e){this._checkProposedApi(),this._core.deregisterCharacterJoiner(e)}registerMarker(e=0){return this._verifyIntegers(e),this._core.registerMarker(e)}registerDecoration(e){return this._checkProposedApi(),this._verifyPositiveIntegers(e.x??0,e.width??0,e.height??0),this._core.registerDecoration(e)}hasSelection(){return this._core.hasSelection()}select(e,t,i){this._verifyIntegers(e,t,i),this._core.select(e,t,i)}getSelection(){return this._core.getSelection()}getSelectionPosition(){return this._core.getSelectionPosition()}clearSelection(){this._core.clearSelection()}selectAll(){this._core.selectAll()}selectLines(e,t){this._verifyIntegers(e,t),this._core.selectLines(e,t)}dispose(){super.dispose()}scrollLines(e){this._verifyIntegers(e),this._core.scrollLines(e)}scrollPages(e){this._verifyIntegers(e),this._core.scrollPages(e)}scrollToTop(){this._core.scrollToTop()}scrollToBottom(){this._core.scrollToBottom()}scrollToLine(e){this._verifyIntegers(e),this._core.scrollToLine(e)}clear(){this._core.clear()}write(e,t){this._core.write(e,t)}writeln(e,t){this._core.write(e),this._core.write("\\r\\n",t)}paste(e){this._core.paste(e)}refresh(e,t){this._verifyIntegers(e,t),this._core.refresh(e,t)}reset(){this._core.reset()}clearTextureAtlas(){this._core.clearTextureAtlas()}loadAddon(e){this._addonManager.loadAddon(this,e)}static get strings(){return t}_verifyIntegers(...e){for(const t of e)if(t===1/0||isNaN(t)||t%1!=0)throw new Error("This API only accepts integers")}_verifyPositiveIntegers(...e){for(const t of e)if(t&&(t===1/0||isNaN(t)||t%1!=0||t<0))throw new Error("This API only accepts positive integers")}}e.Terminal=d})(),s})()));\n//# sourceMappingURL=xterm.js.map';

// node_modules/@xterm/xterm/css/xterm.css
var xterm_default2 = `/**
 * Copyright (c) 2014 The xterm.js authors. All rights reserved.
 * Copyright (c) 2012-2013, Christopher Jeffrey (MIT License)
 * https://github.com/chjj/term.js
 * @license MIT
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 *
 * Originally forked from (with the author's permission):
 *   Fabrice Bellard's javascript vt100 for jslinux:
 *   http://bellard.org/jslinux/
 *   Copyright (c) 2011 Fabrice Bellard
 *   The original design remains. The terminal itself
 *   has been extended to include xterm CSI codes, among
 *   other features.
 */

/**
 *  Default styles for xterm.js
 */

.xterm {
    cursor: text;
    position: relative;
    user-select: none;
    -ms-user-select: none;
    -webkit-user-select: none;
}

.xterm.focus,
.xterm:focus {
    outline: none;
}

.xterm .xterm-helpers {
    position: absolute;
    top: 0;
    /**
     * The z-index of the helpers must be higher than the canvases in order for
     * IMEs to appear on top.
     */
    z-index: 5;
}

.xterm .xterm-helper-textarea {
    padding: 0;
    border: 0;
    margin: 0;
    /* Move textarea out of the screen to the far left, so that the cursor is not visible */
    position: absolute;
    opacity: 0;
    left: -9999em;
    top: 0;
    width: 0;
    height: 0;
    z-index: -5;
    /** Prevent wrapping so the IME appears against the textarea at the correct position */
    white-space: nowrap;
    overflow: hidden;
    resize: none;
}

.xterm .composition-view {
    /* TODO: Composition position got messed up somewhere */
    background: #000;
    color: #FFF;
    display: none;
    position: absolute;
    white-space: nowrap;
    z-index: 1;
}

.xterm .composition-view.active {
    display: block;
}

.xterm .xterm-viewport {
    /* On OS X this is required in order for the scroll bar to appear fully opaque */
    background-color: #000;
    overflow-y: scroll;
    cursor: default;
    position: absolute;
    right: 0;
    left: 0;
    top: 0;
    bottom: 0;
}

.xterm .xterm-screen {
    position: relative;
}

.xterm .xterm-screen canvas {
    position: absolute;
    left: 0;
    top: 0;
}

.xterm .xterm-scroll-area {
    visibility: hidden;
}

.xterm-char-measure-element {
    display: inline-block;
    visibility: hidden;
    position: absolute;
    top: 0;
    left: -9999em;
    line-height: normal;
}

.xterm.enable-mouse-events {
    /* When mouse events are enabled (eg. tmux), revert to the standard pointer cursor */
    cursor: default;
}

.xterm.xterm-cursor-pointer,
.xterm .xterm-cursor-pointer {
    cursor: pointer;
}

.xterm.column-select.focus {
    /* Column selection mode */
    cursor: crosshair;
}

.xterm .xterm-accessibility:not(.debug),
.xterm .xterm-message {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    right: 0;
    z-index: 10;
    color: transparent;
    pointer-events: none;
}

.xterm .xterm-accessibility-tree:not(.debug) *::selection {
  color: transparent;
}

.xterm .xterm-accessibility-tree {
  user-select: text;
  white-space: pre;
}

.xterm .live-region {
    position: absolute;
    left: -9999px;
    width: 1px;
    height: 1px;
    overflow: hidden;
}

.xterm-dim {
    /* Dim should not apply to background, so the opacity of the foreground color is applied
     * explicitly in the generated class and reset to 1 here */
    opacity: 1 !important;
}

.xterm-underline-1 { text-decoration: underline; }
.xterm-underline-2 { text-decoration: double underline; }
.xterm-underline-3 { text-decoration: wavy underline; }
.xterm-underline-4 { text-decoration: dotted underline; }
.xterm-underline-5 { text-decoration: dashed underline; }

.xterm-overline {
    text-decoration: overline;
}

.xterm-overline.xterm-underline-1 { text-decoration: overline underline; }
.xterm-overline.xterm-underline-2 { text-decoration: overline double underline; }
.xterm-overline.xterm-underline-3 { text-decoration: overline wavy underline; }
.xterm-overline.xterm-underline-4 { text-decoration: overline dotted underline; }
.xterm-overline.xterm-underline-5 { text-decoration: overline dashed underline; }

.xterm-strikethrough {
    text-decoration: line-through;
}

.xterm-screen .xterm-decoration-container .xterm-decoration {
	z-index: 6;
	position: absolute;
}

.xterm-screen .xterm-decoration-container .xterm-decoration.xterm-decoration-top-layer {
	z-index: 7;
}

.xterm-decoration-overview-ruler {
    z-index: 8;
    position: absolute;
    top: 0;
    right: 0;
    pointer-events: none;
}

.xterm-decoration-top {
    z-index: 2;
    position: relative;
}
`;

// node_modules/@xterm/addon-fit/lib/addon-fit.js
var addon_fit_default = '!function(e,t){"object"==typeof exports&&"object"==typeof module?module.exports=t():"function"==typeof define&&define.amd?define([],t):"object"==typeof exports?exports.FitAddon=t():e.FitAddon=t()}(self,(()=>(()=>{"use strict";var e={};return(()=>{var t=e;Object.defineProperty(t,"__esModule",{value:!0}),t.FitAddon=void 0,t.FitAddon=class{activate(e){this._terminal=e}dispose(){}fit(){const e=this.proposeDimensions();if(!e||!this._terminal||isNaN(e.cols)||isNaN(e.rows))return;const t=this._terminal._core;this._terminal.rows===e.rows&&this._terminal.cols===e.cols||(t._renderService.clear(),this._terminal.resize(e.cols,e.rows))}proposeDimensions(){if(!this._terminal)return;if(!this._terminal.element||!this._terminal.element.parentElement)return;const e=this._terminal._core,t=e._renderService.dimensions;if(0===t.css.cell.width||0===t.css.cell.height)return;const r=0===this._terminal.options.scrollback?0:e.viewport.scrollBarWidth,i=window.getComputedStyle(this._terminal.element.parentElement),o=parseInt(i.getPropertyValue("height")),s=Math.max(0,parseInt(i.getPropertyValue("width"))),n=window.getComputedStyle(this._terminal.element),l=o-(parseInt(n.getPropertyValue("padding-top"))+parseInt(n.getPropertyValue("padding-bottom"))),a=s-(parseInt(n.getPropertyValue("padding-right"))+parseInt(n.getPropertyValue("padding-left")))-r;return{cols:Math.max(2,Math.floor(a/t.css.cell.width)),rows:Math.max(1,Math.floor(l/t.css.cell.height))}}}})(),e})()));\n//# sourceMappingURL=addon-fit.js.map';

// src/views/chat.js
var inline = (code) => code.replace(/<\/script/gi, "<\\/script").replace(/\/\/# sourceMappingURL=\S+/g, "");
var termSeq = 0;
function TerminalModal({ ticket, from, card, onClose }) {
  useEffect4(() => {
    window.__cockpitModalOpen = true;
    return () => {
      window.__cockpitModalOpen = false;
    };
  }, []);
  const [id] = useState5(() => "tm" + ++termSeq);
  const frame = useRef(null);
  const [state, setState] = useState5({ phase: "opening" });
  const [confirmReset, setConfirmReset] = useState5(false);
  const off = useRef(0);
  const ready = useRef(false);
  const size = useRef(null);
  const send = (msg) => {
    const w = frame.current && frame.current.contentWindow;
    if (w) w.postMessage(Object.assign({ cockpitTerm: id }, msg), "*");
  };
  const open = async (reset) => {
    setState({ phase: "opening" });
    try {
      const sz = size.current || { cols: 120, rows: 36 };
      const r = await post("/chat-open", { ticket, from: from || void 0, card: card || void 0, reset: Boolean(reset), cols: sz.cols, rows: sz.rows });
      off.current = r.offset || 0;
      setState({ phase: "open", ...r });
      if (ready.current) send({ type: "data", b64: r.replay || "", clear: true });
      if (size.current) {
        try {
          await post("/chat-resize", { ticket, cols: size.current.cols, rows: size.current.rows });
        } catch (err) {
        }
      }
    } catch (e) {
      setState({ phase: "error", error: String(e.message || e) });
    }
  };
  useEffect4(() => {
    open(false);
  }, [ticket]);
  useEffect4(() => {
    const onMsg = async (e) => {
      const d = e.data || {};
      if (d.cockpitTerm !== id) return;
      if (d.type === "ready") {
        ready.current = true;
        if (state.phase === "open") {
          const r = await CTX.rest(`/chat-read?ticket=${encodeURIComponent(ticket)}&offset=0`);
          off.current = r.offset;
          send({ type: "data", b64: r.data || "", clear: true });
        }
      } else if (d.type === "input") {
        try {
          await post("/chat-write", { ticket, data: d.b64 });
        } catch (err) {
          setState((s) => ({ ...s, phase: "error", error: String(err.message || err) }));
        }
      } else if (d.type === "resize") {
        size.current = { cols: d.cols, rows: d.rows };
        try {
          await post("/chat-resize", { ticket, cols: d.cols, rows: d.rows });
        } catch (err) {
        }
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [id, ticket, state.phase]);
  useEffect4(() => {
    if (state.phase !== "open") return;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      try {
        const r = await CTX.rest(`/chat-read?ticket=${encodeURIComponent(ticket)}&offset=${off.current}`);
        if (stop) return;
        if (r.gone) {
          setState((s) => ({ ...s, phase: "ended" }));
          return;
        }
        if (r.data) {
          off.current = r.offset;
          if (ready.current) send({ type: "data", b64: r.data });
        }
        if (!r.alive) {
          setState((s) => ({ ...s, phase: "ended" }));
          return;
        }
      } catch (e) {
      }
      setTimeout(tick, 120);
    };
    tick();
    return () => {
      stop = true;
    };
  }, [state.phase, ticket]);
  useEffect4(() => {
    const k = (e) => {
      if (e.key === "Escape" && e.target === document.body) onClose();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  const page = `<!doctype html><html><head><meta charset="utf-8"><style>${xterm_default2}</style><style>html,body{margin:0;height:100%;background:#0d1117;overflow:hidden}#t{position:absolute;inset:0;padding:6px}</style></head><body><div id="t"></div>
<script>${inline(xterm_default)}<\/script><script>${inline(addon_fit_default)}<\/script>
<script>
const ID = ${JSON.stringify(id)}; const post = (m) => parent.postMessage(Object.assign({ cockpitTerm: ID }, m), '*');
const enc = (s) => { const b = new TextEncoder().encode(s); let x = ''; for (const c of b) x += String.fromCharCode(c); return btoa(x) };
const dec = (b64) => { const bin = atob(b64); const a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return a };
const term = new Terminal({ cursorBlink: true, fontSize: 13, fontFamily: 'Menlo, ui-monospace, monospace', theme: { background: '#0d1117', foreground: '#d0d7de', cursor: '#58a6ff' }, scrollback: 20000, allowProposedApi: true });
const fit = new FitAddon.FitAddon(); term.loadAddon(fit); term.open(document.getElementById('t')); fit.fit(); term.focus();
term.onData((d) => post({ type: 'input', b64: enc(d) }));
const sendSize = () => post({ type: 'resize', cols: term.cols, rows: term.rows });
new ResizeObserver(() => { try { fit.fit(); sendSize() } catch (e) {} }).observe(document.getElementById('t'));
window.addEventListener('message', (e) => { const d = e.data || {}; if (d.cockpitTerm !== ID) return; if (d.type === 'data') { if (d.clear) term.reset(); term.write(dec(d.b64)) } if (d.type === 'focus') term.focus() });
post({ type: 'ready' }); sendSize();
<\/script></body></html>`;
  const src = useMemo3(() => "data:text/html;charset=utf-8," + encodeURIComponent(page), [id]);
  const st = state;
  return h(
    "div",
    { role: "presentation", onClick: onClose, style: { position: "fixed", inset: 0, zIndex: 1e3, background: "rgba(0,0,0,.72)", display: "flex", alignItems: "center", justifyContent: "center", padding: "2vh 2vw" } },
    h(
      "div",
      { role: "presentation", onClick: (e) => {
        e.stopPropagation();
        send({ type: "focus" });
      }, className: "rounded-lg border flex flex-col", style: { borderColor: stroke, background: "#0d1117", width: "96vw", height: "96vh", overflow: "hidden" } },
      h(
        "div",
        { className: "flex items-center gap-2 px-3 py-1.5 text-xs", style: { borderBottom: `1px solid ${stroke}`, background: "var(--ui-bg-elevated, #1e1e1e)" } },
        h("span", { className: "font-medium" }, ticket === "own" ? "coding tool \xB7 yours" : `${ticket} \xB7 coding tool`),
        st.session ? h("span", { style: mono, title: "your session for this ticket; it persists until the flow ends" }, st.session.slice(0, 8)) : null,
        st.forked_from ? h("span", { style: sub }, `forked from the run ${st.forked_from.slice(0, 8)}`) : st.cwd ? h("span", { style: { ...mono, ...sub }, title: st.cwd }, st.cwd) : null,
        st.phase === "open" ? h(
          "span",
          { style: { color: st.alive ? "var(--ui-success, #2a9d5c)" : "var(--ui-warning, #c98a00)" } },
          st.attached ? "\u25CF re-attached" : "\u25CF started"
        ) : st.phase === "ended" ? h(
          "span",
          { style: { color: "var(--ui-warning, #c98a00)" } },
          "the process ended \xB7 open again to resume"
        ) : st.phase === "error" ? h("span", { style: { color: "var(--ui-danger, #d33)" } }, st.error) : h(
          "span",
          { style: sub },
          "opening"
        ),
        h(
          "span",
          { className: "ml-auto flex items-center gap-1" },
          st.phase === "ended" ? btn("Resume", () => open(false), { accent: true }) : null,
          confirmReset ? h(
            "span",
            { className: "flex items-center gap-1" },
            h("span", { style: { color: "var(--ui-warning, #c98a00)" } }, "start a new chat from the latest run? this one stays on disk"),
            btn("Yes", () => {
              setConfirmReset(false);
              open(true);
            }, { danger: true }),
            btn("No", () => setConfirmReset(false))
          ) : btn(
            "Start over from latest run",
            () => setConfirmReset(true),
            { title: "fork a fresh chat from the latest run of this ticket; the current conversation stays on disk" }
          ),
          btn("End process", async () => {
            try {
              await post("/chat-end", { ticket });
              setState((s) => ({ ...s, phase: "ended" }));
            } catch (e) {
            }
          }, { title: "stop the terminal process; the conversation stays and resumes next time" }),
          btn("\u2715 close", onClose, { title: "hide the terminal; the chat keeps running" })
        )
      ),
      h("div", { style: { flex: 1, minHeight: 0 } }, h(SandboxedFrame, { ref: frame, src, title: "chat " + ticket, style: { width: "100%", height: "100%", border: 0, display: "block" } }))
    )
  );
}
function ChatButton({ ticket, from, card, label }) {
  const [open, setOpen] = useState5(false);
  const q2 = useQuery({ queryKey: ["cockpit", "chat-state", ticket, card || ""], queryFn: () => CTX.rest("/chat-state?ticket=" + encodeURIComponent(ticket) + (card ? "&card=" + encodeURIComponent(card) : "")), refetchInterval: 15e3, retry: 0, enabled: Boolean(ticket) });
  if (!ticket) return null;
  const st = q2.data || {};
  const best = st.best || {};
  const text = label || (st.exists ? st.running ? "\u25CF Chat" : "Chat" : "Chat");
  const title = ticket === "own" ? "your own coding tool in the workspace, like one started in a shell: outside every flow, one conversation that persists and resumes here" : st.exists ? `your session ${(st.session || "").slice(0, 8)} (${st.forked_source ? "forked from " + st.forked_source : "fresh"}), since ${st.created ? ago(st.created) + " ago" : ""}` : best.session ? `opens an interactive coding tool forked from ${best.source} (${best.session.slice(0, 8)}, its full context); the chat persists until the flow ends` : `opens a fresh interactive coding tool in ${best.cwd || "the ticket folder"}; the chat persists until the flow ends`;
  return h(
    "span",
    null,
    btn(text, () => setOpen(true), { accent: !st.exists, title }),
    open ? h(TerminalModal, { ticket, from, card, onClose: () => setOpen(false) }) : null
  );
}

// src/lib/secret.js
import { useState as useState6, useEffect as useEffect5, useRef as useRef2 } from "react";
var copy = async (text, what) => {
  try {
    await CTX.os.writeClipboard(text);
    host.notify({ kind: "info", message: `${what} copied` });
  } catch (e) {
    host.notifyError(e, "copy failed");
  }
};
var copyBtn = (text, what) => h("button", { type: "button", onClick: (e) => {
  e.stopPropagation();
  copy(text, what);
}, title: `copy ${what}`, className: "rounded px-1.5 py-0.5 text-[0.6875rem]", style: { border: `1px solid ${stroke}`, color: "var(--ui-accent)" } }, "\u29C9 copy");
function CredRows({ username, password }) {
  const [show, setShow] = useState6(false);
  return h(
    "div",
    { className: "grid items-center gap-x-3 gap-y-1", style: { gridTemplateColumns: "6rem 1fr auto" } },
    h("span", { style: sub }, "username"),
    h("span", { style: mono }, username),
    copyBtn(username, "username"),
    h("span", { style: sub }, "password"),
    h("span", { style: mono }, show ? password : "\u2022".repeat(12), " ", h("button", { type: "button", onClick: () => setShow(!show), className: "text-[0.6875rem]", style: { color: "var(--ui-text-tertiary)" } }, show ? "hide" : "show")),
    copyBtn(password, "password")
  );
}
var POOL = { letters: "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ", digits: "23456789", symbols: "!@#$%^&*-_=+?" };
var genPassword = (length = 20, symbols = true) => {
  const pools = [POOL.letters, POOL.digits, ...symbols ? [POOL.symbols] : []];
  const all = pools.join("");
  const pick = (set) => {
    const b = new Uint32Array(1);
    const max = Math.floor(4294967296 / set.length) * set.length;
    do {
      crypto.getRandomValues(b);
    } while (b[0] >= max);
    return set[b[0] % set.length];
  };
  const out = pools.map(pick);
  while (out.length < length) out.push(pick(all));
  for (let i = out.length - 1; i > 0; i--) {
    const r = new Uint32Array(1);
    crypto.getRandomValues(r);
    const k = r[0] % (i + 1);
    [out[i], out[k]] = [out[k], out[i]];
  }
  return out.join("");
};
function SecretField({ label, reveal, disabled, why, multiline, card }) {
  const [value, setValue] = useState6(null);
  const [busy, setBusy] = useState6(false);
  const timer = useRef2(null);
  const hide = () => {
    clearTimeout(timer.current);
    setValue(null);
  };
  useEffect5(() => hide, []);
  const open = async (keep) => {
    if (busy) return null;
    setBusy(true);
    try {
      const r = await reveal();
      if (keep) {
        setValue(r.value);
        clearTimeout(timer.current);
        timer.current = setTimeout(hide, (r.expires_in || 30) * 1e3);
      }
      return r.value;
    } catch (e) {
      host.notifyError(e, `${label} could not be shown`);
      return null;
    } finally {
      setBusy(false);
    }
  };
  const copyIt = async () => {
    const v = value !== null ? value : await open(false);
    if (v !== null && v !== void 0) await copy(v, label);
  };
  const off = Boolean(disabled);
  const small = { color: "var(--ui-text-tertiary)" };
  return h(
    "div",
    { className: "flex items-start gap-2" },
    value !== null ? h("span", { style: { ...mono, whiteSpace: multiline ? "pre-wrap" : "normal", wordBreak: "break-all" } }, value) : busy && card ? h("span", { style: { color: "var(--ui-warning, #c98a00)" } }, "touch your security key if it blinks\u2026") : h("span", { style: mono }, "\u2022".repeat(12)),
    h("button", { type: "button", disabled: off || busy, title: off ? why : "", onClick: () => value !== null ? hide() : open(true), className: "text-[0.6875rem] disabled:opacity-40", style: small }, value !== null ? "hide" : "show"),
    h("button", { type: "button", disabled: off || busy, title: off ? why : `copy ${label}`, onClick: copyIt, className: "rounded px-1.5 py-0.5 text-[0.6875rem] disabled:opacity-40", style: { border: `1px solid ${stroke}`, color: "var(--ui-accent)" } }, "\u29C9 copy")
  );
}

// src/views/demo.js
function StagingDemo({ d }) {
  const open = (url) => openWeb(url);
  const steps = d.steps || [];
  const apps = d.apps || [];
  return h(
    Section,
    { title: "Demo \xB7 staging", open: steps.length > 0, extra: (d.links || []).slice(0, 2).map((l) => h("button", { key: l.url, type: "button", onClick: () => open(l.url), title: l.url, className: "rounded px-1.5 py-0.5 text-[0.6875rem]", style: { border: `1px solid ${stroke}`, color: "var(--ui-accent)" } }, "open " + (l.label || "link"))) },
    h(
      "div",
      { className: "cockpit-staging flex flex-col gap-3 text-xs" },
      apps.length ? h("div", { className: "flex flex-wrap gap-3" }, ...apps.map((a) => h("span", { key: a.name, className: "flex items-center gap-1" }, h("span", { style: { color: a.up ? "var(--ui-success, #2a9d5c)" : "var(--ui-text-quaternary)" } }, a.up ? "\u25CF" : "\u25CB"), a.name))) : null,
      (d.links || []).length ? h(
        "div",
        { className: "grid items-center gap-x-3 gap-y-1", style: { gridTemplateColumns: "12rem 1fr auto" } },
        ...d.links.flatMap((l) => [h("span", { key: l.url + "l" }, l.label), h("a", { key: l.url + "u", href: l.url, onClick: (e) => {
          e.preventDefault();
          open(l.url);
        }, className: "truncate", style: { ...mono, color: "var(--ui-accent)" } }, l.url), h("span", { key: l.url + "c", className: "flex justify-end" }, copyBtn(l.url, "link"))])
      ) : h("div", { style: sub }, "no link recorded yet"),
      steps.length ? h(
        "div",
        { className: "flex flex-col gap-1 rounded border px-2.5 py-2", style: { borderColor: "var(--ui-warning, #c98a00)" } },
        h("div", { className: "cockpit-head", style: { color: "var(--ui-warning, #c98a00)" } }, "your steps"),
        h("ol", { className: "list-decimal pl-5 flex flex-col gap-0.5" }, ...steps.map((s, i) => h("li", { key: i }, s)))
      ) : null,
      h(
        "div",
        { className: "flex flex-col gap-1 rounded border px-2.5 py-2", style: { borderColor: stroke } },
        h("div", { className: "cockpit-head" }, "login on staging (the test account)"),
        d.login ? h(CredRows, { username: d.login.username, password: d.login.password }) : h("div", { style: { color: "var(--ui-warning, #c98a00)" } }, d.login_error || "no login"),
        h("div", { style: sub }, "One browser session is shared across these origins. A staging test account only.")
      ),
      d.notes ? h("div", { style: sub }, d.notes) : null
    )
  );
}
function SessionCard({ ticket }) {
  const q2 = useQuery({ queryKey: ["cockpit", "session-card", ticket], queryFn: () => CTX.rest("/session-card?ticket=" + encodeURIComponent(ticket)), refetchInterval: 2e4, retry: 0, enabled: Boolean(ticket) });
  const [pick, setPick] = useState7("");
  const [cred, setCred] = useState7(null);
  const [busy, setBusy] = useState7(false);
  const d = q2.data;
  if (!ticket || !d || !d.open) return null;
  const label = pick || d.default;
  const chosen = (d.logins || []).find((l) => l.label === label);
  const held = d.current && chosen && d.current.username === chosen.user ? { username: d.current.username, password: d.current.password } : null;
  const shown = cred && cred.label === label ? cred : held;
  const get = async () => {
    if (!chosen) return;
    setBusy(true);
    try {
      const r = await post("/session-login", { ticket, slot: d.slot, user: chosen.user });
      setCred({ label, username: r.user, password: r.password });
    } catch (e) {
      host.notifyError(e, "login failed");
    } finally {
      setBusy(false);
    }
  };
  const open = (url) => openWeb(url);
  return h(
    Section,
    { title: `Manual session \xB7 slot ${d.slot}`, open: true },
    h(
      "div",
      { className: "flex flex-col gap-3 text-xs", "data-session-card": d.slot },
      h(
        "div",
        { className: "grid items-center gap-x-3 gap-y-1", style: { gridTemplateColumns: "9rem 1fr auto" } },
        ...(d.apps || []).flatMap((a) => [
          h("span", { key: a.name + "n" }, a.name),
          h("a", { key: a.name + "u", href: a.url, onClick: (e) => {
            e.preventDefault();
            open(a.url);
          }, className: "truncate", style: { ...mono, color: "var(--ui-accent)" } }, a.url),
          h("span", { key: a.name + "b", className: "flex justify-end" }, copyBtn(a.url, a.name + " URL"))
        ])
      ),
      (d.logins || []).length ? h(
        "div",
        { className: "flex flex-col gap-1 rounded border px-2.5 py-2", style: { borderColor: stroke } },
        h(
          "div",
          { className: "flex items-center gap-2" },
          h("span", { className: "cockpit-head" }, "login on the slot"),
          selectBox(label, setPick, d.logins.map((l) => [l.label, `${l.label} \xB7 ${l.user}`])),
          h("span", { className: "ml-auto" }, btn(busy ? "working\u2026" : "Get password", get, { title: "set a password for this user on the slot database only" }))
        ),
        shown ? h(CredRows, { username: shown.username, password: shown.password }) : h("div", { style: sub }, "no password yet for this user: Get password")
      ) : null
    )
  );
}
function DemoSection({ ticket }) {
  const qc = useQueryClient();
  const q2 = useQuery({ queryKey: ["cockpit", "demo", ticket], queryFn: () => CTX.rest("/demo?ticket=" + encodeURIComponent(ticket)), refetchInterval: 2e4, retry: 0, enabled: Boolean(ticket) });
  const [busy, setBusy] = useState7("");
  const d = q2.data;
  if (ticket && d && d.env === "staging") return h(StagingDemo, { d });
  if (!ticket || !d || !d.slot) return null;
  const refresh = () => qc.invalidateQueries({ queryKey: ["cockpit", "demo", ticket] });
  const open = (url) => openWeb(url);
  const upApps = (d.apps || []).filter((a) => a.up && a.name !== "API");
  const act = async (key, path, body, msg) => {
    setBusy(key);
    try {
      const r = await post(path, body);
      host.notify({ kind: "success", message: msg || r && r.out || "done" });
      refresh();
    } catch (e) {
      host.notifyError(e, "failed");
    } finally {
      setBusy("");
    }
  };
  const login = d.login;
  return h(
    Section,
    { title: `Demo \xB7 slot ${d.slot}`, extra: upApps.map((a) => h("button", { key: a.name, type: "button", onClick: () => open(a.url), title: a.url, className: "rounded px-1.5 py-0.5 text-[0.6875rem]", style: { border: `1px solid ${stroke}`, color: "var(--ui-accent)" } }, a.name + " \u2197")) },
    h(
      "div",
      { className: "flex flex-col gap-3 text-xs" },
      h(
        "div",
        { className: "grid items-center gap-x-3 gap-y-1", style: { gridTemplateColumns: "9rem 1fr auto" } },
        ...(d.apps || []).flatMap((a) => [
          h("span", { key: a.name + "n", className: "flex items-center gap-1.5" }, h("span", { style: { color: a.up ? "var(--ui-success, #2a9d5c)" : "var(--ui-text-quaternary)" } }, a.up ? "\u25CF" : "\u25CB"), a.name),
          a.up ? h("a", { key: a.name + "u", href: a.url, onClick: (e) => {
            e.preventDefault();
            open(a.url);
          }, className: "truncate", style: { ...mono, color: "var(--ui-accent)" } }, a.url) : h("span", { key: a.name + "u", className: "truncate", style: { ...mono, color: "var(--ui-text-tertiary)" } }, a.url),
          h("span", { key: a.name + "b", className: "flex justify-end gap-1" }, a.up ? copyBtn(a.url, a.name + " URL") : a.name === "API" ? h("span", { style: sub }, "slot stack down") : a.worktree ? btn(busy === a.repo ? "starting\u2026" : "Start", () => act(a.repo, "/demo-start", { ticket, repo: a.repo, slot: d.slot }, `${a.name} starting on slot ${d.slot} (about a minute)`), { title: `cockpit slot start ${d.slot} ${a.repo}` }) : h("span", { style: sub }, "no worktree"))
        ])
      ),
      h(
        "div",
        { className: "flex flex-col gap-1 rounded border px-2.5 py-2", style: { borderColor: stroke } },
        h("div", { className: "cockpit-head" }, "login on the slot (its own data copy)"),
        login ? h(CredRows, { username: login.username, password: login.password }) : h("div", { style: { color: "var(--ui-warning, #c98a00)" } }, d.login_error || "no login yet"),
        login && login.twofa ? h("div", { style: { color: "var(--ui-warning, #c98a00)" } }, "This user has 2FA enabled: the login asks for a code.") : null,
        h(
          "div",
          { className: "flex items-center gap-2", style: sub },
          login && login.set_at ? h("span", null, `set ${ago(login.set_at)} ago on slot ${d.slot}; a slot reset restores the original`) : null,
          h("span", { className: "ml-auto" }, btn(busy === "login" ? "working\u2026" : "New password", () => act("login", "/demo-login", { ticket, user: login && login.username || d.account || "", slot: d.slot }, "new demo password set on the slot"), { title: "set a fresh password for this user on the slot database only" }))
        )
      ),
      (d.links || []).length ? h(
        "div",
        { className: "flex flex-col gap-1" },
        h("div", { className: "cockpit-head" }, "where to look (recorded by the lanes)"),
        ...d.links.map((l, i) => h("div", { key: i, className: "flex items-center gap-2" }, h("a", { href: l.url, onClick: (e) => {
          e.preventDefault();
          open(l.url);
        }, style: { color: "var(--ui-accent)" } }, l.label + " \u2197"), h("span", { className: "truncate", style: { ...mono, ...sub } }, l.url)))
      ) : null,
      d.notes ? h("div", { style: sub }, d.notes) : null
    )
  );
}
var ticketOf = (title) => ((title || "").match(/^\s*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)/) || [])[1] || "";
var intentCard = (r) => r && r.card_id && /^t_[0-9a-f]+$/.test(r.card_id) ? r.card_id : void 0;
function TicketTools({ ticket, card, part }) {
  if (!ticket) return null;
  if (part === "chat") return h(
    "div",
    { className: "flex flex-wrap items-center gap-2" },
    h(ChatButton, { ticket, card }),
    btn("Open IDE", () => openIde({ ticket }), { title: "the IDE on the ticket's worktrees: every repo of this ticket, bound to its slot" }),
    h("span", { className: "text-xs", style: sub }, `${ticket}${card ? " \xB7 " + card : ""}`)
  );
  return h("div", { className: "flex flex-col gap-3" }, h(SessionCard, { ticket }), h(DemoSection, { ticket }));
}

// src/views/decide.js
import { useState as useState8 } from "react";
var WARN = "var(--ui-warning, #c98a00)";
var decisionText = (hold, choice, note) => {
  const answer = [choice, (note || "").trim()].filter(Boolean).join(" \u2014 ");
  return [`Decision on "${(hold.ask || "").trim()}": ${answer}`, hold.rework ? `Also, from the gatekeeper's hold:
${hold.rework.trim()}` : ""].filter(Boolean).join("\n\n");
};
var afterNote = (r) => ["push-branch", "pr-patch-apply", "open-pr"].includes(r.type) ? "a tester and a reviewer check the result, then the gatekeeper again" : "the gatekeeper checks the result again";
function DecidePanel({ r, onDone }) {
  const hold = r.hold || {};
  const options = hold.options || [];
  const hh = r.hold_html || {};
  const [choice, setChoice] = useState8("");
  const [note, setNote] = useState8("");
  const [busy, setBusy] = useState8(false);
  const ready = Boolean(choice || note.trim());
  const send = async () => {
    if (!ready || busy) return;
    haptic("tap");
    setBusy(true);
    try {
      const res = await post("/return", { id: r.id, instruction: decisionText(hold, choice, note) });
      host.notify({ kind: "success", title: `${r.id}: decision sent to ${r.created_by || "the lane"}`, message: res.out });
      if (onDone) onDone();
    } catch (e) {
      host.notifyError(e, "sending the decision failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "cockpit-decide rounded border px-2.5 py-2 text-xs flex flex-col gap-2", style: { borderColor: WARN, background: "rgba(201,138,0,.07)" } },
    // talk it through first: Chat, attached to the session of the lane that wrote this intent
    h(TicketTools, { ticket: r.ticket, card: intentCard(r), part: "chat" }),
    h("div", { className: "cockpit-head", style: { color: WARN } }, "Your decision"),
    // the gatekeeper writes its ask and reason in markdown; the backend renders them (hold_html), older rows show the text
    hh.ask ? h(RichMd, { className: "font-medium", html: hh.ask }) : h("div", { className: "font-medium whitespace-pre-wrap" }, hold.ask),
    hold.reason ? h("div", { style: sub, className: "flex gap-1" }, h("span", null, "The gatekeeper:"), hh.reason ? h(RichMd, { html: hh.reason }) : h("span", null, hold.reason)) : null,
    options.length ? h("div", { className: "flex flex-col gap-1", role: "radiogroup" }, ...options.map((o, i) => h(
      "label",
      { key: i, className: "cockpit-decide-opt flex cursor-pointer items-start gap-1.5 rounded border px-2 py-1", style: { borderColor: choice === o ? "var(--ui-accent)" : stroke } },
      h("input", { type: "radio", name: "cockpit-decide-" + r.id, checked: choice === o, onChange: () => setChoice(o), className: "mt-0.5" }),
      h("span", null, o)
    ))) : null,
    h(ClearableTextarea, {
      value: note,
      onChange: (e) => setNote(e.target.value),
      rows: 2,
      placeholder: options.length ? "optional: a note for the lane" : "your answer, in a line",
      className: "min-w-0 rounded border bg-transparent px-1.5 py-0.5",
      style: { borderColor: stroke },
      onKeyDown: (e) => {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
      }
    }),
    hold.rework ? h(Section, { title: "What the lane also does after your answer" }, hh.rework ? h(RichMd, { html: hh.rework }) : h("div", { className: "whitespace-pre-wrap" }, hold.rework)) : null,
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2" },
      h("button", { type: "button", disabled: !ready || busy, onClick: send, className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-accent)", color: "#fff" } }, busy ? "working" : "Send decision (\u2318\u21B5)"),
      h("span", { style: sub }, `It goes back to ${r.created_by || "the lane"} with the rework; ${afterNote(r)}. Nothing leaves the machine.`)
    )
  );
}

// src/views/outbox.js
var waitsText = (w) => w.id === "CI" ? `CI ${w.status}` : `${String(w.id).split("/").pop()} (${w.status})`;
function statusMark(r) {
  if (r.status === "endorsed" && r.waits) return { text: `\u22EF next after ${waitsText(r.waits)}`, color: "var(--ui-text-tertiary)" };
  if (r.status === "endorsed") return { text: "\u2713 endorsed", color: "var(--ui-success, #2a9d5c)" };
  if (r.status === "held") return { text: "\u23F8 held", color: "var(--ui-warning, #c98a00)" };
  if (r.type === "ticket-done" && r.status === "pending") return { text: "\u{1F3C1} awaiting your ack", color: "var(--ui-accent)" };
  if (r.status === "pending") return { text: `\xB7 waiting for ${gateOf(r)}`, color: "var(--ui-text-tertiary)" };
  if (r.status === "returned") return { text: "\u21A9 back in the pipeline", color: "var(--ui-accent)" };
  if (r.status === "posted") return { text: "\u25D4 posted \xB7 check on the forge", color: "var(--ui-warning, #c98a00)" };
  if (r.status === "acknowledged") return { text: "\u{1F3C1} done, acknowledged", color: "var(--ui-text-quaternary)" };
  if (r.status === "reopened") return { text: "\u21BB reopened", color: "var(--ui-text-quaternary)" };
  if (r.status.startsWith("published")) return { text: "\u2197 published", color: "var(--ui-text-quaternary)" };
  return { text: r.status, color: "var(--ui-text-quaternary)" };
}
var rebaseBadge = (r) => r.type === "push-branch" && r.payload && r.payload.rebase_only ? h(
  "span",
  {
    className: "ml-1 rounded px-1 text-[0.6875rem] font-medium align-middle whitespace-nowrap",
    style: { background: "rgba(56,139,253,.18)", color: "var(--ui-accent)", border: "1px solid var(--ui-accent)" },
    title: "rebase only: same patches, new base \u2014 CI watch ignores it; publish it before the content push"
  },
  "\u27F3 rebase"
) : r.type === "push-branch" && r.payload && r.payload.after ? h(
  "span",
  {
    className: "ml-1 rounded px-1 text-[0.6875rem] align-middle whitespace-nowrap",
    style: { background: "rgba(56,139,253,.12)", color: "var(--ui-accent)" },
    title: "two steps in one publish: " + r.payload.after + " (rebase only) then this change" + (r.chain ? " \xB7 step 1 is " + r.chain.step1_status : "")
  },
  "\u27F3 rebase + change" + (r.chain && r.chain.step1_status !== "endorsed" && !String(r.chain.step1_status).startsWith("published") ? " \xB7 step 1 " + r.chain.step1_status : "")
) : null;
var riskColor = (risk) => ({ low: "var(--ui-success, #2a9d5c)", medium: "var(--ui-warning, #c98a00)", high: "var(--ui-danger, #d33)" })[risk] || "var(--ui-text-tertiary)";
var publishLine = (r) => `cockpit publish --id ${r.id}`;
var uploadFiles = async (ticket, fileList, setFiles) => {
  for (const f of Array.from(fileList || [])) {
    try {
      const b64 = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result).split(",")[1] || "");
        r.onerror = rej;
        r.readAsDataURL(f);
      });
      const out = await post("/upload", { ticket, name: f.name || "pasted-" + Date.now() + ".png", b64 });
      setFiles((xs) => [...xs, { name: f.name || out.path.split("/").pop(), path: out.path, size: out.size }]);
    } catch (e) {
      host.notifyError(e, "upload failed: " + (f.name || "file"));
    }
  }
};
function Attach({ ticket, files, setFiles }) {
  return h(
    "div",
    { className: "flex flex-wrap items-center gap-1 text-xs" },
    h(
      "label",
      { className: "rounded border px-2 py-0.5 cursor-pointer", style: { borderColor: stroke, color: "var(--ui-text-secondary)" } },
      "\u{1F4CE} Attach files",
      h("input", { type: "file", multiple: true, style: { display: "none" }, onChange: (e) => {
        uploadFiles(ticket, e.target.files, setFiles);
        e.target.value = "";
      } })
    ),
    h("span", { style: sub }, files.length ? "" : "screenshots, recordings, logs \u2014 or paste an image into the text box"),
    ...files.map((f) => h("span", { key: f.path, className: "rounded border px-1", style: { borderColor: stroke }, title: f.path }, f.name, " ", h("button", { type: "button", onClick: () => setFiles(files.filter((x) => x.path !== f.path)), style: sub, "aria-label": `remove ${f.name}` }, "\u2715")))
  );
}
var onPasteImages = (ticket, setFiles) => (e) => {
  const items = Array.from(e.clipboardData?.items || []).filter((i) => i.kind === "file");
  if (items.length) {
    e.preventDefault();
    uploadFiles(ticket, items.map((i) => i.getAsFile()), setFiles);
  }
};
function ReworkForm({ ticket, repos, delivered, onDone }) {
  const can = delivered || repos;
  const [prompt, setPrompt] = useState9("");
  const [chosen, setChosen] = useState9(can);
  const [busy, setBusy] = useState9(false);
  const qc = useQueryClient();
  const go = async () => {
    if (!prompt.trim() || !chosen.length || busy) return;
    setBusy(true);
    try {
      const r = await post("/kickoff", { ticket, mode: "rework", prompt, repos: chosen });
      host.notify({ kind: "success", title: `${ticket} rework queued`, message: r.out });
      qc.invalidateQueries({ queryKey: ["cockpit"] });
      onDone && onDone();
    } catch (e) {
      host.notifyError(e, "rework failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex flex-col gap-2 rounded border p-2 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)" } },
    h("div", { className: "font-medium" }, `Rework ${ticket}: what is missing`),
    h("div", { style: sub }, "Goes straight to the worker on the branch, with a tester and a reviewer behind it; the push comes back as an Outbox row and updates the PR. For a change of plan use Reopen instead."),
    repos.length > 1 ? h(
      "div",
      { className: "flex flex-wrap gap-2" },
      ...repos.map((r) => h(
        "label",
        {
          key: r,
          className: "flex items-center gap-1",
          style: can.includes(r) ? {} : sub,
          title: can.includes(r) ? "" : "nothing delivered here: no PR, no commits of its own"
        },
        h("input", {
          type: "checkbox",
          disabled: !can.includes(r),
          checked: chosen.includes(r),
          onChange: (e) => setChosen(e.target.checked ? [...chosen, r] : chosen.filter((x) => x !== r))
        }),
        can.includes(r) ? r : `${r} (nothing delivered)`
      ))
    ) : null,
    h(ClearableTextarea, { value: prompt, onChange: (e) => setPrompt(e.target.value), rows: 4, autoFocus: true, placeholder: "e.g. CS: slides.js:1045 uses if/else \u2014 the code-style rule asks for early returns and guard clauses", className: "rounded border bg-transparent px-1.5 py-1", style: { borderColor: stroke } }),
    h("div", { className: "flex gap-1.5" }, h("button", { type: "button", disabled: busy || !prompt.trim() || !chosen.length, onClick: go, className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-warning, #c98a00)", color: "#fff" } }, busy ? "working" : `Rework ${chosen.join(", ") || "\u2026"}`), btn("Cancel", () => onDone && onDone()))
  );
}
function ReopenForm({ ticket, onDone, title, initial }) {
  const [prompt, setPrompt] = useState9(initial && initial.prompt || "");
  const [files, setFiles] = useState9(initial && initial.files || []);
  const [busy, setBusy] = useState9(false);
  const qc = useQueryClient();
  const go = async () => {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    try {
      const r = await post("/reopen-flow", { ticket, prompt, evidence: files.map((f) => f.path), title, ...initial && initial.from_answer ? { from_answer: initial.from_answer } : {} });
      host.notify({ kind: "success", title: `${ticket} reopened`, message: r.out });
      qc.invalidateQueries({ queryKey: ["cockpit"] });
      onDone && onDone();
    } catch (e) {
      host.notifyError(e, "reopen failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex flex-col gap-2 rounded border p-2 text-xs", style: { borderColor: "var(--ui-accent)" } },
    h("div", { className: "font-medium" }, `Reopen ${ticket} with new details`),
    h("div", { style: sub }, "What is wrong or what should happen now. Intake reads the existing evidence and receipts, reproduces, proposes a plan on a card and waits for your go. Nothing starts before that."),
    h(ClearableTextarea, {
      value: prompt,
      onChange: (e) => setPrompt(e.target.value),
      rows: 5,
      autoFocus: true,
      placeholder: "e.g. After the release the divider is still white on page 2 when the page background is an image. Steps: <how to see it>. Expected: <what should happen>",
      onPaste: onPasteImages(ticket, setFiles),
      className: "rounded border bg-transparent px-1.5 py-1",
      style: { borderColor: stroke }
    }),
    h(Attach, { ticket, files, setFiles }),
    h("div", { className: "flex gap-1.5" }, h("button", { type: "button", disabled: busy || !prompt.trim(), onClick: go, className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-accent)", color: "#fff" } }, busy ? "working" : "Reopen \u2192 intake proposes, I confirm"), btn("Cancel", () => onDone && onDone()))
  );
}
var ciMark = (ci) => !ci ? null : ci.state === "none" ? { t: "no CI", c: "var(--ui-text-tertiary)" } : ci.state === "green" ? {
  t: "\u2713 green",
  c: "var(--ui-success, #2a9d5c)"
} : ci.state === "failed" ? {
  t: ci.handled ? "\u2717 failed \xB7 analysed" : ci.analysing ? "\u2717 failed \xB7 analysing" : "\u2717 failed",
  c: ci.handled ? "var(--ui-text-tertiary)" : ci.analysing ? "var(--ui-warning, #c98a00)" : "var(--ui-danger, #d33)"
} : {
  t: "\u25CF running",
  c: "var(--ui-warning, #c98a00)"
};
function PrBox({ pr, ticket, repo, refresh }) {
  const [busy, setBusy] = useState9(false);
  const treat = async () => {
    setBusy(true);
    try {
      const res = await post("/pr-treat", { ticket, repo, number: pr.number });
      host.notify({ kind: "success", title: `${ticket} ${repo}#${pr.number}`, message: `comments sent to a worker (card ${res.card_id})` });
      refresh();
    } catch (e) {
      host.notifyError(e, "treat failed");
    } finally {
      setBusy(false);
    }
  };
  const color = pr.new_count ? "var(--ui-warning, #c98a00)" : stroke;
  return h(
    "div",
    { className: "rounded border p-2 text-xs flex flex-col gap-1", style: { borderColor: color } },
    h(
      "div",
      { className: "flex items-center gap-2" },
      h("div", { className: "font-medium" }, pr.role === "reviewer" ? `PR #${pr.number} by ${pr.author} \xB7 you reviewed it \xB7 ${pr.my_threads ? `${pr.my_threads.resolved}/${pr.my_threads.total} of your threads resolved, ${pr.my_threads.replied} replied` : ""} \xB7 ${pr.merged ? "merged: your review is closed" : pr.state} \xB7 checked ${ago(pr.last_check)} ago` : `PR #${pr.number} \xB7 ${pr.merged ? "merged" : pr.state} \xB7 ${pr.total} comment(s) on the PR \xB7 checked ${ago(pr.last_check)} ago`),
      h("a", { href: pr.url, onClick: (e) => {
        e.preventDefault();
        openWeb(pr.url);
      }, style: { color: "var(--ui-accent)" } }, "open on the forge"),
      copyBtn(pr.url, "PR link"),
      pr.new_count && pr.role !== "reviewer" ? h(
        "div",
        { className: "ml-auto flex gap-1" },
        btn(busy ? "working" : `Treat ${pr.new_count} new comment(s) in the pipeline`, treat, { accent: true, title: "a card for the ticket's lane: same worktree/branch, everything done so far is kept; the lane fixes or replies and amends the intents" }),
        btn("Mark as seen", async () => {
          setBusy(true);
          try {
            const res = await post("/pr-seen", { ticket, repo, number: pr.number });
            host.notify({ kind: "info", message: res.out });
            refresh();
          } catch (e) {
            host.notifyError(e, "failed");
          } finally {
            setBusy(false);
          }
        }, { title: "you handled them yourself on the forge: advance the baseline, no card" }),
        btn("Forget", async () => {
          setBusy(true);
          try {
            await post(
              "/pr-forget",
              { ticket, repo, number: pr.number }
            );
            host.notify({ kind: "info", message: "watch file removed" });
            refresh();
          } catch (e) {
            host.notifyError(
              e,
              "failed"
            );
          } finally {
            setBusy(false);
          }
        }, { title: "delete this pull request's watch file" })
      ) : pr.role === "reviewer" && !pr.merged ? h(
        "div",
        { className: "ml-auto" },
        btn("Re-review what changed", async () => {
          setBusy(true);
          try {
            const res = await post(
              "/pr-rereview",
              { ticket, repo, number: pr.number }
            );
            host.notify({ kind: "success", message: res.out });
            refresh();
          } catch (e) {
            host.notifyError(
              e,
              "failed"
            );
          } finally {
            setBusy(false);
          }
        }, { accent: true, title: "the author says it is addressed: verify your threads and review only the diff since your last review" })
      ) : null
    ),
    pr.new_count ? h("div", { style: { color } }, pr.role === "reviewer" ? "The author moved on your threads:" : `${pr.new_count} comment(s) arrived after the pipeline's last pass:`) : h("div", { style: sub }, pr.role === "reviewer" ? "No answers to your review yet." : "Nothing new since the pipeline last worked on it."),
    ...(pr.new || []).map((c) => h(
      "div",
      { key: c.id, className: "rounded border p-1.5", style: { borderColor: stroke } },
      h("div", { className: "flex gap-2", style: sub }, h("span", { className: "font-medium", style: { color: "var(--ui-text-secondary)" } }, c.author), h("span", null, c.kind), c.path ? h("span", { style: mono }, `${c.path}:${c.line || ""}`) : null, h("span", { className: "ml-auto" }, ago(c.at) + " ago")),
      c.html ? h(RichMd, { html: c.html }) : h("div", { className: "whitespace-pre-wrap" }, (c.body || "").slice(0, 600))
    )),
    // comments that ask for nothing the team's way (no tag, no suggestion, no change requested): not work, still visible
    (pr.skipped || []).length && pr.role !== "reviewer" ? h(
      Section,
      { title: `Skipped \xB7 ${pr.skipped.length} comment(s) that ask for nothing (no tag, no change requested)` },
      ...pr.skipped.map((c) => h(
        "div",
        { key: c.id, className: "cockpit-skipped rounded border p-1.5", style: { borderColor: stroke } },
        h("div", { className: "flex gap-2", style: sub }, h("span", { className: "font-medium" }, c.author), h("span", null, c.kind), h("span", null, c.why)),
        c.html ? h(RichMd, { html: c.html, style: sub }) : c.body ? h("div", { className: "whitespace-pre-wrap", style: sub }, c.body) : null
      ))
    ) : null
  );
}
function CiOverride({ r, onDone }) {
  const [open, setOpen] = useState9(false);
  const [reason, setReason] = useState9("");
  const [busy, setBusy] = useState9(false);
  if (!r.ci_override_allowed || !OPEN.has(r.status)) return null;
  const given = r.ci_override && r.payload && r.ci_override.sha === (r.payload.sha || "") ? r.ci_override : null;
  if (given) return h("div", { className: "text-xs", "data-ci-override": "given", style: { color: "var(--ui-warning, #c98a00)" } }, `CI overridden by you ${given.time ? ago(given.time) + " ago" : ""}: ${given.reason}`);
  const go = async () => {
    setBusy(true);
    try {
      await post("/ci-override", { id: r.id, reason });
      host.notify({ kind: "info", message: "CI overridden for this approval" });
      setOpen(false);
      onDone();
    } catch (e) {
      host.notifyError(e, "override failed");
    } finally {
      setBusy(false);
    }
  };
  if (!open) return h("div", { className: "text-xs" }, btn("Approve despite CI\u2026", () => setOpen(true), { title: "skip the green-CI wait for this approval at this commit; recorded with your reason" }));
  return h(
    "div",
    { className: "flex flex-col gap-1 rounded border p-2 text-xs", "data-ci-override": "ask", style: { borderColor: "var(--ui-warning, #c98a00)" } },
    h("div", null, "This approval will not wait for green CI at this commit. Say why (it is kept on the intent):"),
    h("textarea", { value: reason, onChange: (e) => setReason(e.target.value), rows: 2, className: "rounded border px-1", style: { borderColor: stroke } }),
    h("div", { className: "flex gap-1.5" }, btn(busy ? "working\u2026" : "Override CI", go, { accent: true, disabled: !reason.trim() || busy }), btn("Cancel", () => setOpen(false)))
  );
}
function SubmitReviewForm({ r, busy, setBusy, onDone }) {
  const [event, setEvent] = useState9(r.review && r.review.proposed_event || r.payload && r.payload.event || "COMMENT");
  const [summary, setSummary] = useState9(r.file_contents && r.file_contents.body_file || "");
  const go = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await post("/publish", { id: r.id, confirm: r.id, event, summary });
      host.notify({ kind: "success", title: "Review published", message: res.out.slice(0, 400) });
      onDone();
    } catch (e) {
      host.notifyError(e, "publish failed");
    } finally {
      setBusy(false);
    }
  };
  const opt = (v, label) => h("label", { className: "flex items-center gap-1 cursor-pointer" }, h("input", { type: "radio", name: "ev", checked: event === v, onChange: () => setEvent(v) }), label);
  return h(
    "div",
    { className: "flex flex-col gap-2 rounded border p-2 text-xs", style: { borderColor: "var(--ui-success, #2a9d5c)" } },
    h("div", { className: "font-medium" }, `Publish the pending review on ${r.target}`),
    h("div", { style: sub }, "The inline comments are already on the forge as pending. This submits them with the verdict and the summary below; the author is notified at that moment."),
    h("div", { className: "flex gap-4" }, opt("REQUEST_CHANGES", "Request changes"), opt("COMMENT", "Comment"), opt("APPROVE", "Approve")),
    event === "APPROVE" ? h("div", { style: { color: "var(--ui-warning, #c98a00)" } }, "Approve is yours alone: the lane proposed " + (r.review && r.review.proposed_event || r.payload && r.payload.event || "a verdict") + ".") : null,
    h(ClearableTextarea, { value: summary, onChange: (e) => setSummary(e.target.value), rows: 10, className: "rounded border bg-transparent px-2 py-1", style: { ...mono, borderColor: stroke } }),
    h(
      "div",
      { className: "flex gap-1.5" },
      h("button", { type: "button", disabled: busy, onClick: go, className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" } }, busy ? "working" : `Publish as ${event.replace("_", " ").toLowerCase()}`),
      btn("Cancel", onDone)
    )
  );
}
var OUTBOX_COLS = "6rem 9.5rem minmax(12rem, 1fr) 4.5rem 15.5rem 6.5rem 5.5rem 4rem";
var COMPACT_COLS = "5.5rem 8.5rem minmax(8rem, 1fr) 9rem";
var LABELS = { full: ["ticket", "status", "target", "risk", "type", "PR", "CI", ">age"], compact: ["ticket", "status", "target", "type"] };
var pickCells = (cells, compact) => {
  const o = [cells[0], cells[4], cells[2], cells[3], cells[1], cells[5], cells[6], cells[7]];
  return compact ? [o[0], o[1], o[2], o[4]] : o;
};
var typeColor = (t) => t === "ticket-done" ? "var(--ui-success, #2a9d5c)" : t === "push-branch" || t === "open-pr" || t === "pr-edit" || t === "pr-patch-apply" ? "var(--ui-accent)" : t === "pr-comment" || t === "pr-review-submit" ? "#a78bfa" : t.startsWith("tracker") ? "#22d3ee" : t === "ci-rerun" || t === "ci-dispatch" ? "var(--ui-warning, #c98a00)" : "var(--ui-text-secondary)";
var typeCell = (r, extra) => h("div", { key: "ty", className: "whitespace-nowrap overflow-hidden font-medium", style: { color: typeColor(r.type) }, title: r.skills && !r.skills.ok ? "produced without skill " + r.skills.missing.join(", ") : "" }, extra || r.type, rebaseBadge(r), r.skills && !r.skills.ok ? h("span", { style: { color: "var(--ui-danger, #d33)" } }, " \u25CF") : null);
var prCell = (r) => h(
  "div",
  { key: "pr", className: "flex gap-1 items-center whitespace-nowrap overflow-hidden", title: r && r.pr ? `${r.pr.url} \xB7 ${r.pr.new_count} comment(s) ahead of the pipeline` : "" },
  r && r.pr ? h("span", { style: sub }, r.pr.merged ? "merged" : `#${r.pr.number}`) : h("span", { style: sub }, "\u2013"),
  r && r.pr && !r.pr.merged && r.pr.approvals && r.pr.approvals.length ? h("span", { style: { color: "var(--ui-success, #2a9d5c)" }, title: "approved by " + r.pr.approvals.map((a) => a.author).join(", ") }, "\u{1F44D}") : null,
  r && r.pr && r.pr.new_count ? h("span", { className: "rounded px-1", style: { background: "var(--ui-warning, #c98a00)", color: "#fff" } }, `${r.pr.new_count} new`) : null
);
var ciCell = (r) => {
  const ci = ciMark(r && r.ci);
  return h("div", { key: "ci", className: "whitespace-nowrap overflow-hidden", title: r && r.ci ? `CI on ${r.ci.branch} @ ${r.ci.sha}: ${r.ci.summary}` : "" }, ci ? h("span", { style: { color: ci.c } }, ci.t) : h("span", { style: sub }, "\u2013"));
};
function Row({ r, selected, onSelect, compact }) {
  const m = statusMark(r);
  return trow(compact ? COMPACT_COLS : OUTBOX_COLS, { key: r.id, onClick: () => onSelect(r.id), selected, title: r.payload && r.payload.rebase_only ? "rebase only" : void 0, children: pickCells([
    h("div", { key: "t", className: "truncate font-medium" }, r.ticket),
    typeCell(r),
    h("div", { key: "tg", className: "truncate", title: r.summary }, r.target),
    h("div", { key: "r", style: { color: riskColor(r.risk) } }, r.risk),
    h("div", { key: "s", className: "truncate", style: { color: m.color } }, m.text),
    prCell(r),
    ciCell(r),
    h("div", { key: "a", className: "truncate text-right", style: sub, title: r.created_by }, ago(r.created_at))
  ], compact) });
}
var sourceKind = (path) => /\.json$/i.test(path || "") ? "JSON" : /\.md$/i.test(path || "") ? "Markdown" : "Source";
var prettySource = (source, kind) => {
  if (kind !== "JSON") return source;
  try {
    return JSON.stringify(JSON.parse(source), null, 2);
  } catch (e) {
    return source;
  }
};
function LeavesBody({ html, source, path }) {
  const [view, setView] = useState9("preview");
  const kind = sourceKind(path);
  const raw = h("pre", { className: "cockpit-source whitespace-pre-wrap text-xs", style: mono }, prettySource(source, kind));
  if (!html) return raw;
  return h(
    "div",
    { className: "flex flex-col gap-2" },
    h("div", { className: "flex items-center gap-1 self-start rounded border p-0.5", style: { borderColor: stroke } }, seg(view, "preview", "Preview", setView), seg(view, "source", kind, setView)),
    view === "preview" ? h(RichMd, { html }) : raw
  );
}
function Detail({ id }) {
  const qc = useQueryClient();
  const q2 = useQuery({ queryKey: ["cockpit", "intent", id], queryFn: () => CTX.rest("/intent?id=" + encodeURIComponent(id)), refetchInterval: POLL_MS, retry: 1 });
  const [tab, setTab] = useState9("intent");
  const [ask, setAsk] = useState9(null);
  const [toWorker, setToWorker] = useState9(false);
  const [reason, setReason] = useState9("");
  const [busy, setBusy] = useState9(false);
  const [files, setFiles] = useState9([]);
  useEffect6(() => {
    setAsk(null);
    setReason("");
    setTab("intent");
  }, [id]);
  useEffect6(() => {
    setFiles([]);
  }, [id, ask]);
  if (q2.isLoading) return h("div", { className: "p-3 text-xs", style: sub }, "loading");
  if (q2.error) return h("div", { className: "p-3 text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  const r = q2.data;
  const p = r.payload || {};
  const m = statusMark(r);
  const refresh = () => qc.invalidateQueries({ queryKey: ["cockpit"] });
  const act = async (path, body, okMsg) => {
    setBusy(true);
    try {
      const res = await post(path, body);
      host.notify({ kind: "success", message: okMsg || res && res.out || "done" });
      setAsk(null);
      setReason("");
      refresh();
    } catch (e) {
      host.notifyError(e, "cockpit outbox: action failed");
    } finally {
      setBusy(false);
    }
  };
  const copy2 = async () => {
    await CTX.os.writeClipboard(publishLine(r));
    host.notify({ kind: "info", message: "Copied for your shell: " + publishLine(r) });
  };
  const kv = (k, v) => v ? h("div", { className: "flex gap-2 text-xs" }, h("div", { className: "w-20 shrink-0", style: sub }, k), h("div", { className: "min-w-0 break-words", style: mono }, v)) : null;
  const canAct = OPEN.has(r.status) && r.type !== "ticket-done";
  const note = r.type === "infra-note" && Boolean(r.payload) && Boolean(r.payload.repo && r.payload.branch && r.payload.patch_file);
  const proposesApprove = r.type === "pr-review-submit" && r.status !== "posted" && Boolean(r.payload) && r.payload.event === "APPROVE";
  const confirmable = canAct && r.status === "held" && Boolean(r.hold) && r.hold.waits === "human" && !r.hold.ask;
  const hasRepo = Boolean(p.repo);
  const isDone = r.type === "ticket-done";
  return h(
    "div",
    { className: "flex h-full flex-col gap-3 overflow-auto p-3" },
    h(
      "div",
      { className: "flex items-baseline gap-2" },
      h("div", { className: "font-medium text-sm" }, r.digest_no ? `#${r.digest_no} \xB7 ` : "", r.ticket, " \xB7 ", r.type, rebaseBadge(r)),
      h("div", { className: "text-xs", style: { color: m.color } }, m.text),
      h("div", { className: "ml-auto text-xs", style: sub }, `${r.created_by || ""} \xB7 ${ago(r.created_at)} ago`)
    ),
    h("div", { className: "text-xs" }, r.summary),
    r.chain && r.chain.role === "content" ? h(
      "div",
      { className: "rounded border px-2 py-1 text-xs flex flex-col gap-0.5", style: { borderColor: "var(--ui-accent)" } },
      h("div", { className: "font-medium" }, "Two steps, one publish"),
      h("div", null, h(
        "span",
        { style: { color: String(r.chain.step1_status).startsWith("published") || r.chain.step1_status === "endorsed" ? "var(--ui-success, #2a9d5c)" : "var(--ui-warning, #c98a00)" } },
        `1 \xB7 ${r.chain.step1_status}`
      ), h("span", { style: sub }, r.chain.step1_rebase === false ? ` ${r.chain.step1_type} \xB7 ${r.chain.step1}` : ` \u27F3 rebase only \xB7 ${r.chain.step1} \xB7 ${r.chain.step1_proof || ""}`)),
      h("div", null, h("span", { style: { color: r.status === "endorsed" ? "var(--ui-success, #2a9d5c)" : "var(--ui-warning, #c98a00)" } }, `2 \xB7 ${r.status}`), h("span", { style: sub }, ` \u2192 the change (this intent): ${r.target}`)),
      !(String(r.chain.step1_status).startsWith("published") || r.chain.step1_status === "endorsed") ? h("div", { style: { color: "var(--ui-warning, #c98a00)" } }, "step 1 is not endorsed yet: the gatekeeper must endorse both before Publish") : null
    ) : null,
    r.waits ? h(
      "div",
      { className: "rounded border px-2 py-1 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)" }, "data-waits": r.waits.id },
      h("span", { className: "font-medium" }, "A stage of a sequence: "),
      r.waits.id === "CI" ? `offered once CI at its commit is green (CI ${r.waits.status}).` : `offered once ${r.waits.id} (${r.waits.type}) is out; it is ${r.waits.status}.`
    ) : null,
    r.stale_days ? h(
      "div",
      { className: "rounded border px-2 py-1.5 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)" } },
      h("span", { className: "font-medium", style: { color: "var(--ui-warning, #c98a00)" } }, "Stale"),
      ` pending for ${r.stale_days} days and nothing has touched it. It has no card on the Board: drop it if nobody will act on it.`
    ) : null,
    r.stale_head ? h(
      "div",
      { className: "flex flex-wrap items-center gap-2 rounded border px-2 py-1.5 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)" } },
      h("span", null, h("span", { className: "font-medium", style: { color: "var(--ui-warning, #c98a00)" } }, "PR head moved"), ` after this review was written: reviewed ${r.stale_head.reviewed}, now ${r.stale_head.now}. cockpit publish refuses it because line comments would mis-anchor.`),
      h(
        "button",
        {
          type: "button",
          disabled: busy,
          onClick: () => {
            haptic("tap");
            setBusy(true);
            post(
              "/pr-rereview",
              { ticket: r.ticket, repo: p.repo, number: p.number, supersede: r.id }
            ).then((res) => {
              host.notify({
                kind: "success",
                title: `${r.ticket} re-review at ${r.stale_head.now}`,
                message: res.out
              });
              refresh();
            }).catch((e) => host.notifyError(
              e,
              "re-review failed"
            )).finally(() => setBusy(false));
          },
          className: "rounded px-2.5 py-0.5 text-xs font-medium",
          style: { background: "var(--ui-accent)", color: "#fff" },
          title: "the reviewer lane re-verifies this review's findings at the new head and writes a fresh review intent; this one is dropped as superseded"
        },
        busy ? "working" : "\u21BB Re-review at the new head"
      ),
      btn("Diff since the reviewed head", () => setTab("diff"), { title: "what the author pushed after the review" })
    ) : null,
    r.status === "held" && r.hold && r.hold.ask ? h(DecidePanel, { r, onDone: refresh }) : null,
    isDone ? h(
      "div",
      { className: "flex flex-wrap items-center gap-1.5" },
      r.status === "pending" ? h("button", {
        type: "button",
        disabled: busy,
        onClick: () => {
          haptic("tap");
          setAsk(ask === "ack" ? null : "ack");
        },
        className: "rounded px-2.5 py-0.5 text-xs font-medium",
        style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" },
        title: "Only you can do this: the ticket is merged, released and really done in dev. Nothing is published."
      }, "\u{1F3C1} Confirm done") : null,
      r.status !== "reopened" ? btn("Reopen with details", () => setAsk(ask === "reopen" ? null : "reopen"), { accent: true, title: "restart the flow on this ticket with your prompt and evidence; intake proposes and waits for your go" }) : null,
      r.pr ? h("a", { href: r.pr.url, onClick: (e) => {
        e.preventDefault();
        openWeb(r.pr.url);
      }, className: "text-xs", style: { color: "var(--ui-accent)" } }, "PR on the forge") : null,
      r.pr ? copyBtn(r.pr.url, "PR link") : null,
      btn("Reveal", () => CTX.os.revealPath(r.path))
    ) : null,
    ask === "ack" ? h(
      "div",
      { className: "flex items-center gap-2 rounded border p-2 text-xs", style: { borderColor: "var(--ui-success, #2a9d5c)" } },
      h("span", null, `Confirm ${r.ticket} is done in dev? This only records your acknowledgement locally.`),
      h("button", { type: "button", disabled: busy, onClick: () => act("/ack", { id: r.id, confirm: r.id }, "Acknowledged " + r.ticket), className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" } }, busy ? "working" : "Yes, done"),
      btn("Cancel", () => setAsk(null))
    ) : null,
    ask === "reopen" ? h(ReopenForm, { ticket: r.ticket, onDone: () => setAsk(null) }) : null,
    !isDone ? h(
      "div",
      { className: "flex flex-wrap items-center gap-1.5" },
      r.type === "pr-review-submit" && r.status === "posted" ? h(
        "button",
        {
          type: "button",
          disabled: busy,
          onClick: () => {
            haptic("tap");
            setAsk(ask === "submit" ? null : "submit");
          },
          className: "rounded px-2.5 py-0.5 text-xs font-medium",
          style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" },
          title: "stage 2: submit the pending review with the verdict and a summary you confirm"
        },
        "\u2713 Publish review"
      ) : null,
      r.type === "pr-review-submit" && r.status === "posted" && r.review ? h("a", { href: r.review.url, onClick: (e) => {
        e.preventDefault();
        openWeb(r.review.url);
      }, className: "text-xs", style: { color: "var(--ui-accent)" } }, "check it on the forge") : null,
      r.type === "pr-review-submit" && r.status === "posted" ? btn("Discard pending review", () => setAsk(ask === "discard" ? null : "discard"), { danger: true, title: "delete the pending review on the forge; the intent goes back to endorsed (send it back with notes, or post again)" }) : null,
      // a hold that asks nothing is yours to confirm: that is the pane's first button, where Publish is once it is confirmed
      // (a greyed Publish beside a small Confirm read as "nothing to do here")
      confirmable ? h("button", {
        type: "button",
        disabled: busy,
        "data-step": "confirm",
        onClick: () => act("/confirm", { id: r.id }, "Confirmed " + r.id + " \u2014 publish it when you are ready"),
        className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40",
        style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" },
        title: `You checked it: ${r.hold.reason || "what the gatekeeper held it for"}. Endorse it as yours; Publish is the next step.`
      }, "Confirm") : null,
      // an infrastructure note with a patch: applying it is yours (it becomes your commit and a push for the gate)
      canAct && note ? h("button", {
        type: "button",
        disabled: busy,
        "data-step": "apply-note",
        onClick: () => {
          haptic("tap");
          setAsk(ask === "apply" ? null : "apply");
        },
        className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40",
        style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" },
        title: "commit this patch on the ticket's checkout as yours and file its push"
      }, "Apply patch") : null,
      canAct && r.status !== "posted" && !confirmable && r.type !== "infra-note" ? h(
        "button",
        {
          type: "button",
          disabled: r.status !== "endorsed" || busy || Boolean(r.stale_head) || Boolean(r.waits) || r.chain && r.chain.role === "content" && !(r.chain.step1_status === "endorsed" || String(r.chain.step1_status).startsWith("published")),
          onClick: () => {
            haptic("tap");
            setAsk("publish");
          },
          className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40",
          style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" },
          title: r.waits ? "A later stage: it is offered once the stage before it is out" : r.status === "endorsed" ? "Publish this intent now (cockpit publish --id <intent>). You confirm on the next step." : "Needs the gatekeeper's endorsement first (Inbox \u2192 Gate tools \u2192 Sweep now)"
        },
        r.chain && r.chain.role === "content" ? r.chain.step1_rebase === false ? `\u2713 Publish both (${r.chain.step1_type}, then ${r.type})` : "\u2713 Publish both (rebase, then change)" : r.type === "pr-review-submit" ? "\u2713 Post as pending review" : "\u2713 Publish"
      ) : null,
      canAct ? btn("Copy publish line", copy2, { title: publishLine(r) + "  \u2014 the same thing from your own shell" }) : null,
      btn("Open intent file", () => openIde({ id: r.id, file: r.path }), { title: r.path }),
      btn("Reveal", () => CTX.os.revealPath(r.path), { title: "show in Finder" }),
      canAct ? h("span", { className: "mx-1", style: sub }, "|") : null,
      canAct ? btn("Verify sha", async () => {
        setBusy(true);
        try {
          const res = await post(
            "/verify",
            { id: r.id }
          );
          if (res && res.ok === false) host.notifyError(
            new Error((res.problems || ["not verified"]).join(" \xB7 ")),
            "verify: not ok"
          );
          else host.notify({ kind: "success", message: res && res.out || "verified" });
        } catch (e) {
          host.notifyError(
            e,
            "cockpit outbox: action failed"
          );
        } finally {
          setBusy(false);
        }
      }, { title: "cockpit outbox verify: intent sha vs the worktree HEAD" }) : null,
      // git could not be read when the intent was written: read it again, with what goes out left as it is
      canAct && r.payload && r.payload.probe_error && ["pending", "held", "endorsed"].includes(r.status) ? btn("Re-probe", () => act("/reprobe", { id: r.id }, "Git read again for " + r.id + " \u2014 it is back with the gatekeeper"), { accent: true, title: `git could not be read when this intent was written (${r.payload.probe_error}): read it again; what goes out is not changed` }) : null,
      canAct && r.status !== "returned" ? btn("Send back", () => {
        setAsk("return");
        if (r.hold && r.hold.rework) setReason((r.hold.ask ? `Decision: 

` : "") + r.hold.rework);
      }, { accent: true, title: "tell the lane what to change; it reworks on the same branch and amends this intent" }) : null,
      // a hold that waits on you and asks nothing (commits by another author, say): you check it, then confirm it as yours;
      // Publish is then your next step, and nothing publishes it for you
      canAct && r.status !== "held" ? btn("Hold", () => setAsk("hold")) : null,
      canAct ? btn("Drop", () => setAsk("drop"), { danger: true }) : null
    ) : null,
    h(CiOverride, { r, onDone: refresh }),
    ask === "submit" ? h(SubmitReviewForm, { r, busy, setBusy, onDone: () => {
      setAsk(null);
      refresh();
    } }) : null,
    ask === "discard" ? h(
      "div",
      { className: "flex items-center gap-2 rounded border p-2 text-xs", style: { borderColor: "var(--ui-danger, #d33)" } },
      h("span", null, "Delete the pending review on the forge? The findings stay in the intent; you can send it back with notes and post again."),
      h("button", { type: "button", disabled: busy, onClick: () => act("/review-discard", { id: r.id, confirm: r.id }, "pending review discarded"), className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: "var(--ui-danger, #d33)", color: "#fff" } }, busy ? "working" : "Discard"),
      btn("Cancel", () => setAsk(null))
    ) : null,
    ask === "apply" ? h(
      "div",
      { className: "flex flex-col gap-2 rounded border p-2 text-xs", style: { borderColor: "var(--ui-success, #2a9d5c)" } },
      h("div", { className: "font-medium" }, `Apply ${r.payload.patch_file} in ${r.payload.repo} on ${r.payload.branch}?`),
      h("div", { style: sub }, `It is committed there as your commit, and its push is filed for the gatekeeper and your Publish. ${r.created_by || "The lane"} wrote the patch and could not write these files itself. Read the patch first: this is the approval of that one diff.`),
      h(
        "div",
        { className: "flex items-center gap-1.5" },
        h("button", { type: "button", disabled: busy, onClick: () => {
          haptic("tap");
          act("/apply-note", { id: r.id, confirm: r.id }, "Applied " + r.id + " \u2014 its push comes to the Inbox");
        }, className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" } }, busy ? "working" : "Apply now"),
        btn("Open the patch", () => openIde({ id: r.id, file: r.payload.patch_file }), { title: r.payload.patch_file }),
        btn("Cancel", () => setAsk(null))
      )
    ) : null,
    ask === "publish" ? h(
      "div",
      { className: "flex flex-col gap-2 rounded border p-2 text-xs", style: { borderColor: "var(--ui-success, #2a9d5c)" } },
      h("div", { className: "font-medium" }, r.chain && r.chain.role === "content" ? r.chain.step1_rebase === false ? `Publish the pair: 1 \xB7 ${r.chain.step1_type} (${r.chain.step1}) then 2 \xB7 ${r.type} ${r.target}?` : `Publish the pair: 1 \xB7 rebase only (${r.chain.step1}) then 2 \xB7 ${r.target}?` : r.type === "pr-review-submit" ? proposesApprove ? `Post the review on ${r.target} as PENDING, with the verdict the lane proposed: APPROVE? Approving is yours alone: you confirm the verdict when you publish it (stage 2). Only you can see it until then.` : `Post the review on ${r.target} as PENDING? Only you can see it there; nobody is notified until you publish it (stage 2).` : `Publish ${r.type} \u2192 ${r.target}?`),
      h("div", { style: sub }, `Runs as you: ${publishLine(r)}. Endorsed by ${endorserOf(r)} ${r.endorsed ? ago(r.endorsed.time) + " ago, risk " + r.endorsed.risk : ""}. cockpit publish re-checks the sha against the worktree before anything leaves.`),
      r.pr && r.pr.new_count ? h("div", { style: { color: "var(--ui-warning, #c98a00)" } }, `Note: ${r.pr.new_count} PR comment(s) arrived after the pipeline's pass \u2014 treat them first if they change this.`) : null,
      h(
        "div",
        { className: "flex items-center gap-1.5" },
        h("button", { type: "button", disabled: busy, onClick: () => {
          haptic("tap");
          act("/publish", proposesApprove ? { id: r.id, confirm: r.id, approve: true } : { id: r.id, confirm: r.id }, "Published " + r.id);
        }, className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" } }, busy ? "working" : "Publish now"),
        btn("Dry run", async () => {
          setBusy(true);
          try {
            const res = await post("/publish", { id: r.id, dry_run: true });
            host.notify({ kind: "info", message: res.out, title: "Dry run" });
          } catch (e) {
            host.notifyError(e, "dry run failed");
          } finally {
            setBusy(false);
          }
        }, { title: "cockpit publish --dry-run: shows what would happen, nothing leaves" }),
        btn("Cancel", () => setAsk(null))
      )
    ) : null,
    ask && ask !== "publish" && ask !== "apply" ? h(
      "div",
      { className: "flex items-center gap-2 rounded border p-2 text-xs", style: { borderColor: stroke } },
      h("span", null, ask === "hold" ? "Hold \u2014 why?" : ask === "return" ? `Send back to ${r.created_by || "the lane"} \u2014 what should change?` : "Drop this intent (the lane keeps its work; nothing is deleted). Note:"),
      ask === "return" ? h(
        "div",
        { className: "flex min-w-0 flex-1 flex-col gap-1" },
        h(ClearableTextarea, {
          value: reason,
          onChange: (e) => setReason(e.target.value),
          autoFocus: true,
          rows: 3,
          placeholder: "e.g. make the comment more concise: two sentences, no restating the diff",
          onPaste: onPasteImages(r.ticket, setFiles),
          className: "min-w-0 rounded border bg-transparent px-1.5 py-0.5",
          style: { borderColor: stroke },
          onKeyDown: (e) => {
            if (e.key === "Escape") setAsk(null);
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && reason.trim()) act(
              "/return",
              { id: r.id, instruction: reason, evidence: files.map((f) => f.path), ...toWorker ? { assignee: "worker" } : {} }
            );
          }
        }),
        h(Attach, { ticket: r.ticket, files, setFiles }),
        // a lane that does not write code (a reviewer, the gatekeeper) cannot make a code change: a worker takes the card
        h(
          "label",
          { className: "flex items-center gap-1.5", style: sub, title: "a free worker makes the change on the ticket's checkout and files its push; the lane that wrote this intent then redoes it" },
          h("input", { type: "checkbox", checked: toWorker, onChange: (e) => setToWorker(e.target.checked) }),
          "it needs a code change: send it to a worker"
        )
      ) : h("input", {
        value: reason,
        onChange: (e) => setReason(e.target.value),
        autoFocus: true,
        placeholder: ask === "hold" ? "reason (required)" : "optional note",
        className: "min-w-0 flex-1 rounded border bg-transparent px-1.5 py-0.5",
        style: { borderColor: stroke },
        onKeyDown: (e) => {
          if (e.key === "Escape") setAsk(null);
        }
      }),
      btn(busy ? "working" : ask === "hold" ? "Hold" : ask === "return" ? "Send back (\u2318\u21B5)" : "Drop", () => {
        if (busy) return;
        if (ask === "return") {
          if (!reason.trim()) return;
          act("/return", { id: r.id, instruction: reason, evidence: files.map((f) => f.path), ...toWorker ? { assignee: "worker" } : {} });
          return;
        }
        if (ask === "hold" && !reason.trim()) return;
        act(ask === "hold" ? "/hold" : "/drop", ask === "hold" ? { id: r.id, reason } : { id: r.id, note: reason });
      }, { danger: ask === "drop", accent: ask === "return" }),
      btn("Cancel", () => setAsk(null))
    ) : null,
    // the busy reader's version, always open: what leaves · why · checked · touches
    // a held intent with a question has its chat inside the decision form, above the question: one chat per pane
    r.status === "held" && r.hold && r.hold.ask ? null : h(TicketTools, { ticket: r.ticket, card: intentCard(r), part: "chat" }),
    h(Section, { title: "Brief", open: true, color: "var(--ui-accent)" }, h(RichMd, { html: r.brief || "" })),
    h(TicketTools, { ticket: r.ticket, card: intentCard(r), part: "demo" }),
    // what leaves the machine is never collapsed: the exact text the publish sends
    r.outgoing && r.file_contents && r.file_contents[r.outgoing] != null ? h(
      Section,
      { title: `What leaves \xB7 ${(r.files[r.outgoing] || "").split("/").slice(-2).join("/")}`, open: true, color: "var(--ui-success, #2a9d5c)", extra: btn("open", () => openFile(r.files[r.outgoing]), { title: r.files[r.outgoing] }) },
      (r.file_truncated || []).includes(r.outgoing) ? h("div", { className: "text-xs", style: { color: "var(--ui-danger, #d33)" } }, "This body is larger than the Cockpit shows (2 MB): open the file to read all of it.") : null,
      h(LeavesBody, { html: r.file_html && r.file_html[r.outgoing], source: r.file_contents[r.outgoing], path: r.files[r.outgoing] })
    ) : null,
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2" },
      h("div", { className: "flex items-center gap-1 rounded border p-0.5", style: { borderColor: stroke } }, seg(tab, "intent", "Intent", setTab), hasRepo ? seg(tab, "diff", r.type === "pr-patch-apply" ? "Diff (what gets pushed)" : r.type === "push-branch" ? "Diff (what gets pushed)" : "Diff (worktree vs the base branch)", setTab) : null, seg(tab, "evidence", "Evidence (QA runs)", setTab)),
      prButtons(r.prs)
    ),
    tab === "evidence" ? h(Evidence, { ticket: r.ticket }) : tab === "diff" ? h(DiffPanel, { params: { id: r.id }, defaultMode: r.type === "pr-patch-apply" ? "origin" : r.type === "push-branch" ? r.chain && r.chain.role === "content" ? "change" : "origin" : "base", chained: Boolean(r.chain && r.chain.role === "content"), rebaseOnly: Boolean(p.rebase_only) }) : h(
      "div",
      { className: "flex flex-col gap-2" },
      // PR and CI stay open only while something there needs you (new comments, a failed run)
      r.pr || r.ci ? h(
        Section,
        { title: "PR \xB7 CI" + (r.pr && r.pr.new_count ? ` \xB7 ${r.pr.new_count} new comment(s)` : "") + (r.ci ? ` \xB7 CI ${r.ci.state}` : ""), open: Boolean(r.pr && r.pr.new_count || r.ci && r.ci.state === "failed" && !r.ci.handled), color: r.pr && r.pr.new_count || r.ci && r.ci.state === "failed" && !r.ci.handled ? "var(--ui-warning, #c98a00)" : void 0 },
        r.pr ? h(PrBox, { pr: r.pr, ticket: r.ticket, repo: p.repo, refresh }) : null,
        r.ci ? h(
          "div",
          { className: "rounded border p-2 text-xs flex flex-col gap-1", style: { borderColor: ciMark(r.ci).c } },
          h(
            "div",
            { className: "flex items-center gap-2" },
            h("div", { className: "font-medium" }, `CI on ${r.ci.branch || ""} @ ${r.ci.sha}: ${r.ci.summary} \xB7 checked ${ago(r.ci.last_check)} ago`),
            r.ci.state === "failed" ? h(
              "span",
              { className: "ml-auto flex items-center gap-1" },
              r.ci.handled ? h("span", { style: sub }, r.ci.dismissed ? "dismissed" : "analysed") : btn("Dismiss", () => act("/ci-dismiss", { ticket: r.ticket, repo: r.ci.repo || p.repo, sha: r.ci.sha }, "CI failure dismissed"), { title: "drop it from the Inbox (you dealt with it, or it does not matter)" }),
              btn("Forget", () => act("/ci-forget", { ticket: r.ticket, sha: r.ci.sha }, "CI state forgotten"), { title: "delete this sha's check-watch state" })
            ) : null
          ),
          ...r.ci.runs.map((x) => h(
            "div",
            { key: x.id, className: "flex gap-2" },
            h(
              "span",
              { style: { color: x.conclusion === "success" ? "var(--ui-success, #2a9d5c)" : x.status !== "completed" ? "var(--ui-warning, #c98a00)" : "var(--ui-danger, #d33)" } },
              x.conclusion || x.status
            ),
            h(
              "a",
              { href: x.url, onClick: (e) => {
                e.preventDefault();
                openWeb(x.url);
              }, style: { color: "var(--ui-accent)" } },
              `${x.workflow} / ${x.name}`
            ),
            r.ci.cards[String(x.id)] ? h(
              "span",
              { style: sub },
              `\u2192 analyst card ${r.ci.cards[String(x.id)]}`
            ) : null
          ))
        ) : null
      ) : null,
      h(
        Section,
        { title: `${r.endorsed && r.endorsed.by || "gatekeeper"} check \xB7 ` + (r.endorsed ? `endorsed, risk ${r.endorsed.risk}` : r.hold ? "held" : r.status), color: r.hold ? "var(--ui-warning, #c98a00)" : void 0 },
        // the gatekeeper's notes, its hold and the return's instruction are markdown; the backend renders them (*_html), older rows show the text
        r.endorsed ? h("div", { className: "rounded border p-2 text-xs", style: { borderColor: "var(--ui-success, #2a9d5c)" } }, h("div", { className: "font-medium" }, `${endorserOf(r)} endorsed \xB7 risk ${r.endorsed.risk} \xB7 ${ago(r.endorsed.time)} ago`), r.endorsed_html && r.endorsed_html.notes ? h(RichMd, { html: r.endorsed_html.notes }) : h("div", null, r.endorsed.notes || "")) : null,
        r.hold ? h("div", { className: "rounded border p-2 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)" } }, h("div", { className: "font-medium" }, "Held"), r.hold_html && r.hold_html.reason ? h(RichMd, { html: r.hold_html.reason }) : h("div", null, r.hold.reason)) : null,
        r.receipt ? h(
          "div",
          { className: "rounded border p-2 text-xs", style: { borderColor: stroke } },
          h("div", { className: "font-medium" }, `Published ${ago(r.receipt.time)} ago`),
          r.receipt.url ? h("a", { href: r.receipt.url, onClick: (e) => {
            e.preventDefault();
            openWeb(r.receipt.url);
          }, style: { color: "var(--ui-accent)" } }, r.receipt.url) : null,
          r.receipt.output ? h("pre", { className: "whitespace-pre-wrap", style: { ...mono, ...sub } }, String(r.receipt.output).slice(0, 600)) : null
        ) : null,
        r.returned ? h(
          "div",
          { className: "rounded border p-2 text-xs", style: { borderColor: "var(--ui-accent)" } },
          h("div", { className: "font-medium" }, `Sent back to ${r.returned.lane} \xB7 ${ago(r.returned.time)} ago${r.returned.card ? " \xB7 card " + r.returned.card : ""}${r.returned.resolved ? " \xB7 reworked " + ago(r.returned.resolved) + " ago" : " \xB7 rework pending"}`),
          r.returned_html && r.returned_html.instruction ? h(RichMd, { html: r.returned_html.instruction }) : h("div", { className: "whitespace-pre-wrap" }, r.returned.instruction)
        ) : null,
        r.skills && r.skills.required && r.skills.required.length ? h(
          "div",
          { className: "text-xs flex gap-2 items-center" },
          h("span", { style: sub }, "produced with skills:"),
          h("span", { style: mono }, r.skills.loaded ? r.skills.loaded.join(", ") || "(none)" : "(no run log)"),
          r.skills.ok ? h("span", { style: { color: "var(--ui-success, #2a9d5c)" } }, "\u2713 " + r.skills.required.join(", ")) : h("span", { className: "rounded px-1", style: { background: "var(--ui-danger, #d33)", color: "#fff" } }, "missing " + r.skills.missing.join(", ") + " \u2014 hold / send back")
        ) : null,
        !r.endorsed && !r.hold && !r.receipt && !r.returned && !(r.skills && r.skills.required && r.skills.required.length) ? h("div", { style: sub }, "nothing recorded yet") : null
      ),
      h(
        Section,
        { title: "Details" + (p.commits && p.commits.length ? ` \xB7 ${p.commits.length} commit(s)` : "") + (p.files && p.files.length ? ` \xB7 ${p.files.length} file(s)` : "") },
        h(
          "div",
          { className: "flex flex-col gap-1" },
          kv("intent", r.id),
          kv("card", r.card_id),
          kv("repo", p.repo),
          kv("branch", p.branch ? `${p.branch}${p.publish_as && p.publish_as !== p.branch ? " \u2192 " + p.publish_as : ""}` : null),
          kv("base", p.base),
          kv("sha", p.sha),
          p.rebase_only ? kv("rebase", `only \u2014 ${p.rebase_proof || ""}`) : null,
          p.after ? kv("after", p.after + " (lease = its sha)") : null,
          kv("PR", p.number ? `#${p.number} ${p.event || ""}` : null),
          r.type === "pr-comment" ? kv("posts as", p.in_reply_to ? `reply in review thread ${p.in_reply_to}${p.react ? " \xB7 \u{1F44D}" : ""}${p.resolve ? " \xB7 resolves " + (p.thread || "?") : ""}` : "top-level PR comment") : null,
          kv("issue", p.issue),
          kv("title", p.title),
          kv("diff", p.diffstat)
        ),
        p.commits && p.commits.length ? h("div", null, h("div", { className: "text-xs font-medium" }, "Commits"), h("pre", { className: "whitespace-pre-wrap text-xs", style: mono }, p.commits.join("\n"))) : null,
        p.files && p.files.length ? h("div", null, h("div", { className: "text-xs font-medium" }, `Files (${p.files.length})`), h("pre", { className: "whitespace-pre-wrap text-xs", style: mono }, p.files.join("\n"))) : null
      ),
      ...Object.entries(r.file_contents || {}).filter(([k]) => k !== r.outgoing).map(([k, text]) => h(
        Section,
        { key: k, title: `${k.replace("_file", "")} \xB7 ${r.files[k].split("/").slice(-2).join("/")}`, extra: btn("open", () => openFile(r.files[k]), { title: r.files[k] }) },
        r.file_html && r.file_html[k] ? h(RichMd, { html: r.file_html[k] }) : h("pre", { className: "whitespace-pre-wrap text-xs", style: mono }, text)
      )),
      r.history && r.history.length || r.log && r.log.length ? h(
        Section,
        { title: "History \xB7 log" },
        r.history && r.history.length ? h("div", { className: "text-xs", style: sub }, r.history.map((x) => `${x.event} ${ago(x.time)} ago${x.card ? " (" + x.card + ")" : ""}`).join(" \xB7 ")) : null,
        r.log && r.log.length ? h("pre", { className: "whitespace-pre-wrap text-xs", style: { ...mono, ...sub } }, r.log.join("\n")) : null
      ) : null
    )
  );
}

// src/views/settings.js
import { useState as useState10 } from "react";
var SEATS = [["slots", "Agent slots", "a worker and a tester per slot (the slot stacks exist for three)"], ["intake", "Intake seats", "Dev kickoffs: intake reproduces and proposes"], ["reviewer", "Reviewer seats", "Review and Bump"], ["analyst", "Analyst seats", "Question"]];
var num = (v) => v === "" || v == null ? "" : Number(v);
var box = (title, ...kids) => h("div", { className: "flex flex-col gap-1 rounded border px-3 py-2", style: { borderColor: stroke } }, h("div", { className: "cockpit-head mb-1" }, title), ...kids);
function PluginUpdate() {
  const qc = useQueryClient();
  const q2 = useQuery({ queryKey: ["cockpit", "update"], queryFn: () => CTX.rest("/update"), refetchInterval: 6e4, retry: 0 });
  const [busy, setBusy] = useState10("");
  const [last, setLast] = useState10(null);
  const act = async (key, path, title) => {
    setBusy(key);
    try {
      const r2 = await post(path, {});
      if (key === "apply") setLast(r2);
      host.notify({ kind: "success", title, message: r2.out || (r2.remote && r2.remote.behind ? `${r2.remote.behind} commit(s) behind` : "up to date") });
      qc.invalidateQueries({ queryKey: ["cockpit"] });
    } catch (e) {
      host.notifyError(e, title + " failed");
    } finally {
      setBusy("");
    }
  };
  if (q2.error) return box("Plugin update", h("div", { style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error)));
  const d = q2.data || {};
  const i = d.installed || {};
  const r = d.remote || {};
  const behind = r.behind == null ? null : Number(r.behind);
  const state = d.error ? ["not a git checkout", "var(--ui-warning, #c98a00)"] : d.dirty ? ["local edits in the checkout: update refused until they are committed or stashed", "var(--ui-warning, #c98a00)"] : behind == null ? [r.error ? `last check failed: ${r.error}` : "not checked yet", sub.color] : behind > 0 ? [`${behind} commit(s) behind origin/${r.branch || i.branch || ""} (${r.short || ""})`, "var(--ui-accent)"] : ["up to date", "var(--ui-success, #2a9d5c)"];
  return box(
    "Plugin update (this cockpit against its repository)",
    h(
      "div",
      { className: "grid items-center gap-x-3 gap-y-1", style: { gridTemplateColumns: "7rem 1fr" } },
      h("span", { style: sub }, "installed"),
      h("span", null, h("span", { style: mono }, i.short || "?"), i.subject ? ` \xB7 ${i.subject}` : "", i.date ? h("span", { style: sub }, ` \xB7 ${ago(i.date)} ago`) : null),
      h("span", { style: sub }, "installed from"),
      h(
        "span",
        null,
        h("span", { className: "rounded border px-1.5 py-0.5", style: { ...mono, borderColor: stroke }, title: "the branch this checkout follows; an update moves to its head" }, i.follows || "no branch followed"),
        i.branch && i.follows && !i.follows.endsWith("/" + i.branch) ? h("span", { style: sub }, ` \xB7 local branch ${i.branch}`) : null
      ),
      h("span", { style: sub }, "repository"),
      h("span", { style: { color: state[1] } }, state[0], r.checked_at ? h("span", { style: sub }, ` \xB7 checked ${ago(new Date(r.checked_at * 1e3).toISOString())} ago`) : null),
      d.desktop_stale ? h("span", { style: sub }, "Desktop") : null,
      d.desktop_stale ? h("span", { style: { color: "var(--ui-warning, #c98a00)" } }, d.desktop_stale) : null
    ),
    h(
      "div",
      { className: "flex items-center gap-2 pt-1" },
      btn(busy === "check" ? "Checking\u2026" : "Check now", () => act("check", "/update-check", "update check"), { disabled: Boolean(busy), title: "git fetch origin and count the commits the checkout is behind (housekeeping does this hourly)" }),
      h("button", {
        type: "button",
        disabled: Boolean(busy) || d.dirty || Boolean(d.error) || !behind,
        onClick: () => act("apply", "/update-apply", "cockpit update"),
        className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40",
        style: { background: "var(--ui-accent)", color: "#fff" },
        title: "fast-forward to origin, refresh the kernel dependencies when they changed, drop stale bytecode, bump the Desktop bundle time, record the revision with Hermes, restart the gateway (it drains running jobs first)"
      }, busy === "apply" ? "Updating\u2026" : "Update now"),
      h("span", { style: sub }, "after an update: the gateway restarts by itself; the rest is one line for your shell, shown here once the update ran")
    ),
    last ? h(
      "div",
      { className: "flex flex-col gap-0.5 pt-1" },
      h("div", { style: { color: "var(--ui-success, #2a9d5c)" } }, last.out),
      ...(last.commits || []).map((line) => h("div", { key: line, style: { ...mono, ...sub } }, line)),
      last.hermes_record ? h("div", { style: sub }, `Hermes's install record: ${last.hermes_record}`) : null,
      h(NextLine, { next: last.next })
    ) : null
  );
}
function NextLine({ next }) {
  const steps = next && next.steps || [];
  if (!steps.length) return null;
  return h(
    "div",
    { className: "flex flex-col gap-1 pt-1", "data-next-line": "1" },
    h("div", { className: "font-medium" }, "Now run, in your shell:"),
    h(
      "div",
      { className: "flex items-start gap-2" },
      h("code", { className: "rounded px-1.5 py-0.5 whitespace-pre-wrap break-all", style: { ...mono, background: "rgba(127,127,127,.12)" } }, next.line),
      copyBtn(next.line, "the line to run after the update")
    ),
    h("div", { style: sub }, steps.map((s) => s.what).join(" \u2192 "))
  );
}
function Settings() {
  const q2 = useQuery({ queryKey: ["cockpit", "settings"], queryFn: () => CTX.rest("/settings"), refetchInterval: (d2) => d2 && d2.apply && d2.apply.running ? 2e3 : 2e4, retry: 1 });
  const qc = useQueryClient();
  const [edit, setForm] = useState10(null);
  const [busy, setBusy] = useState10(false);
  const [gcOut, setGcOut] = useState10(null);
  if (q2.error) return h("div", { className: "p-3 text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  if (q2.isLoading || !q2.data) return h("div", { className: "p-3 text-xs", style: sub }, "loading");
  const d = q2.data;
  const b = d.budget || {};
  const lim = d.limits || {};
  const form = edit || d.settings;
  const set = (path, v) => {
    const f = structuredClone(form);
    const [a, k] = path.split(".");
    if (k) f[a][k] = v;
    else f[a] = v;
    setForm(f);
  };
  const act = async (path, body, title) => {
    setBusy(true);
    try {
      const r = await post(path, body);
      host.notify({ kind: "success", title, message: r.out });
      qc.invalidateQueries({ queryKey: ["cockpit"] });
    } catch (e) {
      host.notifyError(e, title + " failed");
    } finally {
      setBusy(false);
    }
  };
  const field = (path, value, props = {}) => h("input", { type: "number", value: value ?? "", onChange: (e) => set(path, num(e.target.value)), className: "w-20 rounded border bg-transparent px-1.5 py-0.5 text-right", style: { borderColor: stroke, fontVariantNumeric: "tabular-nums" }, ...props });
  const row = (label, hint, input) => h("div", { className: "grid items-center gap-3 py-1", style: { gridTemplateColumns: "11rem 6rem 1fr" } }, h("div", { className: "font-medium" }, label), input, h("div", { style: sub }, hint));
  const bar = (pct, cap) => h("div", { className: "h-2 rounded", style: { background: "rgba(127,127,127,.18)" } }, h("div", { className: "h-2 rounded", style: { width: Math.min(100, pct) + "%", background: pct >= (cap || 100) ? "var(--ui-danger, #d33)" : pct >= (cap || 100) * 0.8 ? "var(--ui-warning, #c98a00)" : "var(--ui-success, #2a9d5c)" } }));
  const monthPct = b.cap_usd ? 100 * b.month_usd / b.cap_usd : 0;
  const w = b.window;
  const dirty = JSON.stringify(form) !== JSON.stringify(d.settings);
  const g = d.worktree_gc || {};
  const gl = g.last || {};
  const gcForm = form.worktree_gc || { enabled: false, days: 14 };
  const gcRun = async (dry) => {
    setBusy(true);
    try {
      const r = await post("/worktree-gc", { dry_run: dry, days: gcForm.days });
      setGcOut(r.lines || []);
      host.notify({ kind: "success", title: dry ? "worktree gc preview" : "worktree gc", message: r.out });
      qc.invalidateQueries({ queryKey: ["cockpit"] });
    } catch (e) {
      host.notifyError(e, "worktree gc failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3 text-xs" },
    b.over ? h("div", { className: "rounded border px-3 py-2", style: { borderColor: "var(--ui-danger, #d33)", color: "var(--ui-danger, #d33)" } }, `Over budget: no new kickoff starts \u2014 ${b.why}`) : null,
    box(
      "Seats per flow (the capacity pills count them; anything queued is a taken seat)",
      ...SEATS.map(([k, label, hint]) => row(label, `${hint} \xB7 ${(lim[k] || [1, 5]).join("\u2013")}`, field(`seats.${k}`, form.seats[k], { min: (lim[k] || [1])[0], max: (lim[k] || [1, 5])[1], step: 1 })))
    ),
    box(
      "Budget (stops new kickoffs; the lanes already running finish)",
      row("Monthly cap, $", `the Hermes stack's list-price estimate this month (the Usage page): \u2248$${(b.month_usd || 0).toFixed(2)}${b.cap_usd ? ` of $${b.cap_usd.toFixed(2)}` : " \xB7 0 = no cap"}`, field("budget.monthly_usd", form.budget.monthly_usd, { min: 0, step: 10 })),
      b.cap_usd ? bar(monthPct, 100) : null,
      row(
        "Plan window ceiling, %",
        w ? `the fullest provider plan window: ${w.name} ${w.used}% used, resets in ${w.resets_in}` : (b.unmetered || []).length && !b.error ? `no plan windows: Hermes reads none for ${b.unmetered.join(", ")} (not metered)` : "the provider plan windows (hermes usage) could not be read",
        field("budget.plan_window_max_pct", form.budget.plan_window_max_pct, { min: 1, max: 100, step: 5 })
      ),
      w ? bar(w.used, form.budget.plan_window_max_pct) : null,
      (b.ignored || []).length ? h("div", { style: sub }, `not counted: ${b.ignored.join(", ")} \u2014 no Hermes lane runs that model (the lanes run ${(b.families || []).join(", ") || "\u2026"})`) : null
    ),
    box("External browser", row("Lend it for, hours", "how long a test kickoff keeps the external browser (your Chrome) when you tick it on the kickoff; only that test uses it, and its failure videos come from cockpit record", field("shared_chrome_hours", form.shared_chrome_hours, { min: 0.25, max: 24, step: 0.5 }))),
    box(
      "Worktrees (a daily pass removes the ticket folders under wt/ nothing touched for a while; off by default)",
      row(
        "Remove stale worktrees",
        "a folder goes only when nothing under it was touched, no slot or open card holds the ticket, no process runs inside it, every checkout is clean and its commits are on a remote; branches stay",
        h("input", { type: "checkbox", checked: Boolean(gcForm.enabled), onChange: (e) => set("worktree_gc.enabled", e.target.checked), className: "justify-self-start", "data-worktree-gc": "1" })
      ),
      row("Untouched for, days", `the age a folder must have before it goes \xB7 ${(lim.worktree_gc_days || [1, 365]).join("\u2013")}`, field("worktree_gc.days", gcForm.days, { min: (lim.worktree_gc_days || [1])[0], max: (lim.worktree_gc_days || [1, 365])[1], step: 1 })),
      h(
        "div",
        { className: "flex items-center gap-2 pt-1" },
        btn("Preview", () => gcRun(true), { disabled: busy, title: "list what a pass would remove now, with the reason every other folder stays (cockpit worktree gc --dry-run)" }),
        btn("Run now", () => gcRun(false), { disabled: busy, title: "one pass now, whatever the switch says (cockpit worktree gc)" }),
        h("span", { style: sub }, gl.ran_at ? `last pass ${ago(new Date(gl.ran_at * 1e3).toISOString())} ago: ${gl.summary || ""}` : "no automatic pass yet")
      ),
      gcOut ? h("pre", { className: "whitespace-pre-wrap pt-1", style: { ...mono, ...sub } }, gcOut.join("\n")) : null
    ),
    h(
      "div",
      { className: "flex items-center gap-2" },
      h("button", { type: "button", disabled: busy || !dirty, onClick: () => act("/settings", { settings: form }, "settings").then(() => setForm(null)), className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-accent)", color: "#fff" } }, "Save"),
      dirty ? btn("Discard", () => setForm(null)) : null,
      d.missing_lanes && d.missing_lanes.length ? h(
        "span",
        { className: "flex items-center gap-2" },
        h("span", { style: { color: "var(--ui-warning, #c98a00)" } }, `no profile yet for ${d.missing_lanes.join(", ")}`),
        btn(d.apply.running ? "Applying\u2026" : "Apply profiles", () => act("/settings-apply", {}, "cockpit setup apply"), { disabled: busy || d.apply.running, title: "cockpit setup apply: creates the lanes the seats ask for (about a minute)" })
      ) : null,
      d.apply.running ? h("span", { style: sub }, "cockpit setup apply running\u2026") : null
    ),
    d.apply.log ? h("details", null, h("summary", { className: "cursor-pointer", style: sub }, `last apply${d.apply.rc != null ? ` (exit ${d.apply.rc})` : ""}`), h("pre", { className: "whitespace-pre-wrap", style: mono }, d.apply.log)) : null,
    h("div", { style: sub }, `Stored in ${d.path || "hermes/watch/settings.json"}. A seat taken away keeps its profile; nothing gives it cards.`),
    h(PluginUpdate)
  );
}

// src/views/advisories.js
import { useState as useState12 } from "react";

// src/views/live.js
import { useState as useState11, useEffect as useEffect7 } from "react";
var clockOf = (ts2, digits = 8) => {
  const text = String(ts2 || "");
  const d = new Date(text);
  if (Number.isNaN(d.getTime()) || !/(Z|[+-]\d\d:?\d\d)$/i.test(text)) return text.slice(11, 11 + digits);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":").slice(0, digits);
};
var LIVE_COLS = "1rem 5.5rem 1fr 4rem";
var ENTRY_COLOR = { prompt: "var(--ui-accent)", text: "var(--ui-text-primary, inherit)", tool_use: "var(--ui-text-secondary)", tool_result: "var(--ui-text-tertiary)", thinking: "var(--ui-text-quaternary)", result: "var(--ui-success, #2a9d5c)", system: "var(--ui-text-quaternary)" };
var errText = (e) => String(e && (e.detail || e.message) || e || "request failed").slice(0, 300);
var StreamError = ({ err }) => err ? h("span", { className: "truncate", style: { color: "var(--ui-danger, #d33)", maxWidth: "60%" }, title: err }, "\u26A0 backend error, retrying: " + err) : null;
function TranscriptEntry({ e, showThinking }) {
  const [open, setOpen] = useState11(false);
  if (e.kind === "thinking" && !showThinking) return null;
  const lane = e.src === "hermes" && e.who ? e.who + " " : "";
  const head = lane + (e.kind === "prompt" ? "\u203A prompt" : e.kind === "text" ? "\u25C6 " + (e.model ? e.model.replace(MODEL_PREFIX, "") : "says") : e.kind === "tool_use" ? "\u2699 " + (e.name || "tool") : e.kind === "tool_result" ? (e.error ? "\u2717 " : "\u21B3 ") + (e.name || "result") : e.kind === "result" ? "\u25A0 result" : e.kind === "thinking" ? "\u2234 thinking" : "\xB7 " + e.kind);
  const long = (e.text || "").length > 700 || e.kind === "tool_result" || e.kind === "tool_use";
  const rendered = (e.kind === "text" || e.kind === "prompt" || e.kind === "result") && e.html;
  const body = e.kind === "tool_use" ? open ? e.input : e.summary : long && !open ? (e.text || "").slice(0, e.kind === "tool_result" ? 240 : 700) + (e.text && e.text.length > 240 ? " [more]" : "") : e.text;
  const meta = e.kind === "result" ? h("div", { className: "text-[0.6875rem]", style: sub }, `${e.turns || "?"} turns${e.cost != null ? " \xB7 $" + Number(e.cost).toFixed(3) : ""}${e.duration ? " \xB7 " + Math.round(e.duration / 1e3) + "s" : ""}`) : null;
  return h(
    "div",
    { className: "grid gap-2 py-1 border-b", style: { gridTemplateColumns: "7.5rem 1fr", borderColor: "rgba(127,127,127,.12)", opacity: e.side ? 0.85 : 1 } },
    h("div", { className: "text-[0.6875rem] truncate", style: { color: ENTRY_COLOR[e.kind] || sub.color, paddingLeft: e.side ? ".75rem" : 0 }, title: (e.agent ? "subagent " + e.agent + " \xB7 " : "") + (e.ts || "") }, (e.side ? "\u21B3 " : "") + head, e.ts ? h("div", { style: { color: "var(--ui-text-quaternary)" } }, (e.ticket ? e.ticket + " \xB7 " : "") + clockOf(e.ts)) : null),
    rendered && (!long || open || e.kind !== "prompt") ? h("div", { className: "min-w-0" }, h(RichMd, { className: "rounded px-2", style: { background: e.kind === "prompt" ? "rgba(56,139,253,.08)" : "transparent", borderLeft: e.kind === "prompt" ? "2px solid var(--ui-accent)" : "none" }, html: e.html }), meta) : h("div", { className: "min-w-0" }, h("pre", { className: "whitespace-pre-wrap text-xs cursor-pointer rounded px-2", style: { ...mono, color: ENTRY_COLOR[e.kind] || "inherit", margin: 0, background: e.kind === "tool_result" ? "rgba(127,127,127,.06)" : "transparent" }, onClick: () => setOpen(!open), title: long ? "click to expand / collapse" : "" }, body), meta)
  );
}
function Transcript({ path }) {
  const [err, setErr] = useState11("");
  const [entries, setEntries] = useState11([]);
  const [off, setOff] = useState11(-1);
  const [running, setRunning] = useState11(false);
  const [follow, setFollow] = useState11(true);
  const [showThinking, setShowThinking] = useState11(false);
  const boxRef = { current: null };
  useEffect7(() => {
    setEntries([]);
    setOff(-1);
    setRunning(true);
  }, [path]);
  useEffect7(() => {
    let stop = false;
    let timer = null;
    const tick = async () => {
      try {
        const r = await CTX.rest(`/coding-tail?path=${encodeURIComponent(path)}&offset=${off}`);
        if (stop) return;
        setErr("");
        if (r.entries.length) setEntries((xs) => [...xs, ...r.entries].slice(-2500));
        setOff(r.offset);
        setRunning(r.running);
        timer = setTimeout(tick, r.running ? 2e3 : 8e3);
      } catch (e) {
        if (!stop) {
          setErr(errText(e));
          timer = setTimeout(tick, 8e3);
        }
      }
    };
    tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [path, off]);
  useEffect7(() => {
    if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  });
  return h(
    "div",
    { className: "flex h-full flex-col gap-1" },
    h(
      "div",
      { className: "flex items-center gap-2 text-xs" },
      h("span", { style: { color: running ? "var(--ui-success, #2a9d5c)" : sub.color } }, running ? "\u25CF live" : "\u25CB finished"),
      h(StreamError, { err }),
      h("span", { style: sub }, `${entries.length} entries`),
      h("label", { className: "ml-auto flex items-center gap-1 cursor-pointer", style: sub }, h("input", { type: "checkbox", checked: follow, onChange: (e) => setFollow(e.target.checked) }), "follow"),
      h("label", { className: "flex items-center gap-1 cursor-pointer", style: sub }, h("input", { type: "checkbox", checked: showThinking, onChange: (e) => setShowThinking(e.target.checked) }), "thinking"),
      btn("Reveal", () => CTX.os.revealPath(path))
    ),
    h(
      "div",
      { ref: (el) => {
        boxRef.current = el;
      }, className: "flex-1 overflow-auto rounded border px-2", style: { borderColor: stroke, minHeight: 0 }, onScroll: (e) => {
        const el = e.target;
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        if (!atBottom && follow) setFollow(false);
      } },
      ...entries.map((e, i) => h(TranscriptEntry, { key: i, e, showThinking })),
      !entries.length ? h("div", { className: "p-3 text-xs", style: sub }, "waiting for the first lines") : null
    )
  );
}
function LaneStream({ card }) {
  const [err, setErr] = useState11("");
  const [entries, setEntries] = useState11([]);
  const [last, setLast] = useState11("");
  const [running, setRunning] = useState11(false);
  const [follow, setFollow] = useState11(true);
  const boxRef = { current: null };
  useEffect7(() => {
    setEntries([]);
    setLast("");
  }, [card]);
  useEffect7(() => {
    let stop = false;
    let timer = null;
    const tick = async () => {
      try {
        const r = await CTX.rest(`/lane-stream?card=${encodeURIComponent(card)}&since=${encodeURIComponent(last)}`);
        if (stop) return;
        setErr("");
        if (r.entries.length) {
          setEntries((xs) => [...xs, ...r.entries].slice(-1500));
          setLast(r.last || last);
        }
        setRunning(r.running);
        timer = setTimeout(tick, r.running ? 2500 : 1e4);
      } catch (e) {
        if (!stop) {
          setErr(errText(e));
          timer = setTimeout(tick, 1e4);
        }
      }
    };
    tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [card, last]);
  useEffect7(() => {
    if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  });
  return h(
    "div",
    { className: "flex h-full flex-col gap-1" },
    h(
      "div",
      { className: "flex items-center gap-2 text-xs" },
      h("span", { style: { color: running ? "var(--ui-success, #2a9d5c)" : sub.color } }, running ? "\u25CF live" : "\u25CB finished"),
      h(StreamError, { err }),
      h("span", { style: sub }, `${entries.length} entries`),
      h(
        "label",
        { className: "ml-auto flex items-center gap-1 cursor-pointer", style: sub },
        h("input", { type: "checkbox", checked: follow, onChange: (e) => setFollow(e.target.checked) }),
        "follow"
      )
    ),
    h(
      "div",
      { ref: (el) => {
        boxRef.current = el;
      }, className: "flex-1 overflow-auto rounded border px-2", style: { borderColor: stroke, minHeight: 0 }, onScroll: (e) => {
        const el = e.target;
        if (el.scrollHeight - el.scrollTop - el.clientHeight > 40 && follow) setFollow(false);
      } },
      ...entries.map((e, i) => h(TranscriptEntry, { key: i, e, showThinking: false })),
      !entries.length ? h("div", { className: "p-3 text-xs", style: sub }, "no conversation recorded for this card yet") : null
    )
  );
}
function LaneLog({ path }) {
  const [err, setErr] = useState11("");
  const [text, setText] = useState11("");
  const [off, setOff] = useState11(-1);
  const [running, setRunning] = useState11(true);
  const [follow, setFollow] = useState11(true);
  const boxRef = { current: null };
  useEffect7(() => {
    setText("");
    setOff(-1);
    setRunning(true);
  }, [path]);
  useEffect7(() => {
    let stop = false;
    let timer = null;
    const tick = async () => {
      try {
        const r = await CTX.rest(`/lane-tail?path=${encodeURIComponent(path)}&offset=${off}`);
        if (stop) return;
        setErr("");
        if (r.text) setText((t) => (t + r.text).slice(-4e5));
        setOff(r.offset);
        setRunning(r.running);
        timer = setTimeout(tick, r.running ? 2e3 : 8e3);
      } catch (e) {
        if (!stop) {
          setErr(errText(e));
          timer = setTimeout(tick, 8e3);
        }
      }
    };
    tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [path, off]);
  useEffect7(() => {
    if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  });
  return h(
    "div",
    { className: "flex h-full flex-col gap-1" },
    h(
      "div",
      { className: "flex items-center gap-2 text-xs" },
      h("span", { style: { color: running ? "var(--ui-success, #2a9d5c)" : sub.color } }, running ? "\u25CF live" : "\u25CB finished"),
      h(StreamError, { err }),
      h(
        "label",
        { className: "ml-auto flex items-center gap-1 cursor-pointer", style: sub },
        h("input", { type: "checkbox", checked: follow, onChange: (e) => setFollow(e.target.checked) }),
        "follow"
      ),
      btn("Reveal", () => CTX.os.revealPath(path))
    ),
    h("pre", { ref: (el) => {
      boxRef.current = el;
    }, className: "flex-1 overflow-auto whitespace-pre-wrap rounded border p-2 text-xs", style: { ...mono, borderColor: stroke, minHeight: 0 }, onScroll: (e) => {
      const el = e.target;
      if (el.scrollHeight - el.scrollTop - el.clientHeight > 40 && follow) setFollow(false);
    } }, text || "waiting")
  );
}
var perLane = (entries, n) => {
  const seen = {};
  const kept = [];
  for (let i = entries.length - 1; i >= 0; i--) {
    const w = entries[i].who || "";
    seen[w] = (seen[w] || 0) + 1;
    if (seen[w] <= n) kept.push(entries[i]);
  }
  return kept.reverse();
};
function JobStream({ ticket }) {
  const [err, setErr] = useState11("");
  const [entries, setEntries] = useState11([]);
  const [last, setLast] = useState11("");
  const [running, setRunning] = useState11(false);
  const [follow, setFollow] = useState11(true);
  const [who, setWho] = useState11("all");
  const [offered, setOffered] = useState11([]);
  const [seats, setSeats] = useState11(null);
  const boxRef = { current: null };
  useEffect7(() => {
    setEntries([]);
    setLast("");
    setOffered([]);
  }, [ticket]);
  useEffect7(() => {
    let stop = false;
    let timer = null;
    const tick = async () => {
      try {
        const r = await CTX.rest(`/job-stream?ticket=${encodeURIComponent(ticket)}&since=${encodeURIComponent(last)}`);
        if (stop) return;
        setErr("");
        if (r.entries.length) {
          setEntries((xs) => perLane([...xs, ...r.entries], r.per_lane || 300));
          setLast(r.last || last);
        }
        if (r.lanes) setOffered(r.lanes);
        if (r.lane_order) setSeats(r.lane_order);
        setRunning(r.running);
        timer = setTimeout(tick, r.running ? 3e3 : 1e4);
      } catch (e) {
        if (!stop) {
          setErr(errText(e));
          timer = setTimeout(tick, 1e4);
        }
      }
    };
    tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [ticket, last]);
  useEffect7(() => {
    if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  });
  const lanes = sortLanes([...new Set([...offered, ...entries.map((e) => e.who)].filter(Boolean))], seats);
  const shown = entries.filter((e) => who === "all" || e.who === who);
  const kindColor = (e) => e.src === "board" ? e.kind === "blocked" || e.kind === "gave_up" || e.kind === "protocol_violation" ? "var(--ui-danger, #d33)" : e.kind === "completed" || e.kind === "review_requested" ? "var(--ui-success, #2a9d5c)" : "var(--ui-text-secondary)" : ENTRY_COLOR[e.kind] || sub.color;
  return h(
    "div",
    { className: "flex h-full flex-col gap-1" },
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2 text-xs" },
      h("span", { style: { color: running ? "var(--ui-success, #2a9d5c)" : sub.color } }, running ? "\u25CF a lane is working" : "\u25CB idle"),
      h(StreamError, { err }),
      h("span", { style: sub }, `${shown.length} events`),
      h("div", { className: "flex items-center gap-1 rounded border p-0.5", style: { borderColor: stroke } }, seg(who, "all", "all lanes", setWho), ...lanes.map((l) => seg(who, l, l, setWho))),
      h("label", { className: "ml-auto flex items-center gap-1 cursor-pointer", style: sub }, h("input", { type: "checkbox", checked: follow, onChange: (e) => setFollow(e.target.checked) }), "follow")
    ),
    h(
      "div",
      { ref: (el) => {
        boxRef.current = el;
      }, className: "flex-1 overflow-auto rounded border px-2", style: { borderColor: stroke, minHeight: 0 }, onScroll: (e) => {
        const el = e.target;
        if (el.scrollHeight - el.scrollTop - el.clientHeight > 40 && follow) setFollow(false);
      } },
      ...shown.map((e, i) => e.src !== "board" ? h(TranscriptEntry, { key: i, e, showThinking: false }) : h(
        "div",
        { key: i, className: "grid gap-2 py-1 border-b", style: { gridTemplateColumns: "7.5rem 1fr", borderColor: "rgba(127,127,127,.12)" } },
        h("div", { className: "text-[0.6875rem]", style: { color: kindColor(e) }, title: e.card }, `\u25A3 ${e.who || "board"}`, h("div", { style: { color: "var(--ui-text-quaternary)" } }, (e.ticket ? e.ticket + " \xB7 " : "") + clockOf(e.ts))),
        h("div", { className: "min-w-0 text-xs" }, h("span", { style: { color: kindColor(e) } }, e.kind.replace(/_/g, " ")), h("span", { style: sub }, ` \xB7 ${e.title}`), e.html ? h(RichMd, { className: "rounded px-2", html: e.html }) : null)
      )),
      !shown.length ? h("div", { className: "p-3 text-xs", style: sub }, "nothing yet for this job") : null
    )
  );
}
function Live() {
  const [sub2, setSub2] = useState11("all");
  const [scope, setScope] = useState11("pipeline");
  const jobs = useQuery({ queryKey: ["cockpit", "jobs"], queryFn: () => CTX.rest("/jobs"), refetchInterval: 1e4, retry: 1 });
  const lanes = useQuery({ queryKey: ["cockpit", "lane-runs"], queryFn: () => CTX.rest("/lane-runs"), refetchInterval: 5e3, retry: 1, enabled: sub2 === "hermes" });
  const cc = useQuery({ queryKey: ["cockpit", "coding-sessions", scope], queryFn: () => CTX.rest("/coding-sessions?scope=" + scope), refetchInterval: 5e3, retry: 1, enabled: sub2 === "coding" });
  const [job, setJob] = useState11("all");
  const [sel, setSel] = useState11(null);
  const jobList = jobs.data && jobs.data.jobs || [];
  const activeJob = job;
  const dot = (on) => h("span", { style: { color: on ? "var(--ui-success, #2a9d5c)" : "var(--ui-text-quaternary)" } }, on ? "\u25CF" : "\u25CB");
  const whenOf = (mtime) => {
    const n = Number(mtime);
    if (!Number.isFinite(n) || n <= 0) return "";
    const d = new Date(n * 1e3);
    if (Number.isNaN(d.getTime())) return "";
    return ago(d.toISOString());
  };
  const row = (key, on, who, what, when, item) => trow(
    LIVE_COLS,
    {
      key,
      onClick: () => setSel(sel && sel.path === item.path ? null : item),
      selected: sel && sel.path === item.path,
      children: [
        h("div", { key: "d" }, dot(on)),
        h("div", { key: "w", className: "truncate", style: mono }, who),
        h("div", { key: "t", className: "truncate", title: what }, what),
        h("div", { key: "a", className: "text-right truncate", style: sub }, when)
      ]
    }
  );
  const bar = h(
    "div",
    { className: "flex items-center gap-3 px-3 py-1.5 border-b text-xs", style: { borderColor: stroke } },
    h("div", { className: "flex items-center gap-1 rounded border p-0.5", style: { borderColor: stroke } }, seg(sub2, "all", "All (one job, every lane)", setSub2), seg(sub2, "hermes", "Hermes (lane runs)", setSub2), seg(sub2, "coding", "coding tool (transcripts)", setSub2)),
    sub2 === "all" ? h("div", { className: "flex items-center gap-1" }, h("span", { style: sub }, "job:"), selectBox(activeJob || "all", setJob, [["all", `all jobs (${jobList.length})`], ...jobList.map((j) => [j.ticket, `${j.ticket} \xB7 ${ago(j.last)} ago`])], { style: mono })) : null,
    sub2 === "coding" ? h("div", { className: "ml-auto flex items-center gap-1 rounded border p-0.5", style: { borderColor: stroke } }, seg(scope, "pipeline", "pipeline", setScope), seg(scope, "all", "all sessions", setScope)) : null
  );
  if (sub2 === "all") return h("div", { className: "flex min-h-0 flex-1 flex-col" }, bar, jobList.length || activeJob !== "all" ? h("div", { className: "min-h-0 flex-1 p-3" }, h(JobStream, { ticket: activeJob })) : h("div", { className: "p-6 text-center text-xs", style: sub }, "No job on the board yet. Kick one off from the Inbox."));
  const laneRows = lanes.data && lanes.data.runs || [];
  const ccRows = cc.data && cc.data.sessions || [];
  const list = sub2 === "hermes" ? h(
    "div",
    { className: "cockpit-scroll flex min-w-0 flex-col overflow-auto", style: { flex: sel ? "0 0 40%" : "1 1 auto", borderRight: sel ? `1px solid ${stroke}` : "none" } },
    thead(LIVE_COLS, ["", "lane", "card (run log)", ">age"]),
    ...laneRows.map((r) => row("l" + (r.card || r.lane || ""), r.running, r.assignee || r.lane || "?", `${r.title || r.card || ""} \xB7 ${r.status || ""}`, whenOf(r.mtime), { kind: "lane", path: r.path || "", card: r.card || "", label: r.title || r.card || "", transcript: r.transcript || "" })),
    !laneRows.length ? h("div", { className: "p-3 text-xs", style: sub }, "no lane runs yet") : null
  ) : h(
    "div",
    { className: "cockpit-scroll flex min-w-0 flex-col overflow-auto", style: { flex: sel ? "0 0 40%" : "1 1 auto", borderRight: sel ? `1px solid ${stroke}` : "none" } },
    thead(LIVE_COLS, ["", "ticket", "session (first prompt)", ">age"]),
    ...ccRows.flatMap((s) => [
      row("c" + s.id, s.running, s.ticket || (s.dir || "").split("-").slice(-2).join("-"), (s.prompt || "(no prompt yet)").replace(/\s+/g, " "), whenOf(s.mtime), { kind: "coding", path: s.path, label: s.id, ticket: s.ticket || "", session: s.id }),
      ...(s.subagents || []).map((a) => trow(LIVE_COLS, {
        key: "a" + a.name,
        onClick: () => setSel(sel && sel.path === a.path ? null : { kind: "coding", path: a.path, label: a.name }),
        selected: sel && sel.path === a.path,
        children: [
          h("div", { key: "d" }, ""),
          h("div", { key: "w", style: { ...mono, ...sub } }, "\u21B3 advisor"),
          h("div", { key: "t", className: "truncate", style: sub }, a.name),
          h("div", { key: "a", className: "text-right", style: sub }, whenOf(a.mtime))
        ]
      }))
    ]),
    !ccRows.length ? h("div", { className: "p-3 text-xs", style: sub }, scope === "pipeline" ? "No coding tool sessions in the worktrees yet (worker runs persist them from now on)." : "No sessions.") : null
  );
  return h("div", { className: "flex min-h-0 flex-1 flex-col" }, bar, h(
    "div",
    { className: "flex min-h-0 flex-1" },
    list,
    sel ? h(Pane, { onClose: () => setSel(null) }, h(LaneDetail, { sel })) : null
  ));
}
function LaneDetail({ sel }) {
  const [raw, setRaw] = useState11(null);
  useEffect7(() => setRaw(null), [sel.card]);
  const mode = raw === "transcript" || raw === null && sel.transcript ? "transcript" : raw === true ? "raw" : "conv";
  if (sel.kind !== "lane") return h(
    "div",
    { className: "min-w-0 flex-1 flex flex-col gap-2 p-3", style: { minHeight: 0 } },
    detailHead(sel.label, null, "coding tool transcript"),
    sel.ticket && sel.session ? h("div", { className: "flex items-center gap-2 text-xs" }, h(ChatButton, { ticket: sel.ticket, from: sel.session }), h("span", { style: sub }, "an interactive coding tool with this run's context; one chat per ticket, kept until the flow ends")) : null,
    h(Transcript, { path: sel.path })
  );
  return h(
    "div",
    { className: "min-w-0 flex-1 flex flex-col gap-2 p-3", style: { minHeight: 0 } },
    h(
      "div",
      { className: "flex items-baseline gap-2" },
      h("div", { className: "font-medium text-sm" }, sel.label),
      h(
        "div",
        { className: "ml-auto flex items-center gap-1 rounded border p-0.5", style: { borderColor: stroke } },
        sel.transcript ? seg(mode, "transcript", "agent session", () => setRaw("transcript")) : null,
        seg(mode, "conv", "conversation", () => setRaw(false)),
        seg(mode, "raw", "raw run log", () => setRaw(true))
      )
    ),
    mode === "transcript" ? h(Transcript, { path: sel.transcript }) : mode === "raw" ? h(LaneLog, { path: sel.path }) : h(LaneStream, { card: sel.card })
  );
}

// src/views/advisories.js
var DANGER = "var(--ui-danger, #d33)";
var WARN2 = "var(--ui-warning, #c98a00)";
var ACCENT = "var(--ui-accent)";
var QUIET = "var(--ui-text-tertiary)";
var severityColor = (a) => a.severity === "critical" || a.exploited ? DANGER : a.severity === "high" ? WARN2 : a.severity === "medium" ? ACCENT : QUIET;
var prodHits = (a) => (a.hits || []).filter((x) => x.production);
var hitNames = (a, n = 3) => {
  const hs = [...prodHits(a), ...(a.hits || []).filter((x) => !x.production)].slice(0, n).map((x) => `${x.name}${x.version ? " " + x.version : ""}`);
  const rest = (a.hits || []).length - hs.length;
  return hs.join(", ") + (rest > 0 ? ` +${rest}` : "");
};
var fixText = (a) => {
  const f = a.fix || {};
  return f.time ? `fix ${ago(f.time)} ago` : f.versions && f.versions.length ? `fixed in ${f.versions.join(", ")}` : "";
};
var fixLine = (a) => {
  const f = a.fix || {};
  return f.time ? `fix expected ${String(f.time).replace("T", " ").slice(0, 16)}${f.versions && f.versions.length ? " \xB7 " + f.versions.join(", ") : ""}` : f.versions && f.versions.length ? `fixed in ${f.versions.join(", ")}` : "no fix known yet";
};
var alertable = (a) => Boolean(a && a.alert && !a.acknowledged);
var advisoryWhat = (a) => {
  const fx = fixText(a);
  return `${a.severity || "unknown"} ${a.exploited ? "exploited " : ""}advisory: ${a.title || a.id} \u2014 hits ${hitNames({ ...a, hits: prodHits(a) }, 3) || "none in production"}${fx ? " \xB7 " + fx : ""}`;
};
var sourcesHealth = (sources) => Object.entries(sources || {}).map(([n, s]) => s && s.ok ? `${n} ok ${s.checked ? clockOf(s.checked, 5) : ""}`.trim() : `${n} failed: ${s && s.error || "no answer"}`).join(" \xB7 ");
var bumpPill = (p) => h("button", {
  key: `${p.repo}#${p.number}`,
  type: "button",
  title: `${p.repo}#${p.number} \xB7 ${p.title || ""}${p.covers && p.covers.length ? " \xB7 " + p.covers.join(", ") : ""}`,
  onClick: (e) => {
    e.stopPropagation();
    if (p.url) openWeb(p.url);
  },
  className: "rounded px-1 text-[0.6875rem] whitespace-nowrap",
  style: { border: `1px solid ${ACCENT}`, color: ACCENT, background: "rgba(56,139,253,.08)" }
}, `\u{1F916} #${p.number}`);
function AdvisoryRow({ a, selected, onClick }) {
  const color = severityColor(a);
  return h(
    "div",
    { onClick, "data-advisory": a.id, className: "flex items-center gap-2 px-3 py-0.5 border-b text-xs cursor-pointer", style: { borderColor: stroke, background: selected ? "rgba(56,139,253,.10)" : void 0 } },
    h("span", { className: "rounded px-1 text-[0.6875rem] font-medium whitespace-nowrap", style: { border: `1px solid ${color}`, color } }, a.severity || "unknown"),
    a.exploited ? h("span", { title: "exploited in the wild" }, "\u26A1") : null,
    h("span", { className: "whitespace-nowrap", style: sub }, a.status || "candidate"),
    h("span", { className: "truncate", title: a.title || "" }, h("span", { style: mono }, a.id), " ", a.title || ""),
    h("span", { className: "truncate", style: sub, title: hitNames(a, 12) }, hitNames({ ...a, hits: prodHits(a) }, 2) || "no production hit"),
    ...(a.bump_prs || []).map(bumpPill),
    a.acknowledged ? h("span", { className: "whitespace-nowrap", style: sub, title: a.acknowledged.note || "" }, "ack") : null,
    h("span", { className: "ml-auto whitespace-nowrap", style: sub }, a.last_seen ? ago(a.last_seen) + " ago" : "")
  );
}
function AdvisoryPanel({ a, onDone }) {
  const [note, setNote] = useState12("");
  const [busy, setBusy] = useState12(false);
  const act = async (path, body, msg) => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await post(path, body);
      host.notify({ kind: "success", title: msg, message: r.out });
      onDone();
    } catch (e) {
      host.notifyError(e, "failed");
    } finally {
      setBusy(false);
    }
  };
  const color = severityColor(a);
  const hits = a.hits || [];
  const head = `${a.severity || "unknown"}${a.cvss != null ? " \xB7 cvss " + a.cvss : ""}${a.exploited ? " \xB7 exploited in the wild" : ""}${a.trust === "low" ? " \xB7 low trust" : ""}${a.last_seen ? " \xB7 seen " + ago(a.last_seen) + " ago" : ""}`;
  const cols = { gridTemplateColumns: "1fr 7rem 9rem 1fr 7rem" };
  return h(
    "div",
    { className: "flex flex-col gap-2 p-3 text-xs" },
    detailHead(a.id, { text: a.status || "candidate", color }, head),
    h("div", { className: "font-medium" }, a.title || ""),
    a.summary ? h("div", { className: "whitespace-pre-wrap" }, a.summary) : h("div", { style: sub }, "(no summary)"),
    h(
      "div",
      { className: "overflow-auto rounded border", style: { borderColor: stroke } },
      h("div", { className: "cockpit-head grid gap-2 px-2 py-1 border-b", style: { ...cols, borderColor: stroke } }, h("span", null, "component"), h("span", null, "version"), h("span", null, "repo"), h("span", null, "where"), h("span", null, "fixed in")),
      ...hits.length ? hits.map((x, i) => h(
        "div",
        { key: i, className: "grid gap-2 px-2 py-0.5 items-center", style: { ...cols, opacity: x.production ? 1 : 0.7 } },
        h("span", { className: "truncate", title: `${x.kind || ""} ${x.ecosystem || ""}`.trim() }, x.production ? h("span", { className: "font-medium" }, x.name) : x.name, h("span", { style: sub }, x.production ? " \xB7 production" : " \xB7 dev")),
        h("span", { style: mono }, x.version || "\u2013", x.version_checked === false ? h("span", { style: sub, title: "matched by name: the version could not be checked" }, " ?") : null),
        h("span", { className: "truncate", style: mono }, x.repo || ""),
        h("span", { className: "truncate", style: sub, title: x.where || "" }, x.where || ""),
        h("span", { style: mono }, x.fixed_in || "\u2013")
      )) : [h("div", { key: "none", className: "px-2 py-1", style: sub }, "no component of the stack matched (a name-only candidate)")]
    ),
    h("div", null, h("span", { style: sub }, "fix: "), fixLine(a)),
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2" },
      h("span", { style: sub }, "sources: "),
      (a.via || [a.source]).filter(Boolean).join(", "),
      ...Array.isArray(a.sources) ? a.sources.filter((s) => s && s.url).map((s) => h("a", { key: s.url, href: s.url, title: s.url, onClick: (e) => {
        e.preventDefault();
        openWeb(s.url);
      }, style: { color: ACCENT } }, s.name || s.url)) : [],
      a.url ? h("a", { href: a.url, onClick: (e) => {
        e.preventDefault();
        openWeb(a.url);
      }, style: { color: ACCENT } }, "open the advisory") : null
    ),
    a.bump_prs && a.bump_prs.length ? h("div", { className: "flex flex-wrap items-center gap-1" }, h("span", { style: sub }, "bump PR(s) in flight: "), ...a.bump_prs.map(bumpPill)) : null,
    a.acknowledged ? h(
      "div",
      { className: "flex flex-col gap-1 rounded border p-2", style: { borderColor: stroke } },
      h("div", null, h("span", { style: sub }, `acknowledged ${a.acknowledged.time ? ago(a.acknowledged.time) + " ago" : ""}: `), a.acknowledged.note || "(no note)"),
      h("div", null, btn("Unacknowledge", () => act("/advisory-unack", { id: a.id }, `${a.id}: unacknowledged`), { disabled: busy, title: "an alert comes back to the Inbox" }))
    ) : h(
      "div",
      { className: "flex flex-col gap-1" },
      h(ClearableTextarea, { value: note, onChange: (e) => setNote(e.target.value), rows: 2, placeholder: "why this is fine, or what was done (kept with the advisory)", className: "rounded border bg-transparent px-1.5 py-1 text-xs", style: { borderColor: stroke } }),
      h(
        "div",
        { className: "flex items-center gap-2" },
        btn(busy ? "working" : "Acknowledge", () => act("/advisory-ack", { id: a.id, note }, `${a.id} acknowledged`), { accent: true, disabled: busy, title: "the row leaves the Inbox; the Platform tab keeps it with your note" }),
        h(
          "button",
          {
            type: "button",
            disabled: busy,
            onClick: () => act("/advisory-card", { id: a.id }, `${a.id}: analyst card made`),
            className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40",
            style: { background: ACCENT, color: "#fff" },
            title: "an analyst assesses it: reachable in the stack, on production, the fix; the verdict lands as a card comment"
          },
          busy ? "working" : "Make an analyst card"
        ),
        h("span", { style: sub }, "One card per advisory while it is open.")
      )
    )
  );
}
function AdvisoriesTab({ data, onDone }) {
  const [sel, setSel] = useState12(null);
  const advs = data && data.advisories || [];
  const picked = sel ? advs.find((a) => a.id === sel) : null;
  const comps = Object.entries((data && data.manifest || {}).components || {}).map(([k, n]) => `${n} ${k}`).join(" \xB7 ");
  return h(
    "div",
    { className: "flex min-h-0 flex-1" },
    h(
      "div",
      { className: "flex min-w-0 flex-1 flex-col overflow-auto" },
      h("div", { className: "px-3 py-1 text-xs border-b", style: { ...sub, borderColor: stroke } }, `${advs.length} advisor${advs.length === 1 ? "y" : "ies"} \xB7 ${data && data.time ? "scanned " + ago(data.time) + " ago" : "never scanned"} \xB7 stack: ${comps || "no manifest yet"} \xB7 ${sourcesHealth(data && data.sources) || "no source has run"}`),
      ...advs.length ? advs.map((a) => h(AdvisoryRow, { key: a.id, a, selected: sel === a.id, onClick: () => setSel(sel === a.id ? null : a.id) })) : [h("div", { key: "none", className: "p-3 text-xs", style: sub }, "no advisory touches the stack")]
    ),
    picked ? h("div", { className: "overflow-auto", style: { width: "34rem", borderLeft: `1px solid ${stroke}` } }, h(AdvisoryPanel, { a: picked, onDone: () => {
      setSel(null);
      onDone && onDone();
    } })) : null
  );
}

// src/views/inbox.js
function FileButtons({ files }) {
  const [file, setFile] = useState13(null);
  const media = files.filter((f) => f.kind === "image" || f.kind === "video" || f.kind === "pdf");
  const rest = files.filter((f) => !(f.kind === "image" || f.kind === "video" || f.kind === "pdf"));
  const fileBtn = (f) => h("button", {
    key: f.path,
    type: "button",
    onClick: () => setFile(file && file.path === f.path ? null : f),
    title: `${f.rel} \xB7 ${fmtSize(f.size || 0)}`,
    className: "rounded border px-1 text-[0.6875rem]",
    style: { borderColor: file && file.path === f.path ? "var(--ui-accent)" : stroke, color: f.kind === "image" ? "var(--ui-accent)" : f.kind === "video" ? "var(--ui-success, #2a9d5c)" : "var(--ui-text-secondary)" }
  }, (f.kind === "image" ? "\u{1F5BC} " : f.kind === "video" ? "\u25B6 " : f.kind === "pdf" ? "\u{1F4C4} " : "") + f.rel.split("/").pop());
  return h("div", { className: "flex flex-col gap-1" }, h("div", { className: "flex flex-wrap gap-1" }, ...media.map(fileBtn), ...rest.map(fileBtn)), file ? h(Viewer, { file, onClose: () => setFile(null) }) : null);
}
function CardView({ c }) {
  const a = c.attachments || { docs: [], dirs: [], files: [], brief: null };
  const docs = a.docs || [];
  const dirs = a.dirs || [];
  const files = a.files || [];
  const comments = c.comments || [];
  const events = c.events || [];
  return h(
    "div",
    { className: "flex flex-col gap-2 text-xs" },
    h("div", { className: "flex flex-wrap items-center gap-2" }, (c.prs || []).length ? h("span", { className: "flex items-center gap-2" }, h("span", { style: sub }, "PRs:"), prList(c.prs)) : null),
    h("div", { className: "flex flex-wrap gap-2", style: sub }, h("span", null, c.status), h("span", null, c.assignee), c.created ? h("span", null, "created " + ago(c.created) + " ago") : null, c.skills ? h("span", null, "skills " + (Array.isArray(c.skills) ? c.skills.join(", ") : c.skills)) : null, c.workspace ? h("span", { style: mono }, c.workspace) : null),
    // the only section open by default: issue · fix · ruled out · changes, in platform words
    h(TicketTools, { ticket: ticketOf(c.title), card: c.id, part: "chat" }),
    h(Section, { title: "Brief", open: true, color: "var(--ui-accent)" }, a.brief ? h(RichMd, { html: a.brief }) : h("div", { style: sub }, "no Brief on this card yet (the plan format asks the lane for one: issue \xB7 fix \xB7 ruled out \xB7 changes)")),
    h(TicketTools, { ticket: ticketOf(c.title), card: c.id, part: "demo" }),
    // a card that works in a ticket worktree: the patch to review, uncommitted changes included, and the IDE on it
    c.worktree ? h(Section, { title: `Diff \xB7 ${c.worktree.repo} worktree (vs origin, the uncommitted patch included)`, extra: btn("Open IDE", () => openIde({ ticket: c.worktree.ticket }), { title: "VS Code on the ticket workspace" }) }, h(DiffPanel, { params: { ticket: c.worktree.ticket, repo: c.worktree.repo }, defaultMode: "origin" })) : null,
    ...docs.map((d) => h(Section, { key: d.path, title: `Plan \xB7 ${(d.rel || "").split("/").slice(-2).join("/")}`, extra: btn("Open", () => openFile(d.path)) }, h(RichMd, { html: d.html }))),
    ...dirs.map((d) => h(Section, { key: d.path, title: `Evidence \xB7 ${(d.rel || "").split("/").slice(-2).join("/")} (${(d.files || []).length} files)`, extra: btn("Reveal", () => CTX.os.revealPath(d.path)) }, h(FileButtons, { files: d.files || [] }))),
    files.length ? h(Section, { title: `Files (${files.length})` }, h(FileButtons, { files })) : null,
    h(Section, { title: "Card body" }, h(RichMd, { html: c.body_html })),
    c.result_html ? h(Section, { title: "Result", color: "var(--ui-success, #2a9d5c)" }, h(RichMd, { html: c.result_html })) : null,
    c.error ? h("div", { className: "rounded border px-2 py-1", style: { borderColor: "var(--ui-danger, #d33)", color: "var(--ui-danger, #d33)" } }, String(c.error).slice(0, 600)) : null,
    comments.length ? h(Section, { title: `Comments (${comments.length})` }, ...comments.map((m, i) => h("div", { key: i, className: "rounded border px-2.5 py-1.5", style: { borderColor: stroke } }, h("div", { style: sub }, `${m.author} \xB7 ${m.ts ? ago(m.ts) + " ago" : ""}`), h(RichMd, { className: "", html: m.html })))) : null,
    events.length ? h("div", { style: sub }, "events: " + events.map((e) => `${e.kind} ${ago(e.ts)}`).join(" \xB7 ")) : null
  );
}
var CRED = /^CREDENTIALS NEEDED\s*·\s*(\S+)\s*·\s*([^\s·]+)\s*(?:·\s*([\s\S]*))?$/;
var credentialAsk = (q2) => {
  const m = CRED.exec((q2 || "").trim());
  if (!m || !String(m[2]).includes("@")) return null;
  return { email: m[2], why: (m[3] || "").trim() };
};
function CredentialsForm({ c, ask, refresh }) {
  const [email, setEmail] = useState13(ask.email);
  const [pw, setPw] = useState13("");
  const [key, setKey] = useState13("");
  const [busy, setBusy] = useState13(false);
  const twoFactor = /^2FA\b/i.test(ask.why || "");
  const ok = Boolean(email.trim() && pw);
  const save = async () => {
    if (!ok || busy) return;
    setBusy(true);
    try {
      const r = await post("/staging-credentials", { id: c.id, email: email.trim(), password: pw, otp: key.replace(/\s+/g, "") || void 0 });
      host.notify({ kind: "success", title: `${c.ticket || c.id}: staging login stored`, message: r.out });
      refresh();
    } catch (e) {
      host.notifyError(e, "storing the login failed");
    } finally {
      setPw("");
      setKey("");
      setBusy(false);
    }
  };
  const field = (props) => h("input", { ...props, className: "w-full rounded border bg-transparent px-2 py-1 text-xs", style: { borderColor: stroke } });
  return h(
    "div",
    { className: "cockpit-creds mt-2 flex flex-col gap-2 rounded-md border px-3 py-2 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)", background: "rgba(201,138,0,.07)" } },
    h("div", { className: "cockpit-head", style: { color: "var(--ui-warning, #c98a00)" } }, "staging login needed"),
    ask.why ? h("div", null, ask.why) : null,
    h("label", { className: "flex flex-col gap-0.5" }, h("span", { style: sub }, "test account (email)"), field({ type: "email", value: email, onChange: (e) => setEmail(e.target.value), autoComplete: "off", spellCheck: false })),
    h("label", { className: "flex flex-col gap-0.5" }, h("span", { style: sub }, "password"), field({ type: "password", value: pw, onChange: (e) => setPw(e.target.value), autoComplete: "new-password", autoFocus: true, onKeyDown: (e) => {
      if (e.key === "Enter") save();
    } })),
    h(
      "label",
      { className: "flex flex-col gap-0.5" },
      h("span", { style: sub }, twoFactor ? "authenticator key (the 2FA secret, not a code)" : "authenticator key (optional: only for a login with 2FA)"),
      field({ type: "password", value: key, onChange: (e) => setKey(e.target.value), autoComplete: "off", spellCheck: false, autoFocus: twoFactor })
    ),
    h("div", { style: sub }, `Stored only in this lane's Hermes vault, bound to ${ask.origin || "the origin in the pack"}. The lane fills it without seeing it; it never reaches the board or a log. Use a staging test account only.`),
    h(
      "div",
      { className: "flex items-center gap-2" },
      h("button", { type: "button", disabled: !ok || busy, onClick: save, className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-accent)", color: "#fff" } }, busy ? "working" : "Save to vault & resume"),
      btn("Stop", async () => {
        try {
          await post("/answer", { id: c.id, text: "stop: no staging login; I will take it from here." });
          refresh();
        } catch (e) {
          host.notifyError(e, "stop failed");
        }
      }, { danger: true, title: "closes the card; nothing re-runs" })
    )
  );
}
function PackAskForm({ c, refresh }) {
  const ask = c.pack_ask;
  const [busy, setBusy] = useState13(false);
  const [reason, setReason] = useState13("");
  const act = async (fn, done) => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fn();
      host.notify({ kind: "success", title: `${c.ticket || c.id}: ${done}`, message: r.out });
      refresh();
    } catch (e) {
      host.notifyError(e, `${ask.name} failed`);
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "mt-2 flex flex-col gap-2 rounded-md border px-3 py-2 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)", background: "rgba(201,138,0,.07)" } },
    h("div", { className: "cockpit-head", style: { color: "var(--ui-warning, #c98a00)" } }, `${c.assignee || "the lane"} asks: ${ask.name}`),
    h("input", { value: reason, onChange: (e) => setReason(e.target.value), placeholder: "reason for a denial (optional)", className: "w-full rounded border bg-transparent px-2 py-1 text-xs", style: { borderColor: stroke } }),
    h(
      "div",
      { className: "flex items-center gap-2" },
      h("button", { type: "button", disabled: busy, onClick: () => act(() => post("/ask-approve", { id: c.id }), "approved"), className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-warning, #c98a00)", color: "#fff" } }, busy ? "working" : ask.label),
      btn("Deny", () => act(() => post("/answer", { id: c.id, text: ask.deny + (reason.trim() ? " \u2014 " + reason.trim() : "") }), "denied"), { disabled: busy })
    )
  );
}
var notReady = (c) => (c.not_ready || []).length > 0;
var onlyShots = (c) => notReady(c) && c.not_ready.every((r) => String(r).endsWith("\xB7screenshot"));
var rowsOf = (c) => c.not_ready.map((r) => String(r).replace(/·.*$/, ""));
var SEND_BACK_GRACE_S = 120;
var ROW_TONE = { info: "var(--ui-accent)", ok: "var(--ui-success, #2a9d5c)", warn: "var(--ui-warning, #c98a00)", danger: "var(--ui-danger, #d33)" };
function BlockedCard({ c, refresh }) {
  const [text, setText] = useState13("");
  const [busy, setBusy] = useState13(false);
  const cq = useQuery({ queryKey: ["cockpit", "card-detail", c.id], queryFn: () => CTX.rest("/card-detail?id=" + c.id), retry: 0 });
  const send = async (t) => {
    const msg = (t || text).trim();
    if (!msg || busy) return;
    setBusy(true);
    try {
      const r = await post("/answer", { id: c.id, text: msg });
      host.notify({ kind: "success", title: `${c.ticket || c.id} answered`, message: r.out });
      setText("");
      refresh();
    } catch (e) {
      host.notifyError(e, "answer failed");
    } finally {
      setBusy(false);
    }
  };
  const primary = (label, onClick, extra = {}) => h("button", { type: "button", disabled: busy || extra.disabled, onClick, title: extra.title || "", className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40", style: { background: extra.bg || "var(--ui-accent)", color: "#fff" } }, label);
  return h(
    "div",
    { className: "flex h-full min-h-0 flex-col" },
    // scrolling part: the question, then the card
    h(
      "div",
      { className: "min-h-0 flex-1 overflow-auto flex flex-col gap-3 pr-1" },
      c.question ? h(
        "div",
        { className: "rounded-md border px-3 py-2 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)", background: "rgba(201,138,0,.07)" } },
        h("div", { className: "cockpit-head mb-1", style: { color: "var(--ui-warning, #c98a00)" } }, `${c.assignee} asks`),
        // the short question when the backend found one; a backend without it sends the block reason as before
        c.ask_html ? h(RichMd, { html: c.ask_html, className: "leading-relaxed" }) : c.question_html ? h(RichMd, { html: c.question_html, className: "leading-relaxed" }) : h("div", { className: "whitespace-pre-wrap leading-relaxed" }, c.question)
      ) : null,
      // What the answer decides: the lane's report, open and rendered, right under its question — not folded into
      // the card's comments, where the reader had to go and find the plan they were approving.
      // the platform's card: a Section, open, the way the card view's Brief and Plan read
      c.report_html ? h(
        "div",
        { "data-report": "1", className: "text-xs" },
        h(Section, { title: `${c.assignee} reports`, open: true, color: "var(--ui-accent)" }, h(RichMd, { html: c.report_html, className: "leading-relaxed" }))
      ) : null,
      notReady(c) ? h(
        "div",
        { className: "rounded-md border px-3 py-2 text-xs", style: { borderColor: "var(--ui-danger, #d33)" } },
        h("div", { className: "cockpit-head mb-1", style: { color: "var(--ui-danger, #d33)" } }, "not ready for your review"),
        h("div", { className: "mb-2" }, c.not_ready.includes("(no results table)") ? "No results table was found for this run (a table with a Result column)." : onlyShots(c) ? `Rows ${rowsOf(c).join(", ")} passed but link no screenshot of the verified state (text evidence only).` : `Rows ${rowsOf(c).join(", ")} are still blocked, not run or waiting for your result, so the run is not finished.`),
        h(
          "div",
          { className: "flex flex-wrap items-center gap-2" },
          primary(
            onlyShots(c) ? "Send back: take the screenshots" : "Send back: finish those rows",
            () => send(onlyShots(c) ? `take the screenshots of rows ${rowsOf(c).join(", ")} first (a screenshot from your browser_exec session, copied to the run's evidence folder), then ask for the review again` : `finish rows ${rowsOf(c).join(", ")} first: a run with blocked or not-run rows is not finished, so it is not ready for review`),
            { bg: "var(--ui-danger, #d33)" }
          ),
          onlyShots(c) ? primary("go without screenshots", () => send("go without screenshots: the text evidence is accepted for this run"), { title: "accept this run as it is: the text evidence stands for these rows, the results post may follow", bg: "var(--ui-success, #2a9d5c)" }) : null
        )
      ) : null,
      h("div", { className: "rounded-md border px-3 py-2", style: { borderColor: stroke } }, h("div", { className: "cockpit-head mb-1" }, "the card"), cq.data ? h(CardView, { c: cq.data }) : h("div", { className: "text-xs", style: sub }, "loading the card"))
    ),
    // answer bar: pinned to the bottom of the pane (a staging login request gets the masked form instead)
    credentialAsk(c.question) ? h(CredentialsForm, { c, ask: credentialAsk(c.question), refresh }) : c.pack_ask && c.pack_ask.name ? h(PackAskForm, { c, refresh }) : h(
      "div",
      { className: "mt-2 flex flex-col gap-2 rounded-md border px-3 py-2", style: { borderColor: "var(--ui-accent)", background: "rgba(56,139,253,.06)" } },
      h("div", { className: "cockpit-head" }, "your answer"),
      h(ClearableTextarea, {
        value: text,
        onChange: (e) => setText(e.target.value),
        rows: 3,
        placeholder: "go \xB7 go with changes: <what to change> \xB7 the information the lane asked for \xB7 stop (closes the card)",
        className: "w-full rounded border bg-transparent px-2 py-1.5 text-xs",
        style: { borderColor: stroke, resize: "vertical" },
        onKeyDown: (e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
        }
      }),
      h(
        "div",
        { className: "flex items-center gap-2" },
        notReady(c) ? null : primary("go", () => send("go"), { title: "the plan is approved: start", bg: "var(--ui-success, #2a9d5c)" }),
        // an unfinished run cannot be accepted
        primary("stop", () => send("stop: do not continue; I will take it from here."), { title: "closes the card; nothing re-runs", bg: "var(--ui-danger, #d33)" }),
        btn("Archive card", async () => {
          try {
            await post("/card-archive", { id: c.id });
            host.notify({ kind: "info", message: `${c.id} archived` });
            refresh();
          } catch (e) {
            host.notifyError(e, "archive failed");
          }
        }, { title: "nothing left to do here: drop it from the board" }),
        h("span", { className: "ml-auto text-[0.6875rem]", style: sub }, "\u2318\u21B5"),
        primary(busy ? "working" : "Answer & resume", () => send(), { disabled: !text.trim() })
      )
    )
  );
}
function PrDiffPanel({ ticket, pr }) {
  const [mode, setMode] = useState13("since");
  const qs = `ticket=${encodeURIComponent(ticket)}&repo=${encodeURIComponent(pr.repo)}&number=${pr.number}&mode=${mode}`;
  const q2 = useQuery({ queryKey: ["cockpit", "pr-diff", qs], queryFn: () => CTX.rest("/pr-diff?" + qs), staleTime: 6e4, retry: 0 });
  const sr = pr.since_review || {};
  const toggle = h(
    "div",
    { className: "flex items-center gap-1 self-start rounded border p-0.5", style: { borderColor: stroke } },
    seg(mode, "since", `since your review (what the author pushed${sr.commits ? `, ${sr.commits} commit(s)` : ""})`, setMode),
    seg(mode, "full", `vs ${pr.base || "the base branch"} (what the whole PR changes)`, setMode)
  );
  if (q2.isLoading) return h("div", { className: "flex flex-col gap-2" }, toggle, h("div", { className: "text-xs", style: sub }, "reading the diff from the forge\u2026"));
  if (q2.error) return h("div", { className: "flex flex-col gap-2" }, toggle, h("div", { className: "text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error)));
  return h(
    "div",
    { className: "flex flex-col gap-2" },
    toggle,
    q2.data && q2.data.note ? h("div", { className: "rounded border px-2 py-1 text-xs", style: { borderColor: "var(--ui-warning, #c98a00)" } }, q2.data.note) : null,
    q2.data && mode === "since" && !(q2.data.commits || []).length && !(q2.data.diff || "").trim() ? h("div", { className: "text-xs", style: sub }, "Nothing pushed since your review: the head is still what you reviewed.") : null,
    q2.data ? h(DiffView, { data: q2.data }) : null
  );
}
var useTrackerWord = () => trackerWord((useQuery({ queryKey: ["cockpit", "repos"], queryFn: () => CTX.rest("/repos"), refetchInterval: POLL_MS * 6, retry: 0 }).data || {}).tracker_kind);
var useHints = () => hintsOf((useQuery({ queryKey: ["cockpit", "repos"], queryFn: () => CTX.rest("/repos"), refetchInterval: POLL_MS * 6, retry: 0 }).data || {}).hints);
function ReReviewPanel({ ticket, pr, onDone }) {
  const hints = useHints();
  const [note, setNote] = useState13("");
  const [busy, setBusy] = useState13(false);
  const [tab, setTab] = useState13("review");
  useEffect8(() => {
    setTab("review");
  }, [ticket, pr.repo, pr.number]);
  const mt = pr.my_threads || {};
  const sr = pr.since_review || {};
  const go = async () => {
    setBusy(true);
    try {
      const r = await post("/pr-rereview", { ticket, repo: pr.repo, number: pr.number, note });
      host.notify({ kind: "success", title: `${ticket} re-review started`, message: r.out });
      onDone();
    } catch (e) {
      host.notifyError(e, "re-review failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex flex-col gap-3 p-3 text-xs" },
    detailHead(`${ticket} \xB7 ${pr.repo} #${pr.number}`, { text: "you review \xB7 still open", color: "var(--ui-accent)" }, pr.my_review_state && pr.my_review_state !== "none" ? "your last review: " + pr.my_review_state.toLowerCase().replace("_", " ") : "no review submitted yet"),
    h("div", { className: "flex items-center gap-2" }, prButtons([pr])),
    h("div", { className: "flex items-center gap-1 self-start rounded border p-0.5", style: { borderColor: stroke } }, seg(tab, "review", "Review", setTab), seg(tab, "diff", "Diff (the PR since your review / vs the base branch)", setTab)),
    tab === "diff" ? h(PrDiffPanel, { ticket, pr }) : h(
      "div",
      { className: "flex flex-col gap-3" },
      h(TicketTools, { ticket, part: "chat" }),
      (() => {
        const quiet = pr.last_activity ? (Date.now() - toMs(pr.last_activity)) / 6e4 : null;
        const verdict = pr.re_requested ? [
          "The author re-requested your review: good time.",
          "var(--ui-success, #2a9d5c)"
        ] : mt.total && mt.resolved === mt.total ? [
          "All your threads are resolved: good time.",
          "var(--ui-success, #2a9d5c)"
        ] : quiet != null && quiet < 60 && (mt.replied || sr.commits) ? [
          "The author moved in the last hour: probably still patching.",
          "var(--ui-warning, #c98a00)"
        ] : ["No signal that the author is done; re-review when you want a look anyway.", "var(--ui-text-tertiary)"];
        return h(Section, { title: "Brief", open: true, color: "var(--ui-accent)" }, h(BriefGrid, { fields: [
          { label: "Timing", text: verdict[0], color: verdict[1] },
          { label: "Your threads", text: `${mt.total || 0} opened \xB7 ${mt.resolved || 0} resolved \xB7 ${mt.replied || 0} replied by the author` },
          { label: "Since review", text: sr.commits ? `${sr.commits} commit(s), ${sr.files != null ? sr.files : "?"} file(s) changed${sr.last_push ? ", last push " + ago(sr.last_push) + " ago" : ""}` : "nothing pushed" },
          { label: "Last activity", text: pr.last_activity ? ago(pr.last_activity) + " ago" : "\u2013" },
          { label: "Re-review does", text: hints.rereview }
        ] }));
      })(),
      h(TicketTools, { ticket, part: "demo" }),
      (pr.replies || []).length ? h(
        Section,
        { title: `The author's replies in your threads (${pr.replies.length})` },
        ...pr.replies.map((c, i) => h(
          "div",
          { key: i, className: "rounded border px-2 py-1", style: { borderColor: stroke } },
          h("div", { style: sub }, `${c.author || ""} \xB7 ${c.at ? ago(c.at) + " ago" : ""}`),
          c.html ? h(RichMd, { html: c.html }) : h("div", { className: "whitespace-pre-wrap" }, (c.body || c.text || "").slice(0, 1200))
        ))
      ) : null,
      h(ClearableTextarea, { value: note, onChange: (e) => setNote(e.target.value), rows: 3, placeholder: "optional note for the reviewer, e.g. the author says everything is addressed; focus on thread 2 and the new migration", className: "rounded border bg-transparent px-2 py-1", style: { borderColor: stroke } }),
      h("div", { className: "flex gap-1.5" }, h("button", { type: "button", disabled: busy, onClick: go, className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: "var(--ui-accent)", color: "#fff" } }, busy ? "working" : "Re-review what changed"), btn("Open PR", () => openWeb(pr.url)))
    )
  );
}
var GOOD = "var(--ui-success, #2a9d5c)";
var prKey = (r) => {
  const p = r && r.payload || {};
  const n = p.number || r && r.pr && r.pr.number;
  return p.repo && n ? `${p.repo}#${n}` : "";
};
function afterShort(after) {
  const parts = String(after || "").split("/");
  const tail = parts.length > 1 ? parts[1] : parts[0];
  return String(tail || "").slice(0, 3);
}
function groupByPr(items) {
  const groups = /* @__PURE__ */ new Map();
  const out = [];
  for (const it of items) {
    const k = it.row ? prKey(it.row) : "";
    if (!k) {
      out.push(it);
      continue;
    }
    if (!groups.has(k)) {
      const g = { pr: k, ticket: it.ticket, members: [] };
      groups.set(k, g);
      out.push(g);
    }
    groups.get(k).members.push(it);
  }
  return out.map((g) => {
    if (!g.members) return g;
    if (g.members.length === 1) return g.members[0];
    const m = g.members;
    const lead = m.find((x) => x.color !== GOOD) || m[0];
    const counts = m.reduce((a, x) => ({ ...a, [x.row.type]: (a[x.row.type] || 0) + 1 }), {});
    const types = Object.entries(counts).map(([t, n]) => n > 1 ? `${n} ${t}` : t).join(", ");
    return {
      key: "g" + g.ticket + g.pr,
      icon: lead.icon,
      ticket: g.ticket,
      what: `${g.pr} \u2014 ${m.length} items (${types}) \u2014 ${lead.what.split(" \u2014 ").slice(1).join(" \u2014 ")}`,
      action: [...new Set(m.flatMap((x) => x.action.split(" / ")))].join(" / "),
      ts: m.map((x) => x.ts || "").sort().pop(),
      color: lead.color,
      group: { pr: g.pr, members: m }
    };
  });
}
function PrGroupPanel({ g, ticket, goOutbox, onDone }) {
  const [busy, setBusy] = useState13(false);
  const [ask, setAsk] = useState13(false);
  const [rework, setRework] = useState13(false);
  const members = [...g.members].sort((a, b) => (a.row.order ?? 99) - (b.row.order ?? 99));
  const ready = members.filter((x) => x.action === "publish" && x.row.status === "endorsed" && !x.row.stale_head);
  const publishAll = async () => {
    setBusy(true);
    let done = 0;
    try {
      for (const x of ready) {
        const r = await post("/publish", { id: x.row.id, confirm: x.row.id });
        if (r && r.receipt && r.receipt.ok === false) throw new Error(r.receipt.error || "refused");
        done += 1;
        host.notify({ kind: "success", title: `Published ${x.row.id}`, message: r.out });
      }
      onDone();
    } catch (e) {
      host.notifyError(e, `publishing stopped after ${done} of ${ready.length}`);
    } finally {
      setBusy(false);
      setAsk(false);
    }
  };
  return h(
    "div",
    { className: "cockpit-prgroup flex h-full min-h-0 flex-col gap-2 overflow-auto p-3" },
    detailHead(`${ticket} \xB7 ${g.pr}`, { text: `${members.length} items on this PR`, color: "var(--ui-accent)" }, ""),
    h(TicketTools, { ticket, part: "chat" }),
    h("div", { className: "flex items-center gap-2" }, btn(rework ? "Close" : "Rework", () => setRework(!rework), { title: "something is missing on this PR: tell the worker; tester and reviewer follow, the push updates the PR" })),
    rework ? h(ReworkForm, { ticket, repos: [String(g.pr).split("#")[0]], onDone: () => setRework(false) }) : null,
    ...members.map((x) => h(
      "div",
      { key: x.key, className: "rounded border px-2.5 py-1.5 text-xs flex flex-col gap-1", style: { borderColor: stroke } },
      h(
        "div",
        { className: "flex items-center gap-2" },
        h("span", { className: "font-medium", style: { color: x.color } }, x.action),
        h("span", { style: mono }, x.row.id),
        h(
          "span",
          { className: "ml-auto flex items-center gap-1.5" },
          memberStep(x) ? h("button", { type: "button", "data-step": memberStep(x).step, onClick: () => goOutbox(x.row.id), className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: memberStep(x).color, color: "#fff" }, title: memberStep(x).title }, memberStep(x).label) : null,
          btn("Open the intent", () => goOutbox(x.row.id), { title: "the intent with its Brief, what leaves, the gatekeeper check and the diffs" })
        )
      ),
      h("div", { style: sub }, x.what.split(" \u2014 ").slice(1).join(" \u2014 "))
    )),
    ready.length ? ask ? h(
      "div",
      { className: "flex flex-col gap-2 rounded border p-2 text-xs", style: { borderColor: GOOD } },
      h("div", { className: "font-medium" }, `Publish ${ready.length} item(s) in this order: ${ready.map((x) => x.row.id).join(" \u2192 ")}?`),
      h("div", { style: sub }, "Each runs cockpit publish as you, one after the other; it stops at the first refusal. The sha is re-checked before anything leaves."),
      h("div", { className: "flex items-center gap-1.5" }, h("button", { type: "button", disabled: busy, onClick: publishAll, className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: GOOD, color: "#fff" } }, busy ? "working" : "Publish now"), btn("Cancel", () => setAsk(false)))
    ) : h("div", null, h("button", { type: "button", onClick: () => setAsk(true), className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: GOOD, color: "#fff" } }, `\u2713 Publish ${ready.length} in order (${ready.map((x) => x.row.type).join(" \u2192 ")})`)) : h("div", { style: sub }, "Nothing on this PR is ready to publish yet: open an item for its own action."),
    h(TicketTools, { ticket, part: "demo" })
  );
}
function memberStep(x) {
  const r = x.row || {};
  if (r.type === "pr-review-submit" && r.status === "posted") return { step: "publish-review", label: "\u2713 Publish review\u2026", color: GOOD, title: "stage 2: submit the pending review with the verdict and a summary you confirm (or discard it) on its own pane" };
  if (r.status === "held") return { step: "decide", label: "Decide\u2026", color: "var(--ui-warning, #c98a00)", title: "the gatekeeper holds it with one question for you: answer it on its own pane" };
  return null;
}
var stillOpen = (r) => OPEN.has(r.status) || r.status === "published" && (r.type === "push-branch" || r.type === "pr-patch-apply") && r.ci && (r.ci.state === "running" || r.ci.state === "failed" && !r.ci.handled);
var DAY = 864e5;
var GROUPS = [
  ["flight", "In flight", "at the gate or in the pipeline: the gatekeeper's, a lane's, or publishing with the row it follows \u2014 not yours yet"],
  ["advisories", "Advisories", "every advisory the stack watch knows, the backlog included \u2014 the alerts are your rows above; a \u{1F916} pill means a bump PR already covers it"],
  ["published", "Published today", "what left the machine in the last 24 h; search for older ones"],
  ["dropped", "Dropped", ""]
];
function itemRow(it, selected, onClick, compact) {
  const r = it.row || it.group && it.group.members[0].row || null;
  const kind = it.group ? it.group.members.map((x) => x.row.type).filter((v, k, a) => a.indexOf(v) === k).join(" + ") : it.card ? `card \xB7 ${it.card.assignee}` : it.rereview ? "pr-review" : it.watcher ? "watcher" : it.bumps ? "dependency" : r ? r.type : "";
  return trow(compact ? COMPACT_COLS : OUTBOX_COLS, { key: it.key, onClick, selected, children: pickCells([
    h("div", { key: "t", className: "truncate font-medium" }, it.ticket),
    r && !it.group ? typeCell(r) : h("div", { key: "ty", className: "whitespace-nowrap overflow-hidden font-medium", style: { color: r ? typeColor(r.type) : it.color } }, kind),
    h("div", { key: "tg", className: "truncate", title: it.what }, it.what),
    h("div", { key: "r", style: { color: riskColor(r && r.risk) } }, r && r.risk ? r.risk : "\u2013"),
    h("div", { key: "s", className: "truncate font-medium", style: { color: it.color }, title: it.icon + " " + it.action }, `${it.icon} ${it.action}`),
    prCell(r),
    ciCell(r),
    h("div", { key: "a", className: "truncate text-right", style: sub }, it.ts ? ago(it.ts) : "")
  ], compact) });
}
function BumpsPanel({ repo, prs, onDone, release }) {
  const hints = useHints();
  const [chosen, setChosen] = useState13(prs.map((p) => p.number));
  const [note, setNote] = useState13("");
  const [busy, setBusy] = useState13(false);
  const act = async (path, body, msg) => {
    setBusy(true);
    try {
      const r = await post(path, body);
      host.notify({ kind: "success", title: msg, message: r.out });
      onDone();
    } catch (e) {
      host.notifyError(e, "failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex flex-col gap-3 p-3 text-xs" },
    detailHead(`${repo} \xB7 dependency bumps`, { text: `${prs.length} open bump PR(s)`, color: "var(--ui-accent)" }, "found by cockpit bumps, read-only"),
    h("div", { className: "flex flex-wrap items-center gap-1" }, ...prs.map((p) => h("button", { key: p.number, type: "button", onClick: () => openWeb(p.url), title: `${p.title}
${p.url}`, className: "rounded border px-2 py-0.5 text-xs whitespace-nowrap", style: { borderColor: stroke } }, `#${p.number} \u2197 `, h("span", { style: sub }, p.title.length > 48 ? p.title.slice(0, 47) + "\u2026" : p.title)))),
    h("div", { style: sub }, hints.bumps_start),
    h("div", { className: "flex flex-col gap-1" }, ...prs.map((p) => h(
      "label",
      { key: p.number, className: "flex items-center gap-2" },
      h("input", { type: "checkbox", checked: chosen.includes(p.number), onChange: (e) => setChosen(e.target.checked ? [...chosen, p.number] : chosen.filter((n) => n !== p.number)) }),
      h("a", { href: p.url, onClick: (e) => {
        e.preventDefault();
        openWeb(p.url);
      }, style: mono }, `#${p.number}`),
      h("span", null, p.title),
      h("span", { style: sub }, p.head)
    ))),
    h(ClearableTextarea, { value: note, onChange: (e) => setNote(e.target.value), rows: 2, placeholder: "optional: a note for the lane (skip the major bump, \u2026)", className: "rounded border bg-transparent px-1.5 py-1", style: { borderColor: stroke } }),
    h(
      "div",
      { className: "flex gap-1.5" },
      release ? btn(
        "Release selected",
        () => act("/bumps-release", { repo, numbers: chosen }, `${repo}: released`),
        { title: "return the selected pull requests to the candidates", disabled: busy || !chosen.length }
      ) : h(
        "button",
        {
          type: "button",
          disabled: busy || !chosen.length,
          onClick: () => act(
            "/kickoff",
            { mode: "bumps", repo, prs: chosen, prompt: note },
            `${repo}: bumps started`
          ),
          className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40",
          style: { background: "var(--ui-accent)", color: "#fff" }
        },
        busy ? "working" : `Start ${chosen.length} PR(s)`
      ),
      release ? null : btn("Dismiss selected", () => act("/bumps-dismiss", { repo, numbers: chosen }, `${repo}: dismissed`), { title: "hidden until the PR's head moves (a new bump)", disabled: busy || !chosen.length })
    )
  );
}
function StandupPanel({ d, onDone }) {
  const [text, setText] = useState13(d.note || d.draft || "");
  const [busy, setBusy] = useState13(false);
  useEffect8(() => {
    setText(d.note || d.draft || "");
  }, [d.day, d.drafted_at, d.note, d.draft]);
  const act = async (path, body, msg) => {
    setBusy(true);
    try {
      const r = await post(path, body);
      host.notify({ kind: "success", title: msg, message: r.out });
      onDone();
    } catch (e) {
      host.notifyError(e, "standup failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex h-full min-h-0 flex-col gap-2 p-3 text-xs" },
    detailHead(`standup \xB7 ${d.day}`, { text: `${d.items} item(s) \xB7 draft`, color: "var(--ui-accent)" }, `since ${(d.since || "").replace("T", " ").slice(0, 16)} \xB7 drafted ${d.drafted_at ? ago(d.drafted_at) + " ago" : ""}`),
    h("div", { style: sub }, `What left the machine since ${(d.since || "").replace("T", " ").slice(0, 16) || "the window start"}, from the outbox receipts, the PR watch and the test runs. Edit freely; Update rebuilds it from the records (your edits go); Confirm sends exactly this text.`),
    h(Section, { title: "Preview", open: true }, h(RichMd, { html: d.markdown_html || "" })),
    h(ClearableTextarea, { value: text, onChange: (e) => setText(e.target.value), rows: 12, className: "w-full rounded border bg-transparent px-2 py-1.5 text-xs", style: { borderColor: stroke, resize: "vertical", fontFamily: "var(--ui-font-mono, ui-monospace, Menlo, monospace)" } }),
    h(
      "div",
      { className: "flex items-center gap-2" },
      h("button", {
        type: "button",
        disabled: busy || !text.trim(),
        onClick: () => act("/standup-confirm", { day: d.day, text }, "standup sent"),
        className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40",
        style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" },
        title: "sends this text through the pack notify command and closes the row"
      }, busy ? "working" : "Confirm & send"),
      btn("Update", () => act("/standup-update", {}, "standup drafted again"), { title: "draft again from the records, up to this minute (edits are lost)", disabled: busy })
    )
  );
}
function RefusalPanel({ r, onDone }) {
  const [note, setNote] = useState13("");
  const [busy, setBusy] = useState13(false);
  const act = async (path, msg) => {
    setBusy(true);
    try {
      const x = await post(path, { key: r.key, note });
      host.notify({ kind: "success", title: msg, message: x.out });
      onDone();
    } catch (e) {
      host.notifyError(e, msg + " failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex flex-col gap-2 p-3 text-xs" },
    detailHead(`${r.ticket} \xB7 ${r.type} refused`, { text: "refused \xB7 nothing went out", color: "var(--ui-danger, #d33)" }, r.time),
    r.reason_html ? h(RichMd, { className: "rounded border px-2 py-1.5", style: { borderColor: "var(--ui-danger, #d33)" }, html: r.reason_html }) : h("div", { className: "rounded border px-2 py-1.5 whitespace-pre-wrap", style: { borderColor: "var(--ui-danger, #d33)" } }, r.reason),
    h("div", { style: sub }, `${r.card_lane || r.lane} tried it on card ${r.card || "?"} (${r.card_title || "?"}), which ended ${r.card_status || ""} without fixing it${r.intent ? `; intent ${r.intent}` : ""}. Nothing reached the forge or tracker.`),
    h(ClearableTextarea, { value: note, onChange: (e) => setNote(e.target.value), rows: 3, placeholder: "optional: your decision or a hint for the lane", className: "w-full rounded border bg-transparent px-2 py-1 text-xs", style: { borderColor: stroke } }),
    h(
      "div",
      { className: "flex items-center gap-2" },
      h(
        "button",
        {
          type: "button",
          disabled: busy,
          onClick: () => act("/refusal-send-back", `${r.ticket}: sent back`),
          className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40",
          style: { background: "var(--ui-accent)", color: "#fff" },
          title: "a card to the same kind of lane with the refusal and your note: it fixes the cause and makes the act again, or asks you one question"
        },
        "Send back to the lane"
      ),
      btn("Dismiss", () => act("/refusal-dismiss", `${r.ticket}: dismissed`), { disabled: busy, title: "it is fine as it is: the row leaves (a new refusal brings it back)" })
    )
  );
}
function PrivilegedPanel({ row, onDone, card = null, openCard = null }) {
  const [busy, setBusy] = useState13(false);
  const act = async (path) => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await post(path, { card: row.card || "", lane: row.lane || "" });
      host.notify({ kind: "success", title: row.card || "privileged login", message: r.out });
      onDone();
    } catch (e) {
      host.notifyError(e, "privileged login");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex flex-col gap-2 p-3 text-xs" },
    detailHead(card ? `${card.ticket || row.card} \xB7 ${card.assignee}` : row.card || "privileged login", { text: "needs a decision", color: "var(--ui-warning, #c98a00)" }, row.summary || ""),
    h("div", { className: "whitespace-pre-wrap" }, row.reason || ""),
    card ? h("div", { style: sub }, `The card ${card.id} is blocked on this request. Approve lends the login for the step named and resumes the card; Deny leaves the card blocked with your refusal.`) : null,
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2" },
      h("button", { type: "button", disabled: busy, onClick: () => act("/privileged-approve"), className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-success, #2a9d5c)", color: "#fff" } }, "Approve this step"),
      h("button", { type: "button", disabled: busy, onClick: () => act("/privileged-deny"), className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-danger, #d33)", color: "#fff" } }, "Deny"),
      openCard ? btn("Answer the card instead", openCard, { title: "the card's own pane: a free answer, stop, or archive" }) : null
    )
  );
}
var TICKET_KEY = /^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$/;
function TrackerNotePanel({ n, onDone }) {
  const [busy, setBusy] = useState13(false);
  const word = useTrackerWord();
  const place = word === "Jira" ? "Jira" : "tracker";
  const dismiss = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await post("/tracker-note-dismiss", { id: n.id });
      host.notify({ kind: "info", title: `${n.ticket}: note dismissed`, message: r.out || "" });
      onDone();
    } catch (e) {
      host.notifyError(e, "dismiss failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-xs", "data-tracker-note": n.id },
    detailHead(`${n.ticket} \xB7 ${word} comment ${n.kind === "edited" ? "edited" : "added"}`, { text: "for your information", color: "var(--ui-accent)" }, `${n.author || "someone"}${n.at ? " \xB7 " + ago(n.at) + " ago" : ""}`),
    h("div", { style: sub }, `${n.kind === "edited" ? "An existing comment was edited" : "A comment was added"} while the ticket's done row waited for you. Nothing runs on it; read it, then dismiss.`),
    h(
      "div",
      { className: "rounded-md border px-3 py-2", style: { borderColor: "var(--ui-accent)", background: "rgba(56,139,253,.06)" } },
      n.text_html ? h(RichMd, { html: n.text_html, className: "leading-relaxed" }) : h("div", { className: "whitespace-pre-wrap" }, n.text || "")
    ),
    h(
      "div",
      { className: "flex items-center gap-2" },
      n.url ? btn(`Open in ${place}`, () => openWeb(n.url), { accent: true, title: n.url }) : null,
      n.url ? copyBtn(n.url, `${place} link`) : null,
      h("button", { type: "button", disabled: busy, onClick: dismiss, className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-accent)", color: "#fff" } }, busy ? "working" : "Dismiss")
    )
  );
}
function AnswerPanel({ a, onDone }) {
  const [busy, setBusy] = useState13(false);
  const [ask, setAsk] = useState13(a.followup_text || "");
  const [edit, setEdit] = useState13(false);
  const [kickTicket, setKickTicket] = useState13(a.ticket || "");
  const qc = useQueryClient();
  const refs = a.references || [];
  const paths = refs.map((f) => f.rel || f.path);
  const prompt = a.reopen_prompt || a.summary || "";
  const act = async (fn, done) => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fn();
      host.notify({ kind: "success", title: `${a.ticket}: ${done}`, message: r && r.out || "" });
      qc.invalidateQueries({ queryKey: ["cockpit"] });
      onDone();
    } catch (e) {
      host.notifyError(e, `${done} failed`);
    } finally {
      setBusy(false);
    }
  };
  const primary = (label, onClick, extra = {}) => h("button", { type: "button", disabled: busy || extra.disabled, onClick, title: extra.title || "", className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40", style: { background: extra.bg || "var(--ui-accent)", color: "#fff" } }, label);
  const key = kickTicket.trim().toUpperCase();
  return h(
    "div",
    { className: "flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-xs", "data-answer": a.card },
    detailHead(`${a.ticket} \xB7 ${a.lane || a.mode} answered`, { text: "answer \xB7 use it or dismiss", color: "var(--ui-accent)" }, a.card),
    a.follows ? h("div", { style: sub }, `follow-up to card ${a.follows}`) : null,
    h(
      "div",
      { className: "rounded-md border px-3 py-2", style: { borderColor: "var(--ui-accent)", background: "rgba(56,139,253,.06)" } },
      h("div", { className: "cockpit-head mb-1" }, "the answer"),
      a.summary_html ? h(RichMd, { html: a.summary_html, className: "leading-relaxed" }) : h("div", { style: sub }, "the card ended without a summary; the files below are the answer")
    ),
    refs.length ? h(
      "div",
      { className: "flex flex-col gap-1" },
      h("div", { className: "cockpit-head" }, `References (${refs.length})`),
      h("div", { className: "flex flex-wrap gap-1" }, ...refs.map((f) => h(
        "span",
        {
          key: f.path,
          className: "flex items-center gap-1 rounded border px-1",
          style: { borderColor: stroke, ...f.shared ? { borderStyle: "dashed" } : {} },
          title: f.shared ? `${f.rel || f.path} \xB7 the ticket's file: a later card rewrote it, so it is listed here as shared` : f.rel || f.path,
          "data-shared": f.shared ? "1" : void 0
        },
        h("button", { type: "button", onClick: () => openFile(f.path), style: { color: "var(--ui-accent)" } }, f.name),
        f.shared ? h("span", { style: sub }, "shared") : null,
        copyBtn(f.rel || f.path, "path")
      )))
    ) : h("div", { style: sub }, "no file under qa/ was written by this card"),
    a.report_html ? h(Section, { title: `Report \xB7 ${a.report_name || ""}` }, h(RichMd, { html: a.report_html, className: "leading-relaxed" })) : null,
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2" },
      primary("Reopen with this", () => act(() => post("/reopen-flow", { ticket: a.ticket, prompt, evidence: paths, from_answer: a.card }), "reopened"), { title: "intake reads the answer and its files, proposes, and waits for your go; the ticket-done row, if any, leaves" }),
      h("a", { href: "#", onClick: (e) => {
        e.preventDefault();
        setEdit(!edit);
      }, style: sub }, edit ? "close the form" : "edit first"),
      (a.rework_repos || []).length ? primary("Rework with this", () => act(() => post("/kickoff", { ticket: a.ticket, mode: "rework", prompt, repos: a.rework_repos, evidence: paths, from_answer: a.card }), "rework queued"), { bg: "var(--ui-warning, #c98a00)", title: `straight to the worker on ${a.rework_repos.join(", ")}, with a tester and a reviewer behind it` }) : null,
      btn("Dismiss", () => act(() => post("/answer-dismiss", { card: a.card }), "answer dismissed"), { disabled: busy, title: "read; the row leaves (the card stays on the Board)" })
    ),
    edit ? h(ReopenForm, { ticket: a.ticket, initial: { prompt, files: refs.map((f) => ({ name: f.name, path: f.rel || f.path })), from_answer: a.card }, onDone: () => {
      setEdit(false);
      onDone();
    } }) : null,
    h(
      "div",
      { className: "flex items-center gap-2" },
      h("input", { value: kickTicket, onChange: (e) => setKickTicket(e.target.value), placeholder: "TASK-1", className: "w-32 rounded border bg-transparent px-1.5 py-0.5", style: { ...mono, borderColor: stroke } }),
      btn("Kick off with this", () => act(() => post("/kickoff", { ticket: key, mode: "intake", prompt, evidence: paths, from_answer: a.card }), `${key} \u2192 intake`), { disabled: busy || !TICKET_KEY.test(key), title: "intake on this ticket, or another one, with the answer and its files as the evidence" })
    ),
    h(
      "div",
      { className: "flex flex-col gap-1 rounded-md border px-3 py-2", style: { borderColor: stroke } },
      h("div", { className: "cockpit-head" }, "ask a follow-up (a patch plan is the preset)"),
      h(ClearableTextarea, { value: ask, onChange: (e) => setAsk(e.target.value), rows: 4, className: "w-full rounded border bg-transparent px-2 py-1 text-xs", style: { borderColor: stroke, resize: "vertical" } }),
      h("div", { className: "flex items-center gap-2" }, primary("Ask for a patch plan", () => act(() => post("/answer-followup", { card: a.card, prompt: ask }), "follow-up asked"), { disabled: !ask.trim(), title: "a new card of the same lane with the references; its answer comes back here as a row of its own" }))
    )
  );
}
function Inbox({ rows, refresh, openAll }) {
  const word = useTrackerWord();
  const q2 = useQuery({ queryKey: ["cockpit", "needs-you"], queryFn: () => CTX.rest("/needs-you"), refetchInterval: POLL_MS, retry: 1 });
  const bq = useQuery({ queryKey: ["cockpit", "bumps"], queryFn: () => CTX.rest("/bumps"), refetchInterval: POLL_MS * 6, retry: 0 });
  const rfq = useQuery({ queryKey: ["cockpit", "refusals"], queryFn: () => CTX.rest("/refusals"), refetchInterval: POLL_MS * 2, retry: 0 });
  const aq = useQuery({ queryKey: ["cockpit", "advisories"], queryFn: () => CTX.rest("/advisories"), refetchInterval: POLL_MS * 6, retry: 0 });
  const stq = useQuery({ queryKey: ["cockpit", "standup"], queryFn: () => CTX.rest("/standup"), refetchInterval: POLL_MS * 6, retry: 0 });
  const sq = useQuery({ queryKey: ["cockpit", "sweep-state"], queryFn: () => CTX.rest("/sweep-state"), refetchInterval: POLL_MS, retry: 1 });
  const sweep = sq.data;
  const [sel, setSel] = useState13(null);
  const [open, setOpenRaw] = useState13(() => openAll ? { flight: true, advisories: true, published: true, dropped: true } : CTX.storage.get("groups1", {}));
  const setOpen = (g, v) => {
    const n = { ...open, [g]: v };
    setOpenRaw(n);
    CTX.storage.set("groups1", n);
  };
  const [search, setSearch] = useState13("");
  const [security, setSecurityRaw] = useState13(() => Boolean(CTX.storage.get("showSecurity", false)));
  const setSecurity = (v) => {
    setSecurityRaw(v);
    CTX.storage.set("showSecurity", v);
  };
  const alerts = (aq.data && aq.data.advisories || []).filter(alertable);
  const cards = q2.data && q2.data.cards || [];
  const items = [];
  const privileged = q2.data && q2.data.privileged || [];
  const lendAsked = new Set(privileged.map((p) => p.card).filter(Boolean));
  for (const c of cards.filter((x) => (x.status === "blocked" || x.status === "triage") && !x.waits_publish && !lendAsked.has(x.id) && !(notReady(x) && !x.parked && Date.now() / 1e3 - (x.blocked_at || 0) < SEND_BACK_GRACE_S))) items.push({
    key: "b" + c.id,
    icon: "\u2753",
    ticket: c.ticket || "",
    what: `${c.assignee}${c.status === "triage" ? " (asked twice)" : ""} asks: ${(c.question || c.block_reason || c.title).replace(/\s+/g, " ").slice(0, 140)}`,
    action: notReady(c) ? "send back" : credentialAsk(c.question) ? "staging login" : "answer",
    ts: c.created_at ? new Date(c.created_at * 1e3).toISOString() : null,
    color: "var(--ui-warning, #c98a00)",
    card: c
  });
  for (const a of q2.data && q2.data.answers || []) items.push({ key: "ans" + a.card, icon: "\u{1F4A1}", ticket: a.ticket || "", what: `${a.lane || a.mode || "the analyst"} answered: ${(a.summary || (a.references || []).map((f) => f.name).join(", ") || a.title || "").replace(/\s+/g, " ").slice(0, 140)}`, action: "use answer", ts: a.completed || null, color: "var(--ui-accent)", answer: a });
  for (const n of q2.data && q2.data.tracker_notes || []) items.push({ key: "tn" + n.id, icon: "\u{1F4AC}", ticket: n.ticket || "", what: `${word} comment ${n.kind === "edited" ? "edited" : "added"} by ${n.author || "someone"} while the done row waits: ${(n.text || "").replace(/\s+/g, " ").slice(0, 140)}`, action: "read", ts: n.at || null, color: "var(--ui-accent)", note: n });
  const seenPr = /* @__PURE__ */ new Set();
  const seenCi = /* @__PURE__ */ new Set();
  for (const r of rows) {
    const stepOneNeedsYou = r.status === "held" && !(r.hold && r.hold.waits === "lane") || r.status === "posted";
    if (r.chain && r.chain.followed_by && !stepOneNeedsYou) continue;
    const second = r.chain && r.chain.pair ? rows.find((x) => x.id === r.chain.pair) : null;
    if (second && second.status === "endorsed" && !second.waits && !second.stale_head && !stepOneNeedsYou) continue;
    const stepReady = !(r.chain && r.chain.role === "content") || r.chain.step1_status === "endorsed" || String(r.chain.step1_status).startsWith("published");
    const reasons = [];
    if (r.type === "ticket-done" && r.status === "pending") reasons.push({ icon: "\u{1F3C1}", text: "PR merged, nothing open \u2014 confirm done or reopen", action: "confirm done", ts: r.created_at, color: "var(--ui-accent)" });
    if (r.stale_head) reasons.push({ icon: "\u21BB", text: `PR head moved after this review was written (${r.stale_head.reviewed} \u2192 ${r.stale_head.now}): publish would mis-anchor \u2014 re-review at the new head`, action: "re-review", ts: r.endorsed ? r.endorsed.time : r.created_at, color: "var(--ui-warning, #c98a00)" });
    else if (r.type === "infra-note") {
      if (OPEN.has(r.status) && r.payload && r.payload.repo && r.payload.branch && r.payload.patch_file) reasons.push({ icon: "\u{1FA79}", text: `${r.created_by || "a lane"} left a patch it may not write itself (${r.payload.patch_file.split("/").pop()}) \u2014 apply it as your commit`, action: "apply patch", ts: r.created_at, color: "var(--ui-accent)" });
    } else if (r.status === "endorsed" && r.type !== "ticket-done" && stepReady && !r.waits) reasons.push({ icon: "\u2713", text: `endorsed by ${endorserOf(r)}${r.endorsed && r.endorsed.notes ? ": " + r.endorsed.notes.slice(0, 90) : ""}`, action: "publish", ts: r.endorsed ? r.endorsed.time : r.created_at, color: "var(--ui-success, #2a9d5c)" });
    if (r.status === "posted") reasons.push({ icon: "\u25D4", text: `pending review on the forge (${r.review && r.review.proposed_event ? r.review.proposed_event : "verdict"}) \u2014 look at the PR page, then publish or discard`, action: "publish review", ts: r.review && r.review.posted_at, color: "var(--ui-warning, #c98a00)" });
    const heldInTurn = !(r.waits && !(r.hold && r.hold.ask));
    if (r.status === "held" && !(r.hold && r.hold.waits === "lane") && heldInTurn) reasons.push({ icon: "\u23F8", text: r.hold && r.hold.ask ? `the gatekeeper asks: ${r.hold.ask.slice(0, 160)}` : `held by the gatekeeper: ${(r.hold && r.hold.reason || "").slice(0, 120)}`, action: r.hold && r.hold.ask ? "decide" : "resolve hold", ts: r.hold && r.hold.time, color: "var(--ui-warning, #c98a00)" });
    if (r.ci && r.ci.state === "failed" && !r.ci.handled && !r.ci.analysing && !seenCi.has(r.ticket + r.ci.sha)) {
      seenCi.add(r.ticket + r.ci.sha);
      reasons.push({ icon: "\u2717", text: `CI failed on ${r.ci.branch} @ ${r.ci.sha}: ${r.ci.summary} \u2014 no analyst card could be created; dismiss or diagnose by hand`, action: "diagnose", ts: r.ci.last_check, color: "var(--ui-danger, #d33)" });
    }
    const reviewer = r.pr && r.pr.role === "reviewer";
    if (r.pr && !reviewer && !r.pr.merged && r.pr.approvals && r.pr.approvals.length && !seenPr.has("appr" + r.ticket + r.pr.number)) {
      seenPr.add("appr" + r.ticket + r.pr.number);
      reasons.push({
        icon: "\u{1F44D}",
        text: `PR #${r.pr.number} approved by ${r.pr.approvals.map((a) => a.author).join(", ")} \u2014 merge when you are ready; the final ack follows the merge`,
        action: "merge",
        ts: r.pr.approvals[r.pr.approvals.length - 1].at,
        color: "var(--ui-success, #2a9d5c)"
      });
    }
    if (r.pr && r.pr.new_count && !seenPr.has(r.ticket + r.pr.number)) {
      seenPr.add(r.ticket + r.pr.number);
      if (reviewer) {
      } else reasons.push({ icon: "\u{1F4AC}", text: `${r.pr.new_count} new PR comment(s) on #${r.pr.number} since the pipeline's pass`, action: "treat comments", ts: r.pr.new[0] && r.pr.new[0].at, color: "var(--ui-warning, #c98a00)" });
    }
    if (!reasons.length) continue;
    const first = reasons[0];
    items.push({
      key: "i" + r.id,
      icon: reasons.map((x) => x.icon).join(""),
      ticket: r.ticket,
      what: `${r.target}${r.payload && r.payload.rebase_only ? " \u27F3 REBASE ONLY" : r.payload && r.payload.after ? " \u2192 after " + afterShort(r.payload.after) : ""} \u2014 ` + reasons.map((x) => x.text).join(" \xB7 "),
      action: reasons.map((x) => x.action).join(" / "),
      ts: reasons.map((x) => x.ts || "").sort().pop(),
      color: first.color,
      intent: r.id,
      row: r,
      decide: reasons.some((x) => x.action === "decide") ? r : null
    });
  }
  const doneFirst = (it) => /confirm done/.test(it.action || "") ? 0 : 1;
  items.splice(0, items.length, ...groupByPr(items));
  items.sort((a, b) => doneFirst(a) - doneFirst(b) || (b.ts || "").localeCompare(a.ts || ""));
  const running = cards.filter((c) => ["in_progress", "running", "claimed", "review"].includes(c.status));
  const seenRr = /* @__PURE__ */ new Set();
  const openCards = new Set(cards.map((c) => c.id));
  for (const r of rows) for (const p of r.halted ? [] : r.prs || []) {
    if (p.role !== "reviewer" || p.merged || p.state !== "open" || p.my_review_state === "APPROVED" || seenRr.has(r.ticket + p.number)) continue;
    if (p.rereview && openCards.has(p.rereview.card)) {
      seenRr.add(r.ticket + p.number);
      continue;
    }
    if (rows.some((x) => x.ticket === r.ticket && x.type === "pr-review-submit" && OPEN.has(x.status) && x.payload && String(x.payload.number) === String(p.number))) {
      seenRr.add(r.ticket + p.number);
      continue;
    }
    seenRr.add(r.ticket + p.number);
    const mt = p.my_threads || {};
    const sr = p.since_review || {};
    const quiet = p.last_activity ? (Date.now() - toMs(p.last_activity)) / 6e4 : null;
    const ready = p.rereview_ready !== void 0 ? Boolean(p.rereview_ready) : p.re_requested || mt.total && mt.resolved === mt.total || quiet != null && quiet > 120 && (mt.replied || sr.commits);
    if (!ready && !(mt.replied || sr.commits || p.re_requested)) continue;
    items.push({
      key: "rr" + r.ticket + p.number,
      icon: "\u{1F50E}",
      ticket: r.ticket,
      what: `review in progress: ${p.repo} #${p.number} by ${r.pr && r.pr.author || "the author"} \u2014 ${mt.resolved || 0}/${mt.total || 0} of your threads resolved, ${mt.replied || 0} replied${sr.commits ? `, ${sr.commits} commit(s) since your review` : ", nothing pushed since"}${p.last_activity ? ` \xB7 last activity ${ago(p.last_activity)} ago` : ""}${p.re_requested ? " \xB7 AUTHOR RE-REQUESTED YOUR REVIEW" : ""}${ready ? "" : " \xB7 the author is still on it: the re-review starts by itself after two quiet hours"}`,
      action: "re-review",
      ts: p.last_activity || null,
      color: ready ? "var(--ui-accent)" : "var(--ui-text-tertiary)",
      rereview: { ticket: r.ticket, pr: p }
    });
  }
  for (const r of rfq.data && rfq.data.refusals || []) items.push({ key: "rf" + r.key, icon: "\u26D4", ticket: r.ticket, what: `${r.type} refused for ${r.ticket} and nothing fixed it: ${r.reason}`, action: "refused", ts: r.time, color: "var(--ui-danger, #d33)", refusal: r });
  const su = stq.data || {};
  if (su.day && su.status === "draft") items.push({ key: "standup" + su.day, icon: "\u{1F4DD}", ticket: "standup", what: `standup note for ${su.day}: ${su.items} item(s) since ${(su.since || "").replace("T", " ").slice(5, 16)} \u2014 review, then Confirm sends it`, action: "confirm standup", ts: su.drafted_at, color: "var(--ui-accent)", standup: su });
  for (const [repo, prs] of Object.entries(bq.data && bq.data.repos || {})) {
    if (!prs || !prs.length) continue;
    items.push({ key: "bumps" + repo, icon: "\u{1F4E6}", ticket: "bumps", what: `${repo}: ${prs.length} open bump PR(s) \u2014 ${prs.map((p) => `#${p.number} ${p.title}`).join(" \xB7 ")}`, action: "start bumps", ts: bq.data.time, color: "var(--ui-accent)", bumps: { repo, prs } });
  }
  for (const [repo, prs] of Object.entries(bq.data && bq.data.started || {})) {
    if (!prs || !prs.length) continue;
    items.push({ key: "bumpheld" + repo, icon: "\u{1F4E6}", ticket: "bumps", what: `${repo}: ${prs.length} bump PR(s) in progress \u2014 release returns them to the candidates`, action: "release bumps", ts: bq.data.time, color: "var(--ui-accent)", bumps: { repo, prs, release: true } });
  }
  for (const a of security ? alerts : []) items.push({ key: "adv" + a.id, icon: "\u{1F6E1}", ticket: "platform", what: advisoryWhat(a), action: "advisory", ts: a.last_seen, color: severityColor(a), advisory: a });
  for (const m of q2.data && q2.data.merge_ready || []) items.push({
    key: `merge:${m.repo}#${m.number}`,
    icon: "\u{1F44D}",
    ticket: m.tickets[0] || "platform",
    what: `${m.repo.split(".")[0]} #${m.number} is ready to merge (${m.tickets.join(", ")}) \u2014 merge when you are ready; the final ack follows the merge`,
    action: "merge",
    ts: "",
    color: "var(--ui-success, #2a9d5c)",
    merge: m
  });
  for (const w of (q2.data && q2.data.watchers || []).filter((w2) => !w2.ok)) items.push(w.update ? { key: "w" + w.name, icon: "\u2B06", ticket: "platform", what: w.reason, action: "update", ts: "", color: "var(--ui-accent)", watcher: w } : w.restart ? { key: "w" + w.name, icon: "\u21BB", ticket: "platform", what: w.reason, action: "restart needed", ts: w.last_error || w.last_ok, color: "var(--ui-accent)", watcher: w } : { key: "w" + w.name, icon: "\u26A0", ticket: "platform", what: `watcher ${w.name}: ${w.reason || "is not running properly"} \u2014 ${w.fails} failure(s) in a row, last success ${w.last_ok ? ago(w.last_ok) + " ago" : "never"}`, action: "fix watcher", ts: w.last_error || w.last_ok, color: "var(--ui-danger, #d33)", watcher: w });
  const yours = new Set(items.flatMap((it) => it.group ? it.group.members.map((x) => x.row.id) : it.intent ? [it.intent] : []));
  const digestOrder = (a, b) => (a.type === "ticket-done" ? 0 : 1) - (b.type === "ticket-done" ? 0 : 1) || (a.digest_no || 999) - (b.digest_no || 999) || a.id.localeCompare(b.id);
  const leftAt = (r) => r.receipt && r.receipt.time || r.created_at || "";
  const flight = rows.filter((r) => !yours.has(r.id) && stillOpen(r)).sort(digestOrder);
  const published = rows.filter((r) => !yours.has(r.id) && !stillOpen(r) && r.status !== "dropped").sort((a, b) => leftAt(b).localeCompare(leftAt(a)));
  const needle = search.trim().toLowerCase();
  const shown = needle ? published.filter((r) => `${r.ticket} ${r.type} ${r.target} ${r.id}`.toLowerCase().includes(needle)) : published.filter((r) => Date.now() - new Date(leftAt(r)).getTime() < DAY);
  const dropped = rows.filter((r) => !yours.has(r.id) && r.status === "dropped").sort((a, b) => leftAt(b).localeCompare(leftAt(a)));
  const advs = aq.data && aq.data.advisories || [];
  const groupRows = { flight, advisories: advs, published: shown, dropped };
  const counts = { flight: flight.length, advisories: advs.length, published: needle ? `${shown.length} of ${published.length}` : `${shown.length} today \xB7 ${published.length} in all`, dropped: dropped.length };
  const openIntent = (id) => setSel(sel && sel.intent === id ? null : { key: "o" + id, intent: id });
  for (const p of q2.data && q2.data.plugins || []) items.push({
    key: "pl" + p.plugin + p.id,
    icon: p.icon || "\u2022",
    ticket: p.plugin,
    what: p.what,
    action: p.action_label || (p.detail ? "read" : "open"),
    ts: p.at ? new Date(p.at * 1e3).toISOString() : null,
    color: ROW_TONE[p.tone] || ROW_TONE.info,
    href: p.href || "",
    detail: p.detail || null,
    plugin: p.plugin,
    id: p.id,
    pticket: p.ticket || "",
    orphan: Boolean(p.orphan)
  });
  for (const p of privileged) {
    const c = cards.find((x) => x.id === p.card) || null;
    items.push({
      key: "priv" + (p.card || p.reason),
      icon: "\u{1F511}",
      ticket: c && c.ticket || p.card || "login",
      what: `${c ? c.assignee + " asks: " : ""}${(p.reason || "privileged login").replace(/\s+/g, " ").slice(0, 140)}`,
      action: "approve or deny",
      ts: c && c.created_at ? new Date(c.created_at * 1e3).toISOString() : null,
      color: "var(--ui-warning, #c98a00)",
      privileged: p,
      lendCard: c
    });
  }
  useEffect8(() => {
    if (typeof window === "undefined" || !window.location) return void 0;
    const follow = () => {
      const asked = /(?:^|[#&])plugin=([^&]+)/.exec(window.location.hash || "");
      if (!asked) return;
      let want = "";
      try {
        want = decodeURIComponent(asked[1]);
      } catch {
        want = asked[1];
      }
      const [plugin, ...rest] = want.split("/");
      const id = rest.join("/");
      const found = items.find((it) => it.plugin === plugin && it.id === id);
      if (found) setSel(found);
    };
    follow();
    if (!window.addEventListener) return void 0;
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, [items.length]);
  const pick = (it) => {
    if (it.href !== void 0 && !it.card && !it.detail) {
      if (it.href) host.navigate(it.href);
      else if (it.plugin) setSel(sel && sel.key === it.key ? null : it);
      return;
    }
    if (it.card || it.detail || it.watcher || it.rereview || it.decide || it.group || it.bumps || it.standup || it.refusal || it.privileged || it.advisory || it.answer || it.note || it.merge) setSel(sel && sel.key === it.key ? null : it);
    else if (it.intent) openIntent(it.intent);
  };
  const header = (k, title, hint) => h(
    "div",
    { key: "h" + k, onClick: () => setOpen(k, !open[k]), className: "cockpit-group flex items-center gap-2 px-3 py-1 border-b text-xs cursor-pointer select-none", style: { borderColor: stroke, background: "rgba(127,127,127,.06)" } },
    h("span", { style: sub }, open[k] ? "\u25BE" : "\u25B8"),
    h("span", { className: "font-medium" }, `${title} \xB7 ${counts[k]}`),
    hint ? h("span", { className: "truncate", style: sub }, hint) : null,
    k === "published" && open[k] ? h("input", { value: search, onClick: (e) => e.stopPropagation(), onChange: (e) => setSearch(e.target.value), placeholder: "search all published: ticket, type, target", className: "ml-auto w-64 rounded border bg-transparent px-1.5 py-0.5", style: { borderColor: stroke } }) : null
  );
  const compact = Boolean(sel);
  const pickAdvisory = (a) => {
    const it = { key: "adv" + a.id, advisory: a };
    setSel(sel && sel.key === it.key ? null : it);
  };
  const gate = GROUPS.filter(([k]) => security || k !== "advisories").flatMap(([k, title, hint]) => [header(k, title, hint), ...open[k] ? k === "advisories" ? groupRows[k].map((a) => h(AdvisoryRow, { key: "adv" + a.id, a, selected: sel && sel.key === "adv" + a.id, onClick: () => pickAdvisory(a) })) : groupRows[k].map((r) => h(Row, { key: "o" + r.id, r, selected: sel && sel.intent === r.id, onSelect: openIntent, compact })) : []]);
  return h(
    "div",
    { className: "flex min-h-0 flex-1 flex-col" },
    // one line over your rows: how many and what they ask (the first action of each row), then the security box
    h(
      "div",
      { className: "flex items-center gap-3 px-3 py-1 text-xs border-b", "data-inbox-summary": items.length, style: { ...sub, borderColor: stroke } },
      h("span", null, items.length ? `${items.length} for you: ` + Object.entries(items.reduce((tally, it) => {
        const what = String(it.action || "look").split(" / ")[0];
        tally[what] = (tally[what] || 0) + 1;
        return tally;
      }, {})).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([what, n]) => `${n} ${what}`).join(" \xB7 ") : "nothing for you"),
      h(
        "label",
        { className: "ml-auto flex items-center gap-1.5 cursor-pointer select-none", "data-security-toggle": security ? "on" : "off" },
        h("input", { type: "checkbox", checked: security, onChange: (e) => setSecurity(e.target.checked) }),
        `Show security advisories${alerts.length ? ` (${alerts.length} alert${alerts.length === 1 ? "" : "s"})` : ""}`
      )
    ),
    running.length || sweep && (sweep.running || sweep.requested) ? h(
      "div",
      { className: "px-3 py-1 text-xs border-b", style: { ...sub, borderColor: stroke } },
      "working now: " + [
        ...running.map((c) => `${c.ticket || ""} ${c.assignee} (${c.status.replace("_", " ")})`),
        ...sweep && sweep.running ? ["gatekeeper sweep (endorsing)"] : sweep && sweep.requested ? ["gatekeeper sweep queued"] : []
      ].join(" \xB7 ")
    ) : null,
    h(SplitList, {
      cols: compact ? COMPACT_COLS : OUTBOX_COLS,
      labels: compact ? LABELS.compact : LABELS.full,
      rows: items,
      selected: sel,
      onSelect: pick,
      onClose: () => setSel(null),
      empty: "Nothing for you. The lanes are either working or idle.",
      detailWidth: "46%",
      footer: gate,
      renderRow: (it) => itemRow(it, sel && sel.key === it.key, () => pick(it), compact),
      detail: sel && sel.group ? h(PrGroupPanel, { g: sel.group, ticket: sel.ticket, goOutbox: openIntent, onDone: () => {
        refresh();
        setSel(null);
      } }) : sel && sel.decide ? h(
        "div",
        { className: "flex h-full min-h-0 flex-col gap-2 overflow-auto p-3" },
        detailHead(`${sel.decide.ticket} \xB7 ${sel.decide.type}`, { text: "held \xB7 your decision", color: "var(--ui-warning, #c98a00)" }, sel.decide.id),
        h(DecidePanel, { r: sel.decide, onDone: () => {
          refresh();
          setSel(null);
        } }),
        h(TicketTools, { ticket: sel.decide.ticket, card: intentCard(sel.decide), part: "demo" }),
        h("div", null, btn("Open the intent", () => openIntent(sel.decide.id), { title: "the full intent: Brief, what leaves, the gatekeeper check, diffs" }))
      ) : sel && sel.bumps ? h(BumpsPanel, { repo: sel.bumps.repo, prs: sel.bumps.prs, release: sel.bumps.release, onDone: () => {
        refresh();
        setSel(null);
      } }) : sel && sel.refusal ? h(RefusalPanel, { r: sel.refusal, onDone: () => {
        rfq.refetch && rfq.refetch();
        refresh();
        setSel(null);
      } }) : sel && sel.standup ? h(StandupPanel, { d: sel.standup, onDone: () => {
        stq.refetch && stq.refetch();
        refresh();
        setSel(null);
      } }) : sel && sel.rereview ? h(ReReviewPanel, { ticket: sel.rereview.ticket, pr: sel.rereview.pr, onDone: () => {
        refresh();
        setSel(null);
      } }) : sel && sel.watcher ? sel.watcher.update ? h(UpdatePanel, { w: sel.watcher }) : h(WatcherPanel, { w: sel.watcher }) : sel && sel.merge ? h(MergePanel, { m: sel.merge }) : sel && sel.advisory ? h(AdvisoryPanel, { a: sel.advisory, onDone: () => {
        aq.refetch && aq.refetch();
        refresh();
        setSel(null);
      } }) : sel && sel.privileged ? h(PrivilegedPanel, { row: sel.privileged, card: sel.lendCard || null, openCard: sel.lendCard ? () => setSel({ key: "b" + sel.lendCard.id, card: sel.lendCard }) : null, onDone: () => {
        q2.refetch && q2.refetch();
        refresh();
        setSel(null);
      } }) : sel && sel.answer ? h(AnswerPanel, { a: sel.answer, onDone: () => {
        q2.refetch && q2.refetch();
        refresh();
        setSel(null);
      } }) : sel && sel.note ? h(TrackerNotePanel, { n: sel.note, onDone: () => {
        q2.refetch && q2.refetch();
        refresh();
        setSel(null);
      } }) : sel && sel.card ? h("div", { className: "flex h-full min-h-0 flex-col gap-2 p-3" }, detailHead(sel.card.title, { text: "blocked \xB7 needs your answer", color: "var(--ui-warning, #c98a00)" }, sel.card.id), h(BlockedCard, { c: sel.card, refresh: () => {
        refresh();
        setSel(null);
      } })) : sel && (sel.detail || sel.plugin) ? h(PluginPanel, { row: sel, onDone: () => {
        q2.refetch && q2.refetch();
        refresh();
        setSel(null);
      } }) : sel && sel.intent ? h(Detail, { id: sel.intent }) : null
    })
  );
}
function MergePanel({ m }) {
  return h(
    "div",
    { className: "flex flex-col gap-2 p-3 text-xs" },
    detailHead(`${m.repo} #${m.number}`, { text: "ready to merge", color: "var(--ui-success, #2a9d5c)" }, m.plugin ? `from ${m.plugin}` : ""),
    m.title ? h("div", { className: "font-medium" }, m.title) : null,
    h("div", null, `Tickets: ${m.tickets.join(", ")}`),
    // the link beside its button: where the desktop cannot open a browser (WSL without Windows interop), it can be pasted
    h(
      "div",
      { className: "flex items-center gap-2" },
      m.url ? btn("Open the PR", () => openWeb(m.url), { accent: true, title: m.url }) : null,
      m.url ? copyBtn(m.url, "PR link") : null
    ),
    h("div", { style: sub }, "Merge it on the forge when you are ready. The row leaves once the watch sees it merged; each of its tickets then gets its ticket-done row for your ack.")
  );
}
function PluginPanel({ row, initialDone = {}, onDone = null }) {
  const d = row.detail || {};
  const fields = (d.fields || []).filter((f) => f && f.label);
  const [done, setDone] = useState13(initialDone);
  const [busy, setBusy] = useState13(null);
  const pressed = [.../* @__PURE__ */ new Set([...done[row.id] || [], ...row.queued || [], ...d.pressed || []])];
  const actions = (d.actions || []).filter((a) => a && a.label);
  const act = async (a, i) => {
    const key = `${row.id}:${i}`;
    if (busy === key) return;
    setBusy(key);
    try {
      const r = await post("/plugin-act", { plugin: row.plugin, id: row.id, index: i });
      setDone((was) => ({ ...was, [row.id]: [...was[row.id] || [], i] }));
      if (r.applied) {
        if (r.ok === false) host.notifyError(new Error(r.out || "refused"), a.label);
        else host.notify({ kind: "success", title: a.label, message: r.out || "done" });
        if (onDone) onDone();
        return;
      }
      host.notify({ kind: "info", title: a.label, message: r.already ? `already queued for ${row.plugin}` : `queued for ${row.plugin} \u2014 it applies on the next pass` });
    } catch (e) {
      host.notifyError(e, `${a.label}: not queued`);
    } finally {
      setBusy(null);
    }
  };
  const dismiss = async () => {
    try {
      await post("/plugin-row-dismiss", { plugin: row.plugin, id: row.id });
      host.notify({ kind: "success", message: "row dismissed" });
      if (onDone) onDone();
    } catch (e) {
      host.notifyError(e, "Dismiss: not done");
    }
  };
  return h(
    "div",
    { className: "flex h-full min-h-0 flex-col gap-2 overflow-auto p-3 text-xs", "data-plugin-detail": row.plugin || "" },
    detailHead(d.title || row.what || row.plugin, d.status && d.status.text ? { text: d.status.text, color: d.status.color || row.color } : null, row.plugin || ""),
    row.pticket ? h(TicketTools, { ticket: row.pticket, part: "chat" }) : null,
    // a plugin writes its brief and what it said in markdown; the backend renders them (brief_html, said_html)
    d.brief ? d.brief_html ? h(RichMd, { html: d.brief_html }) : h("div", null, d.brief) : null,
    fields.length ? h(BriefGrid, { fields }) : null,
    // what came of the last press, written by the plugin on the row the button is on: a request it
    // refused has to be readable here, or pressing again is the only way to find out it was refused
    d.said ? h(
      "div",
      {
        "data-said": "1",
        className: "rounded px-2 py-1",
        style: { background: "rgba(127,127,127,.12)", color: /^refused/.test(d.said) ? "var(--ui-danger, #d33)" : "var(--ui-text-secondary)" }
      },
      d.said_html ? h(RichMd, { html: d.said_html }) : d.said
    ) : null,
    actions.length ? h(
      "div",
      { className: "flex flex-wrap items-center gap-2" },
      ...actions.map((a, i) => h(
        "span",
        {
          key: i,
          title: a.hint || "",
          "data-act": a.act ? String(i) : void 0,
          "data-act-queued": pressed.includes(i) ? String(i) : void 0
        },
        pressed.includes(i) ? h("span", { style: sub }, `${a.label} \xB7 queued`) : busy === `${row.id}:${i}` ? h("span", { style: sub }, `${a.label} \xB7 sending`) : btn(
          a.label,
          () => {
            if (a.act) act(a, i);
            else if (a.href) host.navigate(a.href);
          },
          { accent: i === 0, danger: Boolean(a.danger) }
        )
      ))
    ) : null,
    d.footer ? h("div", { style: sub }, d.footer) : null,
    !row.detail && !row.orphan ? h("div", { "data-row-plain": "1", style: sub }, `${row.plugin || "The plugin"} gave this row no page and no detail: it takes the row away when the matter is settled.`) : null,
    row.orphan ? h(
      "div",
      { "data-row-orphan": "1", className: "flex flex-wrap items-center gap-2" },
      h("span", { style: sub }, `${row.plugin || "The plugin"} is not installed any more, so nothing will take this row away.`),
      btn("Dismiss", dismiss, { danger: true, title: "remove this row from the Inbox" })
    ) : null
  );
}
function UpdatePanel({ w }) {
  const [busy, setBusy] = useState13(false);
  const [last, setLast] = useState13(null);
  const apply = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await post("/update-apply", {});
      setLast(r);
      host.notify({ kind: "success", title: "cockpit update", message: r.out || "updated" });
    } catch (e) {
      host.notifyError(e, "cockpit update failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex flex-col gap-2 p-3 text-xs" },
    detailHead("cockpit update", { text: "update available", color: "var(--ui-accent)" }, ""),
    h("div", null, w.reason),
    h("div", { className: "flex items-center gap-2" }, h("button", {
      type: "button",
      disabled: busy,
      onClick: apply,
      className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40",
      style: { background: "var(--ui-accent)", color: "#fff" }
    }, busy ? "updating" : "Update now")),
    last ? h("div", { style: { color: "var(--ui-success, #2a9d5c)" } }, last.out) : null,
    last ? h(NextLine, { next: last.next }) : null
  );
}
function WatcherPanel({ w }) {
  const [running, setRunning] = useState13(false);
  const run = async () => {
    if (running) return;
    setRunning(true);
    try {
      const r = await post("/watcher-run", { name: w.name });
      host.notify({ kind: "info", title: `watcher ${w.name}`, message: r.out });
    } catch (e) {
      host.notifyError(e, `${w.name}: run failed to start`);
    } finally {
      setRunning(false);
    }
  };
  const counts = `${w.fails} failure(s) in a row${w.last_error ? ` \xB7 last failed ${ago(w.last_error)} ago` : ""} \xB7 last success ${w.last_ok ? ago(w.last_ok) + " ago" : "never"}`;
  if (w.restart) return h(
    "div",
    { className: "flex flex-col gap-2 p-3 text-xs" },
    detailHead(w.name, { text: "restart needed", color: "var(--ui-accent)" }, ""),
    h("div", { className: "font-medium" }, w.reason),
    h(
      "div",
      { className: "flex items-center gap-2" },
      h("code", { className: "rounded px-1.5 py-0.5", style: { ...mono, background: "rgba(127,127,127,.12)" } }, w.restart),
      copyBtn(w.restart, "restart command")
    ),
    h("div", { style: sub }, "These pages are answered by code loaded before the change, so they may disagree with the files on disk (a pack written for the new code can fail to load here). The row leaves once the restart loads the new code.")
  );
  return h(
    "div",
    { className: "flex flex-col gap-2 p-3 text-xs" },
    detailHead("watcher " + w.name, { text: "failing", color: "var(--ui-danger, #d33)" }, w.last_ok || "no success yet"),
    h("div", { className: "font-medium", style: { color: "var(--ui-danger, #d33)" } }, w.reason || "not running properly"),
    h("div", { style: sub }, counts),
    h(
      "div",
      { className: "flex items-center gap-2" },
      running ? h("span", { style: sub }, "Running\u2026") : btn("Run now", run, { accent: true, title: "run the watcher's cron script now; the row leaves on its next successful run" }),
      h("span", { style: sub }, "The cron keeps running on its schedule. A network failure is tried again after two minutes by itself; anything else, fix the cause and Run now.")
    ),
    w.error ? h(Section, { title: "Stack trace", open: false, extra: copyBtn(w.error, "stack trace") }, h("pre", { className: "whitespace-pre-wrap", style: mono }, w.error)) : h("div", { style: sub }, "(no output recorded)")
  );
}

// src/views/tickets.js
import { useState as useState14, useEffect as useEffect9 } from "react";
function PlanView({ path, sections }) {
  const q2 = useQuery({ queryKey: ["cockpit", "plan", path], queryFn: () => CTX.rest("/qa-file?path=" + encodeURIComponent(path)), refetchInterval: 2e4, retry: 1 });
  if (q2.isLoading) return h("div", { className: "text-xs", style: sub }, "loading");
  if (q2.error) return h("div", { className: "text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  const stages = ["Decision", "Worker plan", "Delivered", "Tested", "Reviewed"];
  const done = (st) => sections.some((x) => x.toLowerCase().startsWith(st.toLowerCase()));
  return h(
    "div",
    { className: "flex flex-col gap-2" },
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2 text-xs" },
      h("span", { style: sub }, "trail:"),
      ...stages.map((st) => h("span", {
        key: st,
        className: "rounded px-1.5",
        style: {
          background: done(st) ? "rgba(42,157,92,.18)" : "rgba(127,127,127,.12)",
          color: done(st) ? "var(--ui-success, #2a9d5c)" : "var(--ui-text-tertiary)"
        }
      }, (done(st) ? "\u2713 " : "\xB7 ") + st)),
      h("span", { className: "ml-auto flex gap-1" }, btn("Open", () => openFile(path)), btn("Reveal", () => CTX.os.revealPath(path)))
    ),
    h(RichMd, { className: "rounded border px-3 py-1", style: { borderColor: stroke }, html: q2.data.html || "<pre>" + escapeHtml(q2.data.text || "") + "</pre>" })
  );
}
var TICKET_COLS = "9rem 6rem 8rem 5rem 5.5rem 1fr 4rem 7rem 4rem";
var phaseColor = (p) => p === "blocked" ? "var(--ui-danger, #d33)" : p === "running" || p === "in review" ? "var(--ui-accent)" : p === "at the gate" ? "var(--ui-success, #2a9d5c)" : p === "manual session" ? "var(--ui-warning, #c98a00)" : p.startsWith("done (unpushed") ? "var(--ui-warning, #c98a00)" : "var(--ui-text-tertiary)";
function TicketDetail({ ticket, refresh }) {
  const q2 = useQuery({ queryKey: ["cockpit", "ticket", ticket], queryFn: () => CTX.rest("/ticket?ticket=" + encodeURIComponent(ticket)), refetchInterval: 15e3, retry: 1 });
  const [tab, setTab] = useState14("overview");
  const [ask, setAsk] = useState14(null);
  const [force, setForce] = useState14(false);
  const [busy, setBusy] = useState14(false);
  const [note, setNote] = useState14("");
  const [slot, setSlot] = useState14("auto");
  const [cardId, setCardId] = useState14(null);
  const cq = useQuery({ queryKey: ["cockpit", "card-detail", cardId], queryFn: () => CTX.rest("/card-detail?id=" + cardId), enabled: Boolean(cardId), retry: 0 });
  useEffect9(() => {
    setTab("overview");
    setAsk(null);
    setCardId(null);
  }, [ticket]);
  if (q2.isLoading) return h("div", { className: "p-3 text-xs", style: sub }, "loading");
  if (q2.error) return h("div", { className: "p-3 text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  const t = q2.data;
  const act = async (path, body, okTitle) => {
    setBusy(true);
    try {
      const r = await post(path, body);
      host.notify({ kind: "success", title: okTitle, message: (r.out || "").slice(0, 600) });
      setAsk(null);
      refresh();
    } catch (e) {
      host.notifyError(e, okTitle + " failed");
    } finally {
      setBusy(false);
    }
  };
  const unpushed = (t.worktrees || []).filter((w) => w.unpushed).map((w) => `${w.repo} ${w.branch} (${w.unpushed})`);
  const human = t.slot && t.slot.owner === "human";
  const halted = t.halted;
  return h(
    "div",
    { className: "flex h-full flex-col gap-3 overflow-auto p-3" },
    detailHead(t.ticket, { text: halted ? "HALTED" : t.phase, color: halted ? "var(--ui-danger, #d33)" : phaseColor(t.phase) }, (halted ? `halted ${ago(halted.time)} ago${halted.note ? " \xB7 " + halted.note : ""} \xB7 ` : "") + (t.slot ? `slot ${t.slot.slot} \xB7 ${t.slot.owner.replace("lane:", "")}` : "no slot")),
    t.summary || t.plan_line ? h("div", { className: "text-xs", style: sub }, [t.summary, t.plan_line].filter(Boolean).join(" \xB7 ")) : null,
    (t.prs || []).length ? h("div", { className: "flex items-center gap-2 text-xs" }, h("span", { style: sub }, "PRs:"), prList(t.prs)) : null,
    h(
      "div",
      { className: "flex flex-wrap items-center gap-1.5" },
      (t.worktrees || []).length ? btn("Open IDE", () => openIde({ ticket: t.ticket }), { accent: true, title: "VS Code on the ticket workspace" }) : null,
      !human ? h("span", { className: "flex items-center gap-1" }, btn("Manual session", () => setAsk(ask === "session" ? null : "session"), { title: "take a slot yourself: stack + worktrees + own Chrome + VS Code; the lanes keep off it" })) : null,
      human ? btn("Close session", () => act("/session", { action: "close", slot: t.slot.slot }, "session closed"), { title: `cockpit session close ${t.slot.slot}` }) : null,
      human && !halted ? btn("Hand off to the lanes", () => act("/session", { action: "handoff", slot: t.slot.slot, ticket: t.ticket }, "handed off"), { title: "worker-N continues on this slot" }) : null,
      h("span", { className: "mx-1", style: sub }, "|"),
      halted ? btn("Resume", () => act("/ticket-resume", { ticket: t.ticket }, `${t.ticket} resumed`), { accent: true, title: "lift the halt: creators may start again; the closed cards stay closed \u2014 Reopen or Rework to continue" }) : btn("Halt", () => setAsk(ask === "halt" ? null : "halt"), { danger: true, title: "STOP everything on this ticket now: open cards closed (a running worker killed), intents at the gate held, nothing starts until Resume. Local only." }),
      (t.worktrees || []).length && !halted ? btn("Rework", () => setAsk(ask === "rework" ? null : "rework"), { title: "something is missing on the delivered PR: a worker card on the branch, tester and reviewer behind it" }) : null,
      !halted ? btn("Reopen", () => setAsk(ask === "reopen" ? null : "reopen"), { title: "restart the flow with your prompt and evidence; intake proposes and waits for your go" }) : null,
      btn("Archive", () => setAsk(ask === "archive" ? null : "archive"), { title: "local only: cards archived, worktrees removed, slot freed; keeps outbox + qa + branches" }),
      btn("Delete", () => setAsk(ask === "delete" ? null : "delete"), { danger: true, title: "local only: archive + outbox/qa folders + local branches" }),
      btn("Reveal qa", () => CTX.os.revealPath(t.qa && t.qa.dir ? t.qa.dir : t.worktrees && t.worktrees[0] ? t.worktrees[0].dir : ""))
    ),
    ask === "session" ? h(
      "div",
      { className: "flex items-center gap-2 rounded border p-2 text-xs", style: { borderColor: stroke } },
      h("span", null, "Open a manual session on slot"),
      selectBox(slot, setSlot, ["auto", "1", "2", "3"].map((v) => [v, v])),
      h("span", { style: sub }, "(stack from the seed data, worktrees, own Chrome, VS Code; takes ~1 min)"),
      h("button", { type: "button", disabled: busy, onClick: () => act("/session", { action: "open", ticket: t.ticket, slot }, "manual session open"), className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: "var(--ui-accent)", color: "#fff" } }, busy ? "working" : "Open"),
      btn("Cancel", () => setAsk(null))
    ) : null,
    ask === "halt" ? h(
      "div",
      { className: "flex flex-col gap-1 rounded border p-2 text-xs", style: { borderColor: "var(--ui-danger, #d33)" } },
      h("div", { className: "font-medium" }, `Halt ${t.ticket}: stop everything on it now`),
      h("div", { style: sub }, `Closes ${t.cards_open} open card(s) (a running worker is reclaimed: SIGTERM, then SIGKILL), holds ${t.intents_open} intent(s) at the gate for your decision, and marks the ticket so no card, rework, reopen or PR treatment can start until you press Resume. Worktrees, slot, outbox/${t.ticket} and qa/${t.ticket} stay. Nothing leaves this machine.`),
      h("input", { value: note, onChange: (e) => setNote(e.target.value), placeholder: "optional: why (goes on the cards and in the log)", className: "rounded border bg-transparent px-1.5 py-0.5", style: { borderColor: stroke } }),
      h("div", { className: "flex gap-1.5" }, h("button", { type: "button", disabled: busy, onClick: () => act("/ticket-halt", { ticket: t.ticket, confirm: t.ticket, note }, `${t.ticket} halted`), className: "rounded px-2.5 py-0.5 text-xs font-medium", style: { background: "var(--ui-danger, #d33)", color: "#fff" } }, busy ? "working" : "Halt now"), btn("Cancel", () => setAsk(null)))
    ) : null,
    ask === "reopen" ? h(ReopenForm, { ticket: t.ticket, onDone: () => setAsk(null) }) : null,
    ask === "rework" ? h(ReworkForm, { ticket: t.ticket, repos: (t.worktrees || []).map((w) => w.repo), delivered: (t.worktrees || []).filter((w) => w.unpushed || (t.prs || []).some((p) => p.repo === w.repo && p.state === "open")).map((w) => w.repo), onDone: () => setAsk(null) }) : null,
    ask === "archive" || ask === "delete" ? h(
      "div",
      { className: "flex flex-col gap-1 rounded border p-2 text-xs", style: { borderColor: ask === "delete" ? "var(--ui-danger, #d33)" : stroke } },
      h("div", { className: "font-medium" }, ask === "archive" ? `Archive ${t.ticket} on this machine` : `Delete everything local for ${t.ticket}`),
      h("div", { style: sub }, ask === "archive" ? `Archives ${t.cards_open} open card(s), removes ${(t.worktrees || []).length} worktree(s), frees slot ${t.slot ? t.slot.slot : "\u2013"}. Keeps outbox/${t.ticket}, qa/${t.ticket} and the local branches. Nothing leaves this machine.` : `Everything in Archive, plus outbox/${t.ticket} (${t.intents_total} intents), qa/${t.ticket} (${t.qa && t.qa.runs ? t.qa.runs + " runs" : "nothing"}) and the local branches. Origin, the forge, tracker are not touched.`),
      human ? h("div", { style: { color: "var(--ui-warning, #c98a00)" } }, `Slot ${t.slot.slot} is a manual session: close it first.`) : null,
      unpushed.length ? h("div", { style: { color: "var(--ui-warning, #c98a00)" } }, `Commits not on origin: ${unpushed.join(", ")}. ` + (ask === "delete" ? "Those branches are kept unless you tick force." : "Archive keeps the branches.")) : null,
      ask === "delete" && unpushed.length ? h("label", { className: "flex items-center gap-1" }, h("input", { type: "checkbox", checked: force, onChange: (e) => setForce(e.target.checked) }), "also delete the local branches with unpushed commits (irreversible)") : null,
      h("div", { className: "flex gap-1.5" }, h(
        "button",
        {
          type: "button",
          disabled: busy || human,
          onClick: () => act(
            ask === "archive" ? "/ticket-archive" : "/ticket-delete",
            { ticket: t.ticket, confirm: t.ticket, force: ask === "delete" && force },
            `${t.ticket} ${ask}d`
          ),
          className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40",
          style: { background: ask === "delete" ? "var(--ui-danger, #d33)" : "var(--ui-accent)", color: "#fff" }
        },
        busy ? "working" : ask === "archive" ? "Archive now" : "Delete now"
      ), btn("Cancel", () => setAsk(null)))
    ) : null,
    tabs(tab, setTab, [["overview", "Overview"], t.qa && t.qa.plan ? ["plan", "Plan"] : null, (t.worktrees || []).length ? ["diff", "Diff"] : null, ["evidence", "Evidence (QA runs)"]]),
    tab === "plan" ? h(PlanView, { path: t.qa.plan, sections: t.qa.plan_sections || [] }) : tab === "evidence" ? h(Evidence, { ticket: t.ticket }) : tab === "diff" ? h("div", { className: "flex flex-col gap-3" }, ...(t.worktrees || []).map((w) => h("div", { key: w.repo }, h("div", { className: "text-xs font-medium mb-1" }, `${w.repo} \xB7 ${w.branch}`), h(DiffPanel, { params: { ticket: t.ticket, repo: w.repo }, defaultMode: "origin" })))) : h(
      "div",
      { className: "flex flex-col gap-2 text-xs" },
      h(TicketTools, { ticket: t.ticket, part: "chat" }),
      h(Section, { title: "Brief", open: true, color: "var(--ui-accent)" }, t.brief ? h(RichMd, { html: t.brief }) : h("div", { style: sub }, t.qa && t.qa.plan ? "the plan has no Brief section (older plan format)" : "no plan yet: intake has not had its go")),
      h(TicketTools, { ticket: t.ticket, part: "demo" }),
      (t.plan_parts || []).length ? h(
        Section,
        { title: `Plan trail \xB7 ${(t.plan_parts || []).map((x) => x.title).join(" \xB7 ")}`, extra: btn("Open plan", () => openFile(t.qa.plan)) },
        ...(t.plan_parts || []).map((part) => h(Section, { key: part.title, title: part.title }, h(RichMd, { html: part.html })))
      ) : null,
      h(
        Section,
        { title: `Cards (${t.cards_total})` },
        h("div", { style: sub, className: "mb-1" }, "click one to read its comments and result"),
        ...(t.card_list || []).slice().reverse().map((c) => h(
          "div",
          {
            key: c.id,
            className: "flex gap-2 cursor-pointer cockpit-row rounded px-1",
            onClick: () => setCardId(cardId === c.id ? null : c.id),
            style: { background: cardId === c.id ? "var(--ui-bg-selected, rgba(127,127,127,.15))" : "transparent" }
          },
          h("span", { style: {
            color: c.status === "blocked" ? "var(--ui-danger, #d33)" : c.status === "done" ? "var(--ui-success, #2a9d5c)" : c.status === "archived" ? "var(--ui-text-quaternary)" : "var(--ui-accent)",
            minWidth: "5rem"
          } }, c.status),
          h("span", { style: { ...mono, ...sub } }, c.id),
          h("span", { className: "truncate" }, c.title),
          h("span", { style: sub }, c.assignee)
        )),
        !(t.card_list || []).length ? h("div", { style: sub }, "none") : null,
        cardId ? h("div", { className: "rounded border p-2 mt-1", style: { borderColor: stroke, maxHeight: "55vh", overflow: "auto" } }, cq.data ? h(CardView, { c: cq.data }) : h("div", { style: sub }, "loading")) : null
      ),
      h(
        Section,
        { title: `Outbox (${t.intents_total})` },
        ...(t.intent_list || []).map((i) => h(
          "div",
          { key: i.id, className: "flex gap-2" },
          h(
            "span",
            { style: { minWidth: "5rem", color: i.status === "endorsed" ? "var(--ui-success, #2a9d5c)" : i.status === "pending" ? "var(--ui-text-tertiary)" : "var(--ui-text-quaternary)" } },
            i.status
          ),
          h("span", { style: mono }, i.id),
          h("span", { style: sub }, i.type)
        )),
        !(t.intent_list || []).length ? h("div", { style: sub }, "none") : null
      ),
      h(
        Section,
        { title: "Worktrees" + (unpushed.length ? ` \xB7 ${unpushed.length} with unpushed commits` : "") },
        ...(t.worktrees || []).map((w) => h(
          "div",
          { key: w.repo, className: "flex gap-2" },
          h("span", { style: mono }, w.repo),
          h("span", { style: mono }, w.branch),
          h(
            "span",
            { style: { color: w.unpushed ? "var(--ui-accent)" : "var(--ui-text-tertiary)" } },
            `${w.unpushed} unpushed`
          ),
          h("span", { style: { color: w.dirty ? "var(--ui-warning, #c98a00)" : "var(--ui-text-tertiary)" } }, `${w.dirty} dirty`),
          h("span", { style: sub }, w.dir)
        )),
        !(t.worktrees || []).length ? h("div", { style: sub }, "none") : null
      ),
      t.qa && t.qa.dir ? h("div", { style: sub }, `QA: ${t.qa.runs} run(s), ${Math.round(t.qa.size / 1e3)} KB \xB7 ${t.qa.dir}`) : null
    )
  );
}
function Tickets() {
  const q2 = useQuery({ queryKey: ["cockpit", "tickets"], queryFn: () => CTX.rest("/tickets"), refetchInterval: 3e4, retry: 1 });
  const qc = useQueryClient();
  const [selected, setSelected] = useState14(null);
  const [showAll, setShowAll] = useState14(false);
  if (q2.isLoading) return h("div", { className: "p-3 text-xs", style: sub }, "loading");
  if (q2.error) return h("div", { className: "p-3 text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  const all = q2.data.tickets || [];
  const rows = showAll ? all : all.filter((t) => t.phase !== "evidence only");
  const refresh = () => qc.invalidateQueries({ queryKey: ["cockpit"] });
  return h(SplitList, {
    cols: TICKET_COLS,
    labels: [
      "ticket",
      "flow",
      "status",
      "cards",
      ">duration",
      "worktrees (unpushed\u2191 dirty\u270E)",
      "slot",
      "outbox \xB7 qa",
      h(
        "label",
        {
          className: "flex items-center justify-end gap-1 cursor-pointer normal-case tracking-normal",
          title: "tickets that only have evidence folders"
        },
        h("input", { type: "checkbox", checked: showAll, onChange: (e) => setShowAll(e.target.checked) }),
        "all"
      )
    ],
    rows,
    selected,
    onSelect: setSelected,
    empty: "No tickets in flight on this machine.",
    renderRow: (t) => {
      const ic = t.intents || {};
      const cc = t.cards || {};
      return trow(TICKET_COLS, { key: t.ticket, onClick: () => setSelected(selected === t.ticket ? null : t.ticket), selected: selected === t.ticket, children: [
        h("div", { key: "t", className: "font-medium truncate", title: t.summary || "" }, t.ticket, t.summary ? h("span", { className: "font-normal", style: sub }, " " + t.summary) : null),
        h("div", { key: "f", className: "truncate", style: sub, title: (t.flows || []).length > 1 ? "flows, in order: " + t.flows.join(" \u2192 ") : "the flow the ticket came from" }, t.flow ? t.flow + ((t.flows || []).length > 1 ? ` +${t.flows.length - 1}` : "") : "\u2013"),
        h("div", { key: "p", className: "truncate", style: { color: phaseColor(t.phase) } }, t.phase),
        h("div", { key: "c", title: Object.entries(cc).map(([k, v]) => `${k}: ${v}`).join(", ") }, t.cards_total ? `${t.cards_open}/${t.cards_total}` + (cc.blocked ? " \u26A0" : "") : "\u2013"),
        h(
          "div",
          { key: "d", className: "text-right", style: {
            fontVariantNumeric: "tabular-nums",
            color: t.cards_open ? "var(--ui-accent)" : void 0
          }, title: t.started ? `${t.cards_open ? "running" : "ran"} since ${t.started.replace("T", " ").slice(0, 16)}${t.ended ? " until " + t.ended.replace("T", " ").slice(0, 16) : ""} \xB7 the lanes' run time ${fmtDur(t.run_s)}` : "no card yet" },
          t.started ? fmtDur(t.duration_s) : "\u2013"
        ),
        h("div", { key: "w", className: "truncate" }, (t.worktrees || []).length ? (t.worktrees || []).map((w) => h(
          "span",
          { key: w.repo, className: "mr-2" },
          h("span", { style: mono }, w.repo),
          h("span", { style: { color: w.unpushed ? "var(--ui-accent)" : "var(--ui-text-tertiary)" } }, ` ${w.unpushed}\u2191`),
          w.dirty ? h("span", { style: { color: "var(--ui-warning, #c98a00)" } }, ` ${w.dirty}\u270E`) : null
        )) : h("span", { style: sub }, "\u2013")),
        h("div", { key: "s", style: sub }, t.slot ? `${t.slot.slot} ${t.slot.owner === "human" ? "\u{1F464}" : ""}` : "\u2013"),
        h("div", { key: "o", className: "truncate", title: "outbox open/total \xB7 endorsed \u2713 \xB7 published \u2197 \xB7 qa runs" }, t.intents_total ? `${t.intents_open}/${t.intents_total}` + (ic.endorsed ? ` ${ic.endorsed}\u2713` : "") + (ic.published ? ` ${ic.published}\u2197` : "") : "\u2013", h("span", { style: sub }, t.qa && t.qa.runs ? ` \xB7 qa ${t.qa.runs}` : "")),
        h("div", { key: "a", className: "text-right truncate", style: sub }, t.last_card ? ago(t.last_card) : "")
      ] });
    },
    detail: selected ? h(TicketDetail, { ticket: selected, refresh }) : null
  });
}

// src/views/usage.js
import { useState as useState15 } from "react";
var fmtN = (n) => n >= 1e9 ? (n / 1e9).toFixed(2) + "B" : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e8 ? 0 : n >= 1e7 ? 1 : 2) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n || 0);
var fmt$ = (c) => c ? "$" + c.toFixed(2) : "\u2013";
var USAGE_COLS = "1fr 4rem 5rem 5rem 5rem 5.5rem 5rem 5.5rem 4.5rem";
var PERIOD_LABEL = { today: "today", week: "last 7 days", month: "last 30 days", all: "all time" };
var VERDICT_COLOR = { ahead: "var(--ui-warning, #c98a00)", on: "var(--ui-success, #2a9d5c)", behind: "var(--ui-accent)" };
var pctOf = (x) => x == null ? "\u2013" : Math.round(x * 100) + "%";
function PaceBar({ w, target }) {
  const clamp = (x) => Math.max(0, Math.min(100, x || 0));
  return h(
    "div",
    { className: "flex flex-col gap-1 text-xs" },
    h(
      "div",
      { className: "grid items-center gap-3", style: { gridTemplateColumns: "9rem 1fr 11rem" } },
      h("div", { className: "truncate", style: sub }, w.name),
      h(
        "div",
        { className: "relative h-2.5 rounded", style: { background: "rgba(127,127,127,.18)" }, title: `used ${w.used}% \xB7 ideal by now ${w.ideal}% \xB7 target ${target}%` },
        h("div", { className: "h-2.5 rounded", style: { width: clamp(w.used) + "%", background: VERDICT_COLOR[w.verdict] || "var(--ui-accent)" } }),
        h("div", { className: "cockpit-pace-ideal absolute", title: `ideal by now: ${w.ideal}%`, style: { left: clamp(w.ideal) + "%", top: "-3px", bottom: "-3px", width: "2px", background: "var(--ui-text-primary, #222)" } }),
        h("div", { className: "cockpit-pace-target absolute", title: `target: ${target}%`, style: { left: clamp(target) + "%", top: "-4px", bottom: "-4px", borderLeft: "2px dashed var(--ui-danger, #d33)" } })
      ),
      h("div", { className: "text-right whitespace-nowrap", style: { fontVariantNumeric: "tabular-nums" } }, h("span", { className: "font-medium" }, `${w.used}%`), h("span", { style: sub }, ` \xB7 ideal ${w.ideal}% \xB7 ${w.verdict}`))
    ),
    h("div", { style: sub }, w.sentence || "")
  );
}
function PacePanel() {
  const [round, setRound] = useState15(0);
  const q2 = useQuery({ queryKey: ["cockpit", "pace", round], queryFn: () => CTX.rest(round ? "/pace?fresh=1" : "/pace"), refetchInterval: 3e5, retry: 1 });
  const p = q2.data;
  if (!p || !p.target_pct) return null;
  const inp = p.inputs || {};
  const e = p.efficiency || {};
  const fact = (label, value) => h("div", { className: "flex gap-1" }, h("span", { style: sub }, label + ":"), h("span", { style: { fontVariantNumeric: "tabular-nums" } }, value));
  return h(
    "div",
    { className: "flex flex-col gap-2 rounded border px-3 py-2", style: { borderColor: stroke } },
    h(
      "div",
      { className: "flex items-center gap-3" },
      h("div", { className: "cockpit-head" }, `plan pace${p.provider ? " \xB7 " + p.provider : ""}`),
      h("span", { className: "text-xs", style: sub }, "insight only: nothing here holds or starts a card"),
      h("span", { className: "ml-auto" }, btn("Recalculate", () => setRound((r) => r + 1), { title: "read the plan again now, skipping the five-minute cache" }))
    ),
    p.error ? h("div", { className: "text-xs", style: { color: "var(--ui-warning, #c98a00)" } }, `${p.stale ? "last good reading shown; " : ""}${p.error}`) : null,
    ...(p.windows || []).map((w) => h(PaceBar, { key: w.name, w, target: p.target_pct })),
    p.binding ? h("div", { className: "text-xs font-medium" }, `${p.binding} binds: ${p.verdict === "ahead" ? "ahead of pace" : p.verdict === "behind" ? "behind pace (unused capacity)" : "on pace"}`) : null,
    h(
      "div",
      { className: "flex flex-wrap gap-x-4 gap-y-1 text-xs" },
      fact("target (quota ceiling)", `${p.target_pct}%`),
      fact("active hours", inp.schedule || "all hours"),
      fact("peak hours", inp.peak_hours || "not counted"),
      fact("on-pace band", `\xB1${inp.band || 3} points`),
      fact("read at", (p.read_at || "").slice(0, 16).replace("T", " ") + (p.stale ? " (stale)" : ""))
    ),
    h(
      "div",
      { className: "flex flex-wrap gap-x-4 gap-y-1 text-xs" },
      fact("tokens this week", fmtN(e.tokens || 0)),
      fact("tokens per card run", e.tokens_per_run == null ? "\u2013" : fmtN(e.tokens_per_run)),
      fact("card runs that failed or were retried", pctOf(e.wasted_share)),
      fact("Opus share of tokens", pctOf(e.opus_share)),
      fact("cache reads in input", pctOf(e.cache_read_share))
    )
  );
}
function Usage() {
  const [period, setPeriod] = useState15("week");
  const [by, setBy] = useState15("who");
  const [stackOnly, setStackOnlyRaw] = useState15(() => CTX.storage.get("usageStackOnly", true));
  const setStackOnly = (v) => {
    setStackOnlyRaw(v);
    CTX.storage.set("usageStackOnly", v);
  };
  const scope = stackOnly ? "hermes" : "all";
  const q2 = useQuery({ queryKey: ["cockpit", "usage", period, by, scope], queryFn: () => CTX.rest(`/usage?period=${period}&by=${by}&scope=${scope}`), refetchInterval: 6e4, retry: 1 });
  if (q2.isLoading) return h("div", { className: "p-3 text-xs", style: sub }, "adding up every session");
  if (q2.error) return h("div", { className: "p-3 text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  const d = q2.data;
  const T = d.totals || {};
  const periodOf = (k) => T[k] || { total: 0, sessions: 0, cost: 0, output: 0, cache_read: 0 };
  const num2 = (n, cls) => h("div", { className: "text-right " + (cls || ""), style: { fontVariantNumeric: "tabular-nums" } }, n);
  const bar = (w) => h(
    "div",
    { className: "grid items-center gap-3 text-xs", style: { gridTemplateColumns: "9rem 1fr 5rem 10rem" } },
    h("div", { className: "truncate", style: sub }, w.name),
    h("div", { className: "h-2 rounded", style: { background: "rgba(127,127,127,.18)" } }, h("div", { className: "h-2 rounded", style: { width: w.used + "%", background: w.used > 85 ? "var(--ui-danger, #d33)" : w.used > 60 ? "var(--ui-warning, #c98a00)" : "var(--ui-success, #2a9d5c)" } })),
    h("div", { className: "text-right whitespace-nowrap font-medium", style: { fontVariantNumeric: "tabular-nums" } }, `${w.used}% used`),
    h("div", { className: "text-right whitespace-nowrap", style: { ...sub, fontVariantNumeric: "tabular-nums" }, title: "resets at " + w.resets_at }, `resets in ${w.resets_in}`)
  );
  const periodCell = (k, label) => h(
    "div",
    { className: "rounded border px-3 py-2 text-xs cursor-pointer", onClick: () => setPeriod(k), style: { borderColor: period === k ? "var(--ui-accent)" : stroke, background: period === k ? "rgba(56,139,253,.06)" : "transparent" } },
    h("div", { className: "cockpit-head" }, label),
    h("div", { className: "text-sm font-medium", style: { fontVariantNumeric: "tabular-nums" } }, fmtN(periodOf(k).total) + " tokens"),
    h("div", { style: sub }, `${periodOf(k).sessions} sessions \xB7 est ${fmt$(periodOf(k).cost)} \xB7 ${fmtN(periodOf(k).output)} out \xB7 ${fmtN(periodOf(k).cache_read)} cached`)
  );
  const sp = d.split || { hermes: 0, outside: 0, hermes_pct: 0, total: 0, hermes_sessions: 0, outside_sessions: 0 };
  const pct = sp.hermes_pct || 0;
  const periodLabel = PERIOD_LABEL[period] || period;
  const seg2 = (label, color, value, p) => h(
    "span",
    { className: "flex items-center gap-1 whitespace-nowrap" },
    h("span", { className: "inline-block h-2 w-2 rounded-sm", style: { background: color } }),
    h("span", { style: sub }, label),
    h("span", { className: "font-medium", style: { fontVariantNumeric: "tabular-nums" } }, `${p}%`),
    h("span", { style: { ...sub, fontVariantNumeric: "tabular-nums" } }, `\xB7 ${fmtN(value)}`)
  );
  const splitBar = h(
    "div",
    { className: "flex flex-col gap-1 rounded border px-3 py-2", style: { borderColor: stroke } },
    h(
      "div",
      { className: "flex items-center gap-3" },
      h("div", { className: "cockpit-head" }, `where the tokens went \xB7 ${periodLabel}`),
      h(
        "div",
        { className: "ml-auto flex items-center gap-4 text-xs" },
        seg2("Hermes stack", "var(--ui-accent)", sp.hermes, pct),
        seg2("outside (your coding tool)", "rgba(127,127,127,.55)", sp.outside, Math.round((100 - pct) * 10) / 10),
        h("span", { style: { ...sub, fontVariantNumeric: "tabular-nums" } }, `${fmtN(sp.total)} total`)
      )
    ),
    h(
      "div",
      { className: "flex h-2.5 w-full overflow-hidden rounded", style: { background: "rgba(127,127,127,.18)" } },
      h("div", { className: "h-2.5", style: { width: pct + "%", background: "var(--ui-accent)" }, title: `Hermes stack: ${fmtN(sp.hermes)} tokens in ${sp.hermes_sessions} sessions` }),
      h("div", { className: "h-2.5", style: { width: 100 - pct + "%", background: "rgba(127,127,127,.55)" }, title: `outside Hermes: ${fmtN(sp.outside)} tokens in ${sp.outside_sessions} sessions` })
    )
  );
  return h(
    "div",
    { className: "flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3" },
    h(
      "div",
      { className: "flex items-center gap-3 text-xs" },
      h("label", { className: "flex items-center gap-1 cursor-pointer" }, h("input", { type: "checkbox", checked: stackOnly, onChange: (e) => setStackOnly(e.target.checked) }), "Hermes stack only"),
      h("span", { style: sub }, stackOnly ? "the numbers below count the lanes, the concierge and the lanes' coding tool runs; your own coding tool sessions are left out" : "the numbers below count everything, your own coding tool sessions included")
    ),
    (d.windows || []).length ? h("div", { className: "flex flex-col gap-1 rounded border px-3 py-2", style: { borderColor: stroke } }, h("div", { className: "cockpit-head" }, "provider plan windows"), ...(d.windows || []).map((w) => bar(w))) : null,
    h(PacePanel, {}),
    h("div", { className: "flex flex-col gap-1 rounded border px-3 py-2", style: { borderColor: stroke } }, h("div", { className: "cockpit-head" }, "providers"), ...(d.providers || []).map((p) => h(
      "div",
      { key: p.provider, className: "flex items-center gap-3 text-xs" },
      h("span", { className: "font-medium" }, p.provider),
      h("span", { style: sub }, `${p.turns || 0} turns \xB7 ${fmtDur(p.time || 0)}`),
      p.cost == null ? null : h("span", { style: sub }, (p.approximate ? "\u2248 " : "") + fmt$(p.cost)),
      p.plan_window ? h("span", { style: sub }, `window ${p.plan_window}`) : null
    ))),
    stackOnly ? null : splitBar,
    h("div", { className: "grid gap-2", style: { gridTemplateColumns: "repeat(4, 1fr)" } }, periodCell("today", "today"), periodCell("week", "last 7 days"), periodCell("month", "last 30 days"), periodCell("all", "all time")),
    h("div", { className: "flex items-center gap-2 text-xs" }, h("span", { style: sub }, `${PERIOD_LABEL[period] || period}, by`), tabs(by, setBy, [["who", "lane"], ["ticket", "origin"], ["day", "day"], ["model", "model"]]), h("span", { className: "ml-auto", style: sub }, d.note)),
    h(
      "div",
      { className: "cockpit-scroll rounded border", style: { borderColor: stroke } },
      thead(USAGE_COLS, [by === "who" ? "lane / source" : by === "ticket" ? "origin (ticket or where it came from)" : by, ">sessions", ">time", ">input", ">output", ">cache read", ">cache write", ">total", ">est cost (\u2248 list price)"]),
      ...(d.groups || []).map((g) => trow(USAGE_COLS, {
        key: g.key,
        children: [
          h("div", { key: "k", className: "truncate font-medium", style: by === "model" ? mono : {} }, g.key),
          num2(g.sessions),
          h("div", {
            key: "d",
            className: "text-right",
            style: { fontVariantNumeric: "tabular-nums" },
            title: "running time of the sessions (start to end, or to the last activity)"
          }, fmtDur(g.seconds)),
          num2(fmtN(g.input)),
          num2(fmtN(g.output)),
          num2(fmtN(g.cache_read)),
          num2(fmtN(g.cache_write)),
          num2(fmtN(g.total), "font-medium"),
          num2(fmt$(g.cost))
        ]
      })),
      !(d.groups || []).length ? h("div", { className: "p-4 text-center text-xs", style: sub }, "nothing in this period") : null
    ),
    h(
      "details",
      { className: "text-xs" },
      h("summary", { className: "cursor-pointer", style: sub }, `recent sessions in this period (${(d.recent || []).length})`),
      h(
        "div",
        { className: "cockpit-scroll mt-1 rounded border", style: { borderColor: stroke } },
        thead("8rem 7rem 6rem 1fr 5rem 6rem 5rem", ["when", "who", "ticket", "session", ">time", ">tokens", ">est"]),
        ...(d.recent || []).map((r, i) => trow(
          "8rem 7rem 6rem 1fr 5rem 6rem 5rem",
          { key: i, children: [
            h("div", { key: "w", style: sub }, r.when ? r.when.slice(5, 16).replace("T", " ") : ""),
            h("div", { key: "o", style: mono }, r.who),
            h("div", { key: "t" }, r.ticket || ""),
            h("div", { key: "d", className: "text-right", style: { fontVariantNumeric: "tabular-nums" } }, fmtDur(r.seconds)),
            h("div", { key: "s", className: "truncate", title: r.title }, r.title),
            num2(fmtN(r.input + r.output + r.cache_read + r.cache_write)),
            num2((r.estimate ? "\u2248" : "") + fmt$(r.cost))
          ] }
        ))
      )
    )
  );
}

// src/views/vault.js
import { useState as useState17 } from "react";

// src/views/vault-record.js
import { useState as useState16 } from "react";
var KIND_FIELDS = {
  login: [["title", "Title (optional)", "text"], ["origin", "Website (URL)", "url"], ["email", "Username", "text"], ["secret", "Password", "secret"], ["otp", "Authenticator key (2FA, optional)", "secret"], ["lane", "Lane that fills it (optional)", "text"]],
  key: [["title", "Name", "text"], ["origin", "Service (URL, optional)", "url"], ["secret", "Key or token", "secret"]],
  note: [["title", "Title", "text"], ["secret", "Note", "area"]]
};
var NEEDS = { login: ["origin", "email"], key: ["title"], note: ["title"] };
function RecordForm({ vault, kinds, record, placed, onDone, onCancel }) {
  const editing = Boolean(record);
  const [kind, setKind] = useState16(record ? record.kind : "login");
  const [f, setF] = useState16(() => ({ title: record?.title || "", origin: record?.origin || "", email: record?.email || "", lane: record?.lane || "", tags: (record?.tags || []).join(", "), secret: "", otp: "", notes: "" }));
  const [notesTouched, setNotesTouched] = useState16(false);
  const [busy, setBusy] = useState16(false);
  const qc = useQueryClient();
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const missing = NEEDS[kind].filter((k) => !String(f[k] || "").trim());
  const ok = missing.length === 0 && (editing || kind !== "note" || f.secret.trim() || f.notes.trim());
  const loadNotes = async () => {
    try {
      const r = await post("/vault-reveal", { vault, id: record.id, field: "notes" });
      set("notes", r.value || "");
      setNotesTouched(true);
    } catch (e) {
      host.notifyError(e, "notes could not be loaded");
    }
  };
  const save = async () => {
    if (!ok || busy) return;
    setBusy(true);
    const body = { vault, kind, title: f.title, origin: f.origin, email: f.email, tags: f.tags, ...placed && kind === "login" ? { lane: f.lane } : {} };
    if (editing) body.id = record.id;
    if (f.secret) body.secret = f.secret;
    if (f.otp) body.otp = f.otp.replace(/\s+/g, "");
    if (notesTouched) body.notes = f.notes;
    try {
      const r = await post("/vault-save", body);
      host.notify({ kind: "success", title: "Vault", message: r.out });
      qc.invalidateQueries({ queryKey: ["cockpit"] });
      onDone(r.id);
    } catch (e) {
      host.notifyError(e, "saving failed");
    } finally {
      setF((p) => ({ ...p, secret: "", otp: "" }));
      setBusy(false);
    }
  };
  const input = (props) => h("input", { ...props, className: "w-full rounded border bg-transparent px-2 py-1 text-xs", style: { borderColor: stroke } });
  const field = ([k, label, type]) => h(
    "label",
    { key: k, className: "flex flex-col gap-0.5" },
    h("span", { style: sub }, label + (editing && type === "secret" ? " \u2014 blank keeps it" : "")),
    type === "area" ? h(ClearableTextarea, { rows: 6, value: f[k], onChange: (e) => set(k, e.target.value), autoComplete: "off", spellCheck: false, className: "rounded border bg-transparent px-2 py-1 text-xs", style: { borderColor: stroke } }) : h(
      "div",
      { className: "flex items-center gap-1" },
      input({ type: type === "secret" ? "password" : type === "url" ? "url" : "text", value: f[k], onChange: (e) => set(k, e.target.value), autoComplete: type === "secret" ? "new-password" : "off", spellCheck: false }),
      k === "secret" && kind === "login" ? btn("Generate", () => set("secret", genPassword()), { title: "a random 20-character password" }) : null
    )
  );
  return h(
    "div",
    { className: "cockpit-vault-form flex flex-col gap-2 p-3 text-xs" },
    h("div", { className: "cockpit-head" }, editing ? `Change ${record.title}` : "New record"),
    editing ? null : h("div", { className: "flex items-center gap-1" }, ...(kinds || []).map((k) => btn(k.label, () => setKind(k.name), { accent: kind === k.name }))),
    ...KIND_FIELDS[kind].filter(([k]) => k !== "lane" || placed).map(field),
    h("label", { className: "flex flex-col gap-0.5" }, h("span", { style: sub }, "Tags (comma separated)"), input({ type: "text", value: f.tags, onChange: (e) => set("tags", e.target.value), autoComplete: "off" })),
    kind === "note" ? null : h(
      "label",
      { className: "flex flex-col gap-0.5" },
      h("span", { className: "flex items-center gap-2", style: sub }, "Notes", editing && record.has_notes && !notesTouched ? btn("Load current notes", loadNotes, { title: "opens the stored notes (the reveal is logged)" }) : null, editing && record.has_notes && !notesTouched ? h("span", null, "blank keeps them") : null),
      h(ClearableTextarea, { rows: 3, value: f.notes, onChange: (e) => {
        set("notes", e.target.value);
        setNotesTouched(true);
      }, spellCheck: false, className: "rounded border bg-transparent px-2 py-1 text-xs", style: { borderColor: stroke } })
    ),
    h("div", { style: sub }, "Sealed to the vault key on this machine. The secret is never shown in a list and is cleared from this form after saving."),
    h(
      "div",
      { className: "flex items-center gap-2" },
      h("button", { type: "button", disabled: !ok || busy, onClick: save, className: "rounded px-3 py-1 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-accent)", color: "#fff" } }, busy ? "working" : editing ? "Save changes" : "Add to vault"),
      btn("Cancel", onCancel)
    )
  );
}

// src/views/vault.js
var DANGER2 = "var(--ui-danger, #d33)";
var COLS = "5.5rem minmax(0,1.4fr) minmax(0,1.4fr) minmax(0,1fr) 4rem";
var q = (o) => Object.entries(o).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
function Danger({ label, what, explain, run }) {
  const [ask, setAsk] = useState17(false);
  if (!ask) return btn(label, () => setAsk(true), { danger: true });
  return h(
    "div",
    { className: "flex flex-col gap-1 rounded border px-2 py-1.5 text-xs", style: { borderColor: DANGER2 } },
    h("div", null, explain),
    h(
      "div",
      { className: "flex items-center gap-2" },
      h("button", { type: "button", onClick: () => {
        setAsk(false);
        run();
      }, className: "rounded px-2 py-0.5 text-xs font-medium", style: { background: DANGER2, color: "#fff" } }, `Delete ${what} now`),
      btn("Cancel", () => setAsk(false))
    )
  );
}
function RecordDetail({ vault, id, state, vaults, placed, onEdit, onGone }) {
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["cockpit", "vault-record", vault, id], queryFn: () => CTX.rest(`/vault-record?${q({ vault, id })}`), retry: 0 });
  const [to, setTo] = useState17("");
  if (d.error) return h("div", { className: "p-3 text-xs", style: { color: DANGER2 } }, String(d.error.message || d.error));
  if (!d.data) return h("div", { className: "p-3 text-xs", style: sub }, "loading");
  const r = d.data.record;
  const kind = (state.kinds || []).find((k) => k.name === r.kind) || { label: r.kind, secret_label: "secret" };
  const refresh = () => qc.invalidateQueries({ queryKey: ["cockpit"] });
  const reveal = (field, index) => () => post("/vault-reveal", { vault, id, field, ...index === void 0 ? {} : { index } });
  const act = async (path, body, title, gone) => {
    try {
      const x = await post(path, body);
      host.notify({ kind: "success", title, message: x.out });
      refresh();
      if (gone) onGone();
    } catch (e) {
      host.notifyError(e, `${title} failed`);
    }
  };
  const off = state.locked;
  const why = state.reason;
  const card = (state.key || {}).needs === "card";
  const SF = (props) => h(SecretField, { ...props, disabled: off, why, card });
  const row = (label, value) => [h("span", { key: "l" + label, style: sub }, label), value];
  const rows = [
    ...row("type", h("span", null, kind.label)),
    ...r.origin ? row(r.kind === "login" ? "website" : "service", h("span", { className: "flex items-center gap-2" }, h("span", { style: mono }, r.origin), copyBtn(r.origin, "website"))) : [],
    ...r.email ? row("username", h("span", { className: "flex items-center gap-2" }, h("span", { style: mono }, r.email), copyBtn(r.email, "username"))) : [],
    ...r.has_secret ? row(kind.secret_label, SF({ label: kind.secret_label, reveal: reveal("secret"), multiline: r.kind === "note" })) : [],
    ...r.two_factor ? row("2FA code", SF({ label: "2FA code", reveal: reveal("code") })) : [],
    ...r.two_factor ? row("2FA key", SF({ label: "2FA key", reveal: reveal("otp") })) : [],
    ...r.has_notes ? row("notes", SF({ label: "notes", reveal: reveal("notes"), multiline: true })) : [],
    ...r.lane ? row("lane", h("span", null, r.lane)) : [],
    ...row("tags", r.tags && r.tags.length ? h("span", { className: "flex flex-wrap gap-1" }, ...r.tags.map((t) => h("span", { key: t, className: "rounded border px-1.5", style: { borderColor: stroke } }, t))) : h("span", { style: sub }, "none")),
    ...row("changed", h("span", { style: sub }, `${ago(r.updated)} ago \xB7 created ${ago(r.created)} ago`))
  ];
  const others = vaults.filter((v) => v.name !== vault);
  return h(
    "div",
    { className: "flex flex-col gap-2 p-3 text-xs" },
    detailHead(r.title, null, vault),
    off ? h("div", { style: { color: "var(--ui-warning, #c98a00)" } }, why) : null,
    h("div", { className: "grid items-center gap-x-3 gap-y-1.5", style: { gridTemplateColumns: "6rem 1fr" } }, ...rows),
    placed ? h(Section, { title: `On seats (${d.data.seats.length})`, open: true }, d.data.seats.length ? h("div", { className: "flex flex-col gap-0.5" }, ...d.data.seats.map((s) => h("div", { key: s.lane + s.kind }, `${s.lane} \xB7 ${s.kind === "shared" ? "shared" : "its own login"}`)), h("div", { style: sub }, "Cockpit keeps these copies in step when you save, move or delete.")) : h("div", { style: sub }, "no seat holds a copy")) : null,
    r.history.length ? h(Section, { title: `Previous passwords (${r.history.length})` }, h("div", { className: "flex flex-col gap-1" }, ...r.history.map((x, i) => h("div", { key: i, className: "flex items-center gap-3" }, h("span", { style: sub }, `replaced ${ago(x.until)} ago`), SF({ label: "old password", reveal: reveal("history", i) }))).reverse())) : null,
    d.data.audit.length ? h(Section, { title: "Activity" }, h("div", { className: "flex flex-col gap-0.5" }, ...d.data.audit.map((a, i) => h("div", { key: i, style: sub }, `${ago(a.at)} ago \xB7 ${a.act}${a.field ? " " + a.field : ""}`)))) : null,
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2 pt-1" },
      btn("Edit", onEdit, { accent: true }),
      others.length ? h(
        "span",
        { className: "flex items-center gap-1" },
        selectBox(to, setTo, [["", "Move to\u2026"], ...others.map((v) => [v.name, v.title])]),
        to ? btn("Move", () => act("/vault-move", { vault, id, to }, "Move", true)) : null
      ) : null,
      h(Danger, { label: "Delete", what: r.title, explain: `${r.title} is removed from this vault${placed ? " and from every seat that holds it" : ""}. Its old passwords go with it.`, run: () => act("/vault-record-delete", { vault, id, confirm: id }, "Delete", true) })
    )
  );
}
var KEY_TEXT = { "": "vault key open on this machine", passphrase: "vault key locked", card: "vault key on a security key", elsewhere: "private key not on this machine", unsealed: "vault not sealed" };
function KeyBar({ state, refresh }) {
  const key = state.key || {};
  const [open, setOpen] = useState17(false);
  const [secret, setSecret] = useState17("");
  const [busy, setBusy] = useState17(false);
  const unlock = async () => {
    if (!secret || busy) return;
    setBusy(true);
    try {
      const r = await CTX.rest("/vault-unlock", { method: "POST", body: { secret } });
      host.notify({ kind: "success", title: "Vault", message: r.out });
      setOpen(false);
      refresh();
    } catch (e) {
      host.notifyError(e, "unlock failed");
    } finally {
      setSecret("");
      setBusy(false);
    }
  };
  const act = async (path, title) => {
    try {
      const r = await post(path, {});
      host.notify({ kind: "info", title: "Vault", message: r.out });
      refresh();
    } catch (e) {
      host.notifyError(e, `${title} failed`);
    }
  };
  const mins = (s) => s >= 60 ? `${Math.round(s / 60)} min` : `${s}s`;
  const canUnlock = key.needs === "passphrase" || key.needs === "card";
  const color = key.needs === "" ? "var(--ui-success, #2a9d5c)" : key.needs === "card" ? "var(--ui-text-secondary)" : "var(--ui-warning, #c98a00)";
  return h(
    "div",
    { className: "cockpit-vault-key flex flex-wrap items-center gap-2 border-b px-3 py-1 text-[0.6875rem]", style: { borderColor: stroke } },
    h("span", { style: { color } }, key.needs === "" && key.protected ? "vault key unlocked" : KEY_TEXT[key.needs] ?? ""),
    state.reason ? h("span", { style: sub }, state.reason) : null,
    key.protected && key.ttl && key.ttl.idle ? h("span", { style: sub }, `gpg-agent keeps an unlock ${mins(key.ttl.idle)} after last use, ${mins(key.ttl.max)} at most`) : null,
    h(
      "span",
      { className: "ml-auto flex items-center gap-1" },
      canUnlock && !open ? btn(key.needs === "card" ? "Enter PIN" : "Unlock", () => setOpen(true), { accent: true, title: "handed to gpg once; gpg-agent caches it, cockpit keeps nothing. In a terminal: cockpit vault unlock" }) : null,
      key.protected && key.cached || key.needs === "card" ? btn("Lock", () => act("/vault-lock", "lock"), { title: "gpg-agent forgets the passphrase (a security key asks for its PIN again)" }) : null,
      key.needs === "" || key.needs === "card" ? btn("Re-read vault", () => act("/vault-reindex", "re-read"), { title: "open every file and rebuild the list (a security key may want one touch per file)" }) : null
    ),
    open ? h(
      "div",
      { className: "flex w-full items-center gap-2 pt-1" },
      h("input", {
        type: "password",
        value: secret,
        onChange: (e) => setSecret(e.target.value),
        onKeyDown: (e) => {
          if (e.key === "Enter") unlock();
        },
        autoComplete: "off",
        autoFocus: true,
        spellCheck: false,
        placeholder: key.needs === "card" ? "security key PIN" : "vault key passphrase",
        className: "w-64 rounded border bg-transparent px-2 py-0.5 text-xs",
        style: { borderColor: stroke }
      }),
      h("button", { type: "button", disabled: !secret || busy, onClick: unlock, className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-accent)", color: "#fff" } }, busy ? key.needs === "card" ? "touch your key if it blinks\u2026" : "working" : "Unlock"),
      btn("Cancel", () => {
        setSecret("");
        setOpen(false);
      })
    ) : null
  );
}
function VaultRail({ vaults, vault, setVault, refresh }) {
  const [adding, setAdding] = useState17(false);
  const [name, setName] = useState17("");
  const [renaming, setRenaming] = useState17(false);
  const [to, setTo] = useState17("");
  const act = async (path, body, title) => {
    try {
      const x = await post(path, body);
      host.notify({ kind: "success", title, message: x.out });
      refresh();
      return true;
    } catch (e) {
      host.notifyError(e, `${title} failed`);
      return false;
    }
  };
  const current = vaults.find((v) => v.name === vault);
  const input = (value, set, go) => h("input", { value, onChange: (e) => set(e.target.value), onKeyDown: (e) => {
    if (e.key === "Enter") go();
  }, autoFocus: true, className: "w-full rounded border bg-transparent px-1.5 py-0.5 text-xs", style: { borderColor: stroke } });
  return h(
    "div",
    { className: "flex w-52 shrink-0 flex-col gap-1 border-r p-2 text-xs", style: { borderColor: stroke } },
    h("div", { className: "cockpit-head" }, "Vaults"),
    ...vaults.map((v) => h(
      "div",
      { key: v.name, onClick: () => setVault(v.name), className: "cockpit-row flex cursor-pointer items-center gap-2 rounded px-2 py-1", style: { background: v.name === vault ? "var(--ui-bg-selected, rgba(127,127,127,.15))" : "transparent" } },
      h("span", { className: "min-w-0 flex-1 truncate", title: v.name }, v.title),
      v.builtin ? h("span", { style: sub, title: "named by the pack; cannot be renamed or deleted" }, "\u{1F512}") : null,
      h("span", { style: sub }, v.count)
    )),
    adding ? h("div", { className: "flex flex-col gap-1" }, input(name, setName, async () => {
      if (await act("/vault-create", { name }, "New vault")) {
        setVault(name);
        setAdding(false);
        setName("");
      }
    }), h("div", { style: sub }, "letters, digits, - and _"), btn("Cancel", () => setAdding(false))) : btn("+ New vault", () => setAdding(true)),
    current && !current.builtin ? h(
      "div",
      { className: "mt-2 flex flex-col gap-1 border-t pt-2", style: { borderColor: stroke } },
      renaming ? h("div", { className: "flex flex-col gap-1" }, input(to, setTo, async () => {
        if (await act("/vault-rename", { name: vault, to }, "Rename")) {
          setVault(to);
          setRenaming(false);
        }
      }), btn("Cancel", () => setRenaming(false))) : btn("Rename vault", () => {
        setTo(vault);
        setRenaming(true);
      }),
      h(Danger, { label: "Delete vault", what: current.title, explain: current.count ? `${current.title} holds ${current.count} record${current.count === 1 ? "" : "s"}. Deleting the vault removes them all.` : `${current.title} is empty.`, run: async () => {
        if (await act("/vault-delete", { name: vault, confirm: vault, force: current.count > 0 }, "Delete vault")) setVault("");
      } })
    ) : null
  );
}
function Vault() {
  const qc = useQueryClient();
  const vq = useQuery({ queryKey: ["cockpit", "vaults"], queryFn: () => CTX.rest("/vaults"), refetchInterval: 2e4, retry: 1 });
  const [vault, setVaultRaw] = useState17(() => CTX.storage.get("vault.current", ""));
  const setVault = (v) => {
    setVaultRaw(v);
    CTX.storage.set("vault.current", v);
    setSel(null);
    setMode(null);
  };
  const [query, setQuery] = useState17("");
  const [kind, setKind] = useState17("");
  const [tag, setTag] = useState17("");
  const [sel, setSel] = useState17(null);
  const [mode, setMode] = useState17(null);
  const vaults = vq.data && vq.data.vaults || [];
  const active = vaults.find((v) => v.name === vault) || vaults[0];
  const name = active ? active.name : "";
  const rq = useQuery({ queryKey: ["cockpit", "vault-records", name, query, kind, tag], queryFn: () => CTX.rest(`/vault-records?${q({ vault: name, q: query, kind, tag })}`), enabled: Boolean(name), refetchInterval: 2e4, retry: 1 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["cockpit"] });
  if (vq.error) return h("div", { className: "p-3 text-xs", style: { color: DANGER2 } }, String(vq.error.message || vq.error));
  if (!vq.data) return h("div", { className: "p-3 text-xs", style: sub }, "loading");
  const state = vq.data;
  const records = rq.data && rq.data.records || [];
  const tags = rq.data && rq.data.tags || [];
  const rec = records.find((r) => r.id === sel);
  const kinds = state.kinds || [];
  const detail = mode === "new" ? h(RecordForm, { key: "new", vault: name, kinds, placed: active.placed, onDone: (id) => {
    setMode(null);
    setSel(id);
  }, onCancel: () => setMode(null) }) : mode === "edit" && rec ? h(RecordForm, { key: rec.id, vault: name, kinds, record: rec, placed: active.placed, onDone: () => setMode(null), onCancel: () => setMode(null) }) : sel ? h(RecordDetail, { key: sel, vault: name, id: sel, state, vaults, placed: active.placed, onEdit: () => setMode("edit"), onGone: () => setSel(null) }) : null;
  const label = (k) => (kinds.find((x) => x.name === k) || { label: k }).label;
  return h(
    "div",
    { className: "flex min-h-0 flex-1", "data-vault": "1" },
    h(VaultRail, { vaults, vault: name, setVault, refresh }),
    h(
      "div",
      { className: "flex min-h-0 min-w-0 flex-1 flex-col" },
      h(KeyBar, { state, refresh }),
      state.legacy ? h("div", { className: "px-3 py-1 text-[0.6875rem]", style: { color: "var(--ui-warning, #c98a00)" } }, "Your logins are still in the older single-file store. Re-read vault moves them into the vaults (the lanes read the same logins afterwards).") : null,
      rq.data && rq.data.unread ? h("div", { className: "px-3 py-1 text-[0.6875rem]", style: sub }, `${rq.data.unread} file${rq.data.unread === 1 ? "" : "s"} in this vault not read yet: unlock, or Re-read vault, to list ${rq.data.unread === 1 ? "it" : "them"}.`) : null,
      h(
        "div",
        { className: "flex flex-wrap items-center gap-2 border-b px-3 py-1.5", style: { borderColor: stroke } },
        h("input", { value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Search title, website, username, tag", className: "w-64 rounded border bg-transparent px-2 py-0.5 text-xs", style: { borderColor: stroke } }),
        h("div", { className: "flex items-center gap-1 rounded border p-0.5", style: { borderColor: stroke } }, seg(kind, "", "All", setKind), ...kinds.map((k) => seg(kind, k.name, k.label, setKind))),
        tags.length ? selectBox(tag, setTag, [["", "Any tag"], ...tags.map((t) => [t, t])]) : null,
        h("div", { className: "ml-auto" }, btn("+ New record", () => {
          setSel(null);
          setMode("new");
        }, { accent: true }))
      ),
      h(SplitList, {
        cols: COLS,
        labels: ["type", "title", "username / website", "tags", ">changed"],
        rows: records,
        selected: sel || mode,
        onSelect: (v) => {
          setSel(v);
          setMode(null);
        },
        onClose: () => {
          setSel(null);
          setMode(null);
        },
        detailWidth: "52%",
        empty: query || kind || tag ? "no record matches" : `${active ? active.title : "this vault"} is empty \u2014 add the first record`,
        renderRow: (r) => trow(COLS, { key: r.id, onClick: () => {
          setSel(r.id);
          setMode(null);
        }, selected: r.id === sel, children: [
          h("span", { style: sub }, label(r.kind)),
          h("span", { className: "truncate font-medium" }, r.title),
          h("span", { className: "truncate", style: mono }, r.email || r.origin || ""),
          h("span", { className: "truncate", style: sub }, (r.tags || []).join(", ")),
          h("span", { className: "text-right", style: sub }, ago(r.updated))
        ] }),
        detail
      })
    )
  );
}

// src/views/platform.js
import { useState as useState18, useEffect as useEffect10, useMemo as useMemo4, useRef as useRef3 } from "react";
var RANGE_LABEL = { 1: "24 h", 7: "1 week", 14: "2 weeks", 30: "1 month" };
function changeLabel(c) {
  if (c && typeof c.verdict === "string" && String(c.verdict).trim()) return c.verdict;
  if (c && c.verdict && c.verdict.user_change) return c.verdict.user_change;
  return c && c.title || "";
}
function fileOf(f) {
  if (typeof f === "string") return f;
  return f && (f.path || f.filename) || "";
}
var STATUS_MARK = { explained: ["\u25CF changed a user flow", "var(--ui-accent)"], pending: ["\u25D4 analyst reading", "var(--ui-warning, #c98a00)"], unmapped: ["? unmapped area", "var(--ui-warning, #c98a00)"], noise: ["\xB7 no flow change", "var(--ui-text-tertiary)"], skipped: ["\xB7 skipped", "var(--ui-text-quaternary)"] };
function ChangeModal({ repo, number, byId, onClose, onSeen, onUnseen }) {
  useEffect10(() => {
    window.__cockpitModalOpen = true;
    return () => {
      window.__cockpitModalOpen = false;
    };
  }, []);
  const qc = useQueryClient();
  const q2 = useQuery({ queryKey: ["cockpit", "platform-change", repo, number], queryFn: () => CTX.rest(`/platform-change?repo=${encodeURIComponent(repo)}&number=${number}`), retry: 0 });
  const c = q2.data;
  const verdictText = c && typeof c.verdict === "string" ? c.verdict : "";
  const [text, setText] = useState18(verdictText);
  const [busy, setBusy] = useState18(false);
  useEffect10(() => {
    const k = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  useEffect10(() => {
    setText(verdictText);
  }, [verdictText]);
  const v = c && c.verdict && typeof c.verdict === "object" ? c.verdict : {};
  const saveVerdict = async () => {
    setBusy(true);
    try {
      await post("/platform-verdict", { repo, number, text });
      qc.invalidateQueries({ queryKey: ["cockpit", "platform-change", repo, number] });
      qc.invalidateQueries({ queryKey: ["cockpit", "platform"] });
    } catch (e) {
      host.notifyError(e, "verdict failed");
    } finally {
      setBusy(false);
    }
  };
  const title = (id) => byId[id] && byId[id].title || id;
  return h(
    "div",
    { role: "presentation", onClick: onClose, style: { position: "fixed", inset: 0, zIndex: 1e3, background: "rgba(0,0,0,.72)", display: "flex", alignItems: "center", justifyContent: "center", padding: "3vh 3vw" } },
    h(
      "div",
      { role: "presentation", onClick: (e) => e.stopPropagation(), className: "rounded-lg border flex flex-col text-xs", style: { borderColor: stroke, background: "var(--ui-bg-elevated, #1e1e1e)", width: "94vw", height: "94vh", overflow: "hidden" } },
      h(
        "div",
        { className: "flex items-center gap-2 px-3 py-1.5", style: { borderBottom: `1px solid ${stroke}` } },
        h("span", { className: "font-medium text-sm" }, `${repo} #${number}`),
        c ? h("span", { className: "truncate" }, c.title) : null,
        c ? h("span", { style: sub }, `${c.author} \xB7 merged ${ago(c.merged_at)} ago`) : null,
        h("span", { className: "ml-auto flex items-center gap-1" }, c ? btn("PR on the forge", () => openWeb(c.url)) : null, c && !c.seen ? btn("Mark as seen", onSeen, { accent: true }) : null, c && c.seen ? btn("Undo seen", onUnseen) : null, btn("\u2715 close", onClose))
      ),
      h(
        "div",
        { className: "flex-1 overflow-auto p-3 flex flex-col gap-2" },
        !c ? h("div", { style: sub }, q2.error ? String(q2.error.message || q2.error) : "loading") : [
          h(Section, { key: "b", title: "Brief", open: true, color: "var(--ui-accent)" }, typeof c.verdict === "string" ? h(BriefGrid, { fields: [
            { label: "Verdict", text: c.verdict },
            { label: "Status", text: (STATUS_MARK[c.status] || [c.status])[0], color: (STATUS_MARK[c.status] || [])[1] },
            { label: "Areas", items: (c.nodes || []).map(title) }
          ] }) : c.verdict ? h(BriefGrid, { fields: [
            { label: "User change", text: v.user_change },
            { label: "Flow changed", text: v.flow_changed ? "yes" : "no: behaviour kept (refactor, copy, style or tooling)", color: v.flow_changed ? "var(--ui-accent)" : "var(--ui-text-tertiary)" },
            { label: "Areas", items: (c.nodes || []).map(title) },
            { label: "Risk", text: v.risk, color: v.risk === "high" ? "var(--ui-danger, #d33)" : v.risk === "medium" ? "var(--ui-warning, #c98a00)" : void 0 },
            { label: "Why it matters", text: v.why_it_matters },
            { label: "Look at", items: v.notes || [] }
          ] }) : h(BriefGrid, { fields: [
            { label: "Status", text: (STATUS_MARK[c.status] || [c.status])[0] + (c.reason ? " \xB7 " + c.reason : ""), color: (STATUS_MARK[c.status] || [])[1] },
            { label: "Areas", items: (c.nodes || []).map(title) },
            { label: "Files", text: `${c.files_n || (c.files || []).length} files \xB7 ${(c.functional || []).length} functional` + ((c.unmapped || []).length ? ` \xB7 ${c.unmapped.length} unmapped` : "") },
            c.card ? { label: "Analyst", text: `card ${c.card} is reading the diff` } : { label: "", text: "" }
          ] })),
          h(
            "div",
            { key: "verdict", className: "flex flex-col gap-1" },
            h("div", { className: "cockpit-head" }, "Analyst verdict"),
            h("textarea", { value: text, onChange: (e) => setText(e.target.value), rows: 3, className: "rounded border bg-transparent px-2 py-1", style: { borderColor: stroke, resize: "vertical" } }),
            h("div", null, h("button", { type: "button", disabled: busy || !String(text).trim(), onClick: saveVerdict, className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40", style: { background: "var(--ui-accent)", color: "#fff" } }, busy ? "saving\u2026" : "Save verdict"))
          ),
          h(Section, { key: "f", title: `Files by area (${(c.functional || []).length} functional of ${(c.files || []).length})` }, h("div", { className: "flex flex-col gap-0.5" }, ...(c.files || []).map((f) => {
            const path = fileOf(f);
            const row = typeof f === "string" ? {} : f || {};
            const ids = (c.attribution || {})[path];
            const fn = (c.functional || []).includes(path);
            return h(
              "div",
              { key: path, className: "flex gap-2" },
              h("span", { style: { ...mono, color: fn ? void 0 : "var(--ui-text-quaternary)" } }, path),
              row.add == null ? null : h("span", { style: { color: "#2ea043" } }, `+${row.add}`),
              row.del_ == null ? null : h("span", { style: { color: "#f85149" } }, `\u2212${row.del_}`),
              h("span", { style: sub }, fn ? ids && ids.length ? ids.map(title).join(", ") : "unmapped" : "not functional")
            );
          }))),
          h(Section, { key: "d", title: "PR description" }, h(RichMd, { html: c.body_html })),
          h(Section, { key: "x", title: "Diff (from the forge)" }, c.diff && c.diff.diff ? h(DiffView, { data: c.diff }) : h("div", { style: sub }, c.diff && c.diff.note || "no diff"))
        ]
      )
    )
  );
}
function layoutMap(nodes) {
  const W = 1200, H = 820, cx = W / 2, cy = H / 2;
  const areas = nodes.filter((n) => n.kind === "area");
  const comps = nodes.filter((n) => n.kind === "component");
  const pos = {};
  comps.forEach((c, i) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / Math.max(1, comps.length);
    const r = comps.length > 12 ? 150 : 125;
    pos[c.id] = { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a), a };
  });
  areas.forEach((ar, i) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / Math.max(1, areas.length);
    const R = 300;
    pos[ar.id] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), a };
    const fs = nodes.filter((n) => n.parent === ar.id);
    const spread = Math.min(0.5, 0.075 * fs.length);
    const r2 = R + 92;
    fs.forEach((f, j) => {
      const t = fs.length === 1 ? a : a - spread + j * (2 * spread) / (fs.length - 1);
      pos[f.id] = { x: cx + r2 * Math.cos(t), y: cy + r2 * Math.sin(t), a: t };
    });
  });
  return { W, H, pos };
}
function MapGraph({ nodes, byId, counts, inherited, onPick, picked }) {
  const { W, H, pos } = useMemo4(() => layoutMap(nodes), [nodes]);
  const [hover, setHover] = useState18(null);
  const [vb, setVb] = useState18({ x: 0, y: 0, w: W, h: H });
  const drag = useRef3(null);
  const unseen = (id) => ((counts[id] || {}).unseen || 0) + ((inherited[id] || {}).unseen || 0);
  const total = (id) => ((counts[id] || {}).total || 0) + ((inherited[id] || {}).total || 0);
  const edges = [];
  for (const n of nodes) {
    if (n.kind === "feature") {
      edges.push({ a: n.parent, b: n.id, kind: "spoke" });
      for (const dep of n.depends || []) if (pos[dep]) edges.push({ a: n.id, b: dep, kind: "dep" });
    }
  }
  const focus = hover || picked;
  const related = new Set(focus ? [focus, ...edges.filter((e) => e.a === focus || e.b === focus).flatMap((e) => [e.a, e.b])] : []);
  const lit = (id) => !focus || related.has(id);
  const onWheel = (e) => {
    e.preventDefault();
    const k = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    const r = e.currentTarget.getBoundingClientRect();
    const mx = vb.x + (e.clientX - r.left) / r.width * vb.w, my = vb.y + (e.clientY - r.top) / r.height * vb.h;
    const w = Math.min(W * 2, Math.max(W / 4, vb.w * k)), h2 = w * H / W;
    setVb({ x: mx - (mx - vb.x) * w / vb.w, y: my - (my - vb.y) * h2 / vb.h, w, h: h2 });
  };
  const onDown = (e) => {
    drag.current = { x: e.clientX, y: e.clientY, vb };
  };
  const onMove = (e) => {
    if (!drag.current) return;
    const r = e.currentTarget.getBoundingClientRect();
    const dx = (e.clientX - drag.current.x) / r.width * drag.current.vb.w, dy = (e.clientY - drag.current.y) / r.height * drag.current.vb.h;
    setVb({ ...drag.current.vb, x: drag.current.vb.x - dx, y: drag.current.vb.y - dy });
  };
  const onUp = () => {
    drag.current = null;
  };
  const zoom = W / vb.w;
  const label = (n, p, size, dy, always) => always || zoom > 1.6 || related.has(n.id) ? h("text", { x: p.x, y: p.y + dy, textAnchor: "middle", fontSize: size, fill: "var(--ui-text-primary, #ddd)", style: { pointerEvents: "none", opacity: lit(n.id) ? 1 : 0.25 } }, n.title.length > 30 && size < 12 ? n.title.slice(0, 28) + "\u2026" : n.title) : null;
  const glow = (p, r, id) => unseen(id) ? [h("circle", { key: "g" + id, cx: p.x, cy: p.y, r: r + 5, fill: "none", stroke: "var(--ui-accent)", strokeWidth: 2, className: "cockpit-glow" }), h("circle", { key: "h" + id, cx: p.x, cy: p.y, r: r + 2, fill: "var(--ui-accent)", opacity: 0.18 })] : null;
  const badge = (p, r, id) => unseen(id) ? h("g", { key: "b" + id }, h("circle", { cx: p.x + r * 0.8, cy: p.y - r * 0.8, r: 8, fill: "var(--ui-accent)" }), h("text", { x: p.x + r * 0.8, y: p.y - r * 0.8 + 3.5, textAnchor: "middle", fontSize: 10, fontWeight: 700, fill: "#fff", style: { pointerEvents: "none" } }, unseen(id))) : null;
  const shape = (n) => {
    const p = pos[n.id];
    if (!p) return null;
    const r = n.kind === "area" ? 26 : n.kind === "component" ? 15 : total(n.id) ? 7 : 5.5;
    const fill = n.kind === "area" ? "var(--ui-bg-elevated, #22272e)" : n.kind === "component" ? "rgba(201,138,0,.22)" : total(n.id) ? "var(--ui-accent)" : "rgba(127,127,127,.45)";
    const stroke2 = n.kind === "area" ? "var(--ui-accent)" : n.kind === "component" ? "var(--ui-warning, #c98a00)" : "rgba(127,127,127,.6)";
    return h(
      "g",
      { key: n.id, style: { cursor: "pointer", opacity: lit(n.id) ? 1 : 0.22, transition: "opacity .15s" }, onMouseEnter: () => setHover(n.id), onMouseLeave: () => setHover(null), onClick: (e) => {
        e.stopPropagation();
        onPick(n.id);
      } },
      glow(p, r, n.id),
      n.kind === "component" ? h("rect", { x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r, rx: 5, fill, stroke: stroke2, strokeWidth: 1.5, transform: `rotate(45 ${p.x} ${p.y})` }) : h("circle", { cx: p.x, cy: p.y, r, fill, stroke: stroke2, strokeWidth: n.kind === "area" ? 2 : 1.2 }),
      n.kind === "area" ? h("text", { x: p.x, y: p.y + 4, textAnchor: "middle", fontSize: 11, fontWeight: 600, fill: "var(--ui-text-primary, #ddd)", style: { pointerEvents: "none" } }, n.title.split(" (")[0]) : null,
      n.kind === "component" ? label(n, p, 9.5, r + 12, true) : null,
      n.kind === "feature" ? label(n, p, 8.5, -(r + 4), total(n.id) > 0) : null,
      badge(p, r, n.id)
    );
  };
  return h(
    "div",
    { className: "relative h-full w-full", style: { background: "radial-gradient(ellipse at center, rgba(56,139,253,.07), transparent 60%)" } },
    h(
      "svg",
      { viewBox: `${vb.x} ${vb.y} ${vb.w} ${vb.h}`, style: { width: "100%", height: "100%", display: "block", cursor: drag.current ? "grabbing" : "grab" }, onWheel, onMouseDown: onDown, onMouseMove: onMove, onMouseUp: onUp, onMouseLeave: onUp, role: "presentation", onClick: () => onPick(null) },
      h("defs", null, h("filter", { id: "ppsoft" }, h("feGaussianBlur", { stdDeviation: 1.2 }))),
      h("circle", { cx: W / 2, cy: H / 2, r: 300, fill: "none", stroke: "rgba(127,127,127,.15)", strokeDasharray: "3 5" }),
      h("circle", { cx: W / 2, cy: H / 2, r: nodes.filter((n) => n.kind === "component").length > 12 ? 150 : 125, fill: "none", stroke: "rgba(201,138,0,.18)", strokeDasharray: "3 5" }),
      ...edges.map((e, i) => {
        const a = pos[e.a], b = pos[e.b];
        if (!a || !b) return null;
        const on = focus && (e.a === focus || e.b === focus);
        return h("line", { key: i, x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: on ? "var(--ui-accent)" : e.kind === "dep" ? "rgba(201,138,0,.55)" : "rgba(127,127,127,.5)", strokeWidth: on ? 1.6 : e.kind === "dep" ? 0.6 : 0.8, opacity: on ? 0.95 : focus ? 0.06 : e.kind === "dep" ? 0.22 : 0.35 });
      }),
      ...nodes.filter((n) => n.kind === "feature").map(shape),
      ...nodes.filter((n) => n.kind === "component").map(shape),
      ...nodes.filter((n) => n.kind === "area").map(shape)
    ),
    h(
      "div",
      { className: "absolute left-2 bottom-2 flex items-center gap-3 text-[0.6875rem]", style: sub },
      h("span", null, h("span", { style: { color: "var(--ui-accent)" } }, "\u25CF"), " area"),
      h("span", null, h("span", { style: { color: "var(--ui-warning, #c98a00)" } }, "\u25C6"), " cross-cutting component"),
      h("span", null, "\xB7 feature"),
      h("span", null, h("span", { style: { color: "var(--ui-accent)" } }, "\u25CE"), " unread changes"),
      h("span", null, "wheel zooms \xB7 drag pans \xB7 hover shows relations")
    )
  );
}
function MapPopover({ node, byId, changes, onDetails, onClose, onOpenChange, onRead, base = "the base branch" }) {
  const title = (id) => byId[id] && byId[id].title || id;
  const unread = changes.filter((c) => !c.seen && c.status !== "skipped");
  return h(
    "div",
    { className: "absolute rounded-lg border text-xs flex flex-col gap-2 p-3", style: { right: "1rem", top: "1rem", width: "26rem", maxHeight: "calc(100% - 2rem)", overflow: "auto", background: "var(--ui-bg-elevated, #1e1e1e)", borderColor: "var(--ui-accent)", boxShadow: "0 8px 30px rgba(0,0,0,.45)" }, role: "presentation", onClick: (e) => e.stopPropagation() },
    h(
      "div",
      { className: "flex items-start gap-2" },
      h("div", { className: "min-w-0 flex-1" }, h("div", { className: "font-medium text-sm leading-tight" }, node.title), h("div", { className: "cockpit-head" }, node.kind + (unread.length ? ` \xB7 ${unread.length} unread` : ""))),
      h(
        "span",
        { className: "flex items-center gap-1 shrink-0" },
        unread.length ? h("button", { type: "button", onClick: () => onRead(unread), title: `mark the ${unread.length} unread change(s) of this node as read`, className: "rounded px-1.5 py-0.5 text-xs", style: { border: `1px solid ${stroke}`, color: "var(--ui-accent)" } }, "\u2713 read") : null,
        h("button", { type: "button", onClick: onDetails, title: "select it in the map column and open the full view", className: "rounded px-2 py-0.5 text-xs font-medium", style: { background: "var(--ui-accent)", color: "#fff" } }, "Details"),
        closeBtn(onClose)
      )
    ),
    h(BriefGrid, { fields: [
      { label: node.kind === "feature" ? "User does" : "Summary", text: node.user || node.summary },
      { label: "HLD role", text: node.hld },
      { label: node.kind === "component" ? "Used by" : "Depends on", items: (node.kind === "component" ? node.used_by : node.depends || []).map(title) }
    ] }),
    changes.length ? h(
      "div",
      { className: "flex flex-col gap-1" },
      h("div", { className: "cockpit-head" }, `changes on ${base} (${changes.length})`),
      ...changes.slice(0, 8).map((c) => h(
        "div",
        { key: c.repo + c.number, className: "flex items-center gap-2 cockpit-row rounded px-1 cursor-pointer", onClick: () => onOpenChange(c) },
        !c.seen && c.status !== "skipped" ? h("span", { style: { color: "var(--ui-accent)" } }, "\u25CF") : h("span", { style: sub }, "\xB7"),
        h("span", { style: mono }, `${c.repo} #${c.number}`),
        h("span", { className: "truncate", title: c.title }, changeLabel(c)),
        h("span", { className: "ml-auto whitespace-nowrap", style: { color: (STATUS_MARK[c.status] || [])[1] } }, (STATUS_MARK[c.status] || [c.status])[0])
      )),
      changes.length > 8 ? h("div", { style: sub }, `\u2026 ${changes.length - 8} more in Details`) : null
    ) : h("div", { style: sub }, `no changes on ${base} in this window`)
  );
}
function AnchorsCard({ node, root, days, base = "the base branch" }) {
  const [tab, setTab] = useState18("anchors");
  return h(
    "div",
    { className: "flex flex-col gap-2" },
    h("div", { className: "flex items-center gap-1 self-start rounded border p-0.5", style: { borderColor: stroke } }, seg(tab, "anchors", "Anchors", setTab), seg(tab, "diff", `Diff on ${base} (${RANGE_LABEL[days] || days + " days"})`, setTab)),
    tab === "anchors" ? h(
      "div",
      { className: "flex flex-col gap-1" },
      ...node.anchors.map((a, i) => h(
        "div",
        { key: i },
        h("div", { className: "font-medium", style: mono }, a.repo),
        ...a.paths.map((pth) => h(
          "div",
          { key: pth, className: "flex items-center gap-2 pl-2" },
          h("span", { style: mono }, pth),
          btn("Reveal", () => CTX.os.revealPath(`${root}/${a.repo}/${pth.replace(/\*.*$/, "")}`))
        )),
        a.key && a.key.length ? h("div", { className: "pl-2", style: sub }, "key: " + a.key.join(", ")) : null
      ))
    ) : h(NodeDiff, { id: node.id, days, base })
  );
}
function NodeDiff({ id, days, base = "the base branch" }) {
  const q2 = useQuery({ queryKey: ["cockpit", "platform-node-diff", id, days], queryFn: () => CTX.rest(`/platform-node-diff?id=${encodeURIComponent(id)}&days=${days}`), staleTime: 3e5, retry: 0 });
  if (q2.isLoading) return h("div", { className: "text-xs", style: sub }, `fetching origin/${base} and reading the diff under the anchors\u2026`);
  if (q2.error) return h("div", { className: "text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  const repos = q2.data && q2.data.repos || [];
  return h("div", { className: "flex flex-col gap-3" }, ...repos.map((r) => h(
    "div",
    { key: r.repo, className: "flex flex-col gap-1" },
    h("div", { className: "text-xs font-medium", style: mono }, r.repo),
    r.error ? h("div", { className: "text-xs", style: { color: "var(--ui-warning, #c98a00)" } }, r.error) : (r.commits || []).length || r.diff ? h(DiffView, { data: r }) : h("div", { className: "text-xs", style: sub }, "nothing changed under these anchors in the window")
  )));
}
function Platform() {
  const qc = useQueryClient();
  const [days, setDaysRaw] = useState18(() => {
    try {
      return Number(CTX.storage.get("platformDays", 1)) || 1;
    } catch (e) {
      return 1;
    }
  });
  const setDays = (v) => {
    setDaysRaw(v);
    try {
      CTX.storage.set("platformDays", v);
    } catch (e) {
    }
  };
  const q2 = useQuery({ queryKey: ["cockpit", "platform", days], queryFn: () => CTX.rest("/platform?days=" + days), refetchInterval: 3e4, retry: 1 });
  const aq = useQuery({ queryKey: ["cockpit", "advisories"], queryFn: () => CTX.rest("/advisories"), refetchInterval: 18e4, retry: 0 });
  const [sel, setSel] = useState18(null);
  const [picked, setPicked] = useState18(null);
  const [mode, setMode] = useState18("tree");
  const [showAll, setShowAll] = useState18(false);
  const [openChange, setOpenChange] = useState18(null);
  const [busy, setBusy] = useState18(false);
  useEffect10(() => {
    const k = (e) => {
      if (e.key === "Escape" && !window.__cockpitModalOpen && picked) setPicked(null);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [picked]);
  const [collapsed, setCollapsed] = useState18(() => {
    try {
      return new Set(CTX.storage.get("platformCollapsed", []));
    } catch (e) {
      return /* @__PURE__ */ new Set();
    }
  });
  if (q2.isLoading) return h("div", { className: "p-3 text-xs", style: sub }, "loading");
  if (q2.error) return h("div", { className: "p-3 text-xs", style: { color: "var(--ui-danger, #d33)" } }, String(q2.error.message || q2.error));
  const d = q2.data;
  const base = d.base || "the base branch";
  const map = d.map && !Array.isArray(d.map) ? d.map : { nodes: [] };
  const nodes = map.nodes || [];
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const counts = d.counts || {};
  const inh = d.inherited && !Array.isArray(d.inherited) ? d.inherited : {};
  const areas = nodes.filter((n) => n.kind === "area");
  const comps = nodes.filter((n) => n.kind === "component");
  const refresh = () => qc.invalidateQueries({ queryKey: ["cockpit", "platform"] });
  const toggle = (id) => {
    const n = new Set(collapsed);
    n.has(id) ? n.delete(id) : n.add(id);
    setCollapsed(n);
    try {
      CTX.storage.set("platformCollapsed", [...n]);
    } catch (e) {
    }
  };
  const badge = (id) => {
    const a = counts[id] || { total: 0, unseen: 0 };
    const b = inh[id] || { total: 0, unseen: 0 };
    const unseen = a.unseen + (b.unseen || 0);
    const total = a.total + (b.total || 0);
    return total ? h("span", { className: "ml-auto flex items-center gap-1" }, unseen ? h("span", { className: "rounded-full px-1.5 text-[0.6875rem] font-medium", style: { background: "var(--ui-accent)", color: "#fff" } }, unseen) : null, h("span", { className: "text-[0.6875rem]", style: sub }, `${total}`)) : null;
  };
  const nodeRow = (n, depth) => h(
    "div",
    { key: n.id, className: "flex items-center gap-1.5 cockpit-row rounded px-1 py-0.5 cursor-pointer", onClick: () => {
      setSel(n.id);
      setMode("tree");
    }, style: { paddingLeft: `${depth * 1.1 + 0.25}rem`, background: sel === n.id ? "var(--ui-bg-selected, rgba(127,127,127,.15))" : "transparent" } },
    n.kind !== "feature" ? h("span", { onClick: (e) => {
      e.stopPropagation();
      toggle(n.id);
    }, style: sub }, collapsed.has(n.id) ? "\u25B8" : "\u25BE") : h("span", { style: { color: "var(--ui-text-quaternary)" } }, "\xB7"),
    h("span", { className: n.kind === "feature" ? "" : "font-medium" }, n.title),
    badge(n.id)
  );
  const tree = h(
    "div",
    { className: "flex flex-col text-xs" },
    ...areas.flatMap((a) => [nodeRow(a, 0), ...collapsed.has(a.id) ? [] : nodes.filter((n) => n.parent === a.id).map((f) => nodeRow(f, 1))]),
    comps.length ? nodeRow({ id: "components", kind: "area", title: "Cross-cutting components" }, 0) : null,
    ...collapsed.has("components") ? [] : comps.map((c) => nodeRow(c, 1))
  );
  const cutoff = new Date(Date.now() - days * 864e5).toISOString();
  const inWindow = (d.changes || []).filter((c) => (c.merged_at || "") >= cutoff);
  const unseenN = inWindow.filter((c) => c.status !== "skipped" && !c.seen).length;
  const relevant = inWindow.filter((c) => showAll || c.status !== "skipped");
  const changeRow = (c) => {
    const m = STATUS_MARK[c.status] || [c.status, void 0];
    return h(
      "div",
      { key: c.repo + c.number, className: "grid gap-2 cockpit-row rounded px-1 py-0.5 cursor-pointer items-center", style: { gridTemplateColumns: "5.5rem 9rem 1fr 10rem 6rem", opacity: c.seen && c.status !== "pending" ? 0.75 : 1 }, onClick: () => setOpenChange({ repo: c.repo, number: c.number }) },
      h("span", { style: sub }, (c.merged_at || "").slice(5, 16).replace("T", " ")),
      h("span", { style: mono }, `${c.repo} #${c.number}`),
      h("span", { className: "truncate", title: c.title }, !c.seen && c.status !== "skipped" ? h("span", { style: { color: "var(--ui-accent)" } }, "\u25CF ") : null, changeLabel(c)),
      h("span", { className: "truncate", style: sub }, (c.nodes || []).map((id) => byId[id] && byId[id].title || id).join(", ") || c.reason || ""),
      h(
        "span",
        { className: "flex items-center gap-1", style: { color: m[1] } },
        m[0],
        !c.seen && c.status !== "skipped" ? h("button", {
          type: "button",
          onClick: (e) => {
            e.stopPropagation();
            markRead([c]);
          },
          title: "mark as read",
          className: "rounded px-1 text-[0.6875rem]",
          style: { border: `1px solid ${stroke}`, color: "var(--ui-accent)" }
        }, "\u2713") : null,
        c.seen ? h("button", {
          type: "button",
          onClick: (e) => {
            e.stopPropagation();
            markUnread([c]);
          },
          title: "undo seen",
          className: "rounded px-1 text-[0.6875rem]",
          style: { border: `1px solid ${stroke}` }
        }, "undo") : null
      )
    );
  };
  const markRead = async (cs) => {
    try {
      for (const c of cs) await post("/platform-seen", { repo: c.repo, number: c.number });
      refresh();
    } catch (e) {
      host.notifyError(e, "failed");
    }
  };
  const markUnread = async (cs) => {
    try {
      for (const c of cs) await post("/platform-unseen", { repo: c.repo, number: c.number });
      refresh();
    } catch (e) {
      host.notifyError(e, "undo seen failed");
    }
  };
  const node = sel ? byId[sel] : null;
  const changesOf = (n) => n ? inWindow.filter((c) => (c.nodes || []).includes(n.id) || n.kind === "feature" && (c.nodes || []).some((id) => (n.depends || []).includes(id)) || n.kind === "area" && (c.nodes || []).some((id) => byId[id] && byId[id].parent === n.id)).filter((c) => c.status !== "skipped") : [];
  const nodeChanges = node ? inWindow.filter((c) => (c.nodes || []).includes(node.id) || node.kind === "feature" && (c.nodes || []).some((id) => (node.depends || []).includes(id)) || node.kind === "area" && (c.nodes || []).some((id) => byId[id] && byId[id].parent === node.id)) : [];
  const detail = node ? h(
    "div",
    { className: "flex flex-col gap-2 p-3 text-xs" },
    detailHead(node.title, { text: node.kind, color: "var(--ui-accent)" }, node.parent && byId[node.parent] ? byId[node.parent].title : node.kind === "component" ? "cross-cutting" : ""),
    h(Section, { title: "Brief", open: true, color: "var(--ui-accent)" }, h(BriefGrid, { fields: [
      { label: node.kind === "feature" ? "User does" : "Summary", text: node.user || node.summary },
      { label: "HLD role", text: node.hld },
      { label: "LLD", text: node.lld },
      { label: node.kind === "component" ? "Used by" : "Depends on", items: (node.kind === "component" ? node.used_by : node.depends || []).map((id) => byId[id] && byId[id].title || id) }
    ] })),
    (node.anchors || []).length ? h(Section, { title: `Code anchors (${node.anchors.reduce((n, a) => n + a.paths.length, 0)})`, open: true }, h(AnchorsCard, { node, root: d.root, days, base })) : null,
    node.kind === "area" ? h(
      Section,
      { title: `Features (${nodes.filter((n) => n.parent === node.id).length})`, open: true },
      ...nodes.filter((n) => n.parent === node.id).map((f) => h(
        "div",
        { key: f.id, className: "flex gap-2 cockpit-row rounded px-1 cursor-pointer", onClick: () => setSel(f.id) },
        h("span", { className: "font-medium" }, f.title),
        h("span", { className: "truncate", style: sub }, f.user)
      ))
    ) : null,
    h(Section, {
      title: `Changes on ${base} (${nodeChanges.length} in the last ${RANGE_LABEL[days] || days + " days"})`,
      open: true,
      extra: (() => {
        const unread = nodeChanges.filter((c) => !c.seen && c.status !== "skipped");
        return unread.length ? h(
          "button",
          {
            type: "button",
            onClick: () => markRead(unread),
            title: `mark the ${unread.length} unread change(s) of this node as read`,
            className: "rounded px-1.5 py-0.5 text-xs",
            style: { border: `1px solid ${stroke}`, color: "var(--ui-accent)" }
          },
          `\u2713 read (${unread.length})`
        ) : null;
      })()
    }, nodeChanges.length ? h("div", { className: "flex flex-col" }, ...nodeChanges.map(changeRow)) : h(
      "div",
      { style: sub },
      "nothing landed here in this window"
    ))
  ) : null;
  const pickedNode = picked ? byId[picked] : null;
  const canvas = h(
    "div",
    { className: "relative min-w-0 flex-1 min-h-0" },
    h(MapGraph, { nodes, byId, counts, inherited: inh, picked, onPick: (id) => setPicked(id && byId[id] ? id : null) }),
    pickedNode ? h(MapPopover, { node: pickedNode, byId, changes: changesOf(pickedNode), base, onClose: () => setPicked(null), onDetails: () => {
      setSel(pickedNode.id);
      setPicked(null);
    }, onOpenChange: (c) => setOpenChange({ repo: c.repo, number: c.number }), onRead: markRead }) : null
  );
  const feed = h(
    "div",
    { className: "flex flex-col gap-1 p-3 text-xs" },
    h("div", { className: "grid gap-2 cockpit-head px-1", style: { gridTemplateColumns: "5.5rem 9rem 1fr 10rem 6rem" } }, h("span", null, "merged"), h("span", null, "PR"), h("span", null, "title"), h("span", null, "areas"), h("span", null, "verdict")),
    ...relevant.length ? relevant.map(changeRow) : [h("div", { style: sub }, inWindow.length ? 'nothing relevant in this window (tick "include skipped" to see the rest)' : `nothing landed on ${base} in this window: widen it, or Scan now`)]
  );
  const lastScan = Object.values(d.state || {}).map((s) => s.last_scan).filter(Boolean).sort().pop();
  return h(
    "div",
    { className: "flex min-h-0 flex-1 flex-col" },
    h(
      "div",
      { className: "flex items-center gap-2 px-3 py-1.5 text-xs", style: { borderBottom: `1px solid ${stroke}` } },
      h("div", { className: "flex items-center gap-1 rounded border p-0.5", style: { borderColor: stroke } }, seg(mode, "tree", "Map", setMode), seg(mode, "feed", `Feed \xB7 ${unseenN} unread`, setMode), seg(mode, "advisories", `Advisories \xB7 ${(aq.data && aq.data.advisories || []).filter((a) => a.alert && !a.acknowledged).length} alert(s)`, setMode)),
      h("div", { className: "flex items-center gap-1 rounded border p-0.5", style: { borderColor: stroke }, title: "window for badges, the feed and each node's changes" }, ...[1, 7, 14, 30].map((v) => seg(days, v, RANGE_LABEL[v], setDays))),
      mode === "feed" ? h("label", { className: "flex items-center gap-1 cursor-pointer" }, h("input", { type: "checkbox", checked: showAll, onChange: (e) => setShowAll(e.target.checked) }), "include skipped") : null,
      h("span", { className: "ml-auto", style: sub }, lastScan ? `last scan ${ago(lastScan)} ago \xB7 map built ${d.map.built ? ago(d.map.built) + " ago" : "never"}` : "never scanned"),
      btn(
        busy ? "scanning\u2026" : "Scan now",
        async () => {
          setBusy(true);
          try {
            const r = await post(
              "/platform-scan",
              { days: 7 }
            );
            host.notify({
              kind: "info",
              title: `${r.base || base} scan`,
              message: (r.out || "").slice(-600)
            });
            refresh();
          } catch (e) {
            host.notifyError(e, "scan failed");
          } finally {
            setBusy(false);
          }
        },
        { title: `reads of merged pull requests on ${base}; an analyst card for the ones that need a verdict` }
      ),
      btn("Mark all seen", async () => {
        try {
          await post("/platform-seen", { all: true });
          refresh();
        } catch (e) {
          host.notifyError(e, "failed");
        }
      })
    ),
    mode === "advisories" ? h(AdvisoriesTab, { data: aq.data, onDone: () => aq.refetch && aq.refetch() }) : h(
      "div",
      { className: "flex min-h-0 flex-1" },
      h("div", { className: "overflow-auto p-2", style: { width: "22rem", minWidth: "18rem", borderRight: `1px solid ${stroke}` } }, nodes.length ? tree : h("div", { className: "text-xs", style: sub }, d.hint || "no platform map yet. Ask the platform-map skill to write platform/map.yaml, then Scan now")),
      mode === "feed" ? h(Pane, { onClose: () => setMode("tree") }, feed) : node ? h(Pane, { onClose: () => setSel(null) }, detail) : canvas
    ),
    openChange ? h(ChangeModal, {
      repo: openChange.repo,
      number: openChange.number,
      byId,
      onClose: () => setOpenChange(null),
      onSeen: async () => {
        try {
          await post("/platform-seen", openChange);
          qc.invalidateQueries({ queryKey: [
            "cockpit",
            "platform-change",
            openChange.repo,
            openChange.number
          ] });
          refresh();
        } catch (e) {
          host.notifyError(e, "failed");
        }
      },
      onUnseen: async () => {
        try {
          await post(
            "/platform-unseen",
            openChange
          );
          qc.invalidateQueries({ queryKey: [
            "cockpit",
            "platform-change",
            openChange.repo,
            openChange.number
          ] });
          refresh();
        } catch (e) {
          host.notifyError(e, "undo seen failed");
        }
      }
    }) : null
  );
}

// src/views/board.js
import { useState as useState19, useEffect as useEffect11, useMemo as useMemo5, useRef as useRef4 } from "react";
var TONE = { triage: "var(--ui-text-tertiary)", todo: "var(--ui-text-secondary)", ready: "#60a5fa", claimed: "#34d399", in_progress: "#34d399", running: "#34d399", review: "#fbbf24", blocked: "#f87171", done: "var(--ui-text-tertiary)", archived: "var(--ui-text-quaternary)", cancelled: "var(--ui-text-quaternary)" };
var tone = (status) => TONE[status] || "var(--ui-text-secondary)";
var STATUS_LABEL = { in_progress: "in progress" };
var statusLabel = (s) => STATUS_LABEL[s] || (s || "").replace(/_/g, " ");
var COLUMNS = [
  { id: "triage", title: "Triage", statuses: ["triage"] },
  { id: "todo", title: "To do", statuses: ["todo"] },
  { id: "ready", title: "Ready", statuses: ["ready"] },
  { id: "running", title: "Running", statuses: ["claimed", "in_progress", "running"] },
  { id: "review", title: "Review", statuses: ["review"] },
  { id: "blocked", title: "Blocked", statuses: ["blocked"] },
  { id: "done", title: "Done", statuses: ["done", "archived", "cancelled"], closed: true }
];
var LANE_HUES = [[/^intake/, "#a78bfa"], [/^worker/, "#60a5fa"], [/^tester/, "#34d399"], [/^reviewer/, "#fbbf24"], [/^gatekeeper/, "#f87171"], [/^analyst/, "#22d3ee"]];
var laneHue = (lane) => (LANE_HUES.find(([re]) => re.test(lane || "")) || [null, "var(--ui-text-secondary)"])[1];
var initials = (name) => {
  const p = String(name || "").trim().split(/[\s_\-./]+/).filter(Boolean);
  return `${(p[0] || "?")[0]}${p[1] ? p[1][0] : ""}`.toUpperCase();
};
var WARN3 = "var(--ui-warning, #c98a00)";
var DANGER3 = "var(--ui-danger, #d33)";
var NONE = [];
var ts = (iso) => iso ? new Date(iso).getTime() : 0;
var bareTitle = (c) => {
  const t = (c.title || "").trim();
  const k = c.ticket;
  if (!k) return t || c.id;
  const m = t.match(new RegExp("^" + k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*[:\\-\u2013\u2014]?\\s*", "i"));
  return (m ? t.slice(m[0].length) : t) || t || c.id;
};
var firstLine = (s) => (String(s || "").split("\n").find((l) => l.trim()) || "").trim();
var elapsed = (iso) => {
  const s = Math.max(0, (Date.now() - ts(iso)) / 1e3);
  return s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`;
};
function useTick(on) {
  const [, force] = useState19(0);
  useEffect11(() => {
    if (!on) return;
    const id = window.setInterval(() => force((n) => n + 1), 5e3);
    return () => window.clearInterval(id);
  }, [on]);
}
function useLeaving(cards) {
  const prev = useRef4(/* @__PURE__ */ new Map());
  const [ghosts, setGhosts] = useState19([]);
  useEffect11(() => {
    const now = new Map(cards.map((c) => [c.id, c]));
    const gone = [...prev.current.values()].filter((c) => !now.has(c.id));
    prev.current = now;
    if (!gone.length) return;
    setGhosts((g) => [...g.filter((x) => !gone.some((c) => c.id === x.id)), ...gone]);
    window.setTimeout(() => setGhosts((g) => g.filter((x) => !gone.some((c) => c.id === x.id))), 220);
  }, [cards]);
  return ghosts.filter((g) => !cards.some((c) => c.id === g.id));
}
var ticketChip = (ticket) => ticket ? h("span", { className: "cockpit-kb-ticket", style: mono }, ticket) : null;
var ENV = { "test\xB7local": "local", "test\xB7staging": "stg" };
var flowPill = (flow) => flow && flow !== "card" ? h("span", { className: "cockpit-kb-flow", title: ENV[flow] ? `test on ${flow === "test\xB7staging" ? "staging" : "the local slot"}` : "flow: " + flow }, ENV[flow] || flow) : null;
var statusChip = (status) => h("span", { className: "cockpit-kb-status", style: { color: tone(status), background: `color-mix(in srgb, ${tone(status)} 15%, transparent)` } }, h("span", { className: "cockpit-kb-dot", style: { background: tone(status) } }), statusLabel(status));
var laneBadge = (lane, size) => {
  if (!lane) return null;
  const hue = laneHue(lane);
  return h(
    "span",
    { className: "cockpit-kb-lane", title: `lane ${lane}`, style: { color: hue, background: `color-mix(in srgb, ${hue} 14%, transparent)` } },
    h("span", { className: "cockpit-kb-ava", style: {
      background: `color-mix(in srgb, ${hue} 22%, transparent)`,
      width: size || "1rem",
      height: size || "1rem"
    } }, initials(lane)),
    h("span", { className: "truncate" }, lane)
  );
};
function RunClock({ card }) {
  useTick(Boolean(card.alive));
  const since = card.started || card.heartbeat || card.created;
  return since ? h("span", { className: "shrink-0 font-medium", style: { color: TONE.running }, title: `working since ${ago(since)} ago \xB7 heartbeat ${card.heartbeat ? ago(card.heartbeat) + " ago" : "none"}` }, `working \xB7 ${elapsed(since)}`) : null;
}
function Card({ c, column, selected, onOpen, leaving }) {
  const t = tone(c.status);
  const working = ["claimed", "in_progress", "running"].includes(c.status);
  const arc = working && c.alive ? "live" : working && c.heartbeat && !c.alive ? "stale" : null;
  const last = c.last_comment && firstLine(c.last_comment.text);
  return h(
    "div",
    { className: "cockpit-kb-card" + (selected ? " sel" : "") + (leaving ? " out" : "") + (column.closed ? " closed" : ""), onClick: () => onOpen(c.id), title: c.title || c.id, style: { "--cockpit-kb-tone": t, borderLeftColor: t } },
    arc && !selected ? h("span", { "aria-hidden": true, className: "cockpit-kb-arc" + (arc === "stale" ? " stale" : "") }) : null,
    h("div", { className: "flex items-center gap-1.5 min-w-0" }, ticketChip(c.ticket), flowPill(c.flow), column.statuses.length > 1 ? h("span", { className: "cockpit-kb-sub", style: { color: t } }, statusLabel(c.status)) : null, h("span", { className: "ml-auto cockpit-kb-age" }, c.created ? ago(c.created) : "")),
    h("div", { className: "cockpit-kb-title" }, bareTitle(c)),
    c.status === "blocked" && c.question ? h("div", { className: "cockpit-kb-sum", style: { color: WARN3 } }, c.question) : null,
    c.error ? h("div", { className: "cockpit-kb-line", style: { color: DANGER3 } }, c.error) : null,
    last ? h("div", { className: "cockpit-kb-line", style: sub }, `${c.last_comment.author}: ${last}`) : null,
    h(
      "div",
      { className: "cockpit-kb-foot" },
      laneBadge(c.lane),
      arc === "live" ? h(RunClock, { card: c }) : arc === "stale" ? h("span", { className: "shrink-0 font-medium", style: { color: "#fbbf24" }, title: `last heartbeat ${ago(c.heartbeat)} ago` }, "no heartbeat") : null,
      h(
        "div",
        { className: "ml-auto flex min-w-0 shrink items-center gap-2" },
        c.runs > 1 ? h("span", { title: `${c.runs} runs` }, `\u21BB ${c.runs}`) : null,
        c.completed && column.closed ? h("span", { className: "cockpit-kb-age", title: "completed" }, ago(c.completed)) : null,
        h("span", { className: "cockpit-kb-id truncate", style: mono }, String(c.id).replace(/^t_/, "").slice(0, 6))
      )
    )
  );
}
var RECENT_HOURS = 24;
var splitDone = (cards, activity, now = Date.now(), hours = RECENT_HOURS, live = {}) => {
  const recent = (c) => {
    if ((live || {})[c.ticket]) return true;
    const at = ts((activity || {})[c.ticket]);
    return at > 0 && now - at < hours * 36e5;
  };
  return { recent: cards.filter(recent), hidden: cards.filter((c) => !recent(c)) };
};
var WAITS = { work: "in work", publish: "awaiting publish", merge: "awaiting merge", confirm: "awaiting your confirm", release: "in a running release" };
var waitsLine = (whys) => (whys || []).map((w) => WAITS[w] || w).join(" \xB7 ");
var stackByTicket = (cards) => {
  const units = [];
  const byTicket = /* @__PURE__ */ new Map();
  for (const c of cards) {
    if (!c.ticket) {
      units.push(c);
      continue;
    }
    if (!byTicket.has(c.ticket)) {
      const u = { id: "stack:" + c.ticket, stack: true, ticket: c.ticket, cards: [] };
      byTicket.set(c.ticket, u);
      units.push(u);
    }
    byTicket.get(c.ticket).cards.push(c);
  }
  return units;
};
function Stack({ s, title, waits, column, selected, onOpen, leaving }) {
  const holds = s.cards.some((c) => c.id === selected);
  const [open, setOpen] = useState19(false);
  const top = s.cards[0];
  const lanes = [...new Set(s.cards.map((c) => c.lane).filter(Boolean))];
  const t = tone("done");
  return h(
    "div",
    { className: "cockpit-kb-stackwrap" + (leaving ? " out" : "") },
    h(
      "div",
      { className: "cockpit-kb-card closed cockpit-kb-stack" + (open || holds ? " open" : ""), onClick: () => setOpen(!open), title: `${s.ticket}: ${title || bareTitle(top)} \xB7 ${s.cards.length} done card${s.cards.length === 1 ? "" : "s"}, newest: ${bareTitle(top)} \u2014 click to ${open ? "fold" : "open"}`, style: { "--cockpit-kb-tone": t, borderLeftColor: t } },
      h("div", { className: "flex items-center gap-1.5 min-w-0" }, ticketChip(s.ticket), h("span", { className: "cockpit-kb-stackn" }, `${s.cards.length} card${s.cards.length === 1 ? "" : "s"}`), h("span", { className: "ml-auto cockpit-kb-age" }, top.completed ? ago(top.completed) : "")),
      h("div", { className: "cockpit-kb-title" }, title || bareTitle(top)),
      waits ? h("div", { className: "cockpit-kb-sub", "data-waits": waits, style: { color: "var(--ui-warning, #c98a00)" } }, waits) : null,
      h(
        "div",
        { className: "cockpit-kb-foot" },
        ...lanes.slice(0, 4).map((l) => h("span", { key: l }, laneBadge(l))),
        lanes.length > 4 ? h("span", { style: sub }, `+${lanes.length - 4}`) : null,
        h("span", { className: "ml-auto cockpit-kb-age" }, open || holds ? "\u25BE fold" : "\u25B8 open")
      )
    ),
    open || holds ? h("div", { className: "cockpit-kb-stackbody" }, ...s.cards.map((c) => h(Card, { key: c.id, c, column, selected: c.id === selected, onOpen }))) : null
  );
}
var Unit = ({ u, titles, live, column, selected, onOpen, leaving }) => u.stack ? h(Stack, { s: u, title: (titles || {})[u.ticket], waits: waitsLine((live || {})[u.ticket]), column, selected, onOpen, leaving }) : h(Card, { c: u, column, selected: !leaving && u.id === selected, onOpen, leaving });
function Column({ column, cards, activity, titles, live, selected, onOpen, recentHours }) {
  const [showDone, setShowDone] = useState19(false);
  const { recent, hidden } = column.closed ? splitDone(cards, activity, Date.now(), recentHours || RECENT_HOURS, live) : { recent: cards, hidden: NONE };
  const visible = !column.closed || showDone ? cards : recent;
  const shown = useMemo5(() => column.closed ? stackByTicket(visible) : visible, [column.closed, visible]);
  const hiddenUnits = column.closed ? stackByTicket(hidden).length : 0;
  const ghosts = useLeaving(shown);
  const t = tone(column.id === "done" ? "done" : column.statuses[0]);
  return h(
    "div",
    { className: "cockpit-kb-col" },
    h("header", { className: "cockpit-kb-colhead" }, h("span", { className: "cockpit-kb-dot", style: { background: t } }), h("span", { className: "cockpit-kb-collabel" }, column.title), h("span", { className: "cockpit-kb-count" }, cards.length)),
    h(
      "div",
      { className: "cockpit-kb-body" },
      ...shown.map((u) => h(Unit, { key: u.id, u, titles, live, column, selected, onOpen })),
      ...ghosts.map((u) => h(Unit, { key: u.id, u, titles, live, column, selected, onOpen, leaving: true })),
      !cards.length ? h("div", { className: "cockpit-kb-empty" }, "empty") : null,
      column.closed && hiddenUnits ? h("button", { type: "button", className: "cockpit-kb-more", onClick: () => setShowDone(!showDone) }, showDone ? "hide done" : `show ${hiddenUnits} done`) : null
    )
  );
}
function WaitingPane({ card }) {
  const said = { now: "for you now", later: "a later stage", gate: "with the gatekeeper", lane: "back with a lane", stale: "stale" };
  return h(
    "div",
    { className: "flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-3" },
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2" },
      statusChip(card.status),
      ticketChip(card.ticket),
      h("div", { className: "font-medium text-sm min-w-0" }, "outbox items, no lane at work"),
      h("div", { className: "ml-auto flex items-center gap-1.5" }, btn("Open the Inbox", () => host.navigate("/cockpit"), { accent: true, title: "publish, confirm or decide them there" }))
    ),
    h("div", { className: "text-xs", style: sub }, card.question),
    h("div", { className: "flex flex-col gap-0.5 text-xs" }, ...(card.items || []).map((it) => h(
      "div",
      { key: it.id, className: "flex gap-2" },
      h("span", { style: { minWidth: "9rem" } }, said[it.when] || it.when),
      h("span", { style: sub }, it.status),
      h("span", null, it.id)
    )))
  );
}
function CardPane({ card, refresh }) {
  if (card.yours) return h(WaitingPane, { card });
  return h(LaneCardPane, { card, refresh });
}
function LaneCardPane({ card, refresh }) {
  const blocked = card.status === "blocked";
  const cq = useQuery({ queryKey: ["cockpit", "card-detail", card.id], queryFn: () => CTX.rest("/card-detail?id=" + card.id), enabled: !blocked, refetchInterval: 15e3, retry: 0 });
  return h(
    "div",
    { className: "flex min-h-0 flex-1 flex-col gap-2 p-3" },
    h(
      "div",
      { className: "flex flex-wrap items-center gap-2" },
      statusChip(card.status),
      ticketChip(card.ticket),
      flowPill(card.flow),
      h("div", { className: "font-medium text-sm min-w-0" }, bareTitle(card)),
      laneBadge(card.lane),
      h("div", { className: "ml-auto flex items-center gap-1.5" }, btn("Open in Kanban", () => host.navigate("/kanban"), { title: "the host Kanban page: drag, assign, edit" }))
    ),
    h(
      "div",
      { className: "flex flex-wrap gap-2 text-xs", style: sub },
      card.created ? h("span", null, "created " + ago(card.created) + " ago") : null,
      card.started ? h("span", null, "started " + ago(card.started) + " ago") : null,
      card.completed ? h("span", null, "completed " + ago(card.completed) + " ago") : null,
      card.heartbeat ? h("span", { style: { color: card.alive ? TONE.running : "inherit" } }, (card.alive ? "alive \xB7 heartbeat " : "last heartbeat ") + ago(card.heartbeat) + " ago") : null,
      card.runs ? h("span", null, `${card.runs} run${card.runs === 1 ? "" : "s"}`) : null,
      card.skills ? h("span", null, "skills " + (Array.isArray(card.skills) ? card.skills.join(", ") : card.skills)) : null
    ),
    h(
      "div",
      { className: "min-h-0 flex-1 " + (blocked ? "flex flex-col" : "overflow-auto") },
      blocked ? h(BlockedCard, { c: { ...card, assignee: card.lane }, refresh }) : cq.data ? h(CardView, { c: cq.data }) : cq.error ? h("div", { className: "text-xs", style: { color: DANGER3 } }, String(cq.error.message || cq.error)) : h("div", { className: "text-xs", style: sub }, "loading the card")
    )
  );
}
function Board() {
  const q2 = useQuery({ queryKey: ["cockpit", "board"], queryFn: () => CTX.rest("/board"), refetchInterval: 5e3, retry: 1 });
  const qc = useQueryClient();
  const [lanes, setLanesRaw] = useState19(() => {
    const v = CTX.storage.get("boardLanes", []);
    return Array.isArray(v) ? v : [];
  });
  const setLanes = (v) => {
    setLanesRaw(v);
    CTX.storage.set("boardLanes", v);
  };
  const [text, setText] = useState19("");
  const [selected, setSelected] = useState19(null);
  const cards = q2.data && q2.data.cards || [];
  const allLanes = useMemo5(() => [.../* @__PURE__ */ new Set([...q2.data && q2.data.lanes || [], ...lanes])].sort(), [q2.data, lanes]);
  const needle = text.trim().toLowerCase();
  const keep = (c) => (!lanes.length || lanes.includes(c.lane)) && (!needle || `${c.ticket} ${c.title} ${c.id} ${c.lane} ${c.question || ""} ${c.error || ""}`.toLowerCase().includes(needle));
  const byColumn = useMemo5(() => COLUMNS.map((col) => [col, cards.filter((c) => col.statuses.includes(c.status) && keep(c)).sort((a, b) => col.closed ? ts(b.completed || b.created) - ts(a.completed || a.created) : ts(b.created) - ts(a.created))]), [cards, lanes, needle]);
  const open = byColumn.filter(([col]) => !col.closed).reduce((n, [, cs]) => n + cs.length, 0);
  const closed = byColumn.filter(([col]) => col.closed).reduce((n, [, cs]) => n + cs.length, 0);
  const unmatched = cards.filter((c) => !COLUMNS.some((col) => col.statuses.includes(c.status))).length;
  const current = selected ? cards.find((c) => c.id === selected) : null;
  useEffect11(() => {
    if (selected && q2.data && !current) setSelected(null);
  }, [selected, q2.data, current]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["cockpit"] });
  const toggleLane = (l) => setLanes(lanes.includes(l) ? lanes.filter((x) => x !== l) : [...lanes, l]);
  const laneChip = (l) => {
    const on = lanes.includes(l);
    const hue = laneHue(l);
    return h("button", { key: l, type: "button", onClick: () => toggleLane(l), className: "cockpit-kb-chip", style: on ? { color: hue, borderColor: hue, background: `color-mix(in srgb, ${hue} 14%, transparent)` } : { color: "var(--ui-text-secondary)", borderColor: stroke } }, l);
  };
  const filterRow = h(
    "div",
    { className: "cockpit-kb-filter" },
    h("span", { className: "cockpit-kb-total" }, open),
    h("span", { className: "text-xs", style: sub }, `open \xB7 ${closed} done`),
    unmatched ? h("span", { className: "text-xs", style: sub }, `\xB7 ${unmatched} other`) : null,
    h("span", { className: "mx-1", style: sub }, "|"),
    ...allLanes.map(laneChip),
    lanes.length ? btn("all lanes", () => setLanes([]), { title: "clear the lane filter" }) : null,
    h("input", { value: text, onChange: (e) => setText(e.target.value), placeholder: "filter: ticket, title, lane, question", className: "cockpit-kb-input ml-auto rounded border bg-transparent px-1.5 py-0.5 text-xs", style: { borderColor: stroke } })
  );
  const strip = q2.error && !q2.data ? h("div", { className: "p-3 text-xs", style: { color: DANGER3 } }, String(q2.error.message || q2.error)) : !q2.data ? h("div", { className: "p-6 text-center text-xs", style: sub }, "loading the board") : h("div", { className: "cockpit-kb-lanes" }, ...byColumn.map(([col, cs]) => h(Column, { key: col.id, column: col, cards: cs, activity: q2.data && q2.data.ticket_activity, titles: q2.data && q2.data.ticket_titles, live: q2.data && q2.data.live, recentHours: q2.data && q2.data.recent_hours, selected, onOpen: (id) => setSelected(id === selected ? null : id) })));
  return h(
    "div",
    { className: "cockpit-kb flex min-h-0 flex-1" },
    h("div", { className: "flex min-w-0 flex-col", style: { flex: current ? "0 0 54%" : "1 1 auto", borderRight: current ? `1px solid ${stroke}` : "none", minHeight: 0 } }, filterRow, strip),
    current ? h(Pane, { onClose: () => setSelected(null) }, h(CardPane, { key: current.id, card: current, refresh })) : null
  );
}

// src/app.js
function useRepoInfo() {
  const q2 = useQuery({ queryKey: ["cockpit", "repos"], queryFn: () => CTX.rest("/repos"), refetchInterval: POLL_MS * 6, retry: 0 });
  return q2.data || {};
}
var localKey = (project) => `${project || "KEY"}-LOCAL-7`;
var TONE2 = { ok: "var(--ui-success, #2a9d5c)", warn: "var(--ui-warning, #c98a00)", danger: "var(--ui-danger, #d33)" };
function useCapacity() {
  return useQuery({ queryKey: ["cockpit", "capacity"], queryFn: () => CTX.rest("/capacity"), refetchInterval: POLL_MS, retry: 0 });
}
function CapacityPills() {
  const q2 = useCapacity();
  const flows = q2.data && q2.data.flows || [];
  return h(
    "div",
    { className: "flex items-center gap-1" },
    ...flows.map((c) => {
      const color = TONE2[c.tone] || "var(--ui-text-tertiary)";
      return h("span", { key: c.key, className: "cockpit-cap", title: c.why, style: { color, borderColor: color, background: `color-mix(in srgb, ${color} 12%, transparent)` } }, `${c.label} ${c.free}`);
    })
  );
}
function PluginPages() {
  const q2 = useQuery({ queryKey: ["cockpit", "plugin-pages"], queryFn: () => CTX.rest("/plugin-pages"), refetchInterval: POLL_MS * 30, retry: 0 });
  const pages = q2.data && q2.data.pages || [];
  if (!pages.length) return null;
  return h(
    "span",
    { className: "flex items-center gap-1" },
    ...pages.map((page) => h(
      "span",
      { key: page.plugin, "data-plugin-page": page.plugin },
      btn(`${page.label} \u2197`, () => host.navigate(page.path), { title: `${page.label} (${page.path})` })
    ))
  );
}
var capFree = (flows, mode, slotted) => {
  const f = (flows || []).find((x) => x.key === (mode === "intake" || mode === "rework" ? "dev" : mode === "test" ? "test" : ""));
  if (!f) return null;
  const n = mode === "test" && slotted ? f.local : f.free;
  return n <= 0 ? { label: f.label + (mode === "test" && slotted ? " on a local slot" : ""), why: f.why } : null;
};
var KICKOFF_TABS = [["intake", "Ticket \u2192 intake (plan, then your go)"], ["test", "Test \u2192 tester (plan, your go, run, your review, post)"], ["review", "PR review \u2192 reviewer (review intents to publish)"], ["bumps", HINTS.bumps_tab], ["analyst", "Question \u2192 analyst"]];
var kickoffTabs = (hints) => KICKOFF_TABS.map(([mode, label]) => [mode, mode === "bumps" ? hintsOf(hints).bumps_tab : label]);
function KickoffForm({ onDone, initialMode = "intake" }) {
  const info = useRepoInfo();
  const REPOS = info.repos || [];
  const PROJECT = info.project;
  const [ticket, setTicket] = useState20("");
  const [prompt, setPrompt] = useState20("");
  const [files, setFiles] = useState20([]);
  const [busy, setBusy] = useState20(false);
  const [mode, setMode] = useState20(initialMode);
  const [pickedEnv, setEnv] = useState20("");
  const [chrome, setChrome] = useState20(false);
  const scq = useQuery({ queryKey: ["cockpit", "shared-chrome"], queryFn: () => CTX.rest("/shared-chrome"), refetchInterval: POLL_MS * 2, retry: 0 });
  const lent = scq.data && scq.data.ticket ? scq.data : null;
  const [repos, setRepos] = useState20([]);
  const qc = useQueryClient();
  const key = ticket.trim().toUpperCase();
  const mq = useQuery({ queryKey: ["cockpit", "kickoff-modes"], queryFn: () => CTX.rest("/kickoff-modes"), staleTime: POLL_MS * 6, retry: 0 });
  const added = (mq.data && mq.data.modes || []).filter((m) => m.owner);
  const plugged = added.find((m) => m.mode === mode);
  const cq = useCapacity();
  const envs = cq.data && cq.data.environments || [];
  const env = pickedEnv || (envs.find((e) => !e.slot) || envs[0] || { name: "" }).name;
  const slotted = Boolean((envs.find((e) => e.name === env) || {}).slot);
  const full = capFree(cq.data && cq.data.flows, mode, slotted);
  const ok = (mode === "bumps" ? repos.length > 0 : /^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$/.test(key)) && !full;
  const go = async () => {
    if (!ok || busy) return;
    setBusy(true);
    try {
      const r = await post("/kickoff", mode === "bumps" ? { mode, repos, prompt } : {
        ticket: key,
        prompt,
        mode,
        evidence: files.map((f) => f.path),
        ...mode === "test" ? { env } : {},
        ...mode === "test" && chrome ? { chrome: true } : {}
      });
      host.notify({
        kind: "success",
        title: `${mode === "bumps" ? repos.join(", ") : key} \u2192 ${mode}${mode === "test" ? " on " + env : ""}`,
        message: r.out
      });
      qc.invalidateQueries({ queryKey: ["cockpit"] });
      onDone();
    } catch (e) {
      host.notifyError(e, "kickoff failed");
    } finally {
      setBusy(false);
    }
  };
  return h(
    "div",
    { className: "flex flex-col gap-2 border-b px-3 py-2 text-xs", style: { borderColor: "var(--ui-accent)" } },
    h("div", { className: "flex items-center gap-2" }, h("div", { className: "font-medium" }, "Kick off"), tabs(mode, setMode, [...kickoffTabs(info.hints), ...added.map((m) => [m.mode, m.label])])),
    mode === "test" ? h("div", { className: "flex items-center gap-2" }, h("span", { style: sub }, "where"), tabs(env, setEnv, envs.map((e) => [e.name, e.slot ? `${e.name} (a slot of this machine)` : `${e.name} (test accounts)`]))) : null,
    h("div", { style: sub }, mode === "intake" ? 'A tracker key is enough: intake reads the ticket, reproduces on a free slot, proposes the plan on a card and asks you "go?" here. For an issue without a ticket, pick a key like ' + localKey(PROJECT) + " and describe it; intake proposes the ticket too." : mode === "test" ? !slotted ? 'A tester stakes out the test report comment (init), writes the plan and asks you "go?". After your go it runs on staging with the test accounts in its vault (it never sees a password; a failed login asks you here in a masked form). Every run comes back for your review with its results and evidence (failures recorded on video); only after you accept does the post wait in the Outbox for you to publish. Nothing destructive, nothing outside the test accounts; the test data it creates is kept as the reference and the evidence.' : `A tester stakes out the test report comment (init), writes the plan and asks you "go?". After your go it runs on its local slot (the ticket's worktree branches when there are any, else the base branch). Every run comes back for your review with its results and evidence (failures recorded on video); only after you accept does the post wait in the Outbox for you to publish. The test data it creates is kept as the reference and the evidence.` : mode === "review" ? hintsOf(info.hints).review : mode === "bumps" ? hintsOf(info.hints).bumps : plugged ? plugged.text || plugged.label : "The analyst answers with evidence from code, staging and logs (read-only). Its answer and the files it wrote come to the Inbox as a row: reopen, rework or kick off with them in one click, ask for a patch plan, or dismiss."),
    h(
      "div",
      { className: "flex gap-2" },
      mode === "bumps" ? h("div", { className: "flex flex-wrap items-center gap-2 text-xs" }, ...REPOS.map((r) => h("label", { key: r, className: "flex items-center gap-1" }, h("input", { type: "checkbox", checked: repos.includes(r), onChange: (e) => setRepos(e.target.checked ? [...repos, r] : repos.filter((x) => x !== r)) }), r))) : h("input", { value: ticket, onChange: (e) => setTicket(e.target.value), placeholder: "TASK-100", autoFocus: true, className: "w-32 rounded border bg-transparent px-1.5 py-0.5", style: { ...mono, borderColor: ok || !ticket ? stroke : "var(--ui-danger, #d33)" } }),
      h(ClearableTextarea, {
        value: prompt,
        onChange: (e) => setPrompt(e.target.value),
        rows: 2,
        placeholder: mode === "intake" ? "optional: what you already know, constraints, where to look, what not to touch" : mode === "test" ? "optional: scope, ACs to cover, test data to use, what not to touch" : mode === "review" ? 'optional note for the reviewer (e.g. focus on the PDF path; "findings only" to skip the intents)' : "your question",
        onPaste: ok ? onPasteImages(key, setFiles) : void 0,
        className: "min-w-0 flex-1 rounded border bg-transparent px-1.5 py-0.5",
        style: { borderColor: stroke }
      })
    ),
    mode === "test" ? h(
      "label",
      { className: "flex items-center gap-1.5", title: "this test kickoff drives the external browser (Chrome on its DevTools port, through Chrome MCP) for a few hours (Settings) instead of the built-in one; every other flow, and every supervisor card, runs on the built-in browser" },
      h("input", { type: "checkbox", checked: chrome, disabled: Boolean(lent && lent.ticket !== key), onChange: (e) => setChrome(e.target.checked) }),
      "use the external browser (my Chrome) for this test",
      lent ? h("span", { style: sub }, ` \xB7 lent to ${lent.ticket} until ${new Date(lent.until * 1e3).toTimeString().slice(0, 5)} `, h("a", { href: "#", onClick: async (e) => {
        e.preventDefault();
        try {
          await post("/shared-chrome-release", {});
          scq.refetch && scq.refetch();
        } catch (err) {
          host.notifyError(err, "release failed");
        }
      } }, "release")) : null
    ) : null,
    ok && mode !== "bumps" ? h(Attach, { ticket: key, files, setFiles }) : null,
    full ? h("div", { className: "rounded border px-2 py-1 text-xs", style: { borderColor: "var(--ui-danger, #d33)", color: "var(--ui-danger, #d33)" }, title: full.why }, `No capacity for ${full.label} right now: ${full.why}`) : null,
    h(
      "div",
      { className: "flex gap-1.5" },
      h(
        "button",
        {
          type: "button",
          disabled: busy || !ok || mode === "analyst" && !prompt.trim(),
          onClick: go,
          className: "rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40",
          style: { background: "var(--ui-accent)", color: "#fff" }
        },
        busy ? "working" : mode === "intake" ? "Hand to intake" : mode === "test" ? `Hand to a tester (${env})` : mode === "review" ? "Ask for the review" : "Ask the analyst"
      ),
      btn("Cancel", onDone)
    )
  );
}
function OutboxPage({ initialView, openGroups } = {}) {
  const q2 = useList();
  const asksInbox = () => {
    try {
      return /(?:^|[#&])plugin=/.test((window.location || {}).hash || "");
    } catch {
      return false;
    }
  };
  const [view, setViewRaw] = useState20(() => {
    if (asksInbox()) return "inbox";
    const v = initialView ?? CTX.storage.get("view3", "inbox");
    return v === "outbox" ? "inbox" : v;
  });
  const setView = (v) => {
    setViewRaw(v);
    CTX.storage.set("view3", v);
  };
  const [kick, setKick] = useState20(false);
  const [tools, setTools] = useState20(false);
  useEffect12(() => {
    if (typeof window === "undefined" || !window.addEventListener) return void 0;
    const follow = () => {
      if (asksInbox()) setView("inbox");
    };
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  const qc = useQueryClient();
  const allRows = q2.data && q2.data.rows || [];
  const refresh = () => qc.invalidateQueries({ queryKey: ["cockpit"] });
  const renumber = async () => {
    try {
      await post("/digest");
      host.notify({ kind: "info", message: "Digest renumbered" });
      refresh();
    } catch (e) {
      host.notifyError(e, "renumber failed");
    }
  };
  const sweep = async () => {
    try {
      const r = await post("/sweep");
      host.notify({ kind: "info", title: "Gatekeeper", message: r.out });
    } catch (e) {
      host.notifyError(e, "sweep failed");
    }
  };
  const toolbar = h(
    "div",
    { className: "flex items-center gap-3 px-3 py-2 border-b", style: { borderColor: stroke } },
    h(
      "div",
      { className: "flex items-center gap-1 rounded border p-0.5", style: { borderColor: stroke } },
      seg(view, "inbox", "Inbox", setView),
      seg(view, "board", "Board", setView),
      seg(view, "live", "Live", setView),
      seg(view, "worktrees", "Tickets", setView),
      seg(view, "qa", "QA evidence", setView),
      seg(view, "platform", "Platform", setView),
      seg(view, "usage", "Usage", setView),
      seg(view, "vault", "Vault", setView),
      seg(view, "settings", "Settings", setView)
    ),
    h(PluginPages, {}),
    view === "inbox" || view === "board" ? null : view === "qa" ? h(
      "div",
      { className: "text-xs", style: sub },
      "every ticket with test runs under qa/"
    ) : view === "live" ? h(
      "div",
      { className: "text-xs", style: sub },
      "the bots at work: lane run logs and coding tool transcripts, following the tail"
    ) : view === "usage" ? h(
      "div",
      { className: "text-xs", style: sub },
      "tokens and estimated cost: every lane and every coding tool run, against the plan windows"
    ) : view === "platform" ? h(
      "div",
      { className: "text-xs", style: sub },
      "what the platform does, down to the code; what landed on the base branch per area, explained"
    ) : view === "vault" ? h(
      "div",
      { className: "text-xs", style: sub },
      "vaults and the logins, keys and notes they hold; values open only when you ask"
    ) : h(
      "div",
      { className: "text-xs", style: sub },
      "every ticket this machine holds"
    ),
    h(
      "div",
      { className: "ml-auto flex items-center gap-1.5" },
      h(CapacityPills, {}),
      btn(kick ? "Close" : "+ Kick off", () => setKick(!kick), { accent: !kick, title: 'a ticket key (or a described issue) \u2192 intake proposes a plan and asks you "go?" here' }),
      h(ChatButton, { ticket: "own", label: "Chat" }),
      // your own coding tool: the workspace, outside every flow
      view === "inbox" ? btn(tools ? "Gate tools \u25BE" : "Gate tools \u25B8", () => setTools(!tools), { title: "sweep, renumber, rescan" }) : null,
      view === "inbox" && tools ? btn("Sweep now", sweep, { title: "ask the gatekeeper to endorse or hold the pending intents now (sweeps also start by themselves when an intent is written)" }) : null,
      view === "inbox" && tools ? btn("Renumber", renumber, { title: 'cockpit outbox digest: refreshes the #-numbers that "publish 1-3" uses' }) : null,
      view === "inbox" && tools ? btn("Rescan PRs", async () => {
        try {
          await post("/pr-scan");
          host.notify({ kind: "info", message: "PRs rescanned" });
          refresh();
        } catch (e) {
          host.notifyError(e, "rescan failed");
        }
      }, { title: "cockpit watch-pr scan now (the cron does it every 5 min)" }) : null
    )
  );
  return h(
    "div",
    { className: "flex h-full flex-col text-sm", "data-selectable-text": "true", "data-plugin-root": "cockpit" },
    toolbar,
    kick ? h(KickoffForm, { onDone: () => setKick(false) }) : null,
    // Hermes's gateway sometimes stops answering for a few seconds (busy starting lane workers): that is not a plugin
    // that is missing, so it reads as a quiet retry over the last data, not as a red setup hint.
    q2.error ? q2.data || /ticket bootstrap|Timed out connecting|ECONNREFUSED|ECONNRESET/i.test(String(q2.error.message || q2.error)) ? h("div", { className: "px-3 py-1 text-[0.6875rem]", "data-reconnecting": "1", style: { color: "var(--ui-text-tertiary)" } }, "Hermes did not answer for a moment \u2014 retrying" + (q2.data ? "; the last data is shown" : "")) : h("div", { className: "p-3 text-xs", style: { color: "var(--ui-danger, #d33)" } }, "Backend not reachable: ", String(q2.error.message || q2.error), " \u2014 is cockpit in plugins.enabled (~/.hermes/config.yaml)? cockpit setup apply does that.") : null,
    view === "usage" ? h(Usage, {}) : view === "vault" ? h(Vault, {}) : view === "settings" ? h(Settings, {}) : view === "platform" ? h(Platform, {}) : view === "live" ? h(Live, {}) : view === "qa" ? h(QaIndex, {}) : view === "board" ? h(Board, {}) : view === "worktrees" ? h(Tickets, {}) : h(Inbox, { rows: allRows, refresh, openAll: openGroups }),
    h(
      "div",
      { className: "border-t px-3 py-1 text-[0.6875rem]", style: { ...sub, borderColor: stroke } },
      "Inbox = your to-do, then the gate under it (in flight \xB7 published \xB7 dropped: the gatekeeper endorses, you publish) \xB7 Live = the bots at work \xB7 Kanban page = the big picture."
    )
  );
}
function Chip() {
  const q2 = useList();
  const nq = useQuery({ queryKey: ["cockpit", "needs-you"], queryFn: () => CTX.rest("/needs-you"), refetchInterval: POLL_MS, retry: 1 });
  const aq = useQuery({ queryKey: ["cockpit", "advisories"], queryFn: () => CTX.rest("/advisories"), refetchInterval: POLL_MS * 6, retry: 0 });
  const rows = q2.data && q2.data.rows || [];
  const endorsedIds = rows.filter((r) => r.status === "endorsed" && r.type !== "ticket-done" && !r.waits).map((r) => r.id);
  const prNew = rows.filter((r) => r.pr && r.pr.new_count && r.pr.role !== "reviewer").map((r) => `${r.ticket}#${r.pr.number}:${r.pr.new.map((c) => c.id).join("+")}`);
  const reReq = [...new Set(rows.flatMap((r) => (r.prs || []).filter((p) => p.role === "reviewer" && !p.merged && (p.re_requested || p.my_threads && p.my_threads.total && p.my_threads.resolved === p.my_threads.total)).map((p) => `${r.ticket}#${p.number}:${p.re_requested ? "req" : "resolved"}`)))];
  const ciFail = rows.filter((r) => r.ci && r.ci.state === "failed" && !r.ci.handled && !r.ci.analysing).map((r) => `${r.ticket}:${r.ci.sha}`);
  const acks = rows.filter((r) => r.type === "ticket-done" && r.status === "pending").map((r) => r.id);
  const posted = rows.filter((r) => r.status === "posted").map((r) => r.id);
  const approved = [...new Set(rows.filter((r) => r.pr && !r.pr.merged && r.pr.approvals && r.pr.approvals.length).map((r) => `${r.ticket}#${r.pr.number}`))];
  const watchersBad = (nq.data && nq.data.watchers || []).filter((w) => !w.ok).map((w) => w.name);
  const blocked = (nq.data && nq.data.cards || []).filter((c) => c.status === "blocked" || c.status === "triage").map((c) => c.id);
  const advisories = CTX.storage.get("showSecurity", false) ? (aq.data && aq.data.advisories || []).filter((a) => a.alert && !a.acknowledged).map((a) => a.id) : [];
  const watch = (key, ids, title, body) => useEffect12(() => {
    if (!q2.data) return;
    const seen = new Set(CTX.storage.get(key, []));
    const fresh = ids.filter((x) => !seen.has(x));
    if (fresh.length) CTX.os.notify({ title, body: body(fresh), activate: true, onActivate: () => host.navigate("/cockpit") });
    CTX.storage.set(key, ids);
  }, [ids.join(",")]);
  watch("seenEndorsed", endorsedIds, "Outbox: endorsed, waiting for you", (f) => f.join(", "));
  watch("seenPrNew", prNew, "PR comments ahead of the pipeline", (f) => f.map((k) => k.split(":")[0]).join(", "));
  watch("seenCiFail", ciFail, "CI failed", (f) => f.map((k) => k.split(":")[0]).join(", ") + " \u2014 the analyst is diagnosing");
  watch("seenAcks", acks, "Ticket done: your final ack", (f) => f.join(", "));
  watch("seenPosted", posted, "Pending review posted: check it on the forge, then publish", (f) => f.join(", "));
  watch("seenApproved", approved, "PR approved: merge when ready", (f) => f.join(", "));
  watch("seenReReq", reReq, "A PR you review is ready for re-review", (f) => f.map((k) => k.split(":")[0]).join(", "));
  watch("seenWatchers", watchersBad, "A watcher is failing", (f) => f.join(", "));
  watch("seenBlocked", blocked, "A lane needs your answer", (f) => `${f.length} blocked card(s) \u2014 answer in the Outbox`);
  watch("seenAdvisories", advisories, "Stack advisory: a component we run is vulnerable", (f) => f.join(", "));
  const open = q2.data && q2.data.counts ? (q2.data.counts.pending || 0) + (q2.data.counts.endorsed || 0) + (q2.data.counts.held || 0) + (q2.data.counts.returned || 0) : 0;
  const needs = endorsedIds.length + blocked.length + acks.length + ciFail.length + prNew.length + posted.length + approved.length + watchersBad.length + reReq.length + advisories.length;
  if (!q2.data) return null;
  return h("button", {
    type: "button",
    onClick: () => {
      haptic("tap");
      host.navigate("/cockpit");
    },
    className: "px-1.5 text-[0.6875rem]",
    title: `outbox: ${open} open \xB7 needs you: ${endorsedIds.length} to publish, ${blocked.length} questions, ${acks.length} acks, ${ciFail.length} CI failures, ${prNew.length} PRs with new comments, ${advisories.length} advisories`,
    style: { color: needs ? blocked.length || ciFail.length ? "var(--ui-warning, #c98a00)" : "var(--ui-success, #2a9d5c)" : "var(--ui-text-tertiary)" }
  }, needs ? `cockpit \xB7 ${needs} need you` : `cockpit \xB7 ${open} at the gate`);
}

// src/lib/overrides.js
var OVERRIDES = {
  // Hermes hides Appearance → Translucency on Linux, taking window opacity for a no-op there, but WSLg applies it: the
  // default intensity 29 leaves the window see-through, with no setting to turn it off.
  "opaque-window": {
    key: "hermes.desktop.translucency.v2",
    value: { mode: "clear", base: { intensity: 0 }, light: { intensity: 0 }, dark: { intensity: 0 } }
  }
};
var RELOADED = "cockpit.desktop-overrides.reloaded";
function applyOverrides(names, storage) {
  let changed = false;
  for (const name of names || []) {
    const entry = OVERRIDES[name];
    if (!entry) continue;
    const want = JSON.stringify(entry.value);
    try {
      if (storage.getItem(entry.key) === want) continue;
      storage.setItem(entry.key, want);
      changed = storage.getItem(entry.key) === want || changed;
    } catch (e) {
    }
  }
  return changed;
}
async function startOverrides(rest, win = window, tries = 5, waitMs = 1e4) {
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      const { overrides } = await rest("/desktop-overrides");
      if (!applyOverrides(overrides, win.localStorage)) return false;
      if (win.sessionStorage.getItem(RELOADED)) return false;
      win.sessionStorage.setItem(RELOADED, "1");
      win.location.reload();
      return true;
    } catch (e) {
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }
  }
  return false;
}

// src/index.js
var index_default = {
  id: "cockpit",
  name: "Cockpit",
  defaultEnabled: true,
  register(ctx) {
    setCTX(ctx);
    const style = document.createElement("style");
    style.setAttribute("data-plugin", "cockpit");
    style.textContent = CSS;
    document.head.appendChild(style);
    ctx.onDispose(() => style.remove());
    ctx.registerMany([
      { id: "page", area: ROUTES_AREA, data: { path: "/cockpit" }, render: () => jsx(OutboxPage, {}) },
      { id: "nav", area: SIDEBAR_NAV_AREA, order: 61, data: { path: "/cockpit", label: "Cockpit", codicon: "dashboard" } },
      { id: "chip", area: "statusBar.right", order: 120, render: () => jsx(Chip, {}) }
    ]);
    startOverrides((path) => ctx.rest(path)).catch(() => {
    });
  }
};
export {
  index_default as default
};
