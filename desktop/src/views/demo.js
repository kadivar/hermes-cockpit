// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { ChatButton } from './chat.js'
import { copyBtn, CredRows } from '../lib/secret.js'
import { host, useQuery, useQueryClient, CTX, h, sub, mono, stroke, btn, selectBox, post, ago, Section, openIde, openWeb } from '../lib/sdk.js'

// a staging Test run's demo (qa/<T>/demo.json with env: staging): the record the tester prepared, the steps that are yours,
// and the test account's login from the vault, shown to you only
function StagingDemo({ d }) {
  const open = (url) => openWeb(url)
  const steps = d.steps || []
  const apps = d.apps || []
  return h(Section, { title: 'Demo · staging', open: steps.length > 0, extra: (d.links || []).slice(0, 2).map((l) => h('button', { key: l.url, type: 'button', onClick: () => open(l.url), title: l.url, className: 'rounded px-1.5 py-0.5 text-[0.6875rem]', style: { border: `1px solid ${stroke}`, color: 'var(--ui-accent)' } }, 'open ' + (l.label || 'link'))) },
    h('div', { className: 'cockpit-staging flex flex-col gap-3 text-xs' },
      apps.length ? h('div', { className: 'flex flex-wrap gap-3' }, ...apps.map((a) => h('span', { key: a.name, className: 'flex items-center gap-1' }, h('span', { style: { color: a.up ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-text-quaternary)' } }, a.up ? '●' : '○'), a.name))) : null,
      (d.links || []).length ? h('div', { className: 'grid items-center gap-x-3 gap-y-1', style: { gridTemplateColumns: '12rem 1fr auto' } },
        ...d.links.flatMap((l) => [h('span', { key: l.url + 'l' }, l.label), h('a', { key: l.url + 'u', href: l.url, onClick: (e) => { e.preventDefault(); open(l.url) }, className: 'truncate', style: { ...mono, color: 'var(--ui-accent)' } }, l.url), h('span', { key: l.url + 'c', className: 'flex justify-end' }, copyBtn(l.url, 'link'))]))
        : h('div', { style: sub }, 'no link recorded yet'),
      steps.length ? h('div', { className: 'flex flex-col gap-1 rounded border px-2.5 py-2', style: { borderColor: 'var(--ui-warning, #c98a00)' } }, h('div', { className: 'cockpit-head', style: { color: 'var(--ui-warning, #c98a00)' } }, 'your steps'),
        h('ol', { className: 'list-decimal pl-5 flex flex-col gap-0.5' }, ...steps.map((s, i) => h('li', { key: i }, s)))) : null,
      h('div', { className: 'flex flex-col gap-1 rounded border px-2.5 py-2', style: { borderColor: stroke } },
        h('div', { className: 'cockpit-head' }, 'login on staging (the test account)'),
        d.login ? h(CredRows, { username: d.login.username, password: d.login.password }) : h('div', { style: { color: 'var(--ui-warning, #c98a00)' } }, d.login_error || 'no login'),
        h('div', { style: sub }, 'One browser session is shared across these origins. A staging test account only.')),
      d.notes ? h('div', { style: sub }, d.notes) : null))
}

// the human's open manual session on this ticket: the slot's apps (click opens, copy copies) and a login picker (the pack's
// default preselected); "Get password" sets one on the slot's own data copy and shows it like the demo card
export function SessionCard({ ticket }) {
  const q = useQuery({ queryKey: ['cockpit', 'session-card', ticket], queryFn: () => CTX.rest('/session-card?ticket=' + encodeURIComponent(ticket)), refetchInterval: 20000, retry: 0, enabled: Boolean(ticket) })
  const [pick, setPick] = useState('')
  const [cred, setCred] = useState(null)
  const [busy, setBusy] = useState(false)
  const d = q.data
  if (!ticket || !d || !d.open) return null
  const label = pick || d.default
  const chosen = (d.logins || []).find((l) => l.label === label)
  const held = d.current && chosen && d.current.username === chosen.user ? { username: d.current.username, password: d.current.password } : null
  const shown = cred && cred.label === label ? cred : held
  const get = async () => {
    if (!chosen) return
    setBusy(true)
    try { const r = await post('/session-login', { ticket, slot: d.slot, user: chosen.user }); setCred({ label, username: r.user, password: r.password }) } catch (e) { host.notifyError(e, 'login failed') } finally { setBusy(false) }
  }
  const open = (url) => openWeb(url)
  return h(Section, { title: `Manual session · slot ${d.slot}`, open: true },
    h('div', { className: 'flex flex-col gap-3 text-xs', 'data-session-card': d.slot },
      h('div', { className: 'grid items-center gap-x-3 gap-y-1', style: { gridTemplateColumns: '9rem 1fr auto' } },
        ...(d.apps || []).flatMap((a) => [
          h('span', { key: a.name + 'n' }, a.name),
          h('a', { key: a.name + 'u', href: a.url, onClick: (e) => { e.preventDefault(); open(a.url) }, className: 'truncate', style: { ...mono, color: 'var(--ui-accent)' } }, a.url),
          h('span', { key: a.name + 'b', className: 'flex justify-end' }, copyBtn(a.url, a.name + ' URL'))])),
      (d.logins || []).length ? h('div', { className: 'flex flex-col gap-1 rounded border px-2.5 py-2', style: { borderColor: stroke } },
        h('div', { className: 'flex items-center gap-2' },
          h('span', { className: 'cockpit-head' }, 'login on the slot'),
          selectBox(label, setPick, d.logins.map((l) => [l.label, `${l.label} · ${l.user}`])),
          h('span', { className: 'ml-auto' }, btn(busy ? 'working…' : 'Get password', get, { title: 'set a password for this user on the slot database only' }))),
        shown ? h(CredRows, { username: shown.username, password: shown.password }) : h('div', { style: sub }, 'no password yet for this user: Get password')) : null))
}

// the ticket's slot as a demo: open the apps, log in with the slot's demo account, follow the lanes' deep links
export function DemoSection({ ticket }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['cockpit', 'demo', ticket], queryFn: () => CTX.rest('/demo?ticket=' + encodeURIComponent(ticket)), refetchInterval: 20000, retry: 0, enabled: Boolean(ticket) })
  const [busy, setBusy] = useState('')
  const d = q.data
  if (ticket && d && d.env === 'staging') return h(StagingDemo, { d })
  if (!ticket || !d || !d.slot) return null
  const refresh = () => qc.invalidateQueries({ queryKey: ['cockpit', 'demo', ticket] })
  const open = (url) => openWeb(url)
  const upApps = (d.apps || []).filter((a) => a.up && a.name !== 'API')
  const act = async (key, path, body, msg) => { setBusy(key); try { const r = await post(path, body); host.notify({ kind: 'success', message: msg || (r && r.out) || 'done' }); refresh() } catch (e) { host.notifyError(e, 'failed') } finally { setBusy('') } }
  const login = d.login
  return h(Section, { title: `Demo · slot ${d.slot}`, extra: upApps.map((a) => h('button', { key: a.name, type: 'button', onClick: () => open(a.url), title: a.url, className: 'rounded px-1.5 py-0.5 text-[0.6875rem]', style: { border: `1px solid ${stroke}`, color: 'var(--ui-accent)' } }, a.name + ' ↗')) },
    h('div', { className: 'flex flex-col gap-3 text-xs' },
      h('div', { className: 'grid items-center gap-x-3 gap-y-1', style: { gridTemplateColumns: '9rem 1fr auto' } },
        ...(d.apps || []).flatMap((a) => [
          h('span', { key: a.name + 'n', className: 'flex items-center gap-1.5' }, h('span', { style: { color: a.up ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-text-quaternary)' } }, a.up ? '●' : '○'), a.name),
          a.up ? h('a', { key: a.name + 'u', href: a.url, onClick: (e) => { e.preventDefault(); open(a.url) }, className: 'truncate', style: { ...mono, color: 'var(--ui-accent)' } }, a.url) : h('span', { key: a.name + 'u', className: 'truncate', style: { ...mono, color: 'var(--ui-text-tertiary)' } }, a.url),
          h('span', { key: a.name + 'b', className: 'flex justify-end gap-1' }, a.up ? copyBtn(a.url, a.name + ' URL')
            : a.name === 'API' ? h('span', { style: sub }, 'slot stack down')
            : a.worktree ? btn(busy === a.repo ? 'starting…' : 'Start', () => act(a.repo, '/demo-start', { ticket, repo: a.repo, slot: d.slot }, `${a.name} starting on slot ${d.slot} (about a minute)`), { title: `cockpit slot start ${d.slot} ${a.repo}` })
            : h('span', { style: sub }, 'no worktree'))])),
      h('div', { className: 'flex flex-col gap-1 rounded border px-2.5 py-2', style: { borderColor: stroke } },
        h('div', { className: 'cockpit-head' }, 'login on the slot (its own data copy)'),
        login ? h(CredRows, { username: login.username, password: login.password })
          : h('div', { style: { color: 'var(--ui-warning, #c98a00)' } }, d.login_error || 'no login yet'),
        login && login.twofa ? h('div', { style: { color: 'var(--ui-warning, #c98a00)' } }, 'This user has 2FA enabled: the login asks for a code.') : null,
        h('div', { className: 'flex items-center gap-2', style: sub },
          login && login.set_at ? h('span', null, `set ${ago(login.set_at)} ago on slot ${d.slot}; a slot reset restores the original`) : null,
          h('span', { className: 'ml-auto' }, btn(busy === 'login' ? 'working…' : 'New password', () => act('login', '/demo-login', { ticket, user: (login && login.username) || d.account || '', slot: d.slot }, 'new demo password set on the slot'), { title: 'set a fresh password for this user on the slot database only' })))),
      (d.links || []).length ? h('div', { className: 'flex flex-col gap-1' }, h('div', { className: 'cockpit-head' }, 'where to look (recorded by the lanes)'),
        ...d.links.map((l, i) => h('div', { key: i, className: 'flex items-center gap-2' }, h('a', { href: l.url, onClick: (e) => { e.preventDefault(); open(l.url) }, style: { color: 'var(--ui-accent)' } }, l.label + ' ↗'), h('span', { className: 'truncate', style: { ...mono, ...sub } }, l.url)))) : null,
      d.notes ? h('div', { style: sub }, d.notes) : null))
}

// the ticket id a card or intent belongs to ("TASK-132: …" titles)
export const ticketOf = (title) => ((title || '').match(/^\s*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)/) || [])[1] || ''

// the lane card an intent came from (its coding session is the best one to chat in), when the intent recorded one
export const intentCard = (r) => (r && r.card_id && /^t_[0-9a-f]+$/.test(r.card_id) ? r.card_id : undefined)

// the one place every pane gets its ticket tools from. Two parts, same position on every pane: `chat` above the Brief
// (Chat, attached to the best session by itself), `demo` right under it (the Demo card).
export function TicketTools({ ticket, card, part }) {
  if (!ticket) return null
  // every pane of a ticket: the chat, Open IDE (the ticket's worktrees; a ticket without one says so), the ticket
  if (part === 'chat') return h('div', { className: 'flex flex-wrap items-center gap-2' }, h(ChatButton, { ticket, card }),
    btn('Open IDE', () => openIde({ ticket }), { title: 'the IDE on the ticket\'s worktrees: every repo of this ticket, bound to its slot' }),
    h('span', { className: 'text-xs', style: sub }, `${ticket}${card ? ' · ' + card : ''}`))
  return h('div', { className: 'flex flex-col gap-3' }, h(SessionCard, { ticket }), h(DemoSection, { ticket }))
}
