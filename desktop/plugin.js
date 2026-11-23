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
var xterm_default = '!function(e,t){if("object"==typeof exports&&"object"==typeof module)module.exports=t();else if("function"==typeof define&&define.amd)define([],t);else{var i=t();for(var s in i)("object"==typeof exports?exports:e)[s]=i[s]}}(globalThis,(()=>(()=>{"use strict";var e={2840:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.AccessibilityManager=void 0;const n=i(7721),o=i(4292),a=i(7150),l=i(7098),h=i(6501),c=i(7093);let d=class extends a.Disposable{constructor(e,t,i,s){super(),this._terminal=e,this._coreBrowserService=i,this._renderService=s,this._rowColumns=new WeakMap,this._liveRegionLineCount=0,this._charsToConsume=[],this._charsToAnnounce="";const r=this._coreBrowserService.mainDocument;this._accessibilityContainer=r.createElement("div"),this._accessibilityContainer.classList.add("xterm-accessibility"),this._rowContainer=r.createElement("div"),this._rowContainer.setAttribute("role","list"),this._rowContainer.classList.add("xterm-accessibility-tree"),this._rowElements=[];for(let e=0;e<this._terminal.rows;e++)this._rowElements[e]=this._createAccessibilityTreeNode(),this._rowContainer.appendChild(this._rowElements[e]);if(this._topBoundaryFocusListener=e=>this._handleBoundaryFocus(e,0),this._bottomBoundaryFocusListener=e=>this._handleBoundaryFocus(e,1),this._rowElements[0].addEventListener("focus",this._topBoundaryFocusListener),this._rowElements[this._rowElements.length-1].addEventListener("focus",this._bottomBoundaryFocusListener),this._accessibilityContainer.appendChild(this._rowContainer),this._liveRegion=r.createElement("div"),this._liveRegion.classList.add("live-region"),this._liveRegion.setAttribute("aria-live","assertive"),this._accessibilityContainer.appendChild(this._liveRegion),this._liveRegionDebouncer=this._register(new o.TimeBasedDebouncer(this._renderRows.bind(this))),!this._terminal.element)throw new Error("Cannot enable accessibility before Terminal.open");this._terminal.element.insertAdjacentElement("afterbegin",this._accessibilityContainer),this._register(this._terminal.onResize((e=>this._handleResize(e.rows)))),this._register(this._terminal.onRender((e=>this._refreshRows(e.start,e.end)))),this._register(this._terminal.onScroll((()=>this._refreshRows()))),this._register(this._terminal.onA11yChar((e=>this._handleChar(e)))),this._register(this._terminal.onLineFeed((()=>this._handleChar("\\n")))),this._register(this._terminal.onA11yTab((e=>this._handleTab(e)))),this._register(this._terminal.onKey((e=>this._handleKey(e.key)))),this._register(this._terminal.onBlur((()=>this._clearLiveRegion()))),this._register(this._renderService.onDimensionsChange((()=>this._refreshRowsDimensions()))),this._register((0,c.addDisposableListener)(r,"selectionchange",(()=>this._handleSelectionChange()))),this._register(this._coreBrowserService.onDprChange((()=>this._refreshRowsDimensions()))),this._refreshRowsDimensions(),this._refreshRows(),this._register((0,a.toDisposable)((()=>{this._accessibilityContainer.remove(),this._rowElements.length=0})))}_handleTab(e){for(let t=0;t<e;t++)this._handleChar(" ")}_handleChar(e){this._liveRegionLineCount<21&&(this._charsToConsume.length>0?this._charsToConsume.shift()!==e&&(this._charsToAnnounce+=e):this._charsToAnnounce+=e,"\\n"===e&&(this._liveRegionLineCount++,21===this._liveRegionLineCount&&(this._liveRegion.textContent+=n.tooMuchOutput.get())))}_clearLiveRegion(){this._liveRegion.textContent="",this._liveRegionLineCount=0}_handleKey(e){this._clearLiveRegion(),/\\p{Control}/u.test(e)||this._charsToConsume.push(e)}_refreshRows(e,t){this._liveRegionDebouncer.refresh(e,t,this._terminal.rows)}_renderRows(e,t){const i=this._terminal.buffer,s=i.lines.length.toString();for(let r=e;r<=t;r++){const e=i.lines.get(i.ydisp+r),t=[],n=e?.translateToString(!0,void 0,void 0,t)||"",o=(i.ydisp+r+1).toString(),a=this._rowElements[r];a&&(0===n.length?(a.textContent="\xA0",this._rowColumns.set(a,[0,1])):(a.textContent=n,this._rowColumns.set(a,t)),a.setAttribute("aria-posinset",o),a.setAttribute("aria-setsize",s),this._alignRowWidth(a))}this._announceCharacters()}_announceCharacters(){0!==this._charsToAnnounce.length&&(this._liveRegion.textContent+=this._charsToAnnounce,this._charsToAnnounce="")}_handleBoundaryFocus(e,t){const i=e.target,s=this._rowElements[0===t?1:this._rowElements.length-2];if(i.getAttribute("aria-posinset")===(0===t?"1":`${this._terminal.buffer.lines.length}`))return;if(e.relatedTarget!==s)return;let r,n;if(0===t?(r=i,n=this._rowElements.pop(),this._rowContainer.removeChild(n)):(r=this._rowElements.shift(),n=i,this._rowContainer.removeChild(r)),r.removeEventListener("focus",this._topBoundaryFocusListener),n.removeEventListener("focus",this._bottomBoundaryFocusListener),0===t){const e=this._createAccessibilityTreeNode();this._rowElements.unshift(e),this._rowContainer.insertAdjacentElement("afterbegin",e)}else{const e=this._createAccessibilityTreeNode();this._rowElements.push(e),this._rowContainer.appendChild(e)}this._rowElements[0].addEventListener("focus",this._topBoundaryFocusListener),this._rowElements[this._rowElements.length-1].addEventListener("focus",this._bottomBoundaryFocusListener),this._terminal.scrollLines(0===t?-1:1),this._rowElements[0===t?1:this._rowElements.length-2].focus(),e.preventDefault(),e.stopImmediatePropagation()}_handleSelectionChange(){if(0===this._rowElements.length)return;const e=this._coreBrowserService.mainDocument.getSelection();if(!e)return;if(e.isCollapsed)return void(this._rowContainer.contains(e.anchorNode)&&this._terminal.clearSelection());if(!e.anchorNode||!e.focusNode)return void console.error("anchorNode and/or focusNode are null");let t={node:e.anchorNode,offset:e.anchorOffset},i={node:e.focusNode,offset:e.focusOffset};if((t.node.compareDocumentPosition(i.node)&Node.DOCUMENT_POSITION_PRECEDING||t.node===i.node&&t.offset>i.offset)&&([t,i]=[i,t]),t.node.compareDocumentPosition(this._rowElements[0])&(Node.DOCUMENT_POSITION_CONTAINED_BY|Node.DOCUMENT_POSITION_FOLLOWING)&&(t={node:this._rowElements[0].childNodes[0],offset:0}),!this._rowContainer.contains(t.node))return;const s=this._rowElements.slice(-1)[0];if(i.node.compareDocumentPosition(s)&(Node.DOCUMENT_POSITION_CONTAINED_BY|Node.DOCUMENT_POSITION_PRECEDING)&&(i={node:s,offset:s.textContent?.length??0}),!this._rowContainer.contains(i.node))return;const r=({node:e,offset:t})=>{const i=e instanceof Text?e.parentNode:e;let s=parseInt(i?.getAttribute("aria-posinset"),10)-1;if(isNaN(s))return console.warn("row is invalid. Race condition?"),null;const r=this._rowColumns.get(i);if(!r)return console.warn("columns is null. Race condition?"),null;let n=t<r.length?r[t]:r.slice(-1)[0]+1;return n>=this._terminal.cols&&(++s,n=0),{row:s,column:n}},n=r(t),o=r(i);if(n&&o){if(n.row>o.row||n.row===o.row&&n.column>=o.column)throw new Error("invalid range");this._terminal.select(n.column,n.row,(o.row-n.row)*this._terminal.cols-n.column+o.column)}}_handleResize(e){this._rowElements[this._rowElements.length-1].removeEventListener("focus",this._bottomBoundaryFocusListener);for(let e=this._rowContainer.children.length;e<this._terminal.rows;e++)this._rowElements[e]=this._createAccessibilityTreeNode(),this._rowContainer.appendChild(this._rowElements[e]);for(;this._rowElements.length>e;)this._rowContainer.removeChild(this._rowElements.pop());this._rowElements[this._rowElements.length-1].addEventListener("focus",this._bottomBoundaryFocusListener),this._refreshRowsDimensions()}_createAccessibilityTreeNode(){const e=this._coreBrowserService.mainDocument.createElement("div");return e.setAttribute("role","listitem"),e.tabIndex=-1,this._refreshRowDimensions(e),e}_refreshRowsDimensions(){if(this._renderService.dimensions.css.cell.height){Object.assign(this._accessibilityContainer.style,{width:`${this._renderService.dimensions.css.canvas.width}px`,fontSize:`${this._terminal.options.fontSize}px`}),this._rowElements.length!==this._terminal.rows&&this._handleResize(this._terminal.rows);for(let e=0;e<this._terminal.rows;e++)this._refreshRowDimensions(this._rowElements[e]),this._alignRowWidth(this._rowElements[e])}}_refreshRowDimensions(e){e.style.height=`${this._renderService.dimensions.css.cell.height}px`}_alignRowWidth(e){e.style.transform="";const t=e.getBoundingClientRect().width,i=this._rowColumns.get(e)?.slice(-1)?.[0];if(!i)return;const s=i*this._renderService.dimensions.css.cell.width;e.style.transform=`scaleX(${s/t})`}};t.AccessibilityManager=d,t.AccessibilityManager=d=s([r(1,h.IInstantiationService),r(2,l.ICoreBrowserService),r(3,l.IRenderService)],d)},7861:(e,t)=>{function i(e){return e.replace(/\\r?\\n/g,"\\r")}function s(e,t){return t?"\x1B[200~"+e+"\x1B[201~":e}function r(e,t,r,n){e=s(e=i(e),r.decPrivateModes.bracketedPasteMode&&!0!==n.rawOptions.ignoreBracketedPasteMode),r.triggerDataEvent(e,!0),t.value=""}function n(e,t,i){const s=i.getBoundingClientRect(),r=e.clientX-s.left-10,n=e.clientY-s.top-10;t.style.width="20px",t.style.height="20px",t.style.left=`${r}px`,t.style.top=`${n}px`,t.style.zIndex="1000",t.focus()}Object.defineProperty(t,"__esModule",{value:!0}),t.prepareTextForTerminal=i,t.bracketTextForPaste=s,t.copyHandler=function(e,t){e.clipboardData&&e.clipboardData.setData("text/plain",t.selectionText),e.preventDefault()},t.handlePasteEvent=function(e,t,i,s){e.stopPropagation(),e.clipboardData&&r(e.clipboardData.getData("text/plain"),t,i,s)},t.paste=r,t.moveTextAreaUnderMouseCursor=n,t.rightClickHandler=function(e,t,i,s,r){n(e,t,i),r&&s.rightClickSelect(e),t.value=s.selectionText,t.select()}},7174:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ColorContrastCache=void 0;const s=i(7710);t.ColorContrastCache=class{constructor(){this._color=new s.TwoKeyMap,this._css=new s.TwoKeyMap}setCss(e,t,i){this._css.set(e,t,i)}getCss(e,t){return this._css.get(e,t)}setColor(e,t,i){this._color.set(e,t,i)}getColor(e,t){return this._color.get(e,t)}clear(){this._color.clear(),this._css.clear()}}},1718:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CoreBrowserTerminal=void 0;const s=i(7861),r=i(7721),n=i(3285),o=i(4017),a=i(4196),l=i(9925),h=i(3618),c=i(3955),d=i(4792),u=i(945),_=i(9574),f=i(9820),p=i(9784),g=i(5783),m=i(2079),v=i(7098),S=i(9078),b=i(4103),C=i(5777),y=i(701),w=i(6107),E=i(3534),D=i(706),L=i(8693),R=i(4720),A=i(6501),T=i(2486),k=i(2840),M=i(8906),O=i(802),I=i(7093),P=i(7150);class x extends C.CoreTerminal{get linkifier(){return this._linkifier.value}get onFocus(){return this._onFocus.event}get onBlur(){return this._onBlur.event}get onA11yChar(){return this._onA11yCharEmitter.event}get onA11yTab(){return this._onA11yTabEmitter.event}get onWillOpen(){return this._onWillOpen.event}constructor(e={}){super(e),this._linkifier=this._register(new P.MutableDisposable),this.browser=y,this._keyDownHandled=!1,this._keyDownSeen=!1,this._keyPressHandled=!1,this._unprocessedDeadKey=!1,this._accessibilityManager=this._register(new P.MutableDisposable),this._onCursorMove=this._register(new O.Emitter),this.onCursorMove=this._onCursorMove.event,this._onKey=this._register(new O.Emitter),this.onKey=this._onKey.event,this._onRender=this._register(new O.Emitter),this.onRender=this._onRender.event,this._onSelectionChange=this._register(new O.Emitter),this.onSelectionChange=this._onSelectionChange.event,this._onTitleChange=this._register(new O.Emitter),this.onTitleChange=this._onTitleChange.event,this._onBell=this._register(new O.Emitter),this.onBell=this._onBell.event,this._onFocus=this._register(new O.Emitter),this._onBlur=this._register(new O.Emitter),this._onA11yCharEmitter=this._register(new O.Emitter),this._onA11yTabEmitter=this._register(new O.Emitter),this._onWillOpen=this._register(new O.Emitter),this._setup(),this._decorationService=this._instantiationService.createInstance(R.DecorationService),this._instantiationService.setService(A.IDecorationService,this._decorationService),this._linkProviderService=this._instantiationService.createInstance(f.LinkProviderService),this._instantiationService.setService(v.ILinkProviderService,this._linkProviderService),this._linkProviderService.registerLinkProvider(this._instantiationService.createInstance(n.OscLinkProvider)),this._register(this._inputHandler.onRequestBell((()=>this._onBell.fire()))),this._register(this._inputHandler.onRequestRefreshRows((e=>this.refresh(e?.start??0,e?.end??this.rows-1)))),this._register(this._inputHandler.onRequestSendFocus((()=>this._reportFocus()))),this._register(this._inputHandler.onRequestReset((()=>this.reset()))),this._register(this._inputHandler.onRequestWindowsOptionsReport((e=>this._reportWindowsOptions(e)))),this._register(this._inputHandler.onColor((e=>this._handleColorEvent(e)))),this._register(O.Event.forward(this._inputHandler.onCursorMove,this._onCursorMove)),this._register(O.Event.forward(this._inputHandler.onTitleChange,this._onTitleChange)),this._register(O.Event.forward(this._inputHandler.onA11yChar,this._onA11yCharEmitter)),this._register(O.Event.forward(this._inputHandler.onA11yTab,this._onA11yTabEmitter)),this._register(this._bufferService.onResize((e=>this._afterResize(e.cols,e.rows)))),this._register((0,P.toDisposable)((()=>{this._customKeyEventHandler=void 0,this.element?.parentNode?.removeChild(this.element)})))}_handleColorEvent(e){if(this._themeService)for(const t of e){let e,i="";switch(t.index){case 256:e="foreground",i="10";break;case 257:e="background",i="11";break;case 258:e="cursor",i="12";break;default:e="ansi",i="4;"+t.index}switch(t.type){case 0:const s=b.color.toColorRGB("ansi"===e?this._themeService.colors.ansi[t.index]:this._themeService.colors[e]);this.coreService.triggerDataEvent(`${E.C0.ESC}]${i};${(0,L.toRgbString)(s)}${E.C1_ESCAPED.ST}`);break;case 1:if("ansi"===e)this._themeService.modifyColors((e=>e.ansi[t.index]=b.channels.toColor(...t.color)));else{const i=e;this._themeService.modifyColors((e=>e[i]=b.channels.toColor(...t.color)))}break;case 2:this._themeService.restoreColor(t.index)}}}_setup(){super._setup(),this._customKeyEventHandler=void 0}get buffer(){return this.buffers.active}focus(){this.textarea&&this.textarea.focus({preventScroll:!0})}_handleScreenReaderModeOptionChange(e){e?!this._accessibilityManager.value&&this._renderService&&(this._accessibilityManager.value=this._instantiationService.createInstance(k.AccessibilityManager,this)):this._accessibilityManager.clear()}_handleTextAreaFocus(e){this.coreService.decPrivateModes.sendFocus&&this.coreService.triggerDataEvent(E.C0.ESC+"[I"),this.element.classList.add("focus"),this._showCursor(),this._onFocus.fire()}blur(){return this.textarea?.blur()}_handleTextAreaBlur(){this.textarea.value="",this.refresh(this.buffer.y,this.buffer.y),this.coreService.decPrivateModes.sendFocus&&this.coreService.triggerDataEvent(E.C0.ESC+"[O"),this.element.classList.remove("focus"),this._onBlur.fire()}_syncTextArea(){if(!this.textarea||!this.buffer.isCursorInViewport||this._compositionHelper.isComposing||!this._renderService)return;const e=this.buffer.ybase+this.buffer.y,t=this.buffer.lines.get(e);if(!t)return;const i=Math.min(this.buffer.x,this.cols-1),s=this._renderService.dimensions.css.cell.height,r=t.getWidth(i),n=this._renderService.dimensions.css.cell.width*r,o=this.buffer.y*this._renderService.dimensions.css.cell.height,a=i*this._renderService.dimensions.css.cell.width;this.textarea.style.left=a+"px",this.textarea.style.top=o+"px",this.textarea.style.width=n+"px",this.textarea.style.height=s+"px",this.textarea.style.lineHeight=s+"px",this.textarea.style.zIndex="-5"}_initGlobal(){this._bindKeys(),this._register((0,I.addDisposableListener)(this.element,"copy",(e=>{this.hasSelection()&&(0,s.copyHandler)(e,this._selectionService)})));const e=e=>(0,s.handlePasteEvent)(e,this.textarea,this.coreService,this.optionsService);this._register((0,I.addDisposableListener)(this.textarea,"paste",e)),this._register((0,I.addDisposableListener)(this.element,"paste",e)),y.isFirefox?this._register((0,I.addDisposableListener)(this.element,"mousedown",(e=>{2===e.button&&(0,s.rightClickHandler)(e,this.textarea,this.screenElement,this._selectionService,this.options.rightClickSelectsWord)}))):this._register((0,I.addDisposableListener)(this.element,"contextmenu",(e=>{(0,s.rightClickHandler)(e,this.textarea,this.screenElement,this._selectionService,this.options.rightClickSelectsWord)}))),y.isLinux&&this._register((0,I.addDisposableListener)(this.element,"auxclick",(e=>{1===e.button&&(0,s.moveTextAreaUnderMouseCursor)(e,this.textarea,this.screenElement)})))}_bindKeys(){this._register((0,I.addDisposableListener)(this.textarea,"keyup",(e=>this._keyUp(e)),!0)),this._register((0,I.addDisposableListener)(this.textarea,"keydown",(e=>this._keyDown(e)),!0)),this._register((0,I.addDisposableListener)(this.textarea,"keypress",(e=>this._keyPress(e)),!0)),this._register((0,I.addDisposableListener)(this.textarea,"compositionstart",(()=>this._compositionHelper.compositionstart()))),this._register((0,I.addDisposableListener)(this.textarea,"compositionupdate",(e=>this._compositionHelper.compositionupdate(e)))),this._register((0,I.addDisposableListener)(this.textarea,"compositionend",(()=>this._compositionHelper.compositionend()))),this._register((0,I.addDisposableListener)(this.textarea,"input",(e=>this._inputEvent(e)),!0)),this._register(this.onRender((()=>this._compositionHelper.updateCompositionElements())))}open(e){if(!e)throw new Error("Terminal requires a parent element.");if(e.isConnected||this._logService.debug("Terminal.open was called on an element that was not attached to the DOM"),this.element?.ownerDocument.defaultView&&this._coreBrowserService)return void(this.element.ownerDocument.defaultView!==this._coreBrowserService.window&&(this._coreBrowserService.window=this.element.ownerDocument.defaultView));this._document=e.ownerDocument,this.options.documentOverride&&this.options.documentOverride instanceof Document&&(this._document=this.optionsService.rawOptions.documentOverride),this.element=this._document.createElement("div"),this.element.dir="ltr",this.element.classList.add("terminal"),this.element.classList.add("xterm"),e.appendChild(this.element);const t=this._document.createDocumentFragment();this._viewportElement=this._document.createElement("div"),this._viewportElement.classList.add("xterm-viewport"),t.appendChild(this._viewportElement),this.screenElement=this._document.createElement("div"),this.screenElement.classList.add("xterm-screen"),this._register((0,I.addDisposableListener)(this.screenElement,"mousemove",(e=>this.updateCursorStyle(e)))),this._helperContainer=this._document.createElement("div"),this._helperContainer.classList.add("xterm-helpers"),this.screenElement.appendChild(this._helperContainer),t.appendChild(this.screenElement);const i=this.textarea=this._document.createElement("textarea");this.textarea.classList.add("xterm-helper-textarea"),this.textarea.setAttribute("aria-label",r.promptLabel.get()),y.isChromeOS||this.textarea.setAttribute("aria-multiline","false"),this.textarea.setAttribute("autocorrect","off"),this.textarea.setAttribute("autocapitalize","off"),this.textarea.setAttribute("spellcheck","false"),this.textarea.tabIndex=0,this._register(this.optionsService.onSpecificOptionChange("disableStdin",(()=>i.readOnly=this.optionsService.rawOptions.disableStdin))),this.textarea.readOnly=this.optionsService.rawOptions.disableStdin,this._coreBrowserService=this._register(this._instantiationService.createInstance(_.CoreBrowserService,this.textarea,e.ownerDocument.defaultView??window,this._document??"undefined"!=typeof window?window.document:null)),this._instantiationService.setService(v.ICoreBrowserService,this._coreBrowserService),this._register((0,I.addDisposableListener)(this.textarea,"focus",(e=>this._handleTextAreaFocus(e)))),this._register((0,I.addDisposableListener)(this.textarea,"blur",(()=>this._handleTextAreaBlur()))),this._helperContainer.appendChild(this.textarea),this._charSizeService=this._instantiationService.createInstance(d.CharSizeService,this._document,this._helperContainer),this._instantiationService.setService(v.ICharSizeService,this._charSizeService),this._themeService=this._instantiationService.createInstance(S.ThemeService),this._instantiationService.setService(v.IThemeService,this._themeService),this._characterJoinerService=this._instantiationService.createInstance(u.CharacterJoinerService),this._instantiationService.setService(v.ICharacterJoinerService,this._characterJoinerService),this._renderService=this._register(this._instantiationService.createInstance(g.RenderService,this.rows,this.screenElement)),this._instantiationService.setService(v.IRenderService,this._renderService),this._register(this._renderService.onRenderedViewportChange((e=>this._onRender.fire(e)))),this.onResize((e=>this._renderService.resize(e.cols,e.rows))),this._compositionView=this._document.createElement("div"),this._compositionView.classList.add("composition-view"),this._compositionHelper=this._instantiationService.createInstance(h.CompositionHelper,this.textarea,this._compositionView),this._helperContainer.appendChild(this._compositionView),this._mouseService=this._instantiationService.createInstance(p.MouseService),this._instantiationService.setService(v.IMouseService,this._mouseService);const s=this._linkifier.value=this._register(this._instantiationService.createInstance(M.Linkifier,this.screenElement));this.element.appendChild(t);try{this._onWillOpen.fire(this.element)}catch{}this._renderService.hasRenderer()||this._renderService.setRenderer(this._createRenderer()),this._register(this.onCursorMove((()=>{this._renderService.handleCursorMove(),this._syncTextArea()}))),this._register(this.onResize((()=>this._renderService.handleResize(this.cols,this.rows)))),this._register(this.onBlur((()=>this._renderService.handleBlur()))),this._register(this.onFocus((()=>this._renderService.handleFocus()))),this._viewport=this._register(this._instantiationService.createInstance(o.Viewport,this.element,this.screenElement)),this._register(this._viewport.onRequestScrollLines((e=>{super.scrollLines(e,!1),this.refresh(0,this.rows-1)}))),this._selectionService=this._register(this._instantiationService.createInstance(m.SelectionService,this.element,this.screenElement,s)),this._instantiationService.setService(v.ISelectionService,this._selectionService),this._register(this._selectionService.onRequestScrollLines((e=>this.scrollLines(e.amount,e.suppressScrollEvent)))),this._register(this._selectionService.onSelectionChange((()=>this._onSelectionChange.fire()))),this._register(this._selectionService.onRequestRedraw((e=>this._renderService.handleSelectionChanged(e.start,e.end,e.columnSelectMode)))),this._register(this._selectionService.onLinuxMouseSelection((e=>{this.textarea.value=e,this.textarea.focus(),this.textarea.select()}))),this._register(O.Event.any(this._onScroll.event,this._inputHandler.onScroll)((()=>{this._selectionService.refresh(),this._viewport?.queueSync()}))),this._register(this._instantiationService.createInstance(a.BufferDecorationRenderer,this.screenElement)),this._register((0,I.addDisposableListener)(this.element,"mousedown",(e=>this._selectionService.handleMouseDown(e)))),this.coreMouseService.areMouseEventsActive?(this._selectionService.disable(),this.element.classList.add("enable-mouse-events")):this._selectionService.enable(),this.options.screenReaderMode&&(this._accessibilityManager.value=this._instantiationService.createInstance(k.AccessibilityManager,this)),this._register(this.optionsService.onSpecificOptionChange("screenReaderMode",(e=>this._handleScreenReaderModeOptionChange(e)))),this.options.overviewRuler.width&&(this._overviewRulerRenderer=this._register(this._instantiationService.createInstance(l.OverviewRulerRenderer,this._viewportElement,this.screenElement))),this.optionsService.onSpecificOptionChange("overviewRuler",(e=>{!this._overviewRulerRenderer&&e&&this._viewportElement&&this.screenElement&&(this._overviewRulerRenderer=this._register(this._instantiationService.createInstance(l.OverviewRulerRenderer,this._viewportElement,this.screenElement)))})),this._charSizeService.measure(),this.refresh(0,this.rows-1),this._initGlobal(),this.bindMouse()}_createRenderer(){return this._instantiationService.createInstance(c.DomRenderer,this,this._document,this.element,this.screenElement,this._viewportElement,this._helperContainer,this.linkifier)}bindMouse(){const e=this,t=this.element;function i(t){const i=e._mouseService.getMouseReportCoords(t,e.screenElement);if(!i)return!1;let s,r;switch(t.overrideType||t.type){case"mousemove":r=32,void 0===t.buttons?(s=3,void 0!==t.button&&(s=t.button<3?t.button:3)):s=1&t.buttons?0:4&t.buttons?1:2&t.buttons?2:3;break;case"mouseup":r=0,s=t.button<3?t.button:3;break;case"mousedown":r=1,s=t.button<3?t.button:3;break;case"wheel":if(e._customWheelEventHandler&&!1===e._customWheelEventHandler(t))return!1;const i=t.deltaY;if(0===i)return!1;if(0===e.coreMouseService.consumeWheelEvent(t,e._renderService?.dimensions?.device?.cell?.height,e._coreBrowserService?.dpr))return!1;r=i<0?0:1,s=4;break;default:return!1}return!(void 0===r||void 0===s||s>4)&&e.coreMouseService.triggerMouseEvent({col:i.col,row:i.row,x:i.x,y:i.y,button:s,action:r,ctrl:t.ctrlKey,alt:t.altKey,shift:t.shiftKey})}const s={mouseup:null,wheel:null,mousedrag:null,mousemove:null},r={mouseup:e=>(i(e),e.buttons||(this._document.removeEventListener("mouseup",s.mouseup),s.mousedrag&&this._document.removeEventListener("mousemove",s.mousedrag)),this.cancel(e)),wheel:e=>(i(e),this.cancel(e,!0)),mousedrag:e=>{e.buttons&&i(e)},mousemove:e=>{e.buttons||i(e)}};this._register(this.coreMouseService.onProtocolChange((e=>{e?("debug"===this.optionsService.rawOptions.logLevel&&this._logService.debug("Binding to mouse events:",this.coreMouseService.explainEvents(e)),this.element.classList.add("enable-mouse-events"),this._selectionService.disable()):(this._logService.debug("Unbinding from mouse events."),this.element.classList.remove("enable-mouse-events"),this._selectionService.enable()),8&e?s.mousemove||(t.addEventListener("mousemove",r.mousemove),s.mousemove=r.mousemove):(t.removeEventListener("mousemove",s.mousemove),s.mousemove=null),16&e?s.wheel||(t.addEventListener("wheel",r.wheel,{passive:!1}),s.wheel=r.wheel):(t.removeEventListener("wheel",s.wheel),s.wheel=null),2&e?s.mouseup||(s.mouseup=r.mouseup):(this._document.removeEventListener("mouseup",s.mouseup),s.mouseup=null),4&e?s.mousedrag||(s.mousedrag=r.mousedrag):(this._document.removeEventListener("mousemove",s.mousedrag),s.mousedrag=null)}))),this.coreMouseService.activeProtocol=this.coreMouseService.activeProtocol,this._register((0,I.addDisposableListener)(t,"mousedown",(e=>{if(e.preventDefault(),this.focus(),this.coreMouseService.areMouseEventsActive&&!this._selectionService.shouldForceSelection(e))return i(e),s.mouseup&&this._document.addEventListener("mouseup",s.mouseup),s.mousedrag&&this._document.addEventListener("mousemove",s.mousedrag),this.cancel(e)}))),this._register((0,I.addDisposableListener)(t,"wheel",(t=>{if(!s.wheel){if(this._customWheelEventHandler&&!1===this._customWheelEventHandler(t))return!1;if(!this.buffer.hasScrollback){if(0===t.deltaY)return!1;if(0===e.coreMouseService.consumeWheelEvent(t,e._renderService?.dimensions?.device?.cell?.height,e._coreBrowserService?.dpr))return this.cancel(t,!0);const i=E.C0.ESC+(this.coreService.decPrivateModes.applicationCursorKeys?"O":"[")+(t.deltaY<0?"A":"B");return this.coreService.triggerDataEvent(i,!0),this.cancel(t,!0)}}}),{passive:!1}))}refresh(e,t){this._renderService?.refreshRows(e,t)}updateCursorStyle(e){this._selectionService?.shouldColumnSelect(e)?this.element.classList.add("column-select"):this.element.classList.remove("column-select")}_showCursor(){this.coreService.isCursorInitialized||(this.coreService.isCursorInitialized=!0,this.refresh(this.buffer.y,this.buffer.y))}scrollLines(e,t){this._viewport?this._viewport.scrollLines(e):super.scrollLines(e,t),this.refresh(0,this.rows-1)}scrollPages(e){this.scrollLines(e*(this.rows-1))}scrollToTop(){this.scrollLines(-this._bufferService.buffer.ydisp)}scrollToBottom(e){e&&this._viewport?this._viewport.scrollToLine(this.buffer.ybase,!0):this.scrollLines(this._bufferService.buffer.ybase-this._bufferService.buffer.ydisp)}scrollToLine(e){const t=e-this._bufferService.buffer.ydisp;0!==t&&this.scrollLines(t)}paste(e){(0,s.paste)(e,this.textarea,this.coreService,this.optionsService)}attachCustomKeyEventHandler(e){this._customKeyEventHandler=e}attachCustomWheelEventHandler(e){this._customWheelEventHandler=e}registerLinkProvider(e){return this._linkProviderService.registerLinkProvider(e)}registerCharacterJoiner(e){if(!this._characterJoinerService)throw new Error("Terminal must be opened first");const t=this._characterJoinerService.register(e);return this.refresh(0,this.rows-1),t}deregisterCharacterJoiner(e){if(!this._characterJoinerService)throw new Error("Terminal must be opened first");this._characterJoinerService.deregister(e)&&this.refresh(0,this.rows-1)}get markers(){return this.buffer.markers}registerMarker(e){return this.buffer.addMarker(this.buffer.ybase+this.buffer.y+e)}registerDecoration(e){return this._decorationService.registerDecoration(e)}hasSelection(){return!!this._selectionService&&this._selectionService.hasSelection}select(e,t,i){this._selectionService.setSelection(e,t,i)}getSelection(){return this._selectionService?this._selectionService.selectionText:""}getSelectionPosition(){if(this._selectionService&&this._selectionService.hasSelection)return{start:{x:this._selectionService.selectionStart[0],y:this._selectionService.selectionStart[1]},end:{x:this._selectionService.selectionEnd[0],y:this._selectionService.selectionEnd[1]}}}clearSelection(){this._selectionService?.clearSelection()}selectAll(){this._selectionService?.selectAll()}selectLines(e,t){this._selectionService?.selectLines(e,t)}_keyDown(e){if(this._keyDownHandled=!1,this._keyDownSeen=!0,this._customKeyEventHandler&&!1===this._customKeyEventHandler(e))return!1;const t=this.browser.isMac&&this.options.macOptionIsMeta&&e.altKey;if(!t&&!this._compositionHelper.keydown(e))return this.options.scrollOnUserInput&&this.buffer.ybase!==this.buffer.ydisp&&this.scrollToBottom(!0),!1;t||"Dead"!==e.key&&"AltGraph"!==e.key||(this._unprocessedDeadKey=!0);const i=(0,D.evaluateKeyboardEvent)(e,this.coreService.decPrivateModes.applicationCursorKeys,this.browser.isMac,this.options.macOptionIsMeta);if(this.updateCursorStyle(e),3===i.type||2===i.type){const t=this.rows-1;return this.scrollLines(2===i.type?-t:t),this.cancel(e,!0)}return 1===i.type&&this.selectAll(),!!this._isThirdLevelShift(this.browser,e)||(i.cancel&&this.cancel(e,!0),!i.key||!!(e.key&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&1===e.key.length&&e.key.charCodeAt(0)>=65&&e.key.charCodeAt(0)<=90)||(this._unprocessedDeadKey?(this._unprocessedDeadKey=!1,!0):(i.key!==E.C0.ETX&&i.key!==E.C0.CR||(this.textarea.value=""),this._onKey.fire({key:i.key,domEvent:e}),this._showCursor(),this.coreService.triggerDataEvent(i.key,!0),!this.optionsService.rawOptions.screenReaderMode||e.altKey||e.ctrlKey?this.cancel(e,!0):void(this._keyDownHandled=!0))))}_isThirdLevelShift(e,t){const i=e.isMac&&!this.options.macOptionIsMeta&&t.altKey&&!t.ctrlKey&&!t.metaKey||e.isWindows&&t.altKey&&t.ctrlKey&&!t.metaKey||e.isWindows&&t.getModifierState("AltGraph");return"keypress"===t.type?i:i&&(!t.keyCode||t.keyCode>47)}_keyUp(e){this._keyDownSeen=!1,this._customKeyEventHandler&&!1===this._customKeyEventHandler(e)||(function(e){return 16===e.keyCode||17===e.keyCode||18===e.keyCode}(e)||this.focus(),this.updateCursorStyle(e),this._keyPressHandled=!1)}_keyPress(e){let t;if(this._keyPressHandled=!1,this._keyDownHandled)return!1;if(this._customKeyEventHandler&&!1===this._customKeyEventHandler(e))return!1;if(this.cancel(e),e.charCode)t=e.charCode;else if(null===e.which||void 0===e.which)t=e.keyCode;else{if(0===e.which||0===e.charCode)return!1;t=e.which}return!(!t||(e.altKey||e.ctrlKey||e.metaKey)&&!this._isThirdLevelShift(this.browser,e)||(t=String.fromCharCode(t),this._onKey.fire({key:t,domEvent:e}),this._showCursor(),this.coreService.triggerDataEvent(t,!0),this._keyPressHandled=!0,this._unprocessedDeadKey=!1,0))}_inputEvent(e){if(e.data&&"insertText"===e.inputType&&(!e.composed||!this._keyDownSeen)&&!this.optionsService.rawOptions.screenReaderMode){if(this._keyPressHandled)return!1;this._unprocessedDeadKey=!1;const t=e.data;return this.coreService.triggerDataEvent(t,!0),this.cancel(e),!0}return!1}resize(e,t){e!==this.cols||t!==this.rows?super.resize(e,t):this._charSizeService&&!this._charSizeService.hasValidSize&&this._charSizeService.measure()}_afterResize(e,t){this._charSizeService?.measure()}clear(){if(0!==this.buffer.ybase||0!==this.buffer.y){this.buffer.clearAllMarkers(),this.buffer.lines.set(0,this.buffer.lines.get(this.buffer.ybase+this.buffer.y)),this.buffer.lines.length=1,this.buffer.ydisp=0,this.buffer.ybase=0,this.buffer.y=0;for(let e=1;e<this.rows;e++)this.buffer.lines.push(this.buffer.getBlankLine(w.DEFAULT_ATTR_DATA));this._onScroll.fire({position:this.buffer.ydisp}),this.refresh(0,this.rows-1)}}reset(){this.options.rows=this.rows,this.options.cols=this.cols;const e=this._customKeyEventHandler;this._setup(),super.reset(),this._selectionService?.reset(),this._decorationService.reset(),this._customKeyEventHandler=e,this.refresh(0,this.rows-1)}clearTextureAtlas(){this._renderService?.clearTextureAtlas()}_reportFocus(){this.element?.classList.contains("focus")?this.coreService.triggerDataEvent(E.C0.ESC+"[I"):this.coreService.triggerDataEvent(E.C0.ESC+"[O")}_reportWindowsOptions(e){if(this._renderService)switch(e){case T.WindowsOptionsReportType.GET_WIN_SIZE_PIXELS:const e=this._renderService.dimensions.css.canvas.width.toFixed(0),t=this._renderService.dimensions.css.canvas.height.toFixed(0);this.coreService.triggerDataEvent(`${E.C0.ESC}[4;${t};${e}t`);break;case T.WindowsOptionsReportType.GET_CELL_SIZE_PIXELS:const i=this._renderService.dimensions.css.cell.width.toFixed(0),s=this._renderService.dimensions.css.cell.height.toFixed(0);this.coreService.triggerDataEvent(`${E.C0.ESC}[6;${s};${i}t`)}}cancel(e,t){if(this.options.cancelEvents||t)return e.preventDefault(),e.stopPropagation(),!1}}t.CoreBrowserTerminal=x},8906:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.Linkifier=void 0;const n=i(7150),o=i(6501),a=i(7098),l=i(802),h=i(7093);let c=class extends n.Disposable{get currentLink(){return this._currentLink}constructor(e,t,i,s,r){super(),this._element=e,this._mouseService=t,this._renderService=i,this._bufferService=s,this._linkProviderService=r,this._linkCacheDisposables=[],this._isMouseOut=!0,this._wasResized=!1,this._activeLine=-1,this._onShowLinkUnderline=this._register(new l.Emitter),this.onShowLinkUnderline=this._onShowLinkUnderline.event,this._onHideLinkUnderline=this._register(new l.Emitter),this.onHideLinkUnderline=this._onHideLinkUnderline.event,this._register((0,n.toDisposable)((()=>{(0,n.dispose)(this._linkCacheDisposables),this._linkCacheDisposables.length=0,this._lastMouseEvent=void 0,this._activeProviderReplies?.clear()}))),this._register(this._bufferService.onResize((()=>{this._clearCurrentLink(),this._wasResized=!0}))),this._register((0,h.addDisposableListener)(this._element,"mouseleave",(()=>{this._isMouseOut=!0,this._clearCurrentLink()}))),this._register((0,h.addDisposableListener)(this._element,"mousemove",this._handleMouseMove.bind(this))),this._register((0,h.addDisposableListener)(this._element,"mousedown",this._handleMouseDown.bind(this))),this._register((0,h.addDisposableListener)(this._element,"mouseup",this._handleMouseUp.bind(this)))}_handleMouseMove(e){this._lastMouseEvent=e;const t=this._positionFromMouseEvent(e,this._element,this._mouseService);if(!t)return;this._isMouseOut=!1;const i=e.composedPath();for(let e=0;e<i.length;e++){const t=i[e];if(t.classList.contains("xterm"))break;if(t.classList.contains("xterm-hover"))return}this._lastBufferCell&&t.x===this._lastBufferCell.x&&t.y===this._lastBufferCell.y||(this._handleHover(t),this._lastBufferCell=t)}_handleHover(e){if(this._activeLine!==e.y||this._wasResized)return this._clearCurrentLink(),this._askForLink(e,!1),void(this._wasResized=!1);this._currentLink&&this._linkAtPosition(this._currentLink.link,e)||(this._clearCurrentLink(),this._askForLink(e,!0))}_askForLink(e,t){this._activeProviderReplies&&t||(this._activeProviderReplies?.forEach((e=>{e?.forEach((e=>{e.link.dispose&&e.link.dispose()}))})),this._activeProviderReplies=new Map,this._activeLine=e.y);let i=!1;for(const[s,r]of this._linkProviderService.linkProviders.entries())if(t){const t=this._activeProviderReplies?.get(s);t&&(i=this._checkLinkProviderResult(s,e,i))}else r.provideLinks(e.y,(t=>{if(this._isMouseOut)return;const r=t?.map((e=>({link:e})));this._activeProviderReplies?.set(s,r),i=this._checkLinkProviderResult(s,e,i),this._activeProviderReplies?.size===this._linkProviderService.linkProviders.length&&this._removeIntersectingLinks(e.y,this._activeProviderReplies)}))}_removeIntersectingLinks(e,t){const i=new Set;for(let s=0;s<t.size;s++){const r=t.get(s);if(r)for(let t=0;t<r.length;t++){const s=r[t],n=s.link.range.start.y<e?0:s.link.range.start.x,o=s.link.range.end.y>e?this._bufferService.cols:s.link.range.end.x;for(let e=n;e<=o;e++){if(i.has(e)){r.splice(t--,1);break}i.add(e)}}}}_checkLinkProviderResult(e,t,i){if(!this._activeProviderReplies)return i;const s=this._activeProviderReplies.get(e);let r=!1;for(let t=0;t<e;t++)this._activeProviderReplies.has(t)&&!this._activeProviderReplies.get(t)||(r=!0);if(!r&&s){const e=s.find((e=>this._linkAtPosition(e.link,t)));e&&(i=!0,this._handleNewLink(e))}if(this._activeProviderReplies.size===this._linkProviderService.linkProviders.length&&!i)for(let e=0;e<this._activeProviderReplies.size;e++){const s=this._activeProviderReplies.get(e)?.find((e=>this._linkAtPosition(e.link,t)));if(s){i=!0,this._handleNewLink(s);break}}return i}_handleMouseDown(){this._mouseDownLink=this._currentLink}_handleMouseUp(e){if(!this._currentLink)return;const t=this._positionFromMouseEvent(e,this._element,this._mouseService);var i,s;t&&this._mouseDownLink&&(i=this._mouseDownLink.link,s=this._currentLink.link,i.text===s.text&&i.range.start.x===s.range.start.x&&i.range.start.y===s.range.start.y&&i.range.end.x===s.range.end.x&&i.range.end.y===s.range.end.y)&&this._linkAtPosition(this._currentLink.link,t)&&this._currentLink.link.activate(e,this._currentLink.link.text)}_clearCurrentLink(e,t){this._currentLink&&this._lastMouseEvent&&(!e||!t||this._currentLink.link.range.start.y>=e&&this._currentLink.link.range.end.y<=t)&&(this._linkLeave(this._element,this._currentLink.link,this._lastMouseEvent),this._currentLink=void 0,(0,n.dispose)(this._linkCacheDisposables),this._linkCacheDisposables.length=0)}_handleNewLink(e){if(!this._lastMouseEvent)return;const t=this._positionFromMouseEvent(this._lastMouseEvent,this._element,this._mouseService);t&&this._linkAtPosition(e.link,t)&&(this._currentLink=e,this._currentLink.state={decorations:{underline:void 0===e.link.decorations||e.link.decorations.underline,pointerCursor:void 0===e.link.decorations||e.link.decorations.pointerCursor},isHovered:!0},this._linkHover(this._element,e.link,this._lastMouseEvent),e.link.decorations={},Object.defineProperties(e.link.decorations,{pointerCursor:{get:()=>this._currentLink?.state?.decorations.pointerCursor,set:e=>{this._currentLink?.state&&this._currentLink.state.decorations.pointerCursor!==e&&(this._currentLink.state.decorations.pointerCursor=e,this._currentLink.state.isHovered&&this._element.classList.toggle("xterm-cursor-pointer",e))}},underline:{get:()=>this._currentLink?.state?.decorations.underline,set:t=>{this._currentLink?.state&&this._currentLink?.state?.decorations.underline!==t&&(this._currentLink.state.decorations.underline=t,this._currentLink.state.isHovered&&this._fireUnderlineEvent(e.link,t))}}}),this._linkCacheDisposables.push(this._renderService.onRenderedViewportChange((e=>{if(!this._currentLink)return;const t=0===e.start?0:e.start+1+this._bufferService.buffer.ydisp,i=this._bufferService.buffer.ydisp+1+e.end;if(this._currentLink.link.range.start.y>=t&&this._currentLink.link.range.end.y<=i&&(this._clearCurrentLink(t,i),this._lastMouseEvent)){const e=this._positionFromMouseEvent(this._lastMouseEvent,this._element,this._mouseService);e&&this._askForLink(e,!1)}}))))}_linkHover(e,t,i){this._currentLink?.state&&(this._currentLink.state.isHovered=!0,this._currentLink.state.decorations.underline&&this._fireUnderlineEvent(t,!0),this._currentLink.state.decorations.pointerCursor&&e.classList.add("xterm-cursor-pointer")),t.hover&&t.hover(i,t.text)}_fireUnderlineEvent(e,t){const i=e.range,s=this._bufferService.buffer.ydisp,r=this._createLinkUnderlineEvent(i.start.x-1,i.start.y-s-1,i.end.x,i.end.y-s-1,void 0);(t?this._onShowLinkUnderline:this._onHideLinkUnderline).fire(r)}_linkLeave(e,t,i){this._currentLink?.state&&(this._currentLink.state.isHovered=!1,this._currentLink.state.decorations.underline&&this._fireUnderlineEvent(t,!1),this._currentLink.state.decorations.pointerCursor&&e.classList.remove("xterm-cursor-pointer")),t.leave&&t.leave(i,t.text)}_linkAtPosition(e,t){const i=e.range.start.y*this._bufferService.cols+e.range.start.x,s=e.range.end.y*this._bufferService.cols+e.range.end.x,r=t.y*this._bufferService.cols+t.x;return i<=r&&r<=s}_positionFromMouseEvent(e,t,i){const s=i.getCoords(e,t,this._bufferService.cols,this._bufferService.rows);if(s)return{x:s[0],y:s[1]+this._bufferService.buffer.ydisp}}_createLinkUnderlineEvent(e,t,i,s,r){return{x1:e,y1:t,x2:i,y2:s,cols:this._bufferService.cols,fg:r}}};t.Linkifier=c,t.Linkifier=c=s([r(1,a.IMouseService),r(2,a.IRenderService),r(3,o.IBufferService),r(4,a.ILinkProviderService)],c)},7721:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.tooMuchOutput=t.promptLabel=void 0;let i="Terminal input";const s={get:()=>i,set:e=>i=e};t.promptLabel=s;let r="Too much output to announce, navigate to rows manually to read";const n={get:()=>r,set:e=>r=e};t.tooMuchOutput=n},3285:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.OscLinkProvider=void 0;const n=i(3055),o=i(6501);let a=class{constructor(e,t,i){this._bufferService=e,this._optionsService=t,this._oscLinkService=i}provideLinks(e,t){const i=this._bufferService.buffer.lines.get(e-1);if(!i)return void t(void 0);const s=[],r=this._optionsService.rawOptions.linkHandler,o=new n.CellData,a=i.getTrimmedLength();let h=-1,c=-1,d=!1;for(let t=0;t<a;t++)if(-1!==c||i.hasContent(t)){if(i.loadCell(t,o),o.hasExtendedAttrs()&&o.extended.urlId){if(-1===c){c=t,h=o.extended.urlId;continue}d=o.extended.urlId!==h}else-1!==c&&(d=!0);if(d||-1!==c&&t===a-1){const i=this._oscLinkService.getLinkData(h)?.uri;if(i){const n={start:{x:c+1,y:e},end:{x:t+(d||t!==a-1?0:1),y:e}};let o=!1;if(!r?.allowNonHttpProtocols)try{const e=new URL(i);["http:","https:"].includes(e.protocol)||(o=!0)}catch(e){o=!0}o||s.push({text:i,range:n,activate:(e,t)=>r?r.activate(e,t,n):l(0,t),hover:(e,t)=>r?.hover?.(e,t,n),leave:(e,t)=>r?.leave?.(e,t,n)})}d=!1,o.hasExtendedAttrs()&&o.extended.urlId?(c=t,h=o.extended.urlId):(c=-1,h=-1)}}t(s)}};function l(e,t){if(confirm(`Do you want to navigate to ${t}?\\n\\nWARNING: This link could potentially be dangerous`)){const e=window.open();if(e){try{e.opener=null}catch{}e.location.href=t}else console.warn("Opening link blocked as opener could not be cleared")}}t.OscLinkProvider=a,t.OscLinkProvider=a=s([r(0,o.IBufferService),r(1,o.IOptionsService),r(2,o.IOscLinkService)],a)},4852:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.RenderDebouncer=void 0,t.RenderDebouncer=class{constructor(e,t){this._renderCallback=e,this._coreBrowserService=t,this._refreshCallbacks=[]}dispose(){this._animationFrame&&(this._coreBrowserService.window.cancelAnimationFrame(this._animationFrame),this._animationFrame=void 0)}addRefreshCallback(e){return this._refreshCallbacks.push(e),this._animationFrame||(this._animationFrame=this._coreBrowserService.window.requestAnimationFrame((()=>this._innerRefresh()))),this._animationFrame}refresh(e,t,i){this._rowCount=i,e=void 0!==e?e:0,t=void 0!==t?t:this._rowCount-1,this._rowStart=void 0!==this._rowStart?Math.min(this._rowStart,e):e,this._rowEnd=void 0!==this._rowEnd?Math.max(this._rowEnd,t):t,this._animationFrame||(this._animationFrame=this._coreBrowserService.window.requestAnimationFrame((()=>this._innerRefresh())))}_innerRefresh(){if(this._animationFrame=void 0,void 0===this._rowStart||void 0===this._rowEnd||void 0===this._rowCount)return void this._runRefreshCallbacks();const e=Math.max(this._rowStart,0),t=Math.min(this._rowEnd,this._rowCount-1);this._rowStart=void 0,this._rowEnd=void 0,this._renderCallback(e,t),this._runRefreshCallbacks()}_runRefreshCallbacks(){for(const e of this._refreshCallbacks)e(0);this._refreshCallbacks=[]}}},4292:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.TimeBasedDebouncer=void 0,t.TimeBasedDebouncer=class{constructor(e,t=1e3){this._renderCallback=e,this._debounceThresholdMS=t,this._lastRefreshMs=0,this._additionalRefreshRequested=!1}dispose(){this._refreshTimeoutID&&clearTimeout(this._refreshTimeoutID)}refresh(e,t,i){this._rowCount=i,e=void 0!==e?e:0,t=void 0!==t?t:this._rowCount-1,this._rowStart=void 0!==this._rowStart?Math.min(this._rowStart,e):e,this._rowEnd=void 0!==this._rowEnd?Math.max(this._rowEnd,t):t;const s=performance.now();if(s-this._lastRefreshMs>=this._debounceThresholdMS)this._lastRefreshMs=s,this._innerRefresh();else if(!this._additionalRefreshRequested){const e=s-this._lastRefreshMs,t=this._debounceThresholdMS-e;this._additionalRefreshRequested=!0,this._refreshTimeoutID=window.setTimeout((()=>{this._lastRefreshMs=performance.now(),this._innerRefresh(),this._additionalRefreshRequested=!1,this._refreshTimeoutID=void 0}),t)}}_innerRefresh(){if(void 0===this._rowStart||void 0===this._rowEnd||void 0===this._rowCount)return;const e=Math.max(this._rowStart,0),t=Math.min(this._rowEnd,this._rowCount-1);this._rowStart=void 0,this._rowEnd=void 0,this._renderCallback(e,t)}}},9302:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DEFAULT_ANSI_COLORS=void 0;const s=i(4103);t.DEFAULT_ANSI_COLORS=Object.freeze((()=>{const e=[s.css.toColor("#2e3436"),s.css.toColor("#cc0000"),s.css.toColor("#4e9a06"),s.css.toColor("#c4a000"),s.css.toColor("#3465a4"),s.css.toColor("#75507b"),s.css.toColor("#06989a"),s.css.toColor("#d3d7cf"),s.css.toColor("#555753"),s.css.toColor("#ef2929"),s.css.toColor("#8ae234"),s.css.toColor("#fce94f"),s.css.toColor("#729fcf"),s.css.toColor("#ad7fa8"),s.css.toColor("#34e2e2"),s.css.toColor("#eeeeec")],t=[0,95,135,175,215,255];for(let i=0;i<216;i++){const r=t[i/36%6|0],n=t[i/6%6|0],o=t[i%6];e.push({css:s.channels.toCss(r,n,o),rgba:s.channels.toRgba(r,n,o)})}for(let t=0;t<24;t++){const i=8+10*t;e.push({css:s.channels.toCss(i,i,i),rgba:s.channels.toRgba(i,i,i)})}return e})())},4017:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.Viewport=void 0;const n=i(7098),o=i(7150),a=i(6501),l=i(7093),h=i(8234),c=i(802),d=i(9881);let u=class extends o.Disposable{constructor(e,t,i,s,r,n,a,u){super(),this._bufferService=i,this._optionsService=a,this._renderService=u,this._onRequestScrollLines=this._register(new c.Emitter),this.onRequestScrollLines=this._onRequestScrollLines.event,this._isSyncing=!1,this._isHandlingScroll=!1,this._suppressOnScrollHandler=!1;const _=this._register(new d.Scrollable({forceIntegerValues:!1,smoothScrollDuration:this._optionsService.rawOptions.smoothScrollDuration,scheduleAtNextAnimationFrame:e=>(0,l.scheduleAtNextAnimationFrame)(s.window,e)}));this._register(this._optionsService.onSpecificOptionChange("smoothScrollDuration",(()=>{_.setSmoothScrollDuration(this._optionsService.rawOptions.smoothScrollDuration)}))),this._scrollableElement=this._register(new h.SmoothScrollableElement(t,{vertical:1,horizontal:2,useShadows:!1,mouseWheelSmoothScroll:!0,...this._getChangeOptions()},_)),this._register(this._optionsService.onMultipleOptionChange(["scrollSensitivity","fastScrollSensitivity","overviewRuler"],(()=>this._scrollableElement.updateOptions(this._getChangeOptions())))),this._register(r.onProtocolChange((e=>{this._scrollableElement.updateOptions({handleMouseWheel:!(16&e)})}))),this._scrollableElement.setScrollDimensions({height:0,scrollHeight:0}),this._register(c.Event.runAndSubscribe(n.onChangeColors,(()=>{this._scrollableElement.getDomNode().style.backgroundColor=n.colors.background.css}))),e.appendChild(this._scrollableElement.getDomNode()),this._register((0,o.toDisposable)((()=>this._scrollableElement.getDomNode().remove()))),this._styleElement=s.mainDocument.createElement("style"),t.appendChild(this._styleElement),this._register((0,o.toDisposable)((()=>this._styleElement.remove()))),this._register(c.Event.runAndSubscribe(n.onChangeColors,(()=>{this._styleElement.textContent=[".xterm .xterm-scrollable-element > .scrollbar > .slider {",`  background: ${n.colors.scrollbarSliderBackground.css};`,"}",".xterm .xterm-scrollable-element > .scrollbar > .slider:hover {",`  background: ${n.colors.scrollbarSliderHoverBackground.css};`,"}",".xterm .xterm-scrollable-element > .scrollbar > .slider.active {",`  background: ${n.colors.scrollbarSliderActiveBackground.css};`,"}"].join("\\n")}))),this._register(this._bufferService.onResize((()=>this.queueSync()))),this._register(this._bufferService.buffers.onBufferActivate((()=>{this._latestYDisp=void 0,this.queueSync()}))),this._register(this._bufferService.onScroll((()=>this._sync()))),this._register(this._scrollableElement.onScroll((e=>this._handleScroll(e))))}scrollLines(e){const t=this._scrollableElement.getScrollPosition();this._scrollableElement.setScrollPosition({reuseAnimation:!0,scrollTop:t.scrollTop+e*this._renderService.dimensions.css.cell.height})}scrollToLine(e,t){t&&(this._latestYDisp=e),this._scrollableElement.setScrollPosition({reuseAnimation:!t,scrollTop:e*this._renderService.dimensions.css.cell.height})}_getChangeOptions(){return{mouseWheelScrollSensitivity:this._optionsService.rawOptions.scrollSensitivity,fastScrollSensitivity:this._optionsService.rawOptions.fastScrollSensitivity,verticalScrollbarSize:this._optionsService.rawOptions.overviewRuler?.width||14}}queueSync(e){void 0!==e&&(this._latestYDisp=e),void 0===this._queuedAnimationFrame&&(this._queuedAnimationFrame=this._renderService.addRefreshCallback((()=>{this._queuedAnimationFrame=void 0,this._sync(this._latestYDisp)})))}_sync(e=this._bufferService.buffer.ydisp){this._renderService&&!this._isSyncing&&(this._isSyncing=!0,this._suppressOnScrollHandler=!0,this._scrollableElement.setScrollDimensions({height:this._renderService.dimensions.css.canvas.height,scrollHeight:this._renderService.dimensions.css.cell.height*this._bufferService.buffer.lines.length}),this._suppressOnScrollHandler=!1,e!==this._latestYDisp&&this._scrollableElement.setScrollPosition({scrollTop:e*this._renderService.dimensions.css.cell.height}),this._isSyncing=!1)}_handleScroll(e){if(!this._renderService)return;if(this._isHandlingScroll||this._suppressOnScrollHandler)return;this._isHandlingScroll=!0;const t=Math.round(e.scrollTop/this._renderService.dimensions.css.cell.height),i=t-this._bufferService.buffer.ydisp;0!==i&&(this._latestYDisp=t,this._onRequestScrollLines.fire(i)),this._isHandlingScroll=!1}};t.Viewport=u,t.Viewport=u=s([r(2,a.IBufferService),r(3,n.ICoreBrowserService),r(4,a.ICoreMouseService),r(5,n.IThemeService),r(6,a.IOptionsService),r(7,n.IRenderService)],u)},4196:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.BufferDecorationRenderer=void 0;const n=i(7098),o=i(7150),a=i(6501);let l=class extends o.Disposable{constructor(e,t,i,s,r){super(),this._screenElement=e,this._bufferService=t,this._coreBrowserService=i,this._decorationService=s,this._renderService=r,this._decorationElements=new Map,this._altBufferIsActive=!1,this._dimensionsChanged=!1,this._container=document.createElement("div"),this._container.classList.add("xterm-decoration-container"),this._screenElement.appendChild(this._container),this._register(this._renderService.onRenderedViewportChange((()=>this._doRefreshDecorations()))),this._register(this._renderService.onDimensionsChange((()=>{this._dimensionsChanged=!0,this._queueRefresh()}))),this._register(this._coreBrowserService.onDprChange((()=>this._queueRefresh()))),this._register(this._bufferService.buffers.onBufferActivate((()=>{this._altBufferIsActive=this._bufferService.buffer===this._bufferService.buffers.alt}))),this._register(this._decorationService.onDecorationRegistered((()=>this._queueRefresh()))),this._register(this._decorationService.onDecorationRemoved((e=>this._removeDecoration(e)))),this._register((0,o.toDisposable)((()=>{this._container.remove(),this._decorationElements.clear()})))}_queueRefresh(){void 0===this._animationFrame&&(this._animationFrame=this._renderService.addRefreshCallback((()=>{this._doRefreshDecorations(),this._animationFrame=void 0})))}_doRefreshDecorations(){for(const e of this._decorationService.decorations)this._renderDecoration(e);this._dimensionsChanged=!1}_renderDecoration(e){this._refreshStyle(e),this._dimensionsChanged&&this._refreshXPosition(e)}_createElement(e){const t=this._coreBrowserService.mainDocument.createElement("div");t.classList.add("xterm-decoration"),t.classList.toggle("xterm-decoration-top-layer","top"===e?.options?.layer),t.style.width=`${Math.round((e.options.width||1)*this._renderService.dimensions.css.cell.width)}px`,t.style.height=(e.options.height||1)*this._renderService.dimensions.css.cell.height+"px",t.style.top=(e.marker.line-this._bufferService.buffers.active.ydisp)*this._renderService.dimensions.css.cell.height+"px",t.style.lineHeight=`${this._renderService.dimensions.css.cell.height}px`;const i=e.options.x??0;return i&&i>this._bufferService.cols&&(t.style.display="none"),this._refreshXPosition(e,t),t}_refreshStyle(e){const t=e.marker.line-this._bufferService.buffers.active.ydisp;if(t<0||t>=this._bufferService.rows)e.element&&(e.element.style.display="none",e.onRenderEmitter.fire(e.element));else{let i=this._decorationElements.get(e);i||(i=this._createElement(e),e.element=i,this._decorationElements.set(e,i),this._container.appendChild(i),e.onDispose((()=>{this._decorationElements.delete(e),i.remove()}))),i.style.display=this._altBufferIsActive?"none":"block",this._altBufferIsActive||(i.style.width=`${Math.round((e.options.width||1)*this._renderService.dimensions.css.cell.width)}px`,i.style.height=(e.options.height||1)*this._renderService.dimensions.css.cell.height+"px",i.style.top=t*this._renderService.dimensions.css.cell.height+"px",i.style.lineHeight=`${this._renderService.dimensions.css.cell.height}px`),e.onRenderEmitter.fire(i)}}_refreshXPosition(e,t=e.element){if(!t)return;const i=e.options.x??0;"right"===(e.options.anchor||"left")?t.style.right=i?i*this._renderService.dimensions.css.cell.width+"px":"":t.style.left=i?i*this._renderService.dimensions.css.cell.width+"px":""}_removeDecoration(e){this._decorationElements.get(e)?.remove(),this._decorationElements.delete(e),e.dispose()}};t.BufferDecorationRenderer=l,t.BufferDecorationRenderer=l=s([r(1,a.IBufferService),r(2,n.ICoreBrowserService),r(3,a.IDecorationService),r(4,n.IRenderService)],l)},957:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ColorZoneStore=void 0,t.ColorZoneStore=class{constructor(){this._zones=[],this._zonePool=[],this._zonePoolIndex=0,this._linePadding={full:0,left:0,center:0,right:0}}get zones(){return this._zonePool.length=Math.min(this._zonePool.length,this._zones.length),this._zones}clear(){this._zones.length=0,this._zonePoolIndex=0}addDecoration(e){if(e.options.overviewRulerOptions){for(const t of this._zones)if(t.color===e.options.overviewRulerOptions.color&&t.position===e.options.overviewRulerOptions.position){if(this._lineIntersectsZone(t,e.marker.line))return;if(this._lineAdjacentToZone(t,e.marker.line,e.options.overviewRulerOptions.position))return void this._addLineToZone(t,e.marker.line)}if(this._zonePoolIndex<this._zonePool.length)return this._zonePool[this._zonePoolIndex].color=e.options.overviewRulerOptions.color,this._zonePool[this._zonePoolIndex].position=e.options.overviewRulerOptions.position,this._zonePool[this._zonePoolIndex].startBufferLine=e.marker.line,this._zonePool[this._zonePoolIndex].endBufferLine=e.marker.line,void this._zones.push(this._zonePool[this._zonePoolIndex++]);this._zones.push({color:e.options.overviewRulerOptions.color,position:e.options.overviewRulerOptions.position,startBufferLine:e.marker.line,endBufferLine:e.marker.line}),this._zonePool.push(this._zones[this._zones.length-1]),this._zonePoolIndex++}}setPadding(e){this._linePadding=e}_lineIntersectsZone(e,t){return t>=e.startBufferLine&&t<=e.endBufferLine}_lineAdjacentToZone(e,t,i){return t>=e.startBufferLine-this._linePadding[i||"full"]&&t<=e.endBufferLine+this._linePadding[i||"full"]}_addLineToZone(e,t){e.startBufferLine=Math.min(e.startBufferLine,t),e.endBufferLine=Math.max(e.endBufferLine,t)}}},9925:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.OverviewRulerRenderer=void 0;const n=i(957),o=i(7098),a=i(7150),l=i(6501),h={full:0,left:0,center:0,right:0},c={full:0,left:0,center:0,right:0},d={full:0,left:0,center:0,right:0};let u=class extends a.Disposable{get _width(){return this._optionsService.options.overviewRuler?.width||0}constructor(e,t,i,s,r,o,l,h){super(),this._viewportElement=e,this._screenElement=t,this._bufferService=i,this._decorationService=s,this._renderService=r,this._optionsService=o,this._themeService=l,this._coreBrowserService=h,this._colorZoneStore=new n.ColorZoneStore,this._shouldUpdateDimensions=!0,this._shouldUpdateAnchor=!0,this._lastKnownBufferLength=0,this._canvas=this._coreBrowserService.mainDocument.createElement("canvas"),this._canvas.classList.add("xterm-decoration-overview-ruler"),this._refreshCanvasDimensions(),this._viewportElement.parentElement?.insertBefore(this._canvas,this._viewportElement),this._register((0,a.toDisposable)((()=>this._canvas?.remove())));const c=this._canvas.getContext("2d");if(!c)throw new Error("Ctx cannot be null");this._ctx=c,this._register(this._decorationService.onDecorationRegistered((()=>this._queueRefresh(void 0,!0)))),this._register(this._decorationService.onDecorationRemoved((()=>this._queueRefresh(void 0,!0)))),this._register(this._renderService.onRenderedViewportChange((()=>this._queueRefresh()))),this._register(this._bufferService.buffers.onBufferActivate((()=>{this._canvas.style.display=this._bufferService.buffer===this._bufferService.buffers.alt?"none":"block"}))),this._register(this._bufferService.onScroll((()=>{this._lastKnownBufferLength!==this._bufferService.buffers.normal.lines.length&&(this._refreshDrawHeightConstants(),this._refreshColorZonePadding())}))),this._register(this._renderService.onRender((()=>{this._containerHeight&&this._containerHeight===this._screenElement.clientHeight||(this._queueRefresh(!0),this._containerHeight=this._screenElement.clientHeight)}))),this._register(this._coreBrowserService.onDprChange((()=>this._queueRefresh(!0)))),this._register(this._optionsService.onSpecificOptionChange("overviewRuler",(()=>this._queueRefresh(!0)))),this._register(this._themeService.onChangeColors((()=>this._queueRefresh()))),this._queueRefresh(!0)}_refreshDrawConstants(){const e=Math.floor((this._canvas.width-1)/3),t=Math.ceil((this._canvas.width-1)/3);c.full=this._canvas.width,c.left=e,c.center=t,c.right=e,this._refreshDrawHeightConstants(),d.full=1,d.left=1,d.center=1+c.left,d.right=1+c.left+c.center}_refreshDrawHeightConstants(){h.full=Math.round(2*this._coreBrowserService.dpr);const e=this._canvas.height/this._bufferService.buffer.lines.length,t=Math.round(Math.max(Math.min(e,12),6)*this._coreBrowserService.dpr);h.left=t,h.center=t,h.right=t}_refreshColorZonePadding(){this._colorZoneStore.setPadding({full:Math.floor(this._bufferService.buffers.active.lines.length/(this._canvas.height-1)*h.full),left:Math.floor(this._bufferService.buffers.active.lines.length/(this._canvas.height-1)*h.left),center:Math.floor(this._bufferService.buffers.active.lines.length/(this._canvas.height-1)*h.center),right:Math.floor(this._bufferService.buffers.active.lines.length/(this._canvas.height-1)*h.right)}),this._lastKnownBufferLength=this._bufferService.buffers.normal.lines.length}_refreshCanvasDimensions(){this._canvas.style.width=`${this._width}px`,this._canvas.width=Math.round(this._width*this._coreBrowserService.dpr),this._canvas.style.height=`${this._screenElement.clientHeight}px`,this._canvas.height=Math.round(this._screenElement.clientHeight*this._coreBrowserService.dpr),this._refreshDrawConstants(),this._refreshColorZonePadding()}_refreshDecorations(){this._shouldUpdateDimensions&&this._refreshCanvasDimensions(),this._ctx.clearRect(0,0,this._canvas.width,this._canvas.height),this._colorZoneStore.clear();for(const e of this._decorationService.decorations)this._colorZoneStore.addDecoration(e);this._ctx.lineWidth=1,this._renderRulerOutline();const e=this._colorZoneStore.zones;for(const t of e)"full"!==t.position&&this._renderColorZone(t);for(const t of e)"full"===t.position&&this._renderColorZone(t);this._shouldUpdateDimensions=!1,this._shouldUpdateAnchor=!1}_renderRulerOutline(){this._ctx.fillStyle=this._themeService.colors.overviewRulerBorder.css,this._ctx.fillRect(0,0,1,this._canvas.height),this._optionsService.rawOptions.overviewRuler.showTopBorder&&this._ctx.fillRect(1,0,this._canvas.width-1,1),this._optionsService.rawOptions.overviewRuler.showBottomBorder&&this._ctx.fillRect(1,this._canvas.height-1,this._canvas.width-1,this._canvas.height)}_renderColorZone(e){this._ctx.fillStyle=e.color,this._ctx.fillRect(d[e.position||"full"],Math.round((this._canvas.height-1)*(e.startBufferLine/this._bufferService.buffers.active.lines.length)-h[e.position||"full"]/2),c[e.position||"full"],Math.round((this._canvas.height-1)*((e.endBufferLine-e.startBufferLine)/this._bufferService.buffers.active.lines.length)+h[e.position||"full"]))}_queueRefresh(e,t){this._shouldUpdateDimensions=e||this._shouldUpdateDimensions,this._shouldUpdateAnchor=t||this._shouldUpdateAnchor,void 0===this._animationFrame&&(this._animationFrame=this._coreBrowserService.window.requestAnimationFrame((()=>{this._refreshDecorations(),this._animationFrame=void 0})))}};t.OverviewRulerRenderer=u,t.OverviewRulerRenderer=u=s([r(2,l.IBufferService),r(3,l.IDecorationService),r(4,o.IRenderService),r(5,l.IOptionsService),r(6,o.IThemeService),r(7,o.ICoreBrowserService)],u)},3618:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CompositionHelper=void 0;const n=i(7098),o=i(6501),a=i(3534);let l=class{get isComposing(){return this._isComposing}constructor(e,t,i,s,r,n){this._textarea=e,this._compositionView=t,this._bufferService=i,this._optionsService=s,this._coreService=r,this._renderService=n,this._isComposing=!1,this._isSendingComposition=!1,this._compositionPosition={start:0,end:0},this._dataAlreadySent=""}compositionstart(){this._isComposing=!0,this._compositionPosition.start=this._textarea.value.length,this._compositionView.textContent="",this._dataAlreadySent="",this._compositionView.classList.add("active")}compositionupdate(e){this._compositionView.textContent=e.data,this.updateCompositionElements(),setTimeout((()=>{this._compositionPosition.end=this._textarea.value.length}),0)}compositionend(){this._finalizeComposition(!0)}keydown(e){if(this._isComposing||this._isSendingComposition){if(20===e.keyCode||229===e.keyCode)return!1;if(16===e.keyCode||17===e.keyCode||18===e.keyCode)return!1;this._finalizeComposition(!1)}return 229!==e.keyCode||(this._handleAnyTextareaChanges(),!1)}_finalizeComposition(e){if(this._compositionView.classList.remove("active"),this._isComposing=!1,e){const e={start:this._compositionPosition.start,end:this._compositionPosition.end};this._isSendingComposition=!0,setTimeout((()=>{if(this._isSendingComposition){let t;this._isSendingComposition=!1,e.start+=this._dataAlreadySent.length,t=this._isComposing?this._textarea.value.substring(e.start,this._compositionPosition.start):this._textarea.value.substring(e.start),t.length>0&&this._coreService.triggerDataEvent(t,!0)}}),0)}else{this._isSendingComposition=!1;const e=this._textarea.value.substring(this._compositionPosition.start,this._compositionPosition.end);this._coreService.triggerDataEvent(e,!0)}}_handleAnyTextareaChanges(){const e=this._textarea.value;setTimeout((()=>{if(!this._isComposing){const t=this._textarea.value,i=t.replace(e,"");this._dataAlreadySent=i,t.length>e.length?this._coreService.triggerDataEvent(i,!0):t.length<e.length?this._coreService.triggerDataEvent(`${a.C0.DEL}`,!0):t.length===e.length&&t!==e&&this._coreService.triggerDataEvent(t,!0)}}),0)}updateCompositionElements(e){if(this._isComposing){if(this._bufferService.buffer.isCursorInViewport){const e=Math.min(this._bufferService.buffer.x,this._bufferService.cols-1),t=this._renderService.dimensions.css.cell.height,i=this._bufferService.buffer.y*this._renderService.dimensions.css.cell.height,s=e*this._renderService.dimensions.css.cell.width;this._compositionView.style.left=s+"px",this._compositionView.style.top=i+"px",this._compositionView.style.height=t+"px",this._compositionView.style.lineHeight=t+"px",this._compositionView.style.fontFamily=this._optionsService.rawOptions.fontFamily,this._compositionView.style.fontSize=this._optionsService.rawOptions.fontSize+"px";const r=this._compositionView.getBoundingClientRect();this._textarea.style.left=s+"px",this._textarea.style.top=i+"px",this._textarea.style.width=Math.max(r.width,1)+"px",this._textarea.style.height=Math.max(r.height,1)+"px",this._textarea.style.lineHeight=r.height+"px"}e||setTimeout((()=>this.updateCompositionElements(!0)),0)}}};t.CompositionHelper=l,t.CompositionHelper=l=s([r(2,o.IBufferService),r(3,o.IOptionsService),r(4,o.ICoreService),r(5,n.IRenderService)],l)},5251:(e,t)=>{function i(e,t,i){const s=i.getBoundingClientRect(),r=e.getComputedStyle(i),n=parseInt(r.getPropertyValue("padding-left")),o=parseInt(r.getPropertyValue("padding-top"));return[t.clientX-s.left-n,t.clientY-s.top-o]}Object.defineProperty(t,"__esModule",{value:!0}),t.getCoordsRelativeToElement=i,t.getCoords=function(e,t,s,r,n,o,a,l,h){if(!o)return;const c=i(e,t,s);return c?(c[0]=Math.ceil((c[0]+(h?a/2:0))/a),c[1]=Math.ceil(c[1]/l),c[0]=Math.min(Math.max(c[0],1),r+(h?1:0)),c[1]=Math.min(Math.max(c[1],1),n),c):void 0}},9686:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.moveToCellSequence=function(e,t,i,s){const o=i.buffer.x,c=i.buffer.y;if(!i.buffer.hasScrollback)return function(e,t,i,s,o,c){return 0===r(t,s,o,c).length?"":h(a(e,t,e,t-n(t,o),!1,o).length,l("D",c))}(o,c,0,t,i,s)+r(c,t,i,s)+function(e,t,i,s,o,c){let d;d=r(t,s,o,c).length>0?s-n(s,o):t;const u=s,_=function(e,t,i,s,o,a){let l;return l=r(i,s,o,a).length>0?s-n(s,o):t,e<i&&l<=s||e>=i&&l<s?"C":"D"}(e,t,i,s,o,c);return h(a(e,d,i,u,"C"===_,o).length,l(_,c))}(o,c,e,t,i,s);let d;if(c===t)return d=o>e?"D":"C",h(Math.abs(o-e),l(d,s));d=c>t?"D":"C";const u=Math.abs(c-t);return h(function(e,t){return t.cols-e}(c>t?e:o,i)+(u-1)*i.cols+1+((c>t?o:e)-1),l(d,s))};const s=i(3534);function r(e,t,i,s){const r=e-n(e,i),a=t-n(t,i),c=Math.abs(r-a)-function(e,t,i){let s=0;const r=e-n(e,i),a=t-n(t,i);for(let n=0;n<Math.abs(r-a);n++){const a="A"===o(e,t)?-1:1,l=i.buffer.lines.get(r+a*n);l?.isWrapped&&s++}return s}(e,t,i);return h(c,l(o(e,t),s))}function n(e,t){let i=0,s=t.buffer.lines.get(e),r=s?.isWrapped;for(;r&&e>=0&&e<t.rows;)i++,s=t.buffer.lines.get(--e),r=s?.isWrapped;return i}function o(e,t){return e>t?"A":"B"}function a(e,t,i,s,r,n){let o=e,a=t,l="";for(;(o!==i||a!==s)&&a>=0&&a<n.buffer.lines.length;)o+=r?1:-1,r&&o>n.cols-1?(l+=n.buffer.translateBufferLineToString(a,!1,e,o),o=0,e=0,a++):!r&&o<0&&(l+=n.buffer.translateBufferLineToString(a,!1,0,e+1),o=n.cols-1,e=o,a--);return l+n.buffer.translateBufferLineToString(a,!1,e,o)}function l(e,t){const i=t?"O":"[";return s.C0.ESC+i+e}function h(e,t){e=Math.floor(e);let i="";for(let s=0;s<e;s++)i+=t;return i}},3955:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.DomRenderer=void 0;const n=i(1433),o=i(2744),a=i(9176),l=i(6181),h=i(2274),c=i(7098),d=i(4103),u=i(7150),_=i(6501),f=i(802),p="xterm-dom-renderer-owner-",g="xterm-rows",m="xterm-fg-",v="xterm-bg-",S="xterm-focus",b="xterm-selection";let C=1,y=class extends u.Disposable{constructor(e,t,i,s,r,a,c,d,_,m,v,S,y,w){super(),this._terminal=e,this._document=t,this._element=i,this._screenElement=s,this._viewportElement=r,this._helperContainer=a,this._linkifier2=c,this._charSizeService=_,this._optionsService=m,this._bufferService=v,this._coreService=S,this._coreBrowserService=y,this._themeService=w,this._terminalClass=C++,this._rowElements=[],this._selectionRenderModel=(0,h.createSelectionRenderModel)(),this.onRequestRedraw=this._register(new f.Emitter).event,this._rowContainer=this._document.createElement("div"),this._rowContainer.classList.add(g),this._rowContainer.style.lineHeight="normal",this._rowContainer.setAttribute("aria-hidden","true"),this._refreshRowElements(this._bufferService.cols,this._bufferService.rows),this._selectionContainer=this._document.createElement("div"),this._selectionContainer.classList.add(b),this._selectionContainer.setAttribute("aria-hidden","true"),this.dimensions=(0,l.createRenderDimensions)(),this._updateDimensions(),this._register(this._optionsService.onOptionChange((()=>this._handleOptionsChanged()))),this._register(this._themeService.onChangeColors((e=>this._injectCss(e)))),this._injectCss(this._themeService.colors),this._rowFactory=d.createInstance(n.DomRendererRowFactory,document),this._element.classList.add(p+this._terminalClass),this._screenElement.appendChild(this._rowContainer),this._screenElement.appendChild(this._selectionContainer),this._register(this._linkifier2.onShowLinkUnderline((e=>this._handleLinkHover(e)))),this._register(this._linkifier2.onHideLinkUnderline((e=>this._handleLinkLeave(e)))),this._register((0,u.toDisposable)((()=>{this._element.classList.remove(p+this._terminalClass),this._rowContainer.remove(),this._selectionContainer.remove(),this._widthCache.dispose(),this._themeStyleElement.remove(),this._dimensionsStyleElement.remove()}))),this._widthCache=new o.WidthCache(this._document,this._helperContainer),this._widthCache.setFont(this._optionsService.rawOptions.fontFamily,this._optionsService.rawOptions.fontSize,this._optionsService.rawOptions.fontWeight,this._optionsService.rawOptions.fontWeightBold),this._setDefaultSpacing()}_updateDimensions(){const e=this._coreBrowserService.dpr;this.dimensions.device.char.width=this._charSizeService.width*e,this.dimensions.device.char.height=Math.ceil(this._charSizeService.height*e),this.dimensions.device.cell.width=this.dimensions.device.char.width+Math.round(this._optionsService.rawOptions.letterSpacing),this.dimensions.device.cell.height=Math.floor(this.dimensions.device.char.height*this._optionsService.rawOptions.lineHeight),this.dimensions.device.char.left=0,this.dimensions.device.char.top=0,this.dimensions.device.canvas.width=this.dimensions.device.cell.width*this._bufferService.cols,this.dimensions.device.canvas.height=this.dimensions.device.cell.height*this._bufferService.rows,this.dimensions.css.canvas.width=Math.round(this.dimensions.device.canvas.width/e),this.dimensions.css.canvas.height=Math.round(this.dimensions.device.canvas.height/e),this.dimensions.css.cell.width=this.dimensions.css.canvas.width/this._bufferService.cols,this.dimensions.css.cell.height=this.dimensions.css.canvas.height/this._bufferService.rows;for(const e of this._rowElements)e.style.width=`${this.dimensions.css.canvas.width}px`,e.style.height=`${this.dimensions.css.cell.height}px`,e.style.lineHeight=`${this.dimensions.css.cell.height}px`,e.style.overflow="hidden";this._dimensionsStyleElement||(this._dimensionsStyleElement=this._document.createElement("style"),this._screenElement.appendChild(this._dimensionsStyleElement));const t=`${this._terminalSelector} .${g} span { display: inline-block; height: 100%; vertical-align: top;}`;this._dimensionsStyleElement.textContent=t,this._selectionContainer.style.height=this._viewportElement.style.height,this._screenElement.style.width=`${this.dimensions.css.canvas.width}px`,this._screenElement.style.height=`${this.dimensions.css.canvas.height}px`}_injectCss(e){this._themeStyleElement||(this._themeStyleElement=this._document.createElement("style"),this._screenElement.appendChild(this._themeStyleElement));let t=`${this._terminalSelector} .${g} { pointer-events: none; color: ${e.foreground.css}; font-family: ${this._optionsService.rawOptions.fontFamily}; font-size: ${this._optionsService.rawOptions.fontSize}px; font-kerning: none; white-space: pre}`;t+=`${this._terminalSelector} .${g} .xterm-dim { color: ${d.color.multiplyOpacity(e.foreground,.5).css};}`,t+=`${this._terminalSelector} span:not(.xterm-bold) { font-weight: ${this._optionsService.rawOptions.fontWeight};}${this._terminalSelector} span.xterm-bold { font-weight: ${this._optionsService.rawOptions.fontWeightBold};}${this._terminalSelector} span.xterm-italic { font-style: italic;}`;const i=`blink_underline_${this._terminalClass}`,s=`blink_bar_${this._terminalClass}`,r=`blink_block_${this._terminalClass}`;t+=`@keyframes ${i} { 50% {  border-bottom-style: hidden; }}`,t+=`@keyframes ${s} { 50% {  box-shadow: none; }}`,t+=`@keyframes ${r} { 0% {  background-color: ${e.cursor.css};  color: ${e.cursorAccent.css}; } 50% {  background-color: inherit;  color: ${e.cursor.css}; }}`,t+=`${this._terminalSelector} .${g}.${S} .xterm-cursor.xterm-cursor-blink.xterm-cursor-underline { animation: ${i} 1s step-end infinite;}${this._terminalSelector} .${g}.${S} .xterm-cursor.xterm-cursor-blink.xterm-cursor-bar { animation: ${s} 1s step-end infinite;}${this._terminalSelector} .${g}.${S} .xterm-cursor.xterm-cursor-blink.xterm-cursor-block { animation: ${r} 1s step-end infinite;}${this._terminalSelector} .${g} .xterm-cursor.xterm-cursor-block { background-color: ${e.cursor.css}; color: ${e.cursorAccent.css};}${this._terminalSelector} .${g} .xterm-cursor.xterm-cursor-block:not(.xterm-cursor-blink) { background-color: ${e.cursor.css} !important; color: ${e.cursorAccent.css} !important;}${this._terminalSelector} .${g} .xterm-cursor.xterm-cursor-outline { outline: 1px solid ${e.cursor.css}; outline-offset: -1px;}${this._terminalSelector} .${g} .xterm-cursor.xterm-cursor-bar { box-shadow: ${this._optionsService.rawOptions.cursorWidth}px 0 0 ${e.cursor.css} inset;}${this._terminalSelector} .${g} .xterm-cursor.xterm-cursor-underline { border-bottom: 1px ${e.cursor.css}; border-bottom-style: solid; height: calc(100% - 1px);}`,t+=`${this._terminalSelector} .${b} { position: absolute; top: 0; left: 0; z-index: 1; pointer-events: none;}${this._terminalSelector}.focus .${b} div { position: absolute; background-color: ${e.selectionBackgroundOpaque.css};}${this._terminalSelector} .${b} div { position: absolute; background-color: ${e.selectionInactiveBackgroundOpaque.css};}`;for(const[i,s]of e.ansi.entries())t+=`${this._terminalSelector} .${m}${i} { color: ${s.css}; }${this._terminalSelector} .${m}${i}.xterm-dim { color: ${d.color.multiplyOpacity(s,.5).css}; }${this._terminalSelector} .${v}${i} { background-color: ${s.css}; }`;t+=`${this._terminalSelector} .${m}${a.INVERTED_DEFAULT_COLOR} { color: ${d.color.opaque(e.background).css}; }${this._terminalSelector} .${m}${a.INVERTED_DEFAULT_COLOR}.xterm-dim { color: ${d.color.multiplyOpacity(d.color.opaque(e.background),.5).css}; }${this._terminalSelector} .${v}${a.INVERTED_DEFAULT_COLOR} { background-color: ${e.foreground.css}; }`,this._themeStyleElement.textContent=t}_setDefaultSpacing(){const e=this.dimensions.css.cell.width-this._widthCache.get("W",!1,!1);this._rowContainer.style.letterSpacing=`${e}px`,this._rowFactory.defaultSpacing=e}handleDevicePixelRatioChange(){this._updateDimensions(),this._widthCache.clear(),this._setDefaultSpacing()}_refreshRowElements(e,t){for(let e=this._rowElements.length;e<=t;e++){const e=this._document.createElement("div");this._rowContainer.appendChild(e),this._rowElements.push(e)}for(;this._rowElements.length>t;)this._rowContainer.removeChild(this._rowElements.pop())}handleResize(e,t){this._refreshRowElements(e,t),this._updateDimensions(),this.handleSelectionChanged(this._selectionRenderModel.selectionStart,this._selectionRenderModel.selectionEnd,this._selectionRenderModel.columnSelectMode)}handleCharSizeChanged(){this._updateDimensions(),this._widthCache.clear(),this._setDefaultSpacing()}handleBlur(){this._rowContainer.classList.remove(S),this.renderRows(0,this._bufferService.rows-1)}handleFocus(){this._rowContainer.classList.add(S),this.renderRows(this._bufferService.buffer.y,this._bufferService.buffer.y)}handleSelectionChanged(e,t,i){if(this._selectionContainer.replaceChildren(),this._rowFactory.handleSelectionChanged(e,t,i),this.renderRows(0,this._bufferService.rows-1),!e||!t)return;if(this._selectionRenderModel.update(this._terminal,e,t,i),!this._selectionRenderModel.hasSelection)return;const s=this._selectionRenderModel.viewportStartRow,r=this._selectionRenderModel.viewportEndRow,n=this._selectionRenderModel.viewportCappedStartRow,o=this._selectionRenderModel.viewportCappedEndRow,a=this._document.createDocumentFragment();if(i){const i=e[0]>t[0];a.appendChild(this._createSelectionElement(n,i?t[0]:e[0],i?e[0]:t[0],o-n+1))}else{const i=s===n?e[0]:0,l=n===r?t[0]:this._bufferService.cols;a.appendChild(this._createSelectionElement(n,i,l));const h=o-n-1;if(a.appendChild(this._createSelectionElement(n+1,0,this._bufferService.cols,h)),n!==o){const e=r===o?t[0]:this._bufferService.cols;a.appendChild(this._createSelectionElement(o,0,e))}}this._selectionContainer.appendChild(a)}_createSelectionElement(e,t,i,s=1){const r=this._document.createElement("div"),n=t*this.dimensions.css.cell.width;let o=this.dimensions.css.cell.width*(i-t);return n+o>this.dimensions.css.canvas.width&&(o=this.dimensions.css.canvas.width-n),r.style.height=s*this.dimensions.css.cell.height+"px",r.style.top=e*this.dimensions.css.cell.height+"px",r.style.left=`${n}px`,r.style.width=`${o}px`,r}handleCursorMove(){}_handleOptionsChanged(){this._updateDimensions(),this._injectCss(this._themeService.colors),this._widthCache.setFont(this._optionsService.rawOptions.fontFamily,this._optionsService.rawOptions.fontSize,this._optionsService.rawOptions.fontWeight,this._optionsService.rawOptions.fontWeightBold),this._setDefaultSpacing()}clear(){for(const e of this._rowElements)e.replaceChildren()}renderRows(e,t){const i=this._bufferService.buffer,s=i.ybase+i.y,r=Math.min(i.x,this._bufferService.cols-1),n=this._coreService.decPrivateModes.cursorBlink??this._optionsService.rawOptions.cursorBlink,o=this._coreService.decPrivateModes.cursorStyle??this._optionsService.rawOptions.cursorStyle,a=this._optionsService.rawOptions.cursorInactiveStyle;for(let l=e;l<=t;l++){const e=l+i.ydisp,t=this._rowElements[l],h=i.lines.get(e);if(!t||!h)break;t.replaceChildren(...this._rowFactory.createRow(h,e,e===s,o,a,r,n,this.dimensions.css.cell.width,this._widthCache,-1,-1))}}get _terminalSelector(){return`.${p}${this._terminalClass}`}_handleLinkHover(e){this._setCellUnderline(e.x1,e.x2,e.y1,e.y2,e.cols,!0)}_handleLinkLeave(e){this._setCellUnderline(e.x1,e.x2,e.y1,e.y2,e.cols,!1)}_setCellUnderline(e,t,i,s,r,n){i<0&&(e=0),s<0&&(t=0);const o=this._bufferService.rows-1;i=Math.max(Math.min(i,o),0),s=Math.max(Math.min(s,o),0),r=Math.min(r,this._bufferService.cols);const a=this._bufferService.buffer,l=a.ybase+a.y,h=Math.min(a.x,r-1),c=this._optionsService.rawOptions.cursorBlink,d=this._optionsService.rawOptions.cursorStyle,u=this._optionsService.rawOptions.cursorInactiveStyle;for(let o=i;o<=s;++o){const _=o+a.ydisp,f=this._rowElements[o],p=a.lines.get(_);if(!f||!p)break;f.replaceChildren(...this._rowFactory.createRow(p,_,_===l,d,u,h,c,this.dimensions.css.cell.width,this._widthCache,n?o===i?e:0:-1,n?(o===s?t:r)-1:-1))}}};t.DomRenderer=y,t.DomRenderer=y=s([r(7,_.IInstantiationService),r(8,c.ICharSizeService),r(9,_.IOptionsService),r(10,_.IBufferService),r(11,_.ICoreService),r(12,c.ICoreBrowserService),r(13,c.IThemeService)],y)},1433:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.DomRendererRowFactory=void 0;const n=i(9176),o=i(8938),a=i(3055),l=i(6501),h=i(4103),c=i(7098),d=i(945),u=i(6181),_=i(5451);let f=class{constructor(e,t,i,s,r,n,o){this._document=e,this._characterJoinerService=t,this._optionsService=i,this._coreBrowserService=s,this._coreService=r,this._decorationService=n,this._themeService=o,this._workCell=new a.CellData,this._columnSelectMode=!1,this.defaultSpacing=0}handleSelectionChanged(e,t,i){this._selectionStart=e,this._selectionEnd=t,this._columnSelectMode=i}createRow(e,t,i,s,r,a,l,c,u,f,g){const m=[],v=this._characterJoinerService.getJoinedCharacters(t),S=this._themeService.colors;let b,C=e.getNoBgTrimmedLength();i&&C<a+1&&(C=a+1);let y=0,w="",E=0,D=0,L=0,R=0,A=!1,T=0,k=!1,M=0,O=0;const I=[],P=-1!==f&&-1!==g;for(let x=0;x<C;x++){e.loadCell(x,this._workCell);let C=this._workCell.getWidth();if(0===C)continue;let B=!1,N=x>=O,U=x,F=this._workCell;if(v.length>0&&x===v[0][0]&&N){const s=v.shift(),r=this._isCellInSelection(s[0],t);for(E=s[0]+1;E<s[1];E++)N&&=r===this._isCellInSelection(E,t);N&&=!i||a<s[0]||a>=s[1],N?(B=!0,F=new d.JoinedCellData(this._workCell,e.translateToString(!0,s[0],s[1]),s[1]-s[0]),U=s[1]-1,C=F.getWidth()):O=s[1]}const W=this._isCellInSelection(x,t),H=i&&x===a,K=P&&x>=f&&x<=g;let z=!1;this._decorationService.forEachDecorationAtCell(x,t,void 0,(e=>{z=!0}));let j=F.getChars()||o.WHITESPACE_CELL_CHAR;if(" "===j&&(F.isUnderline()||F.isOverline())&&(j="\xA0"),M=C*c-u.get(j,F.isBold(),F.isItalic()),b){if(y&&(W&&k||!W&&!k&&F.bg===D)&&(W&&k&&S.selectionForeground||F.fg===L)&&F.extended.ext===R&&K===A&&M===T&&!H&&!B&&!z&&N){F.isInvisible()?w+=o.WHITESPACE_CELL_CHAR:w+=j,y++;continue}y&&(b.textContent=w),b=this._document.createElement("span"),y=0,w=""}else b=this._document.createElement("span");if(D=F.bg,L=F.fg,R=F.extended.ext,A=K,T=M,k=W,B&&a>=x&&a<=U&&(a=x),!this._coreService.isCursorHidden&&H&&this._coreService.isCursorInitialized)if(I.push("xterm-cursor"),this._coreBrowserService.isFocused)l&&I.push("xterm-cursor-blink"),I.push("bar"===s?"xterm-cursor-bar":"underline"===s?"xterm-cursor-underline":"xterm-cursor-block");else if(r)switch(r){case"outline":I.push("xterm-cursor-outline");break;case"block":I.push("xterm-cursor-block");break;case"bar":I.push("xterm-cursor-bar");break;case"underline":I.push("xterm-cursor-underline")}if(F.isBold()&&I.push("xterm-bold"),F.isItalic()&&I.push("xterm-italic"),F.isDim()&&I.push("xterm-dim"),w=F.isInvisible()?o.WHITESPACE_CELL_CHAR:F.getChars()||o.WHITESPACE_CELL_CHAR,F.isUnderline()&&(I.push(`xterm-underline-${F.extended.underlineStyle}`)," "===w&&(w="\xA0"),!F.isUnderlineColorDefault()))if(F.isUnderlineColorRGB())b.style.textDecorationColor=`rgb(${_.AttributeData.toColorRGB(F.getUnderlineColor()).join(",")})`;else{let e=F.getUnderlineColor();this._optionsService.rawOptions.drawBoldTextInBrightColors&&F.isBold()&&e<8&&(e+=8),b.style.textDecorationColor=S.ansi[e].css}F.isOverline()&&(I.push("xterm-overline")," "===w&&(w="\xA0")),F.isStrikethrough()&&I.push("xterm-strikethrough"),K&&(b.style.textDecoration="underline");let $=F.getFgColor(),V=F.getFgColorMode(),G=F.getBgColor(),q=F.getBgColorMode();const X=!!F.isInverse();if(X){const e=$;$=G,G=e;const t=V;V=q,q=t}let Y,Z,J,Q=!1;switch(this._decorationService.forEachDecorationAtCell(x,t,void 0,(e=>{"top"!==e.options.layer&&Q||(e.backgroundColorRGB&&(q=50331648,G=e.backgroundColorRGB.rgba>>8&16777215,Y=e.backgroundColorRGB),e.foregroundColorRGB&&(V=50331648,$=e.foregroundColorRGB.rgba>>8&16777215,Z=e.foregroundColorRGB),Q="top"===e.options.layer)})),!Q&&W&&(Y=this._coreBrowserService.isFocused?S.selectionBackgroundOpaque:S.selectionInactiveBackgroundOpaque,G=Y.rgba>>8&16777215,q=50331648,Q=!0,S.selectionForeground&&(V=50331648,$=S.selectionForeground.rgba>>8&16777215,Z=S.selectionForeground)),Q&&I.push("xterm-decoration-top"),q){case 16777216:case 33554432:J=S.ansi[G],I.push(`xterm-bg-${G}`);break;case 50331648:J=h.channels.toColor(G>>16,G>>8&255,255&G),this._addStyle(b,`background-color:#${p((G>>>0).toString(16),"0",6)}`);break;default:X?(J=S.foreground,I.push(`xterm-bg-${n.INVERTED_DEFAULT_COLOR}`)):J=S.background}switch(Y||F.isDim()&&(Y=h.color.multiplyOpacity(J,.5)),V){case 16777216:case 33554432:F.isBold()&&$<8&&this._optionsService.rawOptions.drawBoldTextInBrightColors&&($+=8),this._applyMinimumContrast(b,J,S.ansi[$],F,Y,void 0)||I.push(`xterm-fg-${$}`);break;case 50331648:const e=h.channels.toColor($>>16&255,$>>8&255,255&$);this._applyMinimumContrast(b,J,e,F,Y,Z)||this._addStyle(b,`color:#${p($.toString(16),"0",6)}`);break;default:this._applyMinimumContrast(b,J,S.foreground,F,Y,Z)||X&&I.push(`xterm-fg-${n.INVERTED_DEFAULT_COLOR}`)}I.length&&(b.className=I.join(" "),I.length=0),H||B||z||!N?b.textContent=w:y++,M!==this.defaultSpacing&&(b.style.letterSpacing=`${M}px`),m.push(b),x=U}return b&&y&&(b.textContent=w),m}_applyMinimumContrast(e,t,i,s,r,n){if(1===this._optionsService.rawOptions.minimumContrastRatio||(0,u.treatGlyphAsBackgroundColor)(s.getCode()))return!1;const o=this._getContrastCache(s);let a;if(r||n||(a=o.getColor(t.rgba,i.rgba)),void 0===a){const e=this._optionsService.rawOptions.minimumContrastRatio/(s.isDim()?2:1);a=h.color.ensureContrastRatio(r||t,n||i,e),o.setColor((r||t).rgba,(n||i).rgba,a??null)}return!!a&&(this._addStyle(e,`color:${a.css}`),!0)}_getContrastCache(e){return e.isDim()?this._themeService.colors.halfContrastCache:this._themeService.colors.contrastCache}_addStyle(e,t){e.setAttribute("style",`${e.getAttribute("style")||""}${t};`)}_isCellInSelection(e,t){const i=this._selectionStart,s=this._selectionEnd;return!(!i||!s)&&(this._columnSelectMode?i[0]<=s[0]?e>=i[0]&&t>=i[1]&&e<s[0]&&t<=s[1]:e<i[0]&&t>=i[1]&&e>=s[0]&&t<=s[1]:t>i[1]&&t<s[1]||i[1]===s[1]&&t===i[1]&&e>=i[0]&&e<s[0]||i[1]<s[1]&&t===s[1]&&e<s[0]||i[1]<s[1]&&t===i[1]&&e>=i[0])}};function p(e,t,i){for(;e.length<i;)e=t+e;return e}t.DomRendererRowFactory=f,t.DomRendererRowFactory=f=s([r(1,c.ICharacterJoinerService),r(2,l.IOptionsService),r(3,c.ICoreBrowserService),r(4,l.ICoreService),r(5,l.IDecorationService),r(6,c.IThemeService)],f)},2744:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.WidthCache=void 0,t.WidthCache=class{constructor(e,t){this._flat=new Float32Array(256),this._font="",this._fontSize=0,this._weight="normal",this._weightBold="bold",this._measureElements=[],this._container=e.createElement("div"),this._container.classList.add("xterm-width-cache-measure-container"),this._container.setAttribute("aria-hidden","true"),this._container.style.whiteSpace="pre",this._container.style.fontKerning="none";const i=e.createElement("span");i.classList.add("xterm-char-measure-element");const s=e.createElement("span");s.classList.add("xterm-char-measure-element"),s.style.fontWeight="bold";const r=e.createElement("span");r.classList.add("xterm-char-measure-element"),r.style.fontStyle="italic";const n=e.createElement("span");n.classList.add("xterm-char-measure-element"),n.style.fontWeight="bold",n.style.fontStyle="italic",this._measureElements=[i,s,r,n],this._container.appendChild(i),this._container.appendChild(s),this._container.appendChild(r),this._container.appendChild(n),t.appendChild(this._container),this.clear()}dispose(){this._container.remove(),this._measureElements.length=0,this._holey=void 0}clear(){this._flat.fill(-9999),this._holey=new Map}setFont(e,t,i,s){e===this._font&&t===this._fontSize&&i===this._weight&&s===this._weightBold||(this._font=e,this._fontSize=t,this._weight=i,this._weightBold=s,this._container.style.fontFamily=this._font,this._container.style.fontSize=`${this._fontSize}px`,this._measureElements[0].style.fontWeight=`${i}`,this._measureElements[1].style.fontWeight=`${s}`,this._measureElements[2].style.fontWeight=`${i}`,this._measureElements[3].style.fontWeight=`${s}`,this.clear())}get(e,t,i){let s=0;if(!t&&!i&&1===e.length&&(s=e.charCodeAt(0))<256){if(-9999!==this._flat[s])return this._flat[s];const t=this._measure(e,0);return t>0&&(this._flat[s]=t),t}let r=e;t&&(r+="B"),i&&(r+="I");let n=this._holey.get(r);if(void 0===n){let s=0;t&&(s|=1),i&&(s|=2),n=this._measure(e,s),n>0&&this._holey.set(r,n)}return n}_measure(e,t){const i=this._measureElements[t];return i.textContent=e.repeat(32),i.offsetWidth/32}}},9176:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.INVERTED_DEFAULT_COLOR=void 0,t.INVERTED_DEFAULT_COLOR=257},6181:(e,t)=>{function i(e){return 57508<=e&&e<=57558}function s(e){return e>=128512&&e<=128591||e>=127744&&e<=128511||e>=128640&&e<=128767||e>=9728&&e<=9983||e>=9984&&e<=10175||e>=65024&&e<=65039||e>=129280&&e<=129535||e>=127462&&e<=127487}Object.defineProperty(t,"__esModule",{value:!0}),t.throwIfFalsy=function(e){if(!e)throw new Error("value must not be falsy");return e},t.isPowerlineGlyph=i,t.isRestrictedPowerlineGlyph=function(e){return 57520<=e&&e<=57527},t.isEmoji=s,t.allowRescaling=function(e,t,r,n){return 1===t&&r>Math.ceil(1.5*n)&&void 0!==e&&e>255&&!s(e)&&!i(e)&&!function(e){return 57344<=e&&e<=63743}(e)},t.treatGlyphAsBackgroundColor=function(e){return i(e)||function(e){return 9472<=e&&e<=9631}(e)},t.createRenderDimensions=function(){return{css:{canvas:{width:0,height:0},cell:{width:0,height:0}},device:{canvas:{width:0,height:0},cell:{width:0,height:0},char:{width:0,height:0,left:0,top:0}}}},t.computeNextVariantOffset=function(e,t,i=0){return(e-(2*Math.round(t)-i))%(2*Math.round(t))}},2274:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.createSelectionRenderModel=function(){return new i};class i{constructor(){this.clear()}clear(){this.hasSelection=!1,this.columnSelectMode=!1,this.viewportStartRow=0,this.viewportEndRow=0,this.viewportCappedStartRow=0,this.viewportCappedEndRow=0,this.startCol=0,this.endCol=0,this.selectionStart=void 0,this.selectionEnd=void 0}update(e,t,i,s=!1){if(this.selectionStart=t,this.selectionEnd=i,!t||!i||t[0]===i[0]&&t[1]===i[1])return void this.clear();const r=e.buffers.active.ydisp,n=t[1]-r,o=i[1]-r,a=Math.max(n,0),l=Math.min(o,e.rows-1);a>=e.rows||l<0?this.clear():(this.hasSelection=!0,this.columnSelectMode=s,this.viewportStartRow=n,this.viewportEndRow=o,this.viewportCappedStartRow=a,this.viewportCappedEndRow=l,this.startCol=t[0],this.endCol=i[0])}isCellSelected(e,t,i){return!!this.hasSelection&&(i-=e.buffer.active.viewportY,this.columnSelectMode?this.startCol<=this.endCol?t>=this.startCol&&i>=this.viewportCappedStartRow&&t<this.endCol&&i<=this.viewportCappedEndRow:t<this.startCol&&i>=this.viewportCappedStartRow&&t>=this.endCol&&i<=this.viewportCappedEndRow:i>this.viewportStartRow&&i<this.viewportEndRow||this.viewportStartRow===this.viewportEndRow&&i===this.viewportStartRow&&t>=this.startCol&&t<this.endCol||this.viewportStartRow<this.viewportEndRow&&i===this.viewportEndRow&&t<this.endCol||this.viewportStartRow<this.viewportEndRow&&i===this.viewportStartRow&&t>=this.startCol)}}},5959:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.SelectionModel=void 0,t.SelectionModel=class{constructor(e){this._bufferService=e,this.isSelectAllActive=!1,this.selectionStartLength=0}clearSelection(){this.selectionStart=void 0,this.selectionEnd=void 0,this.isSelectAllActive=!1,this.selectionStartLength=0}get finalSelectionStart(){return this.isSelectAllActive?[0,0]:this.selectionEnd&&this.selectionStart&&this.areSelectionValuesReversed()?this.selectionEnd:this.selectionStart}get finalSelectionEnd(){if(this.isSelectAllActive)return[this._bufferService.cols,this._bufferService.buffer.ybase+this._bufferService.rows-1];if(this.selectionStart){if(!this.selectionEnd||this.areSelectionValuesReversed()){const e=this.selectionStart[0]+this.selectionStartLength;return e>this._bufferService.cols?e%this._bufferService.cols==0?[this._bufferService.cols,this.selectionStart[1]+Math.floor(e/this._bufferService.cols)-1]:[e%this._bufferService.cols,this.selectionStart[1]+Math.floor(e/this._bufferService.cols)]:[e,this.selectionStart[1]]}if(this.selectionStartLength&&this.selectionEnd[1]===this.selectionStart[1]){const e=this.selectionStart[0]+this.selectionStartLength;return e>this._bufferService.cols?[e%this._bufferService.cols,this.selectionStart[1]+Math.floor(e/this._bufferService.cols)]:[Math.max(e,this.selectionEnd[0]),this.selectionEnd[1]]}return this.selectionEnd}}areSelectionValuesReversed(){const e=this.selectionStart,t=this.selectionEnd;return!(!e||!t)&&(e[1]>t[1]||e[1]===t[1]&&e[0]>t[0])}handleTrim(e){return this.selectionStart&&(this.selectionStart[1]-=e),this.selectionEnd&&(this.selectionEnd[1]-=e),this.selectionEnd&&this.selectionEnd[1]<0?(this.clearSelection(),!0):(this.selectionStart&&this.selectionStart[1]<0&&(this.selectionStart[1]=0),!1)}}},4792:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CharSizeService=void 0;const n=i(6501),o=i(7150),a=i(802);let l=class extends o.Disposable{get hasValidSize(){return this.width>0&&this.height>0}constructor(e,t,i){super(),this._optionsService=i,this.width=0,this.height=0,this._onCharSizeChange=this._register(new a.Emitter),this.onCharSizeChange=this._onCharSizeChange.event;try{this._measureStrategy=this._register(new d(this._optionsService))}catch{this._measureStrategy=this._register(new c(e,t,this._optionsService))}this._register(this._optionsService.onMultipleOptionChange(["fontFamily","fontSize"],(()=>this.measure())))}measure(){const e=this._measureStrategy.measure();e.width===this.width&&e.height===this.height||(this.width=e.width,this.height=e.height,this._onCharSizeChange.fire())}};t.CharSizeService=l,t.CharSizeService=l=s([r(2,n.IOptionsService)],l);class h extends o.Disposable{constructor(){super(...arguments),this._result={width:0,height:0}}_validateAndSet(e,t){void 0!==e&&e>0&&void 0!==t&&t>0&&(this._result.width=e,this._result.height=t)}}class c extends h{constructor(e,t,i){super(),this._document=e,this._parentElement=t,this._optionsService=i,this._measureElement=this._document.createElement("span"),this._measureElement.classList.add("xterm-char-measure-element"),this._measureElement.textContent="W".repeat(32),this._measureElement.setAttribute("aria-hidden","true"),this._measureElement.style.whiteSpace="pre",this._measureElement.style.fontKerning="none",this._parentElement.appendChild(this._measureElement)}measure(){return this._measureElement.style.fontFamily=this._optionsService.rawOptions.fontFamily,this._measureElement.style.fontSize=`${this._optionsService.rawOptions.fontSize}px`,this._validateAndSet(Number(this._measureElement.offsetWidth)/32,Number(this._measureElement.offsetHeight)),this._result}}class d extends h{constructor(e){super(),this._optionsService=e,this._canvas=new OffscreenCanvas(100,100),this._ctx=this._canvas.getContext("2d");const t=this._ctx.measureText("W");if(!("width"in t&&"fontBoundingBoxAscent"in t&&"fontBoundingBoxDescent"in t))throw new Error("Required font metrics not supported")}measure(){this._ctx.font=`${this._optionsService.rawOptions.fontSize}px ${this._optionsService.rawOptions.fontFamily}`;const e=this._ctx.measureText("W");return this._validateAndSet(e.width,e.fontBoundingBoxAscent+e.fontBoundingBoxDescent),this._result}}},945:function(e,t,i){var s,r=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},n=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CharacterJoinerService=t.JoinedCellData=void 0;const o=i(5451),a=i(8938),l=i(3055),h=i(6501);class c extends o.AttributeData{constructor(e,t,i){super(),this.content=0,this.combinedData="",this.fg=e.fg,this.bg=e.bg,this.combinedData=t,this._width=i}isCombined(){return 2097152}getWidth(){return this._width}getChars(){return this.combinedData}getCode(){return 2097151}setFromCharData(e){throw new Error("not implemented")}getAsCharData(){return[this.fg,this.getChars(),this.getWidth(),this.getCode()]}}t.JoinedCellData=c;let d=s=class{constructor(e){this._bufferService=e,this._characterJoiners=[],this._nextCharacterJoinerId=0,this._workCell=new l.CellData}register(e){const t={id:this._nextCharacterJoinerId++,handler:e};return this._characterJoiners.push(t),t.id}deregister(e){for(let t=0;t<this._characterJoiners.length;t++)if(this._characterJoiners[t].id===e)return this._characterJoiners.splice(t,1),!0;return!1}getJoinedCharacters(e){if(0===this._characterJoiners.length)return[];const t=this._bufferService.buffer.lines.get(e);if(!t||0===t.length)return[];const i=[],s=t.translateToString(!0);let r=0,n=0,o=0,l=t.getFg(0),h=t.getBg(0);for(let e=0;e<t.getTrimmedLength();e++)if(t.loadCell(e,this._workCell),0!==this._workCell.getWidth()){if(this._workCell.fg!==l||this._workCell.bg!==h){if(e-r>1){const e=this._getJoinedRanges(s,o,n,t,r);for(let t=0;t<e.length;t++)i.push(e[t])}r=e,o=n,l=this._workCell.fg,h=this._workCell.bg}n+=this._workCell.getChars().length||a.WHITESPACE_CELL_CHAR.length}if(this._bufferService.cols-r>1){const e=this._getJoinedRanges(s,o,n,t,r);for(let t=0;t<e.length;t++)i.push(e[t])}return i}_getJoinedRanges(e,t,i,r,n){const o=e.substring(t,i);let a=[];try{a=this._characterJoiners[0].handler(o)}catch(e){console.error(e)}for(let e=1;e<this._characterJoiners.length;e++)try{const t=this._characterJoiners[e].handler(o);for(let e=0;e<t.length;e++)s._mergeRanges(a,t[e])}catch(e){console.error(e)}return this._stringRangesToCellRanges(a,r,n),a}_stringRangesToCellRanges(e,t,i){let s=0,r=!1,n=0,o=e[s];if(o){for(let l=i;l<this._bufferService.cols;l++){const i=t.getWidth(l),h=t.getString(l).length||a.WHITESPACE_CELL_CHAR.length;if(0!==i){if(!r&&o[0]<=n&&(o[0]=l,r=!0),o[1]<=n){if(o[1]=l,o=e[++s],!o)break;o[0]<=n?(o[0]=l,r=!0):r=!1}n+=h}}o&&(o[1]=this._bufferService.cols)}}static _mergeRanges(e,t){let i=!1;for(let s=0;s<e.length;s++){const r=e[s];if(i){if(t[1]<=r[0])return e[s-1][1]=t[1],e;if(t[1]<=r[1])return e[s-1][1]=Math.max(t[1],r[1]),e.splice(s,1),e;e.splice(s,1),s--}else{if(t[1]<=r[0])return e.splice(s,0,t),e;if(t[1]<=r[1])return r[0]=Math.min(t[0],r[0]),e;t[0]<r[1]&&(r[0]=Math.min(t[0],r[0]),i=!0)}}return i?e[e.length-1][1]=t[1]:e.push(t),e}};t.CharacterJoinerService=d,t.CharacterJoinerService=d=s=r([n(0,h.IBufferService)],d)},9574:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CoreBrowserService=void 0;const s=i(802),r=i(7093),n=i(7150);class o extends n.Disposable{constructor(e,t,i){super(),this._textarea=e,this._window=t,this.mainDocument=i,this._isFocused=!1,this._cachedIsFocused=void 0,this._screenDprMonitor=this._register(new a(this._window)),this._onDprChange=this._register(new s.Emitter),this.onDprChange=this._onDprChange.event,this._onWindowChange=this._register(new s.Emitter),this.onWindowChange=this._onWindowChange.event,this._register(this.onWindowChange((e=>this._screenDprMonitor.setWindow(e)))),this._register(s.Event.forward(this._screenDprMonitor.onDprChange,this._onDprChange)),this._register((0,r.addDisposableListener)(this._textarea,"focus",(()=>this._isFocused=!0))),this._register((0,r.addDisposableListener)(this._textarea,"blur",(()=>this._isFocused=!1)))}get window(){return this._window}set window(e){this._window!==e&&(this._window=e,this._onWindowChange.fire(this._window))}get dpr(){return this.window.devicePixelRatio}get isFocused(){return void 0===this._cachedIsFocused&&(this._cachedIsFocused=this._isFocused&&this._textarea.ownerDocument.hasFocus(),queueMicrotask((()=>this._cachedIsFocused=void 0))),this._cachedIsFocused}}t.CoreBrowserService=o;class a extends n.Disposable{constructor(e){super(),this._parentWindow=e,this._windowResizeListener=this._register(new n.MutableDisposable),this._onDprChange=this._register(new s.Emitter),this.onDprChange=this._onDprChange.event,this._outerListener=()=>this._setDprAndFireIfDiffers(),this._currentDevicePixelRatio=this._parentWindow.devicePixelRatio,this._updateDpr(),this._setWindowResizeListener(),this._register((0,n.toDisposable)((()=>this.clearListener())))}setWindow(e){this._parentWindow=e,this._setWindowResizeListener(),this._setDprAndFireIfDiffers()}_setWindowResizeListener(){this._windowResizeListener.value=(0,r.addDisposableListener)(this._parentWindow,"resize",(()=>this._setDprAndFireIfDiffers()))}_setDprAndFireIfDiffers(){this._parentWindow.devicePixelRatio!==this._currentDevicePixelRatio&&this._onDprChange.fire(this._parentWindow.devicePixelRatio),this._updateDpr()}_updateDpr(){this._outerListener&&(this._resolutionMediaMatchList?.removeListener(this._outerListener),this._currentDevicePixelRatio=this._parentWindow.devicePixelRatio,this._resolutionMediaMatchList=this._parentWindow.matchMedia(`screen and (resolution: ${this._parentWindow.devicePixelRatio}dppx)`),this._resolutionMediaMatchList.addListener(this._outerListener))}clearListener(){this._resolutionMediaMatchList&&this._outerListener&&(this._resolutionMediaMatchList.removeListener(this._outerListener),this._resolutionMediaMatchList=void 0,this._outerListener=void 0)}}},9820:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.LinkProviderService=void 0;const s=i(7150);class r extends s.Disposable{constructor(){super(),this.linkProviders=[],this._register((0,s.toDisposable)((()=>this.linkProviders.length=0)))}registerLinkProvider(e){return this.linkProviders.push(e),{dispose:()=>{const t=this.linkProviders.indexOf(e);-1!==t&&this.linkProviders.splice(t,1)}}}}t.LinkProviderService=r},9784:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.MouseService=void 0;const n=i(7098),o=i(5251);let a=class{constructor(e,t){this._renderService=e,this._charSizeService=t}getCoords(e,t,i,s,r){return(0,o.getCoords)(window,e,t,i,s,this._charSizeService.hasValidSize,this._renderService.dimensions.css.cell.width,this._renderService.dimensions.css.cell.height,r)}getMouseReportCoords(e,t){const i=(0,o.getCoordsRelativeToElement)(window,e,t);if(this._charSizeService.hasValidSize)return i[0]=Math.min(Math.max(i[0],0),this._renderService.dimensions.css.canvas.width-1),i[1]=Math.min(Math.max(i[1],0),this._renderService.dimensions.css.canvas.height-1),{col:Math.floor(i[0]/this._renderService.dimensions.css.cell.width),row:Math.floor(i[1]/this._renderService.dimensions.css.cell.height),x:Math.floor(i[0]),y:Math.floor(i[1])}}};t.MouseService=a,t.MouseService=a=s([r(0,n.IRenderService),r(1,n.ICharSizeService)],a)},5783:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.RenderService=void 0;const n=i(4852),o=i(7098),a=i(7150),l=i(6168),h=i(6501),c=i(802);let d=class extends a.Disposable{get dimensions(){return this._renderer.value.dimensions}constructor(e,t,i,s,r,o,h,d,_){super(),this._rowCount=e,this._optionsService=i,this._charSizeService=s,this._coreService=r,this._coreBrowserService=d,this._renderer=this._register(new a.MutableDisposable),this._pausedResizeTask=new l.DebouncedIdleTask,this._observerDisposable=this._register(new a.MutableDisposable),this._isPaused=!1,this._needsFullRefresh=!1,this._isNextRenderRedrawOnly=!0,this._needsSelectionRefresh=!1,this._canvasWidth=0,this._canvasHeight=0,this._selectionState={start:void 0,end:void 0,columnSelectMode:!1},this._onDimensionsChange=this._register(new c.Emitter),this.onDimensionsChange=this._onDimensionsChange.event,this._onRenderedViewportChange=this._register(new c.Emitter),this.onRenderedViewportChange=this._onRenderedViewportChange.event,this._onRender=this._register(new c.Emitter),this.onRender=this._onRender.event,this._onRefreshRequest=this._register(new c.Emitter),this.onRefreshRequest=this._onRefreshRequest.event,this._renderDebouncer=new n.RenderDebouncer(((e,t)=>this._renderRows(e,t)),this._coreBrowserService),this._register(this._renderDebouncer),this._syncOutputHandler=new u(this._coreBrowserService,this._coreService,(()=>this._fullRefresh())),this._register((0,a.toDisposable)((()=>this._syncOutputHandler.dispose()))),this._register(this._coreBrowserService.onDprChange((()=>this.handleDevicePixelRatioChange()))),this._register(h.onResize((()=>this._fullRefresh()))),this._register(h.buffers.onBufferActivate((()=>this._renderer.value?.clear()))),this._register(this._optionsService.onOptionChange((()=>this._handleOptionsChanged()))),this._register(this._charSizeService.onCharSizeChange((()=>this.handleCharSizeChanged()))),this._register(o.onDecorationRegistered((()=>this._fullRefresh()))),this._register(o.onDecorationRemoved((()=>this._fullRefresh()))),this._register(this._optionsService.onMultipleOptionChange(["customGlyphs","drawBoldTextInBrightColors","letterSpacing","lineHeight","fontFamily","fontSize","fontWeight","fontWeightBold","minimumContrastRatio","rescaleOverlappingGlyphs"],(()=>{this.clear(),this.handleResize(h.cols,h.rows),this._fullRefresh()}))),this._register(this._optionsService.onMultipleOptionChange(["cursorBlink","cursorStyle"],(()=>this.refreshRows(h.buffer.y,h.buffer.y,!0)))),this._register(_.onChangeColors((()=>this._fullRefresh()))),this._registerIntersectionObserver(this._coreBrowserService.window,t),this._register(this._coreBrowserService.onWindowChange((e=>this._registerIntersectionObserver(e,t))))}_registerIntersectionObserver(e,t){if("IntersectionObserver"in e){const i=new e.IntersectionObserver((e=>this._handleIntersectionChange(e[e.length-1])),{threshold:0});i.observe(t),this._observerDisposable.value=(0,a.toDisposable)((()=>i.disconnect()))}}_handleIntersectionChange(e){this._isPaused=void 0===e.isIntersecting?0===e.intersectionRatio:!e.isIntersecting,this._isPaused||this._charSizeService.hasValidSize||this._charSizeService.measure(),!this._isPaused&&this._needsFullRefresh&&(this._pausedResizeTask.flush(),this.refreshRows(0,this._rowCount-1),this._needsFullRefresh=!1)}refreshRows(e,t,i=!1){if(this._isPaused)return void(this._needsFullRefresh=!0);if(this._coreService.decPrivateModes.synchronizedOutput)return void this._syncOutputHandler.bufferRows(e,t);const s=this._syncOutputHandler.flush();s&&(e=Math.min(e,s.start),t=Math.max(t,s.end)),i||(this._isNextRenderRedrawOnly=!1),this._renderDebouncer.refresh(e,t,this._rowCount)}_renderRows(e,t){this._renderer.value&&(this._coreService.decPrivateModes.synchronizedOutput?this._syncOutputHandler.bufferRows(e,t):(e=Math.min(e,this._rowCount-1),t=Math.min(t,this._rowCount-1),this._renderer.value.renderRows(e,t),this._needsSelectionRefresh&&(this._renderer.value.handleSelectionChanged(this._selectionState.start,this._selectionState.end,this._selectionState.columnSelectMode),this._needsSelectionRefresh=!1),this._isNextRenderRedrawOnly||this._onRenderedViewportChange.fire({start:e,end:t}),this._onRender.fire({start:e,end:t}),this._isNextRenderRedrawOnly=!0))}resize(e,t){this._rowCount=t,this._fireOnCanvasResize()}_handleOptionsChanged(){this._renderer.value&&(this.refreshRows(0,this._rowCount-1),this._fireOnCanvasResize())}_fireOnCanvasResize(){this._renderer.value&&(this._renderer.value.dimensions.css.canvas.width===this._canvasWidth&&this._renderer.value.dimensions.css.canvas.height===this._canvasHeight||this._onDimensionsChange.fire(this._renderer.value.dimensions))}hasRenderer(){return!!this._renderer.value}setRenderer(e){this._renderer.value=e,this._renderer.value&&(this._renderer.value.onRequestRedraw((e=>this.refreshRows(e.start,e.end,!0))),this._needsSelectionRefresh=!0,this._fullRefresh())}addRefreshCallback(e){return this._renderDebouncer.addRefreshCallback(e)}_fullRefresh(){this._isPaused?this._needsFullRefresh=!0:this.refreshRows(0,this._rowCount-1)}clearTextureAtlas(){this._renderer.value&&(this._renderer.value.clearTextureAtlas?.(),this._fullRefresh())}handleDevicePixelRatioChange(){this._charSizeService.measure(),this._renderer.value&&(this._renderer.value.handleDevicePixelRatioChange(),this.refreshRows(0,this._rowCount-1))}handleResize(e,t){this._renderer.value&&(this._isPaused?this._pausedResizeTask.set((()=>this._renderer.value?.handleResize(e,t))):this._renderer.value.handleResize(e,t),this._fullRefresh())}handleCharSizeChanged(){this._renderer.value?.handleCharSizeChanged()}handleBlur(){this._renderer.value?.handleBlur()}handleFocus(){this._renderer.value?.handleFocus()}handleSelectionChanged(e,t,i){this._selectionState.start=e,this._selectionState.end=t,this._selectionState.columnSelectMode=i,this._renderer.value?.handleSelectionChanged(e,t,i)}handleCursorMove(){this._renderer.value?.handleCursorMove()}clear(){this._renderer.value?.clear()}};t.RenderService=d,t.RenderService=d=s([r(2,h.IOptionsService),r(3,o.ICharSizeService),r(4,h.ICoreService),r(5,h.IDecorationService),r(6,h.IBufferService),r(7,o.ICoreBrowserService),r(8,o.IThemeService)],d);class u{constructor(e,t,i){this._coreBrowserService=e,this._coreService=t,this._onTimeout=i,this._start=0,this._end=0,this._isBuffering=!1}bufferRows(e,t){this._isBuffering?(this._start=Math.min(this._start,e),this._end=Math.max(this._end,t)):(this._start=e,this._end=t,this._isBuffering=!0),void 0===this._timeout&&(this._timeout=this._coreBrowserService.window.setTimeout((()=>{this._timeout=void 0,this._coreService.decPrivateModes.synchronizedOutput=!1,this._onTimeout()}),1e3))}flush(){if(void 0!==this._timeout&&(this._coreBrowserService.window.clearTimeout(this._timeout),this._timeout=void 0),!this._isBuffering)return;const e={start:this._start,end:this._end};return this._isBuffering=!1,e}dispose(){void 0!==this._timeout&&(this._coreBrowserService.window.clearTimeout(this._timeout),this._timeout=void 0)}}},2079:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.SelectionService=void 0;const n=i(5251),o=i(9686),a=i(5959),l=i(7098),h=i(7150),c=i(701),d=i(9384),u=i(3055),_=i(6501),f=i(802),p=String.fromCharCode(160),g=new RegExp(p,"g");let m=class extends h.Disposable{constructor(e,t,i,s,r,n,o,l,c){super(),this._element=e,this._screenElement=t,this._linkifier=i,this._bufferService=s,this._coreService=r,this._mouseService=n,this._optionsService=o,this._renderService=l,this._coreBrowserService=c,this._dragScrollAmount=0,this._enabled=!0,this._workCell=new u.CellData,this._mouseDownTimeStamp=0,this._oldHasSelection=!1,this._oldSelectionStart=void 0,this._oldSelectionEnd=void 0,this._onLinuxMouseSelection=this._register(new f.Emitter),this.onLinuxMouseSelection=this._onLinuxMouseSelection.event,this._onRedrawRequest=this._register(new f.Emitter),this.onRequestRedraw=this._onRedrawRequest.event,this._onSelectionChange=this._register(new f.Emitter),this.onSelectionChange=this._onSelectionChange.event,this._onRequestScrollLines=this._register(new f.Emitter),this.onRequestScrollLines=this._onRequestScrollLines.event,this._mouseMoveListener=e=>this._handleMouseMove(e),this._mouseUpListener=e=>this._handleMouseUp(e),this._coreService.onUserInput((()=>{this.hasSelection&&this.clearSelection()})),this._trimListener=this._bufferService.buffer.lines.onTrim((e=>this._handleTrim(e))),this._register(this._bufferService.buffers.onBufferActivate((e=>this._handleBufferActivate(e)))),this.enable(),this._model=new a.SelectionModel(this._bufferService),this._activeSelectionMode=0,this._register((0,h.toDisposable)((()=>{this._removeMouseDownListeners()}))),this._register(this._bufferService.onResize((e=>{e.rowsChanged&&this.clearSelection()})))}reset(){this.clearSelection()}disable(){this.clearSelection(),this._enabled=!1}enable(){this._enabled=!0}get selectionStart(){return this._model.finalSelectionStart}get selectionEnd(){return this._model.finalSelectionEnd}get hasSelection(){const e=this._model.finalSelectionStart,t=this._model.finalSelectionEnd;return!(!e||!t||e[0]===t[0]&&e[1]===t[1])}get selectionText(){const e=this._model.finalSelectionStart,t=this._model.finalSelectionEnd;if(!e||!t)return"";const i=this._bufferService.buffer,s=[];if(3===this._activeSelectionMode){if(e[0]===t[0])return"";const r=e[0]<t[0]?e[0]:t[0],n=e[0]<t[0]?t[0]:e[0];for(let o=e[1];o<=t[1];o++){const e=i.translateBufferLineToString(o,!0,r,n);s.push(e)}}else{const r=e[1]===t[1]?t[0]:void 0;s.push(i.translateBufferLineToString(e[1],!0,e[0],r));for(let r=e[1]+1;r<=t[1]-1;r++){const e=i.lines.get(r),t=i.translateBufferLineToString(r,!0);e?.isWrapped?s[s.length-1]+=t:s.push(t)}if(e[1]!==t[1]){const e=i.lines.get(t[1]),r=i.translateBufferLineToString(t[1],!0,0,t[0]);e&&e.isWrapped?s[s.length-1]+=r:s.push(r)}}return s.map((e=>e.replace(g," "))).join(c.isWindows?"\\r\\n":"\\n")}clearSelection(){this._model.clearSelection(),this._removeMouseDownListeners(),this.refresh(),this._onSelectionChange.fire()}refresh(e){this._refreshAnimationFrame||(this._refreshAnimationFrame=this._coreBrowserService.window.requestAnimationFrame((()=>this._refresh()))),c.isLinux&&e&&this.selectionText.length&&this._onLinuxMouseSelection.fire(this.selectionText)}_refresh(){this._refreshAnimationFrame=void 0,this._onRedrawRequest.fire({start:this._model.finalSelectionStart,end:this._model.finalSelectionEnd,columnSelectMode:3===this._activeSelectionMode})}_isClickInSelection(e){const t=this._getMouseBufferCoords(e),i=this._model.finalSelectionStart,s=this._model.finalSelectionEnd;return!!(i&&s&&t)&&this._areCoordsInSelection(t,i,s)}isCellInSelection(e,t){const i=this._model.finalSelectionStart,s=this._model.finalSelectionEnd;return!(!i||!s)&&this._areCoordsInSelection([e,t],i,s)}_areCoordsInSelection(e,t,i){return e[1]>t[1]&&e[1]<i[1]||t[1]===i[1]&&e[1]===t[1]&&e[0]>=t[0]&&e[0]<i[0]||t[1]<i[1]&&e[1]===i[1]&&e[0]<i[0]||t[1]<i[1]&&e[1]===t[1]&&e[0]>=t[0]}_selectWordAtCursor(e,t){const i=this._linkifier.currentLink?.link?.range;if(i)return this._model.selectionStart=[i.start.x-1,i.start.y-1],this._model.selectionStartLength=(0,d.getRangeLength)(i,this._bufferService.cols),this._model.selectionEnd=void 0,!0;const s=this._getMouseBufferCoords(e);return!!s&&(this._selectWordAt(s,t),this._model.selectionEnd=void 0,!0)}selectAll(){this._model.isSelectAllActive=!0,this.refresh(),this._onSelectionChange.fire()}selectLines(e,t){this._model.clearSelection(),e=Math.max(e,0),t=Math.min(t,this._bufferService.buffer.lines.length-1),this._model.selectionStart=[0,e],this._model.selectionEnd=[this._bufferService.cols,t],this.refresh(),this._onSelectionChange.fire()}_handleTrim(e){this._model.handleTrim(e)&&this.refresh()}_getMouseBufferCoords(e){const t=this._mouseService.getCoords(e,this._screenElement,this._bufferService.cols,this._bufferService.rows,!0);if(t)return t[0]--,t[1]--,t[1]+=this._bufferService.buffer.ydisp,t}_getMouseEventScrollAmount(e){let t=(0,n.getCoordsRelativeToElement)(this._coreBrowserService.window,e,this._screenElement)[1];const i=this._renderService.dimensions.css.canvas.height;return t>=0&&t<=i?0:(t>i&&(t-=i),t=Math.min(Math.max(t,-50),50),t/=50,t/Math.abs(t)+Math.round(14*t))}shouldForceSelection(e){return c.isMac?e.altKey&&this._optionsService.rawOptions.macOptionClickForcesSelection:e.shiftKey}handleMouseDown(e){if(this._mouseDownTimeStamp=e.timeStamp,(2!==e.button||!this.hasSelection)&&0===e.button){if(!this._enabled){if(!this.shouldForceSelection(e))return;e.stopPropagation()}e.preventDefault(),this._dragScrollAmount=0,this._enabled&&e.shiftKey?this._handleIncrementalClick(e):1===e.detail?this._handleSingleClick(e):2===e.detail?this._handleDoubleClick(e):3===e.detail&&this._handleTripleClick(e),this._addMouseDownListeners(),this.refresh(!0)}}_addMouseDownListeners(){this._screenElement.ownerDocument&&(this._screenElement.ownerDocument.addEventListener("mousemove",this._mouseMoveListener),this._screenElement.ownerDocument.addEventListener("mouseup",this._mouseUpListener)),this._dragScrollIntervalTimer=this._coreBrowserService.window.setInterval((()=>this._dragScroll()),50)}_removeMouseDownListeners(){this._screenElement.ownerDocument&&(this._screenElement.ownerDocument.removeEventListener("mousemove",this._mouseMoveListener),this._screenElement.ownerDocument.removeEventListener("mouseup",this._mouseUpListener)),this._coreBrowserService.window.clearInterval(this._dragScrollIntervalTimer),this._dragScrollIntervalTimer=void 0}_handleIncrementalClick(e){this._model.selectionStart&&(this._model.selectionEnd=this._getMouseBufferCoords(e))}_handleSingleClick(e){if(this._model.selectionStartLength=0,this._model.isSelectAllActive=!1,this._activeSelectionMode=this.shouldColumnSelect(e)?3:0,this._model.selectionStart=this._getMouseBufferCoords(e),!this._model.selectionStart)return;this._model.selectionEnd=void 0;const t=this._bufferService.buffer.lines.get(this._model.selectionStart[1]);t&&t.length!==this._model.selectionStart[0]&&0===t.hasWidth(this._model.selectionStart[0])&&this._model.selectionStart[0]++}_handleDoubleClick(e){this._selectWordAtCursor(e,!0)&&(this._activeSelectionMode=1)}_handleTripleClick(e){const t=this._getMouseBufferCoords(e);t&&(this._activeSelectionMode=2,this._selectLineAt(t[1]))}shouldColumnSelect(e){return e.altKey&&!(c.isMac&&this._optionsService.rawOptions.macOptionClickForcesSelection)}_handleMouseMove(e){if(e.stopImmediatePropagation(),!this._model.selectionStart)return;const t=this._model.selectionEnd?[this._model.selectionEnd[0],this._model.selectionEnd[1]]:null;if(this._model.selectionEnd=this._getMouseBufferCoords(e),!this._model.selectionEnd)return void this.refresh(!0);2===this._activeSelectionMode?this._model.selectionEnd[1]<this._model.selectionStart[1]?this._model.selectionEnd[0]=0:this._model.selectionEnd[0]=this._bufferService.cols:1===this._activeSelectionMode&&this._selectToWordAt(this._model.selectionEnd),this._dragScrollAmount=this._getMouseEventScrollAmount(e),3!==this._activeSelectionMode&&(this._dragScrollAmount>0?this._model.selectionEnd[0]=this._bufferService.cols:this._dragScrollAmount<0&&(this._model.selectionEnd[0]=0));const i=this._bufferService.buffer;if(this._model.selectionEnd[1]<i.lines.length){const e=i.lines.get(this._model.selectionEnd[1]);e&&0===e.hasWidth(this._model.selectionEnd[0])&&this._model.selectionEnd[0]<this._bufferService.cols&&this._model.selectionEnd[0]++}t&&t[0]===this._model.selectionEnd[0]&&t[1]===this._model.selectionEnd[1]||this.refresh(!0)}_dragScroll(){if(this._model.selectionEnd&&this._model.selectionStart&&this._dragScrollAmount){this._onRequestScrollLines.fire({amount:this._dragScrollAmount,suppressScrollEvent:!1});const e=this._bufferService.buffer;this._dragScrollAmount>0?(3!==this._activeSelectionMode&&(this._model.selectionEnd[0]=this._bufferService.cols),this._model.selectionEnd[1]=Math.min(e.ydisp+this._bufferService.rows,e.lines.length-1)):(3!==this._activeSelectionMode&&(this._model.selectionEnd[0]=0),this._model.selectionEnd[1]=e.ydisp),this.refresh()}}_handleMouseUp(e){const t=e.timeStamp-this._mouseDownTimeStamp;if(this._removeMouseDownListeners(),this.selectionText.length<=1&&t<500&&e.altKey&&this._optionsService.rawOptions.altClickMovesCursor){if(this._bufferService.buffer.ybase===this._bufferService.buffer.ydisp){const t=this._mouseService.getCoords(e,this._element,this._bufferService.cols,this._bufferService.rows,!1);if(t&&void 0!==t[0]&&void 0!==t[1]){const e=(0,o.moveToCellSequence)(t[0]-1,t[1]-1,this._bufferService,this._coreService.decPrivateModes.applicationCursorKeys);this._coreService.triggerDataEvent(e,!0)}}}else this._fireEventIfSelectionChanged()}_fireEventIfSelectionChanged(){const e=this._model.finalSelectionStart,t=this._model.finalSelectionEnd,i=!(!e||!t||e[0]===t[0]&&e[1]===t[1]);i?e&&t&&(this._oldSelectionStart&&this._oldSelectionEnd&&e[0]===this._oldSelectionStart[0]&&e[1]===this._oldSelectionStart[1]&&t[0]===this._oldSelectionEnd[0]&&t[1]===this._oldSelectionEnd[1]||this._fireOnSelectionChange(e,t,i)):this._oldHasSelection&&this._fireOnSelectionChange(e,t,i)}_fireOnSelectionChange(e,t,i){this._oldSelectionStart=e,this._oldSelectionEnd=t,this._oldHasSelection=i,this._onSelectionChange.fire()}_handleBufferActivate(e){this.clearSelection(),this._trimListener.dispose(),this._trimListener=e.activeBuffer.lines.onTrim((e=>this._handleTrim(e)))}_convertViewportColToCharacterIndex(e,t){let i=t;for(let s=0;t>=s;s++){const r=e.loadCell(s,this._workCell).getChars().length;0===this._workCell.getWidth()?i--:r>1&&t!==s&&(i+=r-1)}return i}setSelection(e,t,i){this._model.clearSelection(),this._removeMouseDownListeners(),this._model.selectionStart=[e,t],this._model.selectionStartLength=i,this.refresh(),this._fireEventIfSelectionChanged()}rightClickSelect(e){this._isClickInSelection(e)||(this._selectWordAtCursor(e,!1)&&this.refresh(!0),this._fireEventIfSelectionChanged())}_getWordAt(e,t,i=!0,s=!0){if(e[0]>=this._bufferService.cols)return;const r=this._bufferService.buffer,n=r.lines.get(e[1]);if(!n)return;const o=r.translateBufferLineToString(e[1],!1);let a=this._convertViewportColToCharacterIndex(n,e[0]),l=a;const h=e[0]-a;let c=0,d=0,u=0,_=0;if(" "===o.charAt(a)){for(;a>0&&" "===o.charAt(a-1);)a--;for(;l<o.length&&" "===o.charAt(l+1);)l++}else{let t=e[0],i=e[0];0===n.getWidth(t)&&(c++,t--),2===n.getWidth(i)&&(d++,i++);const s=n.getString(i).length;for(s>1&&(_+=s-1,l+=s-1);t>0&&a>0&&!this._isCharWordSeparator(n.loadCell(t-1,this._workCell));){n.loadCell(t-1,this._workCell);const e=this._workCell.getChars().length;0===this._workCell.getWidth()?(c++,t--):e>1&&(u+=e-1,a-=e-1),a--,t--}for(;i<n.length&&l+1<o.length&&!this._isCharWordSeparator(n.loadCell(i+1,this._workCell));){n.loadCell(i+1,this._workCell);const e=this._workCell.getChars().length;2===this._workCell.getWidth()?(d++,i++):e>1&&(_+=e-1,l+=e-1),l++,i++}}l++;let f=a+h-c+u,p=Math.min(this._bufferService.cols,l-a+c+d-u-_);if(t||""!==o.slice(a,l).trim()){if(i&&0===f&&32!==n.getCodePoint(0)){const t=r.lines.get(e[1]-1);if(t&&n.isWrapped&&32!==t.getCodePoint(this._bufferService.cols-1)){const t=this._getWordAt([this._bufferService.cols-1,e[1]-1],!1,!0,!1);if(t){const e=this._bufferService.cols-t.start;f-=e,p+=e}}}if(s&&f+p===this._bufferService.cols&&32!==n.getCodePoint(this._bufferService.cols-1)){const t=r.lines.get(e[1]+1);if(t?.isWrapped&&32!==t.getCodePoint(0)){const t=this._getWordAt([0,e[1]+1],!1,!1,!0);t&&(p+=t.length)}}return{start:f,length:p}}}_selectWordAt(e,t){const i=this._getWordAt(e,t);if(i){for(;i.start<0;)i.start+=this._bufferService.cols,e[1]--;this._model.selectionStart=[i.start,e[1]],this._model.selectionStartLength=i.length}}_selectToWordAt(e){const t=this._getWordAt(e,!0);if(t){let i=e[1];for(;t.start<0;)t.start+=this._bufferService.cols,i--;if(!this._model.areSelectionValuesReversed())for(;t.start+t.length>this._bufferService.cols;)t.length-=this._bufferService.cols,i++;this._model.selectionEnd=[this._model.areSelectionValuesReversed()?t.start:t.start+t.length,i]}}_isCharWordSeparator(e){return 0!==e.getWidth()&&this._optionsService.rawOptions.wordSeparator.indexOf(e.getChars())>=0}_selectLineAt(e){const t=this._bufferService.buffer.getWrappedRangeForLine(e),i={start:{x:0,y:t.first},end:{x:this._bufferService.cols-1,y:t.last}};this._model.selectionStart=[0,t.first],this._model.selectionEnd=void 0,this._model.selectionStartLength=(0,d.getRangeLength)(i,this._bufferService.cols)}};t.SelectionService=m,t.SelectionService=m=s([r(3,_.IBufferService),r(4,_.ICoreService),r(5,l.IMouseService),r(6,_.IOptionsService),r(7,l.IRenderService),r(8,l.ICoreBrowserService)],m)},7098:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ILinkProviderService=t.IThemeService=t.ICharacterJoinerService=t.ISelectionService=t.IRenderService=t.IMouseService=t.ICoreBrowserService=t.ICharSizeService=void 0;const s=i(6201);t.ICharSizeService=(0,s.createDecorator)("CharSizeService"),t.ICoreBrowserService=(0,s.createDecorator)("CoreBrowserService"),t.IMouseService=(0,s.createDecorator)("MouseService"),t.IRenderService=(0,s.createDecorator)("RenderService"),t.ISelectionService=(0,s.createDecorator)("SelectionService"),t.ICharacterJoinerService=(0,s.createDecorator)("CharacterJoinerService"),t.IThemeService=(0,s.createDecorator)("ThemeService"),t.ILinkProviderService=(0,s.createDecorator)("LinkProviderService")},9078:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.ThemeService=void 0;const n=i(7174),o=i(9302),a=i(4103),l=i(7150),h=i(6501),c=i(802),d=a.css.toColor("#ffffff"),u=a.css.toColor("#000000"),_=a.css.toColor("#ffffff"),f=u,p={css:"rgba(255, 255, 255, 0.3)",rgba:4294967117},g=d;let m=class extends l.Disposable{get colors(){return this._colors}constructor(e){super(),this._optionsService=e,this._contrastCache=new n.ColorContrastCache,this._halfContrastCache=new n.ColorContrastCache,this._onChangeColors=this._register(new c.Emitter),this.onChangeColors=this._onChangeColors.event,this._colors={foreground:d,background:u,cursor:_,cursorAccent:f,selectionForeground:void 0,selectionBackgroundTransparent:p,selectionBackgroundOpaque:a.color.blend(u,p),selectionInactiveBackgroundTransparent:p,selectionInactiveBackgroundOpaque:a.color.blend(u,p),scrollbarSliderBackground:a.color.opacity(d,.2),scrollbarSliderHoverBackground:a.color.opacity(d,.4),scrollbarSliderActiveBackground:a.color.opacity(d,.5),overviewRulerBorder:d,ansi:o.DEFAULT_ANSI_COLORS.slice(),contrastCache:this._contrastCache,halfContrastCache:this._halfContrastCache},this._updateRestoreColors(),this._setTheme(this._optionsService.rawOptions.theme),this._register(this._optionsService.onSpecificOptionChange("minimumContrastRatio",(()=>this._contrastCache.clear()))),this._register(this._optionsService.onSpecificOptionChange("theme",(()=>this._setTheme(this._optionsService.rawOptions.theme))))}_setTheme(e={}){const t=this._colors;if(t.foreground=v(e.foreground,d),t.background=v(e.background,u),t.cursor=a.color.blend(t.background,v(e.cursor,_)),t.cursorAccent=a.color.blend(t.background,v(e.cursorAccent,f)),t.selectionBackgroundTransparent=v(e.selectionBackground,p),t.selectionBackgroundOpaque=a.color.blend(t.background,t.selectionBackgroundTransparent),t.selectionInactiveBackgroundTransparent=v(e.selectionInactiveBackground,t.selectionBackgroundTransparent),t.selectionInactiveBackgroundOpaque=a.color.blend(t.background,t.selectionInactiveBackgroundTransparent),t.selectionForeground=e.selectionForeground?v(e.selectionForeground,a.NULL_COLOR):void 0,t.selectionForeground===a.NULL_COLOR&&(t.selectionForeground=void 0),a.color.isOpaque(t.selectionBackgroundTransparent)){const e=.3;t.selectionBackgroundTransparent=a.color.opacity(t.selectionBackgroundTransparent,e)}if(a.color.isOpaque(t.selectionInactiveBackgroundTransparent)){const e=.3;t.selectionInactiveBackgroundTransparent=a.color.opacity(t.selectionInactiveBackgroundTransparent,e)}if(t.scrollbarSliderBackground=v(e.scrollbarSliderBackground,a.color.opacity(t.foreground,.2)),t.scrollbarSliderHoverBackground=v(e.scrollbarSliderHoverBackground,a.color.opacity(t.foreground,.4)),t.scrollbarSliderActiveBackground=v(e.scrollbarSliderActiveBackground,a.color.opacity(t.foreground,.5)),t.overviewRulerBorder=v(e.overviewRulerBorder,g),t.ansi=o.DEFAULT_ANSI_COLORS.slice(),t.ansi[0]=v(e.black,o.DEFAULT_ANSI_COLORS[0]),t.ansi[1]=v(e.red,o.DEFAULT_ANSI_COLORS[1]),t.ansi[2]=v(e.green,o.DEFAULT_ANSI_COLORS[2]),t.ansi[3]=v(e.yellow,o.DEFAULT_ANSI_COLORS[3]),t.ansi[4]=v(e.blue,o.DEFAULT_ANSI_COLORS[4]),t.ansi[5]=v(e.magenta,o.DEFAULT_ANSI_COLORS[5]),t.ansi[6]=v(e.cyan,o.DEFAULT_ANSI_COLORS[6]),t.ansi[7]=v(e.white,o.DEFAULT_ANSI_COLORS[7]),t.ansi[8]=v(e.brightBlack,o.DEFAULT_ANSI_COLORS[8]),t.ansi[9]=v(e.brightRed,o.DEFAULT_ANSI_COLORS[9]),t.ansi[10]=v(e.brightGreen,o.DEFAULT_ANSI_COLORS[10]),t.ansi[11]=v(e.brightYellow,o.DEFAULT_ANSI_COLORS[11]),t.ansi[12]=v(e.brightBlue,o.DEFAULT_ANSI_COLORS[12]),t.ansi[13]=v(e.brightMagenta,o.DEFAULT_ANSI_COLORS[13]),t.ansi[14]=v(e.brightCyan,o.DEFAULT_ANSI_COLORS[14]),t.ansi[15]=v(e.brightWhite,o.DEFAULT_ANSI_COLORS[15]),e.extendedAnsi){const i=Math.min(t.ansi.length-16,e.extendedAnsi.length);for(let s=0;s<i;s++)t.ansi[s+16]=v(e.extendedAnsi[s],o.DEFAULT_ANSI_COLORS[s+16])}this._contrastCache.clear(),this._halfContrastCache.clear(),this._updateRestoreColors(),this._onChangeColors.fire(this.colors)}restoreColor(e){this._restoreColor(e),this._onChangeColors.fire(this.colors)}_restoreColor(e){if(void 0!==e)switch(e){case 256:this._colors.foreground=this._restoreColors.foreground;break;case 257:this._colors.background=this._restoreColors.background;break;case 258:this._colors.cursor=this._restoreColors.cursor;break;default:this._colors.ansi[e]=this._restoreColors.ansi[e]}else for(let e=0;e<this._restoreColors.ansi.length;++e)this._colors.ansi[e]=this._restoreColors.ansi[e]}modifyColors(e){e(this._colors),this._onChangeColors.fire(this.colors)}_updateRestoreColors(){this._restoreColors={foreground:this._colors.foreground,background:this._colors.background,cursor:this._colors.cursor,ansi:this._colors.ansi.slice()}}};function v(e,t){if(void 0!==e)try{return a.css.toColor(e)}catch{}return t}t.ThemeService=m,t.ThemeService=m=s([r(0,h.IOptionsService)],m)},5639:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CircularList=void 0;const s=i(7150),r=i(802);class n extends s.Disposable{constructor(e){super(),this._maxLength=e,this.onDeleteEmitter=this._register(new r.Emitter),this.onDelete=this.onDeleteEmitter.event,this.onInsertEmitter=this._register(new r.Emitter),this.onInsert=this.onInsertEmitter.event,this.onTrimEmitter=this._register(new r.Emitter),this.onTrim=this.onTrimEmitter.event,this._array=new Array(this._maxLength),this._startIndex=0,this._length=0}get maxLength(){return this._maxLength}set maxLength(e){if(this._maxLength===e)return;const t=new Array(e);for(let i=0;i<Math.min(e,this.length);i++)t[i]=this._array[this._getCyclicIndex(i)];this._array=t,this._maxLength=e,this._startIndex=0}get length(){return this._length}set length(e){if(e>this._length)for(let t=this._length;t<e;t++)this._array[t]=void 0;this._length=e}get(e){return this._array[this._getCyclicIndex(e)]}set(e,t){this._array[this._getCyclicIndex(e)]=t}push(e){this._array[this._getCyclicIndex(this._length)]=e,this._length===this._maxLength?(this._startIndex=++this._startIndex%this._maxLength,this.onTrimEmitter.fire(1)):this._length++}recycle(){if(this._length!==this._maxLength)throw new Error("Can only recycle when the buffer is full");return this._startIndex=++this._startIndex%this._maxLength,this.onTrimEmitter.fire(1),this._array[this._getCyclicIndex(this._length-1)]}get isFull(){return this._length===this._maxLength}pop(){return this._array[this._getCyclicIndex(this._length---1)]}splice(e,t,...i){if(t){for(let i=e;i<this._length-t;i++)this._array[this._getCyclicIndex(i)]=this._array[this._getCyclicIndex(i+t)];this._length-=t,this.onDeleteEmitter.fire({index:e,amount:t})}for(let t=this._length-1;t>=e;t--)this._array[this._getCyclicIndex(t+i.length)]=this._array[this._getCyclicIndex(t)];for(let t=0;t<i.length;t++)this._array[this._getCyclicIndex(e+t)]=i[t];if(i.length&&this.onInsertEmitter.fire({index:e,amount:i.length}),this._length+i.length>this._maxLength){const e=this._length+i.length-this._maxLength;this._startIndex+=e,this._length=this._maxLength,this.onTrimEmitter.fire(e)}else this._length+=i.length}trimStart(e){e>this._length&&(e=this._length),this._startIndex+=e,this._length-=e,this.onTrimEmitter.fire(e)}shiftElements(e,t,i){if(!(t<=0)){if(e<0||e>=this._length)throw new Error("start argument out of range");if(e+i<0)throw new Error("Cannot shift elements in list beyond index 0");if(i>0){for(let s=t-1;s>=0;s--)this.set(e+s+i,this.get(e+s));const s=e+t+i-this._length;if(s>0)for(this._length+=s;this._length>this._maxLength;)this._length--,this._startIndex++,this.onTrimEmitter.fire(1)}else for(let s=0;s<t;s++)this.set(e+s+i,this.get(e+s))}}_getCyclicIndex(e){return(this._startIndex+e)%this._maxLength}}t.CircularList=n},7453:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.clone=function e(t,i=5){if("object"!=typeof t)return t;const s=Array.isArray(t)?[]:{};for(const r in t)s[r]=i<=1?t[r]:t[r]&&e(t[r],i-1);return s}},4103:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.rgba=t.rgb=t.css=t.color=t.channels=t.NULL_COLOR=void 0,t.toPaddedHex=d,t.contrastRatio=u;let i=0,s=0,r=0,n=0;var o,a,l,h,c;function d(e){const t=e.toString(16);return t.length<2?"0"+t:t}function u(e,t){return e<t?(t+.05)/(e+.05):(e+.05)/(t+.05)}t.NULL_COLOR={css:"#00000000",rgba:0},function(e){e.toCss=function(e,t,i,s){return void 0!==s?`#${d(e)}${d(t)}${d(i)}${d(s)}`:`#${d(e)}${d(t)}${d(i)}`},e.toRgba=function(e,t,i,s=255){return(e<<24|t<<16|i<<8|s)>>>0},e.toColor=function(t,i,s,r){return{css:e.toCss(t,i,s,r),rgba:e.toRgba(t,i,s,r)}}}(o||(t.channels=o={})),function(e){function t(e,t){return n=Math.round(255*t),[i,s,r]=c.toChannels(e.rgba),{css:o.toCss(i,s,r,n),rgba:o.toRgba(i,s,r,n)}}e.blend=function(e,t){if(n=(255&t.rgba)/255,1===n)return{css:t.css,rgba:t.rgba};const a=t.rgba>>24&255,l=t.rgba>>16&255,h=t.rgba>>8&255,c=e.rgba>>24&255,d=e.rgba>>16&255,u=e.rgba>>8&255;return i=c+Math.round((a-c)*n),s=d+Math.round((l-d)*n),r=u+Math.round((h-u)*n),{css:o.toCss(i,s,r),rgba:o.toRgba(i,s,r)}},e.isOpaque=function(e){return!(255&~e.rgba)},e.ensureContrastRatio=function(e,t,i){const s=c.ensureContrastRatio(e.rgba,t.rgba,i);if(s)return o.toColor(s>>24&255,s>>16&255,s>>8&255)},e.opaque=function(e){const t=(255|e.rgba)>>>0;return[i,s,r]=c.toChannels(t),{css:o.toCss(i,s,r),rgba:t}},e.opacity=t,e.multiplyOpacity=function(e,i){return n=255&e.rgba,t(e,n*i/255)},e.toColorRGB=function(e){return[e.rgba>>24&255,e.rgba>>16&255,e.rgba>>8&255]}}(a||(t.color=a={})),function(e){let t,a;try{const e=document.createElement("canvas");e.width=1,e.height=1;const i=e.getContext("2d",{willReadFrequently:!0});i&&(t=i,t.globalCompositeOperation="copy",a=t.createLinearGradient(0,0,1,1))}catch{}e.toColor=function(e){if(e.match(/#[\\da-f]{3,8}/i))switch(e.length){case 4:return i=parseInt(e.slice(1,2).repeat(2),16),s=parseInt(e.slice(2,3).repeat(2),16),r=parseInt(e.slice(3,4).repeat(2),16),o.toColor(i,s,r);case 5:return i=parseInt(e.slice(1,2).repeat(2),16),s=parseInt(e.slice(2,3).repeat(2),16),r=parseInt(e.slice(3,4).repeat(2),16),n=parseInt(e.slice(4,5).repeat(2),16),o.toColor(i,s,r,n);case 7:return{css:e,rgba:(parseInt(e.slice(1),16)<<8|255)>>>0};case 9:return{css:e,rgba:parseInt(e.slice(1),16)>>>0}}const l=e.match(/rgba?\\(\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*,\\s*(\\d{1,3})\\s*(,\\s*(0|1|\\d?\\.(\\d+))\\s*)?\\)/);if(l)return i=parseInt(l[1]),s=parseInt(l[2]),r=parseInt(l[3]),n=Math.round(255*(void 0===l[5]?1:parseFloat(l[5]))),o.toColor(i,s,r,n);if(!t||!a)throw new Error("css.toColor: Unsupported css format");if(t.fillStyle=a,t.fillStyle=e,"string"!=typeof t.fillStyle)throw new Error("css.toColor: Unsupported css format");if(t.fillRect(0,0,1,1),[i,s,r,n]=t.getImageData(0,0,1,1).data,255!==n)throw new Error("css.toColor: Unsupported css format");return{rgba:o.toRgba(i,s,r,n),css:e}}}(l||(t.css=l={})),function(e){function t(e,t,i){const s=e/255,r=t/255,n=i/255;return.2126*(s<=.03928?s/12.92:Math.pow((s+.055)/1.055,2.4))+.7152*(r<=.03928?r/12.92:Math.pow((r+.055)/1.055,2.4))+.0722*(n<=.03928?n/12.92:Math.pow((n+.055)/1.055,2.4))}e.relativeLuminance=function(e){return t(e>>16&255,e>>8&255,255&e)},e.relativeLuminance2=t}(h||(t.rgb=h={})),function(e){function t(e,t,i){const s=e>>24&255,r=e>>16&255,n=e>>8&255;let o=t>>24&255,a=t>>16&255,l=t>>8&255,c=u(h.relativeLuminance2(o,a,l),h.relativeLuminance2(s,r,n));for(;c<i&&(o>0||a>0||l>0);)o-=Math.max(0,Math.ceil(.1*o)),a-=Math.max(0,Math.ceil(.1*a)),l-=Math.max(0,Math.ceil(.1*l)),c=u(h.relativeLuminance2(o,a,l),h.relativeLuminance2(s,r,n));return(o<<24|a<<16|l<<8|255)>>>0}function a(e,t,i){const s=e>>24&255,r=e>>16&255,n=e>>8&255;let o=t>>24&255,a=t>>16&255,l=t>>8&255,c=u(h.relativeLuminance2(o,a,l),h.relativeLuminance2(s,r,n));for(;c<i&&(o<255||a<255||l<255);)o=Math.min(255,o+Math.ceil(.1*(255-o))),a=Math.min(255,a+Math.ceil(.1*(255-a))),l=Math.min(255,l+Math.ceil(.1*(255-l))),c=u(h.relativeLuminance2(o,a,l),h.relativeLuminance2(s,r,n));return(o<<24|a<<16|l<<8|255)>>>0}e.blend=function(e,t){if(n=(255&t)/255,1===n)return t;const a=t>>24&255,l=t>>16&255,h=t>>8&255,c=e>>24&255,d=e>>16&255,u=e>>8&255;return i=c+Math.round((a-c)*n),s=d+Math.round((l-d)*n),r=u+Math.round((h-u)*n),o.toRgba(i,s,r)},e.ensureContrastRatio=function(e,i,s){const r=h.relativeLuminance(e>>8),n=h.relativeLuminance(i>>8);if(u(r,n)<s){if(n<r){const n=t(e,i,s),o=u(r,h.relativeLuminance(n>>8));if(o<s){const t=a(e,i,s);return o>u(r,h.relativeLuminance(t>>8))?n:t}return n}const o=a(e,i,s),l=u(r,h.relativeLuminance(o>>8));if(l<s){const n=t(e,i,s);return l>u(r,h.relativeLuminance(n>>8))?o:n}return o}},e.reduceLuminance=t,e.increaseLuminance=a,e.toChannels=function(e){return[e>>24&255,e>>16&255,e>>8&255,255&e]}}(c||(t.rgba=c={}))},5777:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CoreTerminal=void 0;const s=i(6501),r=i(6025),n=i(7276),o=i(9640),a=i(56),l=i(4071),h=i(7792),c=i(6415),d=i(5746),u=i(5882),_=i(2486),f=i(3562),p=i(8811),g=i(802),m=i(7150);let v=!1;class S extends m.Disposable{get onScroll(){return this._onScrollApi||(this._onScrollApi=this._register(new g.Emitter),this._onScroll.event((e=>{this._onScrollApi?.fire(e.position)}))),this._onScrollApi.event}get cols(){return this._bufferService.cols}get rows(){return this._bufferService.rows}get buffers(){return this._bufferService.buffers}get options(){return this.optionsService.options}set options(e){for(const t in e)this.optionsService.options[t]=e[t]}constructor(e){super(),this._windowsWrappingHeuristics=this._register(new m.MutableDisposable),this._onBinary=this._register(new g.Emitter),this.onBinary=this._onBinary.event,this._onData=this._register(new g.Emitter),this.onData=this._onData.event,this._onLineFeed=this._register(new g.Emitter),this.onLineFeed=this._onLineFeed.event,this._onResize=this._register(new g.Emitter),this.onResize=this._onResize.event,this._onWriteParsed=this._register(new g.Emitter),this.onWriteParsed=this._onWriteParsed.event,this._onScroll=this._register(new g.Emitter),this._instantiationService=new r.InstantiationService,this.optionsService=this._register(new a.OptionsService(e)),this._instantiationService.setService(s.IOptionsService,this.optionsService),this._bufferService=this._register(this._instantiationService.createInstance(o.BufferService)),this._instantiationService.setService(s.IBufferService,this._bufferService),this._logService=this._register(this._instantiationService.createInstance(n.LogService)),this._instantiationService.setService(s.ILogService,this._logService),this.coreService=this._register(this._instantiationService.createInstance(l.CoreService)),this._instantiationService.setService(s.ICoreService,this.coreService),this.coreMouseService=this._register(this._instantiationService.createInstance(h.CoreMouseService)),this._instantiationService.setService(s.ICoreMouseService,this.coreMouseService),this.unicodeService=this._register(this._instantiationService.createInstance(c.UnicodeService)),this._instantiationService.setService(s.IUnicodeService,this.unicodeService),this._charsetService=this._instantiationService.createInstance(d.CharsetService),this._instantiationService.setService(s.ICharsetService,this._charsetService),this._oscLinkService=this._instantiationService.createInstance(p.OscLinkService),this._instantiationService.setService(s.IOscLinkService,this._oscLinkService),this._inputHandler=this._register(new _.InputHandler(this._bufferService,this._charsetService,this.coreService,this._logService,this.optionsService,this._oscLinkService,this.coreMouseService,this.unicodeService)),this._register(g.Event.forward(this._inputHandler.onLineFeed,this._onLineFeed)),this._register(this._inputHandler),this._register(g.Event.forward(this._bufferService.onResize,this._onResize)),this._register(g.Event.forward(this.coreService.onData,this._onData)),this._register(g.Event.forward(this.coreService.onBinary,this._onBinary)),this._register(this.coreService.onRequestScrollToBottom((()=>this.scrollToBottom(!0)))),this._register(this.coreService.onUserInput((()=>this._writeBuffer.handleUserInput()))),this._register(this.optionsService.onMultipleOptionChange(["windowsMode","windowsPty"],(()=>this._handleWindowsPtyOptionChange()))),this._register(this._bufferService.onScroll((()=>{this._onScroll.fire({position:this._bufferService.buffer.ydisp}),this._inputHandler.markRangeDirty(this._bufferService.buffer.scrollTop,this._bufferService.buffer.scrollBottom)}))),this._writeBuffer=this._register(new f.WriteBuffer(((e,t)=>this._inputHandler.parse(e,t)))),this._register(g.Event.forward(this._writeBuffer.onWriteParsed,this._onWriteParsed))}write(e,t){this._writeBuffer.write(e,t)}writeSync(e,t){this._logService.logLevel<=s.LogLevelEnum.WARN&&!v&&(this._logService.warn("writeSync is unreliable and will be removed soon."),v=!0),this._writeBuffer.writeSync(e,t)}input(e,t=!0){this.coreService.triggerDataEvent(e,t)}resize(e,t){isNaN(e)||isNaN(t)||(e=Math.max(e,o.MINIMUM_COLS),t=Math.max(t,o.MINIMUM_ROWS),this._bufferService.resize(e,t))}scroll(e,t=!1){this._bufferService.scroll(e,t)}scrollLines(e,t){this._bufferService.scrollLines(e,t)}scrollPages(e){this.scrollLines(e*(this.rows-1))}scrollToTop(){this.scrollLines(-this._bufferService.buffer.ydisp)}scrollToBottom(e){this.scrollLines(this._bufferService.buffer.ybase-this._bufferService.buffer.ydisp)}scrollToLine(e){const t=e-this._bufferService.buffer.ydisp;0!==t&&this.scrollLines(t)}registerEscHandler(e,t){return this._inputHandler.registerEscHandler(e,t)}registerDcsHandler(e,t){return this._inputHandler.registerDcsHandler(e,t)}registerCsiHandler(e,t){return this._inputHandler.registerCsiHandler(e,t)}registerOscHandler(e,t){return this._inputHandler.registerOscHandler(e,t)}_setup(){this._handleWindowsPtyOptionChange()}reset(){this._inputHandler.reset(),this._bufferService.reset(),this._charsetService.reset(),this.coreService.reset(),this.coreMouseService.reset()}_handleWindowsPtyOptionChange(){let e=!1;const t=this.optionsService.rawOptions.windowsPty;t&&void 0!==t.buildNumber&&void 0!==t.buildNumber?e=!!("conpty"===t.backend&&t.buildNumber<21376):this.optionsService.rawOptions.windowsMode&&(e=!0),e?this._enableWindowsWrappingHeuristics():this._windowsWrappingHeuristics.clear()}_enableWindowsWrappingHeuristics(){if(!this._windowsWrappingHeuristics.value){const e=[];e.push(this.onLineFeed(u.updateWindowsModeWrappedState.bind(null,this._bufferService))),e.push(this.registerCsiHandler({final:"H"},(()=>((0,u.updateWindowsModeWrappedState)(this._bufferService),!1)))),this._windowsWrappingHeuristics.value=(0,m.toDisposable)((()=>{for(const t of e)t.dispose()}))}}}t.CoreTerminal=S},2486:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.InputHandler=t.WindowsOptionsReportType=void 0,t.isValidColorIndex=R;const n=i(3534),o=i(6760),a=i(6717),l=i(7150),h=i(726),c=i(6107),d=i(8938),u=i(3055),_=i(5451),f=i(6501),p=i(6415),g=i(1346),m=i(9823),v=i(8693),S=i(802),b={"(":0,")":1,"*":2,"+":3,"-":1,".":2},C=131072;function y(e,t){if(e>24)return t.setWinLines||!1;switch(e){case 1:return!!t.restoreWin;case 2:return!!t.minimizeWin;case 3:return!!t.setWinPosition;case 4:return!!t.setWinSizePixels;case 5:return!!t.raiseWin;case 6:return!!t.lowerWin;case 7:return!!t.refreshWin;case 8:return!!t.setWinSizeChars;case 9:return!!t.maximizeWin;case 10:return!!t.fullscreenWin;case 11:return!!t.getWinState;case 13:return!!t.getWinPosition;case 14:return!!t.getWinSizePixels;case 15:return!!t.getScreenSizePixels;case 16:return!!t.getCellSizePixels;case 18:return!!t.getWinSizeChars;case 19:return!!t.getScreenSizeChars;case 20:return!!t.getIconTitle;case 21:return!!t.getWinTitle;case 22:return!!t.pushTitle;case 23:return!!t.popTitle;case 24:return!!t.setWinLines}return!1}var w;!function(e){e[e.GET_WIN_SIZE_PIXELS=0]="GET_WIN_SIZE_PIXELS",e[e.GET_CELL_SIZE_PIXELS=1]="GET_CELL_SIZE_PIXELS"}(w||(t.WindowsOptionsReportType=w={}));let E=0;class D extends l.Disposable{getAttrData(){return this._curAttrData}constructor(e,t,i,s,r,l,d,u,_=new a.EscapeSequenceParser){super(),this._bufferService=e,this._charsetService=t,this._coreService=i,this._logService=s,this._optionsService=r,this._oscLinkService=l,this._coreMouseService=d,this._unicodeService=u,this._parser=_,this._parseBuffer=new Uint32Array(4096),this._stringDecoder=new h.StringToUtf32,this._utf8Decoder=new h.Utf8ToUtf32,this._windowTitle="",this._iconName="",this._windowTitleStack=[],this._iconNameStack=[],this._curAttrData=c.DEFAULT_ATTR_DATA.clone(),this._eraseAttrDataInternal=c.DEFAULT_ATTR_DATA.clone(),this._onRequestBell=this._register(new S.Emitter),this.onRequestBell=this._onRequestBell.event,this._onRequestRefreshRows=this._register(new S.Emitter),this.onRequestRefreshRows=this._onRequestRefreshRows.event,this._onRequestReset=this._register(new S.Emitter),this.onRequestReset=this._onRequestReset.event,this._onRequestSendFocus=this._register(new S.Emitter),this.onRequestSendFocus=this._onRequestSendFocus.event,this._onRequestSyncScrollBar=this._register(new S.Emitter),this.onRequestSyncScrollBar=this._onRequestSyncScrollBar.event,this._onRequestWindowsOptionsReport=this._register(new S.Emitter),this.onRequestWindowsOptionsReport=this._onRequestWindowsOptionsReport.event,this._onA11yChar=this._register(new S.Emitter),this.onA11yChar=this._onA11yChar.event,this._onA11yTab=this._register(new S.Emitter),this.onA11yTab=this._onA11yTab.event,this._onCursorMove=this._register(new S.Emitter),this.onCursorMove=this._onCursorMove.event,this._onLineFeed=this._register(new S.Emitter),this.onLineFeed=this._onLineFeed.event,this._onScroll=this._register(new S.Emitter),this.onScroll=this._onScroll.event,this._onTitleChange=this._register(new S.Emitter),this.onTitleChange=this._onTitleChange.event,this._onColor=this._register(new S.Emitter),this.onColor=this._onColor.event,this._parseStack={paused:!1,cursorStartX:0,cursorStartY:0,decodedLength:0,position:0},this._specialColors=[256,257,258],this._register(this._parser),this._dirtyRowTracker=new L(this._bufferService),this._activeBuffer=this._bufferService.buffer,this._register(this._bufferService.buffers.onBufferActivate((e=>this._activeBuffer=e.activeBuffer))),this._parser.setCsiHandlerFallback(((e,t)=>{this._logService.debug("Unknown CSI code: ",{identifier:this._parser.identToString(e),params:t.toArray()})})),this._parser.setEscHandlerFallback((e=>{this._logService.debug("Unknown ESC code: ",{identifier:this._parser.identToString(e)})})),this._parser.setExecuteHandlerFallback((e=>{this._logService.debug("Unknown EXECUTE code: ",{code:e})})),this._parser.setOscHandlerFallback(((e,t,i)=>{this._logService.debug("Unknown OSC code: ",{identifier:e,action:t,data:i})})),this._parser.setDcsHandlerFallback(((e,t,i)=>{"HOOK"===t&&(i=i.toArray()),this._logService.debug("Unknown DCS code: ",{identifier:this._parser.identToString(e),action:t,payload:i})})),this._parser.setPrintHandler(((e,t,i)=>this.print(e,t,i))),this._parser.registerCsiHandler({final:"@"},(e=>this.insertChars(e))),this._parser.registerCsiHandler({intermediates:" ",final:"@"},(e=>this.scrollLeft(e))),this._parser.registerCsiHandler({final:"A"},(e=>this.cursorUp(e))),this._parser.registerCsiHandler({intermediates:" ",final:"A"},(e=>this.scrollRight(e))),this._parser.registerCsiHandler({final:"B"},(e=>this.cursorDown(e))),this._parser.registerCsiHandler({final:"C"},(e=>this.cursorForward(e))),this._parser.registerCsiHandler({final:"D"},(e=>this.cursorBackward(e))),this._parser.registerCsiHandler({final:"E"},(e=>this.cursorNextLine(e))),this._parser.registerCsiHandler({final:"F"},(e=>this.cursorPrecedingLine(e))),this._parser.registerCsiHandler({final:"G"},(e=>this.cursorCharAbsolute(e))),this._parser.registerCsiHandler({final:"H"},(e=>this.cursorPosition(e))),this._parser.registerCsiHandler({final:"I"},(e=>this.cursorForwardTab(e))),this._parser.registerCsiHandler({final:"J"},(e=>this.eraseInDisplay(e,!1))),this._parser.registerCsiHandler({prefix:"?",final:"J"},(e=>this.eraseInDisplay(e,!0))),this._parser.registerCsiHandler({final:"K"},(e=>this.eraseInLine(e,!1))),this._parser.registerCsiHandler({prefix:"?",final:"K"},(e=>this.eraseInLine(e,!0))),this._parser.registerCsiHandler({final:"L"},(e=>this.insertLines(e))),this._parser.registerCsiHandler({final:"M"},(e=>this.deleteLines(e))),this._parser.registerCsiHandler({final:"P"},(e=>this.deleteChars(e))),this._parser.registerCsiHandler({final:"S"},(e=>this.scrollUp(e))),this._parser.registerCsiHandler({final:"T"},(e=>this.scrollDown(e))),this._parser.registerCsiHandler({final:"X"},(e=>this.eraseChars(e))),this._parser.registerCsiHandler({final:"Z"},(e=>this.cursorBackwardTab(e))),this._parser.registerCsiHandler({final:"`"},(e=>this.charPosAbsolute(e))),this._parser.registerCsiHandler({final:"a"},(e=>this.hPositionRelative(e))),this._parser.registerCsiHandler({final:"b"},(e=>this.repeatPrecedingCharacter(e))),this._parser.registerCsiHandler({final:"c"},(e=>this.sendDeviceAttributesPrimary(e))),this._parser.registerCsiHandler({prefix:">",final:"c"},(e=>this.sendDeviceAttributesSecondary(e))),this._parser.registerCsiHandler({final:"d"},(e=>this.linePosAbsolute(e))),this._parser.registerCsiHandler({final:"e"},(e=>this.vPositionRelative(e))),this._parser.registerCsiHandler({final:"f"},(e=>this.hVPosition(e))),this._parser.registerCsiHandler({final:"g"},(e=>this.tabClear(e))),this._parser.registerCsiHandler({final:"h"},(e=>this.setMode(e))),this._parser.registerCsiHandler({prefix:"?",final:"h"},(e=>this.setModePrivate(e))),this._parser.registerCsiHandler({final:"l"},(e=>this.resetMode(e))),this._parser.registerCsiHandler({prefix:"?",final:"l"},(e=>this.resetModePrivate(e))),this._parser.registerCsiHandler({final:"m"},(e=>this.charAttributes(e))),this._parser.registerCsiHandler({final:"n"},(e=>this.deviceStatus(e))),this._parser.registerCsiHandler({prefix:"?",final:"n"},(e=>this.deviceStatusPrivate(e))),this._parser.registerCsiHandler({intermediates:"!",final:"p"},(e=>this.softReset(e))),this._parser.registerCsiHandler({intermediates:" ",final:"q"},(e=>this.setCursorStyle(e))),this._parser.registerCsiHandler({final:"r"},(e=>this.setScrollRegion(e))),this._parser.registerCsiHandler({final:"s"},(e=>this.saveCursor(e))),this._parser.registerCsiHandler({final:"t"},(e=>this.windowOptions(e))),this._parser.registerCsiHandler({final:"u"},(e=>this.restoreCursor(e))),this._parser.registerCsiHandler({intermediates:"\'",final:"}"},(e=>this.insertColumns(e))),this._parser.registerCsiHandler({intermediates:"\'",final:"~"},(e=>this.deleteColumns(e))),this._parser.registerCsiHandler({intermediates:\'"\',final:"q"},(e=>this.selectProtected(e))),this._parser.registerCsiHandler({intermediates:"$",final:"p"},(e=>this.requestMode(e,!0))),this._parser.registerCsiHandler({prefix:"?",intermediates:"$",final:"p"},(e=>this.requestMode(e,!1))),this._parser.setExecuteHandler(n.C0.BEL,(()=>this.bell())),this._parser.setExecuteHandler(n.C0.LF,(()=>this.lineFeed())),this._parser.setExecuteHandler(n.C0.VT,(()=>this.lineFeed())),this._parser.setExecuteHandler(n.C0.FF,(()=>this.lineFeed())),this._parser.setExecuteHandler(n.C0.CR,(()=>this.carriageReturn())),this._parser.setExecuteHandler(n.C0.BS,(()=>this.backspace())),this._parser.setExecuteHandler(n.C0.HT,(()=>this.tab())),this._parser.setExecuteHandler(n.C0.SO,(()=>this.shiftOut())),this._parser.setExecuteHandler(n.C0.SI,(()=>this.shiftIn())),this._parser.setExecuteHandler(n.C1.IND,(()=>this.index())),this._parser.setExecuteHandler(n.C1.NEL,(()=>this.nextLine())),this._parser.setExecuteHandler(n.C1.HTS,(()=>this.tabSet())),this._parser.registerOscHandler(0,new g.OscHandler((e=>(this.setTitle(e),this.setIconName(e),!0)))),this._parser.registerOscHandler(1,new g.OscHandler((e=>this.setIconName(e)))),this._parser.registerOscHandler(2,new g.OscHandler((e=>this.setTitle(e)))),this._parser.registerOscHandler(4,new g.OscHandler((e=>this.setOrReportIndexedColor(e)))),this._parser.registerOscHandler(8,new g.OscHandler((e=>this.setHyperlink(e)))),this._parser.registerOscHandler(10,new g.OscHandler((e=>this.setOrReportFgColor(e)))),this._parser.registerOscHandler(11,new g.OscHandler((e=>this.setOrReportBgColor(e)))),this._parser.registerOscHandler(12,new g.OscHandler((e=>this.setOrReportCursorColor(e)))),this._parser.registerOscHandler(104,new g.OscHandler((e=>this.restoreIndexedColor(e)))),this._parser.registerOscHandler(110,new g.OscHandler((e=>this.restoreFgColor(e)))),this._parser.registerOscHandler(111,new g.OscHandler((e=>this.restoreBgColor(e)))),this._parser.registerOscHandler(112,new g.OscHandler((e=>this.restoreCursorColor(e)))),this._parser.registerEscHandler({final:"7"},(()=>this.saveCursor())),this._parser.registerEscHandler({final:"8"},(()=>this.restoreCursor())),this._parser.registerEscHandler({final:"D"},(()=>this.index())),this._parser.registerEscHandler({final:"E"},(()=>this.nextLine())),this._parser.registerEscHandler({final:"H"},(()=>this.tabSet())),this._parser.registerEscHandler({final:"M"},(()=>this.reverseIndex())),this._parser.registerEscHandler({final:"="},(()=>this.keypadApplicationMode())),this._parser.registerEscHandler({final:">"},(()=>this.keypadNumericMode())),this._parser.registerEscHandler({final:"c"},(()=>this.fullReset())),this._parser.registerEscHandler({final:"n"},(()=>this.setgLevel(2))),this._parser.registerEscHandler({final:"o"},(()=>this.setgLevel(3))),this._parser.registerEscHandler({final:"|"},(()=>this.setgLevel(3))),this._parser.registerEscHandler({final:"}"},(()=>this.setgLevel(2))),this._parser.registerEscHandler({final:"~"},(()=>this.setgLevel(1))),this._parser.registerEscHandler({intermediates:"%",final:"@"},(()=>this.selectDefaultCharset())),this._parser.registerEscHandler({intermediates:"%",final:"G"},(()=>this.selectDefaultCharset()));for(const e in o.CHARSETS)this._parser.registerEscHandler({intermediates:"(",final:e},(()=>this.selectCharset("("+e))),this._parser.registerEscHandler({intermediates:")",final:e},(()=>this.selectCharset(")"+e))),this._parser.registerEscHandler({intermediates:"*",final:e},(()=>this.selectCharset("*"+e))),this._parser.registerEscHandler({intermediates:"+",final:e},(()=>this.selectCharset("+"+e))),this._parser.registerEscHandler({intermediates:"-",final:e},(()=>this.selectCharset("-"+e))),this._parser.registerEscHandler({intermediates:".",final:e},(()=>this.selectCharset("."+e))),this._parser.registerEscHandler({intermediates:"/",final:e},(()=>this.selectCharset("/"+e)));this._parser.registerEscHandler({intermediates:"#",final:"8"},(()=>this.screenAlignmentPattern())),this._parser.setErrorHandler((e=>(this._logService.error("Parsing error: ",e),e))),this._parser.registerDcsHandler({intermediates:"$",final:"q"},new m.DcsHandler(((e,t)=>this.requestStatusString(e,t))))}_preserveStack(e,t,i,s){this._parseStack.paused=!0,this._parseStack.cursorStartX=e,this._parseStack.cursorStartY=t,this._parseStack.decodedLength=i,this._parseStack.position=s}_logSlowResolvingAsync(e){this._logService.logLevel<=f.LogLevelEnum.WARN&&Promise.race([e,new Promise(((e,t)=>setTimeout((()=>t("#SLOW_TIMEOUT")),5e3)))]).catch((e=>{if("#SLOW_TIMEOUT"!==e)throw e;console.warn("async parser handler taking longer than 5000 ms")}))}_getCurrentLinkId(){return this._curAttrData.extended.urlId}parse(e,t){let i,s=this._activeBuffer.x,r=this._activeBuffer.y,n=0;const o=this._parseStack.paused;if(o){if(i=this._parser.parse(this._parseBuffer,this._parseStack.decodedLength,t))return this._logSlowResolvingAsync(i),i;s=this._parseStack.cursorStartX,r=this._parseStack.cursorStartY,this._parseStack.paused=!1,e.length>C&&(n=this._parseStack.position+C)}if(this._logService.logLevel<=f.LogLevelEnum.DEBUG&&this._logService.debug("parsing data "+("string"==typeof e?` "${e}"`:` "${Array.prototype.map.call(e,(e=>String.fromCharCode(e))).join("")}"`)),this._logService.logLevel===f.LogLevelEnum.TRACE&&this._logService.trace("parsing data (codes)","string"==typeof e?e.split("").map((e=>e.charCodeAt(0))):e),this._parseBuffer.length<e.length&&this._parseBuffer.length<C&&(this._parseBuffer=new Uint32Array(Math.min(e.length,C))),o||this._dirtyRowTracker.clearRange(),e.length>C)for(let t=n;t<e.length;t+=C){const n=t+C<e.length?t+C:e.length,o="string"==typeof e?this._stringDecoder.decode(e.substring(t,n),this._parseBuffer):this._utf8Decoder.decode(e.subarray(t,n),this._parseBuffer);if(i=this._parser.parse(this._parseBuffer,o))return this._preserveStack(s,r,o,t),this._logSlowResolvingAsync(i),i}else if(!o){const t="string"==typeof e?this._stringDecoder.decode(e,this._parseBuffer):this._utf8Decoder.decode(e,this._parseBuffer);if(i=this._parser.parse(this._parseBuffer,t))return this._preserveStack(s,r,t,0),this._logSlowResolvingAsync(i),i}this._activeBuffer.x===s&&this._activeBuffer.y===r||this._onCursorMove.fire();const a=this._dirtyRowTracker.end+(this._bufferService.buffer.ybase-this._bufferService.buffer.ydisp),l=this._dirtyRowTracker.start+(this._bufferService.buffer.ybase-this._bufferService.buffer.ydisp);l<this._bufferService.rows&&this._onRequestRefreshRows.fire({start:Math.min(l,this._bufferService.rows-1),end:Math.min(a,this._bufferService.rows-1)})}print(e,t,i){let s,r;const n=this._charsetService.charset,o=this._optionsService.rawOptions.screenReaderMode,a=this._bufferService.cols,l=this._coreService.decPrivateModes.wraparound,u=this._coreService.modes.insertMode,_=this._curAttrData;let f=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);this._dirtyRowTracker.markDirty(this._activeBuffer.y),this._activeBuffer.x&&i-t>0&&2===f.getWidth(this._activeBuffer.x-1)&&f.setCellFromCodepoint(this._activeBuffer.x-1,0,1,_);let g=this._parser.precedingJoinState;for(let m=t;m<i;++m){if(s=e[m],s<127&&n){const e=n[String.fromCharCode(s)];e&&(s=e.charCodeAt(0))}const t=this._unicodeService.charProperties(s,g);r=p.UnicodeService.extractWidth(t);const i=p.UnicodeService.extractShouldJoin(t),v=i?p.UnicodeService.extractWidth(g):0;if(g=t,o&&this._onA11yChar.fire((0,h.stringFromCodePoint)(s)),this._getCurrentLinkId()&&this._oscLinkService.addLineToLink(this._getCurrentLinkId(),this._activeBuffer.ybase+this._activeBuffer.y),this._activeBuffer.x+r-v>a)if(l){const e=f;let t=this._activeBuffer.x-v;for(this._activeBuffer.x=v,this._activeBuffer.y++,this._activeBuffer.y===this._activeBuffer.scrollBottom+1?(this._activeBuffer.y--,this._bufferService.scroll(this._eraseAttrData(),!0)):(this._activeBuffer.y>=this._bufferService.rows&&(this._activeBuffer.y=this._bufferService.rows-1),this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y).isWrapped=!0),f=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y),v>0&&f instanceof c.BufferLine&&f.copyCellsFrom(e,t,0,v,!1);t<a;)e.setCellFromCodepoint(t++,0,1,_)}else if(this._activeBuffer.x=a-1,2===r)continue;if(i&&this._activeBuffer.x){const e=f.getWidth(this._activeBuffer.x-1)?1:2;f.addCodepointToCell(this._activeBuffer.x-e,s,r);for(let e=r-v;--e>=0;)f.setCellFromCodepoint(this._activeBuffer.x++,0,0,_)}else if(u&&(f.insertCells(this._activeBuffer.x,r-v,this._activeBuffer.getNullCell(_)),2===f.getWidth(a-1)&&f.setCellFromCodepoint(a-1,d.NULL_CELL_CODE,d.NULL_CELL_WIDTH,_)),f.setCellFromCodepoint(this._activeBuffer.x++,s,r,_),r>0)for(;--r;)f.setCellFromCodepoint(this._activeBuffer.x++,0,0,_)}this._parser.precedingJoinState=g,this._activeBuffer.x<a&&i-t>0&&0===f.getWidth(this._activeBuffer.x)&&!f.hasContent(this._activeBuffer.x)&&f.setCellFromCodepoint(this._activeBuffer.x,0,1,_),this._dirtyRowTracker.markDirty(this._activeBuffer.y)}registerCsiHandler(e,t){return"t"!==e.final||e.prefix||e.intermediates?this._parser.registerCsiHandler(e,t):this._parser.registerCsiHandler(e,(e=>!y(e.params[0],this._optionsService.rawOptions.windowOptions)||t(e)))}registerDcsHandler(e,t){return this._parser.registerDcsHandler(e,new m.DcsHandler(t))}registerEscHandler(e,t){return this._parser.registerEscHandler(e,t)}registerOscHandler(e,t){return this._parser.registerOscHandler(e,new g.OscHandler(t))}bell(){return this._onRequestBell.fire(),!0}lineFeed(){return this._dirtyRowTracker.markDirty(this._activeBuffer.y),this._optionsService.rawOptions.convertEol&&(this._activeBuffer.x=0),this._activeBuffer.y++,this._activeBuffer.y===this._activeBuffer.scrollBottom+1?(this._activeBuffer.y--,this._bufferService.scroll(this._eraseAttrData())):this._activeBuffer.y>=this._bufferService.rows?this._activeBuffer.y=this._bufferService.rows-1:this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y).isWrapped=!1,this._activeBuffer.x>=this._bufferService.cols&&this._activeBuffer.x--,this._dirtyRowTracker.markDirty(this._activeBuffer.y),this._onLineFeed.fire(),!0}carriageReturn(){return this._activeBuffer.x=0,!0}backspace(){if(!this._coreService.decPrivateModes.reverseWraparound)return this._restrictCursor(),this._activeBuffer.x>0&&this._activeBuffer.x--,!0;if(this._restrictCursor(this._bufferService.cols),this._activeBuffer.x>0)this._activeBuffer.x--;else if(0===this._activeBuffer.x&&this._activeBuffer.y>this._activeBuffer.scrollTop&&this._activeBuffer.y<=this._activeBuffer.scrollBottom&&this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y)?.isWrapped){this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y).isWrapped=!1,this._activeBuffer.y--,this._activeBuffer.x=this._bufferService.cols-1;const e=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);e.hasWidth(this._activeBuffer.x)&&!e.hasContent(this._activeBuffer.x)&&this._activeBuffer.x--}return this._restrictCursor(),!0}tab(){if(this._activeBuffer.x>=this._bufferService.cols)return!0;const e=this._activeBuffer.x;return this._activeBuffer.x=this._activeBuffer.nextStop(),this._optionsService.rawOptions.screenReaderMode&&this._onA11yTab.fire(this._activeBuffer.x-e),!0}shiftOut(){return this._charsetService.setgLevel(1),!0}shiftIn(){return this._charsetService.setgLevel(0),!0}_restrictCursor(e=this._bufferService.cols-1){this._activeBuffer.x=Math.min(e,Math.max(0,this._activeBuffer.x)),this._activeBuffer.y=this._coreService.decPrivateModes.origin?Math.min(this._activeBuffer.scrollBottom,Math.max(this._activeBuffer.scrollTop,this._activeBuffer.y)):Math.min(this._bufferService.rows-1,Math.max(0,this._activeBuffer.y)),this._dirtyRowTracker.markDirty(this._activeBuffer.y)}_setCursor(e,t){this._dirtyRowTracker.markDirty(this._activeBuffer.y),this._coreService.decPrivateModes.origin?(this._activeBuffer.x=e,this._activeBuffer.y=this._activeBuffer.scrollTop+t):(this._activeBuffer.x=e,this._activeBuffer.y=t),this._restrictCursor(),this._dirtyRowTracker.markDirty(this._activeBuffer.y)}_moveCursor(e,t){this._restrictCursor(),this._setCursor(this._activeBuffer.x+e,this._activeBuffer.y+t)}cursorUp(e){const t=this._activeBuffer.y-this._activeBuffer.scrollTop;return t>=0?this._moveCursor(0,-Math.min(t,e.params[0]||1)):this._moveCursor(0,-(e.params[0]||1)),!0}cursorDown(e){const t=this._activeBuffer.scrollBottom-this._activeBuffer.y;return t>=0?this._moveCursor(0,Math.min(t,e.params[0]||1)):this._moveCursor(0,e.params[0]||1),!0}cursorForward(e){return this._moveCursor(e.params[0]||1,0),!0}cursorBackward(e){return this._moveCursor(-(e.params[0]||1),0),!0}cursorNextLine(e){return this.cursorDown(e),this._activeBuffer.x=0,!0}cursorPrecedingLine(e){return this.cursorUp(e),this._activeBuffer.x=0,!0}cursorCharAbsolute(e){return this._setCursor((e.params[0]||1)-1,this._activeBuffer.y),!0}cursorPosition(e){return this._setCursor(e.length>=2?(e.params[1]||1)-1:0,(e.params[0]||1)-1),!0}charPosAbsolute(e){return this._setCursor((e.params[0]||1)-1,this._activeBuffer.y),!0}hPositionRelative(e){return this._moveCursor(e.params[0]||1,0),!0}linePosAbsolute(e){return this._setCursor(this._activeBuffer.x,(e.params[0]||1)-1),!0}vPositionRelative(e){return this._moveCursor(0,e.params[0]||1),!0}hVPosition(e){return this.cursorPosition(e),!0}tabClear(e){const t=e.params[0];return 0===t?delete this._activeBuffer.tabs[this._activeBuffer.x]:3===t&&(this._activeBuffer.tabs={}),!0}cursorForwardTab(e){if(this._activeBuffer.x>=this._bufferService.cols)return!0;let t=e.params[0]||1;for(;t--;)this._activeBuffer.x=this._activeBuffer.nextStop();return!0}cursorBackwardTab(e){if(this._activeBuffer.x>=this._bufferService.cols)return!0;let t=e.params[0]||1;for(;t--;)this._activeBuffer.x=this._activeBuffer.prevStop();return!0}selectProtected(e){const t=e.params[0];return 1===t&&(this._curAttrData.bg|=536870912),2!==t&&0!==t||(this._curAttrData.bg&=-536870913),!0}_eraseInBufferLine(e,t,i,s=!1,r=!1){const n=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);n.replaceCells(t,i,this._activeBuffer.getNullCell(this._eraseAttrData()),r),s&&(n.isWrapped=!1)}_resetBufferLine(e,t=!1){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i&&(i.fill(this._activeBuffer.getNullCell(this._eraseAttrData()),t),this._bufferService.buffer.clearMarkers(this._activeBuffer.ybase+e),i.isWrapped=!1)}eraseInDisplay(e,t=!1){let i;switch(this._restrictCursor(this._bufferService.cols),e.params[0]){case 0:for(i=this._activeBuffer.y,this._dirtyRowTracker.markDirty(i),this._eraseInBufferLine(i++,this._activeBuffer.x,this._bufferService.cols,0===this._activeBuffer.x,t);i<this._bufferService.rows;i++)this._resetBufferLine(i,t);this._dirtyRowTracker.markDirty(i);break;case 1:for(i=this._activeBuffer.y,this._dirtyRowTracker.markDirty(i),this._eraseInBufferLine(i,0,this._activeBuffer.x+1,!0,t),this._activeBuffer.x+1>=this._bufferService.cols&&(this._activeBuffer.lines.get(i+1).isWrapped=!1);i--;)this._resetBufferLine(i,t);this._dirtyRowTracker.markDirty(0);break;case 2:if(this._optionsService.rawOptions.scrollOnEraseInDisplay){for(i=this._bufferService.rows,this._dirtyRowTracker.markRangeDirty(0,i-1);i--;){const e=this._activeBuffer.lines.get(this._activeBuffer.ybase+i);if(e?.getTrimmedLength())break}for(;i>=0;i--)this._bufferService.scroll(this._eraseAttrData())}else{for(i=this._bufferService.rows,this._dirtyRowTracker.markDirty(i-1);i--;)this._resetBufferLine(i,t);this._dirtyRowTracker.markDirty(0)}break;case 3:const e=this._activeBuffer.lines.length-this._bufferService.rows;e>0&&(this._activeBuffer.lines.trimStart(e),this._activeBuffer.ybase=Math.max(this._activeBuffer.ybase-e,0),this._activeBuffer.ydisp=Math.max(this._activeBuffer.ydisp-e,0),this._onScroll.fire(0))}return!0}eraseInLine(e,t=!1){switch(this._restrictCursor(this._bufferService.cols),e.params[0]){case 0:this._eraseInBufferLine(this._activeBuffer.y,this._activeBuffer.x,this._bufferService.cols,0===this._activeBuffer.x,t);break;case 1:this._eraseInBufferLine(this._activeBuffer.y,0,this._activeBuffer.x+1,!1,t);break;case 2:this._eraseInBufferLine(this._activeBuffer.y,0,this._bufferService.cols,!0,t)}return this._dirtyRowTracker.markDirty(this._activeBuffer.y),!0}insertLines(e){this._restrictCursor();let t=e.params[0]||1;if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const i=this._activeBuffer.ybase+this._activeBuffer.y,s=this._bufferService.rows-1-this._activeBuffer.scrollBottom,r=this._bufferService.rows-1+this._activeBuffer.ybase-s+1;for(;t--;)this._activeBuffer.lines.splice(r-1,1),this._activeBuffer.lines.splice(i,0,this._activeBuffer.getBlankLine(this._eraseAttrData()));return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.y,this._activeBuffer.scrollBottom),this._activeBuffer.x=0,!0}deleteLines(e){this._restrictCursor();let t=e.params[0]||1;if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const i=this._activeBuffer.ybase+this._activeBuffer.y;let s;for(s=this._bufferService.rows-1-this._activeBuffer.scrollBottom,s=this._bufferService.rows-1+this._activeBuffer.ybase-s;t--;)this._activeBuffer.lines.splice(i,1),this._activeBuffer.lines.splice(s,0,this._activeBuffer.getBlankLine(this._eraseAttrData()));return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.y,this._activeBuffer.scrollBottom),this._activeBuffer.x=0,!0}insertChars(e){this._restrictCursor();const t=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);return t&&(t.insertCells(this._activeBuffer.x,e.params[0]||1,this._activeBuffer.getNullCell(this._eraseAttrData())),this._dirtyRowTracker.markDirty(this._activeBuffer.y)),!0}deleteChars(e){this._restrictCursor();const t=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);return t&&(t.deleteCells(this._activeBuffer.x,e.params[0]||1,this._activeBuffer.getNullCell(this._eraseAttrData())),this._dirtyRowTracker.markDirty(this._activeBuffer.y)),!0}scrollUp(e){let t=e.params[0]||1;for(;t--;)this._activeBuffer.lines.splice(this._activeBuffer.ybase+this._activeBuffer.scrollTop,1),this._activeBuffer.lines.splice(this._activeBuffer.ybase+this._activeBuffer.scrollBottom,0,this._activeBuffer.getBlankLine(this._eraseAttrData()));return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}scrollDown(e){let t=e.params[0]||1;for(;t--;)this._activeBuffer.lines.splice(this._activeBuffer.ybase+this._activeBuffer.scrollBottom,1),this._activeBuffer.lines.splice(this._activeBuffer.ybase+this._activeBuffer.scrollTop,0,this._activeBuffer.getBlankLine(c.DEFAULT_ATTR_DATA));return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}scrollLeft(e){if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const t=e.params[0]||1;for(let e=this._activeBuffer.scrollTop;e<=this._activeBuffer.scrollBottom;++e){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i.deleteCells(0,t,this._activeBuffer.getNullCell(this._eraseAttrData())),i.isWrapped=!1}return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}scrollRight(e){if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const t=e.params[0]||1;for(let e=this._activeBuffer.scrollTop;e<=this._activeBuffer.scrollBottom;++e){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i.insertCells(0,t,this._activeBuffer.getNullCell(this._eraseAttrData())),i.isWrapped=!1}return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}insertColumns(e){if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const t=e.params[0]||1;for(let e=this._activeBuffer.scrollTop;e<=this._activeBuffer.scrollBottom;++e){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i.insertCells(this._activeBuffer.x,t,this._activeBuffer.getNullCell(this._eraseAttrData())),i.isWrapped=!1}return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}deleteColumns(e){if(this._activeBuffer.y>this._activeBuffer.scrollBottom||this._activeBuffer.y<this._activeBuffer.scrollTop)return!0;const t=e.params[0]||1;for(let e=this._activeBuffer.scrollTop;e<=this._activeBuffer.scrollBottom;++e){const i=this._activeBuffer.lines.get(this._activeBuffer.ybase+e);i.deleteCells(this._activeBuffer.x,t,this._activeBuffer.getNullCell(this._eraseAttrData())),i.isWrapped=!1}return this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom),!0}eraseChars(e){this._restrictCursor();const t=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y);return t&&(t.replaceCells(this._activeBuffer.x,this._activeBuffer.x+(e.params[0]||1),this._activeBuffer.getNullCell(this._eraseAttrData())),this._dirtyRowTracker.markDirty(this._activeBuffer.y)),!0}repeatPrecedingCharacter(e){const t=this._parser.precedingJoinState;if(!t)return!0;const i=e.params[0]||1,s=p.UnicodeService.extractWidth(t),r=this._activeBuffer.x-s,n=this._activeBuffer.lines.get(this._activeBuffer.ybase+this._activeBuffer.y).getString(r),o=new Uint32Array(n.length*i);let a=0;for(let e=0;e<n.length;){const t=n.codePointAt(e)||0;o[a++]=t,e+=t>65535?2:1}let l=a;for(let e=1;e<i;++e)o.copyWithin(l,0,a),l+=a;return this.print(o,0,l),!0}sendDeviceAttributesPrimary(e){return e.params[0]>0||(this._is("xterm")||this._is("rxvt-unicode")||this._is("screen")?this._coreService.triggerDataEvent(n.C0.ESC+"[?1;2c"):this._is("linux")&&this._coreService.triggerDataEvent(n.C0.ESC+"[?6c")),!0}sendDeviceAttributesSecondary(e){return e.params[0]>0||(this._is("xterm")?this._coreService.triggerDataEvent(n.C0.ESC+"[>0;276;0c"):this._is("rxvt-unicode")?this._coreService.triggerDataEvent(n.C0.ESC+"[>85;95;0c"):this._is("linux")?this._coreService.triggerDataEvent(e.params[0]+"c"):this._is("screen")&&this._coreService.triggerDataEvent(n.C0.ESC+"[>83;40003;0c")),!0}_is(e){return 0===(this._optionsService.rawOptions.termName+"").indexOf(e)}setMode(e){for(let t=0;t<e.length;t++)switch(e.params[t]){case 4:this._coreService.modes.insertMode=!0;break;case 20:this._optionsService.options.convertEol=!0}return!0}setModePrivate(e){for(let t=0;t<e.length;t++)switch(e.params[t]){case 1:this._coreService.decPrivateModes.applicationCursorKeys=!0;break;case 2:this._charsetService.setgCharset(0,o.DEFAULT_CHARSET),this._charsetService.setgCharset(1,o.DEFAULT_CHARSET),this._charsetService.setgCharset(2,o.DEFAULT_CHARSET),this._charsetService.setgCharset(3,o.DEFAULT_CHARSET);break;case 3:this._optionsService.rawOptions.windowOptions.setWinLines&&(this._bufferService.resize(132,this._bufferService.rows),this._onRequestReset.fire());break;case 6:this._coreService.decPrivateModes.origin=!0,this._setCursor(0,0);break;case 7:this._coreService.decPrivateModes.wraparound=!0;break;case 12:this._optionsService.options.cursorBlink=!0;break;case 45:this._coreService.decPrivateModes.reverseWraparound=!0;break;case 66:this._logService.debug("Serial port requested application keypad."),this._coreService.decPrivateModes.applicationKeypad=!0,this._onRequestSyncScrollBar.fire();break;case 9:this._coreMouseService.activeProtocol="X10";break;case 1e3:this._coreMouseService.activeProtocol="VT200";break;case 1002:this._coreMouseService.activeProtocol="DRAG";break;case 1003:this._coreMouseService.activeProtocol="ANY";break;case 1004:this._coreService.decPrivateModes.sendFocus=!0,this._onRequestSendFocus.fire();break;case 1005:this._logService.debug("DECSET 1005 not supported (see #2507)");break;case 1006:this._coreMouseService.activeEncoding="SGR";break;case 1015:this._logService.debug("DECSET 1015 not supported (see #2507)");break;case 1016:this._coreMouseService.activeEncoding="SGR_PIXELS";break;case 25:this._coreService.isCursorHidden=!1;break;case 1048:this.saveCursor();break;case 1049:this.saveCursor();case 47:case 1047:this._bufferService.buffers.activateAltBuffer(this._eraseAttrData()),this._coreService.isCursorInitialized=!0,this._onRequestRefreshRows.fire(void 0),this._onRequestSyncScrollBar.fire();break;case 2004:this._coreService.decPrivateModes.bracketedPasteMode=!0;break;case 2026:this._coreService.decPrivateModes.synchronizedOutput=!0}return!0}resetMode(e){for(let t=0;t<e.length;t++)switch(e.params[t]){case 4:this._coreService.modes.insertMode=!1;break;case 20:this._optionsService.options.convertEol=!1}return!0}resetModePrivate(e){for(let t=0;t<e.length;t++)switch(e.params[t]){case 1:this._coreService.decPrivateModes.applicationCursorKeys=!1;break;case 3:this._optionsService.rawOptions.windowOptions.setWinLines&&(this._bufferService.resize(80,this._bufferService.rows),this._onRequestReset.fire());break;case 6:this._coreService.decPrivateModes.origin=!1,this._setCursor(0,0);break;case 7:this._coreService.decPrivateModes.wraparound=!1;break;case 12:this._optionsService.options.cursorBlink=!1;break;case 45:this._coreService.decPrivateModes.reverseWraparound=!1;break;case 66:this._logService.debug("Switching back to normal keypad."),this._coreService.decPrivateModes.applicationKeypad=!1,this._onRequestSyncScrollBar.fire();break;case 9:case 1e3:case 1002:case 1003:this._coreMouseService.activeProtocol="NONE";break;case 1004:this._coreService.decPrivateModes.sendFocus=!1;break;case 1005:this._logService.debug("DECRST 1005 not supported (see #2507)");break;case 1006:case 1016:this._coreMouseService.activeEncoding="DEFAULT";break;case 1015:this._logService.debug("DECRST 1015 not supported (see #2507)");break;case 25:this._coreService.isCursorHidden=!0;break;case 1048:this.restoreCursor();break;case 1049:case 47:case 1047:this._bufferService.buffers.activateNormalBuffer(),1049===e.params[t]&&this.restoreCursor(),this._coreService.isCursorInitialized=!0,this._onRequestRefreshRows.fire(void 0),this._onRequestSyncScrollBar.fire();break;case 2004:this._coreService.decPrivateModes.bracketedPasteMode=!1;break;case 2026:this._coreService.decPrivateModes.synchronizedOutput=!1,this._onRequestRefreshRows.fire(void 0)}return!0}requestMode(e,t){const i=this._coreService.decPrivateModes,{activeProtocol:s,activeEncoding:r}=this._coreMouseService,o=this._coreService,{buffers:a,cols:l}=this._bufferService,{active:h,alt:c}=a,d=this._optionsService.rawOptions,u=e=>e?1:2,_=e.params[0];return f=_,p=t?2===_?4:4===_?u(o.modes.insertMode):12===_?3:20===_?u(d.convertEol):0:1===_?u(i.applicationCursorKeys):3===_?d.windowOptions.setWinLines?80===l?2:132===l?1:0:0:6===_?u(i.origin):7===_?u(i.wraparound):8===_?3:9===_?u("X10"===s):12===_?u(d.cursorBlink):25===_?u(!o.isCursorHidden):45===_?u(i.reverseWraparound):66===_?u(i.applicationKeypad):67===_?4:1e3===_?u("VT200"===s):1002===_?u("DRAG"===s):1003===_?u("ANY"===s):1004===_?u(i.sendFocus):1005===_?4:1006===_?u("SGR"===r):1015===_?4:1016===_?u("SGR_PIXELS"===r):1048===_?1:47===_||1047===_||1049===_?u(h===c):2004===_?u(i.bracketedPasteMode):2026===_?u(i.synchronizedOutput):0,o.triggerDataEvent(`${n.C0.ESC}[${t?"":"?"}${f};${p}$y`),!0;var f,p}_updateAttrColor(e,t,i,s,r){return 2===t?(e|=50331648,e&=-16777216,e|=_.AttributeData.fromColorRGB([i,s,r])):5===t&&(e&=-50331904,e|=33554432|255&i),e}_extractColor(e,t,i){const s=[0,0,-1,0,0,0];let r=0,n=0;do{if(s[n+r]=e.params[t+n],e.hasSubParams(t+n)){const i=e.getSubParams(t+n);let o=0;do{5===s[1]&&(r=1),s[n+o+1+r]=i[o]}while(++o<i.length&&o+n+1+r<s.length);break}if(5===s[1]&&n+r>=2||2===s[1]&&n+r>=5)break;s[1]&&(r=1)}while(++n+t<e.length&&n+r<s.length);for(let e=2;e<s.length;++e)-1===s[e]&&(s[e]=0);switch(s[0]){case 38:i.fg=this._updateAttrColor(i.fg,s[1],s[3],s[4],s[5]);break;case 48:i.bg=this._updateAttrColor(i.bg,s[1],s[3],s[4],s[5]);break;case 58:i.extended=i.extended.clone(),i.extended.underlineColor=this._updateAttrColor(i.extended.underlineColor,s[1],s[3],s[4],s[5])}return n}_processUnderline(e,t){t.extended=t.extended.clone(),(!~e||e>5)&&(e=1),t.extended.underlineStyle=e,t.fg|=268435456,0===e&&(t.fg&=-268435457),t.updateExtended()}_processSGR0(e){e.fg=c.DEFAULT_ATTR_DATA.fg,e.bg=c.DEFAULT_ATTR_DATA.bg,e.extended=e.extended.clone(),e.extended.underlineStyle=0,e.extended.underlineColor&=-67108864,e.updateExtended()}charAttributes(e){if(1===e.length&&0===e.params[0])return this._processSGR0(this._curAttrData),!0;const t=e.length;let i;const s=this._curAttrData;for(let r=0;r<t;r++)i=e.params[r],i>=30&&i<=37?(s.fg&=-50331904,s.fg|=16777216|i-30):i>=40&&i<=47?(s.bg&=-50331904,s.bg|=16777216|i-40):i>=90&&i<=97?(s.fg&=-50331904,s.fg|=16777224|i-90):i>=100&&i<=107?(s.bg&=-50331904,s.bg|=16777224|i-100):0===i?this._processSGR0(s):1===i?s.fg|=134217728:3===i?s.bg|=67108864:4===i?(s.fg|=268435456,this._processUnderline(e.hasSubParams(r)?e.getSubParams(r)[0]:1,s)):5===i?s.fg|=536870912:7===i?s.fg|=67108864:8===i?s.fg|=1073741824:9===i?s.fg|=2147483648:2===i?s.bg|=134217728:21===i?this._processUnderline(2,s):22===i?(s.fg&=-134217729,s.bg&=-134217729):23===i?s.bg&=-67108865:24===i?(s.fg&=-268435457,this._processUnderline(0,s)):25===i?s.fg&=-536870913:27===i?s.fg&=-67108865:28===i?s.fg&=-1073741825:29===i?s.fg&=2147483647:39===i?(s.fg&=-67108864,s.fg|=16777215&c.DEFAULT_ATTR_DATA.fg):49===i?(s.bg&=-67108864,s.bg|=16777215&c.DEFAULT_ATTR_DATA.bg):38===i||48===i||58===i?r+=this._extractColor(e,r,s):53===i?s.bg|=1073741824:55===i?s.bg&=-1073741825:59===i?(s.extended=s.extended.clone(),s.extended.underlineColor=-1,s.updateExtended()):100===i?(s.fg&=-67108864,s.fg|=16777215&c.DEFAULT_ATTR_DATA.fg,s.bg&=-67108864,s.bg|=16777215&c.DEFAULT_ATTR_DATA.bg):this._logService.debug("Unknown SGR attribute: %d.",i);return!0}deviceStatus(e){switch(e.params[0]){case 5:this._coreService.triggerDataEvent(`${n.C0.ESC}[0n`);break;case 6:const e=this._activeBuffer.y+1,t=this._activeBuffer.x+1;this._coreService.triggerDataEvent(`${n.C0.ESC}[${e};${t}R`)}return!0}deviceStatusPrivate(e){if(6===e.params[0]){const e=this._activeBuffer.y+1,t=this._activeBuffer.x+1;this._coreService.triggerDataEvent(`${n.C0.ESC}[?${e};${t}R`)}return!0}softReset(e){return this._coreService.isCursorHidden=!1,this._onRequestSyncScrollBar.fire(),this._activeBuffer.scrollTop=0,this._activeBuffer.scrollBottom=this._bufferService.rows-1,this._curAttrData=c.DEFAULT_ATTR_DATA.clone(),this._coreService.reset(),this._charsetService.reset(),this._activeBuffer.savedX=0,this._activeBuffer.savedY=this._activeBuffer.ybase,this._activeBuffer.savedCurAttrData.fg=this._curAttrData.fg,this._activeBuffer.savedCurAttrData.bg=this._curAttrData.bg,this._activeBuffer.savedCharset=this._charsetService.charset,this._coreService.decPrivateModes.origin=!1,!0}setCursorStyle(e){const t=0===e.length?1:e.params[0];if(0===t)this._coreService.decPrivateModes.cursorStyle=void 0,this._coreService.decPrivateModes.cursorBlink=void 0;else{switch(t){case 1:case 2:this._coreService.decPrivateModes.cursorStyle="block";break;case 3:case 4:this._coreService.decPrivateModes.cursorStyle="underline";break;case 5:case 6:this._coreService.decPrivateModes.cursorStyle="bar"}const e=t%2==1;this._coreService.decPrivateModes.cursorBlink=e}return!0}setScrollRegion(e){const t=e.params[0]||1;let i;return(e.length<2||(i=e.params[1])>this._bufferService.rows||0===i)&&(i=this._bufferService.rows),i>t&&(this._activeBuffer.scrollTop=t-1,this._activeBuffer.scrollBottom=i-1,this._setCursor(0,0)),!0}windowOptions(e){if(!y(e.params[0],this._optionsService.rawOptions.windowOptions))return!0;const t=e.length>1?e.params[1]:0;switch(e.params[0]){case 14:2!==t&&this._onRequestWindowsOptionsReport.fire(w.GET_WIN_SIZE_PIXELS);break;case 16:this._onRequestWindowsOptionsReport.fire(w.GET_CELL_SIZE_PIXELS);break;case 18:this._bufferService&&this._coreService.triggerDataEvent(`${n.C0.ESC}[8;${this._bufferService.rows};${this._bufferService.cols}t`);break;case 22:0!==t&&2!==t||(this._windowTitleStack.push(this._windowTitle),this._windowTitleStack.length>10&&this._windowTitleStack.shift()),0!==t&&1!==t||(this._iconNameStack.push(this._iconName),this._iconNameStack.length>10&&this._iconNameStack.shift());break;case 23:0!==t&&2!==t||this._windowTitleStack.length&&this.setTitle(this._windowTitleStack.pop()),0!==t&&1!==t||this._iconNameStack.length&&this.setIconName(this._iconNameStack.pop())}return!0}saveCursor(e){return this._activeBuffer.savedX=this._activeBuffer.x,this._activeBuffer.savedY=this._activeBuffer.ybase+this._activeBuffer.y,this._activeBuffer.savedCurAttrData.fg=this._curAttrData.fg,this._activeBuffer.savedCurAttrData.bg=this._curAttrData.bg,this._activeBuffer.savedCharset=this._charsetService.charset,!0}restoreCursor(e){return this._activeBuffer.x=this._activeBuffer.savedX||0,this._activeBuffer.y=Math.max(this._activeBuffer.savedY-this._activeBuffer.ybase,0),this._curAttrData.fg=this._activeBuffer.savedCurAttrData.fg,this._curAttrData.bg=this._activeBuffer.savedCurAttrData.bg,this._charsetService.charset=this._savedCharset,this._activeBuffer.savedCharset&&(this._charsetService.charset=this._activeBuffer.savedCharset),this._restrictCursor(),!0}setTitle(e){return this._windowTitle=e,this._onTitleChange.fire(e),!0}setIconName(e){return this._iconName=e,!0}setOrReportIndexedColor(e){const t=[],i=e.split(";");for(;i.length>1;){const e=i.shift(),s=i.shift();if(/^\\d+$/.exec(e)){const i=parseInt(e);if(R(i))if("?"===s)t.push({type:0,index:i});else{const e=(0,v.parseColor)(s);e&&t.push({type:1,index:i,color:e})}}}return t.length&&this._onColor.fire(t),!0}setHyperlink(e){const t=e.indexOf(";");if(-1===t)return!0;const i=e.slice(0,t).trim(),s=e.slice(t+1);return s?this._createHyperlink(i,s):!i.trim()&&this._finishHyperlink()}_createHyperlink(e,t){this._getCurrentLinkId()&&this._finishHyperlink();const i=e.split(":");let s;const r=i.findIndex((e=>e.startsWith("id=")));return-1!==r&&(s=i[r].slice(3)||void 0),this._curAttrData.extended=this._curAttrData.extended.clone(),this._curAttrData.extended.urlId=this._oscLinkService.registerLink({id:s,uri:t}),this._curAttrData.updateExtended(),!0}_finishHyperlink(){return this._curAttrData.extended=this._curAttrData.extended.clone(),this._curAttrData.extended.urlId=0,this._curAttrData.updateExtended(),!0}_setOrReportSpecialColor(e,t){const i=e.split(";");for(let e=0;e<i.length&&!(t>=this._specialColors.length);++e,++t)if("?"===i[e])this._onColor.fire([{type:0,index:this._specialColors[t]}]);else{const s=(0,v.parseColor)(i[e]);s&&this._onColor.fire([{type:1,index:this._specialColors[t],color:s}])}return!0}setOrReportFgColor(e){return this._setOrReportSpecialColor(e,0)}setOrReportBgColor(e){return this._setOrReportSpecialColor(e,1)}setOrReportCursorColor(e){return this._setOrReportSpecialColor(e,2)}restoreIndexedColor(e){if(!e)return this._onColor.fire([{type:2}]),!0;const t=[],i=e.split(";");for(let e=0;e<i.length;++e)if(/^\\d+$/.exec(i[e])){const s=parseInt(i[e]);R(s)&&t.push({type:2,index:s})}return t.length&&this._onColor.fire(t),!0}restoreFgColor(e){return this._onColor.fire([{type:2,index:256}]),!0}restoreBgColor(e){return this._onColor.fire([{type:2,index:257}]),!0}restoreCursorColor(e){return this._onColor.fire([{type:2,index:258}]),!0}nextLine(){return this._activeBuffer.x=0,this.index(),!0}keypadApplicationMode(){return this._logService.debug("Serial port requested application keypad."),this._coreService.decPrivateModes.applicationKeypad=!0,this._onRequestSyncScrollBar.fire(),!0}keypadNumericMode(){return this._logService.debug("Switching back to normal keypad."),this._coreService.decPrivateModes.applicationKeypad=!1,this._onRequestSyncScrollBar.fire(),!0}selectDefaultCharset(){return this._charsetService.setgLevel(0),this._charsetService.setgCharset(0,o.DEFAULT_CHARSET),!0}selectCharset(e){return 2!==e.length?(this.selectDefaultCharset(),!0):("/"===e[0]||this._charsetService.setgCharset(b[e[0]],o.CHARSETS[e[1]]||o.DEFAULT_CHARSET),!0)}index(){return this._restrictCursor(),this._activeBuffer.y++,this._activeBuffer.y===this._activeBuffer.scrollBottom+1?(this._activeBuffer.y--,this._bufferService.scroll(this._eraseAttrData())):this._activeBuffer.y>=this._bufferService.rows&&(this._activeBuffer.y=this._bufferService.rows-1),this._restrictCursor(),!0}tabSet(){return this._activeBuffer.tabs[this._activeBuffer.x]=!0,!0}reverseIndex(){if(this._restrictCursor(),this._activeBuffer.y===this._activeBuffer.scrollTop){const e=this._activeBuffer.scrollBottom-this._activeBuffer.scrollTop;this._activeBuffer.lines.shiftElements(this._activeBuffer.ybase+this._activeBuffer.y,e,1),this._activeBuffer.lines.set(this._activeBuffer.ybase+this._activeBuffer.y,this._activeBuffer.getBlankLine(this._eraseAttrData())),this._dirtyRowTracker.markRangeDirty(this._activeBuffer.scrollTop,this._activeBuffer.scrollBottom)}else this._activeBuffer.y--,this._restrictCursor();return!0}fullReset(){return this._parser.reset(),this._onRequestReset.fire(),!0}reset(){this._curAttrData=c.DEFAULT_ATTR_DATA.clone(),this._eraseAttrDataInternal=c.DEFAULT_ATTR_DATA.clone()}_eraseAttrData(){return this._eraseAttrDataInternal.bg&=-67108864,this._eraseAttrDataInternal.bg|=67108863&this._curAttrData.bg,this._eraseAttrDataInternal}setgLevel(e){return this._charsetService.setgLevel(e),!0}screenAlignmentPattern(){const e=new u.CellData;e.content=1<<22|"E".charCodeAt(0),e.fg=this._curAttrData.fg,e.bg=this._curAttrData.bg,this._setCursor(0,0);for(let t=0;t<this._bufferService.rows;++t){const i=this._activeBuffer.ybase+this._activeBuffer.y+t,s=this._activeBuffer.lines.get(i);s&&(s.fill(e),s.isWrapped=!1)}return this._dirtyRowTracker.markAllDirty(),this._setCursor(0,0),!0}requestStatusString(e,t){const i=this._bufferService.buffer,s=this._optionsService.rawOptions;return(e=>(this._coreService.triggerDataEvent(`${n.C0.ESC}${e}${n.C0.ESC}\\\\`),!0))(\'"q\'===e?`P1$r${this._curAttrData.isProtected()?1:0}"q`:\'"p\'===e?\'P1$r61;1"p\':"r"===e?`P1$r${i.scrollTop+1};${i.scrollBottom+1}r`:"m"===e?"P1$r0m":" q"===e?`P1$r${{block:2,underline:4,bar:6}[s.cursorStyle]-(s.cursorBlink?1:0)} q`:"P0$r")}markRangeDirty(e,t){this._dirtyRowTracker.markRangeDirty(e,t)}}t.InputHandler=D;let L=class{constructor(e){this._bufferService=e,this.clearRange()}clearRange(){this.start=this._bufferService.buffer.y,this.end=this._bufferService.buffer.y}markDirty(e){e<this.start?this.start=e:e>this.end&&(this.end=e)}markRangeDirty(e,t){e>t&&(E=e,e=t,t=E),e<this.start&&(this.start=e),t>this.end&&(this.end=t)}markAllDirty(){this.markRangeDirty(0,this._bufferService.rows-1)}};function R(e){return 0<=e&&e<256}L=s([r(0,f.IBufferService)],L)},7710:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.FourKeyMap=t.TwoKeyMap=void 0;class i{constructor(){this._data={}}set(e,t,i){this._data[e]||(this._data[e]={}),this._data[e][t]=i}get(e,t){return this._data[e]?this._data[e][t]:void 0}clear(){this._data={}}}t.TwoKeyMap=i,t.FourKeyMap=class{constructor(){this._data=new i}set(e,t,s,r,n){this._data.get(e,t)||this._data.set(e,t,new i),this._data.get(e,t).set(s,r,n)}get(e,t,i,s){return this._data.get(e,t)?.get(i,s)}clear(){this._data.clear()}}},701:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.isChromeOS=t.isLinux=t.isWindows=t.isIphone=t.isIpad=t.isMac=t.isSafari=t.isLegacyEdge=t.isFirefox=t.isNode=void 0,t.getSafariVersion=function(){if(!t.isSafari)return 0;const e=i.match(/Version\\/(\\d+)/);return null===e||e.length<2?0:parseInt(e[1])},t.isNode="undefined"!=typeof process&&"title"in process;const i=t.isNode?"node":navigator.userAgent,s=t.isNode?"node":navigator.platform;t.isFirefox=i.includes("Firefox"),t.isLegacyEdge=i.includes("Edge"),t.isSafari=/^((?!chrome|android).)*safari/i.test(i),t.isMac=["Macintosh","MacIntel","MacPPC","Mac68K"].includes(s),t.isIpad="iPad"===s,t.isIphone="iPhone"===s,t.isWindows=["Windows","Win16","Win32","WinCE"].includes(s),t.isLinux=s.indexOf("Linux")>=0,t.isChromeOS=/\\bCrOS\\b/.test(i)},3087:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.SortedList=void 0;const s=i(6168);let r=0;t.SortedList=class{constructor(e){this._getKey=e,this._array=[],this._insertedValues=[],this._flushInsertedTask=new s.IdleTaskQueue,this._isFlushingInserted=!1,this._deletedIndices=[],this._flushDeletedTask=new s.IdleTaskQueue,this._isFlushingDeleted=!1}clear(){this._array.length=0,this._insertedValues.length=0,this._flushInsertedTask.clear(),this._isFlushingInserted=!1,this._deletedIndices.length=0,this._flushDeletedTask.clear(),this._isFlushingDeleted=!1}insert(e){this._flushCleanupDeleted(),0===this._insertedValues.length&&this._flushInsertedTask.enqueue((()=>this._flushInserted())),this._insertedValues.push(e)}_flushInserted(){const e=this._insertedValues.sort(((e,t)=>this._getKey(e)-this._getKey(t)));let t=0,i=0;const s=new Array(this._array.length+this._insertedValues.length);for(let r=0;r<s.length;r++)i>=this._array.length||this._getKey(e[t])<=this._getKey(this._array[i])?(s[r]=e[t],t++):s[r]=this._array[i++];this._array=s,this._insertedValues.length=0}_flushCleanupInserted(){!this._isFlushingInserted&&this._insertedValues.length>0&&this._flushInsertedTask.flush()}delete(e){if(this._flushCleanupInserted(),0===this._array.length)return!1;const t=this._getKey(e);if(void 0===t)return!1;if(r=this._search(t),-1===r)return!1;if(this._getKey(this._array[r])!==t)return!1;do{if(this._array[r]===e)return 0===this._deletedIndices.length&&this._flushDeletedTask.enqueue((()=>this._flushDeleted())),this._deletedIndices.push(r),!0}while(++r<this._array.length&&this._getKey(this._array[r])===t);return!1}_flushDeleted(){this._isFlushingDeleted=!0;const e=this._deletedIndices.sort(((e,t)=>e-t));let t=0;const i=new Array(this._array.length-e.length);let s=0;for(let r=0;r<this._array.length;r++)e[t]===r?t++:i[s++]=this._array[r];this._array=i,this._deletedIndices.length=0,this._isFlushingDeleted=!1}_flushCleanupDeleted(){!this._isFlushingDeleted&&this._deletedIndices.length>0&&this._flushDeletedTask.flush()}*getKeyIterator(e){if(this._flushCleanupInserted(),this._flushCleanupDeleted(),0!==this._array.length&&(r=this._search(e),!(r<0||r>=this._array.length)&&this._getKey(this._array[r])===e))do{yield this._array[r]}while(++r<this._array.length&&this._getKey(this._array[r])===e)}forEachByKey(e,t){if(this._flushCleanupInserted(),this._flushCleanupDeleted(),0!==this._array.length&&(r=this._search(e),!(r<0||r>=this._array.length)&&this._getKey(this._array[r])===e))do{t(this._array[r])}while(++r<this._array.length&&this._getKey(this._array[r])===e)}values(){return this._flushCleanupInserted(),this._flushCleanupDeleted(),[...this._array].values()}_search(e){let t=0,i=this._array.length-1;for(;i>=t;){let s=t+i>>1;const r=this._getKey(this._array[s]);if(r>e)i=s-1;else{if(!(r<e)){for(;s>0&&this._getKey(this._array[s-1])===e;)s--;return s}t=s+1}}return t}}},6168:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DebouncedIdleTask=t.IdleTaskQueue=t.PriorityTaskQueue=void 0;const s=i(701);class r{constructor(){this._tasks=[],this._i=0}enqueue(e){this._tasks.push(e),this._start()}flush(){for(;this._i<this._tasks.length;)this._tasks[this._i]()||this._i++;this.clear()}clear(){this._idleCallback&&(this._cancelCallback(this._idleCallback),this._idleCallback=void 0),this._i=0,this._tasks.length=0}_start(){this._idleCallback||(this._idleCallback=this._requestCallback(this._process.bind(this)))}_process(e){this._idleCallback=void 0;let t=0,i=0,s=e.timeRemaining(),r=0;for(;this._i<this._tasks.length;){if(t=performance.now(),this._tasks[this._i]()||this._i++,t=Math.max(1,performance.now()-t),i=Math.max(t,i),r=e.timeRemaining(),1.5*i>r)return s-t<-20&&console.warn(`task queue exceeded allotted deadline by ${Math.abs(Math.round(s-t))}ms`),void this._start();s=r}this.clear()}}class n extends r{_requestCallback(e){return setTimeout((()=>e(this._createDeadline(16))))}_cancelCallback(e){clearTimeout(e)}_createDeadline(e){const t=performance.now()+e;return{timeRemaining:()=>Math.max(0,t-performance.now())}}}t.PriorityTaskQueue=n,t.IdleTaskQueue=!s.isNode&&"requestIdleCallback"in window?class extends r{_requestCallback(e){return requestIdleCallback(e)}_cancelCallback(e){cancelIdleCallback(e)}}:n,t.DebouncedIdleTask=class{constructor(){this._queue=new t.IdleTaskQueue}set(e){this._queue.clear(),this._queue.enqueue(e)}flush(){this._queue.flush()}}},5882:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.updateWindowsModeWrappedState=function(e){const t=e.buffer.lines.get(e.buffer.ybase+e.buffer.y-1),i=t?.get(e.cols-1),r=e.buffer.lines.get(e.buffer.ybase+e.buffer.y);r&&i&&(r.isWrapped=i[s.CHAR_DATA_CODE_INDEX]!==s.NULL_CELL_CODE&&i[s.CHAR_DATA_CODE_INDEX]!==s.WHITESPACE_CELL_CODE)};const s=i(8938)},5451:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ExtendedAttrs=t.AttributeData=void 0;class i{constructor(){this.fg=0,this.bg=0,this.extended=new s}static toColorRGB(e){return[e>>>16&255,e>>>8&255,255&e]}static fromColorRGB(e){return(255&e[0])<<16|(255&e[1])<<8|255&e[2]}clone(){const e=new i;return e.fg=this.fg,e.bg=this.bg,e.extended=this.extended.clone(),e}isInverse(){return 67108864&this.fg}isBold(){return 134217728&this.fg}isUnderline(){return this.hasExtendedAttrs()&&0!==this.extended.underlineStyle?1:268435456&this.fg}isBlink(){return 536870912&this.fg}isInvisible(){return 1073741824&this.fg}isItalic(){return 67108864&this.bg}isDim(){return 134217728&this.bg}isStrikethrough(){return 2147483648&this.fg}isProtected(){return 536870912&this.bg}isOverline(){return 1073741824&this.bg}getFgColorMode(){return 50331648&this.fg}getBgColorMode(){return 50331648&this.bg}isFgRGB(){return!(50331648&~this.fg)}isBgRGB(){return!(50331648&~this.bg)}isFgPalette(){return 16777216==(50331648&this.fg)||33554432==(50331648&this.fg)}isBgPalette(){return 16777216==(50331648&this.bg)||33554432==(50331648&this.bg)}isFgDefault(){return!(50331648&this.fg)}isBgDefault(){return!(50331648&this.bg)}isAttributeDefault(){return 0===this.fg&&0===this.bg}getFgColor(){switch(50331648&this.fg){case 16777216:case 33554432:return 255&this.fg;case 50331648:return 16777215&this.fg;default:return-1}}getBgColor(){switch(50331648&this.bg){case 16777216:case 33554432:return 255&this.bg;case 50331648:return 16777215&this.bg;default:return-1}}hasExtendedAttrs(){return 268435456&this.bg}updateExtended(){this.extended.isEmpty()?this.bg&=-268435457:this.bg|=268435456}getUnderlineColor(){if(268435456&this.bg&&~this.extended.underlineColor)switch(50331648&this.extended.underlineColor){case 16777216:case 33554432:return 255&this.extended.underlineColor;case 50331648:return 16777215&this.extended.underlineColor;default:return this.getFgColor()}return this.getFgColor()}getUnderlineColorMode(){return 268435456&this.bg&&~this.extended.underlineColor?50331648&this.extended.underlineColor:this.getFgColorMode()}isUnderlineColorRGB(){return 268435456&this.bg&&~this.extended.underlineColor?!(50331648&~this.extended.underlineColor):this.isFgRGB()}isUnderlineColorPalette(){return 268435456&this.bg&&~this.extended.underlineColor?16777216==(50331648&this.extended.underlineColor)||33554432==(50331648&this.extended.underlineColor):this.isFgPalette()}isUnderlineColorDefault(){return 268435456&this.bg&&~this.extended.underlineColor?!(50331648&this.extended.underlineColor):this.isFgDefault()}getUnderlineStyle(){return 268435456&this.fg?268435456&this.bg?this.extended.underlineStyle:1:0}getUnderlineVariantOffset(){return this.extended.underlineVariantOffset}}t.AttributeData=i;class s{get ext(){return this._urlId?-469762049&this._ext|this.underlineStyle<<26:this._ext}set ext(e){this._ext=e}get underlineStyle(){return this._urlId?5:(469762048&this._ext)>>26}set underlineStyle(e){this._ext&=-469762049,this._ext|=e<<26&469762048}get underlineColor(){return 67108863&this._ext}set underlineColor(e){this._ext&=-67108864,this._ext|=67108863&e}get urlId(){return this._urlId}set urlId(e){this._urlId=e}get underlineVariantOffset(){const e=(3758096384&this._ext)>>29;return e<0?4294967288^e:e}set underlineVariantOffset(e){this._ext&=536870911,this._ext|=e<<29&3758096384}constructor(e=0,t=0){this._ext=0,this._urlId=0,this._ext=e,this._urlId=t}clone(){return new s(this._ext,this._urlId)}isEmpty(){return 0===this.underlineStyle&&0===this._urlId}}t.ExtendedAttrs=s},1073:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Buffer=t.MAX_BUFFER_SIZE=void 0;const s=i(5639),r=i(6168),n=i(5451),o=i(6107),a=i(732),l=i(3055),h=i(8938),c=i(8158),d=i(6760);t.MAX_BUFFER_SIZE=4294967295,t.Buffer=class{constructor(e,t,i){this._hasScrollback=e,this._optionsService=t,this._bufferService=i,this.ydisp=0,this.ybase=0,this.y=0,this.x=0,this.tabs={},this.savedY=0,this.savedX=0,this.savedCurAttrData=o.DEFAULT_ATTR_DATA.clone(),this.savedCharset=d.DEFAULT_CHARSET,this.markers=[],this._nullCell=l.CellData.fromCharData([0,h.NULL_CELL_CHAR,h.NULL_CELL_WIDTH,h.NULL_CELL_CODE]),this._whitespaceCell=l.CellData.fromCharData([0,h.WHITESPACE_CELL_CHAR,h.WHITESPACE_CELL_WIDTH,h.WHITESPACE_CELL_CODE]),this._isClearing=!1,this._memoryCleanupQueue=new r.IdleTaskQueue,this._memoryCleanupPosition=0,this._cols=this._bufferService.cols,this._rows=this._bufferService.rows,this.lines=new s.CircularList(this._getCorrectBufferLength(this._rows)),this.scrollTop=0,this.scrollBottom=this._rows-1,this.setupTabStops()}getNullCell(e){return e?(this._nullCell.fg=e.fg,this._nullCell.bg=e.bg,this._nullCell.extended=e.extended):(this._nullCell.fg=0,this._nullCell.bg=0,this._nullCell.extended=new n.ExtendedAttrs),this._nullCell}getWhitespaceCell(e){return e?(this._whitespaceCell.fg=e.fg,this._whitespaceCell.bg=e.bg,this._whitespaceCell.extended=e.extended):(this._whitespaceCell.fg=0,this._whitespaceCell.bg=0,this._whitespaceCell.extended=new n.ExtendedAttrs),this._whitespaceCell}getBlankLine(e,t){return new o.BufferLine(this._bufferService.cols,this.getNullCell(e),t)}get hasScrollback(){return this._hasScrollback&&this.lines.maxLength>this._rows}get isCursorInViewport(){const e=this.ybase+this.y-this.ydisp;return e>=0&&e<this._rows}_getCorrectBufferLength(e){if(!this._hasScrollback)return e;const i=e+this._optionsService.rawOptions.scrollback;return i>t.MAX_BUFFER_SIZE?t.MAX_BUFFER_SIZE:i}fillViewportRows(e){if(0===this.lines.length){void 0===e&&(e=o.DEFAULT_ATTR_DATA);let t=this._rows;for(;t--;)this.lines.push(this.getBlankLine(e))}}clear(){this.ydisp=0,this.ybase=0,this.y=0,this.x=0,this.lines=new s.CircularList(this._getCorrectBufferLength(this._rows)),this.scrollTop=0,this.scrollBottom=this._rows-1,this.setupTabStops()}resize(e,t){const i=this.getNullCell(o.DEFAULT_ATTR_DATA);let s=0;const r=this._getCorrectBufferLength(t);if(r>this.lines.maxLength&&(this.lines.maxLength=r),this.lines.length>0){if(this._cols<e)for(let t=0;t<this.lines.length;t++)s+=+this.lines.get(t).resize(e,i);let n=0;if(this._rows<t)for(let s=this._rows;s<t;s++)this.lines.length<t+this.ybase&&(this._optionsService.rawOptions.windowsMode||void 0!==this._optionsService.rawOptions.windowsPty.backend||void 0!==this._optionsService.rawOptions.windowsPty.buildNumber?this.lines.push(new o.BufferLine(e,i)):this.ybase>0&&this.lines.length<=this.ybase+this.y+n+1?(this.ybase--,n++,this.ydisp>0&&this.ydisp--):this.lines.push(new o.BufferLine(e,i)));else for(let e=this._rows;e>t;e--)this.lines.length>t+this.ybase&&(this.lines.length>this.ybase+this.y+1?this.lines.pop():(this.ybase++,this.ydisp++));if(r<this.lines.maxLength){const e=this.lines.length-r;e>0&&(this.lines.trimStart(e),this.ybase=Math.max(this.ybase-e,0),this.ydisp=Math.max(this.ydisp-e,0),this.savedY=Math.max(this.savedY-e,0)),this.lines.maxLength=r}this.x=Math.min(this.x,e-1),this.y=Math.min(this.y,t-1),n&&(this.y+=n),this.savedX=Math.min(this.savedX,e-1),this.scrollTop=0}if(this.scrollBottom=t-1,this._isReflowEnabled&&(this._reflow(e,t),this._cols>e))for(let t=0;t<this.lines.length;t++)s+=+this.lines.get(t).resize(e,i);this._cols=e,this._rows=t,this._memoryCleanupQueue.clear(),s>.1*this.lines.length&&(this._memoryCleanupPosition=0,this._memoryCleanupQueue.enqueue((()=>this._batchedMemoryCleanup())))}_batchedMemoryCleanup(){let e=!0;this._memoryCleanupPosition>=this.lines.length&&(this._memoryCleanupPosition=0,e=!1);let t=0;for(;this._memoryCleanupPosition<this.lines.length;)if(t+=this.lines.get(this._memoryCleanupPosition++).cleanupMemory(),t>100)return!0;return e}get _isReflowEnabled(){const e=this._optionsService.rawOptions.windowsPty;return e&&e.buildNumber?this._hasScrollback&&"conpty"===e.backend&&e.buildNumber>=21376:this._hasScrollback&&!this._optionsService.rawOptions.windowsMode}_reflow(e,t){this._cols!==e&&(e>this._cols?this._reflowLarger(e,t):this._reflowSmaller(e,t))}_reflowLarger(e,t){const i=this._optionsService.rawOptions.reflowCursorLine,s=(0,a.reflowLargerGetLinesToRemove)(this.lines,this._cols,e,this.ybase+this.y,this.getNullCell(o.DEFAULT_ATTR_DATA),i);if(s.length>0){const i=(0,a.reflowLargerCreateNewLayout)(this.lines,s);(0,a.reflowLargerApplyNewLayout)(this.lines,i.layout),this._reflowLargerAdjustViewport(e,t,i.countRemoved)}}_reflowLargerAdjustViewport(e,t,i){const s=this.getNullCell(o.DEFAULT_ATTR_DATA);let r=i;for(;r-- >0;)0===this.ybase?(this.y>0&&this.y--,this.lines.length<t&&this.lines.push(new o.BufferLine(e,s))):(this.ydisp===this.ybase&&this.ydisp--,this.ybase--);this.savedY=Math.max(this.savedY-i,0)}_reflowSmaller(e,t){const i=this._optionsService.rawOptions.reflowCursorLine,s=this.getNullCell(o.DEFAULT_ATTR_DATA),r=[];let n=0;for(let l=this.lines.length-1;l>=0;l--){let h=this.lines.get(l);if(!h||!h.isWrapped&&h.getTrimmedLength()<=e)continue;const c=[h];for(;h.isWrapped&&l>0;)h=this.lines.get(--l),c.unshift(h);if(!i){const e=this.ybase+this.y;if(e>=l&&e<l+c.length)continue}const d=c[c.length-1].getTrimmedLength(),u=(0,a.reflowSmallerGetNewLineLengths)(c,this._cols,e),_=u.length-c.length;let f;f=0===this.ybase&&this.y!==this.lines.length-1?Math.max(0,this.y-this.lines.maxLength+_):Math.max(0,this.lines.length-this.lines.maxLength+_);const p=[];for(let e=0;e<_;e++){const e=this.getBlankLine(o.DEFAULT_ATTR_DATA,!0);p.push(e)}p.length>0&&(r.push({start:l+c.length+n,newLines:p}),n+=p.length),c.push(...p);let g=u.length-1,m=u[g];0===m&&(g--,m=u[g]);let v=c.length-_-1,S=d;for(;v>=0;){const e=Math.min(S,m);if(void 0===c[g])break;if(c[g].copyCellsFrom(c[v],S-e,m-e,e,!0),m-=e,0===m&&(g--,m=u[g]),S-=e,0===S){v--;const e=Math.max(v,0);S=(0,a.getWrappedLineTrimmedLength)(c,e,this._cols)}}for(let t=0;t<c.length;t++)u[t]<e&&c[t].setCell(u[t],s);let b=_-f;for(;b-- >0;)0===this.ybase?this.y<t-1?(this.y++,this.lines.pop()):(this.ybase++,this.ydisp++):this.ybase<Math.min(this.lines.maxLength,this.lines.length+n)-t&&(this.ybase===this.ydisp&&this.ydisp++,this.ybase++);this.savedY=Math.min(this.savedY+_,this.ybase+t-1)}if(r.length>0){const e=[],t=[];for(let e=0;e<this.lines.length;e++)t.push(this.lines.get(e));const i=this.lines.length;let s=i-1,o=0,a=r[o];this.lines.length=Math.min(this.lines.maxLength,this.lines.length+n);let l=0;for(let h=Math.min(this.lines.maxLength-1,i+n-1);h>=0;h--)if(a&&a.start>s+l){for(let e=a.newLines.length-1;e>=0;e--)this.lines.set(h--,a.newLines[e]);h++,e.push({index:s+1,amount:a.newLines.length}),l+=a.newLines.length,a=r[++o]}else this.lines.set(h,t[s--]);let h=0;for(let t=e.length-1;t>=0;t--)e[t].index+=h,this.lines.onInsertEmitter.fire(e[t]),h+=e[t].amount;const c=Math.max(0,i+n-this.lines.maxLength);c>0&&this.lines.onTrimEmitter.fire(c)}}translateBufferLineToString(e,t,i=0,s){const r=this.lines.get(e);return r?r.translateToString(t,i,s):""}getWrappedRangeForLine(e){let t=e,i=e;for(;t>0&&this.lines.get(t).isWrapped;)t--;for(;i+1<this.lines.length&&this.lines.get(i+1).isWrapped;)i++;return{first:t,last:i}}setupTabStops(e){for(null!=e?this.tabs[e]||(e=this.prevStop(e)):(this.tabs={},e=0);e<this._cols;e+=this._optionsService.rawOptions.tabStopWidth)this.tabs[e]=!0}prevStop(e){for(null==e&&(e=this.x);!this.tabs[--e]&&e>0;);return e>=this._cols?this._cols-1:e<0?0:e}nextStop(e){for(null==e&&(e=this.x);!this.tabs[++e]&&e<this._cols;);return e>=this._cols?this._cols-1:e<0?0:e}clearMarkers(e){this._isClearing=!0;for(let t=0;t<this.markers.length;t++)this.markers[t].line===e&&(this.markers[t].dispose(),this.markers.splice(t--,1));this._isClearing=!1}clearAllMarkers(){this._isClearing=!0;for(let e=0;e<this.markers.length;e++)this.markers[e].dispose();this.markers.length=0,this._isClearing=!1}addMarker(e){const t=new c.Marker(e);return this.markers.push(t),t.register(this.lines.onTrim((e=>{t.line-=e,t.line<0&&t.dispose()}))),t.register(this.lines.onInsert((e=>{t.line>=e.index&&(t.line+=e.amount)}))),t.register(this.lines.onDelete((e=>{t.line>=e.index&&t.line<e.index+e.amount&&t.dispose(),t.line>e.index&&(t.line-=e.amount)}))),t.register(t.onDispose((()=>this._removeMarker(t)))),t}_removeMarker(e){this._isClearing||this.markers.splice(this.markers.indexOf(e),1)}}},6107:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferLine=t.DEFAULT_ATTR_DATA=void 0;const s=i(5451),r=i(3055),n=i(8938),o=i(726);t.DEFAULT_ATTR_DATA=Object.freeze(new s.AttributeData);let a=0;class l{constructor(e,t,i=!1){this.isWrapped=i,this._combined={},this._extendedAttrs={},this._data=new Uint32Array(3*e);const s=t||r.CellData.fromCharData([0,n.NULL_CELL_CHAR,n.NULL_CELL_WIDTH,n.NULL_CELL_CODE]);for(let t=0;t<e;++t)this.setCell(t,s);this.length=e}get(e){const t=this._data[3*e+0],i=2097151&t;return[this._data[3*e+1],2097152&t?this._combined[e]:i?(0,o.stringFromCodePoint)(i):"",t>>22,2097152&t?this._combined[e].charCodeAt(this._combined[e].length-1):i]}set(e,t){this._data[3*e+1]=t[n.CHAR_DATA_ATTR_INDEX],t[n.CHAR_DATA_CHAR_INDEX].length>1?(this._combined[e]=t[1],this._data[3*e+0]=2097152|e|t[n.CHAR_DATA_WIDTH_INDEX]<<22):this._data[3*e+0]=t[n.CHAR_DATA_CHAR_INDEX].charCodeAt(0)|t[n.CHAR_DATA_WIDTH_INDEX]<<22}getWidth(e){return this._data[3*e+0]>>22}hasWidth(e){return 12582912&this._data[3*e+0]}getFg(e){return this._data[3*e+1]}getBg(e){return this._data[3*e+2]}hasContent(e){return 4194303&this._data[3*e+0]}getCodePoint(e){const t=this._data[3*e+0];return 2097152&t?this._combined[e].charCodeAt(this._combined[e].length-1):2097151&t}isCombined(e){return 2097152&this._data[3*e+0]}getString(e){const t=this._data[3*e+0];return 2097152&t?this._combined[e]:2097151&t?(0,o.stringFromCodePoint)(2097151&t):""}isProtected(e){return 536870912&this._data[3*e+2]}loadCell(e,t){return a=3*e,t.content=this._data[a+0],t.fg=this._data[a+1],t.bg=this._data[a+2],2097152&t.content&&(t.combinedData=this._combined[e]),268435456&t.bg&&(t.extended=this._extendedAttrs[e]),t}setCell(e,t){2097152&t.content&&(this._combined[e]=t.combinedData),268435456&t.bg&&(this._extendedAttrs[e]=t.extended),this._data[3*e+0]=t.content,this._data[3*e+1]=t.fg,this._data[3*e+2]=t.bg}setCellFromCodepoint(e,t,i,s){268435456&s.bg&&(this._extendedAttrs[e]=s.extended),this._data[3*e+0]=t|i<<22,this._data[3*e+1]=s.fg,this._data[3*e+2]=s.bg}addCodepointToCell(e,t,i){let s=this._data[3*e+0];2097152&s?this._combined[e]+=(0,o.stringFromCodePoint)(t):2097151&s?(this._combined[e]=(0,o.stringFromCodePoint)(2097151&s)+(0,o.stringFromCodePoint)(t),s&=-2097152,s|=2097152):s=t|1<<22,i&&(s&=-12582913,s|=i<<22),this._data[3*e+0]=s}insertCells(e,t,i){if((e%=this.length)&&2===this.getWidth(e-1)&&this.setCellFromCodepoint(e-1,0,1,i),t<this.length-e){const s=new r.CellData;for(let i=this.length-e-t-1;i>=0;--i)this.setCell(e+t+i,this.loadCell(e+i,s));for(let s=0;s<t;++s)this.setCell(e+s,i)}else for(let t=e;t<this.length;++t)this.setCell(t,i);2===this.getWidth(this.length-1)&&this.setCellFromCodepoint(this.length-1,0,1,i)}deleteCells(e,t,i){if(e%=this.length,t<this.length-e){const s=new r.CellData;for(let i=0;i<this.length-e-t;++i)this.setCell(e+i,this.loadCell(e+t+i,s));for(let e=this.length-t;e<this.length;++e)this.setCell(e,i)}else for(let t=e;t<this.length;++t)this.setCell(t,i);e&&2===this.getWidth(e-1)&&this.setCellFromCodepoint(e-1,0,1,i),0!==this.getWidth(e)||this.hasContent(e)||this.setCellFromCodepoint(e,0,1,i)}replaceCells(e,t,i,s=!1){if(s)for(e&&2===this.getWidth(e-1)&&!this.isProtected(e-1)&&this.setCellFromCodepoint(e-1,0,1,i),t<this.length&&2===this.getWidth(t-1)&&!this.isProtected(t)&&this.setCellFromCodepoint(t,0,1,i);e<t&&e<this.length;)this.isProtected(e)||this.setCell(e,i),e++;else for(e&&2===this.getWidth(e-1)&&this.setCellFromCodepoint(e-1,0,1,i),t<this.length&&2===this.getWidth(t-1)&&this.setCellFromCodepoint(t,0,1,i);e<t&&e<this.length;)this.setCell(e++,i)}resize(e,t){if(e===this.length)return 4*this._data.length*2<this._data.buffer.byteLength;const i=3*e;if(e>this.length){if(this._data.buffer.byteLength>=4*i)this._data=new Uint32Array(this._data.buffer,0,i);else{const e=new Uint32Array(i);e.set(this._data),this._data=e}for(let i=this.length;i<e;++i)this.setCell(i,t)}else{this._data=this._data.subarray(0,i);const t=Object.keys(this._combined);for(let i=0;i<t.length;i++){const s=parseInt(t[i],10);s>=e&&delete this._combined[s]}const s=Object.keys(this._extendedAttrs);for(let t=0;t<s.length;t++){const i=parseInt(s[t],10);i>=e&&delete this._extendedAttrs[i]}}return this.length=e,4*i*2<this._data.buffer.byteLength}cleanupMemory(){if(4*this._data.length*2<this._data.buffer.byteLength){const e=new Uint32Array(this._data.length);return e.set(this._data),this._data=e,1}return 0}fill(e,t=!1){if(t)for(let t=0;t<this.length;++t)this.isProtected(t)||this.setCell(t,e);else{this._combined={},this._extendedAttrs={};for(let t=0;t<this.length;++t)this.setCell(t,e)}}copyFrom(e){this.length!==e.length?this._data=new Uint32Array(e._data):this._data.set(e._data),this.length=e.length,this._combined={};for(const t in e._combined)this._combined[t]=e._combined[t];this._extendedAttrs={};for(const t in e._extendedAttrs)this._extendedAttrs[t]=e._extendedAttrs[t];this.isWrapped=e.isWrapped}clone(){const e=new l(0);e._data=new Uint32Array(this._data),e.length=this.length;for(const t in this._combined)e._combined[t]=this._combined[t];for(const t in this._extendedAttrs)e._extendedAttrs[t]=this._extendedAttrs[t];return e.isWrapped=this.isWrapped,e}getTrimmedLength(){for(let e=this.length-1;e>=0;--e)if(4194303&this._data[3*e+0])return e+(this._data[3*e+0]>>22);return 0}getNoBgTrimmedLength(){for(let e=this.length-1;e>=0;--e)if(4194303&this._data[3*e+0]||50331648&this._data[3*e+2])return e+(this._data[3*e+0]>>22);return 0}copyCellsFrom(e,t,i,s,r){const n=e._data;if(r)for(let r=s-1;r>=0;r--){for(let e=0;e<3;e++)this._data[3*(i+r)+e]=n[3*(t+r)+e];268435456&n[3*(t+r)+2]&&(this._extendedAttrs[i+r]=e._extendedAttrs[t+r])}else for(let r=0;r<s;r++){for(let e=0;e<3;e++)this._data[3*(i+r)+e]=n[3*(t+r)+e];268435456&n[3*(t+r)+2]&&(this._extendedAttrs[i+r]=e._extendedAttrs[t+r])}const o=Object.keys(e._combined);for(let s=0;s<o.length;s++){const r=parseInt(o[s],10);r>=t&&(this._combined[r-t+i]=e._combined[r])}}translateToString(e,t,i,s){t=t??0,i=i??this.length,e&&(i=Math.min(i,this.getTrimmedLength())),s&&(s.length=0);let r="";for(;t<i;){const e=this._data[3*t+0],i=2097151&e,a=2097152&e?this._combined[t]:i?(0,o.stringFromCodePoint)(i):n.WHITESPACE_CELL_CHAR;if(r+=a,s)for(let e=0;e<a.length;++e)s.push(t);t+=e>>22||1}return s&&s.push(t),r}}t.BufferLine=l},9384:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.getRangeLength=function(e,t){if(e.start.y>e.end.y)throw new Error(`Buffer range end (${e.end.x}, ${e.end.y}) cannot be before start (${e.start.x}, ${e.start.y})`);return t*(e.end.y-e.start.y)+(e.end.x-e.start.x+1)}},732:(e,t)=>{function i(e,t,i){if(t===e.length-1)return e[t].getTrimmedLength();const s=!e[t].hasContent(i-1)&&1===e[t].getWidth(i-1),r=2===e[t+1].getWidth(0);return s&&r?i-1:i}Object.defineProperty(t,"__esModule",{value:!0}),t.reflowLargerGetLinesToRemove=function(e,t,s,r,n,o){const a=[];for(let l=0;l<e.length-1;l++){let h=l,c=e.get(++h);if(!c.isWrapped)continue;const d=[e.get(l)];for(;h<e.length&&c.isWrapped;)d.push(c),c=e.get(++h);if(!o&&r>=l&&r<h){l+=d.length-1;continue}let u=0,_=i(d,u,t),f=1,p=0;for(;f<d.length;){const e=i(d,f,t),r=e-p,o=s-_,a=Math.min(r,o);d[u].copyCellsFrom(d[f],p,_,a,!1),_+=a,_===s&&(u++,_=0),p+=a,p===e&&(f++,p=0),0===_&&0!==u&&2===d[u-1].getWidth(s-1)&&(d[u].copyCellsFrom(d[u-1],s-1,_++,1,!1),d[u-1].setCell(s-1,n))}d[u].replaceCells(_,s,n);let g=0;for(let e=d.length-1;e>0&&(e>u||0===d[e].getTrimmedLength());e--)g++;g>0&&(a.push(l+d.length-g),a.push(g)),l+=d.length-1}return a},t.reflowLargerCreateNewLayout=function(e,t){const i=[];let s=0,r=t[s],n=0;for(let o=0;o<e.length;o++)if(r===o){const i=t[++s];e.onDeleteEmitter.fire({index:o-n,amount:i}),o+=i-1,n+=i,r=t[++s]}else i.push(o);return{layout:i,countRemoved:n}},t.reflowLargerApplyNewLayout=function(e,t){const i=[];for(let s=0;s<t.length;s++)i.push(e.get(t[s]));for(let t=0;t<i.length;t++)e.set(t,i[t]);e.length=t.length},t.reflowSmallerGetNewLineLengths=function(e,t,s){const r=[],n=e.map(((s,r)=>i(e,r,t))).reduce(((e,t)=>e+t));let o=0,a=0,l=0;for(;l<n;){if(n-l<s){r.push(n-l);break}o+=s;const h=i(e,a,t);o>h&&(o-=h,a++);const c=2===e[a].getWidth(o-1);c&&o--;const d=c?s-1:s;r.push(d),l+=d}return r},t.getWrappedLineTrimmedLength=i},4097:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferSet=void 0;const s=i(7150),r=i(1073),n=i(802);class o extends s.Disposable{constructor(e,t){super(),this._optionsService=e,this._bufferService=t,this._onBufferActivate=this._register(new n.Emitter),this.onBufferActivate=this._onBufferActivate.event,this.reset(),this._register(this._optionsService.onSpecificOptionChange("scrollback",(()=>this.resize(this._bufferService.cols,this._bufferService.rows)))),this._register(this._optionsService.onSpecificOptionChange("tabStopWidth",(()=>this.setupTabStops())))}reset(){this._normal=new r.Buffer(!0,this._optionsService,this._bufferService),this._normal.fillViewportRows(),this._alt=new r.Buffer(!1,this._optionsService,this._bufferService),this._activeBuffer=this._normal,this._onBufferActivate.fire({activeBuffer:this._normal,inactiveBuffer:this._alt}),this.setupTabStops()}get alt(){return this._alt}get active(){return this._activeBuffer}get normal(){return this._normal}activateNormalBuffer(){this._activeBuffer!==this._normal&&(this._normal.x=this._alt.x,this._normal.y=this._alt.y,this._alt.clearAllMarkers(),this._alt.clear(),this._activeBuffer=this._normal,this._onBufferActivate.fire({activeBuffer:this._normal,inactiveBuffer:this._alt}))}activateAltBuffer(e){this._activeBuffer!==this._alt&&(this._alt.fillViewportRows(e),this._alt.x=this._normal.x,this._alt.y=this._normal.y,this._activeBuffer=this._alt,this._onBufferActivate.fire({activeBuffer:this._alt,inactiveBuffer:this._normal}))}resize(e,t){this._normal.resize(e,t),this._alt.resize(e,t),this.setupTabStops(e)}setupTabStops(e){this._normal.setupTabStops(e),this._alt.setupTabStops(e)}}t.BufferSet=o},3055:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CellData=void 0;const s=i(726),r=i(8938),n=i(5451);class o extends n.AttributeData{constructor(){super(...arguments),this.content=0,this.fg=0,this.bg=0,this.extended=new n.ExtendedAttrs,this.combinedData=""}static fromCharData(e){const t=new o;return t.setFromCharData(e),t}isCombined(){return 2097152&this.content}getWidth(){return this.content>>22}getChars(){return 2097152&this.content?this.combinedData:2097151&this.content?(0,s.stringFromCodePoint)(2097151&this.content):""}getCode(){return this.isCombined()?this.combinedData.charCodeAt(this.combinedData.length-1):2097151&this.content}setFromCharData(e){this.fg=e[r.CHAR_DATA_ATTR_INDEX],this.bg=0;let t=!1;if(e[r.CHAR_DATA_CHAR_INDEX].length>2)t=!0;else if(2===e[r.CHAR_DATA_CHAR_INDEX].length){const i=e[r.CHAR_DATA_CHAR_INDEX].charCodeAt(0);if(55296<=i&&i<=56319){const s=e[r.CHAR_DATA_CHAR_INDEX].charCodeAt(1);56320<=s&&s<=57343?this.content=1024*(i-55296)+s-56320+65536|e[r.CHAR_DATA_WIDTH_INDEX]<<22:t=!0}else t=!0}else this.content=e[r.CHAR_DATA_CHAR_INDEX].charCodeAt(0)|e[r.CHAR_DATA_WIDTH_INDEX]<<22;t&&(this.combinedData=e[r.CHAR_DATA_CHAR_INDEX],this.content=2097152|e[r.CHAR_DATA_WIDTH_INDEX]<<22)}getAsCharData(){return[this.fg,this.getChars(),this.getWidth(),this.getCode()]}}t.CellData=o},8938:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.WHITESPACE_CELL_CODE=t.WHITESPACE_CELL_WIDTH=t.WHITESPACE_CELL_CHAR=t.NULL_CELL_CODE=t.NULL_CELL_WIDTH=t.NULL_CELL_CHAR=t.CHAR_DATA_CODE_INDEX=t.CHAR_DATA_WIDTH_INDEX=t.CHAR_DATA_CHAR_INDEX=t.CHAR_DATA_ATTR_INDEX=t.DEFAULT_EXT=t.DEFAULT_ATTR=t.DEFAULT_COLOR=void 0,t.DEFAULT_COLOR=0,t.DEFAULT_ATTR=t.DEFAULT_COLOR<<9|256,t.DEFAULT_EXT=0,t.CHAR_DATA_ATTR_INDEX=0,t.CHAR_DATA_CHAR_INDEX=1,t.CHAR_DATA_WIDTH_INDEX=2,t.CHAR_DATA_CODE_INDEX=3,t.NULL_CELL_CHAR="",t.NULL_CELL_WIDTH=1,t.NULL_CELL_CODE=0,t.WHITESPACE_CELL_CHAR=" ",t.WHITESPACE_CELL_WIDTH=1,t.WHITESPACE_CELL_CODE=32},8158:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Marker=void 0;const s=i(802),r=i(7150);class n{get id(){return this._id}constructor(e){this.line=e,this.isDisposed=!1,this._disposables=[],this._id=n._nextId++,this._onDispose=this.register(new s.Emitter),this.onDispose=this._onDispose.event}dispose(){this.isDisposed||(this.isDisposed=!0,this.line=-1,this._onDispose.fire(),(0,r.dispose)(this._disposables),this._disposables.length=0)}register(e){return this._disposables.push(e),e}}t.Marker=n,n._nextId=1},6760:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DEFAULT_CHARSET=t.CHARSETS=void 0,t.CHARSETS={},t.DEFAULT_CHARSET=t.CHARSETS.B,t.CHARSETS[0]={"`":"\u25C6",a:"\u2592",b:"\u2409",c:"\u240C",d:"\u240D",e:"\u240A",f:"\xB0",g:"\xB1",h:"\u2424",i:"\u240B",j:"\u2518",k:"\u2510",l:"\u250C",m:"\u2514",n:"\u253C",o:"\u23BA",p:"\u23BB",q:"\u2500",r:"\u23BC",s:"\u23BD",t:"\u251C",u:"\u2524",v:"\u2534",w:"\u252C",x:"\u2502",y:"\u2264",z:"\u2265","{":"\u03C0","|":"\u2260","}":"\xA3","~":"\xB7"},t.CHARSETS.A={"#":"\xA3"},t.CHARSETS.B=void 0,t.CHARSETS[4]={"#":"\xA3","@":"\xBE","[":"ij","\\\\":"\xBD","]":"|","{":"\xA8","|":"f","}":"\xBC","~":"\xB4"},t.CHARSETS.C=t.CHARSETS[5]={"[":"\xC4","\\\\":"\xD6","]":"\xC5","^":"\xDC","`":"\xE9","{":"\xE4","|":"\xF6","}":"\xE5","~":"\xFC"},t.CHARSETS.R={"#":"\xA3","@":"\xE0","[":"\xB0","\\\\":"\xE7","]":"\xA7","{":"\xE9","|":"\xF9","}":"\xE8","~":"\xA8"},t.CHARSETS.Q={"@":"\xE0","[":"\xE2","\\\\":"\xE7","]":"\xEA","^":"\xEE","`":"\xF4","{":"\xE9","|":"\xF9","}":"\xE8","~":"\xFB"},t.CHARSETS.K={"@":"\xA7","[":"\xC4","\\\\":"\xD6","]":"\xDC","{":"\xE4","|":"\xF6","}":"\xFC","~":"\xDF"},t.CHARSETS.Y={"#":"\xA3","@":"\xA7","[":"\xB0","\\\\":"\xE7","]":"\xE9","`":"\xF9","{":"\xE0","|":"\xF2","}":"\xE8","~":"\xEC"},t.CHARSETS.E=t.CHARSETS[6]={"@":"\xC4","[":"\xC6","\\\\":"\xD8","]":"\xC5","^":"\xDC","`":"\xE4","{":"\xE6","|":"\xF8","}":"\xE5","~":"\xFC"},t.CHARSETS.Z={"#":"\xA3","@":"\xA7","[":"\xA1","\\\\":"\xD1","]":"\xBF","{":"\xB0","|":"\xF1","}":"\xE7"},t.CHARSETS.H=t.CHARSETS[7]={"@":"\xC9","[":"\xC4","\\\\":"\xD6","]":"\xC5","^":"\xDC","`":"\xE9","{":"\xE4","|":"\xF6","}":"\xE5","~":"\xFC"},t.CHARSETS["="]={"#":"\xF9","@":"\xE0","[":"\xE9","\\\\":"\xE7","]":"\xEA","^":"\xEE",_:"\xE8","`":"\xF4","{":"\xE4","|":"\xF6","}":"\xFC","~":"\xFB"}},3534:(e,t)=>{var i,s,r;Object.defineProperty(t,"__esModule",{value:!0}),t.C1_ESCAPED=t.C1=t.C0=void 0,function(e){e.NUL="\\0",e.SOH="",e.STX="",e.ETX="",e.EOT="",e.ENQ="",e.ACK="",e.BEL="\x07",e.BS="\\b",e.HT="\\t",e.LF="\\n",e.VT="\\v",e.FF="\\f",e.CR="\\r",e.SO="",e.SI="",e.DLE="",e.DC1="",e.DC2="",e.DC3="",e.DC4="",e.NAK="",e.SYN="",e.ETB="",e.CAN="",e.EM="",e.SUB="",e.ESC="\x1B",e.FS="",e.GS="",e.RS="",e.US="",e.SP=" ",e.DEL="\x7F"}(i||(t.C0=i={})),function(e){e.PAD="\x80",e.HOP="\x81",e.BPH="\x82",e.NBH="\x83",e.IND="\x84",e.NEL="\x85",e.SSA="\x86",e.ESA="\x87",e.HTS="\x88",e.HTJ="\x89",e.VTS="\x8A",e.PLD="\x8B",e.PLU="\x8C",e.RI="\x8D",e.SS2="\x8E",e.SS3="\x8F",e.DCS="\x90",e.PU1="\x91",e.PU2="\x92",e.STS="\x93",e.CCH="\x94",e.MW="\x95",e.SPA="\x96",e.EPA="\x97",e.SOS="\x98",e.SGCI="\x99",e.SCI="\x9A",e.CSI="\x9B",e.ST="\x9C",e.OSC="\x9D",e.PM="\x9E",e.APC="\x9F"}(s||(t.C1=s={})),function(e){e.ST=`${i.ESC}\\\\`}(r||(t.C1_ESCAPED=r={}))},706:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.evaluateKeyboardEvent=function(e,t,i,n){const o={type:0,cancel:!1,key:void 0},a=(e.shiftKey?1:0)|(e.altKey?2:0)|(e.ctrlKey?4:0)|(e.metaKey?8:0);switch(e.keyCode){case 0:"UIKeyInputUpArrow"===e.key?o.key=t?s.C0.ESC+"OA":s.C0.ESC+"[A":"UIKeyInputLeftArrow"===e.key?o.key=t?s.C0.ESC+"OD":s.C0.ESC+"[D":"UIKeyInputRightArrow"===e.key?o.key=t?s.C0.ESC+"OC":s.C0.ESC+"[C":"UIKeyInputDownArrow"===e.key&&(o.key=t?s.C0.ESC+"OB":s.C0.ESC+"[B");break;case 8:o.key=e.ctrlKey?"\\b":s.C0.DEL,e.altKey&&(o.key=s.C0.ESC+o.key);break;case 9:if(e.shiftKey){o.key=s.C0.ESC+"[Z";break}o.key=s.C0.HT,o.cancel=!0;break;case 13:o.key=e.altKey?s.C0.ESC+s.C0.CR:s.C0.CR,o.cancel=!0;break;case 27:o.key=s.C0.ESC,e.altKey&&(o.key=s.C0.ESC+s.C0.ESC),o.cancel=!0;break;case 37:if(e.metaKey)break;o.key=a?s.C0.ESC+"[1;"+(a+1)+"D":t?s.C0.ESC+"OD":s.C0.ESC+"[D";break;case 39:if(e.metaKey)break;o.key=a?s.C0.ESC+"[1;"+(a+1)+"C":t?s.C0.ESC+"OC":s.C0.ESC+"[C";break;case 38:if(e.metaKey)break;o.key=a?s.C0.ESC+"[1;"+(a+1)+"A":t?s.C0.ESC+"OA":s.C0.ESC+"[A";break;case 40:if(e.metaKey)break;o.key=a?s.C0.ESC+"[1;"+(a+1)+"B":t?s.C0.ESC+"OB":s.C0.ESC+"[B";break;case 45:e.shiftKey||e.ctrlKey||(o.key=s.C0.ESC+"[2~");break;case 46:o.key=a?s.C0.ESC+"[3;"+(a+1)+"~":s.C0.ESC+"[3~";break;case 36:o.key=a?s.C0.ESC+"[1;"+(a+1)+"H":t?s.C0.ESC+"OH":s.C0.ESC+"[H";break;case 35:o.key=a?s.C0.ESC+"[1;"+(a+1)+"F":t?s.C0.ESC+"OF":s.C0.ESC+"[F";break;case 33:e.shiftKey?o.type=2:e.ctrlKey?o.key=s.C0.ESC+"[5;"+(a+1)+"~":o.key=s.C0.ESC+"[5~";break;case 34:e.shiftKey?o.type=3:e.ctrlKey?o.key=s.C0.ESC+"[6;"+(a+1)+"~":o.key=s.C0.ESC+"[6~";break;case 112:o.key=a?s.C0.ESC+"[1;"+(a+1)+"P":s.C0.ESC+"OP";break;case 113:o.key=a?s.C0.ESC+"[1;"+(a+1)+"Q":s.C0.ESC+"OQ";break;case 114:o.key=a?s.C0.ESC+"[1;"+(a+1)+"R":s.C0.ESC+"OR";break;case 115:o.key=a?s.C0.ESC+"[1;"+(a+1)+"S":s.C0.ESC+"OS";break;case 116:o.key=a?s.C0.ESC+"[15;"+(a+1)+"~":s.C0.ESC+"[15~";break;case 117:o.key=a?s.C0.ESC+"[17;"+(a+1)+"~":s.C0.ESC+"[17~";break;case 118:o.key=a?s.C0.ESC+"[18;"+(a+1)+"~":s.C0.ESC+"[18~";break;case 119:o.key=a?s.C0.ESC+"[19;"+(a+1)+"~":s.C0.ESC+"[19~";break;case 120:o.key=a?s.C0.ESC+"[20;"+(a+1)+"~":s.C0.ESC+"[20~";break;case 121:o.key=a?s.C0.ESC+"[21;"+(a+1)+"~":s.C0.ESC+"[21~";break;case 122:o.key=a?s.C0.ESC+"[23;"+(a+1)+"~":s.C0.ESC+"[23~";break;case 123:o.key=a?s.C0.ESC+"[24;"+(a+1)+"~":s.C0.ESC+"[24~";break;default:if(!e.ctrlKey||e.shiftKey||e.altKey||e.metaKey)if(i&&!n||!e.altKey||e.metaKey)!i||e.altKey||e.ctrlKey||e.shiftKey||!e.metaKey?e.key&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&e.keyCode>=48&&1===e.key.length?o.key=e.key:e.key&&e.ctrlKey&&("_"===e.key&&(o.key=s.C0.US),"@"===e.key&&(o.key=s.C0.NUL)):65===e.keyCode&&(o.type=1);else{const t=r[e.keyCode],i=t?.[e.shiftKey?1:0];if(i)o.key=s.C0.ESC+i;else if(e.keyCode>=65&&e.keyCode<=90){const t=e.ctrlKey?e.keyCode-64:e.keyCode+32;let i=String.fromCharCode(t);e.shiftKey&&(i=i.toUpperCase()),o.key=s.C0.ESC+i}else if(32===e.keyCode)o.key=s.C0.ESC+(e.ctrlKey?s.C0.NUL:" ");else if("Dead"===e.key&&e.code.startsWith("Key")){let t=e.code.slice(3,4);e.shiftKey||(t=t.toLowerCase()),o.key=s.C0.ESC+t,o.cancel=!0}}else e.keyCode>=65&&e.keyCode<=90?o.key=String.fromCharCode(e.keyCode-64):32===e.keyCode?o.key=s.C0.NUL:e.keyCode>=51&&e.keyCode<=55?o.key=String.fromCharCode(e.keyCode-51+27):56===e.keyCode?o.key=s.C0.DEL:219===e.keyCode?o.key=s.C0.ESC:220===e.keyCode?o.key=s.C0.FS:221===e.keyCode&&(o.key=s.C0.GS)}return o};const s=i(3534),r={48:["0",")"],49:["1","!"],50:["2","@"],51:["3","#"],52:["4","$"],53:["5","%"],54:["6","^"],55:["7","&"],56:["8","*"],57:["9","("],186:[";",":"],187:["=","+"],188:[",","<"],189:["-","_"],190:[".",">"],191:["/","?"],192:["`","~"],219:["[","{"],220:["\\\\","|"],221:["]","}"],222:["\'",\'"\']}},726:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Utf8ToUtf32=t.StringToUtf32=void 0,t.stringFromCodePoint=function(e){return e>65535?(e-=65536,String.fromCharCode(55296+(e>>10))+String.fromCharCode(e%1024+56320)):String.fromCharCode(e)},t.utf32ToString=function(e,t=0,i=e.length){let s="";for(let r=t;r<i;++r){let t=e[r];t>65535?(t-=65536,s+=String.fromCharCode(55296+(t>>10))+String.fromCharCode(t%1024+56320)):s+=String.fromCharCode(t)}return s},t.StringToUtf32=class{constructor(){this._interim=0}clear(){this._interim=0}decode(e,t){const i=e.length;if(!i)return 0;let s=0,r=0;if(this._interim){const i=e.charCodeAt(r++);56320<=i&&i<=57343?t[s++]=1024*(this._interim-55296)+i-56320+65536:(t[s++]=this._interim,t[s++]=i),this._interim=0}for(let n=r;n<i;++n){const r=e.charCodeAt(n);if(55296<=r&&r<=56319){if(++n>=i)return this._interim=r,s;const o=e.charCodeAt(n);56320<=o&&o<=57343?t[s++]=1024*(r-55296)+o-56320+65536:(t[s++]=r,t[s++]=o)}else 65279!==r&&(t[s++]=r)}return s}},t.Utf8ToUtf32=class{constructor(){this.interim=new Uint8Array(3)}clear(){this.interim.fill(0)}decode(e,t){const i=e.length;if(!i)return 0;let s,r,n,o,a=0,l=0,h=0;if(this.interim[0]){let s=!1,r=this.interim[0];r&=192==(224&r)?31:224==(240&r)?15:7;let n,o=0;for(;(n=63&this.interim[++o])&&o<4;)r<<=6,r|=n;const l=192==(224&this.interim[0])?2:224==(240&this.interim[0])?3:4,c=l-o;for(;h<c;){if(h>=i)return 0;if(n=e[h++],128!=(192&n)){h--,s=!0;break}this.interim[o++]=n,r<<=6,r|=63&n}s||(2===l?r<128?h--:t[a++]=r:3===l?r<2048||r>=55296&&r<=57343||65279===r||(t[a++]=r):r<65536||r>1114111||(t[a++]=r)),this.interim.fill(0)}const c=i-4;let d=h;for(;d<i;){for(;!(!(d<c)||128&(s=e[d])||128&(r=e[d+1])||128&(n=e[d+2])||128&(o=e[d+3]));)t[a++]=s,t[a++]=r,t[a++]=n,t[a++]=o,d+=4;if(s=e[d++],s<128)t[a++]=s;else if(192==(224&s)){if(d>=i)return this.interim[0]=s,a;if(r=e[d++],128!=(192&r)){d--;continue}if(l=(31&s)<<6|63&r,l<128){d--;continue}t[a++]=l}else if(224==(240&s)){if(d>=i)return this.interim[0]=s,a;if(r=e[d++],128!=(192&r)){d--;continue}if(d>=i)return this.interim[0]=s,this.interim[1]=r,a;if(n=e[d++],128!=(192&n)){d--;continue}if(l=(15&s)<<12|(63&r)<<6|63&n,l<2048||l>=55296&&l<=57343||65279===l)continue;t[a++]=l}else if(240==(248&s)){if(d>=i)return this.interim[0]=s,a;if(r=e[d++],128!=(192&r)){d--;continue}if(d>=i)return this.interim[0]=s,this.interim[1]=r,a;if(n=e[d++],128!=(192&n)){d--;continue}if(d>=i)return this.interim[0]=s,this.interim[1]=r,this.interim[2]=n,a;if(o=e[d++],128!=(192&o)){d--;continue}if(l=(7&s)<<18|(63&r)<<12|(63&n)<<6|63&o,l<65536||l>1114111)continue;t[a++]=l}}return a}}},7428:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.UnicodeV6=void 0;const s=i(6415),r=[[768,879],[1155,1158],[1160,1161],[1425,1469],[1471,1471],[1473,1474],[1476,1477],[1479,1479],[1536,1539],[1552,1557],[1611,1630],[1648,1648],[1750,1764],[1767,1768],[1770,1773],[1807,1807],[1809,1809],[1840,1866],[1958,1968],[2027,2035],[2305,2306],[2364,2364],[2369,2376],[2381,2381],[2385,2388],[2402,2403],[2433,2433],[2492,2492],[2497,2500],[2509,2509],[2530,2531],[2561,2562],[2620,2620],[2625,2626],[2631,2632],[2635,2637],[2672,2673],[2689,2690],[2748,2748],[2753,2757],[2759,2760],[2765,2765],[2786,2787],[2817,2817],[2876,2876],[2879,2879],[2881,2883],[2893,2893],[2902,2902],[2946,2946],[3008,3008],[3021,3021],[3134,3136],[3142,3144],[3146,3149],[3157,3158],[3260,3260],[3263,3263],[3270,3270],[3276,3277],[3298,3299],[3393,3395],[3405,3405],[3530,3530],[3538,3540],[3542,3542],[3633,3633],[3636,3642],[3655,3662],[3761,3761],[3764,3769],[3771,3772],[3784,3789],[3864,3865],[3893,3893],[3895,3895],[3897,3897],[3953,3966],[3968,3972],[3974,3975],[3984,3991],[3993,4028],[4038,4038],[4141,4144],[4146,4146],[4150,4151],[4153,4153],[4184,4185],[4448,4607],[4959,4959],[5906,5908],[5938,5940],[5970,5971],[6002,6003],[6068,6069],[6071,6077],[6086,6086],[6089,6099],[6109,6109],[6155,6157],[6313,6313],[6432,6434],[6439,6440],[6450,6450],[6457,6459],[6679,6680],[6912,6915],[6964,6964],[6966,6970],[6972,6972],[6978,6978],[7019,7027],[7616,7626],[7678,7679],[8203,8207],[8234,8238],[8288,8291],[8298,8303],[8400,8431],[12330,12335],[12441,12442],[43014,43014],[43019,43019],[43045,43046],[64286,64286],[65024,65039],[65056,65059],[65279,65279],[65529,65531]],n=[[68097,68099],[68101,68102],[68108,68111],[68152,68154],[68159,68159],[119143,119145],[119155,119170],[119173,119179],[119210,119213],[119362,119364],[917505,917505],[917536,917631],[917760,917999]];let o;t.UnicodeV6=class{constructor(){if(this.version="6",!o){o=new Uint8Array(65536),o.fill(1),o[0]=0,o.fill(0,1,32),o.fill(0,127,160),o.fill(2,4352,4448),o[9001]=2,o[9002]=2,o.fill(2,11904,42192),o[12351]=1,o.fill(2,44032,55204),o.fill(2,63744,64256),o.fill(2,65040,65050),o.fill(2,65072,65136),o.fill(2,65280,65377),o.fill(2,65504,65511);for(let e=0;e<r.length;++e)o.fill(0,r[e][0],r[e][1]+1)}}wcwidth(e){return e<32?0:e<127?1:e<65536?o[e]:function(e,t){let i,s=0,r=t.length-1;if(e<t[0][0]||e>t[r][1])return!1;for(;r>=s;)if(i=s+r>>1,e>t[i][1])s=i+1;else{if(!(e<t[i][0]))return!0;r=i-1}return!1}(e,n)?0:e>=131072&&e<=196605||e>=196608&&e<=262141?2:1}charProperties(e,t){let i=this.wcwidth(e),r=0===i&&0!==t;if(r){const e=s.UnicodeService.extractWidth(t);0===e?r=!1:e>i&&(i=e)}return s.UnicodeService.createPropertyValue(0,i,r)}}},3562:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.WriteBuffer=void 0;const s=i(7150),r=i(802);class n extends s.Disposable{constructor(e){super(),this._action=e,this._writeBuffer=[],this._callbacks=[],this._pendingData=0,this._bufferOffset=0,this._isSyncWriting=!1,this._syncCalls=0,this._didUserInput=!1,this._onWriteParsed=this._register(new r.Emitter),this.onWriteParsed=this._onWriteParsed.event}handleUserInput(){this._didUserInput=!0}writeSync(e,t){if(void 0!==t&&this._syncCalls>t)return void(this._syncCalls=0);if(this._pendingData+=e.length,this._writeBuffer.push(e),this._callbacks.push(void 0),this._syncCalls++,this._isSyncWriting)return;let i;for(this._isSyncWriting=!0;i=this._writeBuffer.shift();){this._action(i);const e=this._callbacks.shift();e&&e()}this._pendingData=0,this._bufferOffset=2147483647,this._isSyncWriting=!1,this._syncCalls=0}write(e,t){if(this._pendingData>5e7)throw new Error("write data discarded, use flow control to avoid losing data");if(!this._writeBuffer.length){if(this._bufferOffset=0,this._didUserInput)return this._didUserInput=!1,this._pendingData+=e.length,this._writeBuffer.push(e),this._callbacks.push(t),void this._innerWrite();setTimeout((()=>this._innerWrite()))}this._pendingData+=e.length,this._writeBuffer.push(e),this._callbacks.push(t)}_innerWrite(e=0,t=!0){const i=e||performance.now();for(;this._writeBuffer.length>this._bufferOffset;){const e=this._writeBuffer[this._bufferOffset],s=this._action(e,t);if(s){const e=e=>performance.now()-i>=12?setTimeout((()=>this._innerWrite(0,e))):this._innerWrite(i,e);return void s.catch((e=>(queueMicrotask((()=>{throw e})),Promise.resolve(!1)))).then(e)}const r=this._callbacks[this._bufferOffset];if(r&&r(),this._bufferOffset++,this._pendingData-=e.length,performance.now()-i>=12)break}this._writeBuffer.length>this._bufferOffset?(this._bufferOffset>50&&(this._writeBuffer=this._writeBuffer.slice(this._bufferOffset),this._callbacks=this._callbacks.slice(this._bufferOffset),this._bufferOffset=0),setTimeout((()=>this._innerWrite()))):(this._writeBuffer.length=0,this._callbacks.length=0,this._pendingData=0,this._bufferOffset=0),this._onWriteParsed.fire()}}t.WriteBuffer=n},8693:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.parseColor=function(e){if(!e)return;let t=e.toLowerCase();if(0===t.indexOf("rgb:")){t=t.slice(4);const e=i.exec(t);if(e){const t=e[1]?15:e[4]?255:e[7]?4095:65535;return[Math.round(parseInt(e[1]||e[4]||e[7]||e[10],16)/t*255),Math.round(parseInt(e[2]||e[5]||e[8]||e[11],16)/t*255),Math.round(parseInt(e[3]||e[6]||e[9]||e[12],16)/t*255)]}}else if(0===t.indexOf("#")&&(t=t.slice(1),s.exec(t)&&[3,6,9,12].includes(t.length))){const e=t.length/3,i=[0,0,0];for(let s=0;s<3;++s){const r=parseInt(t.slice(e*s,e*s+e),16);i[s]=1===e?r<<4:2===e?r:3===e?r>>4:r>>8}return i}},t.toRgbString=function(e,t=16){const[i,s,n]=e;return`rgb:${r(i,t)}/${r(s,t)}/${r(n,t)}`};const i=/^([\\da-f])\\/([\\da-f])\\/([\\da-f])$|^([\\da-f]{2})\\/([\\da-f]{2})\\/([\\da-f]{2})$|^([\\da-f]{3})\\/([\\da-f]{3})\\/([\\da-f]{3})$|^([\\da-f]{4})\\/([\\da-f]{4})\\/([\\da-f]{4})$/,s=/^[\\da-f]+$/;function r(e,t){const i=e.toString(16),s=i.length<2?"0"+i:i;switch(t){case 4:return i[0];case 8:return s;case 12:return(s+s).slice(0,3);default:return s+s}}},1263:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.PAYLOAD_LIMIT=void 0,t.PAYLOAD_LIMIT=1e7},9823:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DcsHandler=t.DcsParser=void 0;const s=i(726),r=i(7262),n=i(1263),o=[];t.DcsParser=class{constructor(){this._handlers=Object.create(null),this._active=o,this._ident=0,this._handlerFb=()=>{},this._stack={paused:!1,loopPosition:0,fallThrough:!1}}dispose(){this._handlers=Object.create(null),this._handlerFb=()=>{},this._active=o}registerHandler(e,t){void 0===this._handlers[e]&&(this._handlers[e]=[]);const i=this._handlers[e];return i.push(t),{dispose:()=>{const e=i.indexOf(t);-1!==e&&i.splice(e,1)}}}clearHandler(e){this._handlers[e]&&delete this._handlers[e]}setHandlerFallback(e){this._handlerFb=e}reset(){if(this._active.length)for(let e=this._stack.paused?this._stack.loopPosition-1:this._active.length-1;e>=0;--e)this._active[e].unhook(!1);this._stack.paused=!1,this._active=o,this._ident=0}hook(e,t){if(this.reset(),this._ident=e,this._active=this._handlers[e]||o,this._active.length)for(let e=this._active.length-1;e>=0;e--)this._active[e].hook(t);else this._handlerFb(this._ident,"HOOK",t)}put(e,t,i){if(this._active.length)for(let s=this._active.length-1;s>=0;s--)this._active[s].put(e,t,i);else this._handlerFb(this._ident,"PUT",(0,s.utf32ToString)(e,t,i))}unhook(e,t=!0){if(this._active.length){let i=!1,s=this._active.length-1,r=!1;if(this._stack.paused&&(s=this._stack.loopPosition-1,i=t,r=this._stack.fallThrough,this._stack.paused=!1),!r&&!1===i){for(;s>=0&&(i=this._active[s].unhook(e),!0!==i);s--)if(i instanceof Promise)return this._stack.paused=!0,this._stack.loopPosition=s,this._stack.fallThrough=!1,i;s--}for(;s>=0;s--)if(i=this._active[s].unhook(!1),i instanceof Promise)return this._stack.paused=!0,this._stack.loopPosition=s,this._stack.fallThrough=!0,i}else this._handlerFb(this._ident,"UNHOOK",e);this._active=o,this._ident=0}};const a=new r.Params;a.addParam(0),t.DcsHandler=class{constructor(e){this._handler=e,this._data="",this._params=a,this._hitLimit=!1}hook(e){this._params=e.length>1||e.params[0]?e.clone():a,this._data="",this._hitLimit=!1}put(e,t,i){this._hitLimit||(this._data+=(0,s.utf32ToString)(e,t,i),this._data.length>n.PAYLOAD_LIMIT&&(this._data="",this._hitLimit=!0))}unhook(e){let t=!1;if(this._hitLimit)t=!1;else if(e&&(t=this._handler(this._data,this._params),t instanceof Promise))return t.then((e=>(this._params=a,this._data="",this._hitLimit=!1,e)));return this._params=a,this._data="",this._hitLimit=!1,t}}},6717:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.EscapeSequenceParser=t.VT500_TRANSITION_TABLE=t.TransitionTable=void 0;const s=i(7150),r=i(7262),n=i(1346),o=i(9823);class a{constructor(e){this.table=new Uint8Array(e)}setDefault(e,t){this.table.fill(e<<4|t)}add(e,t,i,s){this.table[t<<8|e]=i<<4|s}addMany(e,t,i,s){for(let r=0;r<e.length;r++)this.table[t<<8|e[r]]=i<<4|s}}t.TransitionTable=a;const l=160;t.VT500_TRANSITION_TABLE=function(){const e=new a(4095),t=Array.apply(null,Array(256)).map(((e,t)=>t)),i=(e,i)=>t.slice(e,i),s=i(32,127),r=i(0,24);r.push(25),r.push.apply(r,i(28,32));const n=i(0,14);let o;for(o in e.setDefault(1,0),e.addMany(s,0,2,0),n)e.addMany([24,26,153,154],o,3,0),e.addMany(i(128,144),o,3,0),e.addMany(i(144,152),o,3,0),e.add(156,o,0,0),e.add(27,o,11,1),e.add(157,o,4,8),e.addMany([152,158,159],o,0,7),e.add(155,o,11,3),e.add(144,o,11,9);return e.addMany(r,0,3,0),e.addMany(r,1,3,1),e.add(127,1,0,1),e.addMany(r,8,0,8),e.addMany(r,3,3,3),e.add(127,3,0,3),e.addMany(r,4,3,4),e.add(127,4,0,4),e.addMany(r,6,3,6),e.addMany(r,5,3,5),e.add(127,5,0,5),e.addMany(r,2,3,2),e.add(127,2,0,2),e.add(93,1,4,8),e.addMany(s,8,5,8),e.add(127,8,5,8),e.addMany([156,27,24,26,7],8,6,0),e.addMany(i(28,32),8,0,8),e.addMany([88,94,95],1,0,7),e.addMany(s,7,0,7),e.addMany(r,7,0,7),e.add(156,7,0,0),e.add(127,7,0,7),e.add(91,1,11,3),e.addMany(i(64,127),3,7,0),e.addMany(i(48,60),3,8,4),e.addMany([60,61,62,63],3,9,4),e.addMany(i(48,60),4,8,4),e.addMany(i(64,127),4,7,0),e.addMany([60,61,62,63],4,0,6),e.addMany(i(32,64),6,0,6),e.add(127,6,0,6),e.addMany(i(64,127),6,0,0),e.addMany(i(32,48),3,9,5),e.addMany(i(32,48),5,9,5),e.addMany(i(48,64),5,0,6),e.addMany(i(64,127),5,7,0),e.addMany(i(32,48),4,9,5),e.addMany(i(32,48),1,9,2),e.addMany(i(32,48),2,9,2),e.addMany(i(48,127),2,10,0),e.addMany(i(48,80),1,10,0),e.addMany(i(81,88),1,10,0),e.addMany([89,90,92],1,10,0),e.addMany(i(96,127),1,10,0),e.add(80,1,11,9),e.addMany(r,9,0,9),e.add(127,9,0,9),e.addMany(i(28,32),9,0,9),e.addMany(i(32,48),9,9,12),e.addMany(i(48,60),9,8,10),e.addMany([60,61,62,63],9,9,10),e.addMany(r,11,0,11),e.addMany(i(32,128),11,0,11),e.addMany(i(28,32),11,0,11),e.addMany(r,10,0,10),e.add(127,10,0,10),e.addMany(i(28,32),10,0,10),e.addMany(i(48,60),10,8,10),e.addMany([60,61,62,63],10,0,11),e.addMany(i(32,48),10,9,12),e.addMany(r,12,0,12),e.add(127,12,0,12),e.addMany(i(28,32),12,0,12),e.addMany(i(32,48),12,9,12),e.addMany(i(48,64),12,0,11),e.addMany(i(64,127),12,12,13),e.addMany(i(64,127),10,12,13),e.addMany(i(64,127),9,12,13),e.addMany(r,13,13,13),e.addMany(s,13,13,13),e.add(127,13,0,13),e.addMany([27,156,24,26],13,14,0),e.add(l,0,2,0),e.add(l,8,5,8),e.add(l,6,0,6),e.add(l,11,0,11),e.add(l,13,13,13),e}();class h extends s.Disposable{constructor(e=t.VT500_TRANSITION_TABLE){super(),this._transitions=e,this._parseStack={state:0,handlers:[],handlerPos:0,transition:0,chunkPos:0},this.initialState=0,this.currentState=this.initialState,this._params=new r.Params,this._params.addParam(0),this._collect=0,this.precedingJoinState=0,this._printHandlerFb=(e,t,i)=>{},this._executeHandlerFb=e=>{},this._csiHandlerFb=(e,t)=>{},this._escHandlerFb=e=>{},this._errorHandlerFb=e=>e,this._printHandler=this._printHandlerFb,this._executeHandlers=Object.create(null),this._csiHandlers=Object.create(null),this._escHandlers=Object.create(null),this._register((0,s.toDisposable)((()=>{this._csiHandlers=Object.create(null),this._executeHandlers=Object.create(null),this._escHandlers=Object.create(null)}))),this._oscParser=this._register(new n.OscParser),this._dcsParser=this._register(new o.DcsParser),this._errorHandler=this._errorHandlerFb,this.registerEscHandler({final:"\\\\"},(()=>!0))}_identifier(e,t=[64,126]){let i=0;if(e.prefix){if(e.prefix.length>1)throw new Error("only one byte as prefix supported");if(i=e.prefix.charCodeAt(0),i&&60>i||i>63)throw new Error("prefix must be in range 0x3c .. 0x3f")}if(e.intermediates){if(e.intermediates.length>2)throw new Error("only two bytes as intermediates are supported");for(let t=0;t<e.intermediates.length;++t){const s=e.intermediates.charCodeAt(t);if(32>s||s>47)throw new Error("intermediate must be in range 0x20 .. 0x2f");i<<=8,i|=s}}if(1!==e.final.length)throw new Error("final must be a single byte");const s=e.final.charCodeAt(0);if(t[0]>s||s>t[1])throw new Error(`final must be in range ${t[0]} .. ${t[1]}`);return i<<=8,i|=s,i}identToString(e){const t=[];for(;e;)t.push(String.fromCharCode(255&e)),e>>=8;return t.reverse().join("")}setPrintHandler(e){this._printHandler=e}clearPrintHandler(){this._printHandler=this._printHandlerFb}registerEscHandler(e,t){const i=this._identifier(e,[48,126]);void 0===this._escHandlers[i]&&(this._escHandlers[i]=[]);const s=this._escHandlers[i];return s.push(t),{dispose:()=>{const e=s.indexOf(t);-1!==e&&s.splice(e,1)}}}clearEscHandler(e){this._escHandlers[this._identifier(e,[48,126])]&&delete this._escHandlers[this._identifier(e,[48,126])]}setEscHandlerFallback(e){this._escHandlerFb=e}setExecuteHandler(e,t){this._executeHandlers[e.charCodeAt(0)]=t}clearExecuteHandler(e){this._executeHandlers[e.charCodeAt(0)]&&delete this._executeHandlers[e.charCodeAt(0)]}setExecuteHandlerFallback(e){this._executeHandlerFb=e}registerCsiHandler(e,t){const i=this._identifier(e);void 0===this._csiHandlers[i]&&(this._csiHandlers[i]=[]);const s=this._csiHandlers[i];return s.push(t),{dispose:()=>{const e=s.indexOf(t);-1!==e&&s.splice(e,1)}}}clearCsiHandler(e){this._csiHandlers[this._identifier(e)]&&delete this._csiHandlers[this._identifier(e)]}setCsiHandlerFallback(e){this._csiHandlerFb=e}registerDcsHandler(e,t){return this._dcsParser.registerHandler(this._identifier(e),t)}clearDcsHandler(e){this._dcsParser.clearHandler(this._identifier(e))}setDcsHandlerFallback(e){this._dcsParser.setHandlerFallback(e)}registerOscHandler(e,t){return this._oscParser.registerHandler(e,t)}clearOscHandler(e){this._oscParser.clearHandler(e)}setOscHandlerFallback(e){this._oscParser.setHandlerFallback(e)}setErrorHandler(e){this._errorHandler=e}clearErrorHandler(){this._errorHandler=this._errorHandlerFb}reset(){this.currentState=this.initialState,this._oscParser.reset(),this._dcsParser.reset(),this._params.reset(),this._params.addParam(0),this._collect=0,this.precedingJoinState=0,0!==this._parseStack.state&&(this._parseStack.state=2,this._parseStack.handlers=[])}_preserveStack(e,t,i,s,r){this._parseStack.state=e,this._parseStack.handlers=t,this._parseStack.handlerPos=i,this._parseStack.transition=s,this._parseStack.chunkPos=r}parse(e,t,i){let s,r=0,n=0,o=0;if(this._parseStack.state)if(2===this._parseStack.state)this._parseStack.state=0,o=this._parseStack.chunkPos+1;else{if(void 0===i||1===this._parseStack.state)throw this._parseStack.state=1,new Error("improper continuation due to previous async handler, giving up parsing");const t=this._parseStack.handlers;let n=this._parseStack.handlerPos-1;switch(this._parseStack.state){case 3:if(!1===i&&n>-1)for(;n>=0&&(s=t[n](this._params),!0!==s);n--)if(s instanceof Promise)return this._parseStack.handlerPos=n,s;this._parseStack.handlers=[];break;case 4:if(!1===i&&n>-1)for(;n>=0&&(s=t[n](),!0!==s);n--)if(s instanceof Promise)return this._parseStack.handlerPos=n,s;this._parseStack.handlers=[];break;case 6:if(r=e[this._parseStack.chunkPos],s=this._dcsParser.unhook(24!==r&&26!==r,i),s)return s;27===r&&(this._parseStack.transition|=1),this._params.reset(),this._params.addParam(0),this._collect=0;break;case 5:if(r=e[this._parseStack.chunkPos],s=this._oscParser.end(24!==r&&26!==r,i),s)return s;27===r&&(this._parseStack.transition|=1),this._params.reset(),this._params.addParam(0),this._collect=0}this._parseStack.state=0,o=this._parseStack.chunkPos+1,this.precedingJoinState=0,this.currentState=15&this._parseStack.transition}for(let i=o;i<t;++i){switch(r=e[i],n=this._transitions.table[this.currentState<<8|(r<160?r:l)],n>>4){case 2:for(let s=i+1;;++s){if(s>=t||(r=e[s])<32||r>126&&r<l){this._printHandler(e,i,s),i=s-1;break}if(++s>=t||(r=e[s])<32||r>126&&r<l){this._printHandler(e,i,s),i=s-1;break}if(++s>=t||(r=e[s])<32||r>126&&r<l){this._printHandler(e,i,s),i=s-1;break}if(++s>=t||(r=e[s])<32||r>126&&r<l){this._printHandler(e,i,s),i=s-1;break}}break;case 3:this._executeHandlers[r]?this._executeHandlers[r]():this._executeHandlerFb(r),this.precedingJoinState=0;break;case 0:break;case 1:if(this._errorHandler({position:i,code:r,currentState:this.currentState,collect:this._collect,params:this._params,abort:!1}).abort)return;break;case 7:const o=this._csiHandlers[this._collect<<8|r];let a=o?o.length-1:-1;for(;a>=0&&(s=o[a](this._params),!0!==s);a--)if(s instanceof Promise)return this._preserveStack(3,o,a,n,i),s;a<0&&this._csiHandlerFb(this._collect<<8|r,this._params),this.precedingJoinState=0;break;case 8:do{switch(r){case 59:this._params.addParam(0);break;case 58:this._params.addSubParam(-1);break;default:this._params.addDigit(r-48)}}while(++i<t&&(r=e[i])>47&&r<60);i--;break;case 9:this._collect<<=8,this._collect|=r;break;case 10:const h=this._escHandlers[this._collect<<8|r];let c=h?h.length-1:-1;for(;c>=0&&(s=h[c](),!0!==s);c--)if(s instanceof Promise)return this._preserveStack(4,h,c,n,i),s;c<0&&this._escHandlerFb(this._collect<<8|r),this.precedingJoinState=0;break;case 11:this._params.reset(),this._params.addParam(0),this._collect=0;break;case 12:this._dcsParser.hook(this._collect<<8|r,this._params);break;case 13:for(let s=i+1;;++s)if(s>=t||24===(r=e[s])||26===r||27===r||r>127&&r<l){this._dcsParser.put(e,i,s),i=s-1;break}break;case 14:if(s=this._dcsParser.unhook(24!==r&&26!==r),s)return this._preserveStack(6,[],0,n,i),s;27===r&&(n|=1),this._params.reset(),this._params.addParam(0),this._collect=0,this.precedingJoinState=0;break;case 4:this._oscParser.start();break;case 5:for(let s=i+1;;s++)if(s>=t||(r=e[s])<32||r>127&&r<l){this._oscParser.put(e,i,s),i=s-1;break}break;case 6:if(s=this._oscParser.end(24!==r&&26!==r),s)return this._preserveStack(5,[],0,n,i),s;27===r&&(n|=1),this._params.reset(),this._params.addParam(0),this._collect=0,this.precedingJoinState=0}this.currentState=15&n}}}t.EscapeSequenceParser=h},1346:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.OscHandler=t.OscParser=void 0;const s=i(1263),r=i(726),n=[];t.OscParser=class{constructor(){this._state=0,this._active=n,this._id=-1,this._handlers=Object.create(null),this._handlerFb=()=>{},this._stack={paused:!1,loopPosition:0,fallThrough:!1}}registerHandler(e,t){void 0===this._handlers[e]&&(this._handlers[e]=[]);const i=this._handlers[e];return i.push(t),{dispose:()=>{const e=i.indexOf(t);-1!==e&&i.splice(e,1)}}}clearHandler(e){this._handlers[e]&&delete this._handlers[e]}setHandlerFallback(e){this._handlerFb=e}dispose(){this._handlers=Object.create(null),this._handlerFb=()=>{},this._active=n}reset(){if(2===this._state)for(let e=this._stack.paused?this._stack.loopPosition-1:this._active.length-1;e>=0;--e)this._active[e].end(!1);this._stack.paused=!1,this._active=n,this._id=-1,this._state=0}_start(){if(this._active=this._handlers[this._id]||n,this._active.length)for(let e=this._active.length-1;e>=0;e--)this._active[e].start();else this._handlerFb(this._id,"START")}_put(e,t,i){if(this._active.length)for(let s=this._active.length-1;s>=0;s--)this._active[s].put(e,t,i);else this._handlerFb(this._id,"PUT",(0,r.utf32ToString)(e,t,i))}start(){this.reset(),this._state=1}put(e,t,i){if(3!==this._state){if(1===this._state)for(;t<i;){const i=e[t++];if(59===i){this._state=2,this._start();break}if(i<48||57<i)return void(this._state=3);-1===this._id&&(this._id=0),this._id=10*this._id+i-48}2===this._state&&i-t>0&&this._put(e,t,i)}}end(e,t=!0){if(0!==this._state){if(3!==this._state)if(1===this._state&&this._start(),this._active.length){let i=!1,s=this._active.length-1,r=!1;if(this._stack.paused&&(s=this._stack.loopPosition-1,i=t,r=this._stack.fallThrough,this._stack.paused=!1),!r&&!1===i){for(;s>=0&&(i=this._active[s].end(e),!0!==i);s--)if(i instanceof Promise)return this._stack.paused=!0,this._stack.loopPosition=s,this._stack.fallThrough=!1,i;s--}for(;s>=0;s--)if(i=this._active[s].end(!1),i instanceof Promise)return this._stack.paused=!0,this._stack.loopPosition=s,this._stack.fallThrough=!0,i}else this._handlerFb(this._id,"END",e);this._active=n,this._id=-1,this._state=0}}},t.OscHandler=class{constructor(e){this._handler=e,this._data="",this._hitLimit=!1}start(){this._data="",this._hitLimit=!1}put(e,t,i){this._hitLimit||(this._data+=(0,r.utf32ToString)(e,t,i),this._data.length>s.PAYLOAD_LIMIT&&(this._data="",this._hitLimit=!0))}end(e){let t=!1;if(this._hitLimit)t=!1;else if(e&&(t=this._handler(this._data),t instanceof Promise))return t.then((e=>(this._data="",this._hitLimit=!1,e)));return this._data="",this._hitLimit=!1,t}}},7262:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Params=void 0;const i=2147483647;class s{static fromArray(e){const t=new s;if(!e.length)return t;for(let i=Array.isArray(e[0])?1:0;i<e.length;++i){const s=e[i];if(Array.isArray(s))for(let e=0;e<s.length;++e)t.addSubParam(s[e]);else t.addParam(s)}return t}constructor(e=32,t=32){if(this.maxLength=e,this.maxSubParamsLength=t,t>256)throw new Error("maxSubParamsLength must not be greater than 256");this.params=new Int32Array(e),this.length=0,this._subParams=new Int32Array(t),this._subParamsLength=0,this._subParamsIdx=new Uint16Array(e),this._rejectDigits=!1,this._rejectSubDigits=!1,this._digitIsSub=!1}clone(){const e=new s(this.maxLength,this.maxSubParamsLength);return e.params.set(this.params),e.length=this.length,e._subParams.set(this._subParams),e._subParamsLength=this._subParamsLength,e._subParamsIdx.set(this._subParamsIdx),e._rejectDigits=this._rejectDigits,e._rejectSubDigits=this._rejectSubDigits,e._digitIsSub=this._digitIsSub,e}toArray(){const e=[];for(let t=0;t<this.length;++t){e.push(this.params[t]);const i=this._subParamsIdx[t]>>8,s=255&this._subParamsIdx[t];s-i>0&&e.push(Array.prototype.slice.call(this._subParams,i,s))}return e}reset(){this.length=0,this._subParamsLength=0,this._rejectDigits=!1,this._rejectSubDigits=!1,this._digitIsSub=!1}addParam(e){if(this._digitIsSub=!1,this.length>=this.maxLength)this._rejectDigits=!0;else{if(e<-1)throw new Error("values lesser than -1 are not allowed");this._subParamsIdx[this.length]=this._subParamsLength<<8|this._subParamsLength,this.params[this.length++]=e>i?i:e}}addSubParam(e){if(this._digitIsSub=!0,this.length)if(this._rejectDigits||this._subParamsLength>=this.maxSubParamsLength)this._rejectSubDigits=!0;else{if(e<-1)throw new Error("values lesser than -1 are not allowed");this._subParams[this._subParamsLength++]=e>i?i:e,this._subParamsIdx[this.length-1]++}}hasSubParams(e){return(255&this._subParamsIdx[e])-(this._subParamsIdx[e]>>8)>0}getSubParams(e){const t=this._subParamsIdx[e]>>8,i=255&this._subParamsIdx[e];return i-t>0?this._subParams.subarray(t,i):null}getSubParamsAll(){const e={};for(let t=0;t<this.length;++t){const i=this._subParamsIdx[t]>>8,s=255&this._subParamsIdx[t];s-i>0&&(e[t]=this._subParams.slice(i,s))}return e}addDigit(e){let t;if(this._rejectDigits||!(t=this._digitIsSub?this._subParamsLength:this.length)||this._digitIsSub&&this._rejectSubDigits)return;const s=this._digitIsSub?this._subParams:this.params,r=s[t-1];s[t-1]=~r?Math.min(10*r+e,i):e}}t.Params=s},3027:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.AddonManager=void 0,t.AddonManager=class{constructor(){this._addons=[]}dispose(){for(let e=this._addons.length-1;e>=0;e--)this._addons[e].instance.dispose()}loadAddon(e,t){const i={instance:t,dispose:t.dispose,isDisposed:!1};this._addons.push(i),t.dispose=()=>this._wrappedAddonDispose(i),t.activate(e)}_wrappedAddonDispose(e){if(e.isDisposed)return;let t=-1;for(let i=0;i<this._addons.length;i++)if(this._addons[i]===e){t=i;break}if(-1===t)throw new Error("Could not dispose an addon that has not been loaded");e.isDisposed=!0,e.dispose.apply(e.instance),this._addons.splice(t,1)}}},3235:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferApiView=void 0;const s=i(793),r=i(3055);t.BufferApiView=class{constructor(e,t){this._buffer=e,this.type=t}init(e){return this._buffer=e,this}get cursorY(){return this._buffer.y}get cursorX(){return this._buffer.x}get viewportY(){return this._buffer.ydisp}get baseY(){return this._buffer.ybase}get length(){return this._buffer.lines.length}getLine(e){const t=this._buffer.lines.get(e);if(t)return new s.BufferLineApiView(t)}getNullCell(){return new r.CellData}}},793:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferLineApiView=void 0;const s=i(3055);t.BufferLineApiView=class{constructor(e){this._line=e}get isWrapped(){return this._line.isWrapped}get length(){return this._line.length}getCell(e,t){if(!(e<0||e>=this._line.length))return t?(this._line.loadCell(e,t),t):this._line.loadCell(e,new s.CellData)}translateToString(e,t,i){return this._line.translateToString(e,t,i)}}},5101:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BufferNamespaceApi=void 0;const s=i(3235),r=i(7150),n=i(802);class o extends r.Disposable{constructor(e){super(),this._core=e,this._onBufferChange=this._register(new n.Emitter),this.onBufferChange=this._onBufferChange.event,this._normal=new s.BufferApiView(this._core.buffers.normal,"normal"),this._alternate=new s.BufferApiView(this._core.buffers.alt,"alternate"),this._core.buffers.onBufferActivate((()=>this._onBufferChange.fire(this.active)))}get active(){if(this._core.buffers.active===this._core.buffers.normal)return this.normal;if(this._core.buffers.active===this._core.buffers.alt)return this.alternate;throw new Error("Active buffer is neither normal nor alternate")}get normal(){return this._normal.init(this._core.buffers.normal)}get alternate(){return this._alternate.init(this._core.buffers.alt)}}t.BufferNamespaceApi=o},6097:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ParserApi=void 0,t.ParserApi=class{constructor(e){this._core=e}registerCsiHandler(e,t){return this._core.registerCsiHandler(e,(e=>t(e.toArray())))}addCsiHandler(e,t){return this.registerCsiHandler(e,t)}registerDcsHandler(e,t){return this._core.registerDcsHandler(e,((e,i)=>t(e,i.toArray())))}addDcsHandler(e,t){return this.registerDcsHandler(e,t)}registerEscHandler(e,t){return this._core.registerEscHandler(e,t)}addEscHandler(e,t){return this.registerEscHandler(e,t)}registerOscHandler(e,t){return this._core.registerOscHandler(e,t)}addOscHandler(e,t){return this.registerOscHandler(e,t)}}},4335:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.UnicodeApi=void 0,t.UnicodeApi=class{constructor(e){this._core=e}register(e){this._core.unicodeService.register(e)}get versions(){return this._core.unicodeService.versions}get activeVersion(){return this._core.unicodeService.activeVersion}set activeVersion(e){this._core.unicodeService.activeVersion=e}}},9640:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.BufferService=t.MINIMUM_ROWS=t.MINIMUM_COLS=void 0;const n=i(7150),o=i(4097),a=i(6501),l=i(802);t.MINIMUM_COLS=2,t.MINIMUM_ROWS=1;let h=class extends n.Disposable{get buffer(){return this.buffers.active}constructor(e){super(),this.isUserScrolling=!1,this._onResize=this._register(new l.Emitter),this.onResize=this._onResize.event,this._onScroll=this._register(new l.Emitter),this.onScroll=this._onScroll.event,this.cols=Math.max(e.rawOptions.cols||0,t.MINIMUM_COLS),this.rows=Math.max(e.rawOptions.rows||0,t.MINIMUM_ROWS),this.buffers=this._register(new o.BufferSet(e,this)),this._register(this.buffers.onBufferActivate((e=>{this._onScroll.fire(e.activeBuffer.ydisp)})))}resize(e,t){const i=this.cols!==e,s=this.rows!==t;this.cols=e,this.rows=t,this.buffers.resize(e,t),this._onResize.fire({cols:e,rows:t,colsChanged:i,rowsChanged:s})}reset(){this.buffers.reset(),this.isUserScrolling=!1}scroll(e,t=!1){const i=this.buffer;let s;s=this._cachedBlankLine,s&&s.length===this.cols&&s.getFg(0)===e.fg&&s.getBg(0)===e.bg||(s=i.getBlankLine(e,t),this._cachedBlankLine=s),s.isWrapped=t;const r=i.ybase+i.scrollTop,n=i.ybase+i.scrollBottom;if(0===i.scrollTop){const e=i.lines.isFull;n===i.lines.length-1?e?i.lines.recycle().copyFrom(s):i.lines.push(s.clone()):i.lines.splice(n+1,0,s.clone()),e?this.isUserScrolling&&(i.ydisp=Math.max(i.ydisp-1,0)):(i.ybase++,this.isUserScrolling||i.ydisp++)}else{const e=n-r+1;i.lines.shiftElements(r+1,e-1,-1),i.lines.set(n,s.clone())}this.isUserScrolling||(i.ydisp=i.ybase),this._onScroll.fire(i.ydisp)}scrollLines(e,t){const i=this.buffer;if(e<0){if(0===i.ydisp)return;this.isUserScrolling=!0}else e+i.ydisp>=i.ybase&&(this.isUserScrolling=!1);const s=i.ydisp;i.ydisp=Math.max(Math.min(i.ydisp+e,i.ybase),0),s!==i.ydisp&&(t||this._onScroll.fire(i.ydisp))}};t.BufferService=h,t.BufferService=h=s([r(0,a.IOptionsService)],h)},5746:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CharsetService=void 0,t.CharsetService=class{constructor(){this.glevel=0,this._charsets=[]}reset(){this.charset=void 0,this._charsets=[],this.glevel=0}setgLevel(e){this.glevel=e,this.charset=this._charsets[e]}setgCharset(e,t){this._charsets[e]=t,this.glevel===e&&(this.charset=t)}}},7792:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CoreMouseService=void 0;const n=i(6501),o=i(7150),a=i(802),l={NONE:{events:0,restrict:()=>!1},X10:{events:1,restrict:e=>4!==e.button&&1===e.action&&(e.ctrl=!1,e.alt=!1,e.shift=!1,!0)},VT200:{events:19,restrict:e=>32!==e.action},DRAG:{events:23,restrict:e=>32!==e.action||3!==e.button},ANY:{events:31,restrict:e=>!0}};function h(e,t){let i=(e.ctrl?16:0)|(e.shift?4:0)|(e.alt?8:0);return 4===e.button?(i|=64,i|=e.action):(i|=3&e.button,4&e.button&&(i|=64),8&e.button&&(i|=128),32===e.action?i|=32:0!==e.action||t||(i|=3)),i}const c=String.fromCharCode,d={DEFAULT:e=>{const t=[h(e,!1)+32,e.col+32,e.row+32];return t[0]>255||t[1]>255||t[2]>255?"":`\x1B[M${c(t[0])}${c(t[1])}${c(t[2])}`},SGR:e=>{const t=0===e.action&&4!==e.button?"m":"M";return`\x1B[<${h(e,!0)};${e.col};${e.row}${t}`},SGR_PIXELS:e=>{const t=0===e.action&&4!==e.button?"m":"M";return`\x1B[<${h(e,!0)};${e.x};${e.y}${t}`}};let u=class extends o.Disposable{constructor(e,t,i){super(),this._bufferService=e,this._coreService=t,this._optionsService=i,this._protocols={},this._encodings={},this._activeProtocol="",this._activeEncoding="",this._lastEvent=null,this._wheelPartialScroll=0,this._onProtocolChange=this._register(new a.Emitter),this.onProtocolChange=this._onProtocolChange.event;for(const e of Object.keys(l))this.addProtocol(e,l[e]);for(const e of Object.keys(d))this.addEncoding(e,d[e]);this.reset()}addProtocol(e,t){this._protocols[e]=t}addEncoding(e,t){this._encodings[e]=t}get activeProtocol(){return this._activeProtocol}get areMouseEventsActive(){return 0!==this._protocols[this._activeProtocol].events}set activeProtocol(e){if(!this._protocols[e])throw new Error(`unknown protocol "${e}"`);this._activeProtocol=e,this._onProtocolChange.fire(this._protocols[e].events)}get activeEncoding(){return this._activeEncoding}set activeEncoding(e){if(!this._encodings[e])throw new Error(`unknown encoding "${e}"`);this._activeEncoding=e}reset(){this.activeProtocol="NONE",this.activeEncoding="DEFAULT",this._lastEvent=null,this._wheelPartialScroll=0}consumeWheelEvent(e,t,i){if(0===e.deltaY||e.shiftKey)return 0;if(void 0===t||void 0===i)return 0;const s=t/i;let r=this._applyScrollModifier(e.deltaY,e);return e.deltaMode===WheelEvent.DOM_DELTA_PIXEL?(r/=s+0,Math.abs(e.deltaY)<50&&(r*=.3),this._wheelPartialScroll+=r,r=Math.floor(Math.abs(this._wheelPartialScroll))*(this._wheelPartialScroll>0?1:-1),this._wheelPartialScroll%=1):e.deltaMode===WheelEvent.DOM_DELTA_PAGE&&(r*=this._bufferService.rows),r}_applyScrollModifier(e,t){return t.altKey||t.ctrlKey||t.shiftKey?e*this._optionsService.rawOptions.fastScrollSensitivity*this._optionsService.rawOptions.scrollSensitivity:e*this._optionsService.rawOptions.scrollSensitivity}triggerMouseEvent(e){if(e.col<0||e.col>=this._bufferService.cols||e.row<0||e.row>=this._bufferService.rows)return!1;if(4===e.button&&32===e.action)return!1;if(3===e.button&&32!==e.action)return!1;if(4!==e.button&&(2===e.action||3===e.action))return!1;if(e.col++,e.row++,32===e.action&&this._lastEvent&&this._equalEvents(this._lastEvent,e,"SGR_PIXELS"===this._activeEncoding))return!1;if(!this._protocols[this._activeProtocol].restrict(e))return!1;const t=this._encodings[this._activeEncoding](e);return t&&("DEFAULT"===this._activeEncoding?this._coreService.triggerBinaryEvent(t):this._coreService.triggerDataEvent(t,!0)),this._lastEvent=e,!0}explainEvents(e){return{down:!!(1&e),up:!!(2&e),drag:!!(4&e),move:!!(8&e),wheel:!!(16&e)}}_equalEvents(e,t,i){if(i){if(e.x!==t.x)return!1;if(e.y!==t.y)return!1}else{if(e.col!==t.col)return!1;if(e.row!==t.row)return!1}return e.button===t.button&&e.action===t.action&&e.ctrl===t.ctrl&&e.alt===t.alt&&e.shift===t.shift}};t.CoreMouseService=u,t.CoreMouseService=u=s([r(0,n.IBufferService),r(1,n.ICoreService),r(2,n.IOptionsService)],u)},4071:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.CoreService=void 0;const n=i(7453),o=i(7150),a=i(6501),l=i(802),h=Object.freeze({insertMode:!1}),c=Object.freeze({applicationCursorKeys:!1,applicationKeypad:!1,bracketedPasteMode:!1,cursorBlink:void 0,cursorStyle:void 0,origin:!1,reverseWraparound:!1,sendFocus:!1,synchronizedOutput:!1,wraparound:!0});let d=class extends o.Disposable{constructor(e,t,i){super(),this._bufferService=e,this._logService=t,this._optionsService=i,this.isCursorInitialized=!1,this.isCursorHidden=!1,this._onData=this._register(new l.Emitter),this.onData=this._onData.event,this._onUserInput=this._register(new l.Emitter),this.onUserInput=this._onUserInput.event,this._onBinary=this._register(new l.Emitter),this.onBinary=this._onBinary.event,this._onRequestScrollToBottom=this._register(new l.Emitter),this.onRequestScrollToBottom=this._onRequestScrollToBottom.event,this.modes=(0,n.clone)(h),this.decPrivateModes=(0,n.clone)(c)}reset(){this.modes=(0,n.clone)(h),this.decPrivateModes=(0,n.clone)(c)}triggerDataEvent(e,t=!1){if(this._optionsService.rawOptions.disableStdin)return;const i=this._bufferService.buffer;t&&this._optionsService.rawOptions.scrollOnUserInput&&i.ybase!==i.ydisp&&this._onRequestScrollToBottom.fire(),t&&this._onUserInput.fire(),this._logService.debug(`sending data "${e}"`),this._logService.trace("sending data (codes)",(()=>e.split("").map((e=>e.charCodeAt(0))))),this._onData.fire(e)}triggerBinaryEvent(e){this._optionsService.rawOptions.disableStdin||(this._logService.debug(`sending binary "${e}"`),this._logService.trace("sending binary (codes)",(()=>e.split("").map((e=>e.charCodeAt(0))))),this._onBinary.fire(e))}};t.CoreService=d,t.CoreService=d=s([r(0,a.IBufferService),r(1,a.ILogService),r(2,a.IOptionsService)],d)},4720:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DecorationService=void 0;const s=i(4103),r=i(7150),n=i(3087),o=i(802);let a=0,l=0;class h extends r.Disposable{get decorations(){return this._decorations.values()}constructor(){super(),this._decorations=new n.SortedList((e=>e?.marker.line)),this._onDecorationRegistered=this._register(new o.Emitter),this.onDecorationRegistered=this._onDecorationRegistered.event,this._onDecorationRemoved=this._register(new o.Emitter),this.onDecorationRemoved=this._onDecorationRemoved.event,this._register((0,r.toDisposable)((()=>this.reset())))}registerDecoration(e){if(e.marker.isDisposed)return;const t=new c(e);if(t){const e=t.marker.onDispose((()=>t.dispose())),i=t.onDispose((()=>{i.dispose(),t&&(this._decorations.delete(t)&&this._onDecorationRemoved.fire(t),e.dispose())}));this._decorations.insert(t),this._onDecorationRegistered.fire(t)}return t}reset(){for(const e of this._decorations.values())e.dispose();this._decorations.clear()}*getDecorationsAtCell(e,t,i){let s=0,r=0;for(const n of this._decorations.getKeyIterator(t))s=n.options.x??0,r=s+(n.options.width??1),e>=s&&e<r&&(!i||(n.options.layer??"bottom")===i)&&(yield n)}forEachDecorationAtCell(e,t,i,s){this._decorations.forEachByKey(t,(t=>{a=t.options.x??0,l=a+(t.options.width??1),e>=a&&e<l&&(!i||(t.options.layer??"bottom")===i)&&s(t)}))}}t.DecorationService=h;class c extends r.DisposableStore{get backgroundColorRGB(){return null===this._cachedBg&&(this.options.backgroundColor?this._cachedBg=s.css.toColor(this.options.backgroundColor):this._cachedBg=void 0),this._cachedBg}get foregroundColorRGB(){return null===this._cachedFg&&(this.options.foregroundColor?this._cachedFg=s.css.toColor(this.options.foregroundColor):this._cachedFg=void 0),this._cachedFg}constructor(e){super(),this.options=e,this.onRenderEmitter=this.add(new o.Emitter),this.onRender=this.onRenderEmitter.event,this._onDispose=this.add(new o.Emitter),this.onDispose=this._onDispose.event,this._cachedBg=null,this._cachedFg=null,this.marker=e.marker,this.options.overviewRulerOptions&&!this.options.overviewRulerOptions.position&&(this.options.overviewRulerOptions.position="full")}dispose(){this._onDispose.fire(),super.dispose()}}},6025:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.InstantiationService=t.ServiceCollection=void 0;const s=i(6501),r=i(6201);class n{constructor(...e){this._entries=new Map;for(const[t,i]of e)this.set(t,i)}set(e,t){const i=this._entries.get(e);return this._entries.set(e,t),i}forEach(e){for(const[t,i]of this._entries.entries())e(t,i)}has(e){return this._entries.has(e)}get(e){return this._entries.get(e)}}t.ServiceCollection=n,t.InstantiationService=class{constructor(){this._services=new n,this._services.set(s.IInstantiationService,this)}setService(e,t){this._services.set(e,t)}getService(e){return this._services.get(e)}createInstance(e,...t){const i=(0,r.getServiceDependencies)(e).sort(((e,t)=>e.index-t.index)),s=[];for(const t of i){const i=this._services.get(t.id);if(!i)throw new Error(`[createInstance] ${e.name} depends on UNKNOWN service ${t.id._id}.`);s.push(i)}const n=i.length>0?i[0].index:t.length;if(t.length!==n)throw new Error(`[createInstance] First service dependency of ${e.name} at position ${n+1} conflicts with ${t.length} static arguments`);return new e(...[...t,...s])}}},7276:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.LogService=void 0,t.setTraceLogger=function(e){l=e},t.traceCall=function(e,t,i){if("function"!=typeof i.value)throw new Error("not supported");const s=i.value;i.value=function(...e){if(l.logLevel!==o.LogLevelEnum.TRACE)return s.apply(this,e);l.trace(`GlyphRenderer#${s.name}(${e.map((e=>JSON.stringify(e))).join(", ")})`);const t=s.apply(this,e);return l.trace(`GlyphRenderer#${s.name} return`,t),t}};const n=i(7150),o=i(6501),a={trace:o.LogLevelEnum.TRACE,debug:o.LogLevelEnum.DEBUG,info:o.LogLevelEnum.INFO,warn:o.LogLevelEnum.WARN,error:o.LogLevelEnum.ERROR,off:o.LogLevelEnum.OFF};let l,h=class extends n.Disposable{get logLevel(){return this._logLevel}constructor(e){super(),this._optionsService=e,this._logLevel=o.LogLevelEnum.OFF,this._updateLogLevel(),this._register(this._optionsService.onSpecificOptionChange("logLevel",(()=>this._updateLogLevel()))),l=this}_updateLogLevel(){this._logLevel=a[this._optionsService.rawOptions.logLevel]}_evalLazyOptionalParams(e){for(let t=0;t<e.length;t++)"function"==typeof e[t]&&(e[t]=e[t]())}_log(e,t,i){this._evalLazyOptionalParams(i),e.call(console,(this._optionsService.options.logger?"":"xterm.js: ")+t,...i)}trace(e,...t){this._logLevel<=o.LogLevelEnum.TRACE&&this._log(this._optionsService.options.logger?.trace.bind(this._optionsService.options.logger)??console.log,e,t)}debug(e,...t){this._logLevel<=o.LogLevelEnum.DEBUG&&this._log(this._optionsService.options.logger?.debug.bind(this._optionsService.options.logger)??console.log,e,t)}info(e,...t){this._logLevel<=o.LogLevelEnum.INFO&&this._log(this._optionsService.options.logger?.info.bind(this._optionsService.options.logger)??console.info,e,t)}warn(e,...t){this._logLevel<=o.LogLevelEnum.WARN&&this._log(this._optionsService.options.logger?.warn.bind(this._optionsService.options.logger)??console.warn,e,t)}error(e,...t){this._logLevel<=o.LogLevelEnum.ERROR&&this._log(this._optionsService.options.logger?.error.bind(this._optionsService.options.logger)??console.error,e,t)}};t.LogService=h,t.LogService=h=s([r(0,o.IOptionsService)],h)},56:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.OptionsService=t.DEFAULT_OPTIONS=void 0;const s=i(7150),r=i(701),n=i(802);t.DEFAULT_OPTIONS={cols:80,rows:24,cursorBlink:!1,cursorStyle:"block",cursorWidth:1,cursorInactiveStyle:"outline",customGlyphs:!0,drawBoldTextInBrightColors:!0,documentOverride:null,fastScrollModifier:"alt",fastScrollSensitivity:5,fontFamily:"monospace",fontSize:15,fontWeight:"normal",fontWeightBold:"bold",ignoreBracketedPasteMode:!1,lineHeight:1,letterSpacing:0,linkHandler:null,logLevel:"info",logger:null,scrollback:1e3,scrollOnEraseInDisplay:!1,scrollOnUserInput:!0,scrollSensitivity:1,screenReaderMode:!1,smoothScrollDuration:0,macOptionIsMeta:!1,macOptionClickForcesSelection:!1,minimumContrastRatio:1,disableStdin:!1,allowProposedApi:!1,allowTransparency:!1,tabStopWidth:8,theme:{},reflowCursorLine:!1,rescaleOverlappingGlyphs:!1,rightClickSelectsWord:r.isMac,windowOptions:{},windowsMode:!1,windowsPty:{},wordSeparator:" ()[]{}\',\\"`",altClickMovesCursor:!0,convertEol:!1,termName:"xterm",cancelEvents:!1,overviewRuler:{}};const o=["normal","bold","100","200","300","400","500","600","700","800","900"];class a extends s.Disposable{constructor(e){super(),this._onOptionChange=this._register(new n.Emitter),this.onOptionChange=this._onOptionChange.event;const i={...t.DEFAULT_OPTIONS};for(const t in e)if(t in i)try{const s=e[t];i[t]=this._sanitizeAndValidateOption(t,s)}catch(e){console.error(e)}this.rawOptions=i,this.options={...i},this._setupOptions(),this._register((0,s.toDisposable)((()=>{this.rawOptions.linkHandler=null,this.rawOptions.documentOverride=null})))}onSpecificOptionChange(e,t){return this.onOptionChange((i=>{i===e&&t(this.rawOptions[e])}))}onMultipleOptionChange(e,t){return this.onOptionChange((i=>{-1!==e.indexOf(i)&&t()}))}_setupOptions(){const e=e=>{if(!(e in t.DEFAULT_OPTIONS))throw new Error(`No option with key "${e}"`);return this.rawOptions[e]},i=(e,i)=>{if(!(e in t.DEFAULT_OPTIONS))throw new Error(`No option with key "${e}"`);i=this._sanitizeAndValidateOption(e,i),this.rawOptions[e]!==i&&(this.rawOptions[e]=i,this._onOptionChange.fire(e))};for(const t in this.rawOptions){const s={get:e.bind(this,t),set:i.bind(this,t)};Object.defineProperty(this.options,t,s)}}_sanitizeAndValidateOption(e,i){switch(e){case"cursorStyle":if(i||(i=t.DEFAULT_OPTIONS[e]),!function(e){return"block"===e||"underline"===e||"bar"===e}(i))throw new Error(`"${i}" is not a valid value for ${e}`);break;case"wordSeparator":i||(i=t.DEFAULT_OPTIONS[e]);break;case"fontWeight":case"fontWeightBold":if("number"==typeof i&&1<=i&&i<=1e3)break;i=o.includes(i)?i:t.DEFAULT_OPTIONS[e];break;case"cursorWidth":i=Math.floor(i);case"lineHeight":case"tabStopWidth":if(i<1)throw new Error(`${e} cannot be less than 1, value: ${i}`);break;case"minimumContrastRatio":i=Math.max(1,Math.min(21,Math.round(10*i)/10));break;case"scrollback":if((i=Math.min(i,4294967295))<0)throw new Error(`${e} cannot be less than 0, value: ${i}`);break;case"fastScrollSensitivity":case"scrollSensitivity":if(i<=0)throw new Error(`${e} cannot be less than or equal to 0, value: ${i}`);break;case"rows":case"cols":if(!i&&0!==i)throw new Error(`${e} must be numeric, value: ${i}`);break;case"windowsPty":i=i??{}}return i}}t.OptionsService=a},8811:function(e,t,i){var s=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},r=this&&this.__param||function(e,t){return function(i,s){t(i,s,e)}};Object.defineProperty(t,"__esModule",{value:!0}),t.OscLinkService=void 0;const n=i(6501);let o=class{constructor(e){this._bufferService=e,this._nextId=1,this._entriesWithId=new Map,this._dataByLinkId=new Map}registerLink(e){const t=this._bufferService.buffer;if(void 0===e.id){const i=t.addMarker(t.ybase+t.y),s={data:e,id:this._nextId++,lines:[i]};return i.onDispose((()=>this._removeMarkerFromLink(s,i))),this._dataByLinkId.set(s.id,s),s.id}const i=e,s=this._getEntryIdKey(i),r=this._entriesWithId.get(s);if(r)return this.addLineToLink(r.id,t.ybase+t.y),r.id;const n=t.addMarker(t.ybase+t.y),o={id:this._nextId++,key:this._getEntryIdKey(i),data:i,lines:[n]};return n.onDispose((()=>this._removeMarkerFromLink(o,n))),this._entriesWithId.set(o.key,o),this._dataByLinkId.set(o.id,o),o.id}addLineToLink(e,t){const i=this._dataByLinkId.get(e);if(i&&i.lines.every((e=>e.line!==t))){const e=this._bufferService.buffer.addMarker(t);i.lines.push(e),e.onDispose((()=>this._removeMarkerFromLink(i,e)))}}getLinkData(e){return this._dataByLinkId.get(e)?.data}_getEntryIdKey(e){return`${e.id};;${e.uri}`}_removeMarkerFromLink(e,t){const i=e.lines.indexOf(t);-1!==i&&(e.lines.splice(i,1),0===e.lines.length&&(void 0!==e.data.id&&this._entriesWithId.delete(e.key),this._dataByLinkId.delete(e.id)))}};t.OscLinkService=o,t.OscLinkService=o=s([r(0,n.IBufferService)],o)},6201:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.serviceRegistry=void 0,t.getServiceDependencies=function(e){return e[s]||[]},t.createDecorator=function(e){if(t.serviceRegistry.has(e))return t.serviceRegistry.get(e);const r=function(e,t,n){if(3!==arguments.length)throw new Error("@IServiceName-decorator can only be used to decorate a parameter");!function(e,t,r){t[i]===t?t[s].push({id:e,index:r}):(t[s]=[{id:e,index:r}],t[i]=t)}(r,e,n)};return r._id=e,t.serviceRegistry.set(e,r),r};const i="di$target",s="di$dependencies";t.serviceRegistry=new Map},6501:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.IDecorationService=t.IUnicodeService=t.IOscLinkService=t.IOptionsService=t.ILogService=t.LogLevelEnum=t.IInstantiationService=t.ICharsetService=t.ICoreService=t.ICoreMouseService=t.IBufferService=void 0;const s=i(6201);var r;t.IBufferService=(0,s.createDecorator)("BufferService"),t.ICoreMouseService=(0,s.createDecorator)("CoreMouseService"),t.ICoreService=(0,s.createDecorator)("CoreService"),t.ICharsetService=(0,s.createDecorator)("CharsetService"),t.IInstantiationService=(0,s.createDecorator)("InstantiationService"),function(e){e[e.TRACE=0]="TRACE",e[e.DEBUG=1]="DEBUG",e[e.INFO=2]="INFO",e[e.WARN=3]="WARN",e[e.ERROR=4]="ERROR",e[e.OFF=5]="OFF"}(r||(t.LogLevelEnum=r={})),t.ILogService=(0,s.createDecorator)("LogService"),t.IOptionsService=(0,s.createDecorator)("OptionsService"),t.IOscLinkService=(0,s.createDecorator)("OscLinkService"),t.IUnicodeService=(0,s.createDecorator)("UnicodeService"),t.IDecorationService=(0,s.createDecorator)("DecorationService")},6415:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.UnicodeService=void 0;const s=i(7428),r=i(802);class n{static extractShouldJoin(e){return!!(1&e)}static extractWidth(e){return e>>1&3}static extractCharKind(e){return e>>3}static createPropertyValue(e,t,i=!1){return(16777215&e)<<3|(3&t)<<1|(i?1:0)}constructor(){this._providers=Object.create(null),this._active="",this._onChange=new r.Emitter,this.onChange=this._onChange.event;const e=new s.UnicodeV6;this.register(e),this._active=e.version,this._activeProvider=e}dispose(){this._onChange.dispose()}get versions(){return Object.keys(this._providers)}get activeVersion(){return this._active}set activeVersion(e){if(!this._providers[e])throw new Error(`unknown Unicode version "${e}"`);this._active=e,this._activeProvider=this._providers[e],this._onChange.fire(e)}register(e){this._providers[e.version]=e}wcwidth(e){return this._activeProvider.wcwidth(e)}getStringCellWidth(e){let t=0,i=0;const s=e.length;for(let r=0;r<s;++r){let o=e.charCodeAt(r);if(55296<=o&&o<=56319){if(++r>=s)return t+this.wcwidth(o);const i=e.charCodeAt(r);56320<=i&&i<=57343?o=1024*(o-55296)+i-56320+65536:t+=this.wcwidth(i)}const a=this.charProperties(o,i);let l=n.extractWidth(a);n.extractShouldJoin(a)&&(l-=n.extractWidth(i)),t+=l,i=a}return t}charProperties(e,t){return this._activeProvider.charProperties(e,t)}}t.UnicodeService=n},4333:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.isAndroid=t.isElectron=t.isWebkitWebView=t.isSafari=t.isChrome=t.isWebKit=t.isFirefox=t.onDidChangeFullscreen=t.onDidChangeZoomLevel=void 0,t.addMatchMediaChangeListener=o,t.setZoomLevel=function(e,t){n.INSTANCE.setZoomLevel(e,t)},t.getZoomLevel=function(e){return n.INSTANCE.getZoomLevel(e)},t.getZoomFactor=function(e){return n.INSTANCE.getZoomFactor(e)},t.setZoomFactor=function(e,t){n.INSTANCE.setZoomFactor(e,t)},t.setFullscreen=function(e,t){n.INSTANCE.setFullscreen(e,t)},t.isFullscreen=function(e){return n.INSTANCE.isFullscreen(e)},t.isStandalone=function(){return l},t.isWCOEnabled=function(){return navigator?.windowControlsOverlay?.visible},t.getWCOBoundingRect=function(){return navigator?.windowControlsOverlay?.getTitlebarAreaRect()};const s=i(4693),r=i(802);class n{constructor(){this.mapWindowIdToZoomLevel=new Map,this._onDidChangeZoomLevel=new r.Emitter,this.onDidChangeZoomLevel=this._onDidChangeZoomLevel.event,this.mapWindowIdToZoomFactor=new Map,this._onDidChangeFullscreen=new r.Emitter,this.onDidChangeFullscreen=this._onDidChangeFullscreen.event,this.mapWindowIdToFullScreen=new Map}static{this.INSTANCE=new n}getZoomLevel(e){return this.mapWindowIdToZoomLevel.get(this.getWindowId(e))??0}setZoomLevel(e,t){if(this.getZoomLevel(t)===e)return;const i=this.getWindowId(t);this.mapWindowIdToZoomLevel.set(i,e),this._onDidChangeZoomLevel.fire(i)}getZoomFactor(e){return this.mapWindowIdToZoomFactor.get(this.getWindowId(e))??1}setZoomFactor(e,t){this.mapWindowIdToZoomFactor.set(this.getWindowId(t),e)}setFullscreen(e,t){if(this.isFullscreen(t)===e)return;const i=this.getWindowId(t);this.mapWindowIdToFullScreen.set(i,e),this._onDidChangeFullscreen.fire(i)}isFullscreen(e){return!!this.mapWindowIdToFullScreen.get(this.getWindowId(e))}getWindowId(e){return e.vscodeWindowId}}function o(e,t,i){"string"==typeof t&&(t=e.matchMedia(t)),t.addEventListener("change",i)}t.onDidChangeZoomLevel=n.INSTANCE.onDidChangeZoomLevel,t.onDidChangeFullscreen=n.INSTANCE.onDidChangeFullscreen;const a="object"==typeof navigator?navigator.userAgent:"";t.isFirefox=a.indexOf("Firefox")>=0,t.isWebKit=a.indexOf("AppleWebKit")>=0,t.isChrome=a.indexOf("Chrome")>=0,t.isSafari=!t.isChrome&&a.indexOf("Safari")>=0,t.isWebkitWebView=!t.isChrome&&!t.isSafari&&t.isWebKit,t.isElectron=a.indexOf("Electron/")>=0,t.isAndroid=a.indexOf("Android")>=0;let l=!1;if("function"==typeof s.mainWindow.matchMedia){const e=s.mainWindow.matchMedia("(display-mode: standalone) or (display-mode: window-controls-overlay)"),t=s.mainWindow.matchMedia("(display-mode: fullscreen)");l=e.matches,o(s.mainWindow,e,(({matches:e})=>{l&&t.matches||(l=e)}))}},7745:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.BrowserFeatures=t.KeyboardSupport=void 0;const o=n(i(4333)),a=i(4693),l=n(i(8163));var h;!function(e){e[e.Always=0]="Always",e[e.FullScreen=1]="FullScreen",e[e.None=2]="None"}(h||(t.KeyboardSupport=h={}));const c="object"==typeof navigator?navigator:{};t.BrowserFeatures={clipboard:{writeText:l.isNative||document.queryCommandSupported&&document.queryCommandSupported("copy")||!!(c&&c.clipboard&&c.clipboard.writeText),readText:l.isNative||!!(c&&c.clipboard&&c.clipboard.readText)},keyboard:l.isNative||o.isStandalone()?h.Always:c.keyboard||o.isSafari?h.FullScreen:h.None,touch:"ontouchstart"in a.mainWindow||c.maxTouchPoints>0,pointerEvents:a.mainWindow.PointerEvent&&("ontouchstart"in a.mainWindow||navigator.maxTouchPoints>0)}},7093:function(e,t,i){var s,r=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),n=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),o=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&r(t,e,i);return n(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.SafeTriangle=t.DragAndDropObserver=t.ModifierKeyEmitter=t.DetectedFullscreenMode=t.Namespace=t.EventHelper=t.EventType=t.sharedMutationObserver=t.Dimension=t.WindowIntervalTimer=t.scheduleAtNextAnimationFrame=t.runAtThisOrScheduleAtNextAnimationFrame=t.WindowIdleValue=t.addStandardDisposableGenericMouseUpListener=t.addStandardDisposableGenericMouseDownListener=t.addStandardDisposableListener=t.onDidUnregisterWindow=t.onWillUnregisterWindow=t.onDidRegisterWindow=t.hasWindow=t.getWindowById=t.getWindowId=t.getWindowsCount=t.getWindows=t.getDocument=t.getWindow=t.registerWindow=void 0,t.clearNode=function(e){for(;e.firstChild;)e.firstChild.remove()},t.clearNodeRecursively=function e(t){for(;t.firstChild;){const i=t.firstChild;i.remove(),e(i)}},t.addDisposableListener=C,t.addDisposableGenericMouseDownListener=w,t.addDisposableGenericMouseMoveListener=function(e,i,s){return C(e,g.isIOS&&l.BrowserFeatures.pointerEvents?t.EventType.POINTER_MOVE:t.EventType.MOUSE_MOVE,i,s)},t.addDisposableGenericMouseUpListener=E,t.runWhenWindowIdle=function(e,t,i){return(0,d._runWhenIdle)(e,t,i)},t.disposableWindowInterval=function(e,t,i,s){let r=0;const n=e.setInterval((()=>{r++,("number"==typeof s&&r>=s||!0===t())&&o.dispose()}),i),o=(0,p.toDisposable)((()=>{e.clearInterval(n)}));return o},t.measure=function(e,i){return(0,t.scheduleAtNextAnimationFrame)(e,i,1e4)},t.modify=function(e,i){return(0,t.scheduleAtNextAnimationFrame)(e,i,-1e4)},t.addDisposableThrottledListener=function(e,t,i,s,r){return new T(e,t,i,s,r)},t.getComputedStyle=k,t.getClientArea=function e(i,s){const r=(0,t.getWindow)(i),n=r.document;if(i!==n.body)return new O(i.clientWidth,i.clientHeight);if(g.isIOS&&r?.visualViewport)return new O(r.visualViewport.width,r.visualViewport.height);if(r?.innerWidth&&r.innerHeight)return new O(r.innerWidth,r.innerHeight);if(n.body&&n.body.clientWidth&&n.body.clientHeight)return new O(n.body.clientWidth,n.body.clientHeight);if(n.documentElement&&n.documentElement.clientWidth&&n.documentElement.clientHeight)return new O(n.documentElement.clientWidth,n.documentElement.clientHeight);if(s)return e(s);throw new Error("Unable to figure out browser width and height")},t.getTopLeftOffset=I,t.size=function(e,t,i){"number"==typeof t&&(e.style.width=`${t}px`),"number"==typeof i&&(e.style.height=`${i}px`)},t.position=function(e,t,i,s,r,n="absolute"){"number"==typeof t&&(e.style.top=`${t}px`),"number"==typeof i&&(e.style.right=`${i}px`),"number"==typeof s&&(e.style.bottom=`${s}px`),"number"==typeof r&&(e.style.left=`${r}px`),e.style.position=n},t.getDomNodePagePosition=function(e){const i=e.getBoundingClientRect(),s=(0,t.getWindow)(e);return{left:i.left+s.scrollX,top:i.top+s.scrollY,width:i.width,height:i.height}},t.getDomNodeZoomLevel=function(e){let t=e,i=1;do{const e=k(t).zoom;null!=e&&"1"!==e&&(i*=e),t=t.parentElement}while(null!==t&&t!==t.ownerDocument.documentElement);return i},t.getTotalWidth=P,t.getContentWidth=function(e){const t=M.getBorderLeftWidth(e)+M.getBorderRightWidth(e),i=M.getPaddingLeft(e)+M.getPaddingRight(e);return e.offsetWidth-t-i},t.getTotalScrollWidth=x,t.getContentHeight=function(e){const t=M.getBorderTopWidth(e)+M.getBorderBottomWidth(e),i=M.getPaddingTop(e)+M.getPaddingBottom(e);return e.offsetHeight-t-i},t.getTotalHeight=function(e){const t=M.getMarginTop(e)+M.getMarginBottom(e);return e.offsetHeight+t},t.getLargestChildWidth=function(e,t){const i=t.map((t=>Math.max(x(t),P(t))+function(e,t){if(null===e)return 0;const i=I(e),s=I(t);return i.left-s.left}(t,e)||0));return Math.max(...i)},t.isAncestor=B,t.setParentFlowTo=function(e,t){e.dataset[N]=t.id},t.isAncestorUsingFlowTo=function(e,t){let i=e;for(;i;){if(i===t)return!0;if(Q(i)){const e=U(i);if(e){i=e;continue}}i=i.parentNode}return!1},t.findParentWithClass=F,t.hasParentWithClass=function(e,t,i){return!!F(e,t,i)},t.isShadowRoot=W,t.isInShadowDOM=function(e){return!!H(e)},t.getShadowRoot=H,t.getActiveElement=K,t.isActiveElement=function(e){return K()===e},t.isAncestorOfActiveElement=function(e){return B(K(),e)},t.isActiveDocument=function(e){return e.ownerDocument===z()},t.getActiveDocument=z,t.getActiveWindow=function(){const e=z();return e.defaultView?.window??v.mainWindow},t.isGlobalStylesheet=function(e){return j.has(e)},t.createStyleSheet2=function(){return new $},t.createStyleSheet=V,t.cloneGlobalStylesheets=function(e){const t=new p.DisposableStore;for(const[i,s]of j)t.add(G(i,s,e));return t},t.createMetaElement=function(e=v.mainWindow.document.head){return q("meta",e)},t.createLinkElement=function(e=v.mainWindow.document.head){return q("link",e)},t.createCSSRule=function e(t,i,s=Y()){if(s&&i){s.sheet?.insertRule(`${t} {${i}}`,0);for(const r of j.get(s)??[])e(t,i,r)}},t.removeCSSRulesContainingSelector=function e(t,i=Y()){if(!i)return;const s=Z(i),r=[];for(let e=0;e<s.length;e++){const i=s[e];J(i)&&-1!==i.selectorText.indexOf(t)&&r.push(e)}for(let e=r.length-1;e>=0;e--)i.sheet?.deleteRule(r[e]);for(const s of j.get(i)??[])e(t,s)},t.isHTMLElement=Q,t.isHTMLAnchorElement=function(e){return e instanceof HTMLAnchorElement||e instanceof(0,t.getWindow)(e).HTMLAnchorElement},t.isHTMLSpanElement=function(e){return e instanceof HTMLSpanElement||e instanceof(0,t.getWindow)(e).HTMLSpanElement},t.isHTMLTextAreaElement=function(e){return e instanceof HTMLTextAreaElement||e instanceof(0,t.getWindow)(e).HTMLTextAreaElement},t.isHTMLInputElement=function(e){return e instanceof HTMLInputElement||e instanceof(0,t.getWindow)(e).HTMLInputElement},t.isHTMLButtonElement=function(e){return e instanceof HTMLButtonElement||e instanceof(0,t.getWindow)(e).HTMLButtonElement},t.isHTMLDivElement=function(e){return e instanceof HTMLDivElement||e instanceof(0,t.getWindow)(e).HTMLDivElement},t.isSVGElement=function(e){return e instanceof SVGElement||e instanceof(0,t.getWindow)(e).SVGElement},t.isMouseEvent=function(e){return e instanceof MouseEvent||e instanceof(0,t.getWindow)(e).MouseEvent},t.isKeyboardEvent=function(e){return e instanceof KeyboardEvent||e instanceof(0,t.getWindow)(e).KeyboardEvent},t.isPointerEvent=function(e){return e instanceof PointerEvent||e instanceof(0,t.getWindow)(e).PointerEvent},t.isDragEvent=function(e){return e instanceof DragEvent||e instanceof(0,t.getWindow)(e).DragEvent},t.isEventLike=function(e){const t=e;return!(!t||"function"!=typeof t.preventDefault||"function"!=typeof t.stopPropagation)},t.saveParentsScrollTop=function(e){const t=[];for(let i=0;e&&e.nodeType===e.ELEMENT_NODE;i++)t[i]=e.scrollTop,e=e.parentNode;return t},t.restoreParentsScrollTop=function(e,t){for(let i=0;e&&e.nodeType===e.ELEMENT_NODE;i++)e.scrollTop!==t[i]&&(e.scrollTop=t[i]),e=e.parentNode},t.trackFocus=function(e){return new ee(e)},t.after=function(e,t){return e.after(t),t},t.append=te,t.prepend=function(e,t){return e.insertBefore(t,e.firstChild),t},t.reset=function(e,...t){e.innerText="",te(e,...t)},t.$=ne,t.join=function(e,t){const i=[];return e.forEach(((e,s)=>{s>0&&(t instanceof Node?i.push(t.cloneNode()):i.push(document.createTextNode(t))),i.push(e)})),i},t.setVisibility=function(e,...t){e?oe(...t):ae(...t)},t.show=oe,t.hide=ae,t.removeTabIndexAndUpdateFocus=function(e){if(e&&e.hasAttribute("tabIndex")){if(e.ownerDocument.activeElement===e){const t=function(e){for(;e&&e.nodeType===e.ELEMENT_NODE;){if(Q(e)&&e.hasAttribute("tabIndex"))return e;e=e.parentNode}return null}(e.parentElement);t?.focus()}e.removeAttribute("tabindex")}},t.finalHandler=function(e){return t=>{t.preventDefault(),t.stopPropagation(),e(t)}},t.domContentLoaded=function(e){return new Promise((t=>{if("complete"===e.document.readyState||e.document&&null!==e.document.body)t(void 0);else{const i=()=>{e.window.removeEventListener("DOMContentLoaded",i,!1),t()};e.window.addEventListener("DOMContentLoaded",i,!1)}}))},t.computeScreenAwareSize=function(e,t){const i=e.devicePixelRatio*t;return Math.max(1,Math.floor(i))/e.devicePixelRatio},t.windowOpenNoOpener=function(e){v.mainWindow.open(e,"_blank","noopener")},t.windowOpenPopup=function(e){const t=Math.floor(v.mainWindow.screenLeft+v.mainWindow.innerWidth/2-le/2),i=Math.floor(v.mainWindow.screenTop+v.mainWindow.innerHeight/2-he/2);v.mainWindow.open(e,"_blank",`width=${le},height=${he},top=${i},left=${t}`)},t.windowOpenWithSuccess=function(e,t=!0){const i=v.mainWindow.open();return!!i&&(t&&(i.opener=null),i.location.href=e,!0)},t.animate=function(e,i){const s=()=>{i(),r=(0,t.scheduleAtNextAnimationFrame)(e,s)};let r=(0,t.scheduleAtNextAnimationFrame)(e,s);return(0,p.toDisposable)((()=>r.dispose()))},t.asCSSPropertyValue=function(e){return`\'${e.replace(/\'/g,"%27")}\'`},t.asCssValueWithDefault=function e(t,i){if(void 0!==t){const s=t.match(/^\\s*var\\((.+)\\)$/);if(s){const t=s[1].split(",",2);return 2===t.length&&(i=e(t[1].trim(),i)),`var(${t[0]}, ${i})`}return t}return i},t.detectFullscreen=function(e){return e.document.fullscreenElement||e.document.webkitFullscreenElement||e.document.webkitIsFullScreen?{mode:ce.DOCUMENT,guess:!1}:e.innerHeight===e.screen.height?{mode:ce.BROWSER,guess:!1}:(g.isMacintosh||g.isLinux)&&e.outerHeight===e.screen.height&&e.outerWidth===e.screen.width?{mode:ce.BROWSER,guess:!0}:null},t.multibyteAwareBtoa=function(e){return btoa(function(e){const t=new Uint16Array(e.length);for(let i=0;i<t.length;i++)t[i]=e.charCodeAt(i);let i="";const s=new Uint8Array(t.buffer);for(let e=0;e<s.length;e++)i+=String.fromCharCode(s[e]);return i}(e))},t.getCookieValue=function(e){const t=document.cookie.match("(^|[^;]+)\\\\s*"+e+"\\\\s*=\\\\s*([^;]+)");return t?t.pop():void 0},t.h=function(e,...t){let i,s;Array.isArray(t[0])?(i={},s=t[0]):(i=t[0]||{},s=t[1]);const r=_e.exec(e);if(!r||!r.groups)throw new Error("Bad use of h");const n=r.groups.tag||"div",o=document.createElement(n);r.groups.id&&(o.id=r.groups.id);const a=[];if(r.groups.class)for(const e of r.groups.class.split("."))""!==e&&a.push(e);if(void 0!==i.className)for(const e of i.className.split("."))""!==e&&a.push(e);a.length>0&&(o.className=a.join(" "));const l={};if(r.groups.name&&(l[r.groups.name]=o),s)for(const e of s)Q(e)?o.appendChild(e):"string"==typeof e?o.append(e):"root"in e&&(Object.assign(l,e),o.appendChild(e.root));for(const[e,t]of Object.entries(i))if("className"!==e)if("style"===e)for(const[e,i]of Object.entries(t))o.style.setProperty(fe(e),"number"==typeof i?i+"px":""+i);else"tabIndex"===e?o.tabIndex=t:o.setAttribute(fe(e),t.toString());return l.root=o,l},t.svgElem=function(e,...t){let i,s;Array.isArray(t[0])?(i={},s=t[0]):(i=t[0]||{},s=t[1]);const r=_e.exec(e);if(!r||!r.groups)throw new Error("Bad use of h");const n=r.groups.tag||"div",o=document.createElementNS("http://www.w3.org/2000/svg",n);r.groups.id&&(o.id=r.groups.id);const a=[];if(r.groups.class)for(const e of r.groups.class.split("."))""!==e&&a.push(e);if(void 0!==i.className)for(const e of i.className.split("."))""!==e&&a.push(e);a.length>0&&(o.className=a.join(" "));const l={};if(r.groups.name&&(l[r.groups.name]=o),s)for(const e of s)Q(e)?o.appendChild(e):"string"==typeof e?o.append(e):"root"in e&&(Object.assign(l,e),o.appendChild(e.root));for(const[e,t]of Object.entries(i))if("className"!==e)if("style"===e)for(const[e,i]of Object.entries(t))o.style.setProperty(fe(e),"number"==typeof i?i+"px":""+i);else"tabIndex"===e?o.tabIndex=t:o.setAttribute(fe(e),t.toString());return l.root=o,l},t.copyAttributes=pe,t.trackAttributes=function(e,i,s){pe(e,i,s);const r=new p.DisposableStore;return r.add(t.sharedMutationObserver.observe(e,r,{attributes:!0,attributeFilter:s})((t=>{for(const s of t)"attributes"===s.type&&s.attributeName&&ge(e,i,s.attributeName)}))),r};const a=o(i(4333)),l=i(7745),h=i(5394),c=i(5964),d=i(1758),u=i(9807),_=o(i(802)),f=i(7883),p=i(7150),g=o(i(8163)),m=i(6304),v=i(4693),S=i(7704);s=function(){const e=new Map;(0,v.ensureCodeWindow)(v.mainWindow,1);const i={window:v.mainWindow,disposables:new p.DisposableStore};e.set(v.mainWindow.vscodeWindowId,i);const s=new _.Emitter,r=new _.Emitter,n=new _.Emitter;return{onDidRegisterWindow:s.event,onWillUnregisterWindow:n.event,onDidUnregisterWindow:r.event,registerWindow(i){if(e.has(i.vscodeWindowId))return p.Disposable.None;const o=new p.DisposableStore,a={window:i,disposables:o.add(new p.DisposableStore)};return e.set(i.vscodeWindowId,a),o.add((0,p.toDisposable)((()=>{e.delete(i.vscodeWindowId),r.fire(i)}))),o.add(C(i,t.EventType.BEFORE_UNLOAD,(()=>{n.fire(i)}))),s.fire(a),o},getWindows:()=>e.values(),getWindowsCount:()=>e.size,getWindowId:e=>e.vscodeWindowId,hasWindow:t=>e.has(t),getWindowById:function(t,s){return("number"==typeof t?e.get(t):void 0)??(s?i:void 0)},getWindow(e){const t=e;if(t?.ownerDocument?.defaultView)return t.ownerDocument.defaultView.window;const i=e;return i?.view?i.view.window:v.mainWindow},getDocument(e){const i=e;return(0,t.getWindow)(i).document}}}(),t.registerWindow=s.registerWindow,t.getWindow=s.getWindow,t.getDocument=s.getDocument,t.getWindows=s.getWindows,t.getWindowsCount=s.getWindowsCount,t.getWindowId=s.getWindowId,t.getWindowById=s.getWindowById,t.hasWindow=s.hasWindow,t.onDidRegisterWindow=s.onDidRegisterWindow,t.onWillUnregisterWindow=s.onWillUnregisterWindow,t.onDidUnregisterWindow=s.onDidUnregisterWindow;class b{constructor(e,t,i,s){this._node=e,this._type=t,this._handler=i,this._options=s||!1,this._node.addEventListener(this._type,this._handler,this._options)}dispose(){this._handler&&(this._node.removeEventListener(this._type,this._handler,this._options),this._node=null,this._handler=null)}}function C(e,t,i,s){return new b(e,t,i,s)}function y(e,t){return function(i){return t(new c.StandardMouseEvent(e,i))}}function w(e,i,s){return C(e,g.isIOS&&l.BrowserFeatures.pointerEvents?t.EventType.POINTER_DOWN:t.EventType.MOUSE_DOWN,i,s)}function E(e,i,s){return C(e,g.isIOS&&l.BrowserFeatures.pointerEvents?t.EventType.POINTER_UP:t.EventType.MOUSE_UP,i,s)}t.addStandardDisposableListener=function(e,i,s,r){let n=s;return"click"===i||"mousedown"===i||"contextmenu"===i?n=y((0,t.getWindow)(e),s):"keydown"!==i&&"keypress"!==i&&"keyup"!==i||(n=function(e){return function(t){return e(new h.StandardKeyboardEvent(t))}}(s)),C(e,i,n,r)},t.addStandardDisposableGenericMouseDownListener=function(e,i,s){return w(e,y((0,t.getWindow)(e),i),s)},t.addStandardDisposableGenericMouseUpListener=function(e,i,s){return E(e,y((0,t.getWindow)(e),i),s)};class D extends d.AbstractIdleValue{constructor(e,t){super(e,t)}}t.WindowIdleValue=D;class L extends d.IntervalTimer{constructor(e){super(),this.defaultTarget=e&&(0,t.getWindow)(e)}cancelAndSet(e,t,i){return super.cancelAndSet(e,t,i??this.defaultTarget)}}t.WindowIntervalTimer=L;class R{constructor(e,t=0){this._runner=e,this.priority=t,this._canceled=!1}dispose(){this._canceled=!0}execute(){if(!this._canceled)try{this._runner()}catch(e){(0,u.onUnexpectedError)(e)}}static sort(e,t){return t.priority-e.priority}}!function(){const e=new Map,i=new Map,s=new Map,r=new Map;t.scheduleAtNextAnimationFrame=(n,o,a=0)=>{const l=(0,t.getWindowId)(n),h=new R(o,a);let c=e.get(l);return c||(c=[],e.set(l,c)),c.push(h),s.get(l)||(s.set(l,!0),n.requestAnimationFrame((()=>(t=>{s.set(t,!1);const n=e.get(t)??[];for(i.set(t,n),e.set(t,[]),r.set(t,!0);n.length>0;)n.sort(R.sort),n.shift().execute();r.set(t,!1)})(l)))),h},t.runAtThisOrScheduleAtNextAnimationFrame=(e,s,n)=>{const o=(0,t.getWindowId)(e);if(r.get(o)){const e=new R(s,n);let t=i.get(o);return t||(t=[],i.set(o,t)),t.push(e),e}return(0,t.scheduleAtNextAnimationFrame)(e,s,n)}}();const A=function(e,t){return t};class T extends p.Disposable{constructor(e,t,i,s=A,r=8){super();let n=null,o=0;const a=this._register(new d.TimeoutTimer),l=()=>{o=(new Date).getTime(),i(n),n=null};this._register(C(e,t,(e=>{n=s(n,e);const t=(new Date).getTime()-o;t>=r?(a.cancel(),l()):a.setIfNotSet(l,r-t)})))}}function k(e){return(0,t.getWindow)(e).getComputedStyle(e,null)}class M{static convertToPixels(e,t){return parseFloat(t)||0}static getDimension(e,t,i){const s=k(e),r=s?s.getPropertyValue(t):"0";return M.convertToPixels(e,r)}static getBorderLeftWidth(e){return M.getDimension(e,"border-left-width","borderLeftWidth")}static getBorderRightWidth(e){return M.getDimension(e,"border-right-width","borderRightWidth")}static getBorderTopWidth(e){return M.getDimension(e,"border-top-width","borderTopWidth")}static getBorderBottomWidth(e){return M.getDimension(e,"border-bottom-width","borderBottomWidth")}static getPaddingLeft(e){return M.getDimension(e,"padding-left","paddingLeft")}static getPaddingRight(e){return M.getDimension(e,"padding-right","paddingRight")}static getPaddingTop(e){return M.getDimension(e,"padding-top","paddingTop")}static getPaddingBottom(e){return M.getDimension(e,"padding-bottom","paddingBottom")}static getMarginLeft(e){return M.getDimension(e,"margin-left","marginLeft")}static getMarginTop(e){return M.getDimension(e,"margin-top","marginTop")}static getMarginRight(e){return M.getDimension(e,"margin-right","marginRight")}static getMarginBottom(e){return M.getDimension(e,"margin-bottom","marginBottom")}}class O{static{this.None=new O(0,0)}constructor(e,t){this.width=e,this.height=t}with(e=this.width,t=this.height){return e!==this.width||t!==this.height?new O(e,t):this}static is(e){return"object"==typeof e&&"number"==typeof e.height&&"number"==typeof e.width}static lift(e){return e instanceof O?e:new O(e.width,e.height)}static equals(e,t){return e===t||!(!e||!t)&&e.width===t.width&&e.height===t.height}}function I(e){let t=e.offsetParent,i=e.offsetTop,s=e.offsetLeft;for(;null!==(e=e.parentNode)&&e!==e.ownerDocument.body&&e!==e.ownerDocument.documentElement;){i-=e.scrollTop;const r=W(e)?null:k(e);r&&(s-="rtl"!==r.direction?e.scrollLeft:-e.scrollLeft),e===t&&(s+=M.getBorderLeftWidth(e),i+=M.getBorderTopWidth(e),i+=e.offsetTop,s+=e.offsetLeft,t=e.offsetParent)}return{left:s,top:i}}function P(e){const t=M.getMarginLeft(e)+M.getMarginRight(e);return e.offsetWidth+t}function x(e){const t=M.getMarginLeft(e)+M.getMarginRight(e);return e.scrollWidth+t}function B(e,t){return Boolean(t?.contains(e))}t.Dimension=O;const N="parentFlowToElementId";function U(e){const t=e.dataset[N];return"string"==typeof t?e.ownerDocument.getElementById(t):null}function F(e,t,i){for(;e&&e.nodeType===e.ELEMENT_NODE;){if(e.classList.contains(t))return e;if(i)if("string"==typeof i){if(e.classList.contains(i))return null}else if(e===i)return null;e=e.parentNode}return null}function W(e){return e&&!!e.host&&!!e.mode}function H(e){for(;e.parentNode;){if(e===e.ownerDocument?.body)return null;e=e.parentNode}return W(e)?e:null}function K(){let e=z().activeElement;for(;e?.shadowRoot;)e=e.shadowRoot.activeElement;return e}function z(){return(0,t.getWindowsCount)()<=1?v.mainWindow.document:Array.from((0,t.getWindows)()).map((({window:e})=>e.document)).find((e=>e.hasFocus()))??v.mainWindow.document}const j=new Map;class ${constructor(){this._currentCssStyle="",this._styleSheet=void 0}setStyle(e){e!==this._currentCssStyle&&(this._currentCssStyle=e,this._styleSheet?this._styleSheet.innerText=e:this._styleSheet=V(v.mainWindow.document.head,(t=>t.innerText=e)))}dispose(){this._styleSheet&&(this._styleSheet.remove(),this._styleSheet=void 0)}}function V(e=v.mainWindow.document.head,i,s){const r=document.createElement("style");if(r.type="text/css",r.media="screen",i?.(r),e.appendChild(r),s&&s.add((0,p.toDisposable)((()=>r.remove()))),e===v.mainWindow.document.head){const e=new Set;j.set(r,e);for(const{window:i,disposables:n}of(0,t.getWindows)()){if(i===v.mainWindow)continue;const t=n.add(G(r,e,i));s?.add(t)}}return r}function G(e,i,s){const r=new p.DisposableStore,n=e.cloneNode(!0);s.document.head.appendChild(n),r.add((0,p.toDisposable)((()=>n.remove())));for(const t of Z(e))n.sheet?.insertRule(t.cssText,n.sheet?.cssRules.length);return r.add(t.sharedMutationObserver.observe(e,r,{childList:!0})((()=>{n.textContent=e.textContent}))),i.add(n),r.add((0,p.toDisposable)((()=>i.delete(n)))),r}function q(e,t=v.mainWindow.document.head){const i=document.createElement(e);return t.appendChild(i),i}t.sharedMutationObserver=new class{constructor(){this.mutationObservers=new Map}observe(e,t,i){let s=this.mutationObservers.get(e);s||(s=new Map,this.mutationObservers.set(e,s));const r=(0,m.hash)(i);let n=s.get(r);if(n)n.users+=1;else{const o=new _.Emitter,a=new MutationObserver((e=>o.fire(e)));a.observe(e,i);const l=n={users:1,observer:a,onDidMutate:o.event};t.add((0,p.toDisposable)((()=>{l.users-=1,0===l.users&&(o.dispose(),a.disconnect(),s?.delete(r),0===s?.size&&this.mutationObservers.delete(e))}))),s.set(r,n)}return n.onDidMutate}};let X=null;function Y(){return X||(X=V()),X}function Z(e){return e?.sheet?.rules?e.sheet.rules:e?.sheet?.cssRules?e.sheet.cssRules:[]}function J(e){return"string"==typeof e.selectorText}function Q(e){return e instanceof HTMLElement||e instanceof(0,t.getWindow)(e).HTMLElement}t.EventType={CLICK:"click",AUXCLICK:"auxclick",DBLCLICK:"dblclick",MOUSE_UP:"mouseup",MOUSE_DOWN:"mousedown",MOUSE_OVER:"mouseover",MOUSE_MOVE:"mousemove",MOUSE_OUT:"mouseout",MOUSE_ENTER:"mouseenter",MOUSE_LEAVE:"mouseleave",MOUSE_WHEEL:"wheel",POINTER_UP:"pointerup",POINTER_DOWN:"pointerdown",POINTER_MOVE:"pointermove",POINTER_LEAVE:"pointerleave",CONTEXT_MENU:"contextmenu",WHEEL:"wheel",KEY_DOWN:"keydown",KEY_PRESS:"keypress",KEY_UP:"keyup",LOAD:"load",BEFORE_UNLOAD:"beforeunload",UNLOAD:"unload",PAGE_SHOW:"pageshow",PAGE_HIDE:"pagehide",PASTE:"paste",ABORT:"abort",ERROR:"error",RESIZE:"resize",SCROLL:"scroll",FULLSCREEN_CHANGE:"fullscreenchange",WK_FULLSCREEN_CHANGE:"webkitfullscreenchange",SELECT:"select",CHANGE:"change",SUBMIT:"submit",RESET:"reset",FOCUS:"focus",FOCUS_IN:"focusin",FOCUS_OUT:"focusout",BLUR:"blur",INPUT:"input",STORAGE:"storage",DRAG_START:"dragstart",DRAG:"drag",DRAG_ENTER:"dragenter",DRAG_LEAVE:"dragleave",DRAG_OVER:"dragover",DROP:"drop",DRAG_END:"dragend",ANIMATION_START:a.isWebKit?"webkitAnimationStart":"animationstart",ANIMATION_END:a.isWebKit?"webkitAnimationEnd":"animationend",ANIMATION_ITERATION:a.isWebKit?"webkitAnimationIteration":"animationiteration"},t.EventHelper={stop:(e,t)=>(e.preventDefault(),t&&e.stopPropagation(),e)};class ee extends p.Disposable{static hasFocusWithin(e){if(Q(e)){const t=H(e);return B(t?t.activeElement:e.ownerDocument.activeElement,e)}{const t=e;return B(t.document.activeElement,t.document)}}constructor(e){super(),this._onDidFocus=this._register(new _.Emitter),this.onDidFocus=this._onDidFocus.event,this._onDidBlur=this._register(new _.Emitter),this.onDidBlur=this._onDidBlur.event;let i=ee.hasFocusWithin(e),s=!1;const r=()=>{s=!1,i||(i=!0,this._onDidFocus.fire())},n=()=>{i&&(s=!0,(Q(e)?(0,t.getWindow)(e):e).setTimeout((()=>{s&&(s=!1,i=!1,this._onDidBlur.fire())}),0))};this._refreshStateHandler=()=>{ee.hasFocusWithin(e)!==i&&(i?n():r())},this._register(C(e,t.EventType.FOCUS,r,!0)),this._register(C(e,t.EventType.BLUR,n,!0)),Q(e)&&(this._register(C(e,t.EventType.FOCUS_IN,(()=>this._refreshStateHandler()))),this._register(C(e,t.EventType.FOCUS_OUT,(()=>this._refreshStateHandler()))))}refreshState(){this._refreshStateHandler()}}function te(e,...t){if(e.append(...t),1===t.length&&"string"!=typeof t[0])return t[0]}const ie=/([\\w\\-]+)?(#([\\w\\-]+))?((\\.([\\w\\-]+))*)/;var se;function re(e,t,i,...s){const r=ie.exec(t);if(!r)throw new Error("Bad use of emmet");const n=r[1]||"div";let o;return o=e!==se.HTML?document.createElementNS(e,n):document.createElement(n),r[3]&&(o.id=r[3]),r[4]&&(o.className=r[4].replace(/\\./g," ").trim()),i&&Object.entries(i).forEach((([e,t])=>{void 0!==t&&(/^on\\w+$/.test(e)?o[e]=t:"selected"===e?t&&o.setAttribute(e,"true"):o.setAttribute(e,t))})),o.append(...s),o}function ne(e,t,...i){return re(se.HTML,e,t,...i)}function oe(...e){for(const t of e)t.style.display="",t.removeAttribute("aria-hidden")}function ae(...e){for(const t of e)t.style.display="none",t.setAttribute("aria-hidden","true")}!function(e){e.HTML="http://www.w3.org/1999/xhtml",e.SVG="http://www.w3.org/2000/svg"}(se||(t.Namespace=se={})),ne.SVG=function(e,t,...i){return re(se.SVG,e,t,...i)};const le=780,he=640;var ce;!function(e){e[e.DOCUMENT=1]="DOCUMENT",e[e.BROWSER=2]="BROWSER"}(ce||(t.DetectedFullscreenMode=ce={}));class de extends _.Emitter{constructor(){super(),this._subscriptions=new p.DisposableStore,this._keyStatus={altKey:!1,shiftKey:!1,ctrlKey:!1,metaKey:!1},this._subscriptions.add(_.Event.runAndSubscribe(t.onDidRegisterWindow,(({window:e,disposables:t})=>this.registerListeners(e,t)),{window:v.mainWindow,disposables:this._subscriptions}))}registerListeners(e,t){t.add(C(e,"keydown",(e=>{if(e.defaultPrevented)return;const t=new h.StandardKeyboardEvent(e);if(t.keyCode!==f.KeyCode.Alt||!e.repeat){if(e.altKey&&!this._keyStatus.altKey)this._keyStatus.lastKeyPressed="alt";else if(e.ctrlKey&&!this._keyStatus.ctrlKey)this._keyStatus.lastKeyPressed="ctrl";else if(e.metaKey&&!this._keyStatus.metaKey)this._keyStatus.lastKeyPressed="meta";else if(e.shiftKey&&!this._keyStatus.shiftKey)this._keyStatus.lastKeyPressed="shift";else{if(t.keyCode===f.KeyCode.Alt)return;this._keyStatus.lastKeyPressed=void 0}this._keyStatus.altKey=e.altKey,this._keyStatus.ctrlKey=e.ctrlKey,this._keyStatus.metaKey=e.metaKey,this._keyStatus.shiftKey=e.shiftKey,this._keyStatus.lastKeyPressed&&(this._keyStatus.event=e,this.fire(this._keyStatus))}}),!0)),t.add(C(e,"keyup",(e=>{e.defaultPrevented||(!e.altKey&&this._keyStatus.altKey?this._keyStatus.lastKeyReleased="alt":!e.ctrlKey&&this._keyStatus.ctrlKey?this._keyStatus.lastKeyReleased="ctrl":!e.metaKey&&this._keyStatus.metaKey?this._keyStatus.lastKeyReleased="meta":!e.shiftKey&&this._keyStatus.shiftKey?this._keyStatus.lastKeyReleased="shift":this._keyStatus.lastKeyReleased=void 0,this._keyStatus.lastKeyPressed!==this._keyStatus.lastKeyReleased&&(this._keyStatus.lastKeyPressed=void 0),this._keyStatus.altKey=e.altKey,this._keyStatus.ctrlKey=e.ctrlKey,this._keyStatus.metaKey=e.metaKey,this._keyStatus.shiftKey=e.shiftKey,this._keyStatus.lastKeyReleased&&(this._keyStatus.event=e,this.fire(this._keyStatus)))}),!0)),t.add(C(e.document.body,"mousedown",(()=>{this._keyStatus.lastKeyPressed=void 0}),!0)),t.add(C(e.document.body,"mouseup",(()=>{this._keyStatus.lastKeyPressed=void 0}),!0)),t.add(C(e.document.body,"mousemove",(e=>{e.buttons&&(this._keyStatus.lastKeyPressed=void 0)}),!0)),t.add(C(e,"blur",(()=>{this.resetKeyStatus()})))}get keyStatus(){return this._keyStatus}get isModifierPressed(){return this._keyStatus.altKey||this._keyStatus.ctrlKey||this._keyStatus.metaKey||this._keyStatus.shiftKey}resetKeyStatus(){this.doResetKeyStatus(),this.fire(this._keyStatus)}doResetKeyStatus(){this._keyStatus={altKey:!1,shiftKey:!1,ctrlKey:!1,metaKey:!1}}static getInstance(){return de.instance||(de.instance=new de),de.instance}dispose(){super.dispose(),this._subscriptions.dispose()}}t.ModifierKeyEmitter=de;class ue extends p.Disposable{constructor(e,t){super(),this.element=e,this.callbacks=t,this.counter=0,this.dragStartTime=0,this.registerListeners()}registerListeners(){this.callbacks.onDragStart&&this._register(C(this.element,t.EventType.DRAG_START,(e=>{this.callbacks.onDragStart?.(e)}))),this.callbacks.onDrag&&this._register(C(this.element,t.EventType.DRAG,(e=>{this.callbacks.onDrag?.(e)}))),this._register(C(this.element,t.EventType.DRAG_ENTER,(e=>{this.counter++,this.dragStartTime=e.timeStamp,this.callbacks.onDragEnter?.(e)}))),this._register(C(this.element,t.EventType.DRAG_OVER,(e=>{e.preventDefault(),this.callbacks.onDragOver?.(e,e.timeStamp-this.dragStartTime)}))),this._register(C(this.element,t.EventType.DRAG_LEAVE,(e=>{this.counter--,0===this.counter&&(this.dragStartTime=0,this.callbacks.onDragLeave?.(e))}))),this._register(C(this.element,t.EventType.DRAG_END,(e=>{this.counter=0,this.dragStartTime=0,this.callbacks.onDragEnd?.(e)}))),this._register(C(this.element,t.EventType.DROP,(e=>{this.counter=0,this.dragStartTime=0,this.callbacks.onDrop?.(e)})))}}t.DragAndDropObserver=ue;const _e=/(?<tag>[\\w\\-]+)?(?:#(?<id>[\\w\\-]+))?(?<class>(?:\\.(?:[\\w\\-]+))*)(?:@(?<name>(?:[\\w\\_])+))?/;function fe(e){return e.replace(/([a-z])([A-Z])/g,"$1-$2").toLowerCase()}function pe(e,t,i){for(const{name:s,value:r}of e.attributes)i&&!i.includes(s)||t.setAttribute(s,r)}function ge(e,t,i){const s=e.getAttribute(i);s?t.setAttribute(i,s):t.removeAttribute(i)}t.SafeTriangle=class{constructor(e,t,i){this.originX=e,this.originY=t,this.triangles=[];const{top:s,left:r,right:n,bottom:o}=i.getBoundingClientRect(),a=this.triangles;let l=0;a[l++]=r,a[l++]=s,a[l++]=n,a[l++]=s,a[l++]=r,a[l++]=s,a[l++]=r,a[l++]=o,a[l++]=n,a[l++]=s,a[l++]=n,a[l++]=o,a[l++]=r,a[l++]=o,a[l++]=n,a[l++]=o}contains(e,t){const{triangles:i,originX:s,originY:r}=this;for(let n=0;n<4;n++)if((0,S.isPointWithinTriangle)(e,t,s,r,i[2*n],i[2*n+1],i[2*n+2],i[2*n+3]))return!0;return!1}}},9675:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.FastDomNode=void 0,t.createFastDomNode=function(e){return new i(e)};class i{constructor(e){this.domNode=e,this._maxWidth="",this._width="",this._height="",this._top="",this._left="",this._bottom="",this._right="",this._paddingTop="",this._paddingLeft="",this._paddingBottom="",this._paddingRight="",this._fontFamily="",this._fontWeight="",this._fontSize="",this._fontStyle="",this._fontFeatureSettings="",this._fontVariationSettings="",this._textDecoration="",this._lineHeight="",this._letterSpacing="",this._className="",this._display="",this._position="",this._visibility="",this._color="",this._backgroundColor="",this._layerHint=!1,this._contain="none",this._boxShadow=""}setMaxWidth(e){const t=s(e);this._maxWidth!==t&&(this._maxWidth=t,this.domNode.style.maxWidth=this._maxWidth)}setWidth(e){const t=s(e);this._width!==t&&(this._width=t,this.domNode.style.width=this._width)}setHeight(e){const t=s(e);this._height!==t&&(this._height=t,this.domNode.style.height=this._height)}setTop(e){const t=s(e);this._top!==t&&(this._top=t,this.domNode.style.top=this._top)}setLeft(e){const t=s(e);this._left!==t&&(this._left=t,this.domNode.style.left=this._left)}setBottom(e){const t=s(e);this._bottom!==t&&(this._bottom=t,this.domNode.style.bottom=this._bottom)}setRight(e){const t=s(e);this._right!==t&&(this._right=t,this.domNode.style.right=this._right)}setPaddingTop(e){const t=s(e);this._paddingTop!==t&&(this._paddingTop=t,this.domNode.style.paddingTop=this._paddingTop)}setPaddingLeft(e){const t=s(e);this._paddingLeft!==t&&(this._paddingLeft=t,this.domNode.style.paddingLeft=this._paddingLeft)}setPaddingBottom(e){const t=s(e);this._paddingBottom!==t&&(this._paddingBottom=t,this.domNode.style.paddingBottom=this._paddingBottom)}setPaddingRight(e){const t=s(e);this._paddingRight!==t&&(this._paddingRight=t,this.domNode.style.paddingRight=this._paddingRight)}setFontFamily(e){this._fontFamily!==e&&(this._fontFamily=e,this.domNode.style.fontFamily=this._fontFamily)}setFontWeight(e){this._fontWeight!==e&&(this._fontWeight=e,this.domNode.style.fontWeight=this._fontWeight)}setFontSize(e){const t=s(e);this._fontSize!==t&&(this._fontSize=t,this.domNode.style.fontSize=this._fontSize)}setFontStyle(e){this._fontStyle!==e&&(this._fontStyle=e,this.domNode.style.fontStyle=this._fontStyle)}setFontFeatureSettings(e){this._fontFeatureSettings!==e&&(this._fontFeatureSettings=e,this.domNode.style.fontFeatureSettings=this._fontFeatureSettings)}setFontVariationSettings(e){this._fontVariationSettings!==e&&(this._fontVariationSettings=e,this.domNode.style.fontVariationSettings=this._fontVariationSettings)}setTextDecoration(e){this._textDecoration!==e&&(this._textDecoration=e,this.domNode.style.textDecoration=this._textDecoration)}setLineHeight(e){const t=s(e);this._lineHeight!==t&&(this._lineHeight=t,this.domNode.style.lineHeight=this._lineHeight)}setLetterSpacing(e){const t=s(e);this._letterSpacing!==t&&(this._letterSpacing=t,this.domNode.style.letterSpacing=this._letterSpacing)}setClassName(e){this._className!==e&&(this._className=e,this.domNode.className=this._className)}toggleClassName(e,t){this.domNode.classList.toggle(e,t),this._className=this.domNode.className}setDisplay(e){this._display!==e&&(this._display=e,this.domNode.style.display=this._display)}setPosition(e){this._position!==e&&(this._position=e,this.domNode.style.position=this._position)}setVisibility(e){this._visibility!==e&&(this._visibility=e,this.domNode.style.visibility=this._visibility)}setColor(e){this._color!==e&&(this._color=e,this.domNode.style.color=this._color)}setBackgroundColor(e){this._backgroundColor!==e&&(this._backgroundColor=e,this.domNode.style.backgroundColor=this._backgroundColor)}setLayerHinting(e){this._layerHint!==e&&(this._layerHint=e,this.domNode.style.transform=this._layerHint?"translate3d(0px, 0px, 0px)":"")}setBoxShadow(e){this._boxShadow!==e&&(this._boxShadow=e,this.domNode.style.boxShadow=e)}setContain(e){this._contain!==e&&(this._contain=e,this.domNode.style.contain=this._contain)}setAttribute(e,t){this.domNode.setAttribute(e,t)}removeAttribute(e){this.domNode.removeAttribute(e)}appendChild(e){this.domNode.appendChild(e.domNode)}removeChild(e){this.domNode.removeChild(e.domNode)}}function s(e){return"number"==typeof e?`${e}px`:e}t.FastDomNode=i},8328:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.GlobalPointerMoveMonitor=void 0;const o=n(i(7093)),a=i(7150);t.GlobalPointerMoveMonitor=class{constructor(){this._hooks=new a.DisposableStore,this._pointerMoveCallback=null,this._onStopCallback=null}dispose(){this.stopMonitoring(!1),this._hooks.dispose()}stopMonitoring(e,t){if(!this.isMonitoring())return;this._hooks.clear(),this._pointerMoveCallback=null;const i=this._onStopCallback;this._onStopCallback=null,e&&i&&i(t)}isMonitoring(){return!!this._pointerMoveCallback}startMonitoring(e,t,i,s,r){this.isMonitoring()&&this.stopMonitoring(!1),this._pointerMoveCallback=s,this._onStopCallback=r;let n=e;try{e.setPointerCapture(t),this._hooks.add((0,a.toDisposable)((()=>{try{e.releasePointerCapture(t)}catch(e){}})))}catch(t){n=o.getWindow(e)}this._hooks.add(o.addDisposableListener(n,o.EventType.POINTER_MOVE,(e=>{e.buttons===i?(e.preventDefault(),this._pointerMoveCallback(e)):this.stopMonitoring(!0)}))),this._hooks.add(o.addDisposableListener(n,o.EventType.POINTER_UP,(e=>this.stopMonitoring(!0))))}}},6609:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.IframeUtils=void 0,t.parentOriginHash=async function(e,t){if(!crypto.subtle)throw new Error("\'crypto.subtle\' is not available so webviews will not work. This is likely because the editor is not running in a secure context (https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts).");const i=JSON.stringify({parentOrigin:e,salt:t}),s=(new TextEncoder).encode(i);return function(e){const t=Array.from(new Uint8Array(e)).map((e=>e.toString(16).padStart(2,"0"))).join("");return BigInt(`0x${t}`).toString(32).padStart(52,"0")}(await crypto.subtle.digest("sha-256",s))};const i=new WeakMap;function s(e){if(!e.parent||e.parent===e)return null;try{const t=e.location,i=e.parent.location;if("null"!==t.origin&&"null"!==i.origin&&t.origin!==i.origin)return null}catch(e){return null}return e.parent}t.IframeUtils=class{static getSameOriginWindowChain(e){let t=i.get(e);if(!t){t=[],i.set(e,t);let r,n=e;do{r=s(n),r?t.push({window:new WeakRef(n),iframeElement:n.frameElement||null}):t.push({window:new WeakRef(n),iframeElement:null}),n=r}while(n)}return t.slice(0)}static getPositionOfChildWindowRelativeToAncestorWindow(e,t){if(!t||e===t)return{top:0,left:0};let i=0,s=0;const r=this.getSameOriginWindowChain(e);for(const e of r){const r=e.window.deref();if(i+=r?.scrollY??0,s+=r?.scrollX??0,r===t)break;if(!e.iframeElement)break;const n=e.iframeElement.getBoundingClientRect();i+=n.top,s+=n.left}return{top:i,left:s}}}},5394:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.StandardKeyboardEvent=void 0,t.printKeyboardEvent=function(e){const t=[];return e.ctrlKey&&t.push("ctrl"),e.shiftKey&&t.push("shift"),e.altKey&&t.push("alt"),e.metaKey&&t.push("meta"),`modifiers: [${t.join(",")}], code: ${e.code}, keyCode: ${e.keyCode}, key: ${e.key}`},t.printStandardKeyboardEvent=function(e){const t=[];return e.ctrlKey&&t.push("ctrl"),e.shiftKey&&t.push("shift"),e.altKey&&t.push("alt"),e.metaKey&&t.push("meta"),`modifiers: [${t.join(",")}], code: ${e.code}, keyCode: ${e.keyCode} (\'${a.KeyCodeUtils.toString(e.keyCode)}\')`};const o=n(i(4333)),a=i(7883),l=i(2811),h=n(i(8163)),c=h.isMacintosh?a.KeyMod.WinCtrl:a.KeyMod.CtrlCmd,d=a.KeyMod.Alt,u=a.KeyMod.Shift,_=h.isMacintosh?a.KeyMod.CtrlCmd:a.KeyMod.WinCtrl;t.StandardKeyboardEvent=class{constructor(e){this._standardKeyboardEventBrand=!0;const t=e;this.browserEvent=t,this.target=t.target,this.ctrlKey=t.ctrlKey,this.shiftKey=t.shiftKey,this.altKey=t.altKey,this.metaKey=t.metaKey,this.altGraphKey=t.getModifierState?.("AltGraph"),this.keyCode=function(e){if(e.charCode){const t=String.fromCharCode(e.charCode).toUpperCase();return a.KeyCodeUtils.fromString(t)}const t=e.keyCode;if(3===t)return a.KeyCode.PauseBreak;if(o.isFirefox)switch(t){case 59:return a.KeyCode.Semicolon;case 60:if(h.isLinux)return a.KeyCode.IntlBackslash;break;case 61:return a.KeyCode.Equal;case 107:return a.KeyCode.NumpadAdd;case 109:return a.KeyCode.NumpadSubtract;case 173:return a.KeyCode.Minus;case 224:if(h.isMacintosh)return a.KeyCode.Meta}else if(o.isWebKit){if(h.isMacintosh&&93===t)return a.KeyCode.Meta;if(!h.isMacintosh&&92===t)return a.KeyCode.Meta}return a.EVENT_KEY_CODE_MAP[t]||a.KeyCode.Unknown}(t),this.code=t.code,this.ctrlKey=this.ctrlKey||this.keyCode===a.KeyCode.Ctrl,this.altKey=this.altKey||this.keyCode===a.KeyCode.Alt,this.shiftKey=this.shiftKey||this.keyCode===a.KeyCode.Shift,this.metaKey=this.metaKey||this.keyCode===a.KeyCode.Meta,this._asKeybinding=this._computeKeybinding(),this._asKeyCodeChord=this._computeKeyCodeChord()}preventDefault(){this.browserEvent&&this.browserEvent.preventDefault&&this.browserEvent.preventDefault()}stopPropagation(){this.browserEvent&&this.browserEvent.stopPropagation&&this.browserEvent.stopPropagation()}toKeyCodeChord(){return this._asKeyCodeChord}equals(e){return this._asKeybinding===e}_computeKeybinding(){let e=a.KeyCode.Unknown;this.keyCode!==a.KeyCode.Ctrl&&this.keyCode!==a.KeyCode.Shift&&this.keyCode!==a.KeyCode.Alt&&this.keyCode!==a.KeyCode.Meta&&(e=this.keyCode);let t=0;return this.ctrlKey&&(t|=c),this.altKey&&(t|=d),this.shiftKey&&(t|=u),this.metaKey&&(t|=_),t|=e,t}_computeKeyCodeChord(){let e=a.KeyCode.Unknown;return this.keyCode!==a.KeyCode.Ctrl&&this.keyCode!==a.KeyCode.Shift&&this.keyCode!==a.KeyCode.Alt&&this.keyCode!==a.KeyCode.Meta&&(e=this.keyCode),new l.KeyCodeChord(this.ctrlKey,this.shiftKey,this.altKey,this.metaKey,e)}}},5964:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.StandardWheelEvent=t.DragMouseEvent=t.StandardMouseEvent=void 0;const o=n(i(4333)),a=i(6609),l=n(i(8163));class h{constructor(e,t){this.timestamp=Date.now(),this.browserEvent=t,this.leftButton=0===t.button,this.middleButton=1===t.button,this.rightButton=2===t.button,this.buttons=t.buttons,this.target=t.target,this.detail=t.detail||1,"dblclick"===t.type&&(this.detail=2),this.ctrlKey=t.ctrlKey,this.shiftKey=t.shiftKey,this.altKey=t.altKey,this.metaKey=t.metaKey,"number"==typeof t.pageX?(this.posx=t.pageX,this.posy=t.pageY):(this.posx=t.clientX+this.target.ownerDocument.body.scrollLeft+this.target.ownerDocument.documentElement.scrollLeft,this.posy=t.clientY+this.target.ownerDocument.body.scrollTop+this.target.ownerDocument.documentElement.scrollTop);const i=a.IframeUtils.getPositionOfChildWindowRelativeToAncestorWindow(e,t.view);this.posx-=i.left,this.posy-=i.top}preventDefault(){this.browserEvent.preventDefault()}stopPropagation(){this.browserEvent.stopPropagation()}}t.StandardMouseEvent=h,t.DragMouseEvent=class extends h{constructor(e,t){super(e,t),this.dataTransfer=t.dataTransfer}},t.StandardWheelEvent=class{constructor(e,t=0,i=0){this.browserEvent=e||null,this.target=e?e.target||e.targetNode||e.srcElement:null,this.deltaY=i,this.deltaX=t;let s=!1;if(o.isChrome){const e=navigator.userAgent.match(/Chrome\\/(\\d+)/);s=(e?parseInt(e[1]):123)<=122}if(e){const t=e,i=e,r=e.view?.devicePixelRatio||1;if(void 0!==t.wheelDeltaY)this.deltaY=s?t.wheelDeltaY/(120*r):t.wheelDeltaY/120;else if(void 0!==i.VERTICAL_AXIS&&i.axis===i.VERTICAL_AXIS)this.deltaY=-i.detail/3;else if("wheel"===e.type){const t=e;t.deltaMode===t.DOM_DELTA_LINE?o.isFirefox&&!l.isMacintosh?this.deltaY=-e.deltaY/3:this.deltaY=-e.deltaY:this.deltaY=-e.deltaY/40}if(void 0!==t.wheelDeltaX)o.isSafari&&l.isWindows?this.deltaX=-t.wheelDeltaX/120:this.deltaX=s?t.wheelDeltaX/(120*r):t.wheelDeltaX/120;else if(void 0!==i.HORIZONTAL_AXIS&&i.axis===i.HORIZONTAL_AXIS)this.deltaX=-e.detail/3;else if("wheel"===e.type){const t=e;t.deltaMode===t.DOM_DELTA_LINE?o.isFirefox&&!l.isMacintosh?this.deltaX=-e.deltaX/3:this.deltaX=-e.deltaX:this.deltaX=-e.deltaX/40}0===this.deltaY&&0===this.deltaX&&e.wheelDelta&&(this.deltaY=s?e.wheelDelta/(120*r):e.wheelDelta/120)}}preventDefault(){this.browserEvent?.preventDefault()}stopPropagation(){this.browserEvent?.stopPropagation()}}},8594:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__decorate||function(e,t,i,s){var r,n=arguments.length,o=n<3?t:null===s?s=Object.getOwnPropertyDescriptor(t,i):s;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,i,s);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(n<3?r(o):n>3?r(t,i,o):r(t,i))||o);return n>3&&o&&Object.defineProperty(t,i,o),o},o=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.Gesture=t.EventType=void 0;const a=o(i(7093)),l=i(4693),h=o(i(3058)),c=i(4838),d=i(802),u=i(7150),_=i(6317);var f;!function(e){e.Tap="-xterm-gesturetap",e.Change="-xterm-gesturechange",e.Start="-xterm-gesturestart",e.End="-xterm-gesturesend",e.Contextmenu="-xterm-gesturecontextmenu"}(f||(t.EventType=f={}));class p extends u.Disposable{static{this.SCROLL_FRICTION=-.005}static{this.HOLD_DELAY=700}static{this.CLEAR_TAP_COUNT_TIME=400}constructor(){super(),this.dispatched=!1,this.targets=new _.LinkedList,this.ignoreTargets=new _.LinkedList,this.activeTouches={},this.handle=null,this._lastSetTapCountTime=0,this._register(d.Event.runAndSubscribe(a.onDidRegisterWindow,(({window:e,disposables:t})=>{t.add(a.addDisposableListener(e.document,"touchstart",(e=>this.onTouchStart(e)),{passive:!1})),t.add(a.addDisposableListener(e.document,"touchend",(t=>this.onTouchEnd(e,t)))),t.add(a.addDisposableListener(e.document,"touchmove",(e=>this.onTouchMove(e)),{passive:!1}))}),{window:l.mainWindow,disposables:this._store}))}static addTarget(e){if(!p.isTouchDevice())return u.Disposable.None;p.INSTANCE||(p.INSTANCE=(0,u.markAsSingleton)(new p));const t=p.INSTANCE.targets.push(e);return(0,u.toDisposable)(t)}static ignoreTarget(e){if(!p.isTouchDevice())return u.Disposable.None;p.INSTANCE||(p.INSTANCE=(0,u.markAsSingleton)(new p));const t=p.INSTANCE.ignoreTargets.push(e);return(0,u.toDisposable)(t)}static isTouchDevice(){return"ontouchstart"in l.mainWindow||navigator.maxTouchPoints>0}dispose(){this.handle&&(this.handle.dispose(),this.handle=null),super.dispose()}onTouchStart(e){const t=Date.now();this.handle&&(this.handle.dispose(),this.handle=null);for(let i=0,s=e.targetTouches.length;i<s;i++){const s=e.targetTouches.item(i);this.activeTouches[s.identifier]={id:s.identifier,initialTarget:s.target,initialTimeStamp:t,initialPageX:s.pageX,initialPageY:s.pageY,rollingTimestamps:[t],rollingPageX:[s.pageX],rollingPageY:[s.pageY]};const r=this.newGestureEvent(f.Start,s.target);r.pageX=s.pageX,r.pageY=s.pageY,this.dispatchEvent(r)}this.dispatched&&(e.preventDefault(),e.stopPropagation(),this.dispatched=!1)}onTouchEnd(e,t){const i=Date.now(),s=Object.keys(this.activeTouches).length;for(let r=0,n=t.changedTouches.length;r<n;r++){const n=t.changedTouches.item(r);if(!this.activeTouches.hasOwnProperty(String(n.identifier))){console.warn("move of an UNKNOWN touch",n);continue}const o=this.activeTouches[n.identifier],a=Date.now()-o.initialTimeStamp;if(a<p.HOLD_DELAY&&Math.abs(o.initialPageX-h.tail(o.rollingPageX))<30&&Math.abs(o.initialPageY-h.tail(o.rollingPageY))<30){const e=this.newGestureEvent(f.Tap,o.initialTarget);e.pageX=h.tail(o.rollingPageX),e.pageY=h.tail(o.rollingPageY),this.dispatchEvent(e)}else if(a>=p.HOLD_DELAY&&Math.abs(o.initialPageX-h.tail(o.rollingPageX))<30&&Math.abs(o.initialPageY-h.tail(o.rollingPageY))<30){const e=this.newGestureEvent(f.Contextmenu,o.initialTarget);e.pageX=h.tail(o.rollingPageX),e.pageY=h.tail(o.rollingPageY),this.dispatchEvent(e)}else if(1===s){const t=h.tail(o.rollingPageX),s=h.tail(o.rollingPageY),r=h.tail(o.rollingTimestamps)-o.rollingTimestamps[0],n=t-o.rollingPageX[0],a=s-o.rollingPageY[0],l=[...this.targets].filter((e=>o.initialTarget instanceof Node&&e.contains(o.initialTarget)));this.inertia(e,l,i,Math.abs(n)/r,n>0?1:-1,t,Math.abs(a)/r,a>0?1:-1,s)}this.dispatchEvent(this.newGestureEvent(f.End,o.initialTarget)),delete this.activeTouches[n.identifier]}this.dispatched&&(t.preventDefault(),t.stopPropagation(),this.dispatched=!1)}newGestureEvent(e,t){const i=document.createEvent("CustomEvent");return i.initEvent(e,!1,!0),i.initialTarget=t,i.tapCount=0,i}dispatchEvent(e){if(e.type===f.Tap){const t=(new Date).getTime();let i=0;i=t-this._lastSetTapCountTime>p.CLEAR_TAP_COUNT_TIME?1:2,this._lastSetTapCountTime=t,e.tapCount=i}else e.type!==f.Change&&e.type!==f.Contextmenu||(this._lastSetTapCountTime=0);if(e.initialTarget instanceof Node){for(const t of this.ignoreTargets)if(t.contains(e.initialTarget))return;const t=[];for(const i of this.targets)if(i.contains(e.initialTarget)){let s=0,r=e.initialTarget;for(;r&&r!==i;)s++,r=r.parentElement;t.push([s,i])}t.sort(((e,t)=>e[0]-t[0]));for(const[i,s]of t)s.dispatchEvent(e),this.dispatched=!0}}inertia(e,t,i,s,r,n,o,l,h){this.handle=a.scheduleAtNextAnimationFrame(e,(()=>{const a=Date.now(),c=a-i;let d=0,u=0,_=!0;s+=p.SCROLL_FRICTION*c,o+=p.SCROLL_FRICTION*c,s>0&&(_=!1,d=r*s*c),o>0&&(_=!1,u=l*o*c);const g=this.newGestureEvent(f.Change);g.translationX=d,g.translationY=u,t.forEach((e=>e.dispatchEvent(g))),_||this.inertia(e,t,a,s,r,n+d,o,l,h+u)}))}onTouchMove(e){const t=Date.now();for(let i=0,s=e.changedTouches.length;i<s;i++){const s=e.changedTouches.item(i);if(!this.activeTouches.hasOwnProperty(String(s.identifier))){console.warn("end of an UNKNOWN touch",s);continue}const r=this.activeTouches[s.identifier],n=this.newGestureEvent(f.Change,r.initialTarget);n.translationX=s.pageX-h.tail(r.rollingPageX),n.translationY=s.pageY-h.tail(r.rollingPageY),n.pageX=s.pageX,n.pageY=s.pageY,this.dispatchEvent(n),r.rollingPageX.length>3&&(r.rollingPageX.shift(),r.rollingPageY.shift(),r.rollingTimestamps.shift()),r.rollingPageX.push(s.pageX),r.rollingPageY.push(s.pageY),r.rollingTimestamps.push(t)}this.dispatched&&(e.preventDefault(),e.stopPropagation(),this.dispatched=!1)}}t.Gesture=p,n([c.memoize],p,"isTouchDevice",null)},8801:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.AbstractScrollbar=void 0;const o=n(i(7093)),a=i(9675),l=i(8328),h=i(8974),c=i(79),d=i(8286),u=n(i(8163));class _ extends d.Widget{constructor(e){super(),this._lazyRender=e.lazyRender,this._host=e.host,this._scrollable=e.scrollable,this._scrollByPage=e.scrollByPage,this._scrollbarState=e.scrollbarState,this._visibilityController=this._register(new c.ScrollbarVisibilityController(e.visibility,"visible scrollbar "+e.extraScrollbarClassName,"invisible scrollbar "+e.extraScrollbarClassName)),this._visibilityController.setIsNeeded(this._scrollbarState.isNeeded()),this._pointerMoveMonitor=this._register(new l.GlobalPointerMoveMonitor),this._shouldRender=!0,this.domNode=(0,a.createFastDomNode)(document.createElement("div")),this.domNode.setAttribute("role","presentation"),this.domNode.setAttribute("aria-hidden","true"),this._visibilityController.setDomNode(this.domNode),this.domNode.setPosition("absolute"),this._register(o.addDisposableListener(this.domNode.domNode,o.EventType.POINTER_DOWN,(e=>this._domNodePointerDown(e))))}_createArrow(e){const t=this._register(new h.ScrollbarArrow(e));this.domNode.domNode.appendChild(t.bgDomNode),this.domNode.domNode.appendChild(t.domNode)}_createSlider(e,t,i,s){this.slider=(0,a.createFastDomNode)(document.createElement("div")),this.slider.setClassName("slider"),this.slider.setPosition("absolute"),this.slider.setTop(e),this.slider.setLeft(t),"number"==typeof i&&this.slider.setWidth(i),"number"==typeof s&&this.slider.setHeight(s),this.slider.setLayerHinting(!0),this.slider.setContain("strict"),this.domNode.domNode.appendChild(this.slider.domNode),this._register(o.addDisposableListener(this.slider.domNode,o.EventType.POINTER_DOWN,(e=>{0===e.button&&(e.preventDefault(),this._sliderPointerDown(e))}))),this.onclick(this.slider.domNode,(e=>{e.leftButton&&e.stopPropagation()}))}_onElementSize(e){return this._scrollbarState.setVisibleSize(e)&&(this._visibilityController.setIsNeeded(this._scrollbarState.isNeeded()),this._shouldRender=!0,this._lazyRender||this.render()),this._shouldRender}_onElementScrollSize(e){return this._scrollbarState.setScrollSize(e)&&(this._visibilityController.setIsNeeded(this._scrollbarState.isNeeded()),this._shouldRender=!0,this._lazyRender||this.render()),this._shouldRender}_onElementScrollPosition(e){return this._scrollbarState.setScrollPosition(e)&&(this._visibilityController.setIsNeeded(this._scrollbarState.isNeeded()),this._shouldRender=!0,this._lazyRender||this.render()),this._shouldRender}beginReveal(){this._visibilityController.setShouldBeVisible(!0)}beginHide(){this._visibilityController.setShouldBeVisible(!1)}render(){this._shouldRender&&(this._shouldRender=!1,this._renderDomNode(this._scrollbarState.getRectangleLargeSize(),this._scrollbarState.getRectangleSmallSize()),this._updateSlider(this._scrollbarState.getSliderSize(),this._scrollbarState.getArrowSize()+this._scrollbarState.getSliderPosition()))}_domNodePointerDown(e){e.target===this.domNode.domNode&&this._onPointerDown(e)}delegatePointerDown(e){const t=this.domNode.domNode.getClientRects()[0].top,i=t+this._scrollbarState.getSliderPosition(),s=t+this._scrollbarState.getSliderPosition()+this._scrollbarState.getSliderSize(),r=this._sliderPointerPosition(e);i<=r&&r<=s?0===e.button&&(e.preventDefault(),this._sliderPointerDown(e)):this._onPointerDown(e)}_onPointerDown(e){let t,i;if(e.target===this.domNode.domNode&&"number"==typeof e.offsetX&&"number"==typeof e.offsetY)t=e.offsetX,i=e.offsetY;else{const s=o.getDomNodePagePosition(this.domNode.domNode);t=e.pageX-s.left,i=e.pageY-s.top}const s=this._pointerDownRelativePosition(t,i);this._setDesiredScrollPositionNow(this._scrollByPage?this._scrollbarState.getDesiredScrollPositionFromOffsetPaged(s):this._scrollbarState.getDesiredScrollPositionFromOffset(s)),0===e.button&&(e.preventDefault(),this._sliderPointerDown(e))}_sliderPointerDown(e){if(!(e.target&&e.target instanceof Element))return;const t=this._sliderPointerPosition(e),i=this._sliderOrthogonalPointerPosition(e),s=this._scrollbarState.clone();this.slider.toggleClassName("active",!0),this._pointerMoveMonitor.startMonitoring(e.target,e.pointerId,e.buttons,(e=>{const r=this._sliderOrthogonalPointerPosition(e),n=Math.abs(r-i);if(u.isWindows&&n>140)return void this._setDesiredScrollPositionNow(s.getScrollPosition());const o=this._sliderPointerPosition(e)-t;this._setDesiredScrollPositionNow(s.getDesiredScrollPositionFromDelta(o))}),(()=>{this.slider.toggleClassName("active",!1),this._host.onDragEnd()})),this._host.onDragStart()}_setDesiredScrollPositionNow(e){const t={};this.writeScrollPosition(t,e),this._scrollable.setScrollPositionNow(t)}updateScrollbarSize(e){this._updateScrollbarSize(e),this._scrollbarState.setScrollbarSize(e),this._shouldRender=!0,this._lazyRender||this.render()}isNeeded(){return this._scrollbarState.isNeeded()}}t.AbstractScrollbar=_},151:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.HorizontalScrollbar=void 0;const s=i(8801),r=i(8245),n=i(9881);class o extends s.AbstractScrollbar{constructor(e,t,i){const s=e.getScrollDimensions(),o=e.getCurrentScrollPosition();if(super({lazyRender:t.lazyRender,host:i,scrollbarState:new r.ScrollbarState(t.horizontalHasArrows?t.arrowSize:0,t.horizontal===n.ScrollbarVisibility.Hidden?0:t.horizontalScrollbarSize,t.vertical===n.ScrollbarVisibility.Hidden?0:t.verticalScrollbarSize,s.width,s.scrollWidth,o.scrollLeft),visibility:t.horizontal,extraScrollbarClassName:"horizontal",scrollable:e,scrollByPage:t.scrollByPage}),t.horizontalHasArrows)throw new Error("horizontalHasArrows is not supported in xterm.js");this._createSlider(Math.floor((t.horizontalScrollbarSize-t.horizontalSliderSize)/2),0,void 0,t.horizontalSliderSize)}_updateSlider(e,t){this.slider.setWidth(e),this.slider.setLeft(t)}_renderDomNode(e,t){this.domNode.setWidth(e),this.domNode.setHeight(t),this.domNode.setLeft(0),this.domNode.setBottom(0)}onDidScroll(e){return this._shouldRender=this._onElementScrollSize(e.scrollWidth)||this._shouldRender,this._shouldRender=this._onElementScrollPosition(e.scrollLeft)||this._shouldRender,this._shouldRender=this._onElementSize(e.width)||this._shouldRender,this._shouldRender}_pointerDownRelativePosition(e,t){return e}_sliderPointerPosition(e){return e.pageX}_sliderOrthogonalPointerPosition(e){return e.pageY}_updateScrollbarSize(e){this.slider.setHeight(e)}writeScrollPosition(e,t){e.scrollLeft=t}updateOptions(e){this.updateScrollbarSize(e.horizontal===n.ScrollbarVisibility.Hidden?0:e.horizontalScrollbarSize),this._scrollbarState.setOppositeScrollbarSize(e.vertical===n.ScrollbarVisibility.Hidden?0:e.verticalScrollbarSize),this._visibilityController.setVisibility(e.horizontal),this._scrollByPage=e.scrollByPage}}t.HorizontalScrollbar=o},8234:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.DomScrollableElement=t.SmoothScrollableElement=t.ScrollableElement=t.AbstractScrollableElement=t.MouseWheelClassifier=void 0;const o=i(4333),a=n(i(7093)),l=i(9675),h=i(5964),c=i(151),d=i(5473),u=i(8286),_=i(1758),f=i(802),p=i(7150),g=n(i(8163)),m=i(9881);class v{constructor(e,t,i){this.timestamp=e,this.deltaX=t,this.deltaY=i,this.score=0}}class S{static{this.INSTANCE=new S}constructor(){this._capacity=5,this._memory=[],this._front=-1,this._rear=-1}isPhysicalMouseWheel(){if(-1===this._front&&-1===this._rear)return!1;let e=1,t=0,i=1,s=this._rear;for(;;){const r=s===this._front?e:Math.pow(2,-i);if(e-=r,t+=this._memory[s].score*r,s===this._front)break;s=(this._capacity+s-1)%this._capacity,i++}return t<=.5}acceptStandardWheelEvent(e){if(o.isChrome){const t=a.getWindow(e.browserEvent),i=(0,o.getZoomFactor)(t);this.accept(Date.now(),e.deltaX*i,e.deltaY*i)}else this.accept(Date.now(),e.deltaX,e.deltaY)}accept(e,t,i){let s=null;const r=new v(e,t,i);-1===this._front&&-1===this._rear?(this._memory[0]=r,this._front=0,this._rear=0):(s=this._memory[this._rear],this._rear=(this._rear+1)%this._capacity,this._rear===this._front&&(this._front=(this._front+1)%this._capacity),this._memory[this._rear]=r),r.score=this._computeScore(r,s)}_computeScore(e,t){if(Math.abs(e.deltaX)>0&&Math.abs(e.deltaY)>0)return 1;let i=.5;if(this._isAlmostInt(e.deltaX)&&this._isAlmostInt(e.deltaY)||(i+=.25),t){const s=Math.abs(e.deltaX),r=Math.abs(e.deltaY),n=Math.abs(t.deltaX),o=Math.abs(t.deltaY),a=Math.max(Math.min(s,n),1),l=Math.max(Math.min(r,o),1),h=Math.max(s,n),c=Math.max(r,o);h%a==0&&c%l==0&&(i-=.5)}return Math.min(Math.max(i,0),1)}_isAlmostInt(e){return Math.abs(Math.round(e)-e)<.01}}t.MouseWheelClassifier=S;class b extends u.Widget{get options(){return this._options}constructor(e,t,i){super(),this._onScroll=this._register(new f.Emitter),this.onScroll=this._onScroll.event,this._onWillScroll=this._register(new f.Emitter),this.onWillScroll=this._onWillScroll.event,this._options=function(e){const t={lazyRender:void 0!==e.lazyRender&&e.lazyRender,className:void 0!==e.className?e.className:"",useShadows:void 0===e.useShadows||e.useShadows,handleMouseWheel:void 0===e.handleMouseWheel||e.handleMouseWheel,flipAxes:void 0!==e.flipAxes&&e.flipAxes,consumeMouseWheelIfScrollbarIsNeeded:void 0!==e.consumeMouseWheelIfScrollbarIsNeeded&&e.consumeMouseWheelIfScrollbarIsNeeded,alwaysConsumeMouseWheel:void 0!==e.alwaysConsumeMouseWheel&&e.alwaysConsumeMouseWheel,scrollYToX:void 0!==e.scrollYToX&&e.scrollYToX,mouseWheelScrollSensitivity:void 0!==e.mouseWheelScrollSensitivity?e.mouseWheelScrollSensitivity:1,fastScrollSensitivity:void 0!==e.fastScrollSensitivity?e.fastScrollSensitivity:5,scrollPredominantAxis:void 0===e.scrollPredominantAxis||e.scrollPredominantAxis,mouseWheelSmoothScroll:void 0===e.mouseWheelSmoothScroll||e.mouseWheelSmoothScroll,arrowSize:void 0!==e.arrowSize?e.arrowSize:11,listenOnDomNode:void 0!==e.listenOnDomNode?e.listenOnDomNode:null,horizontal:void 0!==e.horizontal?e.horizontal:m.ScrollbarVisibility.Auto,horizontalScrollbarSize:void 0!==e.horizontalScrollbarSize?e.horizontalScrollbarSize:10,horizontalSliderSize:void 0!==e.horizontalSliderSize?e.horizontalSliderSize:0,horizontalHasArrows:void 0!==e.horizontalHasArrows&&e.horizontalHasArrows,vertical:void 0!==e.vertical?e.vertical:m.ScrollbarVisibility.Auto,verticalScrollbarSize:void 0!==e.verticalScrollbarSize?e.verticalScrollbarSize:10,verticalHasArrows:void 0!==e.verticalHasArrows&&e.verticalHasArrows,verticalSliderSize:void 0!==e.verticalSliderSize?e.verticalSliderSize:0,scrollByPage:void 0!==e.scrollByPage&&e.scrollByPage};return t.horizontalSliderSize=void 0!==e.horizontalSliderSize?e.horizontalSliderSize:t.horizontalScrollbarSize,t.verticalSliderSize=void 0!==e.verticalSliderSize?e.verticalSliderSize:t.verticalScrollbarSize,g.isMacintosh&&(t.className+=" mac"),t}(t),this._scrollable=i,this._register(this._scrollable.onScroll((e=>{this._onWillScroll.fire(e),this._onDidScroll(e),this._onScroll.fire(e)})));const s={onMouseWheel:e=>this._onMouseWheel(e),onDragStart:()=>this._onDragStart(),onDragEnd:()=>this._onDragEnd()};this._verticalScrollbar=this._register(new d.VerticalScrollbar(this._scrollable,this._options,s)),this._horizontalScrollbar=this._register(new c.HorizontalScrollbar(this._scrollable,this._options,s)),this._domNode=document.createElement("div"),this._domNode.className="xterm-scrollable-element "+this._options.className,this._domNode.setAttribute("role","presentation"),this._domNode.style.position="relative",this._domNode.appendChild(e),this._domNode.appendChild(this._horizontalScrollbar.domNode.domNode),this._domNode.appendChild(this._verticalScrollbar.domNode.domNode),this._options.useShadows?(this._leftShadowDomNode=(0,l.createFastDomNode)(document.createElement("div")),this._leftShadowDomNode.setClassName("shadow"),this._domNode.appendChild(this._leftShadowDomNode.domNode),this._topShadowDomNode=(0,l.createFastDomNode)(document.createElement("div")),this._topShadowDomNode.setClassName("shadow"),this._domNode.appendChild(this._topShadowDomNode.domNode),this._topLeftShadowDomNode=(0,l.createFastDomNode)(document.createElement("div")),this._topLeftShadowDomNode.setClassName("shadow"),this._domNode.appendChild(this._topLeftShadowDomNode.domNode)):(this._leftShadowDomNode=null,this._topShadowDomNode=null,this._topLeftShadowDomNode=null),this._listenOnDomNode=this._options.listenOnDomNode||this._domNode,this._mouseWheelToDispose=[],this._setListeningToMouseWheel(this._options.handleMouseWheel),this.onmouseover(this._listenOnDomNode,(e=>this._onMouseOver(e))),this.onmouseleave(this._listenOnDomNode,(e=>this._onMouseLeave(e))),this._hideTimeout=this._register(new _.TimeoutTimer),this._isDragging=!1,this._mouseIsOver=!1,this._shouldRender=!0,this._revealOnScroll=!0}dispose(){this._mouseWheelToDispose=(0,p.dispose)(this._mouseWheelToDispose),super.dispose()}getDomNode(){return this._domNode}getOverviewRulerLayoutInfo(){return{parent:this._domNode,insertBefore:this._verticalScrollbar.domNode.domNode}}delegateVerticalScrollbarPointerDown(e){this._verticalScrollbar.delegatePointerDown(e)}getScrollDimensions(){return this._scrollable.getScrollDimensions()}setScrollDimensions(e){this._scrollable.setScrollDimensions(e,!1)}updateClassName(e){this._options.className=e,g.isMacintosh&&(this._options.className+=" mac"),this._domNode.className="xterm-scrollable-element "+this._options.className}updateOptions(e){void 0!==e.handleMouseWheel&&(this._options.handleMouseWheel=e.handleMouseWheel,this._setListeningToMouseWheel(this._options.handleMouseWheel)),void 0!==e.mouseWheelScrollSensitivity&&(this._options.mouseWheelScrollSensitivity=e.mouseWheelScrollSensitivity),void 0!==e.fastScrollSensitivity&&(this._options.fastScrollSensitivity=e.fastScrollSensitivity),void 0!==e.scrollPredominantAxis&&(this._options.scrollPredominantAxis=e.scrollPredominantAxis),void 0!==e.horizontal&&(this._options.horizontal=e.horizontal),void 0!==e.vertical&&(this._options.vertical=e.vertical),void 0!==e.horizontalScrollbarSize&&(this._options.horizontalScrollbarSize=e.horizontalScrollbarSize),void 0!==e.verticalScrollbarSize&&(this._options.verticalScrollbarSize=e.verticalScrollbarSize),void 0!==e.scrollByPage&&(this._options.scrollByPage=e.scrollByPage),this._horizontalScrollbar.updateOptions(this._options),this._verticalScrollbar.updateOptions(this._options),this._options.lazyRender||this._render()}setRevealOnScroll(e){this._revealOnScroll=e}delegateScrollFromMouseWheelEvent(e){this._onMouseWheel(new h.StandardWheelEvent(e))}_setListeningToMouseWheel(e){if(this._mouseWheelToDispose.length>0!==e&&(this._mouseWheelToDispose=(0,p.dispose)(this._mouseWheelToDispose),e)){const e=e=>{this._onMouseWheel(new h.StandardWheelEvent(e))};this._mouseWheelToDispose.push(a.addDisposableListener(this._listenOnDomNode,a.EventType.MOUSE_WHEEL,e,{passive:!1}))}}_onMouseWheel(e){if(e.browserEvent?.defaultPrevented)return;const t=S.INSTANCE;t.acceptStandardWheelEvent(e);let i=!1;if(e.deltaY||e.deltaX){let s=e.deltaY*this._options.mouseWheelScrollSensitivity,r=e.deltaX*this._options.mouseWheelScrollSensitivity;this._options.scrollPredominantAxis&&(this._options.scrollYToX&&r+s===0?r=s=0:Math.abs(s)>=Math.abs(r)?r=0:s=0),this._options.flipAxes&&([s,r]=[r,s]);const n=!g.isMacintosh&&e.browserEvent&&e.browserEvent.shiftKey;!this._options.scrollYToX&&!n||r||(r=s,s=0),e.browserEvent&&e.browserEvent.altKey&&(r*=this._options.fastScrollSensitivity,s*=this._options.fastScrollSensitivity);const o=this._scrollable.getFutureScrollPosition();let a={};if(s){const e=50*s,t=o.scrollTop-(e<0?Math.floor(e):Math.ceil(e));this._verticalScrollbar.writeScrollPosition(a,t)}if(r){const e=50*r,t=o.scrollLeft-(e<0?Math.floor(e):Math.ceil(e));this._horizontalScrollbar.writeScrollPosition(a,t)}a=this._scrollable.validateScrollPosition(a),(o.scrollLeft!==a.scrollLeft||o.scrollTop!==a.scrollTop)&&(this._options.mouseWheelSmoothScroll&&t.isPhysicalMouseWheel()?this._scrollable.setScrollPositionSmooth(a):this._scrollable.setScrollPositionNow(a),i=!0)}let s=i;!s&&this._options.alwaysConsumeMouseWheel&&(s=!0),!s&&this._options.consumeMouseWheelIfScrollbarIsNeeded&&(this._verticalScrollbar.isNeeded()||this._horizontalScrollbar.isNeeded())&&(s=!0),s&&(e.preventDefault(),e.stopPropagation())}_onDidScroll(e){this._shouldRender=this._horizontalScrollbar.onDidScroll(e)||this._shouldRender,this._shouldRender=this._verticalScrollbar.onDidScroll(e)||this._shouldRender,this._options.useShadows&&(this._shouldRender=!0),this._revealOnScroll&&this._reveal(),this._options.lazyRender||this._render()}renderNow(){if(!this._options.lazyRender)throw new Error("Please use `lazyRender` together with `renderNow`!");this._render()}_render(){if(this._shouldRender&&(this._shouldRender=!1,this._horizontalScrollbar.render(),this._verticalScrollbar.render(),this._options.useShadows)){const e=this._scrollable.getCurrentScrollPosition(),t=e.scrollTop>0,i=e.scrollLeft>0,s=i?" left":"",r=t?" top":"",n=i||t?" top-left-corner":"";this._leftShadowDomNode.setClassName(`shadow${s}`),this._topShadowDomNode.setClassName(`shadow${r}`),this._topLeftShadowDomNode.setClassName(`shadow${n}${r}${s}`)}}_onDragStart(){this._isDragging=!0,this._reveal()}_onDragEnd(){this._isDragging=!1,this._hide()}_onMouseLeave(e){this._mouseIsOver=!1,this._hide()}_onMouseOver(e){this._mouseIsOver=!0,this._reveal()}_reveal(){this._verticalScrollbar.beginReveal(),this._horizontalScrollbar.beginReveal(),this._scheduleHide()}_hide(){this._mouseIsOver||this._isDragging||(this._verticalScrollbar.beginHide(),this._horizontalScrollbar.beginHide())}_scheduleHide(){this._mouseIsOver||this._isDragging||this._hideTimeout.cancelAndSet((()=>this._hide()),500)}}t.AbstractScrollableElement=b,t.ScrollableElement=class extends b{constructor(e,t){(t=t||{}).mouseWheelSmoothScroll=!1;const i=new m.Scrollable({forceIntegerValues:!0,smoothScrollDuration:0,scheduleAtNextAnimationFrame:t=>a.scheduleAtNextAnimationFrame(a.getWindow(e),t)});super(e,t,i),this._register(i)}setScrollPosition(e){this._scrollable.setScrollPositionNow(e)}getScrollPosition(){return this._scrollable.getCurrentScrollPosition()}},t.SmoothScrollableElement=class extends b{constructor(e,t,i){super(e,t,i)}setScrollPosition(e){e.reuseAnimation?this._scrollable.setScrollPositionSmooth(e,e.reuseAnimation):this._scrollable.setScrollPositionNow(e)}getScrollPosition(){return this._scrollable.getCurrentScrollPosition()}},t.DomScrollableElement=class extends b{constructor(e,t){(t=t||{}).mouseWheelSmoothScroll=!1;const i=new m.Scrollable({forceIntegerValues:!1,smoothScrollDuration:0,scheduleAtNextAnimationFrame:t=>a.scheduleAtNextAnimationFrame(a.getWindow(e),t)});super(e,t,i),this._register(i),this._element=e,this._register(this.onScroll((e=>{e.scrollTopChanged&&(this._element.scrollTop=e.scrollTop),e.scrollLeftChanged&&(this._element.scrollLeft=e.scrollLeft)}))),this.scanDomNode()}setScrollPosition(e){this._scrollable.setScrollPositionNow(e)}getScrollPosition(){return this._scrollable.getCurrentScrollPosition()}scanDomNode(){this.setScrollDimensions({width:this._element.clientWidth,scrollWidth:this._element.scrollWidth,height:this._element.clientHeight,scrollHeight:this._element.scrollHeight}),this.setScrollPosition({scrollLeft:this._element.scrollLeft,scrollTop:this._element.scrollTop})}}},8974:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.ScrollbarArrow=t.ARROW_IMG_SIZE=void 0;const o=i(8328),a=i(8286),l=i(1758),h=n(i(7093));t.ARROW_IMG_SIZE=11;class c extends a.Widget{constructor(e){super(),this._onActivate=e.onActivate,this.bgDomNode=document.createElement("div"),this.bgDomNode.className="arrow-background",this.bgDomNode.style.position="absolute",this.bgDomNode.style.width=e.bgWidth+"px",this.bgDomNode.style.height=e.bgHeight+"px",void 0!==e.top&&(this.bgDomNode.style.top="0px"),void 0!==e.left&&(this.bgDomNode.style.left="0px"),void 0!==e.bottom&&(this.bgDomNode.style.bottom="0px"),void 0!==e.right&&(this.bgDomNode.style.right="0px"),this.domNode=document.createElement("div"),this.domNode.className=e.className,this.domNode.style.position="absolute",this.domNode.style.width=t.ARROW_IMG_SIZE+"px",this.domNode.style.height=t.ARROW_IMG_SIZE+"px",void 0!==e.top&&(this.domNode.style.top=e.top+"px"),void 0!==e.left&&(this.domNode.style.left=e.left+"px"),void 0!==e.bottom&&(this.domNode.style.bottom=e.bottom+"px"),void 0!==e.right&&(this.domNode.style.right=e.right+"px"),this._pointerMoveMonitor=this._register(new o.GlobalPointerMoveMonitor),this._register(h.addStandardDisposableListener(this.bgDomNode,h.EventType.POINTER_DOWN,(e=>this._arrowPointerDown(e)))),this._register(h.addStandardDisposableListener(this.domNode,h.EventType.POINTER_DOWN,(e=>this._arrowPointerDown(e)))),this._pointerdownRepeatTimer=this._register(new h.WindowIntervalTimer),this._pointerdownScheduleRepeatTimer=this._register(new l.TimeoutTimer)}_arrowPointerDown(e){e.target&&e.target instanceof Element&&(this._onActivate(),this._pointerdownRepeatTimer.cancel(),this._pointerdownScheduleRepeatTimer.cancelAndSet((()=>{this._pointerdownRepeatTimer.cancelAndSet((()=>this._onActivate()),1e3/24,h.getWindow(e))}),200),this._pointerMoveMonitor.startMonitoring(e.target,e.pointerId,e.buttons,(e=>{}),(()=>{this._pointerdownRepeatTimer.cancel(),this._pointerdownScheduleRepeatTimer.cancel()})),e.preventDefault())}}t.ScrollbarArrow=c},8245:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ScrollbarState=void 0;class i{constructor(e,t,i,s,r,n){this._scrollbarSize=Math.round(t),this._oppositeScrollbarSize=Math.round(i),this._arrowSize=Math.round(e),this._visibleSize=s,this._scrollSize=r,this._scrollPosition=n,this._computedAvailableSize=0,this._computedIsNeeded=!1,this._computedSliderSize=0,this._computedSliderRatio=0,this._computedSliderPosition=0,this._refreshComputedValues()}clone(){return new i(this._arrowSize,this._scrollbarSize,this._oppositeScrollbarSize,this._visibleSize,this._scrollSize,this._scrollPosition)}setVisibleSize(e){const t=Math.round(e);return this._visibleSize!==t&&(this._visibleSize=t,this._refreshComputedValues(),!0)}setScrollSize(e){const t=Math.round(e);return this._scrollSize!==t&&(this._scrollSize=t,this._refreshComputedValues(),!0)}setScrollPosition(e){const t=Math.round(e);return this._scrollPosition!==t&&(this._scrollPosition=t,this._refreshComputedValues(),!0)}setScrollbarSize(e){this._scrollbarSize=Math.round(e)}setOppositeScrollbarSize(e){this._oppositeScrollbarSize=Math.round(e)}static _computeValues(e,t,i,s,r){const n=Math.max(0,i-e),o=Math.max(0,n-2*t),a=s>0&&s>i;if(!a)return{computedAvailableSize:Math.round(n),computedIsNeeded:a,computedSliderSize:Math.round(o),computedSliderRatio:0,computedSliderPosition:0};const l=Math.round(Math.max(20,Math.floor(i*o/s))),h=(o-l)/(s-i),c=r*h;return{computedAvailableSize:Math.round(n),computedIsNeeded:a,computedSliderSize:Math.round(l),computedSliderRatio:h,computedSliderPosition:Math.round(c)}}_refreshComputedValues(){const e=i._computeValues(this._oppositeScrollbarSize,this._arrowSize,this._visibleSize,this._scrollSize,this._scrollPosition);this._computedAvailableSize=e.computedAvailableSize,this._computedIsNeeded=e.computedIsNeeded,this._computedSliderSize=e.computedSliderSize,this._computedSliderRatio=e.computedSliderRatio,this._computedSliderPosition=e.computedSliderPosition}getArrowSize(){return this._arrowSize}getScrollPosition(){return this._scrollPosition}getRectangleLargeSize(){return this._computedAvailableSize}getRectangleSmallSize(){return this._scrollbarSize}isNeeded(){return this._computedIsNeeded}getSliderSize(){return this._computedSliderSize}getSliderPosition(){return this._computedSliderPosition}getDesiredScrollPositionFromOffset(e){if(!this._computedIsNeeded)return 0;const t=e-this._arrowSize-this._computedSliderSize/2;return Math.round(t/this._computedSliderRatio)}getDesiredScrollPositionFromOffsetPaged(e){if(!this._computedIsNeeded)return 0;const t=e-this._arrowSize;let i=this._scrollPosition;return t<this._computedSliderPosition?i-=this._visibleSize:i+=this._visibleSize,i}getDesiredScrollPositionFromDelta(e){if(!this._computedIsNeeded)return 0;const t=this._computedSliderPosition+e;return Math.round(t/this._computedSliderRatio)}}t.ScrollbarState=i},79:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ScrollbarVisibilityController=void 0;const s=i(1758),r=i(7150),n=i(9881);class o extends r.Disposable{constructor(e,t,i){super(),this._visibility=e,this._visibleClassName=t,this._invisibleClassName=i,this._domNode=null,this._isVisible=!1,this._isNeeded=!1,this._rawShouldBeVisible=!1,this._shouldBeVisible=!1,this._revealTimer=this._register(new s.TimeoutTimer)}setVisibility(e){this._visibility!==e&&(this._visibility=e,this._updateShouldBeVisible())}setShouldBeVisible(e){this._rawShouldBeVisible=e,this._updateShouldBeVisible()}_applyVisibilitySetting(){return this._visibility!==n.ScrollbarVisibility.Hidden&&(this._visibility===n.ScrollbarVisibility.Visible||this._rawShouldBeVisible)}_updateShouldBeVisible(){const e=this._applyVisibilitySetting();this._shouldBeVisible!==e&&(this._shouldBeVisible=e,this.ensureVisibility())}setIsNeeded(e){this._isNeeded!==e&&(this._isNeeded=e,this.ensureVisibility())}setDomNode(e){this._domNode=e,this._domNode.setClassName(this._invisibleClassName),this.setShouldBeVisible(!1)}ensureVisibility(){this._isNeeded?this._shouldBeVisible?this._reveal():this._hide(!0):this._hide(!1)}_reveal(){this._isVisible||(this._isVisible=!0,this._revealTimer.setIfNotSet((()=>{this._domNode?.setClassName(this._visibleClassName)}),0))}_hide(e){this._revealTimer.cancel(),this._isVisible&&(this._isVisible=!1,this._domNode?.setClassName(this._invisibleClassName+(e?" fade":"")))}}t.ScrollbarVisibilityController=o},5473:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.VerticalScrollbar=void 0;const s=i(8801),r=i(8245),n=i(9881);class o extends s.AbstractScrollbar{constructor(e,t,i){const s=e.getScrollDimensions(),o=e.getCurrentScrollPosition();if(super({lazyRender:t.lazyRender,host:i,scrollbarState:new r.ScrollbarState(t.verticalHasArrows?t.arrowSize:0,t.vertical===n.ScrollbarVisibility.Hidden?0:t.verticalScrollbarSize,0,s.height,s.scrollHeight,o.scrollTop),visibility:t.vertical,extraScrollbarClassName:"vertical",scrollable:e,scrollByPage:t.scrollByPage}),t.verticalHasArrows)throw new Error("horizontalHasArrows is not supported in xterm.js");this._createSlider(0,Math.floor((t.verticalScrollbarSize-t.verticalSliderSize)/2),t.verticalSliderSize,void 0)}_updateSlider(e,t){this.slider.setHeight(e),this.slider.setTop(t)}_renderDomNode(e,t){this.domNode.setWidth(t),this.domNode.setHeight(e),this.domNode.setRight(0),this.domNode.setTop(0)}onDidScroll(e){return this._shouldRender=this._onElementScrollSize(e.scrollHeight)||this._shouldRender,this._shouldRender=this._onElementScrollPosition(e.scrollTop)||this._shouldRender,this._shouldRender=this._onElementSize(e.height)||this._shouldRender,this._shouldRender}_pointerDownRelativePosition(e,t){return t}_sliderPointerPosition(e){return e.pageY}_sliderOrthogonalPointerPosition(e){return e.pageX}_updateScrollbarSize(e){this.slider.setWidth(e)}writeScrollPosition(e,t){e.scrollTop=t}updateOptions(e){this.updateScrollbarSize(e.vertical===n.ScrollbarVisibility.Hidden?0:e.verticalScrollbarSize),this._scrollbarState.setOppositeScrollbarSize(0),this._visibilityController.setVisibility(e.vertical),this._scrollByPage=e.scrollByPage}}t.VerticalScrollbar=o},8286:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.Widget=void 0;const o=n(i(7093)),a=i(5394),l=i(5964),h=i(8594),c=i(7150);class d extends c.Disposable{onclick(e,t){this._register(o.addDisposableListener(e,o.EventType.CLICK,(i=>t(new l.StandardMouseEvent(o.getWindow(e),i)))))}onmousedown(e,t){this._register(o.addDisposableListener(e,o.EventType.MOUSE_DOWN,(i=>t(new l.StandardMouseEvent(o.getWindow(e),i)))))}onmouseover(e,t){this._register(o.addDisposableListener(e,o.EventType.MOUSE_OVER,(i=>t(new l.StandardMouseEvent(o.getWindow(e),i)))))}onmouseleave(e,t){this._register(o.addDisposableListener(e,o.EventType.MOUSE_LEAVE,(i=>t(new l.StandardMouseEvent(o.getWindow(e),i)))))}onkeydown(e,t){this._register(o.addDisposableListener(e,o.EventType.KEY_DOWN,(e=>t(new a.StandardKeyboardEvent(e)))))}onkeyup(e,t){this._register(o.addDisposableListener(e,o.EventType.KEY_UP,(e=>t(new a.StandardKeyboardEvent(e)))))}oninput(e,t){this._register(o.addDisposableListener(e,o.EventType.INPUT,t))}onblur(e,t){this._register(o.addDisposableListener(e,o.EventType.BLUR,t))}onfocus(e,t){this._register(o.addDisposableListener(e,o.EventType.FOCUS,t))}onchange(e,t){this._register(o.addDisposableListener(e,o.EventType.CHANGE,t))}ignoreGesture(e){return h.Gesture.ignoreTarget(e)}}t.Widget=d},4693:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.mainWindow=void 0,t.ensureCodeWindow=function(e,t){},t.mainWindow="object"==typeof window?window:globalThis},3058:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Permutation=t.CallbackIterable=t.ArrayQueue=t.booleanComparator=t.numberComparator=t.CompareResult=void 0,t.tail=function(e,t=0){return e[e.length-(1+t)]},t.tail2=function(e){if(0===e.length)throw new Error("Invalid tail call");return[e.slice(0,e.length-1),e[e.length-1]]},t.equals=function(e,t,i=(e,t)=>e===t){if(e===t)return!0;if(!e||!t)return!1;if(e.length!==t.length)return!1;for(let s=0,r=e.length;s<r;s++)if(!i(e[s],t[s]))return!1;return!0},t.removeFastWithoutKeepingOrder=function(e,t){const i=e.length-1;t<i&&(e[t]=e[i]),e.pop()},t.binarySearch=function(e,t,i){return n(e.length,(s=>i(e[s],t)))},t.binarySearch2=n,t.quickSelect=function e(t,i,s){if((t|=0)>=i.length)throw new TypeError("invalid index");const r=i[Math.floor(i.length*Math.random())],n=[],o=[],a=[];for(const e of i){const t=s(e,r);t<0?n.push(e):t>0?o.push(e):a.push(e)}return t<n.length?e(t,n,s):t<n.length+a.length?a[0]:e(t-(n.length+a.length),o,s)},t.groupBy=function(e,t){const i=[];let s;for(const r of e.slice(0).sort(t))s&&0===t(s[0],r)?s.push(r):(s=[r],i.push(s));return i},t.groupAdjacentBy=function*(e,t){let i,s;for(const r of e)void 0!==s&&t(s,r)?i.push(r):(i&&(yield i),i=[r]),s=r;i&&(yield i)},t.forEachAdjacent=function(e,t){for(let i=0;i<=e.length;i++)t(0===i?void 0:e[i-1],i===e.length?void 0:e[i])},t.forEachWithNeighbors=function(e,t){for(let i=0;i<e.length;i++)t(0===i?void 0:e[i-1],e[i],i+1===e.length?void 0:e[i+1])},t.sortedDiff=o,t.delta=function(e,t,i){const s=o(e,t,i),r=[],n=[];for(const t of s)r.push(...e.slice(t.start,t.start+t.deleteCount)),n.push(...t.toInsert);return{removed:r,added:n}},t.top=function(e,t,i){if(0===i)return[];const s=e.slice(0,i).sort(t);return a(e,t,s,i,e.length),s},t.topAsync=function(e,t,i,r,n){return 0===i?Promise.resolve([]):new Promise(((o,l)=>{(async()=>{const o=e.length,l=e.slice(0,i).sort(t);for(let h=i,c=Math.min(i+r,o);h<o;h=c,c=Math.min(c+r,o)){if(h>i&&await new Promise((e=>setTimeout(e))),n&&n.isCancellationRequested)throw new s.CancellationError;a(e,t,l,h,c)}return l})().then(o,l)}))},t.coalesce=function(e){return e.filter((e=>!!e))},t.coalesceInPlace=function(e){let t=0;for(let i=0;i<e.length;i++)e[i]&&(e[t]=e[i],t+=1);e.length=t},t.move=function(e,t,i){e.splice(i,0,e.splice(t,1)[0])},t.isFalsyOrEmpty=function(e){return!Array.isArray(e)||0===e.length},t.isNonEmptyArray=function(e){return Array.isArray(e)&&e.length>0},t.distinct=function(e,t=e=>e){const i=new Set;return e.filter((e=>{const s=t(e);return!i.has(s)&&(i.add(s),!0)}))},t.uniqueFilter=function(e){const t=new Set;return i=>{const s=e(i);return!t.has(s)&&(t.add(s),!0)}},t.firstOrDefault=function(e,t){return e.length>0?e[0]:t},t.lastOrDefault=function(e,t){return e.length>0?e[e.length-1]:t},t.commonPrefixLength=function(e,t,i=(e,t)=>e===t){let s=0;for(let r=0,n=Math.min(e.length,t.length);r<n&&i(e[r],t[r]);r++)s++;return s},t.range=function(e,t){let i="number"==typeof t?e:0;"number"==typeof t?i=e:(i=0,t=e);const s=[];if(i<=t)for(let e=i;e<t;e++)s.push(e);else for(let e=i;e>t;e--)s.push(e);return s},t.index=function(e,t,i){return e.reduce(((e,s)=>(e[t(s)]=i?i(s):s,e)),Object.create(null))},t.insert=function(e,t){return e.push(t),()=>l(e,t)},t.remove=l,t.arrayInsert=function(e,t,i){const s=e.slice(0,t),r=e.slice(t);return s.concat(i,r)},t.shuffle=function(e,t){let i;if("number"==typeof t){let e=t;i=()=>{const t=179426549*Math.sin(e++);return t-Math.floor(t)}}else i=Math.random;for(let t=e.length-1;t>0;t-=1){const s=Math.floor(i()*(t+1)),r=e[t];e[t]=e[s],e[s]=r}},t.pushToStart=function(e,t){const i=e.indexOf(t);i>-1&&(e.splice(i,1),e.unshift(t))},t.pushToEnd=function(e,t){const i=e.indexOf(t);i>-1&&(e.splice(i,1),e.push(t))},t.pushMany=function(e,t){for(const i of t)e.push(i)},t.mapArrayOrNot=function(e,t){return Array.isArray(e)?e.map(t):t(e)},t.asArray=function(e){return Array.isArray(e)?e:[e]},t.getRandomElement=function(e){return e[Math.floor(Math.random()*e.length)]},t.insertInto=h,t.splice=function(e,t,i,s){const r=c(e,t);let n=e.splice(r,i);return void 0===n&&(n=[]),h(e,r,s),n},t.compareBy=function(e,t){return(i,s)=>t(e(i),e(s))},t.tieBreakComparators=function(...e){return(t,i)=>{for(const s of e){const e=s(t,i);if(!d.isNeitherLessOrGreaterThan(e))return e}return d.neitherLessOrGreaterThan}},t.reverseOrder=function(e){return(t,i)=>-e(t,i)};const s=i(9807),r=i(8297);function n(e,t){let i=0,s=e-1;for(;i<=s;){const e=(i+s)/2|0,r=t(e);if(r<0)i=e+1;else{if(!(r>0))return e;s=e-1}}return-(i+1)}function o(e,t,i){const s=[];function r(e,t,i){if(0===t&&0===i.length)return;const r=s[s.length-1];r&&r.start+r.deleteCount===e?(r.deleteCount+=t,r.toInsert.push(...i)):s.push({start:e,deleteCount:t,toInsert:i})}let n=0,o=0;for(;;){if(n===e.length){r(n,0,t.slice(o));break}if(o===t.length){r(n,e.length-n,[]);break}const s=e[n],a=t[o],l=i(s,a);0===l?(n+=1,o+=1):l<0?(r(n,1,[]),n+=1):l>0&&(r(n,0,[a]),o+=1)}return s}function a(e,t,i,s,n){for(const o=i.length;s<n;s++){const n=e[s];if(t(n,i[o-1])<0){i.pop();const e=(0,r.findFirstIdxMonotonousOrArrLen)(i,(e=>t(n,e)<0));i.splice(e,0,n)}}}function l(e,t){const i=e.indexOf(t);if(i>-1)return e.splice(i,1),t}function h(e,t,i){const s=c(e,t),r=e.length,n=i.length;e.length=r+n;for(let t=r-1;t>=s;t--)e[t+n]=e[t];for(let t=0;t<n;t++)e[t+s]=i[t]}function c(e,t){return t<0?Math.max(t+e.length,0):Math.min(t,e.length)}var d;!function(e){e.isLessThan=function(e){return e<0},e.isLessThanOrEqual=function(e){return e<=0},e.isGreaterThan=function(e){return e>0},e.isNeitherLessOrGreaterThan=function(e){return 0===e},e.greaterThan=1,e.lessThan=-1,e.neitherLessOrGreaterThan=0}(d||(t.CompareResult=d={})),t.numberComparator=(e,t)=>e-t,t.booleanComparator=(e,i)=>(0,t.numberComparator)(e?1:0,i?1:0),t.ArrayQueue=class{constructor(e){this.items=e,this.firstIdx=0,this.lastIdx=this.items.length-1}get length(){return this.lastIdx-this.firstIdx+1}takeWhile(e){let t=this.firstIdx;for(;t<this.items.length&&e(this.items[t]);)t++;const i=t===this.firstIdx?null:this.items.slice(this.firstIdx,t);return this.firstIdx=t,i}takeFromEndWhile(e){let t=this.lastIdx;for(;t>=0&&e(this.items[t]);)t--;const i=t===this.lastIdx?null:this.items.slice(t+1,this.lastIdx+1);return this.lastIdx=t,i}peek(){if(0!==this.length)return this.items[this.firstIdx]}peekLast(){if(0!==this.length)return this.items[this.lastIdx]}dequeue(){const e=this.items[this.firstIdx];return this.firstIdx++,e}removeLast(){const e=this.items[this.lastIdx];return this.lastIdx--,e}takeCount(e){const t=this.items.slice(this.firstIdx,this.firstIdx+e);return this.firstIdx+=e,t}};class u{static{this.empty=new u((e=>{}))}constructor(e){this.iterate=e}forEach(e){this.iterate((t=>(e(t),!0)))}toArray(){const e=[];return this.iterate((t=>(e.push(t),!0))),e}filter(e){return new u((t=>this.iterate((i=>!e(i)||t(i)))))}map(e){return new u((t=>this.iterate((i=>t(e(i))))))}some(e){let t=!1;return this.iterate((i=>(t=e(i),!t))),t}findFirst(e){let t;return this.iterate((i=>!e(i)||(t=i,!1))),t}findLast(e){let t;return this.iterate((i=>(e(i)&&(t=i),!0))),t}findLastMaxBy(e){let t,i=!0;return this.iterate((s=>((i||d.isGreaterThan(e(s,t)))&&(i=!1,t=s),!0))),t}}t.CallbackIterable=u;class _{constructor(e){this._indexMap=e}static createSortPermutation(e,t){const i=Array.from(e.keys()).sort(((i,s)=>t(e[i],e[s])));return new _(i)}apply(e){return e.map(((t,i)=>e[this._indexMap[i]]))}inverse(){const e=this._indexMap.slice();for(let t=0;t<this._indexMap.length;t++)e[this._indexMap[t]]=t;return new _(e)}}t.Permutation=_},8297:(e,t)=>{function i(e,t,i=e.length-1){for(let s=i;s>=0;s--)if(t(e[s]))return s;return-1}function s(e,t,i=0,s=e.length){let r=i,n=s;for(;r<n;){const i=Math.floor((r+n)/2);t(e[i])?r=i+1:n=i}return r-1}function r(e,t,i=0,s=e.length){let r=i,n=s;for(;r<n;){const i=Math.floor((r+n)/2);t(e[i])?n=i:r=i+1}return r}Object.defineProperty(t,"__esModule",{value:!0}),t.MonotonousArray=void 0,t.findLast=function(e,t){const s=i(e,t);if(-1!==s)return e[s]},t.findLastIdx=i,t.findLastMonotonous=function(e,t){const i=s(e,t);return-1===i?void 0:e[i]},t.findLastIdxMonotonous=s,t.findFirstMonotonous=function(e,t){const i=r(e,t);return i===e.length?void 0:e[i]},t.findFirstIdxMonotonousOrArrLen=r,t.findFirstIdxMonotonous=function(e,t,i=0,s=e.length){const n=r(e,t,i,s);return n===e.length?-1:n},t.findFirstMax=o,t.findLastMax=function(e,t){if(0===e.length)return;let i=e[0];for(let s=1;s<e.length;s++){const r=e[s];t(r,i)>=0&&(i=r)}return i},t.findFirstMin=function(e,t){return o(e,((e,i)=>-t(e,i)))},t.findMaxIdx=function(e,t){if(0===e.length)return-1;let i=0;for(let s=1;s<e.length;s++)t(e[s],e[i])>0&&(i=s);return i},t.mapFindFirst=function(e,t){for(const i of e){const e=t(i);if(void 0!==e)return e}};class n{static{this.assertInvariants=!1}constructor(e){this._array=e,this._findLastMonotonousLastIdx=0}findLastMonotonous(e){if(n.assertInvariants){if(this._prevFindLastPredicate)for(const t of this._array)if(this._prevFindLastPredicate(t)&&!e(t))throw new Error("MonotonousArray: current predicate must be weaker than (or equal to) the previous predicate.");this._prevFindLastPredicate=e}const t=s(this._array,e,this._findLastMonotonousLastIdx);return this._findLastMonotonousLastIdx=t+1,-1===t?void 0:this._array[t]}}function o(e,t){if(0===e.length)return;let i=e[0];for(let s=1;s<e.length;s++){const r=e[s];t(r,i)>0&&(i=r)}return i}t.MonotonousArray=n},1758:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.AsyncIterableSource=t.CancelableAsyncIterableObject=t.AsyncIterableObject=t.LazyStatefulPromise=t.StatefulPromise=t.Promises=t.DeferredPromise=t.IntervalCounter=t.TaskSequentializer=t.GlobalIdleValue=t.AbstractIdleValue=t._runWhenIdle=t.runWhenGlobalIdle=t.ThrottledWorker=t.RunOnceWorker=t.ProcessTimeRunOnceScheduler=t.RunOnceScheduler=t.IntervalTimer=t.TimeoutTimer=t.LimitedQueue=t.Queue=t.Limiter=t.AutoOpenBarrier=t.Barrier=t.ThrottledDelayer=t.Delayer=t.SequencerByKey=t.Sequencer=t.Throttler=void 0,t.isThenable=c,t.createCancelablePromise=d,t.raceCancellation=function(e,t,i){return new Promise(((s,r)=>{const n=t.onCancellationRequested((()=>{n.dispose(),s(i)}));e.then(s,r).finally((()=>n.dispose()))}))},t.raceCancellationError=function(e,t){return new Promise(((i,s)=>{const n=t.onCancellationRequested((()=>{n.dispose(),s(new r.CancellationError)}));e.then(i,s).finally((()=>n.dispose()))}))},t.raceCancellablePromises=async function(e){let t=-1;const i=e.map(((e,i)=>e.then((e=>(t=i,e)))));try{return await Promise.race(i)}finally{e.forEach(((e,i)=>{i!==t&&e.cancel()}))}},t.raceTimeout=function(e,t,i){let s;const r=setTimeout((()=>{s?.(void 0),i?.()}),t);return Promise.race([e.finally((()=>clearTimeout(r))),new Promise((e=>s=e))])},t.asPromise=function(e){return new Promise(((t,i)=>{const s=e();c(s)?s.then(t,i):t(s)}))},t.promiseWithResolvers=u,t.timeout=g,t.disposableTimeout=function(e,t=0,i){const s=setTimeout((()=>{e(),i&&r.dispose()}),t),r=(0,o.toDisposable)((()=>{clearTimeout(s),i?.deleteAndLeak(r)}));return i?.add(r),r},t.sequence=function(e){const t=[];let i=0;const s=e.length;return Promise.resolve(null).then((function r(n){null!=n&&t.push(n);const o=i<s?e[i++]():null;return o?o.then(r):Promise.resolve(t)}))},t.first=function(e,t=e=>!!e,i=null){let s=0;const r=e.length,n=()=>{if(s>=r)return Promise.resolve(i);const o=e[s++];return Promise.resolve(o()).then((e=>t(e)?Promise.resolve(e):n()))};return n()},t.firstParallel=function(e,t=e=>!!e,i=null){if(0===e.length)return Promise.resolve(i);let s=e.length;const r=()=>{s=-1;for(const t of e)t.cancel?.()};return new Promise(((n,o)=>{for(const a of e)a.then((e=>{--s>=0&&t(e)?(r(),n(e)):0===s&&n(i)})).catch((e=>{--s>=0&&(r(),o(e))}))}))},t.retry=async function(e,t,i){let s;for(let r=0;r<i;r++)try{return await e()}catch(e){s=e,await g(t)}throw s},t.createCancelableAsyncIterable=function(e){const t=new s.CancellationTokenSource,i=e(t.token);return new A(t,(async e=>{const s=t.token.onCancellationRequested((()=>{s.dispose(),t.dispose(),e.reject(new r.CancellationError)}));try{for await(const s of i){if(t.token.isCancellationRequested)return;e.emitOne(s)}s.dispose(),t.dispose()}catch(i){s.dispose(),t.dispose(),e.reject(i)}}))};const s=i(8447),r=i(9807),n=i(802),o=i(7150),a=i(8163),l=i(5015),h=i(626);function c(e){return!!e&&"function"==typeof e.then}function d(e){const t=new s.CancellationTokenSource,i=e(t.token),n=new Promise(((e,s)=>{const n=t.token.onCancellationRequested((()=>{n.dispose(),s(new r.CancellationError)}));Promise.resolve(i).then((i=>{n.dispose(),t.dispose(),e(i)}),(e=>{n.dispose(),t.dispose(),s(e)}))}));return new class{cancel(){t.cancel(),t.dispose()}then(e,t){return n.then(e,t)}catch(e){return this.then(void 0,e)}finally(e){return n.finally(e)}}}function u(){let e,t;return{promise:new Promise(((i,s)=>{e=i,t=s})),resolve:e,reject:t}}class _{constructor(){this.isDisposed=!1,this.activePromise=null,this.queuedPromise=null,this.queuedPromiseFactory=null}queue(e){if(this.isDisposed)return Promise.reject(new Error("Throttler is disposed"));if(this.activePromise){if(this.queuedPromiseFactory=e,!this.queuedPromise){const e=()=>{if(this.queuedPromise=null,this.isDisposed)return;const e=this.queue(this.queuedPromiseFactory);return this.queuedPromiseFactory=null,e};this.queuedPromise=new Promise((t=>{this.activePromise.then(e,e).then(t)}))}return new Promise(((e,t)=>{this.queuedPromise.then(e,t)}))}return this.activePromise=e(),new Promise(((e,t)=>{this.activePromise.then((t=>{this.activePromise=null,e(t)}),(e=>{this.activePromise=null,t(e)}))}))}dispose(){this.isDisposed=!0}}t.Throttler=_,t.Sequencer=class{constructor(){this.current=Promise.resolve(null)}queue(e){return this.current=this.current.then((()=>e()),(()=>e()))}},t.SequencerByKey=class{constructor(){this.promiseMap=new Map}queue(e,t){const i=(this.promiseMap.get(e)??Promise.resolve()).catch((()=>{})).then(t).finally((()=>{this.promiseMap.get(e)===i&&this.promiseMap.delete(e)}));return this.promiseMap.set(e,i),i}};class f{constructor(e){this.defaultDelay=e,this.deferred=null,this.completionPromise=null,this.doResolve=null,this.doReject=null,this.task=null}trigger(e,t=this.defaultDelay){this.task=e,this.cancelTimeout(),this.completionPromise||(this.completionPromise=new Promise(((e,t)=>{this.doResolve=e,this.doReject=t})).then((()=>{if(this.completionPromise=null,this.doResolve=null,this.task){const e=this.task;return this.task=null,e()}})));const i=()=>{this.deferred=null,this.doResolve?.(null)};return this.deferred=t===l.MicrotaskDelay?(e=>{let t=!0;return queueMicrotask((()=>{t&&(t=!1,e())})),{isTriggered:()=>t,dispose:()=>{t=!1}}})(i):((e,t)=>{let i=!0;const s=setTimeout((()=>{i=!1,t()}),e);return{isTriggered:()=>i,dispose:()=>{clearTimeout(s),i=!1}}})(t,i),this.completionPromise}isTriggered(){return!!this.deferred?.isTriggered()}cancel(){this.cancelTimeout(),this.completionPromise&&(this.doReject?.(new r.CancellationError),this.completionPromise=null)}cancelTimeout(){this.deferred?.dispose(),this.deferred=null}dispose(){this.cancel()}}t.Delayer=f,t.ThrottledDelayer=class{constructor(e){this.delayer=new f(e),this.throttler=new _}trigger(e,t){return this.delayer.trigger((()=>this.throttler.queue(e)),t)}isTriggered(){return this.delayer.isTriggered()}cancel(){this.delayer.cancel()}dispose(){this.delayer.dispose(),this.throttler.dispose()}};class p{constructor(){this._isOpen=!1,this._promise=new Promise(((e,t)=>{this._completePromise=e}))}isOpen(){return this._isOpen}open(){this._isOpen=!0,this._completePromise(!0)}wait(){return this._promise}}function g(e,t){return t?new Promise(((i,s)=>{const n=setTimeout((()=>{o.dispose(),i()}),e),o=t.onCancellationRequested((()=>{clearTimeout(n),o.dispose(),s(new r.CancellationError)}))})):d((t=>g(e,t)))}t.Barrier=p,t.AutoOpenBarrier=class extends p{constructor(e){super(),this._timeout=setTimeout((()=>this.open()),e)}open(){clearTimeout(this._timeout),super.open()}};class m{constructor(e){this._size=0,this._isDisposed=!1,this.maxDegreeOfParalellism=e,this.outstandingPromises=[],this.runningPromises=0,this._onDrained=new n.Emitter}whenIdle(){return this.size>0?n.Event.toPromise(this.onDrained):Promise.resolve()}get onDrained(){return this._onDrained.event}get size(){return this._size}queue(e){if(this._isDisposed)throw new Error("Object has been disposed");return this._size++,new Promise(((t,i)=>{this.outstandingPromises.push({factory:e,c:t,e:i}),this.consume()}))}consume(){for(;this.outstandingPromises.length&&this.runningPromises<this.maxDegreeOfParalellism;){const e=this.outstandingPromises.shift();this.runningPromises++;const t=e.factory();t.then(e.c,e.e),t.then((()=>this.consumed()),(()=>this.consumed()))}}consumed(){this._isDisposed||(this.runningPromises--,0==--this._size&&this._onDrained.fire(),this.outstandingPromises.length>0&&this.consume())}clear(){if(this._isDisposed)throw new Error("Object has been disposed");this.outstandingPromises.length=0,this._size=this.runningPromises}dispose(){this._isDisposed=!0,this.outstandingPromises.length=0,this._size=0,this._onDrained.dispose()}}t.Limiter=m,t.Queue=class extends m{constructor(){super(1)}},t.LimitedQueue=class{constructor(){this.sequentializer=new C,this.tasks=0}queue(e){return this.sequentializer.isRunning()?this.sequentializer.queue((()=>this.sequentializer.run(this.tasks++,e()))):this.sequentializer.run(this.tasks++,e())}},t.TimeoutTimer=class{constructor(e,t){this._isDisposed=!1,this._token=-1,"function"==typeof e&&"number"==typeof t&&this.setIfNotSet(e,t)}dispose(){this.cancel(),this._isDisposed=!0}cancel(){-1!==this._token&&(clearTimeout(this._token),this._token=-1)}cancelAndSet(e,t){if(this._isDisposed)throw new r.BugIndicatingError("Calling \'cancelAndSet\' on a disposed TimeoutTimer");this.cancel(),this._token=setTimeout((()=>{this._token=-1,e()}),t)}setIfNotSet(e,t){if(this._isDisposed)throw new r.BugIndicatingError("Calling \'setIfNotSet\' on a disposed TimeoutTimer");-1===this._token&&(this._token=setTimeout((()=>{this._token=-1,e()}),t))}},t.IntervalTimer=class{constructor(){this.disposable=void 0,this.isDisposed=!1}cancel(){this.disposable?.dispose(),this.disposable=void 0}cancelAndSet(e,t,i=globalThis){if(this.isDisposed)throw new r.BugIndicatingError("Calling \'cancelAndSet\' on a disposed IntervalTimer");this.cancel();const s=i.setInterval((()=>{e()}),t);this.disposable=(0,o.toDisposable)((()=>{i.clearInterval(s),this.disposable=void 0}))}dispose(){this.cancel(),this.isDisposed=!0}};class v{constructor(e,t){this.timeoutToken=-1,this.runner=e,this.timeout=t,this.timeoutHandler=this.onTimeout.bind(this)}dispose(){this.cancel(),this.runner=null}cancel(){this.isScheduled()&&(clearTimeout(this.timeoutToken),this.timeoutToken=-1)}schedule(e=this.timeout){this.cancel(),this.timeoutToken=setTimeout(this.timeoutHandler,e)}get delay(){return this.timeout}set delay(e){this.timeout=e}isScheduled(){return-1!==this.timeoutToken}flush(){this.isScheduled()&&(this.cancel(),this.doRun())}onTimeout(){this.timeoutToken=-1,this.runner&&this.doRun()}doRun(){this.runner?.()}}t.RunOnceScheduler=v,t.ProcessTimeRunOnceScheduler=class{constructor(e,t){t%1e3!=0&&console.warn(`ProcessTimeRunOnceScheduler resolution is 1s, ${t}ms is not a multiple of 1000ms.`),this.runner=e,this.timeout=t,this.counter=0,this.intervalToken=-1,this.intervalHandler=this.onInterval.bind(this)}dispose(){this.cancel(),this.runner=null}cancel(){this.isScheduled()&&(clearInterval(this.intervalToken),this.intervalToken=-1)}schedule(e=this.timeout){e%1e3!=0&&console.warn(`ProcessTimeRunOnceScheduler resolution is 1s, ${e}ms is not a multiple of 1000ms.`),this.cancel(),this.counter=Math.ceil(e/1e3),this.intervalToken=setInterval(this.intervalHandler,1e3)}isScheduled(){return-1!==this.intervalToken}onInterval(){this.counter--,this.counter>0||(clearInterval(this.intervalToken),this.intervalToken=-1,this.runner?.())}},t.RunOnceWorker=class extends v{constructor(e,t){super(e,t),this.units=[]}work(e){this.units.push(e),this.isScheduled()||this.schedule()}doRun(){const e=this.units;this.units=[],this.runner?.(e)}dispose(){this.units=[],super.dispose()}};class S extends o.Disposable{constructor(e,t){super(),this.options=e,this.handler=t,this.pendingWork=[],this.throttler=this._register(new o.MutableDisposable),this.disposed=!1}get pending(){return this.pendingWork.length}work(e){if(this.disposed)return!1;if("number"==typeof this.options.maxBufferedWork)if(this.throttler.value){if(this.pending+e.length>this.options.maxBufferedWork)return!1}else if(this.pending+e.length-this.options.maxWorkChunkSize>this.options.maxBufferedWork)return!1;for(const t of e)this.pendingWork.push(t);return this.throttler.value||this.doWork(),!0}doWork(){this.handler(this.pendingWork.splice(0,this.options.maxWorkChunkSize)),this.pendingWork.length>0&&(this.throttler.value=new v((()=>{this.throttler.clear(),this.doWork()}),this.options.throttleDelay),this.throttler.value.schedule())}dispose(){super.dispose(),this.disposed=!0}}t.ThrottledWorker=S,"function"!=typeof globalThis.requestIdleCallback||"function"!=typeof globalThis.cancelIdleCallback?t._runWhenIdle=(e,t)=>{(0,a.setTimeout0)((()=>{if(i)return;const e=Date.now()+15,s={didTimeout:!0,timeRemaining:()=>Math.max(0,e-Date.now())};t(Object.freeze(s))}));let i=!1;return{dispose(){i||(i=!0)}}}:t._runWhenIdle=(e,t,i)=>{const s=e.requestIdleCallback(t,"number"==typeof i?{timeout:i}:void 0);let r=!1;return{dispose(){r||(r=!0,e.cancelIdleCallback(s))}}},t.runWhenGlobalIdle=e=>(0,t._runWhenIdle)(globalThis,e);class b{constructor(e,i){this._didRun=!1,this._executor=()=>{try{this._value=i()}catch(e){this._error=e}finally{this._didRun=!0}},this._handle=(0,t._runWhenIdle)(e,(()=>this._executor()))}dispose(){this._handle.dispose()}get value(){if(this._didRun||(this._handle.dispose(),this._executor()),this._error)throw this._error;return this._value}get isInitialized(){return this._didRun}}t.AbstractIdleValue=b,t.GlobalIdleValue=class extends b{constructor(e){super(globalThis,e)}};class C{isRunning(e){return"number"==typeof e?this._running?.taskId===e:!!this._running}get running(){return this._running?.promise}cancelRunning(){this._running?.cancel()}run(e,t,i){return this._running={taskId:e,cancel:()=>i?.(),promise:t},t.then((()=>this.doneRunning(e)),(()=>this.doneRunning(e))),t}doneRunning(e){this._running&&e===this._running.taskId&&(this._running=void 0,this.runQueued())}runQueued(){if(this._queued){const e=this._queued;this._queued=void 0,e.run().then(e.promiseResolve,e.promiseReject)}}queue(e){if(this._queued)this._queued.run=e;else{const{promise:t,resolve:i,reject:s}=u();this._queued={run:e,promise:t,promiseResolve:i,promiseReject:s}}return this._queued.promise}hasQueued(){return!!this._queued}async join(){return this._queued?.promise??this._running?.promise}}var y,w,E;t.TaskSequentializer=C,t.IntervalCounter=class{constructor(e,t=()=>Date.now()){this.interval=e,this.nowFn=t,this.lastIncrementTime=0,this.value=0}increment(){const e=this.nowFn();return e-this.lastIncrementTime>this.interval&&(this.lastIncrementTime=e,this.value=0),this.value++,this.value}},function(e){e[e.Resolved=0]="Resolved",e[e.Rejected=1]="Rejected"}(y||(y={}));class D{get isRejected(){return this.outcome?.outcome===y.Rejected}get isResolved(){return this.outcome?.outcome===y.Resolved}get isSettled(){return!!this.outcome}get value(){return this.outcome?.outcome===y.Resolved?this.outcome?.value:void 0}constructor(){this.p=new Promise(((e,t)=>{this.completeCallback=e,this.errorCallback=t}))}complete(e){return new Promise((t=>{this.completeCallback(e),this.outcome={outcome:y.Resolved,value:e},t()}))}error(e){return new Promise((t=>{this.errorCallback(e),this.outcome={outcome:y.Rejected,value:e},t()}))}cancel(){return this.error(new r.CancellationError)}}t.DeferredPromise=D,function(e){e.settled=async function(e){let t;const i=await Promise.all(e.map((e=>e.then((e=>e),(e=>{t||(t=e)})))));if(void 0!==t)throw t;return i},e.withAsyncBody=function(e){return new Promise((async(t,i)=>{try{await e(t,i)}catch(e){i(e)}}))}}(w||(t.Promises=w={}));class L{get value(){return this._value}get error(){return this._error}get isResolved(){return this._isResolved}constructor(e){this._value=void 0,this._error=void 0,this._isResolved=!1,this.promise=e.then((e=>(this._value=e,this._isResolved=!0,e)),(e=>{throw this._error=e,this._isResolved=!0,e}))}requireValue(){if(!this._isResolved)throw new r.BugIndicatingError("Promise is not resolved yet");if(this._error)throw this._error;return this._value}}t.StatefulPromise=L,t.LazyStatefulPromise=class{constructor(e){this._compute=e,this._promise=new h.Lazy((()=>new L(this._compute())))}requireValue(){return this._promise.value.requireValue()}getPromise(){return this._promise.value.promise}get currentValue(){return this._promise.rawValue?.value}},function(e){e[e.Initial=0]="Initial",e[e.DoneOK=1]="DoneOK",e[e.DoneError=2]="DoneError"}(E||(E={}));class R{static fromArray(e){return new R((t=>{t.emitMany(e)}))}static fromPromise(e){return new R((async t=>{t.emitMany(await e)}))}static fromPromises(e){return new R((async t=>{await Promise.all(e.map((async e=>t.emitOne(await e))))}))}static merge(e){return new R((async t=>{await Promise.all(e.map((async e=>{for await(const i of e)t.emitOne(i)})))}))}static{this.EMPTY=R.fromArray([])}constructor(e,t){this._state=E.Initial,this._results=[],this._error=null,this._onReturn=t,this._onStateChanged=new n.Emitter,queueMicrotask((async()=>{const t={emitOne:e=>this.emitOne(e),emitMany:e=>this.emitMany(e),reject:e=>this.reject(e)};try{await Promise.resolve(e(t)),this.resolve()}catch(e){this.reject(e)}finally{t.emitOne=void 0,t.emitMany=void 0,t.reject=void 0}}))}[Symbol.asyncIterator](){let e=0;return{next:async()=>{for(;;){if(this._state===E.DoneError)throw this._error;if(e<this._results.length)return{done:!1,value:this._results[e++]};if(this._state===E.DoneOK)return{done:!0,value:void 0};await n.Event.toPromise(this._onStateChanged.event)}},return:async()=>(this._onReturn?.(),{done:!0,value:void 0})}}static map(e,t){return new R((async i=>{for await(const s of e)i.emitOne(t(s))}))}map(e){return R.map(this,e)}static filter(e,t){return new R((async i=>{for await(const s of e)t(s)&&i.emitOne(s)}))}filter(e){return R.filter(this,e)}static coalesce(e){return R.filter(e,(e=>!!e))}coalesce(){return R.coalesce(this)}static async toPromise(e){const t=[];for await(const i of e)t.push(i);return t}toPromise(){return R.toPromise(this)}emitOne(e){this._state===E.Initial&&(this._results.push(e),this._onStateChanged.fire())}emitMany(e){this._state===E.Initial&&(this._results=this._results.concat(e),this._onStateChanged.fire())}resolve(){this._state===E.Initial&&(this._state=E.DoneOK,this._onStateChanged.fire())}reject(e){this._state===E.Initial&&(this._state=E.DoneError,this._error=e,this._onStateChanged.fire())}}t.AsyncIterableObject=R;class A extends R{constructor(e,t){super(t),this._source=e}cancel(){this._source.cancel()}}t.CancelableAsyncIterableObject=A,t.AsyncIterableSource=class{constructor(e){let t,i;this._deferred=new D,this._asyncIterable=new R((e=>{if(!t)return i&&e.emitMany(i),this._errorFn=t=>e.reject(t),this._emitFn=t=>e.emitOne(t),this._deferred.p;e.reject(t)}),e),this._emitFn=e=>{i||(i=[]),i.push(e)},this._errorFn=e=>{t||(t=e)}}get asyncIterable(){return this._asyncIterable}resolve(){this._deferred.complete()}reject(e){this._errorFn(e),this._deferred.complete()}emitOne(e){this._emitFn(e)}}},8447:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.CancellationTokenSource=t.CancellationToken=void 0,t.cancelOnDispose=function(e){const t=new a;return e.add({dispose(){t.cancel()}}),t.token};const s=i(802),r=Object.freeze((function(e,t){const i=setTimeout(e.bind(t),0);return{dispose(){clearTimeout(i)}}}));var n;!function(e){e.isCancellationToken=function(t){return t===e.None||t===e.Cancelled||t instanceof o||!(!t||"object"!=typeof t)&&"boolean"==typeof t.isCancellationRequested&&"function"==typeof t.onCancellationRequested},e.None=Object.freeze({isCancellationRequested:!1,onCancellationRequested:s.Event.None}),e.Cancelled=Object.freeze({isCancellationRequested:!0,onCancellationRequested:r})}(n||(t.CancellationToken=n={}));class o{constructor(){this._isCancelled=!1,this._emitter=null}cancel(){this._isCancelled||(this._isCancelled=!0,this._emitter&&(this._emitter.fire(void 0),this.dispose()))}get isCancellationRequested(){return this._isCancelled}get onCancellationRequested(){return this._isCancelled?r:(this._emitter||(this._emitter=new s.Emitter),this._emitter.event)}dispose(){this._emitter&&(this._emitter.dispose(),this._emitter=null)}}class a{constructor(e){this._token=void 0,this._parentListener=void 0,this._parentListener=e&&e.onCancellationRequested(this.cancel,this)}get token(){return this._token||(this._token=new o),this._token}cancel(){this._token?this._token instanceof o&&this._token.cancel():this._token=n.Cancelled}dispose(e=!1){e&&this.cancel(),this._parentListener?.dispose(),this._token?this._token instanceof o&&this._token.dispose():this._token=n.None}}t.CancellationTokenSource=a},4869:(e,t)=>{var i;Object.defineProperty(t,"__esModule",{value:!0}),t.CharCode=void 0,function(e){e[e.Null=0]="Null",e[e.Backspace=8]="Backspace",e[e.Tab=9]="Tab",e[e.LineFeed=10]="LineFeed",e[e.CarriageReturn=13]="CarriageReturn",e[e.Space=32]="Space",e[e.ExclamationMark=33]="ExclamationMark",e[e.DoubleQuote=34]="DoubleQuote",e[e.Hash=35]="Hash",e[e.DollarSign=36]="DollarSign",e[e.PercentSign=37]="PercentSign",e[e.Ampersand=38]="Ampersand",e[e.SingleQuote=39]="SingleQuote",e[e.OpenParen=40]="OpenParen",e[e.CloseParen=41]="CloseParen",e[e.Asterisk=42]="Asterisk",e[e.Plus=43]="Plus",e[e.Comma=44]="Comma",e[e.Dash=45]="Dash",e[e.Period=46]="Period",e[e.Slash=47]="Slash",e[e.Digit0=48]="Digit0",e[e.Digit1=49]="Digit1",e[e.Digit2=50]="Digit2",e[e.Digit3=51]="Digit3",e[e.Digit4=52]="Digit4",e[e.Digit5=53]="Digit5",e[e.Digit6=54]="Digit6",e[e.Digit7=55]="Digit7",e[e.Digit8=56]="Digit8",e[e.Digit9=57]="Digit9",e[e.Colon=58]="Colon",e[e.Semicolon=59]="Semicolon",e[e.LessThan=60]="LessThan",e[e.Equals=61]="Equals",e[e.GreaterThan=62]="GreaterThan",e[e.QuestionMark=63]="QuestionMark",e[e.AtSign=64]="AtSign",e[e.A=65]="A",e[e.B=66]="B",e[e.C=67]="C",e[e.D=68]="D",e[e.E=69]="E",e[e.F=70]="F",e[e.G=71]="G",e[e.H=72]="H",e[e.I=73]="I",e[e.J=74]="J",e[e.K=75]="K",e[e.L=76]="L",e[e.M=77]="M",e[e.N=78]="N",e[e.O=79]="O",e[e.P=80]="P",e[e.Q=81]="Q",e[e.R=82]="R",e[e.S=83]="S",e[e.T=84]="T",e[e.U=85]="U",e[e.V=86]="V",e[e.W=87]="W",e[e.X=88]="X",e[e.Y=89]="Y",e[e.Z=90]="Z",e[e.OpenSquareBracket=91]="OpenSquareBracket",e[e.Backslash=92]="Backslash",e[e.CloseSquareBracket=93]="CloseSquareBracket",e[e.Caret=94]="Caret",e[e.Underline=95]="Underline",e[e.BackTick=96]="BackTick",e[e.a=97]="a",e[e.b=98]="b",e[e.c=99]="c",e[e.d=100]="d",e[e.e=101]="e",e[e.f=102]="f",e[e.g=103]="g",e[e.h=104]="h",e[e.i=105]="i",e[e.j=106]="j",e[e.k=107]="k",e[e.l=108]="l",e[e.m=109]="m",e[e.n=110]="n",e[e.o=111]="o",e[e.p=112]="p",e[e.q=113]="q",e[e.r=114]="r",e[e.s=115]="s",e[e.t=116]="t",e[e.u=117]="u",e[e.v=118]="v",e[e.w=119]="w",e[e.x=120]="x",e[e.y=121]="y",e[e.z=122]="z",e[e.OpenCurlyBrace=123]="OpenCurlyBrace",e[e.Pipe=124]="Pipe",e[e.CloseCurlyBrace=125]="CloseCurlyBrace",e[e.Tilde=126]="Tilde",e[e.NoBreakSpace=160]="NoBreakSpace",e[e.U_Combining_Grave_Accent=768]="U_Combining_Grave_Accent",e[e.U_Combining_Acute_Accent=769]="U_Combining_Acute_Accent",e[e.U_Combining_Circumflex_Accent=770]="U_Combining_Circumflex_Accent",e[e.U_Combining_Tilde=771]="U_Combining_Tilde",e[e.U_Combining_Macron=772]="U_Combining_Macron",e[e.U_Combining_Overline=773]="U_Combining_Overline",e[e.U_Combining_Breve=774]="U_Combining_Breve",e[e.U_Combining_Dot_Above=775]="U_Combining_Dot_Above",e[e.U_Combining_Diaeresis=776]="U_Combining_Diaeresis",e[e.U_Combining_Hook_Above=777]="U_Combining_Hook_Above",e[e.U_Combining_Ring_Above=778]="U_Combining_Ring_Above",e[e.U_Combining_Double_Acute_Accent=779]="U_Combining_Double_Acute_Accent",e[e.U_Combining_Caron=780]="U_Combining_Caron",e[e.U_Combining_Vertical_Line_Above=781]="U_Combining_Vertical_Line_Above",e[e.U_Combining_Double_Vertical_Line_Above=782]="U_Combining_Double_Vertical_Line_Above",e[e.U_Combining_Double_Grave_Accent=783]="U_Combining_Double_Grave_Accent",e[e.U_Combining_Candrabindu=784]="U_Combining_Candrabindu",e[e.U_Combining_Inverted_Breve=785]="U_Combining_Inverted_Breve",e[e.U_Combining_Turned_Comma_Above=786]="U_Combining_Turned_Comma_Above",e[e.U_Combining_Comma_Above=787]="U_Combining_Comma_Above",e[e.U_Combining_Reversed_Comma_Above=788]="U_Combining_Reversed_Comma_Above",e[e.U_Combining_Comma_Above_Right=789]="U_Combining_Comma_Above_Right",e[e.U_Combining_Grave_Accent_Below=790]="U_Combining_Grave_Accent_Below",e[e.U_Combining_Acute_Accent_Below=791]="U_Combining_Acute_Accent_Below",e[e.U_Combining_Left_Tack_Below=792]="U_Combining_Left_Tack_Below",e[e.U_Combining_Right_Tack_Below=793]="U_Combining_Right_Tack_Below",e[e.U_Combining_Left_Angle_Above=794]="U_Combining_Left_Angle_Above",e[e.U_Combining_Horn=795]="U_Combining_Horn",e[e.U_Combining_Left_Half_Ring_Below=796]="U_Combining_Left_Half_Ring_Below",e[e.U_Combining_Up_Tack_Below=797]="U_Combining_Up_Tack_Below",e[e.U_Combining_Down_Tack_Below=798]="U_Combining_Down_Tack_Below",e[e.U_Combining_Plus_Sign_Below=799]="U_Combining_Plus_Sign_Below",e[e.U_Combining_Minus_Sign_Below=800]="U_Combining_Minus_Sign_Below",e[e.U_Combining_Palatalized_Hook_Below=801]="U_Combining_Palatalized_Hook_Below",e[e.U_Combining_Retroflex_Hook_Below=802]="U_Combining_Retroflex_Hook_Below",e[e.U_Combining_Dot_Below=803]="U_Combining_Dot_Below",e[e.U_Combining_Diaeresis_Below=804]="U_Combining_Diaeresis_Below",e[e.U_Combining_Ring_Below=805]="U_Combining_Ring_Below",e[e.U_Combining_Comma_Below=806]="U_Combining_Comma_Below",e[e.U_Combining_Cedilla=807]="U_Combining_Cedilla",e[e.U_Combining_Ogonek=808]="U_Combining_Ogonek",e[e.U_Combining_Vertical_Line_Below=809]="U_Combining_Vertical_Line_Below",e[e.U_Combining_Bridge_Below=810]="U_Combining_Bridge_Below",e[e.U_Combining_Inverted_Double_Arch_Below=811]="U_Combining_Inverted_Double_Arch_Below",e[e.U_Combining_Caron_Below=812]="U_Combining_Caron_Below",e[e.U_Combining_Circumflex_Accent_Below=813]="U_Combining_Circumflex_Accent_Below",e[e.U_Combining_Breve_Below=814]="U_Combining_Breve_Below",e[e.U_Combining_Inverted_Breve_Below=815]="U_Combining_Inverted_Breve_Below",e[e.U_Combining_Tilde_Below=816]="U_Combining_Tilde_Below",e[e.U_Combining_Macron_Below=817]="U_Combining_Macron_Below",e[e.U_Combining_Low_Line=818]="U_Combining_Low_Line",e[e.U_Combining_Double_Low_Line=819]="U_Combining_Double_Low_Line",e[e.U_Combining_Tilde_Overlay=820]="U_Combining_Tilde_Overlay",e[e.U_Combining_Short_Stroke_Overlay=821]="U_Combining_Short_Stroke_Overlay",e[e.U_Combining_Long_Stroke_Overlay=822]="U_Combining_Long_Stroke_Overlay",e[e.U_Combining_Short_Solidus_Overlay=823]="U_Combining_Short_Solidus_Overlay",e[e.U_Combining_Long_Solidus_Overlay=824]="U_Combining_Long_Solidus_Overlay",e[e.U_Combining_Right_Half_Ring_Below=825]="U_Combining_Right_Half_Ring_Below",e[e.U_Combining_Inverted_Bridge_Below=826]="U_Combining_Inverted_Bridge_Below",e[e.U_Combining_Square_Below=827]="U_Combining_Square_Below",e[e.U_Combining_Seagull_Below=828]="U_Combining_Seagull_Below",e[e.U_Combining_X_Above=829]="U_Combining_X_Above",e[e.U_Combining_Vertical_Tilde=830]="U_Combining_Vertical_Tilde",e[e.U_Combining_Double_Overline=831]="U_Combining_Double_Overline",e[e.U_Combining_Grave_Tone_Mark=832]="U_Combining_Grave_Tone_Mark",e[e.U_Combining_Acute_Tone_Mark=833]="U_Combining_Acute_Tone_Mark",e[e.U_Combining_Greek_Perispomeni=834]="U_Combining_Greek_Perispomeni",e[e.U_Combining_Greek_Koronis=835]="U_Combining_Greek_Koronis",e[e.U_Combining_Greek_Dialytika_Tonos=836]="U_Combining_Greek_Dialytika_Tonos",e[e.U_Combining_Greek_Ypogegrammeni=837]="U_Combining_Greek_Ypogegrammeni",e[e.U_Combining_Bridge_Above=838]="U_Combining_Bridge_Above",e[e.U_Combining_Equals_Sign_Below=839]="U_Combining_Equals_Sign_Below",e[e.U_Combining_Double_Vertical_Line_Below=840]="U_Combining_Double_Vertical_Line_Below",e[e.U_Combining_Left_Angle_Below=841]="U_Combining_Left_Angle_Below",e[e.U_Combining_Not_Tilde_Above=842]="U_Combining_Not_Tilde_Above",e[e.U_Combining_Homothetic_Above=843]="U_Combining_Homothetic_Above",e[e.U_Combining_Almost_Equal_To_Above=844]="U_Combining_Almost_Equal_To_Above",e[e.U_Combining_Left_Right_Arrow_Below=845]="U_Combining_Left_Right_Arrow_Below",e[e.U_Combining_Upwards_Arrow_Below=846]="U_Combining_Upwards_Arrow_Below",e[e.U_Combining_Grapheme_Joiner=847]="U_Combining_Grapheme_Joiner",e[e.U_Combining_Right_Arrowhead_Above=848]="U_Combining_Right_Arrowhead_Above",e[e.U_Combining_Left_Half_Ring_Above=849]="U_Combining_Left_Half_Ring_Above",e[e.U_Combining_Fermata=850]="U_Combining_Fermata",e[e.U_Combining_X_Below=851]="U_Combining_X_Below",e[e.U_Combining_Left_Arrowhead_Below=852]="U_Combining_Left_Arrowhead_Below",e[e.U_Combining_Right_Arrowhead_Below=853]="U_Combining_Right_Arrowhead_Below",e[e.U_Combining_Right_Arrowhead_And_Up_Arrowhead_Below=854]="U_Combining_Right_Arrowhead_And_Up_Arrowhead_Below",e[e.U_Combining_Right_Half_Ring_Above=855]="U_Combining_Right_Half_Ring_Above",e[e.U_Combining_Dot_Above_Right=856]="U_Combining_Dot_Above_Right",e[e.U_Combining_Asterisk_Below=857]="U_Combining_Asterisk_Below",e[e.U_Combining_Double_Ring_Below=858]="U_Combining_Double_Ring_Below",e[e.U_Combining_Zigzag_Above=859]="U_Combining_Zigzag_Above",e[e.U_Combining_Double_Breve_Below=860]="U_Combining_Double_Breve_Below",e[e.U_Combining_Double_Breve=861]="U_Combining_Double_Breve",e[e.U_Combining_Double_Macron=862]="U_Combining_Double_Macron",e[e.U_Combining_Double_Macron_Below=863]="U_Combining_Double_Macron_Below",e[e.U_Combining_Double_Tilde=864]="U_Combining_Double_Tilde",e[e.U_Combining_Double_Inverted_Breve=865]="U_Combining_Double_Inverted_Breve",e[e.U_Combining_Double_Rightwards_Arrow_Below=866]="U_Combining_Double_Rightwards_Arrow_Below",e[e.U_Combining_Latin_Small_Letter_A=867]="U_Combining_Latin_Small_Letter_A",e[e.U_Combining_Latin_Small_Letter_E=868]="U_Combining_Latin_Small_Letter_E",e[e.U_Combining_Latin_Small_Letter_I=869]="U_Combining_Latin_Small_Letter_I",e[e.U_Combining_Latin_Small_Letter_O=870]="U_Combining_Latin_Small_Letter_O",e[e.U_Combining_Latin_Small_Letter_U=871]="U_Combining_Latin_Small_Letter_U",e[e.U_Combining_Latin_Small_Letter_C=872]="U_Combining_Latin_Small_Letter_C",e[e.U_Combining_Latin_Small_Letter_D=873]="U_Combining_Latin_Small_Letter_D",e[e.U_Combining_Latin_Small_Letter_H=874]="U_Combining_Latin_Small_Letter_H",e[e.U_Combining_Latin_Small_Letter_M=875]="U_Combining_Latin_Small_Letter_M",e[e.U_Combining_Latin_Small_Letter_R=876]="U_Combining_Latin_Small_Letter_R",e[e.U_Combining_Latin_Small_Letter_T=877]="U_Combining_Latin_Small_Letter_T",e[e.U_Combining_Latin_Small_Letter_V=878]="U_Combining_Latin_Small_Letter_V",e[e.U_Combining_Latin_Small_Letter_X=879]="U_Combining_Latin_Small_Letter_X",e[e.LINE_SEPARATOR=8232]="LINE_SEPARATOR",e[e.PARAGRAPH_SEPARATOR=8233]="PARAGRAPH_SEPARATOR",e[e.NEXT_LINE=133]="NEXT_LINE",e[e.U_CIRCUMFLEX=94]="U_CIRCUMFLEX",e[e.U_GRAVE_ACCENT=96]="U_GRAVE_ACCENT",e[e.U_DIAERESIS=168]="U_DIAERESIS",e[e.U_MACRON=175]="U_MACRON",e[e.U_ACUTE_ACCENT=180]="U_ACUTE_ACCENT",e[e.U_CEDILLA=184]="U_CEDILLA",e[e.U_MODIFIER_LETTER_LEFT_ARROWHEAD=706]="U_MODIFIER_LETTER_LEFT_ARROWHEAD",e[e.U_MODIFIER_LETTER_RIGHT_ARROWHEAD=707]="U_MODIFIER_LETTER_RIGHT_ARROWHEAD",e[e.U_MODIFIER_LETTER_UP_ARROWHEAD=708]="U_MODIFIER_LETTER_UP_ARROWHEAD",e[e.U_MODIFIER_LETTER_DOWN_ARROWHEAD=709]="U_MODIFIER_LETTER_DOWN_ARROWHEAD",e[e.U_MODIFIER_LETTER_CENTRED_RIGHT_HALF_RING=722]="U_MODIFIER_LETTER_CENTRED_RIGHT_HALF_RING",e[e.U_MODIFIER_LETTER_CENTRED_LEFT_HALF_RING=723]="U_MODIFIER_LETTER_CENTRED_LEFT_HALF_RING",e[e.U_MODIFIER_LETTER_UP_TACK=724]="U_MODIFIER_LETTER_UP_TACK",e[e.U_MODIFIER_LETTER_DOWN_TACK=725]="U_MODIFIER_LETTER_DOWN_TACK",e[e.U_MODIFIER_LETTER_PLUS_SIGN=726]="U_MODIFIER_LETTER_PLUS_SIGN",e[e.U_MODIFIER_LETTER_MINUS_SIGN=727]="U_MODIFIER_LETTER_MINUS_SIGN",e[e.U_BREVE=728]="U_BREVE",e[e.U_DOT_ABOVE=729]="U_DOT_ABOVE",e[e.U_RING_ABOVE=730]="U_RING_ABOVE",e[e.U_OGONEK=731]="U_OGONEK",e[e.U_SMALL_TILDE=732]="U_SMALL_TILDE",e[e.U_DOUBLE_ACUTE_ACCENT=733]="U_DOUBLE_ACUTE_ACCENT",e[e.U_MODIFIER_LETTER_RHOTIC_HOOK=734]="U_MODIFIER_LETTER_RHOTIC_HOOK",e[e.U_MODIFIER_LETTER_CROSS_ACCENT=735]="U_MODIFIER_LETTER_CROSS_ACCENT",e[e.U_MODIFIER_LETTER_EXTRA_HIGH_TONE_BAR=741]="U_MODIFIER_LETTER_EXTRA_HIGH_TONE_BAR",e[e.U_MODIFIER_LETTER_HIGH_TONE_BAR=742]="U_MODIFIER_LETTER_HIGH_TONE_BAR",e[e.U_MODIFIER_LETTER_MID_TONE_BAR=743]="U_MODIFIER_LETTER_MID_TONE_BAR",e[e.U_MODIFIER_LETTER_LOW_TONE_BAR=744]="U_MODIFIER_LETTER_LOW_TONE_BAR",e[e.U_MODIFIER_LETTER_EXTRA_LOW_TONE_BAR=745]="U_MODIFIER_LETTER_EXTRA_LOW_TONE_BAR",e[e.U_MODIFIER_LETTER_YIN_DEPARTING_TONE_MARK=746]="U_MODIFIER_LETTER_YIN_DEPARTING_TONE_MARK",e[e.U_MODIFIER_LETTER_YANG_DEPARTING_TONE_MARK=747]="U_MODIFIER_LETTER_YANG_DEPARTING_TONE_MARK",e[e.U_MODIFIER_LETTER_UNASPIRATED=749]="U_MODIFIER_LETTER_UNASPIRATED",e[e.U_MODIFIER_LETTER_LOW_DOWN_ARROWHEAD=751]="U_MODIFIER_LETTER_LOW_DOWN_ARROWHEAD",e[e.U_MODIFIER_LETTER_LOW_UP_ARROWHEAD=752]="U_MODIFIER_LETTER_LOW_UP_ARROWHEAD",e[e.U_MODIFIER_LETTER_LOW_LEFT_ARROWHEAD=753]="U_MODIFIER_LETTER_LOW_LEFT_ARROWHEAD",e[e.U_MODIFIER_LETTER_LOW_RIGHT_ARROWHEAD=754]="U_MODIFIER_LETTER_LOW_RIGHT_ARROWHEAD",e[e.U_MODIFIER_LETTER_LOW_RING=755]="U_MODIFIER_LETTER_LOW_RING",e[e.U_MODIFIER_LETTER_MIDDLE_GRAVE_ACCENT=756]="U_MODIFIER_LETTER_MIDDLE_GRAVE_ACCENT",e[e.U_MODIFIER_LETTER_MIDDLE_DOUBLE_GRAVE_ACCENT=757]="U_MODIFIER_LETTER_MIDDLE_DOUBLE_GRAVE_ACCENT",e[e.U_MODIFIER_LETTER_MIDDLE_DOUBLE_ACUTE_ACCENT=758]="U_MODIFIER_LETTER_MIDDLE_DOUBLE_ACUTE_ACCENT",e[e.U_MODIFIER_LETTER_LOW_TILDE=759]="U_MODIFIER_LETTER_LOW_TILDE",e[e.U_MODIFIER_LETTER_RAISED_COLON=760]="U_MODIFIER_LETTER_RAISED_COLON",e[e.U_MODIFIER_LETTER_BEGIN_HIGH_TONE=761]="U_MODIFIER_LETTER_BEGIN_HIGH_TONE",e[e.U_MODIFIER_LETTER_END_HIGH_TONE=762]="U_MODIFIER_LETTER_END_HIGH_TONE",e[e.U_MODIFIER_LETTER_BEGIN_LOW_TONE=763]="U_MODIFIER_LETTER_BEGIN_LOW_TONE",e[e.U_MODIFIER_LETTER_END_LOW_TONE=764]="U_MODIFIER_LETTER_END_LOW_TONE",e[e.U_MODIFIER_LETTER_SHELF=765]="U_MODIFIER_LETTER_SHELF",e[e.U_MODIFIER_LETTER_OPEN_SHELF=766]="U_MODIFIER_LETTER_OPEN_SHELF",e[e.U_MODIFIER_LETTER_LOW_LEFT_ARROW=767]="U_MODIFIER_LETTER_LOW_LEFT_ARROW",e[e.U_GREEK_LOWER_NUMERAL_SIGN=885]="U_GREEK_LOWER_NUMERAL_SIGN",e[e.U_GREEK_TONOS=900]="U_GREEK_TONOS",e[e.U_GREEK_DIALYTIKA_TONOS=901]="U_GREEK_DIALYTIKA_TONOS",e[e.U_GREEK_KORONIS=8125]="U_GREEK_KORONIS",e[e.U_GREEK_PSILI=8127]="U_GREEK_PSILI",e[e.U_GREEK_PERISPOMENI=8128]="U_GREEK_PERISPOMENI",e[e.U_GREEK_DIALYTIKA_AND_PERISPOMENI=8129]="U_GREEK_DIALYTIKA_AND_PERISPOMENI",e[e.U_GREEK_PSILI_AND_VARIA=8141]="U_GREEK_PSILI_AND_VARIA",e[e.U_GREEK_PSILI_AND_OXIA=8142]="U_GREEK_PSILI_AND_OXIA",e[e.U_GREEK_PSILI_AND_PERISPOMENI=8143]="U_GREEK_PSILI_AND_PERISPOMENI",e[e.U_GREEK_DASIA_AND_VARIA=8157]="U_GREEK_DASIA_AND_VARIA",e[e.U_GREEK_DASIA_AND_OXIA=8158]="U_GREEK_DASIA_AND_OXIA",e[e.U_GREEK_DASIA_AND_PERISPOMENI=8159]="U_GREEK_DASIA_AND_PERISPOMENI",e[e.U_GREEK_DIALYTIKA_AND_VARIA=8173]="U_GREEK_DIALYTIKA_AND_VARIA",e[e.U_GREEK_DIALYTIKA_AND_OXIA=8174]="U_GREEK_DIALYTIKA_AND_OXIA",e[e.U_GREEK_VARIA=8175]="U_GREEK_VARIA",e[e.U_GREEK_OXIA=8189]="U_GREEK_OXIA",e[e.U_GREEK_DASIA=8190]="U_GREEK_DASIA",e[e.U_IDEOGRAPHIC_FULL_STOP=12290]="U_IDEOGRAPHIC_FULL_STOP",e[e.U_LEFT_CORNER_BRACKET=12300]="U_LEFT_CORNER_BRACKET",e[e.U_RIGHT_CORNER_BRACKET=12301]="U_RIGHT_CORNER_BRACKET",e[e.U_LEFT_BLACK_LENTICULAR_BRACKET=12304]="U_LEFT_BLACK_LENTICULAR_BRACKET",e[e.U_RIGHT_BLACK_LENTICULAR_BRACKET=12305]="U_RIGHT_BLACK_LENTICULAR_BRACKET",e[e.U_OVERLINE=8254]="U_OVERLINE",e[e.UTF8_BOM=65279]="UTF8_BOM",e[e.U_FULLWIDTH_SEMICOLON=65307]="U_FULLWIDTH_SEMICOLON",e[e.U_FULLWIDTH_COMMA=65292]="U_FULLWIDTH_COMMA"}(i||(t.CharCode=i={}))},9087:(e,t)=>{var i;Object.defineProperty(t,"__esModule",{value:!0}),t.SetWithKey=void 0,t.groupBy=function(e,t){const i=Object.create(null);for(const s of e){const e=t(s);let r=i[e];r||(r=i[e]=[]),r.push(s)}return i},t.diffSets=function(e,t){const i=[],s=[];for(const s of e)t.has(s)||i.push(s);for(const i of t)e.has(i)||s.push(i);return{removed:i,added:s}},t.diffMaps=function(e,t){const i=[],s=[];for(const[s,r]of e)t.has(s)||i.push(r);for(const[i,r]of t)e.has(i)||s.push(r);return{removed:i,added:s}},t.intersection=function(e,t){const i=new Set;for(const s of t)e.has(s)&&i.add(s);return i};class s{static{i=Symbol.toStringTag}constructor(e,t){this.toKey=t,this._map=new Map,this[i]="SetWithKey";for(const t of e)this.add(t)}get size(){return this._map.size}add(e){const t=this.toKey(e);return this._map.set(t,e),this}delete(e){return this._map.delete(this.toKey(e))}has(e){return this._map.has(this.toKey(e))}*entries(){for(const e of this._map.values())yield[e,e]}keys(){return this.values()}*values(){for(const e of this._map.values())yield e}clear(){this._map.clear()}forEach(e,t){this._map.forEach((i=>e.call(t,i,i,this)))}[Symbol.iterator](){return this.values()}}t.SetWithKey=s},4838:(e,t)=>{function i(e){return(t,i,s)=>{let r=null,n=null;if("function"==typeof s.value?(r="value",n=s.value):"function"==typeof s.get&&(r="get",n=s.get),!n)throw new Error("not supported");s[r]=e(n,i)}}Object.defineProperty(t,"__esModule",{value:!0}),t.memoize=function(e,t,i){let s=null,r=null;if("function"==typeof i.value?(s="value",r=i.value,0!==r.length&&console.warn("Memoize should only be used in functions with zero parameters")):"function"==typeof i.get&&(s="get",r=i.get),!r)throw new Error("not supported");const n=`$memoize$${t}`;i[s]=function(...e){return this.hasOwnProperty(n)||Object.defineProperty(this,n,{configurable:!1,enumerable:!1,writable:!1,value:r.apply(this,e)}),this[n]}},t.debounce=function(e,t,s){return i(((i,r)=>{const n=`$debounce$${r}`,o=`$debounce$result$${r}`;return function(...r){this[o]||(this[o]=s?s():void 0),clearTimeout(this[n]),t&&(this[o]=t(this[o],...r),r=[this[o]]),this[n]=setTimeout((()=>{i.apply(this,r),this[o]=s?s():void 0}),e)}}))},t.throttle=function(e,t,s){return i(((i,r)=>{const n=`$throttle$timer$${r}`,o=`$throttle$result$${r}`,a=`$throttle$lastRun$${r}`,l=`$throttle$pending$${r}`;return function(...r){if(this[o]||(this[o]=s?s():void 0),null!==this[a]&&void 0!==this[a]||(this[a]=-Number.MAX_VALUE),t&&(this[o]=t(this[o],...r)),this[l])return;const h=this[a]+e;h<=Date.now()?(this[a]=Date.now(),i.apply(this,[this[o]]),this[o]=s?s():void 0):(this[l]=!0,this[n]=setTimeout((()=>{this[l]=!1,this[a]=Date.now(),i.apply(this,[this[o]]),this[o]=s?s():void 0}),h-Date.now()))}}))}},9807:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.BugIndicatingError=t.ErrorNoTelemetry=t.ExpectedError=t.NotSupportedError=t.NotImplementedError=t.ReadonlyError=t.CancellationError=t.errorHandler=t.ErrorHandler=void 0,t.setUnexpectedErrorHandler=function(e){t.errorHandler.setUnexpectedErrorHandler(e)},t.isSigPipeError=function(e){if(!e||"object"!=typeof e)return!1;const t=e;return"EPIPE"===t.code&&"WRITE"===t.syscall?.toUpperCase()},t.onUnexpectedError=function(e){r(e)||t.errorHandler.onUnexpectedError(e)},t.onUnexpectedExternalError=function(e){r(e)||t.errorHandler.onUnexpectedExternalError(e)},t.transformErrorForSerialization=function(e){if(e instanceof Error){const{name:t,message:i}=e;return{$isError:!0,name:t,message:i,stack:e.stacktrace||e.stack,noTelemetry:c.isErrorNoTelemetry(e)}}return e},t.transformErrorFromSerialization=function(e){let t;return e.noTelemetry?t=new c:(t=new Error,t.name=e.name),t.message=e.message,t.stack=e.stack,t},t.isCancellationError=r,t.canceled=function(){const e=new Error(s);return e.name=e.message,e},t.illegalArgument=function(e){return e?new Error(`Illegal argument: ${e}`):new Error("Illegal argument")},t.illegalState=function(e){return e?new Error(`Illegal state: ${e}`):new Error("Illegal state")},t.getErrorMessage=function(e){return e?e.message?e.message:e.stack?e.stack.split("\\n")[0]:String(e):"Error"};class i{constructor(){this.listeners=[],this.unexpectedErrorHandler=function(e){setTimeout((()=>{if(e.stack){if(c.isErrorNoTelemetry(e))throw new c(e.message+"\\n\\n"+e.stack);throw new Error(e.message+"\\n\\n"+e.stack)}throw e}),0)}}addListener(e){return this.listeners.push(e),()=>{this._removeListener(e)}}emit(e){this.listeners.forEach((t=>{t(e)}))}_removeListener(e){this.listeners.splice(this.listeners.indexOf(e),1)}setUnexpectedErrorHandler(e){this.unexpectedErrorHandler=e}getUnexpectedErrorHandler(){return this.unexpectedErrorHandler}onUnexpectedError(e){this.unexpectedErrorHandler(e),this.emit(e)}onUnexpectedExternalError(e){this.unexpectedErrorHandler(e)}}t.ErrorHandler=i,t.errorHandler=new i;const s="Canceled";function r(e){return e instanceof n||e instanceof Error&&e.name===s&&e.message===s}class n extends Error{constructor(){super(s),this.name=this.message}}t.CancellationError=n;class o extends TypeError{constructor(e){super(e?`${e} is read-only and cannot be changed`:"Cannot change read-only property")}}t.ReadonlyError=o;class a extends Error{constructor(e){super("NotImplemented"),e&&(this.message=e)}}t.NotImplementedError=a;class l extends Error{constructor(e){super("NotSupported"),e&&(this.message=e)}}t.NotSupportedError=l;class h extends Error{constructor(){super(...arguments),this.isExpected=!0}}t.ExpectedError=h;class c extends Error{constructor(e){super(e),this.name="CodeExpectedError"}static fromError(e){if(e instanceof c)return e;const t=new c;return t.message=e.message,t.stack=e.stack,t}static isErrorNoTelemetry(e){return"CodeExpectedError"===e.name}}t.ErrorNoTelemetry=c;class d extends Error{constructor(e){super(e||"An unexpected bug occurred."),Object.setPrototypeOf(this,d.prototype)}}t.BugIndicatingError=d},802:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ValueWithChangeEvent=t.Relay=t.EventBufferer=t.DynamicListEventMultiplexer=t.EventMultiplexer=t.MicrotaskEmitter=t.DebounceEmitter=t.PauseableEmitter=t.AsyncEmitter=t.createEventDeliveryQueue=t.Emitter=t.ListenerRefusalError=t.ListenerLeakError=t.EventProfiling=t.Event=void 0,t.setGlobalLeakWarningThreshold=function(e){const t=c;return c=e,{dispose(){c=t}}};const s=i(9807),r=i(8841),n=i(7150),o=i(6317),a=i(9725);var l;!function(e){function t(e){return(t,i=null,s)=>{let r,n=!1;return r=e((e=>{if(!n)return r?r.dispose():n=!0,t.call(i,e)}),null,s),n&&r.dispose(),r}}function i(e,t,i){return r(((i,s=null,r)=>e((e=>i.call(s,t(e))),null,r)),i)}function s(e,t,i){return r(((i,s=null,r)=>e((e=>t(e)&&i.call(s,e)),null,r)),i)}function r(e,t){let i;const s=new m({onWillAddFirstListener(){i=e(s.fire,s)},onDidRemoveLastListener(){i?.dispose()}});return t?.add(s),s.event}function o(e,t,i=100,s=!1,r=!1,n,o){let a,l,h,c,d=0;const u=new m({leakWarningThreshold:n,onWillAddFirstListener(){a=e((e=>{d++,l=t(l,e),s&&!h&&(u.fire(l),l=void 0),c=()=>{const e=l;l=void 0,h=void 0,(!s||d>1)&&u.fire(e),d=0},"number"==typeof i?(clearTimeout(h),h=setTimeout(c,i)):void 0===h&&(h=0,queueMicrotask(c))}))},onWillRemoveListener(){r&&d>0&&c?.()},onDidRemoveLastListener(){c=void 0,a.dispose()}});return o?.add(u),u.event}e.None=()=>n.Disposable.None,e.defer=function(e,t){return o(e,(()=>{}),0,void 0,!0,void 0,t)},e.once=t,e.map=i,e.forEach=function(e,t,i){return r(((i,s=null,r)=>e((e=>{t(e),i.call(s,e)}),null,r)),i)},e.filter=s,e.signal=function(e){return e},e.any=function(...e){return(t,i=null,s)=>{return r=(0,n.combinedDisposable)(...e.map((e=>e((e=>t.call(i,e)))))),(o=s)instanceof Array?o.push(r):o&&o.add(r),r;var r,o}},e.reduce=function(e,t,s,r){let n=s;return i(e,(e=>(n=t(n,e),n)),r)},e.debounce=o,e.accumulate=function(t,i=0,s){return e.debounce(t,((e,t)=>e?(e.push(t),e):[t]),i,void 0,!0,void 0,s)},e.latch=function(e,t=(e,t)=>e===t,i){let r,n=!0;return s(e,(e=>{const i=n||!t(e,r);return n=!1,r=e,i}),i)},e.split=function(t,i,s){return[e.filter(t,i,s),e.filter(t,(e=>!i(e)),s)]},e.buffer=function(e,t=!1,i=[],s){let r=i.slice(),n=e((e=>{r?r.push(e):a.fire(e)}));s&&s.add(n);const o=()=>{r?.forEach((e=>a.fire(e))),r=null},a=new m({onWillAddFirstListener(){n||(n=e((e=>a.fire(e))),s&&s.add(n))},onDidAddFirstListener(){r&&(t?setTimeout(o):o())},onDidRemoveLastListener(){n&&n.dispose(),n=null}});return s&&s.add(a),a.event},e.chain=function(e,t){return(i,s,r)=>{const n=t(new l);return e((function(e){const t=n.evaluate(e);t!==a&&i.call(s,t)}),void 0,r)}};const a=Symbol("HaltChainable");class l{constructor(){this.steps=[]}map(e){return this.steps.push(e),this}forEach(e){return this.steps.push((t=>(e(t),t))),this}filter(e){return this.steps.push((t=>e(t)?t:a)),this}reduce(e,t){let i=t;return this.steps.push((t=>(i=e(i,t),i))),this}latch(e=(e,t)=>e===t){let t,i=!0;return this.steps.push((s=>{const r=i||!e(s,t);return i=!1,t=s,r?s:a})),this}evaluate(e){for(const t of this.steps)if((e=t(e))===a)break;return e}}e.fromNodeEventEmitter=function(e,t,i=e=>e){const s=(...e)=>r.fire(i(...e)),r=new m({onWillAddFirstListener:()=>e.on(t,s),onDidRemoveLastListener:()=>e.removeListener(t,s)});return r.event},e.fromDOMEventEmitter=function(e,t,i=e=>e){const s=(...e)=>r.fire(i(...e)),r=new m({onWillAddFirstListener:()=>e.addEventListener(t,s),onDidRemoveLastListener:()=>e.removeEventListener(t,s)});return r.event},e.toPromise=function(e){return new Promise((i=>t(e)(i)))},e.fromPromise=function(e){const t=new m;return e.then((e=>{t.fire(e)}),(()=>{t.fire(void 0)})).finally((()=>{t.dispose()})),t.event},e.forward=function(e,t){return e((e=>t.fire(e)))},e.runAndSubscribe=function(e,t,i){return t(i),e((e=>t(e)))};class h{constructor(e,t){this._observable=e,this._counter=0,this._hasChanged=!1;const i={onWillAddFirstListener:()=>{e.addObserver(this)},onDidRemoveLastListener:()=>{e.removeObserver(this)}};this.emitter=new m(i),t&&t.add(this.emitter)}beginUpdate(e){this._counter++}handlePossibleChange(e){}handleChange(e,t){this._hasChanged=!0}endUpdate(e){this._counter--,0===this._counter&&(this._observable.reportChanges(),this._hasChanged&&(this._hasChanged=!1,this.emitter.fire(this._observable.get())))}}e.fromObservable=function(e,t){return new h(e,t).emitter.event},e.fromObservableLight=function(e){return(t,i,s)=>{let r=0,o=!1;const a={beginUpdate(){r++},endUpdate(){r--,0===r&&(e.reportChanges(),o&&(o=!1,t.call(i)))},handlePossibleChange(){},handleChange(){o=!0}};e.addObserver(a),e.reportChanges();const l={dispose(){e.removeObserver(a)}};return s instanceof n.DisposableStore?s.add(l):Array.isArray(s)&&s.push(l),l}}}(l||(t.Event=l={}));class h{static{this.all=new Set}static{this._idPool=0}constructor(e){this.listenerCount=0,this.invocationCount=0,this.elapsedOverall=0,this.durations=[],this.name=`${e}_${h._idPool++}`,h.all.add(this)}start(e){this._stopWatch=new a.StopWatch,this.listenerCount=e}stop(){if(this._stopWatch){const e=this._stopWatch.elapsed();this.durations.push(e),this.elapsedOverall+=e,this.invocationCount+=1,this._stopWatch=void 0}}}t.EventProfiling=h;let c=-1;class d{static{this._idPool=1}constructor(e,t,i=(d._idPool++).toString(16).padStart(3,"0")){this._errorHandler=e,this.threshold=t,this.name=i,this._warnCountdown=0}dispose(){this._stacks?.clear()}check(e,t){const i=this.threshold;if(i<=0||t<i)return;this._stacks||(this._stacks=new Map);const s=this._stacks.get(e.value)||0;if(this._stacks.set(e.value,s+1),this._warnCountdown-=1,this._warnCountdown<=0){this._warnCountdown=.5*i;const[e,s]=this.getMostFrequentStack(),r=`[${this.name}] potential listener LEAK detected, having ${t} listeners already. MOST frequent listener (${s}):`;console.warn(r),console.warn(e);const n=new _(r,e);this._errorHandler(n)}return()=>{const t=this._stacks.get(e.value)||0;this._stacks.set(e.value,t-1)}}getMostFrequentStack(){if(!this._stacks)return;let e,t=0;for(const[i,s]of this._stacks)(!e||t<s)&&(e=[i,s],t=s);return e}}class u{static create(){const e=new Error;return new u(e.stack??"")}constructor(e){this.value=e}print(){console.warn(this.value.split("\\n").slice(2).join("\\n"))}}class _ extends Error{constructor(e,t){super(e),this.name="ListenerLeakError",this.stack=t}}t.ListenerLeakError=_;class f extends Error{constructor(e,t){super(e),this.name="ListenerRefusalError",this.stack=t}}t.ListenerRefusalError=f;let p=0;class g{constructor(e){this.value=e,this.id=p++}}class m{constructor(e){this._size=0,this._options=e,this._leakageMon=c>0||this._options?.leakWarningThreshold?new d(e?.onListenerError??s.onUnexpectedError,this._options?.leakWarningThreshold??c):void 0,this._perfMon=this._options?._profName?new h(this._options._profName):void 0,this._deliveryQueue=this._options?.deliveryQueue}dispose(){this._disposed||(this._disposed=!0,this._deliveryQueue?.current===this&&this._deliveryQueue.reset(),this._listeners&&(this._listeners=void 0,this._size=0),this._options?.onDidRemoveLastListener?.(),this._leakageMon?.dispose())}get event(){return this._event??=(e,t,i)=>{if(this._leakageMon&&this._size>this._leakageMon.threshold**2){const e=`[${this._leakageMon.name}] REFUSES to accept new listeners because it exceeded its threshold by far (${this._size} vs ${this._leakageMon.threshold})`;console.warn(e);const t=this._leakageMon.getMostFrequentStack()??["UNKNOWN stack",-1],i=new f(`${e}. HINT: Stack shows most frequent listener (${t[1]}-times)`,t[0]);return(this._options?.onListenerError||s.onUnexpectedError)(i),n.Disposable.None}if(this._disposed)return n.Disposable.None;t&&(e=e.bind(t));const r=new g(e);let o;this._leakageMon&&this._size>=Math.ceil(.2*this._leakageMon.threshold)&&(r.stack=u.create(),o=this._leakageMon.check(r.stack,this._size+1)),this._listeners?this._listeners instanceof g?(this._deliveryQueue??=new v,this._listeners=[this._listeners,r]):this._listeners.push(r):(this._options?.onWillAddFirstListener?.(this),this._listeners=r,this._options?.onDidAddFirstListener?.(this)),this._size++;const a=(0,n.toDisposable)((()=>{o?.(),this._removeListener(r)}));return i instanceof n.DisposableStore?i.add(a):Array.isArray(i)&&i.push(a),a},this._event}_removeListener(e){if(this._options?.onWillRemoveListener?.(this),!this._listeners)return;if(1===this._size)return this._listeners=void 0,this._options?.onDidRemoveLastListener?.(this),void(this._size=0);const t=this._listeners,i=t.indexOf(e);if(-1===i)throw console.log("disposed?",this._disposed),console.log("size?",this._size),console.log("arr?",JSON.stringify(this._listeners)),new Error("Attempted to dispose unknown listener");this._size--,t[i]=void 0;const s=this._deliveryQueue.current===this;if(2*this._size<=t.length){let e=0;for(let i=0;i<t.length;i++)t[i]?t[e++]=t[i]:s&&(this._deliveryQueue.end--,e<this._deliveryQueue.i&&this._deliveryQueue.i--);t.length=e}}_deliver(e,t){if(!e)return;const i=this._options?.onListenerError||s.onUnexpectedError;if(i)try{e.value(t)}catch(e){i(e)}else e.value(t)}_deliverQueue(e){const t=e.current._listeners;for(;e.i<e.end;)this._deliver(t[e.i++],e.value);e.reset()}fire(e){if(this._deliveryQueue?.current&&(this._deliverQueue(this._deliveryQueue),this._perfMon?.stop()),this._perfMon?.start(this._size),this._listeners)if(this._listeners instanceof g)this._deliver(this._listeners,e);else{const t=this._deliveryQueue;t.enqueue(this,e,this._listeners.length),this._deliverQueue(t)}this._perfMon?.stop()}hasListeners(){return this._size>0}}t.Emitter=m,t.createEventDeliveryQueue=()=>new v;class v{constructor(){this.i=-1,this.end=0}enqueue(e,t,i){this.i=0,this.end=i,this.current=e,this.value=t}reset(){this.i=this.end,this.current=void 0,this.value=void 0}}t.AsyncEmitter=class extends m{async fireAsync(e,t,i){if(this._listeners)for(this._asyncDeliveryQueue||(this._asyncDeliveryQueue=new o.LinkedList),((e,t)=>{if(e instanceof g)t(e);else for(let i=0;i<e.length;i++){const s=e[i];s&&t(s)}})(this._listeners,(t=>this._asyncDeliveryQueue.push([t.value,e])));this._asyncDeliveryQueue.size>0&&!t.isCancellationRequested;){const[e,r]=this._asyncDeliveryQueue.shift(),n=[],o={...r,token:t,waitUntil:t=>{if(Object.isFrozen(n))throw new Error("waitUntil can NOT be called asynchronous");i&&(t=i(t,e)),n.push(t)}};try{e(o)}catch(e){(0,s.onUnexpectedError)(e);continue}Object.freeze(n),await Promise.allSettled(n).then((e=>{for(const t of e)"rejected"===t.status&&(0,s.onUnexpectedError)(t.reason)}))}}};class S extends m{get isPaused(){return 0!==this._isPaused}constructor(e){super(e),this._isPaused=0,this._eventQueue=new o.LinkedList,this._mergeFn=e?.merge}pause(){this._isPaused++}resume(){if(0!==this._isPaused&&0==--this._isPaused)if(this._mergeFn){if(this._eventQueue.size>0){const e=Array.from(this._eventQueue);this._eventQueue.clear(),super.fire(this._mergeFn(e))}}else for(;!this._isPaused&&0!==this._eventQueue.size;)super.fire(this._eventQueue.shift())}fire(e){this._size&&(0!==this._isPaused?this._eventQueue.push(e):super.fire(e))}}t.PauseableEmitter=S,t.DebounceEmitter=class extends S{constructor(e){super(e),this._delay=e.delay??100}fire(e){this._handle||(this.pause(),this._handle=setTimeout((()=>{this._handle=void 0,this.resume()}),this._delay)),super.fire(e)}},t.MicrotaskEmitter=class extends m{constructor(e){super(e),this._queuedEvents=[],this._mergeFn=e?.merge}fire(e){this.hasListeners()&&(this._queuedEvents.push(e),1===this._queuedEvents.length&&queueMicrotask((()=>{this._mergeFn?super.fire(this._mergeFn(this._queuedEvents)):this._queuedEvents.forEach((e=>super.fire(e))),this._queuedEvents=[]})))}};class b{constructor(){this.hasListeners=!1,this.events=[],this.emitter=new m({onWillAddFirstListener:()=>this.onFirstListenerAdd(),onDidRemoveLastListener:()=>this.onLastListenerRemove()})}get event(){return this.emitter.event}add(e){const t={event:e,listener:null};return this.events.push(t),this.hasListeners&&this.hook(t),(0,n.toDisposable)((0,r.createSingleCallFunction)((()=>{this.hasListeners&&this.unhook(t);const e=this.events.indexOf(t);this.events.splice(e,1)})))}onFirstListenerAdd(){this.hasListeners=!0,this.events.forEach((e=>this.hook(e)))}onLastListenerRemove(){this.hasListeners=!1,this.events.forEach((e=>this.unhook(e)))}hook(e){e.listener=e.event((e=>this.emitter.fire(e)))}unhook(e){e.listener?.dispose(),e.listener=null}dispose(){this.emitter.dispose();for(const e of this.events)e.listener?.dispose();this.events=[]}}t.EventMultiplexer=b,t.DynamicListEventMultiplexer=class{constructor(e,t,i,s){this._store=new n.DisposableStore;const r=this._store.add(new b),o=this._store.add(new n.DisposableMap);function a(e){o.set(e,r.add(s(e)))}for(const t of e)a(t);this._store.add(t((e=>{a(e)}))),this._store.add(i((e=>{o.deleteAndDispose(e)}))),this.event=r.event}dispose(){this._store.dispose()}},t.EventBufferer=class{constructor(){this.data=[]}wrapEvent(e,t,i){return(s,r,n)=>e((e=>{const n=this.data[this.data.length-1];if(!t)return void(n?n.buffers.push((()=>s.call(r,e))):s.call(r,e));const o=n;o?(o.items??=[],o.items.push(e),0===o.buffers.length&&n.buffers.push((()=>{o.reducedResult??=i?o.items.reduce(t,i):o.items.reduce(t),s.call(r,o.reducedResult)}))):s.call(r,t(i,e))}),void 0,n)}bufferEvents(e){const t={buffers:new Array};this.data.push(t);const i=e();return this.data.pop(),t.buffers.forEach((e=>e())),i}},t.Relay=class{constructor(){this.listening=!1,this.inputEvent=l.None,this.inputEventListener=n.Disposable.None,this.emitter=new m({onDidAddFirstListener:()=>{this.listening=!0,this.inputEventListener=this.inputEvent(this.emitter.fire,this.emitter)},onDidRemoveLastListener:()=>{this.listening=!1,this.inputEventListener.dispose()}}),this.event=this.emitter.event}set input(e){this.inputEvent=e,this.listening&&(this.inputEventListener.dispose(),this.inputEventListener=e(this.emitter.fire,this.emitter))}dispose(){this.inputEventListener.dispose(),this.emitter.dispose()}},t.ValueWithChangeEvent=class{static const(e){return new C(e)}constructor(e){this._value=e,this._onDidChange=new m,this.onDidChange=this._onDidChange.event}get value(){return this._value}set value(e){e!==this._value&&(this._value=e,this._onDidChange.fire(void 0))}};class C{constructor(e){this.value=e,this.onDidChange=l.None}}},8841:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.createSingleCallFunction=function(e,t){const i=this;let s,r=!1;return function(){if(r)return s;if(r=!0,t)try{s=e.apply(i,arguments)}finally{t()}else s=e.apply(i,arguments);return s}}},6304:function(e,t,i){var s=this&&this.__createBinding||(Object.create?function(e,t,i,s){void 0===s&&(s=i);var r=Object.getOwnPropertyDescriptor(t,i);r&&!("get"in r?!t.__esModule:r.writable||r.configurable)||(r={enumerable:!0,get:function(){return t[i]}}),Object.defineProperty(e,s,r)}:function(e,t,i,s){void 0===s&&(s=i),e[s]=t[i]}),r=this&&this.__setModuleDefault||(Object.create?function(e,t){Object.defineProperty(e,"default",{enumerable:!0,value:t})}:function(e,t){e.default=t}),n=this&&this.__importStar||function(e){if(e&&e.__esModule)return e;var t={};if(null!=e)for(var i in e)"default"!==i&&Object.prototype.hasOwnProperty.call(e,i)&&s(t,e,i);return r(t,e),t};Object.defineProperty(t,"__esModule",{value:!0}),t.StringSHA1=t.Hasher=void 0,t.hash=function(e){return a(e,0)},t.doHash=a,t.numberHash=l,t.stringHash=h,t.toHexString=_;const o=n(i(1316));function a(e,t){switch(typeof e){case"object":return null===e?l(349,t):Array.isArray(e)?(i=e,s=l(104579,s=t),i.reduce(((e,t)=>a(t,e)),s)):function(e,t){return t=l(181387,t),Object.keys(e).sort().reduce(((t,i)=>(t=h(i,t),a(e[i],t))),t)}(e,t);case"string":return h(e,t);case"boolean":return function(e,t){return l(e?433:863,t)}(e,t);case"number":return l(e,t);case"undefined":return l(937,t);default:return l(617,t)}var i,s}function l(e,t){return(t<<5)-t+e|0}function h(e,t){t=l(149417,t);for(let i=0,s=e.length;i<s;i++)t=l(e.charCodeAt(i),t);return t}var c;function d(e,t,i=32){const s=i-t;return(e<<t|(~((1<<s)-1)&e)>>>s)>>>0}function u(e,t=0,i=e.byteLength,s=0){for(let r=0;r<i;r++)e[t+r]=s}function _(e,t=32){return e instanceof ArrayBuffer?Array.from(new Uint8Array(e)).map((e=>e.toString(16).padStart(2,"0"))).join(""):function(e,t,i="0"){for(;e.length<t;)e=i+e;return e}((e>>>0).toString(16),t/4)}t.Hasher=class{constructor(){this._value=0}get value(){return this._value}hash(e){return this._value=a(e,this._value),this._value}},function(e){e[e.BLOCK_SIZE=64]="BLOCK_SIZE",e[e.UNICODE_REPLACEMENT=65533]="UNICODE_REPLACEMENT"}(c||(c={}));class f{static{this._bigBlock32=new DataView(new ArrayBuffer(320))}constructor(){this._h0=1732584193,this._h1=4023233417,this._h2=2562383102,this._h3=271733878,this._h4=3285377520,this._buff=new Uint8Array(c.BLOCK_SIZE+3),this._buffDV=new DataView(this._buff.buffer),this._buffLen=0,this._totalLen=0,this._leftoverHighSurrogate=0,this._finished=!1}update(e){const t=e.length;if(0===t)return;const i=this._buff;let s,r,n=this._buffLen,a=this._leftoverHighSurrogate;for(0!==a?(s=a,r=-1,a=0):(s=e.charCodeAt(0),r=0);;){let l=s;if(o.isHighSurrogate(s)){if(!(r+1<t)){a=s;break}{const t=e.charCodeAt(r+1);o.isLowSurrogate(t)?(r++,l=o.computeCodePoint(s,t)):l=c.UNICODE_REPLACEMENT}}else o.isLowSurrogate(s)&&(l=c.UNICODE_REPLACEMENT);if(n=this._push(i,n,l),r++,!(r<t))break;s=e.charCodeAt(r)}this._buffLen=n,this._leftoverHighSurrogate=a}_push(e,t,i){return i<128?e[t++]=i:i<2048?(e[t++]=192|(1984&i)>>>6,e[t++]=128|(63&i)>>>0):i<65536?(e[t++]=224|(61440&i)>>>12,e[t++]=128|(4032&i)>>>6,e[t++]=128|(63&i)>>>0):(e[t++]=240|(1835008&i)>>>18,e[t++]=128|(258048&i)>>>12,e[t++]=128|(4032&i)>>>6,e[t++]=128|(63&i)>>>0),t>=c.BLOCK_SIZE&&(this._step(),t-=c.BLOCK_SIZE,this._totalLen+=c.BLOCK_SIZE,e[0]=e[c.BLOCK_SIZE+0],e[1]=e[c.BLOCK_SIZE+1],e[2]=e[c.BLOCK_SIZE+2]),t}digest(){return this._finished||(this._finished=!0,this._leftoverHighSurrogate&&(this._leftoverHighSurrogate=0,this._buffLen=this._push(this._buff,this._buffLen,c.UNICODE_REPLACEMENT)),this._totalLen+=this._buffLen,this._wrapUp()),_(this._h0)+_(this._h1)+_(this._h2)+_(this._h3)+_(this._h4)}_wrapUp(){this._buff[this._buffLen++]=128,u(this._buff,this._buffLen),this._buffLen>56&&(this._step(),u(this._buff));const e=8*this._totalLen;this._buffDV.setUint32(56,Math.floor(e/4294967296),!1),this._buffDV.setUint32(60,e%4294967296,!1),this._step()}_step(){const e=f._bigBlock32,t=this._buffDV;for(let i=0;i<64;i+=4)e.setUint32(i,t.getUint32(i,!1),!1);for(let t=64;t<320;t+=4)e.setUint32(t,d(e.getUint32(t-12,!1)^e.getUint32(t-32,!1)^e.getUint32(t-56,!1)^e.getUint32(t-64,!1),1),!1);let i,s,r,n=this._h0,o=this._h1,a=this._h2,l=this._h3,h=this._h4;for(let t=0;t<80;t++)t<20?(i=o&a|~o&l,s=1518500249):t<40?(i=o^a^l,s=1859775393):t<60?(i=o&a|o&l|a&l,s=2400959708):(i=o^a^l,s=3395469782),r=d(n,5)+i+h+s+e.getUint32(4*t,!1)&4294967295,h=l,l=a,a=d(o,30),o=n,n=r;this._h0=this._h0+n&4294967295,this._h1=this._h1+o&4294967295,this._h2=this._h2+a&4294967295,this._h3=this._h3+l&4294967295,this._h4=this._h4+h&4294967295}}t.StringSHA1=f},4218:(e,t)=>{var i;Object.defineProperty(t,"__esModule",{value:!0}),t.Iterable=void 0,function(e){function t(e){return e&&"object"==typeof e&&"function"==typeof e[Symbol.iterator]}e.is=t;const i=Object.freeze([]);function*s(e){yield e}e.empty=function(){return i},e.single=s,e.wrap=function(e){return t(e)?e:s(e)},e.from=function(e){return e||i},e.reverse=function*(e){for(let t=e.length-1;t>=0;t--)yield e[t]},e.isEmpty=function(e){return!e||!0===e[Symbol.iterator]().next().done},e.first=function(e){return e[Symbol.iterator]().next().value},e.some=function(e,t){let i=0;for(const s of e)if(t(s,i++))return!0;return!1},e.find=function(e,t){for(const i of e)if(t(i))return i},e.filter=function*(e,t){for(const i of e)t(i)&&(yield i)},e.map=function*(e,t){let i=0;for(const s of e)yield t(s,i++)},e.flatMap=function*(e,t){let i=0;for(const s of e)yield*t(s,i++)},e.concat=function*(...e){for(const t of e)yield*t},e.reduce=function(e,t,i){let s=i;for(const i of e)s=t(s,i);return s},e.slice=function*(e,t,i=e.length){for(t<0&&(t+=e.length),i<0?i+=e.length:i>e.length&&(i=e.length);t<i;t++)yield e[t]},e.consume=function(t,i=Number.POSITIVE_INFINITY){const s=[];if(0===i)return[s,t];const r=t[Symbol.iterator]();for(let t=0;t<i;t++){const t=r.next();if(t.done)return[s,e.empty()];s.push(t.value)}return[s,{[Symbol.iterator]:()=>r}]},e.asyncToArray=async function(e){const t=[];for await(const i of e)t.push(i);return Promise.resolve(t)}}(i||(t.Iterable=i={}))},7883:(e,t)=>{var i,s;Object.defineProperty(t,"__esModule",{value:!0}),t.KeyMod=t.KeyCodeUtils=t.ScanCodeUtils=t.NATIVE_WINDOWS_KEY_CODE_TO_KEY_CODE=t.EVENT_KEY_CODE_MAP=t.ScanCode=t.KeyCode=void 0,t.KeyChord=function(e,t){return(e|(65535&t)<<16>>>0)>>>0},function(e){e[e.DependsOnKbLayout=-1]="DependsOnKbLayout",e[e.Unknown=0]="Unknown",e[e.Backspace=1]="Backspace",e[e.Tab=2]="Tab",e[e.Enter=3]="Enter",e[e.Shift=4]="Shift",e[e.Ctrl=5]="Ctrl",e[e.Alt=6]="Alt",e[e.PauseBreak=7]="PauseBreak",e[e.CapsLock=8]="CapsLock",e[e.Escape=9]="Escape",e[e.Space=10]="Space",e[e.PageUp=11]="PageUp",e[e.PageDown=12]="PageDown",e[e.End=13]="End",e[e.Home=14]="Home",e[e.LeftArrow=15]="LeftArrow",e[e.UpArrow=16]="UpArrow",e[e.RightArrow=17]="RightArrow",e[e.DownArrow=18]="DownArrow",e[e.Insert=19]="Insert",e[e.Delete=20]="Delete",e[e.Digit0=21]="Digit0",e[e.Digit1=22]="Digit1",e[e.Digit2=23]="Digit2",e[e.Digit3=24]="Digit3",e[e.Digit4=25]="Digit4",e[e.Digit5=26]="Digit5",e[e.Digit6=27]="Digit6",e[e.Digit7=28]="Digit7",e[e.Digit8=29]="Digit8",e[e.Digit9=30]="Digit9",e[e.KeyA=31]="KeyA",e[e.KeyB=32]="KeyB",e[e.KeyC=33]="KeyC",e[e.KeyD=34]="KeyD",e[e.KeyE=35]="KeyE",e[e.KeyF=36]="KeyF",e[e.KeyG=37]="KeyG",e[e.KeyH=38]="KeyH",e[e.KeyI=39]="KeyI",e[e.KeyJ=40]="KeyJ",e[e.KeyK=41]="KeyK",e[e.KeyL=42]="KeyL",e[e.KeyM=43]="KeyM",e[e.KeyN=44]="KeyN",e[e.KeyO=45]="KeyO",e[e.KeyP=46]="KeyP",e[e.KeyQ=47]="KeyQ",e[e.KeyR=48]="KeyR",e[e.KeyS=49]="KeyS",e[e.KeyT=50]="KeyT",e[e.KeyU=51]="KeyU",e[e.KeyV=52]="KeyV",e[e.KeyW=53]="KeyW",e[e.KeyX=54]="KeyX",e[e.KeyY=55]="KeyY",e[e.KeyZ=56]="KeyZ",e[e.Meta=57]="Meta",e[e.ContextMenu=58]="ContextMenu",e[e.F1=59]="F1",e[e.F2=60]="F2",e[e.F3=61]="F3",e[e.F4=62]="F4",e[e.F5=63]="F5",e[e.F6=64]="F6",e[e.F7=65]="F7",e[e.F8=66]="F8",e[e.F9=67]="F9",e[e.F10=68]="F10",e[e.F11=69]="F11",e[e.F12=70]="F12",e[e.F13=71]="F13",e[e.F14=72]="F14",e[e.F15=73]="F15",e[e.F16=74]="F16",e[e.F17=75]="F17",e[e.F18=76]="F18",e[e.F19=77]="F19",e[e.F20=78]="F20",e[e.F21=79]="F21",e[e.F22=80]="F22",e[e.F23=81]="F23",e[e.F24=82]="F24",e[e.NumLock=83]="NumLock",e[e.ScrollLock=84]="ScrollLock",e[e.Semicolon=85]="Semicolon",e[e.Equal=86]="Equal",e[e.Comma=87]="Comma",e[e.Minus=88]="Minus",e[e.Period=89]="Period",e[e.Slash=90]="Slash",e[e.Backquote=91]="Backquote",e[e.BracketLeft=92]="BracketLeft",e[e.Backslash=93]="Backslash",e[e.BracketRight=94]="BracketRight",e[e.Quote=95]="Quote",e[e.OEM_8=96]="OEM_8",e[e.IntlBackslash=97]="IntlBackslash",e[e.Numpad0=98]="Numpad0",e[e.Numpad1=99]="Numpad1",e[e.Numpad2=100]="Numpad2",e[e.Numpad3=101]="Numpad3",e[e.Numpad4=102]="Numpad4",e[e.Numpad5=103]="Numpad5",e[e.Numpad6=104]="Numpad6",e[e.Numpad7=105]="Numpad7",e[e.Numpad8=106]="Numpad8",e[e.Numpad9=107]="Numpad9",e[e.NumpadMultiply=108]="NumpadMultiply",e[e.NumpadAdd=109]="NumpadAdd",e[e.NUMPAD_SEPARATOR=110]="NUMPAD_SEPARATOR",e[e.NumpadSubtract=111]="NumpadSubtract",e[e.NumpadDecimal=112]="NumpadDecimal",e[e.NumpadDivide=113]="NumpadDivide",e[e.KEY_IN_COMPOSITION=114]="KEY_IN_COMPOSITION",e[e.ABNT_C1=115]="ABNT_C1",e[e.ABNT_C2=116]="ABNT_C2",e[e.AudioVolumeMute=117]="AudioVolumeMute",e[e.AudioVolumeUp=118]="AudioVolumeUp",e[e.AudioVolumeDown=119]="AudioVolumeDown",e[e.BrowserSearch=120]="BrowserSearch",e[e.BrowserHome=121]="BrowserHome",e[e.BrowserBack=122]="BrowserBack",e[e.BrowserForward=123]="BrowserForward",e[e.MediaTrackNext=124]="MediaTrackNext",e[e.MediaTrackPrevious=125]="MediaTrackPrevious",e[e.MediaStop=126]="MediaStop",e[e.MediaPlayPause=127]="MediaPlayPause",e[e.LaunchMediaPlayer=128]="LaunchMediaPlayer",e[e.LaunchMail=129]="LaunchMail",e[e.LaunchApp2=130]="LaunchApp2",e[e.Clear=131]="Clear",e[e.MAX_VALUE=132]="MAX_VALUE"}(i||(t.KeyCode=i={})),function(e){e[e.DependsOnKbLayout=-1]="DependsOnKbLayout",e[e.None=0]="None",e[e.Hyper=1]="Hyper",e[e.Super=2]="Super",e[e.Fn=3]="Fn",e[e.FnLock=4]="FnLock",e[e.Suspend=5]="Suspend",e[e.Resume=6]="Resume",e[e.Turbo=7]="Turbo",e[e.Sleep=8]="Sleep",e[e.WakeUp=9]="WakeUp",e[e.KeyA=10]="KeyA",e[e.KeyB=11]="KeyB",e[e.KeyC=12]="KeyC",e[e.KeyD=13]="KeyD",e[e.KeyE=14]="KeyE",e[e.KeyF=15]="KeyF",e[e.KeyG=16]="KeyG",e[e.KeyH=17]="KeyH",e[e.KeyI=18]="KeyI",e[e.KeyJ=19]="KeyJ",e[e.KeyK=20]="KeyK",e[e.KeyL=21]="KeyL",e[e.KeyM=22]="KeyM",e[e.KeyN=23]="KeyN",e[e.KeyO=24]="KeyO",e[e.KeyP=25]="KeyP",e[e.KeyQ=26]="KeyQ",e[e.KeyR=27]="KeyR",e[e.KeyS=28]="KeyS",e[e.KeyT=29]="KeyT",e[e.KeyU=30]="KeyU",e[e.KeyV=31]="KeyV",e[e.KeyW=32]="KeyW",e[e.KeyX=33]="KeyX",e[e.KeyY=34]="KeyY",e[e.KeyZ=35]="KeyZ",e[e.Digit1=36]="Digit1",e[e.Digit2=37]="Digit2",e[e.Digit3=38]="Digit3",e[e.Digit4=39]="Digit4",e[e.Digit5=40]="Digit5",e[e.Digit6=41]="Digit6",e[e.Digit7=42]="Digit7",e[e.Digit8=43]="Digit8",e[e.Digit9=44]="Digit9",e[e.Digit0=45]="Digit0",e[e.Enter=46]="Enter",e[e.Escape=47]="Escape",e[e.Backspace=48]="Backspace",e[e.Tab=49]="Tab",e[e.Space=50]="Space",e[e.Minus=51]="Minus",e[e.Equal=52]="Equal",e[e.BracketLeft=53]="BracketLeft",e[e.BracketRight=54]="BracketRight",e[e.Backslash=55]="Backslash",e[e.IntlHash=56]="IntlHash",e[e.Semicolon=57]="Semicolon",e[e.Quote=58]="Quote",e[e.Backquote=59]="Backquote",e[e.Comma=60]="Comma",e[e.Period=61]="Period",e[e.Slash=62]="Slash",e[e.CapsLock=63]="CapsLock",e[e.F1=64]="F1",e[e.F2=65]="F2",e[e.F3=66]="F3",e[e.F4=67]="F4",e[e.F5=68]="F5",e[e.F6=69]="F6",e[e.F7=70]="F7",e[e.F8=71]="F8",e[e.F9=72]="F9",e[e.F10=73]="F10",e[e.F11=74]="F11",e[e.F12=75]="F12",e[e.PrintScreen=76]="PrintScreen",e[e.ScrollLock=77]="ScrollLock",e[e.Pause=78]="Pause",e[e.Insert=79]="Insert",e[e.Home=80]="Home",e[e.PageUp=81]="PageUp",e[e.Delete=82]="Delete",e[e.End=83]="End",e[e.PageDown=84]="PageDown",e[e.ArrowRight=85]="ArrowRight",e[e.ArrowLeft=86]="ArrowLeft",e[e.ArrowDown=87]="ArrowDown",e[e.ArrowUp=88]="ArrowUp",e[e.NumLock=89]="NumLock",e[e.NumpadDivide=90]="NumpadDivide",e[e.NumpadMultiply=91]="NumpadMultiply",e[e.NumpadSubtract=92]="NumpadSubtract",e[e.NumpadAdd=93]="NumpadAdd",e[e.NumpadEnter=94]="NumpadEnter",e[e.Numpad1=95]="Numpad1",e[e.Numpad2=96]="Numpad2",e[e.Numpad3=97]="Numpad3",e[e.Numpad4=98]="Numpad4",e[e.Numpad5=99]="Numpad5",e[e.Numpad6=100]="Numpad6",e[e.Numpad7=101]="Numpad7",e[e.Numpad8=102]="Numpad8",e[e.Numpad9=103]="Numpad9",e[e.Numpad0=104]="Numpad0",e[e.NumpadDecimal=105]="NumpadDecimal",e[e.IntlBackslash=106]="IntlBackslash",e[e.ContextMenu=107]="ContextMenu",e[e.Power=108]="Power",e[e.NumpadEqual=109]="NumpadEqual",e[e.F13=110]="F13",e[e.F14=111]="F14",e[e.F15=112]="F15",e[e.F16=113]="F16",e[e.F17=114]="F17",e[e.F18=115]="F18",e[e.F19=116]="F19",e[e.F20=117]="F20",e[e.F21=118]="F21",e[e.F22=119]="F22",e[e.F23=120]="F23",e[e.F24=121]="F24",e[e.Open=122]="Open",e[e.Help=123]="Help",e[e.Select=124]="Select",e[e.Again=125]="Again",e[e.Undo=126]="Undo",e[e.Cut=127]="Cut",e[e.Copy=128]="Copy",e[e.Paste=129]="Paste",e[e.Find=130]="Find",e[e.AudioVolumeMute=131]="AudioVolumeMute",e[e.AudioVolumeUp=132]="AudioVolumeUp",e[e.AudioVolumeDown=133]="AudioVolumeDown",e[e.NumpadComma=134]="NumpadComma",e[e.IntlRo=135]="IntlRo",e[e.KanaMode=136]="KanaMode",e[e.IntlYen=137]="IntlYen",e[e.Convert=138]="Convert",e[e.NonConvert=139]="NonConvert",e[e.Lang1=140]="Lang1",e[e.Lang2=141]="Lang2",e[e.Lang3=142]="Lang3",e[e.Lang4=143]="Lang4",e[e.Lang5=144]="Lang5",e[e.Abort=145]="Abort",e[e.Props=146]="Props",e[e.NumpadParenLeft=147]="NumpadParenLeft",e[e.NumpadParenRight=148]="NumpadParenRight",e[e.NumpadBackspace=149]="NumpadBackspace",e[e.NumpadMemoryStore=150]="NumpadMemoryStore",e[e.NumpadMemoryRecall=151]="NumpadMemoryRecall",e[e.NumpadMemoryClear=152]="NumpadMemoryClear",e[e.NumpadMemoryAdd=153]="NumpadMemoryAdd",e[e.NumpadMemorySubtract=154]="NumpadMemorySubtract",e[e.NumpadClear=155]="NumpadClear",e[e.NumpadClearEntry=156]="NumpadClearEntry",e[e.ControlLeft=157]="ControlLeft",e[e.ShiftLeft=158]="ShiftLeft",e[e.AltLeft=159]="AltLeft",e[e.MetaLeft=160]="MetaLeft",e[e.ControlRight=161]="ControlRight",e[e.ShiftRight=162]="ShiftRight",e[e.AltRight=163]="AltRight",e[e.MetaRight=164]="MetaRight",e[e.BrightnessUp=165]="BrightnessUp",e[e.BrightnessDown=166]="BrightnessDown",e[e.MediaPlay=167]="MediaPlay",e[e.MediaRecord=168]="MediaRecord",e[e.MediaFastForward=169]="MediaFastForward",e[e.MediaRewind=170]="MediaRewind",e[e.MediaTrackNext=171]="MediaTrackNext",e[e.MediaTrackPrevious=172]="MediaTrackPrevious",e[e.MediaStop=173]="MediaStop",e[e.Eject=174]="Eject",e[e.MediaPlayPause=175]="MediaPlayPause",e[e.MediaSelect=176]="MediaSelect",e[e.LaunchMail=177]="LaunchMail",e[e.LaunchApp2=178]="LaunchApp2",e[e.LaunchApp1=179]="LaunchApp1",e[e.SelectTask=180]="SelectTask",e[e.LaunchScreenSaver=181]="LaunchScreenSaver",e[e.BrowserSearch=182]="BrowserSearch",e[e.BrowserHome=183]="BrowserHome",e[e.BrowserBack=184]="BrowserBack",e[e.BrowserForward=185]="BrowserForward",e[e.BrowserStop=186]="BrowserStop",e[e.BrowserRefresh=187]="BrowserRefresh",e[e.BrowserFavorites=188]="BrowserFavorites",e[e.ZoomToggle=189]="ZoomToggle",e[e.MailReply=190]="MailReply",e[e.MailForward=191]="MailForward",e[e.MailSend=192]="MailSend",e[e.MAX_VALUE=193]="MAX_VALUE"}(s||(t.ScanCode=s={}));class r{constructor(){this._keyCodeToStr=[],this._strToKeyCode=Object.create(null)}define(e,t){this._keyCodeToStr[e]=t,this._strToKeyCode[t.toLowerCase()]=e}keyCodeToStr(e){return this._keyCodeToStr[e]}strToKeyCode(e){return this._strToKeyCode[e.toLowerCase()]||i.Unknown}}const n=new r,o=new r,a=new r;t.EVENT_KEY_CODE_MAP=new Array(230),t.NATIVE_WINDOWS_KEY_CODE_TO_KEY_CODE={};const l=[],h=Object.create(null),c=Object.create(null);var d,u;t.ScanCodeUtils={lowerCaseToEnum:e=>c[e]||s.None,toEnum:e=>h[e]||s.None,toString:e=>l[e]||"None"},function(e){e.toString=function(e){return n.keyCodeToStr(e)},e.fromString=function(e){return n.strToKeyCode(e)},e.toUserSettingsUS=function(e){return o.keyCodeToStr(e)},e.toUserSettingsGeneral=function(e){return a.keyCodeToStr(e)},e.fromUserSettings=function(e){return o.strToKeyCode(e)||a.strToKeyCode(e)},e.toElectronAccelerator=function(e){if(e>=i.Numpad0&&e<=i.NumpadDivide)return null;switch(e){case i.UpArrow:return"Up";case i.DownArrow:return"Down";case i.LeftArrow:return"Left";case i.RightArrow:return"Right"}return n.keyCodeToStr(e)}}(d||(t.KeyCodeUtils=d={})),function(e){e[e.CtrlCmd=2048]="CtrlCmd",e[e.Shift=1024]="Shift",e[e.Alt=512]="Alt",e[e.WinCtrl=256]="WinCtrl"}(u||(t.KeyMod=u={}))},2811:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.ResolvedKeybinding=t.ResolvedChord=t.Keybinding=t.ScanCodeChord=t.KeyCodeChord=void 0,t.decodeKeybinding=function(e,t){if("number"==typeof e){if(0===e)return null;const i=(65535&e)>>>0,s=(4294901760&e)>>>16;return new c(0!==s?[a(i,t),a(s,t)]:[a(i,t)])}{const i=[];for(let s=0;s<e.length;s++)i.push(a(e[s],t));return new c(i)}},t.createSimpleKeybinding=a;const s=i(9807),r=i(7883),n=i(8163);var o;function a(e,t){const i=!!(e&o.CtrlCmd),s=!!(e&o.WinCtrl),r=t===n.OperatingSystem.Macintosh?s:i,a=!!(e&o.Shift),h=!!(e&o.Alt),c=t===n.OperatingSystem.Macintosh?i:s,d=e&o.KeyCode;return new l(r,a,h,c,d)}!function(e){e[e.CtrlCmd=2048]="CtrlCmd",e[e.Shift=1024]="Shift",e[e.Alt=512]="Alt",e[e.WinCtrl=256]="WinCtrl",e[e.KeyCode=255]="KeyCode"}(o||(o={}));class l{constructor(e,t,i,s,r){this.ctrlKey=e,this.shiftKey=t,this.altKey=i,this.metaKey=s,this.keyCode=r}equals(e){return e instanceof l&&this.ctrlKey===e.ctrlKey&&this.shiftKey===e.shiftKey&&this.altKey===e.altKey&&this.metaKey===e.metaKey&&this.keyCode===e.keyCode}getHashCode(){return`K${this.ctrlKey?"1":"0"}${this.shiftKey?"1":"0"}${this.altKey?"1":"0"}${this.metaKey?"1":"0"}${this.keyCode}`}isModifierKey(){return this.keyCode===r.KeyCode.Unknown||this.keyCode===r.KeyCode.Ctrl||this.keyCode===r.KeyCode.Meta||this.keyCode===r.KeyCode.Alt||this.keyCode===r.KeyCode.Shift}toKeybinding(){return new c([this])}isDuplicateModifierCase(){return this.ctrlKey&&this.keyCode===r.KeyCode.Ctrl||this.shiftKey&&this.keyCode===r.KeyCode.Shift||this.altKey&&this.keyCode===r.KeyCode.Alt||this.metaKey&&this.keyCode===r.KeyCode.Meta}}t.KeyCodeChord=l;class h{constructor(e,t,i,s,r){this.ctrlKey=e,this.shiftKey=t,this.altKey=i,this.metaKey=s,this.scanCode=r}equals(e){return e instanceof h&&this.ctrlKey===e.ctrlKey&&this.shiftKey===e.shiftKey&&this.altKey===e.altKey&&this.metaKey===e.metaKey&&this.scanCode===e.scanCode}getHashCode(){return`S${this.ctrlKey?"1":"0"}${this.shiftKey?"1":"0"}${this.altKey?"1":"0"}${this.metaKey?"1":"0"}${this.scanCode}`}isDuplicateModifierCase(){return this.ctrlKey&&(this.scanCode===r.ScanCode.ControlLeft||this.scanCode===r.ScanCode.ControlRight)||this.shiftKey&&(this.scanCode===r.ScanCode.ShiftLeft||this.scanCode===r.ScanCode.ShiftRight)||this.altKey&&(this.scanCode===r.ScanCode.AltLeft||this.scanCode===r.ScanCode.AltRight)||this.metaKey&&(this.scanCode===r.ScanCode.MetaLeft||this.scanCode===r.ScanCode.MetaRight)}}t.ScanCodeChord=h;class c{constructor(e){if(0===e.length)throw(0,s.illegalArgument)("chords");this.chords=e}getHashCode(){let e="";for(let t=0,i=this.chords.length;t<i;t++)0!==t&&(e+=";"),e+=this.chords[t].getHashCode();return e}equals(e){if(null===e)return!1;if(this.chords.length!==e.chords.length)return!1;for(let t=0;t<this.chords.length;t++)if(!this.chords[t].equals(e.chords[t]))return!1;return!0}}t.Keybinding=c,t.ResolvedChord=class{constructor(e,t,i,s,r,n){this.ctrlKey=e,this.shiftKey=t,this.altKey=i,this.metaKey=s,this.keyLabel=r,this.keyAriaLabel=n}},t.ResolvedKeybinding=class{}},626:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.Lazy=void 0,t.Lazy=class{constructor(e){this.executor=e,this._didRun=!1}get hasValue(){return this._didRun}get value(){if(!this._didRun)try{this._value=this.executor()}catch(e){this._error=e}finally{this._didRun=!0}if(this._error)throw this._error;return this._value}get rawValue(){return this._value}}},7150:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.DisposableMap=t.ImmortalReference=t.AsyncReferenceCollection=t.ReferenceCollection=t.SafeDisposable=t.RefCountedDisposable=t.MandatoryMutableDisposable=t.MutableDisposable=t.Disposable=t.DisposableStore=t.DisposableTracker=void 0,t.setDisposableTracker=function(e){l=e},t.trackDisposable=c,t.markAsDisposed=d,t.markAsSingleton=function(e){return l?.markAsSingleton(e),e},t.isDisposable=_,t.dispose=f,t.disposeIfDisposable=function(e){for(const t of e)_(t)&&t.dispose();return[]},t.combinedDisposable=function(...e){const t=p((()=>f(e)));return function(e,t){if(l)for(const i of e)l.setParent(i,t)}(e,t),t},t.toDisposable=p,t.disposeOnReturn=function(e){const t=new g;try{e(t)}finally{t.dispose()}};const s=i(3058),r=i(9087),n=i(2608),o=i(8841),a=i(4218);let l=null;class h{constructor(){this.livingDisposables=new Map}static{this.idx=0}getDisposableData(e){let t=this.livingDisposables.get(e);return t||(t={parent:null,source:null,isSingleton:!1,value:e,idx:h.idx++},this.livingDisposables.set(e,t)),t}trackDisposable(e){const t=this.getDisposableData(e);t.source||(t.source=(new Error).stack)}setParent(e,t){this.getDisposableData(e).parent=t}markAsDisposed(e){this.livingDisposables.delete(e)}markAsSingleton(e){this.getDisposableData(e).isSingleton=!0}getRootParent(e,t){const i=t.get(e);if(i)return i;const s=e.parent?this.getRootParent(this.getDisposableData(e.parent),t):e;return t.set(e,s),s}getTrackedDisposables(){const e=new Map;return[...this.livingDisposables.entries()].filter((([,t])=>null!==t.source&&!this.getRootParent(t,e).isSingleton)).flatMap((([e])=>e))}computeLeakingDisposables(e=10,t){let i;if(t)i=t;else{const e=new Map,t=[...this.livingDisposables.values()].filter((t=>null!==t.source&&!this.getRootParent(t,e).isSingleton));if(0===t.length)return;const s=new Set(t.map((e=>e.value)));if(i=t.filter((e=>!(e.parent&&s.has(e.parent)))),0===i.length)throw new Error("There are cyclic diposable chains!")}if(!i)return;function o(e){const t=e.source.split("\\n").map((e=>e.trim().replace("at ",""))).filter((e=>""!==e));return function(e,t){for(;e.length>0&&t.some((t=>"string"==typeof t?t===e[0]:e[0].match(t)));)e.shift()}(t,["Error",/^trackDisposable \\(.*\\)$/,/^DisposableTracker.trackDisposable \\(.*\\)$/]),t.reverse()}const a=new n.SetMap;for(const e of i){const t=o(e);for(let i=0;i<=t.length;i++)a.add(t.slice(0,i).join("\\n"),e)}i.sort((0,s.compareBy)((e=>e.idx),s.numberComparator));let l="",h=0;for(const t of i.slice(0,e)){h++;const e=o(t),s=[];for(let t=0;t<e.length;t++){let n=e[t];n=`(shared with ${a.get(e.slice(0,t+1).join("\\n")).size}/${i.length} leaks) at ${n}`;const l=a.get(e.slice(0,t).join("\\n")),h=(0,r.groupBy)([...l].map((e=>o(e)[t])),(e=>e));delete h[e[t]];for(const[e,t]of Object.entries(h))s.unshift(`    - stacktraces of ${t.length} other leaks continue with ${e}`);s.unshift(n)}l+=`\\n\\n\\n==================== Leaking disposable ${h}/${i.length}: ${t.value.constructor.name} ====================\\n${s.join("\\n")}\\n============================================================\\n\\n`}return i.length>e&&(l+=`\\n\\n\\n... and ${i.length-e} more leaking disposables\\n\\n`),{leaks:i,details:l}}}function c(e){return l?.trackDisposable(e),e}function d(e){l?.markAsDisposed(e)}function u(e,t){l?.setParent(e,t)}function _(e){return"object"==typeof e&&null!==e&&"function"==typeof e.dispose&&0===e.dispose.length}function f(e){if(a.Iterable.is(e)){const t=[];for(const i of e)if(i)try{i.dispose()}catch(e){t.push(e)}if(1===t.length)throw t[0];if(t.length>1)throw new AggregateError(t,"Encountered errors while disposing of store");return Array.isArray(e)?[]:e}if(e)return e.dispose(),e}function p(e){const t=c({dispose:(0,o.createSingleCallFunction)((()=>{d(t),e()}))});return t}t.DisposableTracker=h;class g{static{this.DISABLE_DISPOSED_WARNING=!1}constructor(){this._toDispose=new Set,this._isDisposed=!1,c(this)}dispose(){this._isDisposed||(d(this),this._isDisposed=!0,this.clear())}get isDisposed(){return this._isDisposed}clear(){if(0!==this._toDispose.size)try{f(this._toDispose)}finally{this._toDispose.clear()}}add(e){if(!e)return e;if(e===this)throw new Error("Cannot register a disposable on itself!");return u(e,this),this._isDisposed?g.DISABLE_DISPOSED_WARNING||console.warn(new Error("Trying to add a disposable to a DisposableStore that has already been disposed of. The added object will be leaked!").stack):this._toDispose.add(e),e}delete(e){if(e){if(e===this)throw new Error("Cannot dispose a disposable on itself!");this._toDispose.delete(e),e.dispose()}}deleteAndLeak(e){e&&this._toDispose.has(e)&&(this._toDispose.delete(e),u(e,null))}}t.DisposableStore=g;class m{static{this.None=Object.freeze({dispose(){}})}constructor(){this._store=new g,c(this),u(this._store,this)}dispose(){d(this),this._store.dispose()}_register(e){if(e===this)throw new Error("Cannot register a disposable on itself!");return this._store.add(e)}}t.Disposable=m;class v{constructor(){this._isDisposed=!1,c(this)}get value(){return this._isDisposed?void 0:this._value}set value(e){this._isDisposed||e===this._value||(this._value?.dispose(),e&&u(e,this),this._value=e)}clear(){this.value=void 0}dispose(){this._isDisposed=!0,d(this),this._value?.dispose(),this._value=void 0}clearAndLeak(){const e=this._value;return this._value=void 0,e&&u(e,null),e}}t.MutableDisposable=v,t.MandatoryMutableDisposable=class{constructor(e){this._disposable=new v,this._isDisposed=!1,this._disposable.value=e}get value(){return this._disposable.value}set value(e){this._isDisposed||e===this._disposable.value||(this._disposable.value=e)}dispose(){this._isDisposed=!0,this._disposable.dispose()}},t.RefCountedDisposable=class{constructor(e){this._disposable=e,this._counter=1}acquire(){return this._counter++,this}release(){return 0==--this._counter&&this._disposable.dispose(),this}},t.SafeDisposable=class{constructor(){this.dispose=()=>{},this.unset=()=>{},this.isset=()=>!1,c(this)}set(e){let t=e;return this.unset=()=>t=void 0,this.isset=()=>void 0!==t,this.dispose=()=>{t&&(t(),t=void 0,d(this))},this}},t.ReferenceCollection=class{constructor(){this.references=new Map}acquire(e,...t){let i=this.references.get(e);i||(i={counter:0,object:this.createReferencedObject(e,...t)},this.references.set(e,i));const{object:s}=i,r=(0,o.createSingleCallFunction)((()=>{0==--i.counter&&(this.destroyReferencedObject(e,i.object),this.references.delete(e))}));return i.counter++,{object:s,dispose:r}}},t.AsyncReferenceCollection=class{constructor(e){this.referenceCollection=e}async acquire(e,...t){const i=this.referenceCollection.acquire(e,...t);try{return{object:await i.object,dispose:()=>i.dispose()}}catch(e){throw i.dispose(),e}}},t.ImmortalReference=class{constructor(e){this.object=e}dispose(){}};class S{constructor(){this._store=new Map,this._isDisposed=!1,c(this)}dispose(){d(this),this._isDisposed=!0,this.clearAndDisposeAll()}clearAndDisposeAll(){if(this._store.size)try{f(this._store.values())}finally{this._store.clear()}}has(e){return this._store.has(e)}get size(){return this._store.size}get(e){return this._store.get(e)}set(e,t,i=!1){this._isDisposed&&console.warn(new Error("Trying to add a disposable to a DisposableMap that has already been disposed of. The added object will be leaked!").stack),i||this._store.get(e)?.dispose(),this._store.set(e,t)}deleteAndDispose(e){this._store.get(e)?.dispose(),this._store.delete(e)}deleteAndLeak(e){const t=this._store.get(e);return this._store.delete(e),t}keys(){return this._store.keys()}values(){return this._store.values()}[Symbol.iterator](){return this._store[Symbol.iterator]()}}t.DisposableMap=S},6317:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.LinkedList=void 0;class i{static{this.Undefined=new i(void 0)}constructor(e){this.element=e,this.next=i.Undefined,this.prev=i.Undefined}}class s{constructor(){this._first=i.Undefined,this._last=i.Undefined,this._size=0}get size(){return this._size}isEmpty(){return this._first===i.Undefined}clear(){let e=this._first;for(;e!==i.Undefined;){const t=e.next;e.prev=i.Undefined,e.next=i.Undefined,e=t}this._first=i.Undefined,this._last=i.Undefined,this._size=0}unshift(e){return this._insert(e,!1)}push(e){return this._insert(e,!0)}_insert(e,t){const s=new i(e);if(this._first===i.Undefined)this._first=s,this._last=s;else if(t){const e=this._last;this._last=s,s.prev=e,e.next=s}else{const e=this._first;this._first=s,s.next=e,e.prev=s}this._size+=1;let r=!1;return()=>{r||(r=!0,this._remove(s))}}shift(){if(this._first!==i.Undefined){const e=this._first.element;return this._remove(this._first),e}}pop(){if(this._last!==i.Undefined){const e=this._last.element;return this._remove(this._last),e}}_remove(e){if(e.prev!==i.Undefined&&e.next!==i.Undefined){const t=e.prev;t.next=e.next,e.next.prev=t}else e.prev===i.Undefined&&e.next===i.Undefined?(this._first=i.Undefined,this._last=i.Undefined):e.next===i.Undefined?(this._last=this._last.prev,this._last.next=i.Undefined):e.prev===i.Undefined&&(this._first=this._first.next,this._first.prev=i.Undefined);this._size-=1}*[Symbol.iterator](){let e=this._first;for(;e!==i.Undefined;)yield e.element,e=e.next}}t.LinkedList=s},2608:(e,t)=>{var i;Object.defineProperty(t,"__esModule",{value:!0}),t.SetMap=t.BidirectionalMap=t.CounterSet=t.Touch=void 0,t.getOrSet=function(e,t,i){let s=e.get(t);return void 0===s&&(s=i,e.set(t,s)),s},t.mapToString=function(e){const t=[];return e.forEach(((e,i)=>{t.push(`${i} => ${e}`)})),`Map(${e.size}) {${t.join(", ")}}`},t.setToString=function(e){const t=[];return e.forEach((e=>{t.push(e)})),`Set(${e.size}) {${t.join(", ")}}`},t.mapsStrictEqualIgnoreOrder=function(e,t){if(e===t)return!0;if(e.size!==t.size)return!1;for(const[i,s]of e)if(!t.has(i)||t.get(i)!==s)return!1;for(const[i]of t)if(!e.has(i))return!1;return!0},function(e){e[e.None=0]="None",e[e.AsOld=1]="AsOld",e[e.AsNew=2]="AsNew"}(i||(t.Touch=i={})),t.CounterSet=class{constructor(){this.map=new Map}add(e){return this.map.set(e,(this.map.get(e)||0)+1),this}delete(e){let t=this.map.get(e)||0;return 0!==t&&(t--,0===t?this.map.delete(e):this.map.set(e,t),!0)}has(e){return this.map.has(e)}},t.BidirectionalMap=class{constructor(e){if(this._m1=new Map,this._m2=new Map,e)for(const[t,i]of e)this.set(t,i)}clear(){this._m1.clear(),this._m2.clear()}set(e,t){this._m1.set(e,t),this._m2.set(t,e)}get(e){return this._m1.get(e)}getKey(e){return this._m2.get(e)}delete(e){const t=this._m1.get(e);return void 0!==t&&(this._m1.delete(e),this._m2.delete(t),!0)}forEach(e,t){this._m1.forEach(((i,s)=>{e.call(t,i,s,this)}))}keys(){return this._m1.keys()}values(){return this._m1.values()}},t.SetMap=class{constructor(){this.map=new Map}add(e,t){let i=this.map.get(e);i||(i=new Set,this.map.set(e,i)),i.add(t)}delete(e,t){const i=this.map.get(e);i&&(i.delete(t),0===i.size&&this.map.delete(e))}forEach(e,t){const i=this.map.get(e);i&&i.forEach(t)}get(e){return this.map.get(e)||new Set}}},7704:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.SlidingWindowAverage=t.MovingAverage=t.Counter=void 0,t.clamp=function(e,t,i){return Math.min(Math.max(e,t),i)},t.rot=function(e,t){return(t+e%t)%t},t.isPointWithinTriangle=function(e,t,i,s,r,n,o,a){const l=o-i,h=a-s,c=r-i,d=n-s,u=e-i,_=t-s,f=l*l+h*h,p=l*c+h*d,g=l*u+h*_,m=c*c+d*d,v=c*u+d*_,S=1/(f*m-p*p),b=(m*g-p*v)*S,C=(f*v-p*g)*S;return b>=0&&C>=0&&b+C<1},t.Counter=class{constructor(){this._next=0}getNext(){return this._next++}},t.MovingAverage=class{constructor(){this._n=1,this._val=0}update(e){return this._val=this._val+(e-this._val)/this._n,this._n+=1,this._val}get value(){return this._val}},t.SlidingWindowAverage=class{constructor(e){this._n=0,this._val=0,this._values=[],this._index=0,this._sum=0,this._values=new Array(e),this._values.fill(0,0,e)}update(e){const t=this._values[this._index];return this._values[this._index]=e,this._index=(this._index+1)%this._values.length,this._sum-=t,this._sum+=e,this._n<this._values.length&&(this._n+=1),this._val=this._sum/this._n,this._val}get value(){return this._val}}},8163:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.isAndroid=t.isEdge=t.isSafari=t.isFirefox=t.isChrome=t.OS=t.OperatingSystem=t.setTimeout0=t.setTimeout0IsFaster=t.translationsConfigFile=t.platformLocale=t.locale=t.Language=t.language=t.userAgent=t.platform=t.isCI=t.isMobile=t.isIOS=t.webWorkerOrigin=t.isWebWorker=t.isWeb=t.isElectron=t.isNative=t.isLinuxSnap=t.isLinux=t.isMacintosh=t.isWindows=t.Platform=t.LANGUAGE_DEFAULT=void 0,t.PlatformToString=function(e){switch(e){case C.Web:return"Web";case C.Mac:return"Mac";case C.Linux:return"Linux";case C.Windows:return"Windows"}},t.isLittleEndian=function(){if(!L){L=!0;const e=new Uint8Array(2);e[0]=1,e[1]=2;const t=new Uint16Array(e.buffer);D=513===t[0]}return D},t.isBigSurOrNewer=function(e){return parseFloat(e)>=20},t.LANGUAGE_DEFAULT="en";let i,s,r,n=!1,o=!1,a=!1,l=!1,h=!1,c=!1,d=!1,u=!1,_=!1,f=!1,p=t.LANGUAGE_DEFAULT,g=t.LANGUAGE_DEFAULT;const m=globalThis;let v;void 0!==m.vscode&&void 0!==m.vscode.process?v=m.vscode.process:"undefined"!=typeof process&&"string"==typeof process?.versions?.node&&(v=process);const S="string"==typeof v?.versions?.electron,b=S&&"renderer"===v?.type;if("object"==typeof v){n="win32"===v.platform,o="darwin"===v.platform,a="linux"===v.platform,l=a&&!!v.env.SNAP&&!!v.env.SNAP_REVISION,d=S,_=!!v.env.CI||!!v.env.BUILD_ARTIFACTSTAGINGDIRECTORY,i=t.LANGUAGE_DEFAULT,p=t.LANGUAGE_DEFAULT;const e=v.env.VSCODE_NLS_CONFIG;if(e)try{const r=JSON.parse(e);i=r.userLocale,g=r.osLocale,p=r.resolvedLanguage||t.LANGUAGE_DEFAULT,s=r.languagePack?.translationsConfigFile}catch(e){}h=!0}else"object"!=typeof navigator||b?console.error("Unable to resolve platform."):(r=navigator.userAgent,n=r.indexOf("Windows")>=0,o=r.indexOf("Macintosh")>=0,u=(r.indexOf("Macintosh")>=0||r.indexOf("iPad")>=0||r.indexOf("iPhone")>=0)&&!!navigator.maxTouchPoints&&navigator.maxTouchPoints>0,a=r.indexOf("Linux")>=0,f=r?.indexOf("Mobi")>=0,c=!0,p=globalThis._VSCODE_NLS_LANGUAGE||t.LANGUAGE_DEFAULT,i=navigator.language.toLowerCase(),g=i);var C;!function(e){e[e.Web=0]="Web",e[e.Mac=1]="Mac",e[e.Linux=2]="Linux",e[e.Windows=3]="Windows"}(C||(t.Platform=C={}));let y=C.Web;var w,E;o?y=C.Mac:n?y=C.Windows:a&&(y=C.Linux),t.isWindows=n,t.isMacintosh=o,t.isLinux=a,t.isLinuxSnap=l,t.isNative=h,t.isElectron=d,t.isWeb=c,t.isWebWorker=c&&"function"==typeof m.importScripts,t.webWorkerOrigin=t.isWebWorker?m.origin:void 0,t.isIOS=u,t.isMobile=f,t.isCI=_,t.platform=y,t.userAgent=r,t.language=p,function(e){e.value=function(){return t.language},e.isDefaultVariant=function(){return 2===t.language.length?"en"===t.language:t.language.length>=3&&"e"===t.language[0]&&"n"===t.language[1]&&"-"===t.language[2]},e.isDefault=function(){return"en"===t.language}}(w||(t.Language=w={})),t.locale=i,t.platformLocale=g,t.translationsConfigFile=s,t.setTimeout0IsFaster="function"==typeof m.postMessage&&!m.importScripts,t.setTimeout0=(()=>{if(t.setTimeout0IsFaster){const e=[];m.addEventListener("message",(t=>{if(t.data&&t.data.vscodeScheduleAsyncWork)for(let i=0,s=e.length;i<s;i++){const s=e[i];if(s.id===t.data.vscodeScheduleAsyncWork)return e.splice(i,1),void s.callback()}}));let t=0;return i=>{const s=++t;e.push({id:s,callback:i}),m.postMessage({vscodeScheduleAsyncWork:s},"*")}}return e=>setTimeout(e)})(),function(e){e[e.Windows=1]="Windows",e[e.Macintosh=2]="Macintosh",e[e.Linux=3]="Linux"}(E||(t.OperatingSystem=E={})),t.OS=o||u?E.Macintosh:n?E.Windows:E.Linux;let D=!0,L=!1;t.isChrome=!!(t.userAgent&&t.userAgent.indexOf("Chrome")>=0),t.isFirefox=!!(t.userAgent&&t.userAgent.indexOf("Firefox")>=0),t.isSafari=!!(!t.isChrome&&t.userAgent&&t.userAgent.indexOf("Safari")>=0),t.isEdge=!!(t.userAgent&&t.userAgent.indexOf("Edg/")>=0),t.isAndroid=!!(t.userAgent&&t.userAgent.indexOf("Android")>=0)},9881:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.SmoothScrollingOperation=t.SmoothScrollingUpdate=t.Scrollable=t.ScrollState=t.ScrollbarVisibility=void 0;const s=i(802),r=i(7150);var n;!function(e){e[e.Auto=1]="Auto",e[e.Hidden=2]="Hidden",e[e.Visible=3]="Visible"}(n||(t.ScrollbarVisibility=n={}));class o{constructor(e,t,i,s,r,n,o){this._forceIntegerValues=e,this._scrollStateBrand=void 0,this._forceIntegerValues&&(t|=0,i|=0,s|=0,r|=0,n|=0,o|=0),this.rawScrollLeft=s,this.rawScrollTop=o,t<0&&(t=0),s+t>i&&(s=i-t),s<0&&(s=0),r<0&&(r=0),o+r>n&&(o=n-r),o<0&&(o=0),this.width=t,this.scrollWidth=i,this.scrollLeft=s,this.height=r,this.scrollHeight=n,this.scrollTop=o}equals(e){return this.rawScrollLeft===e.rawScrollLeft&&this.rawScrollTop===e.rawScrollTop&&this.width===e.width&&this.scrollWidth===e.scrollWidth&&this.scrollLeft===e.scrollLeft&&this.height===e.height&&this.scrollHeight===e.scrollHeight&&this.scrollTop===e.scrollTop}withScrollDimensions(e,t){return new o(this._forceIntegerValues,void 0!==e.width?e.width:this.width,void 0!==e.scrollWidth?e.scrollWidth:this.scrollWidth,t?this.rawScrollLeft:this.scrollLeft,void 0!==e.height?e.height:this.height,void 0!==e.scrollHeight?e.scrollHeight:this.scrollHeight,t?this.rawScrollTop:this.scrollTop)}withScrollPosition(e){return new o(this._forceIntegerValues,this.width,this.scrollWidth,void 0!==e.scrollLeft?e.scrollLeft:this.rawScrollLeft,this.height,this.scrollHeight,void 0!==e.scrollTop?e.scrollTop:this.rawScrollTop)}createScrollEvent(e,t){const i=this.width!==e.width,s=this.scrollWidth!==e.scrollWidth,r=this.scrollLeft!==e.scrollLeft,n=this.height!==e.height,o=this.scrollHeight!==e.scrollHeight,a=this.scrollTop!==e.scrollTop;return{inSmoothScrolling:t,oldWidth:e.width,oldScrollWidth:e.scrollWidth,oldScrollLeft:e.scrollLeft,width:this.width,scrollWidth:this.scrollWidth,scrollLeft:this.scrollLeft,oldHeight:e.height,oldScrollHeight:e.scrollHeight,oldScrollTop:e.scrollTop,height:this.height,scrollHeight:this.scrollHeight,scrollTop:this.scrollTop,widthChanged:i,scrollWidthChanged:s,scrollLeftChanged:r,heightChanged:n,scrollHeightChanged:o,scrollTopChanged:a}}}t.ScrollState=o;class a extends r.Disposable{constructor(e){super(),this._scrollableBrand=void 0,this._onScroll=this._register(new s.Emitter),this.onScroll=this._onScroll.event,this._smoothScrollDuration=e.smoothScrollDuration,this._scheduleAtNextAnimationFrame=e.scheduleAtNextAnimationFrame,this._state=new o(e.forceIntegerValues,0,0,0,0,0,0),this._smoothScrolling=null}dispose(){this._smoothScrolling&&(this._smoothScrolling.dispose(),this._smoothScrolling=null),super.dispose()}setSmoothScrollDuration(e){this._smoothScrollDuration=e}validateScrollPosition(e){return this._state.withScrollPosition(e)}getScrollDimensions(){return this._state}setScrollDimensions(e,t){const i=this._state.withScrollDimensions(e,t);this._setState(i,Boolean(this._smoothScrolling)),this._smoothScrolling?.acceptScrollDimensions(this._state)}getFutureScrollPosition(){return this._smoothScrolling?this._smoothScrolling.to:this._state}getCurrentScrollPosition(){return this._state}setScrollPositionNow(e){const t=this._state.withScrollPosition(e);this._smoothScrolling&&(this._smoothScrolling.dispose(),this._smoothScrolling=null),this._setState(t,!1)}setScrollPositionSmooth(e,t){if(0===this._smoothScrollDuration)return this.setScrollPositionNow(e);if(this._smoothScrolling){e={scrollLeft:void 0===e.scrollLeft?this._smoothScrolling.to.scrollLeft:e.scrollLeft,scrollTop:void 0===e.scrollTop?this._smoothScrolling.to.scrollTop:e.scrollTop};const i=this._state.withScrollPosition(e);if(this._smoothScrolling.to.scrollLeft===i.scrollLeft&&this._smoothScrolling.to.scrollTop===i.scrollTop)return;let s;s=t?new c(this._smoothScrolling.from,i,this._smoothScrolling.startTime,this._smoothScrolling.duration):this._smoothScrolling.combine(this._state,i,this._smoothScrollDuration),this._smoothScrolling.dispose(),this._smoothScrolling=s}else{const t=this._state.withScrollPosition(e);this._smoothScrolling=c.start(this._state,t,this._smoothScrollDuration)}this._smoothScrolling.animationFrameDisposable=this._scheduleAtNextAnimationFrame((()=>{this._smoothScrolling&&(this._smoothScrolling.animationFrameDisposable=null,this._performSmoothScrolling())}))}hasPendingScrollAnimation(){return Boolean(this._smoothScrolling)}_performSmoothScrolling(){if(!this._smoothScrolling)return;const e=this._smoothScrolling.tick(),t=this._state.withScrollPosition(e);return this._setState(t,!0),this._smoothScrolling?e.isDone?(this._smoothScrolling.dispose(),void(this._smoothScrolling=null)):void(this._smoothScrolling.animationFrameDisposable=this._scheduleAtNextAnimationFrame((()=>{this._smoothScrolling&&(this._smoothScrolling.animationFrameDisposable=null,this._performSmoothScrolling())}))):void 0}_setState(e,t){const i=this._state;i.equals(e)||(this._state=e,this._onScroll.fire(this._state.createScrollEvent(i,t)))}}t.Scrollable=a;class l{constructor(e,t,i){this.scrollLeft=e,this.scrollTop=t,this.isDone=i}}function h(e,t){const i=t-e;return function(t){return e+i*(1-(s=1-t,Math.pow(s,3)));var s}}t.SmoothScrollingUpdate=l;class c{constructor(e,t,i,s){this.from=e,this.to=t,this.duration=s,this.startTime=i,this.animationFrameDisposable=null,this._initAnimations()}_initAnimations(){this.scrollLeft=this._initAnimation(this.from.scrollLeft,this.to.scrollLeft,this.to.width),this.scrollTop=this._initAnimation(this.from.scrollTop,this.to.scrollTop,this.to.height)}_initAnimation(e,t,i){if(Math.abs(e-t)>2.5*i){let o,a;return e<t?(o=e+.75*i,a=t-.75*i):(o=e-.75*i,a=t+.75*i),s=h(e,o),r=h(a,t),n=.33,function(e){return e<n?s(e/n):r((e-n)/(1-n))}}var s,r,n;return h(e,t)}dispose(){null!==this.animationFrameDisposable&&(this.animationFrameDisposable.dispose(),this.animationFrameDisposable=null)}acceptScrollDimensions(e){this.to=e.withScrollPosition(this.to),this._initAnimations()}tick(){return this._tick(Date.now())}_tick(e){const t=(e-this.startTime)/this.duration;if(t<1){const e=this.scrollLeft(t),i=this.scrollTop(t);return new l(e,i,!1)}return new l(this.to.scrollLeft,this.to.scrollTop,!0)}combine(e,t,i){return c.start(e,t,i)}static start(e,t,i){i+=10;const s=Date.now()-10;return new c(e,t,s,i)}}t.SmoothScrollingOperation=c},9725:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.StopWatch=void 0;const i=globalThis.performance&&"function"==typeof globalThis.performance.now;class s{static create(e){return new s(e)}constructor(e){this._now=i&&!1===e?Date.now:globalThis.performance.now.bind(globalThis.performance),this._startTime=this._now(),this._stopTime=-1}stop(){this._stopTime=this._now()}reset(){this._startTime=this._now(),this._stopTime=-1}elapsed(){return-1!==this._stopTime?this._stopTime-this._startTime:this._now()-this._startTime}}t.StopWatch=s},1316:(e,t,i)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.noBreakWhitespace=t.CodePointIterator=void 0,t.isFalsyOrWhitespace=function(e){return!e||"string"!=typeof e||0===e.trim().length},t.format=function(e,...t){return 0===t.length?e:e.replace(n,(function(e,i){const s=parseInt(i,10);return isNaN(s)||s<0||s>=t.length?e:t[s]}))},t.format2=function(e,t){return 0===Object.keys(t).length?e:e.replace(o,((e,i)=>t[i]??e))},t.htmlAttributeEncodeValue=function(e){return e.replace(/[<>"\'&]/g,(e=>{switch(e){case"<":return"&lt;";case">":return"&gt;";case\'"\':return"&quot;";case"\'":return"&apos;";case"&":return"&amp;"}return e}))},t.escape=function(e){return e.replace(/[<>&]/g,(function(e){switch(e){case"<":return"&lt;";case">":return"&gt;";case"&":return"&amp;";default:return e}}))},t.escapeRegExpCharacters=a,t.count=function(e,t){let i=0,s=e.indexOf(t);for(;-1!==s;)i++,s=e.indexOf(t,s+t.length);return i},t.truncate=function(e,t,i="\u2026"){return e.length<=t?e:`${e.substr(0,t)}${i}`},t.truncateMiddle=function(e,t,i="\u2026"){if(e.length<=t)return e;const s=Math.ceil(t/2)-i.length/2,r=Math.floor(t/2)-i.length/2;return`${e.substr(0,s)}${i}${e.substr(e.length-r)}`},t.trim=function(e,t=" "){return h(l(e,t),t)},t.ltrim=l,t.rtrim=h,t.convertSimple2RegExpPattern=function(e){return e.replace(/[\\-\\\\\\{\\}\\+\\?\\|\\^\\$\\.\\,\\[\\]\\(\\)\\#\\s]/g,"\\\\$&").replace(/[\\*]/g,".*")},t.stripWildcards=function(e){return e.replace(/\\*/g,"")},t.createRegExp=function(e,t,i={}){if(!e)throw new Error("Cannot create regex from empty string");t||(e=a(e)),i.wholeWord&&(/\\B/.test(e.charAt(0))||(e="\\\\b"+e),/\\B/.test(e.charAt(e.length-1))||(e+="\\\\b"));let s="";return i.global&&(s+="g"),i.matchCase||(s+="i"),i.multiline&&(s+="m"),i.unicode&&(s+="u"),new RegExp(e,s)},t.regExpLeadsToEndlessLoop=function(e){return"^"!==e.source&&"^$"!==e.source&&"$"!==e.source&&"^\\\\s*$"!==e.source&&!(!e.exec("")||0!==e.lastIndex)},t.splitLines=function(e){return e.split(/\\r\\n|\\r|\\n/)},t.splitLinesIncludeSeparators=function(e){const t=[],i=e.split(/(\\r\\n|\\r|\\n)/);for(let e=0;e<Math.ceil(i.length/2);e++)t.push(i[2*e]+(i[2*e+1]??""));return t},t.firstNonWhitespaceIndex=function(e){for(let t=0,i=e.length;t<i;t++){const i=e.charCodeAt(t);if(i!==s.CharCode.Space&&i!==s.CharCode.Tab)return t}return-1},t.getLeadingWhitespace=function(e,t=0,i=e.length){for(let r=t;r<i;r++){const i=e.charCodeAt(r);if(i!==s.CharCode.Space&&i!==s.CharCode.Tab)return e.substring(t,r)}return e.substring(t,i)},t.lastNonWhitespaceIndex=function(e,t=e.length-1){for(let i=t;i>=0;i--){const t=e.charCodeAt(i);if(t!==s.CharCode.Space&&t!==s.CharCode.Tab)return i}return-1},t.replaceAsync=function(e,t,i){const s=[];let r=0;for(const n of e.matchAll(t)){if(s.push(e.slice(r,n.index)),void 0===n.index)throw new Error("match.index should be defined");r=n.index+n[0].length,s.push(i(n[0],...n.slice(1),n.index,e,n.groups))}return s.push(e.slice(r)),Promise.all(s).then((e=>e.join("")))},t.compare=function(e,t){return e<t?-1:e>t?1:0},t.compareSubstring=c,t.compareIgnoreCase=function(e,t){return d(e,t,0,e.length,0,t.length)},t.compareSubstringIgnoreCase=d,t.isAsciiDigit=function(e){return e>=s.CharCode.Digit0&&e<=s.CharCode.Digit9},t.isLowerAsciiLetter=u,t.isUpperAsciiLetter=function(e){return e>=s.CharCode.A&&e<=s.CharCode.Z},t.equalsIgnoreCase=function(e,t){return e.length===t.length&&0===d(e,t)},t.startsWithIgnoreCase=function(e,t){const i=t.length;return!(t.length>e.length)&&0===d(e,t,0,i)},t.commonPrefixLength=function(e,t){const i=Math.min(e.length,t.length);let s;for(s=0;s<i;s++)if(e.charCodeAt(s)!==t.charCodeAt(s))return s;return i},t.commonSuffixLength=function(e,t){const i=Math.min(e.length,t.length);let s;const r=e.length-1,n=t.length-1;for(s=0;s<i;s++)if(e.charCodeAt(r-s)!==t.charCodeAt(n-s))return s;return i},t.isHighSurrogate=_,t.isLowSurrogate=f,t.computeCodePoint=p,t.getNextCodePoint=g;const s=i(4869),r=i(8960),n=/{(\\d+)}/g,o=/{([^}]+)}/g;function a(e){return e.replace(/[\\\\\\{\\}\\*\\+\\?\\|\\^\\$\\.\\[\\]\\(\\)]/g,"\\\\$&")}function l(e,t){if(!e||!t)return e;const i=t.length;if(0===i||0===e.length)return e;let s=0;for(;e.indexOf(t,s)===s;)s+=i;return e.substring(s)}function h(e,t){if(!e||!t)return e;const i=t.length,s=e.length;if(0===i||0===s)return e;let r=s,n=-1;for(;n=e.lastIndexOf(t,r-1),-1!==n&&n+i===r;){if(0===n)return"";r=n}return e.substring(0,r)}function c(e,t,i=0,s=e.length,r=0,n=t.length){for(;i<s&&r<n;i++,r++){const s=e.charCodeAt(i),n=t.charCodeAt(r);if(s<n)return-1;if(s>n)return 1}const o=s-i,a=n-r;return o<a?-1:o>a?1:0}function d(e,t,i=0,s=e.length,r=0,n=t.length){for(;i<s&&r<n;i++,r++){let o=e.charCodeAt(i),a=t.charCodeAt(r);if(o===a)continue;if(o>=128||a>=128)return c(e.toLowerCase(),t.toLowerCase(),i,s,r,n);u(o)&&(o-=32),u(a)&&(a-=32);const l=o-a;if(0!==l)return l}const o=s-i,a=n-r;return o<a?-1:o>a?1:0}function u(e){return e>=s.CharCode.a&&e<=s.CharCode.z}function _(e){return 55296<=e&&e<=56319}function f(e){return 56320<=e&&e<=57343}function p(e,t){return t-56320+(e-55296<<10)+65536}function g(e,t,i){const s=e.charCodeAt(i);if(_(s)&&i+1<t){const t=e.charCodeAt(i+1);if(f(t))return p(s,t)}return s}t.CodePointIterator=class{get offset(){return this._offset}constructor(e,t=0){this._str=e,this._len=e.length,this._offset=t}setOffset(e){this._offset=e}prevCodePoint(){const e=function(e,t){const i=e.charCodeAt(t-1);if(f(i)&&t>1){const s=e.charCodeAt(t-2);if(_(s))return p(s,i)}return i}(this._str,this._offset);return this._offset-=e>=r.Constants.UNICODE_SUPPLEMENTARY_PLANE_BEGIN?2:1,e}nextCodePoint(){const e=g(this._str,this._len,this._offset);return this._offset+=e>=r.Constants.UNICODE_SUPPLEMENTARY_PLANE_BEGIN?2:1,e}eol(){return this._offset>=this._len}},t.noBreakWhitespace="\xA0"},5015:(e,t)=>{Object.defineProperty(t,"__esModule",{value:!0}),t.MicrotaskDelay=void 0,t.MicrotaskDelay=Symbol("MicrotaskDelay")},8960:(e,t)=>{var i;Object.defineProperty(t,"__esModule",{value:!0}),t.Constants=void 0,t.toUint8=function(e){return e<0?0:e>i.MAX_UINT_8?i.MAX_UINT_8:0|e},t.toUint32=function(e){return e<0?0:e>i.MAX_UINT_32?i.MAX_UINT_32:0|e},function(e){e[e.MAX_SAFE_SMALL_INTEGER=1073741824]="MAX_SAFE_SMALL_INTEGER",e[e.MIN_SAFE_SMALL_INTEGER=-1073741824]="MIN_SAFE_SMALL_INTEGER",e[e.MAX_UINT_8=255]="MAX_UINT_8",e[e.MAX_UINT_16=65535]="MAX_UINT_16",e[e.MAX_UINT_32=4294967295]="MAX_UINT_32",e[e.UNICODE_SUPPLEMENTARY_PLANE_BEGIN=65536]="UNICODE_SUPPLEMENTARY_PLANE_BEGIN"}(i||(t.Constants=i={}))}},t={};function i(s){var r=t[s];if(void 0!==r)return r.exports;var n=t[s]={exports:{}};return e[s].call(n.exports,n,n.exports,i),n.exports}var s={};return(()=>{var e=s;Object.defineProperty(e,"__esModule",{value:!0}),e.Terminal=void 0;const t=i(7721),r=i(1718),n=i(7150),o=i(3027),a=i(5101),l=i(6097),h=i(4335),c=["cols","rows"];let d=0;class u extends n.Disposable{constructor(e){super(),this._core=this._register(new r.CoreBrowserTerminal(e)),this._addonManager=this._register(new o.AddonManager),this._publicOptions={...this._core.options};const t=e=>this._core.options[e],i=(e,t)=>{this._checkReadonlyOptions(e),this._core.options[e]=t};for(const e in this._core.options){const s={get:t.bind(this,e),set:i.bind(this,e)};Object.defineProperty(this._publicOptions,e,s)}}_checkReadonlyOptions(e){if(c.includes(e))throw new Error(`Option "${e}" can only be set in the constructor`)}_checkProposedApi(){if(!this._core.optionsService.rawOptions.allowProposedApi)throw new Error("You must set the allowProposedApi option to true to use proposed API")}get onBell(){return this._core.onBell}get onBinary(){return this._core.onBinary}get onCursorMove(){return this._core.onCursorMove}get onData(){return this._core.onData}get onKey(){return this._core.onKey}get onLineFeed(){return this._core.onLineFeed}get onRender(){return this._core.onRender}get onResize(){return this._core.onResize}get onScroll(){return this._core.onScroll}get onSelectionChange(){return this._core.onSelectionChange}get onTitleChange(){return this._core.onTitleChange}get onWriteParsed(){return this._core.onWriteParsed}get element(){return this._core.element}get parser(){return this._parser||(this._parser=new l.ParserApi(this._core)),this._parser}get unicode(){return this._checkProposedApi(),new h.UnicodeApi(this._core)}get textarea(){return this._core.textarea}get rows(){return this._core.rows}get cols(){return this._core.cols}get buffer(){return this._buffer||(this._buffer=this._register(new a.BufferNamespaceApi(this._core))),this._buffer}get markers(){return this._checkProposedApi(),this._core.markers}get modes(){const e=this._core.coreService.decPrivateModes;let t="none";switch(this._core.coreMouseService.activeProtocol){case"X10":t="x10";break;case"VT200":t="vt200";break;case"DRAG":t="drag";break;case"ANY":t="any"}return{applicationCursorKeysMode:e.applicationCursorKeys,applicationKeypadMode:e.applicationKeypad,bracketedPasteMode:e.bracketedPasteMode,insertMode:this._core.coreService.modes.insertMode,mouseTrackingMode:t,originMode:e.origin,reverseWraparoundMode:e.reverseWraparound,sendFocusMode:e.sendFocus,synchronizedOutputMode:e.synchronizedOutput,wraparoundMode:e.wraparound}}get options(){return this._publicOptions}set options(e){for(const t in e)this._publicOptions[t]=e[t]}blur(){this._core.blur()}focus(){this._core.focus()}input(e,t=!0){this._core.input(e,t)}resize(e,t){this._verifyIntegers(e,t),this._core.resize(e,t)}open(e){this._core.open(e)}attachCustomKeyEventHandler(e){this._core.attachCustomKeyEventHandler(e)}attachCustomWheelEventHandler(e){this._core.attachCustomWheelEventHandler(e)}registerLinkProvider(e){return this._core.registerLinkProvider(e)}registerCharacterJoiner(e){return this._checkProposedApi(),this._core.registerCharacterJoiner(e)}deregisterCharacterJoiner(e){this._checkProposedApi(),this._core.deregisterCharacterJoiner(e)}registerMarker(e=0){return this._verifyIntegers(e),this._core.registerMarker(e)}registerDecoration(e){return this._checkProposedApi(),this._verifyPositiveIntegers(e.x??0,e.width??0,e.height??0),this._core.registerDecoration(e)}hasSelection(){return this._core.hasSelection()}select(e,t,i){this._verifyIntegers(e,t,i),this._core.select(e,t,i)}getSelection(){return this._core.getSelection()}getSelectionPosition(){return this._core.getSelectionPosition()}clearSelection(){this._core.clearSelection()}selectAll(){this._core.selectAll()}selectLines(e,t){this._verifyIntegers(e,t),this._core.selectLines(e,t)}dispose(){super.dispose()}scrollLines(e){this._verifyIntegers(e),this._core.scrollLines(e)}scrollPages(e){this._verifyIntegers(e),this._core.scrollPages(e)}scrollToTop(){this._core.scrollToTop()}scrollToBottom(){this._core.scrollToBottom()}scrollToLine(e){this._verifyIntegers(e),this._core.scrollToLine(e)}clear(){this._core.clear()}write(e,t){this._core.write(e,t)}writeln(e,t){this._core.write(e),this._core.write("\\r\\n",t)}paste(e){this._core.paste(e)}refresh(e,t){this._verifyIntegers(e,t),this._core.refresh(e,t)}reset(){this._core.reset()}clearTextureAtlas(){this._core.clearTextureAtlas()}loadAddon(e){this._addonManager.loadAddon(this,e)}static get strings(){return{get promptLabel(){return t.promptLabel.get()},set promptLabel(e){t.promptLabel.set(e)},get tooMuchOutput(){return t.tooMuchOutput.get()},set tooMuchOutput(e){t.tooMuchOutput.set(e)}}}_verifyIntegers(...e){for(d of e)if(d===1/0||isNaN(d)||d%1!=0)throw new Error("This API only accepts integers")}_verifyPositiveIntegers(...e){for(d of e)if(d&&(d===1/0||isNaN(d)||d%1!=0||d<0))throw new Error("This API only accepts positive integers")}}e.Terminal=u})(),s})()));\n//# sourceMappingURL=xterm.js.map';

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
  font-family: monospace;
  user-select: text;
  white-space: pre;
}

.xterm .xterm-accessibility-tree > div {
  transform-origin: left;
  width: fit-content;
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



/* Derived from vs/base/browser/ui/scrollbar/media/scrollbar.css */

/* xterm.js customization: Override xterm's cursor style */
.xterm .xterm-scrollable-element > .scrollbar {
    cursor: default;
}

/* Arrows */
.xterm .xterm-scrollable-element > .scrollbar > .scra {
	cursor: pointer;
	font-size: 11px !important;
}

.xterm .xterm-scrollable-element > .visible {
	opacity: 1;

	/* Background rule added for IE9 - to allow clicks on dom node */
	background:rgba(0,0,0,0);

	transition: opacity 100ms linear;
	/* In front of peek view */
	z-index: 11;
}
.xterm .xterm-scrollable-element > .invisible {
	opacity: 0;
	pointer-events: none;
}
.xterm .xterm-scrollable-element > .invisible.fade {
	transition: opacity 800ms linear;
}

/* Scrollable Content Inset Shadow */
.xterm .xterm-scrollable-element > .shadow {
	position: absolute;
	display: none;
}
.xterm .xterm-scrollable-element > .shadow.top {
	display: block;
	top: 0;
	left: 3px;
	height: 3px;
	width: 100%;
	box-shadow: var(--vscode-scrollbar-shadow, #000) 0 6px 6px -6px inset;
}
.xterm .xterm-scrollable-element > .shadow.left {
	display: block;
	top: 3px;
	left: 0;
	height: 100%;
	width: 3px;
	box-shadow: var(--vscode-scrollbar-shadow, #000) 6px 0 6px -6px inset;
}
.xterm .xterm-scrollable-element > .shadow.top-left-corner {
	display: block;
	top: 0;
	left: 0;
	height: 3px;
	width: 3px;
}
.xterm .xterm-scrollable-element > .shadow.top.left {
	box-shadow: var(--vscode-scrollbar-shadow, #000) 6px 0 6px -6px inset;
}
`;

// node_modules/@xterm/addon-fit/lib/addon-fit.js
var addon_fit_default = '!function(e,t){"object"==typeof exports&&"object"==typeof module?module.exports=t():"function"==typeof define&&define.amd?define([],t):"object"==typeof exports?exports.FitAddon=t():e.FitAddon=t()}(globalThis,(()=>(()=>{"use strict";var e={};return(()=>{var t=e;Object.defineProperty(t,"__esModule",{value:!0}),t.FitAddon=void 0,t.FitAddon=class{activate(e){this._terminal=e}dispose(){}fit(){const e=this.proposeDimensions();if(!e||!this._terminal||isNaN(e.cols)||isNaN(e.rows))return;const t=this._terminal._core;this._terminal.rows===e.rows&&this._terminal.cols===e.cols||(t._renderService.clear(),this._terminal.resize(e.cols,e.rows))}proposeDimensions(){if(!this._terminal)return;if(!this._terminal.element||!this._terminal.element.parentElement)return;const e=this._terminal._core._renderService.dimensions;if(0===e.css.cell.width||0===e.css.cell.height)return;const t=0===this._terminal.options.scrollback?0:this._terminal.options.overviewRuler?.width||14,r=window.getComputedStyle(this._terminal.element.parentElement),i=parseInt(r.getPropertyValue("height")),o=Math.max(0,parseInt(r.getPropertyValue("width"))),s=window.getComputedStyle(this._terminal.element),n=i-(parseInt(s.getPropertyValue("padding-top"))+parseInt(s.getPropertyValue("padding-bottom"))),l=o-(parseInt(s.getPropertyValue("padding-right"))+parseInt(s.getPropertyValue("padding-left")))-t;return{cols:Math.max(2,Math.floor(l/e.css.cell.width)),rows:Math.max(1,Math.floor(n/e.css.cell.height))}}}})(),e})()));\n//# sourceMappingURL=addon-fit.js.map';

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
