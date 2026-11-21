// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect } from 'react'
import { host, useQuery, useQueryClient, CTX, h, sub, mono, stroke, btn, selectBox, ago, fmtDur, post, openIde, openFile, trow, SplitList, detailHead, tabs, Section, prList } from '../lib/sdk.js'
import { RichMd, escapeHtml } from '../lib/markdown.js'
import { DiffPanel } from '../lib/diff.js'
import { Evidence } from './qa.js'
import { ReopenForm, ReworkForm } from './outbox.js'
import { CardView } from './inbox.js'
import { TicketTools } from './demo.js'

// ---------- the ticket's plan on disk (qa/<ticket>/plan.md): approved outline → worker plan → delivered → tested → reviewed ----------
function PlanView({ path, sections }) {
  const q = useQuery({ queryKey: ['cockpit', 'plan', path], queryFn: () => CTX.rest('/qa-file?path=' + encodeURIComponent(path)), refetchInterval: 20000, retry: 1 })
  if (q.isLoading) return h('div', { className: 'text-xs', style: sub }, 'loading')
  if (q.error) return h('div', { className: 'text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  const stages = ['Decision', 'Worker plan', 'Delivered', 'Tested', 'Reviewed']
  const done = (st) => sections.some((x) => x.toLowerCase().startsWith(st.toLowerCase()))
  return h('div', { className: 'flex flex-col gap-2' },
    h('div', { className: 'flex flex-wrap items-center gap-2 text-xs' }, h('span', { style: sub }, 'trail:'),
      ...stages.map((st) => h('span', { key: st, className: 'rounded px-1.5',
      style: { background: done(st) ? 'rgba(42,157,92,.18)' : 'rgba(127,127,127,.12)',
      color: done(st) ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-text-tertiary)' } }, (done(st) ? '✓ ' : '· ') + st)),
      h('span', { className: 'ml-auto flex gap-1' }, btn('Open', () => openFile(path)), btn('Reveal', () => CTX.os.revealPath(path)))),
    h(RichMd, { className: 'rounded border px-3 py-1', style: { borderColor: stroke }, html: q.data.html || ('<pre>' + escapeHtml(q.data.text || '') + '</pre>') }))
}

// ---------- tickets view: everything this machine holds per ticket; archive/delete are LOCAL ONLY ----------
const TICKET_COLS = '9rem 6rem 8rem 5rem 5.5rem 1fr 4rem 7rem 4rem'
const phaseColor = (p) => p === 'blocked' ? 'var(--ui-danger, #d33)' : p === 'running' || p === 'in review' ? 'var(--ui-accent)' : p === 'at the gate' ? 'var(--ui-success, #2a9d5c)' : p === 'manual session' ? 'var(--ui-warning, #c98a00)' : p.startsWith('done (unpushed') ? 'var(--ui-warning, #c98a00)' : 'var(--ui-text-tertiary)'
function TicketDetail({ ticket, refresh }) {
  const q = useQuery({ queryKey: ['cockpit', 'ticket', ticket], queryFn: () => CTX.rest('/ticket?ticket=' + encodeURIComponent(ticket)), refetchInterval: 15000, retry: 1 })
  const [tab, setTab] = useState('overview'); const [ask, setAsk] = useState(null); const [force, setForce] = useState(false); const [busy, setBusy] = useState(false); const [note, setNote] = useState(''); const [slot, setSlot] = useState('auto')
  const [cardId, setCardId] = useState(null)
  const cq = useQuery({ queryKey: ['cockpit', 'card-detail', cardId], queryFn: () => CTX.rest('/card-detail?id=' + cardId), enabled: Boolean(cardId), retry: 0 })
  useEffect(() => { setTab('overview'); setAsk(null); setCardId(null) }, [ticket])
  if (q.isLoading) return h('div', { className: 'p-3 text-xs', style: sub }, 'loading')
  if (q.error) return h('div', { className: 'p-3 text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  const t = q.data
  const act = async (path, body, okTitle) => { setBusy(true); try { const r = await post(path, body); host.notify({ kind: 'success', title: okTitle, message: (r.out || '').slice(0, 600) }); setAsk(null); refresh() } catch (e) { host.notifyError(e, okTitle + ' failed') } finally { setBusy(false) } }
  const unpushed = (t.worktrees || []).filter((w) => w.unpushed).map((w) => `${w.repo} ${w.branch} (${w.unpushed})`)
  const human = t.slot && t.slot.owner === 'human'; const halted = t.halted
  return h('div', { className: 'flex h-full flex-col gap-3 overflow-auto p-3' },
    detailHead(t.ticket, { text: halted ? 'HALTED' : t.phase, color: halted ? 'var(--ui-danger, #d33)' : phaseColor(t.phase) }, (halted ? `halted ${ago(halted.time)} ago${halted.note ? ' · ' + halted.note : ''} · ` : '') + (t.slot ? `slot ${t.slot.slot} · ${t.slot.owner.replace('lane:', '')}` : 'no slot')),
    t.summary || t.plan_line ? h('div', { className: 'text-xs', style: sub }, [t.summary, t.plan_line].filter(Boolean).join(' · ')) : null,
    (t.prs || []).length ? h('div', { className: 'flex items-center gap-2 text-xs' }, h('span', { style: sub }, 'PRs:'), prList(t.prs)) : null,
    h('div', { className: 'flex flex-wrap items-center gap-1.5' },
      (t.worktrees || []).length ? btn('Open IDE', () => openIde({ ticket: t.ticket }), { accent: true, title: 'VS Code on the ticket workspace' }) : null,
      !human ? h('span', { className: 'flex items-center gap-1' }, btn('Manual session', () => setAsk(ask === 'session' ? null : 'session'), { title: 'take a slot yourself: stack + worktrees + own Chrome + VS Code; the lanes keep off it' })) : null,
      human ? btn('Close session', () => act('/session', { action: 'close', slot: t.slot.slot }, 'session closed'), { title: `cockpit session close ${t.slot.slot}` }) : null,
      human && !halted ? btn('Hand off to the lanes', () => act('/session', { action: 'handoff', slot: t.slot.slot, ticket: t.ticket }, 'handed off'), { title: 'worker-N continues on this slot' }) : null,
      h('span', { className: 'mx-1', style: sub }, '|'),
      halted ? btn('Resume', () => act('/ticket-resume', { ticket: t.ticket }, `${t.ticket} resumed`), { accent: true, title: 'lift the halt: creators may start again; the closed cards stay closed — Reopen or Rework to continue' })
        : btn('Halt', () => setAsk(ask === 'halt' ? null : 'halt'), { danger: true, title: 'STOP everything on this ticket now: open cards closed (a running worker killed), intents at the gate held, nothing starts until Resume. Local only.' }),
      (t.worktrees || []).length && !halted ? btn('Rework', () => setAsk(ask === 'rework' ? null : 'rework'), { title: 'something is missing on the delivered PR: a worker card on the branch, tester and reviewer behind it' }) : null,
      !halted ? btn('Reopen', () => setAsk(ask === 'reopen' ? null : 'reopen'), { title: 'restart the flow with your prompt and evidence; intake proposes and waits for your go' }) : null,
      btn('Archive', () => setAsk(ask === 'archive' ? null : 'archive'), { title: 'local only: cards archived, worktrees removed, slot freed; keeps outbox + qa + branches' }),
      btn('Delete', () => setAsk(ask === 'delete' ? null : 'delete'), { danger: true, title: 'local only: archive + outbox/qa folders + local branches' }),
      btn('Reveal qa', () => CTX.os.revealPath(t.qa && t.qa.dir ? t.qa.dir : t.worktrees && t.worktrees[0] ? t.worktrees[0].dir : ''))),
    ask === 'session' ? h('div', { className: 'flex items-center gap-2 rounded border p-2 text-xs', style: { borderColor: stroke } },
      h('span', null, 'Open a manual session on slot'), selectBox(slot, setSlot, ['auto', '1', '2', '3'].map((v) => [v, v])),
      h('span', { style: sub }, '(stack from the seed data, worktrees, own Chrome, VS Code; takes ~1 min)'),
      h('button', { type: 'button', disabled: busy, onClick: () => act('/session', { action: 'open', ticket: t.ticket, slot }, 'manual session open'), className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'working' : 'Open'), btn('Cancel', () => setAsk(null))) : null,
    ask === 'halt' ? h('div', { className: 'flex flex-col gap-1 rounded border p-2 text-xs', style: { borderColor: 'var(--ui-danger, #d33)' } },
      h('div', { className: 'font-medium' }, `Halt ${t.ticket}: stop everything on it now`),
      h('div', { style: sub }, `Closes ${t.cards_open} open card(s) (a running worker is reclaimed: SIGTERM, then SIGKILL), holds ${t.intents_open} intent(s) at the gate for your decision, and marks the ticket so no card, rework, reopen or PR treatment can start until you press Resume. Worktrees, slot, outbox/${t.ticket} and qa/${t.ticket} stay. Nothing leaves this machine.`),
      h('input', { value: note, onChange: (e) => setNote(e.target.value), placeholder: 'optional: why (goes on the cards and in the log)', className: 'rounded border bg-transparent px-1.5 py-0.5', style: { borderColor: stroke } }),
      h('div', { className: 'flex gap-1.5' }, h('button', { type: 'button', disabled: busy, onClick: () => act('/ticket-halt', { ticket: t.ticket, confirm: t.ticket, note }, `${t.ticket} halted`), className: 'rounded px-2.5 py-0.5 text-xs font-medium', style: { background: 'var(--ui-danger, #d33)', color: '#fff' } }, busy ? 'working' : 'Halt now'), btn('Cancel', () => setAsk(null)))) : null,
    ask === 'reopen' ? h(ReopenForm, { ticket: t.ticket, onDone: () => setAsk(null) }) : null,
    ask === 'rework' ? h(ReworkForm, { ticket: t.ticket, repos: (t.worktrees || []).map((w) => w.repo), delivered: (t.worktrees || []).filter((w) => w.unpushed || (t.prs || []).some((p) => p.repo === w.repo && p.state === 'open')).map((w) => w.repo), onDone: () => setAsk(null) }) : null,
    ask === 'archive' || ask === 'delete' ? h('div', { className: 'flex flex-col gap-1 rounded border p-2 text-xs', style: { borderColor: ask === 'delete' ? 'var(--ui-danger, #d33)' : stroke } },
      h('div', { className: 'font-medium' }, ask === 'archive' ? `Archive ${t.ticket} on this machine` : `Delete everything local for ${t.ticket}`),
      h('div', { style: sub }, ask === 'archive'
        ? `Archives ${t.cards_open} open card(s), removes ${(t.worktrees || []).length} worktree(s), frees slot ${t.slot ? t.slot.slot : '–'}. Keeps outbox/${t.ticket}, qa/${t.ticket} and the local branches. Nothing leaves this machine.`
        : `Everything in Archive, plus outbox/${t.ticket} (${t.intents_total} intents), qa/${t.ticket} (${t.qa && t.qa.runs ? t.qa.runs + ' runs' : 'nothing'}) and the local branches. Origin, the forge, tracker are not touched.`),
      human ? h('div', { style: { color: 'var(--ui-warning, #c98a00)' } }, `Slot ${t.slot.slot} is a manual session: close it first.`) : null,
      unpushed.length ? h('div', { style: { color: 'var(--ui-warning, #c98a00)' } }, `Commits not on origin: ${unpushed.join(', ')}. ` + (ask === 'delete' ? 'Those branches are kept unless you tick force.' : 'Archive keeps the branches.')) : null,
      ask === 'delete' && unpushed.length ? h('label', { className: 'flex items-center gap-1' }, h('input', { type: 'checkbox', checked: force, onChange: (e) => setForce(e.target.checked) }), 'also delete the local branches with unpushed commits (irreversible)') : null,
      h('div', { className: 'flex gap-1.5' }, h('button', { type: 'button', disabled: busy || human,
        onClick: () => act(ask === 'archive' ? '/ticket-archive' : '/ticket-delete',
        { ticket: t.ticket, confirm: t.ticket, force: ask === 'delete' && force }, `${t.ticket} ${ask}d`),
        className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40',
        style: { background: ask === 'delete' ? 'var(--ui-danger, #d33)' : 'var(--ui-accent)', color: '#fff' } },
        busy ? 'working' : (ask === 'archive' ? 'Archive now' : 'Delete now')), btn('Cancel', () => setAsk(null)))) : null,
    tabs(tab, setTab, [['overview', 'Overview'], t.qa && t.qa.plan ? ['plan', 'Plan'] : null, (t.worktrees || []).length ? ['diff', 'Diff'] : null, ['evidence', 'Evidence (QA runs)']]),
    tab === 'plan' ? h(PlanView, { path: t.qa.plan, sections: t.qa.plan_sections || [] }) :
    tab === 'evidence' ? h(Evidence, { ticket: t.ticket }) :
    tab === 'diff' ? h('div', { className: 'flex flex-col gap-3' }, ...(t.worktrees || []).map((w) => h('div', { key: w.repo }, h('div', { className: 'text-xs font-medium mb-1' }, `${w.repo} · ${w.branch}`), h(DiffPanel, { params: { ticket: t.ticket, repo: w.repo }, defaultMode: 'origin' })))) :
    h('div', { className: 'flex flex-col gap-2 text-xs' },
      h(TicketTools, { ticket: t.ticket, part: 'chat' }),
      h(Section, { title: 'Brief', open: true, color: 'var(--ui-accent)' }, t.brief ? h(RichMd, { html: t.brief }) : h('div', { style: sub }, t.qa && t.qa.plan ? 'the plan has no Brief section (older plan format)' : 'no plan yet: intake has not had its go')),
      h(TicketTools, { ticket: t.ticket, part: 'demo' }),
      (t.plan_parts || []).length ? h(Section, { title: `Plan trail · ${(t.plan_parts || []).map((x) => x.title).join(' · ')}`, extra: btn('Open plan', () => openFile(t.qa.plan)) },
        ...(t.plan_parts || []).map((part) => h(Section, { key: part.title, title: part.title }, h(RichMd, { html: part.html })))) : null,
      h(Section, { title: `Cards (${t.cards_total})` }, h('div', { style: sub, className: 'mb-1' }, 'click one to read its comments and result'),
        ...(t.card_list || []).slice().reverse().map((c) => h('div',
        { key: c.id, className: 'flex gap-2 cursor-pointer cockpit-row rounded px-1', onClick: () => setCardId(cardId === c.id ? null : c.id),
        style: { background: cardId === c.id ? 'var(--ui-bg-selected, rgba(127,127,127,.15))' : 'transparent' } },
        h('span', { style: { color: c.status === 'blocked' ? 'var(--ui-danger, #d33)' : c.status === 'done' ? 'var(--ui-success, #2a9d5c)' : c.status === 'archived' ? 'var(--ui-text-quaternary)' : 'var(--ui-accent)',
        minWidth: '5rem' } }, c.status), h('span', { style: { ...mono, ...sub } }, c.id), h('span', { className: 'truncate' }, c.title),
        h('span', { style: sub }, c.assignee))), !(t.card_list || []).length ? h('div', { style: sub }, 'none') : null,
        cardId ? h('div', { className: 'rounded border p-2 mt-1', style: { borderColor: stroke, maxHeight: '55vh', overflow: 'auto' } }, cq.data ? h(CardView, { c: cq.data }) : h('div', { style: sub }, 'loading')) : null),
      h(Section, { title: `Outbox (${t.intents_total})` }, ...(t.intent_list || []).map((i) => h('div', { key: i.id, className: 'flex gap-2' },
        h('span', { style: { minWidth: '5rem', color: i.status === 'endorsed' ? 'var(--ui-success, #2a9d5c)' : i.status === 'pending' ? 'var(--ui-text-tertiary)' : 'var(--ui-text-quaternary)' } },
        i.status), h('span', { style: mono }, i.id), h('span', { style: sub }, i.type))),
        !(t.intent_list || []).length ? h('div', { style: sub }, 'none') : null),
      h(Section, { title: 'Worktrees' + (unpushed.length ? ` · ${unpushed.length} with unpushed commits` : '') },
        ...(t.worktrees || []).map((w) => h('div', { key: w.repo, className: 'flex gap-2' }, h('span', { style: mono }, w.repo),
        h('span', { style: mono }, w.branch), h('span', { style: { color: w.unpushed ? 'var(--ui-accent)' : 'var(--ui-text-tertiary)' } },
        `${w.unpushed} unpushed`), h('span', { style: { color: w.dirty ? 'var(--ui-warning, #c98a00)' : 'var(--ui-text-tertiary)' } }, `${w.dirty} dirty`),
        h('span', { style: sub }, w.dir))), !(t.worktrees || []).length ? h('div', { style: sub }, 'none') : null),
      t.qa && t.qa.dir ? h('div', { style: sub }, `QA: ${t.qa.runs} run(s), ${Math.round(t.qa.size / 1000)} KB · ${t.qa.dir}`) : null))
}
function Tickets() {
  const q = useQuery({ queryKey: ['cockpit', 'tickets'], queryFn: () => CTX.rest('/tickets'), refetchInterval: 30000, retry: 1 })
  const qc = useQueryClient()
  const [selected, setSelected] = useState(null)
  const [showAll, setShowAll] = useState(false)
  if (q.isLoading) return h('div', { className: 'p-3 text-xs', style: sub }, 'loading')
  if (q.error) return h('div', { className: 'p-3 text-xs', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error))
  const all = q.data.tickets || []
  const rows = showAll ? all : all.filter((t) => t.phase !== 'evidence only')
  const refresh = () => qc.invalidateQueries({ queryKey: ['cockpit'] })
  return h(SplitList, { cols: TICKET_COLS, labels: ['ticket', 'flow', 'status', 'cards', '>duration', 'worktrees (unpushed↑ dirty✎)', 'slot',
    'outbox · qa', h('label', { className: 'flex items-center justify-end gap-1 cursor-pointer normal-case tracking-normal',
    title: 'tickets that only have evidence folders' }, h('input', { type: 'checkbox', checked: showAll, onChange: (e) => setShowAll(e.target.checked) }),
    'all')],
    rows, selected, onSelect: setSelected, empty: 'No tickets in flight on this machine.',
    renderRow: (t) => { const ic = t.intents || {}; const cc = t.cards || {}
      return trow(TICKET_COLS, { key: t.ticket, onClick: () => setSelected(selected === t.ticket ? null : t.ticket), selected: selected === t.ticket, children: [
        h('div', { key: 't', className: 'font-medium truncate', title: t.summary || '' }, t.ticket, t.summary ? h('span', { className: 'font-normal', style: sub }, ' ' + t.summary) : null),
        h('div', { key: 'f', className: 'truncate', style: sub, title: (t.flows || []).length > 1 ? 'flows, in order: ' + t.flows.join(' → ') : 'the flow the ticket came from' }, t.flow ? t.flow + ((t.flows || []).length > 1 ? ` +${t.flows.length - 1}` : '') : '–'),
        h('div', { key: 'p', className: 'truncate', style: { color: phaseColor(t.phase) } }, t.phase),
        h('div', { key: 'c', title: Object.entries(cc).map(([k, v]) => `${k}: ${v}`).join(', ') }, t.cards_total ? `${t.cards_open}/${t.cards_total}` + (cc.blocked ? ' ⚠' : '') : '–'),
        h('div', { key: 'd', className: 'text-right', style: { fontVariantNumeric: 'tabular-nums',
          color: t.cards_open ? 'var(--ui-accent)' : undefined }, title: t.started ? `${t.cards_open ? 'running' : 'ran'} since ${t.started.replace('T', ' ').slice(0, 16)}${t.ended ? ' until ' + t.ended.replace('T', ' ').slice(0, 16) : ''} · the lanes' run time ${fmtDur(t.run_s)}` : 'no card yet' },
          t.started ? fmtDur(t.duration_s) : '–'),
        h('div', { key: 'w', className: 'truncate' }, (t.worktrees || []).length ? (t.worktrees || []).map((w) => h('span',
          { key: w.repo, className: 'mr-2' }, h('span', { style: mono }, w.repo),
          h('span', { style: { color: w.unpushed ? 'var(--ui-accent)' : 'var(--ui-text-tertiary)' } }, ` ${w.unpushed}↑`),
          w.dirty ? h('span', { style: { color: 'var(--ui-warning, #c98a00)' } }, ` ${w.dirty}✎`) : null)) : h('span', { style: sub }, '–')),
        h('div', { key: 's', style: sub }, t.slot ? `${t.slot.slot} ${t.slot.owner === 'human' ? '👤' : ''}` : '–'),
        h('div', { key: 'o', className: 'truncate', title: 'outbox open/total · endorsed ✓ · published ↗ · qa runs' }, t.intents_total ? `${t.intents_open}/${t.intents_total}` + (ic.endorsed ? ` ${ic.endorsed}✓` : '') + (ic.published ? ` ${ic.published}↗` : '') : '–', h('span', { style: sub }, t.qa && t.qa.runs ? ` · qa ${t.qa.runs}` : '')),
        h('div', { key: 'a', className: 'text-right truncate', style: sub }, t.last_card ? ago(t.last_card) : '')] }) },
    detail: selected ? h(TicketDetail, { ticket: selected, refresh }) : null })
}

export { Tickets, TicketDetail, PlanView, phaseColor, TICKET_COLS }
