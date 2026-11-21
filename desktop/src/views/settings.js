// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// The Settings page: the seats of every flow and the budget that stops new kickoffs (cockpitlib.settings, hermes/watch/settings.json).
// Everything reads from here: the capacity pills and the kickoff refusal, the lane choosers, cockpit setup apply for the profiles.
// Then the daily pass over stale worktrees (cockpitlib.cleanup, worktree_gc: off by default; Preview and Run now run it by hand).
// Below them: the plugin against its own repository (cockpitlib.self_update): what is installed, whether the repository is ahead, Update.
import { useState } from 'react'
import { host, useQuery, useQueryClient, CTX, h, sub, mono, stroke, btn, ago, post } from '../lib/sdk.js'
import { copyBtn } from '../lib/secret.js'

const SEATS = [['slots', 'Agent slots', 'a worker and a tester per slot (the slot stacks exist for three)'], ['intake', 'Intake seats', 'Dev kickoffs: intake reproduces and proposes'], ['reviewer', 'Reviewer seats', 'Review and Bump'], ['analyst', 'Analyst seats', 'Question']]
const num = (v) => (v === '' || v == null ? '' : Number(v))
const box = (title, ...kids) => h('div', { className: 'flex flex-col gap-1 rounded border px-3 py-2', style: { borderColor: stroke } }, h('div', { className: 'cockpit-head mb-1' }, title), ...kids)

// the plugin's own update: installed commit, the last check against origin, Check now / Update now; the gateway restarts by itself,
// the Desktop needs its own restart when the UI changed (the dashboard-restart row in the Inbox says so too)
function PluginUpdate() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['cockpit', 'update'], queryFn: () => CTX.rest('/update'), refetchInterval: 60000, retry: 0 })
  const [busy, setBusy] = useState(''); const [last, setLast] = useState(null)
  const act = async (key, path, title) => {
    setBusy(key)
    try { const r = await post(path, {}); if (key === 'apply') setLast(r); host.notify({ kind: 'success', title, message: r.out || (r.remote && r.remote.behind ? `${r.remote.behind} commit(s) behind` : 'up to date') }); qc.invalidateQueries({ queryKey: ['cockpit'] }) }
    catch (e) { host.notifyError(e, title + ' failed') } finally { setBusy('') }
  }
  if (q.error) return box('Plugin update', h('div', { style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error)))
  const d = q.data || {}; const i = d.installed || {}; const r = d.remote || {}
  const behind = r.behind == null ? null : Number(r.behind)
  const state = d.error ? ['not a git checkout', 'var(--ui-warning, #c98a00)'] : d.dirty ? ['local edits in the checkout: update refused until they are committed or stashed', 'var(--ui-warning, #c98a00)']
    : behind == null ? [r.error ? `last check failed: ${r.error}` : 'not checked yet', sub.color] : behind > 0 ? [`${behind} commit(s) behind origin/${r.branch || i.branch || ''} (${r.short || ''})`, 'var(--ui-accent)'] : ['up to date', 'var(--ui-success, #2a9d5c)']
  return box('Plugin update (this cockpit against its repository)',
    h('div', { className: 'grid items-center gap-x-3 gap-y-1', style: { gridTemplateColumns: '7rem 1fr' } },
      h('span', { style: sub }, 'installed'), h('span', null, h('span', { style: mono }, i.short || '?'), i.subject ? ` · ${i.subject}` : '', i.date ? h('span', { style: sub }, ` · ${ago(i.date)} ago`) : null),
      h('span', { style: sub }, 'installed from'), h('span', null,
        h('span', { className: 'rounded border px-1.5 py-0.5', style: { ...mono, borderColor: stroke }, title: 'the branch this checkout follows; an update moves to its head' }, i.follows || 'no branch followed'),
        i.branch && i.follows && !i.follows.endsWith('/' + i.branch) ? h('span', { style: sub }, ` · local branch ${i.branch}`) : null),
      h('span', { style: sub }, 'repository'), h('span', { style: { color: state[1] } }, state[0], r.checked_at ? h('span', { style: sub }, ` · checked ${ago(new Date(r.checked_at * 1000).toISOString())} ago`) : null),
      d.desktop_stale ? h('span', { style: sub }, 'Desktop') : null, d.desktop_stale ? h('span', { style: { color: 'var(--ui-warning, #c98a00)' } }, d.desktop_stale) : null),
    h('div', { className: 'flex items-center gap-2 pt-1' },
      btn(busy === 'check' ? 'Checking…' : 'Check now', () => act('check', '/update-check', 'update check'), { disabled: Boolean(busy), title: 'git fetch origin and count the commits the checkout is behind (housekeeping does this hourly)' }),
      h('button', { type: 'button', disabled: Boolean(busy) || d.dirty || Boolean(d.error) || !behind, onClick: () => act('apply', '/update-apply', 'cockpit update'), className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' },
        title: 'fast-forward to origin, refresh the kernel dependencies when they changed, drop stale bytecode, bump the Desktop bundle time, record the revision with Hermes, restart the gateway (it drains running jobs first)' }, busy === 'apply' ? 'Updating…' : 'Update now'),
      h('span', { style: sub }, 'after an update: the gateway restarts by itself; the rest is one line for your shell, shown here once the update ran')),
    last ? h('div', { className: 'flex flex-col gap-0.5 pt-1' }, h('div', { style: { color: 'var(--ui-success, #2a9d5c)' } }, last.out),
      ...(last.commits || []).map((line) => h('div', { key: line, style: { ...mono, ...sub } }, line)),
      last.hermes_record ? h('div', { style: sub }, `Hermes's install record: ${last.hermes_record}`) : null,
      h(NextLine, { next: last.next })) : null)
}

// what is left to the human after an update, as the backend resolved it for this machine (the launcher's real path, the
// seats re-rendered, doctor, the Desktop when the UI changed): one line to copy into a shell, and the steps it holds
export function NextLine({ next }) {
  const steps = (next && next.steps) || []
  if (!steps.length) return null
  return h('div', { className: 'flex flex-col gap-1 pt-1', 'data-next-line': '1' },
    h('div', { className: 'font-medium' }, 'Now run, in your shell:'),
    h('div', { className: 'flex items-start gap-2' },
      h('code', { className: 'rounded px-1.5 py-0.5 whitespace-pre-wrap break-all', style: { ...mono, background: 'rgba(127,127,127,.12)' } }, next.line),
      copyBtn(next.line, 'the line to run after the update')),
    h('div', { style: sub }, steps.map((s) => s.what).join(' → ')))
}

function Settings() {
  const q = useQuery({ queryKey: ['cockpit', 'settings'], queryFn: () => CTX.rest('/settings'), refetchInterval: (d) => (d && d.apply && d.apply.running ? 2000 : 20000), retry: 1 })
  const qc = useQueryClient(); const [edit, setForm] = useState(null); const [busy, setBusy] = useState(false)   // edit: the unsaved form, null = what is saved
  const [gcOut, setGcOut] = useState(null)   // the lines of the last Preview / Run now of the worktree pass, this visit
  if (q.error) return h('div', { className: 'p-3 text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  if (q.isLoading || !q.data) return h('div', { className: 'p-3 text-xs', style: sub }, 'loading')
  const d = q.data; const b = d.budget || {}; const lim = d.limits || {}; const form = edit || d.settings
  const set = (path, v) => { const f = structuredClone(form); const [a, k] = path.split('.'); if (k) f[a][k] = v; else f[a] = v; setForm(f) }
  const act = async (path, body, title) => { setBusy(true); try { const r = await post(path, body); host.notify({ kind: 'success', title, message: r.out }); qc.invalidateQueries({ queryKey: ['cockpit'] }) } catch (e) { host.notifyError(e, title + ' failed') } finally { setBusy(false) } }
  const field = (path, value, props = {}) => h('input', { type: 'number', value: value ?? '', onChange: (e) => set(path, num(e.target.value)), className: 'w-20 rounded border bg-transparent px-1.5 py-0.5 text-right', style: { borderColor: stroke, fontVariantNumeric: 'tabular-nums' }, ...props })
  const row = (label, hint, input) => h('div', { className: 'grid items-center gap-3 py-1', style: { gridTemplateColumns: '11rem 6rem 1fr' } }, h('div', { className: 'font-medium' }, label), input, h('div', { style: sub }, hint))
  const bar = (pct, cap) => h('div', { className: 'h-2 rounded', style: { background: 'rgba(127,127,127,.18)' } }, h('div', { className: 'h-2 rounded', style: { width: Math.min(100, pct) + '%', background: pct >= (cap || 100) ? 'var(--ui-danger, #d33)' : pct >= (cap || 100) * 0.8 ? 'var(--ui-warning, #c98a00)' : 'var(--ui-success, #2a9d5c)' } }))
  const monthPct = b.cap_usd ? (100 * b.month_usd) / b.cap_usd : 0; const w = b.window
  const dirty = JSON.stringify(form) !== JSON.stringify(d.settings)
  const g = d.worktree_gc || {}; const gl = g.last || {}; const gcForm = form.worktree_gc || { enabled: false, days: 14 }
  const gcRun = async (dry) => { setBusy(true); try { const r = await post('/worktree-gc', { dry_run: dry, days: gcForm.days }); setGcOut(r.lines || []); host.notify({ kind: 'success', title: dry ? 'worktree gc preview' : 'worktree gc', message: r.out }); qc.invalidateQueries({ queryKey: ['cockpit'] }) } catch (e) { host.notifyError(e, 'worktree gc failed') } finally { setBusy(false) } }
  return h('div', { className: 'flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3 text-xs' },
    b.over ? h('div', { className: 'rounded border px-3 py-2', style: { borderColor: 'var(--ui-danger, #d33)', color: 'var(--ui-danger, #d33)' } }, `Over budget: no new kickoff starts — ${b.why}`) : null,
    box('Seats per flow (the capacity pills count them; anything queued is a taken seat)',
      ...SEATS.map(([k, label, hint]) => row(label, `${hint} · ${(lim[k] || [1, 5]).join('–')}`, field(`seats.${k}`, form.seats[k], { min: (lim[k] || [1])[0], max: (lim[k] || [1, 5])[1], step: 1 })))),
    box('Budget (stops new kickoffs; the lanes already running finish)',
      row('Monthly cap, $', `the Hermes stack's list-price estimate this month (the Usage page): ≈$${(b.month_usd || 0).toFixed(2)}${b.cap_usd ? ` of $${b.cap_usd.toFixed(2)}` : ' · 0 = no cap'}`, field('budget.monthly_usd', form.budget.monthly_usd, { min: 0, step: 10 })),
      b.cap_usd ? bar(monthPct, 100) : null,
      row('Plan window ceiling, %', w ? `the fullest provider plan window: ${w.name} ${w.used}% used, resets in ${w.resets_in}` : (b.unmetered || []).length && !b.error ? `no plan windows: Hermes reads none for ${b.unmetered.join(', ')} (not metered)` : 'the provider plan windows (hermes usage) could not be read',
        field('budget.plan_window_max_pct', form.budget.plan_window_max_pct, { min: 1, max: 100, step: 5 })),
      w ? bar(w.used, form.budget.plan_window_max_pct) : null,
      (b.ignored || []).length ? h('div', { style: sub }, `not counted: ${b.ignored.join(', ')} — no Hermes lane runs that model (the lanes run ${(b.families || []).join(', ') || '…'})`) : null),
    box('External browser', row('Lend it for, hours', 'how long a test kickoff keeps the external browser (your Chrome) when you tick it on the kickoff; only that test uses it, and its failure videos come from cockpit record', field('shared_chrome_hours', form.shared_chrome_hours, { min: 0.25, max: 24, step: 0.5 }))),
    box('Worktrees (a daily pass removes the ticket folders under wt/ nothing touched for a while; off by default)',
      row('Remove stale worktrees', 'a folder goes only when nothing under it was touched, no slot or open card holds the ticket, no process runs inside it, every checkout is clean and its commits are on a remote; branches stay',
        h('input', { type: 'checkbox', checked: Boolean(gcForm.enabled), onChange: (e) => set('worktree_gc.enabled', e.target.checked), className: 'justify-self-start', 'data-worktree-gc': '1' })),
      row('Untouched for, days', `the age a folder must have before it goes · ${((lim.worktree_gc_days) || [1, 365]).join('–')}`, field('worktree_gc.days', gcForm.days, { min: (lim.worktree_gc_days || [1])[0], max: (lim.worktree_gc_days || [1, 365])[1], step: 1 })),
      h('div', { className: 'flex items-center gap-2 pt-1' },
        btn('Preview', () => gcRun(true), { disabled: busy, title: 'list what a pass would remove now, with the reason every other folder stays (cockpit worktree gc --dry-run)' }),
        btn('Run now', () => gcRun(false), { disabled: busy, title: 'one pass now, whatever the switch says (cockpit worktree gc)' }),
        h('span', { style: sub }, gl.ran_at ? `last pass ${ago(new Date(gl.ran_at * 1000).toISOString())} ago: ${gl.summary || ''}` : 'no automatic pass yet')),
      gcOut ? h('pre', { className: 'whitespace-pre-wrap pt-1', style: { ...mono, ...sub } }, gcOut.join('\n')) : null),
    h('div', { className: 'flex items-center gap-2' },
      h('button', { type: 'button', disabled: busy || !dirty, onClick: () => act('/settings', { settings: form }, 'settings').then(() => setForm(null)), className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' } }, 'Save'),
      dirty ? btn('Discard', () => setForm(null)) : null,
      d.missing_lanes && d.missing_lanes.length ? h('span', { className: 'flex items-center gap-2' }, h('span', { style: { color: 'var(--ui-warning, #c98a00)' } }, `no profile yet for ${d.missing_lanes.join(', ')}`),
        btn(d.apply.running ? 'Applying…' : 'Apply profiles', () => act('/settings-apply', {}, 'cockpit setup apply'), { disabled: busy || d.apply.running, title: 'cockpit setup apply: creates the lanes the seats ask for (about a minute)' })) : null,
      d.apply.running ? h('span', { style: sub }, 'cockpit setup apply running…') : null),
    d.apply.log ? h('details', null, h('summary', { className: 'cursor-pointer', style: sub }, `last apply${d.apply.rc != null ? ` (exit ${d.apply.rc})` : ''}`), h('pre', { className: 'whitespace-pre-wrap', style: mono }, d.apply.log)) : null,
    h('div', { style: sub }, `Stored in ${d.path || 'hermes/watch/settings.json'}. A seat taken away keeps its profile; nothing gives it cards.`),
    h(PluginUpdate))
}

export { Settings }
