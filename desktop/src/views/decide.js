// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { host, haptic, h, sub, stroke, ClearableTextarea, post, Section } from '../lib/sdk.js'
import { RichMd } from '../lib/markdown.js'
import { TicketTools, intentCard } from './demo.js'

// ---------- a gatekeeper hold with one question for the human: the answer is the whole act ----------
const WARN = 'var(--ui-warning, #c98a00)'

// the instruction the decision sends back to the lane: the answer first, the gatekeeper's mechanical rework under it
const decisionText = (hold, choice, note) => {
  const answer = [choice, (note || '').trim()].filter(Boolean).join(' — ')
  return [`Decision on "${(hold.ask || '').trim()}": ${answer}`, hold.rework ? `Also, from the gatekeeper's hold:\n${hold.rework.trim()}` : ''].filter(Boolean).join('\n\n')
}

// who checks the lane's work after the decision: a Send back of a push or PR queues a tester and a reviewer by itself
const afterNote = (r) => (['push-branch', 'pr-patch-apply', 'open-pr'].includes(r.type) ? 'a tester and a reviewer check the result, then the gatekeeper again' : 'the gatekeeper checks the result again')

function DecidePanel({ r, onDone }) {
  const hold = r.hold || {}; const options = hold.options || []; const hh = r.hold_html || {}
  const [choice, setChoice] = useState(''); const [note, setNote] = useState(''); const [busy, setBusy] = useState(false)
  const ready = Boolean(choice || note.trim())
  const send = async () => {
    if (!ready || busy) return
    haptic('tap'); setBusy(true)
    try { const res = await post('/return', { id: r.id, instruction: decisionText(hold, choice, note) }); host.notify({ kind: 'success', title: `${r.id}: decision sent to ${r.created_by || 'the lane'}`, message: res.out }); if (onDone) onDone() }
    catch (e) { host.notifyError(e, 'sending the decision failed') }
    finally { setBusy(false) }
  }
  return h('div', { className: 'cockpit-decide rounded border px-2.5 py-2 text-xs flex flex-col gap-2', style: { borderColor: WARN, background: 'rgba(201,138,0,.07)' } },
    // talk it through first: Chat, attached to the session of the lane that wrote this intent
    h(TicketTools, { ticket: r.ticket, card: intentCard(r), part: 'chat' }),
    h('div', { className: 'cockpit-head', style: { color: WARN } }, 'Your decision'),
    // the gatekeeper writes its ask and reason in markdown; the backend renders them (hold_html), older rows show the text
    hh.ask ? h(RichMd, { className: 'font-medium', html: hh.ask }) : h('div', { className: 'font-medium whitespace-pre-wrap' }, hold.ask),
    hold.reason ? h('div', { style: sub, className: 'flex gap-1' }, h('span', null, 'The gatekeeper:'), hh.reason ? h(RichMd, { html: hh.reason }) : h('span', null, hold.reason)) : null,
    options.length ? h('div', { className: 'flex flex-col gap-1', role: 'radiogroup' }, ...options.map((o, i) => h('label', { key: i, className: 'cockpit-decide-opt flex cursor-pointer items-start gap-1.5 rounded border px-2 py-1', style: { borderColor: choice === o ? 'var(--ui-accent)' : stroke } },
      h('input', { type: 'radio', name: 'cockpit-decide-' + r.id, checked: choice === o, onChange: () => setChoice(o), className: 'mt-0.5' }), h('span', null, o)))) : null,
    h(ClearableTextarea, { value: note, onChange: (e) => setNote(e.target.value), rows: 2, placeholder: options.length ? 'optional: a note for the lane' : 'your answer, in a line',
      className: 'min-w-0 rounded border bg-transparent px-1.5 py-0.5', style: { borderColor: stroke }, onKeyDown: (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send() } }),
    hold.rework ? h(Section, { title: 'What the lane also does after your answer' }, hh.rework ? h(RichMd, { html: hh.rework }) : h('div', { className: 'whitespace-pre-wrap' }, hold.rework)) : null,
    h('div', { className: 'flex flex-wrap items-center gap-2' },
      h('button', { type: 'button', disabled: !ready || busy, onClick: send, className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'working' : 'Send decision (⌘↵)'),
      h('span', { style: sub }, `It goes back to ${r.created_by || 'the lane'} with the rework; ${afterNote(r)}. Nothing leaves the machine.`)))
}

export { DecidePanel, decisionText }
