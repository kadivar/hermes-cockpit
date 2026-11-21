// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// the Vault page: the human's vaults on the left, a vault's records in the middle, one record on the right
import { useState } from 'react'
import { host, useQuery, useQueryClient, CTX, h, sub, mono, stroke, btn, seg, selectBox, post, ago, SplitList, trow, detailHead, Section } from '../lib/sdk.js'
import { copyBtn, SecretField } from '../lib/secret.js'
import { RecordForm } from './vault-record.js'

const DANGER = 'var(--ui-danger, #d33)'
const COLS = '5.5rem minmax(0,1.4fr) minmax(0,1.4fr) minmax(0,1fr) 4rem'
const q = (o) => Object.entries(o).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')

// a destructive act asks inline first and sends the name or id back as `confirm`
export function Danger({ label, what, explain, run }) {
  const [ask, setAsk] = useState(false)
  if (!ask) return btn(label, () => setAsk(true), { danger: true })
  return h('div', { className: 'flex flex-col gap-1 rounded border px-2 py-1.5 text-xs', style: { borderColor: DANGER } },
    h('div', null, explain),
    h('div', { className: 'flex items-center gap-2' },
      h('button', { type: 'button', onClick: () => { setAsk(false); run() }, className: 'rounded px-2 py-0.5 text-xs font-medium', style: { background: DANGER, color: '#fff' } }, `Delete ${what} now`),
      btn('Cancel', () => setAsk(false))))
}

export function RecordDetail({ vault, id, state, vaults, placed, onEdit, onGone }) {
  const qc = useQueryClient()
  const d = useQuery({ queryKey: ['cockpit', 'vault-record', vault, id], queryFn: () => CTX.rest(`/vault-record?${q({ vault, id })}`), retry: 0 })
  const [to, setTo] = useState('')
  if (d.error) return h('div', { className: 'p-3 text-xs', style: { color: DANGER } }, String(d.error.message || d.error))
  if (!d.data) return h('div', { className: 'p-3 text-xs', style: sub }, 'loading')
  const r = d.data.record; const kind = (state.kinds || []).find((k) => k.name === r.kind) || { label: r.kind, secret_label: 'secret' }
  const refresh = () => qc.invalidateQueries({ queryKey: ['cockpit'] })
  const reveal = (field, index) => () => post('/vault-reveal', { vault, id, field, ...(index === undefined ? {} : { index }) })
  const act = async (path, body, title, gone) => { try { const x = await post(path, body); host.notify({ kind: 'success', title, message: x.out }); refresh(); if (gone) onGone() } catch (e) { host.notifyError(e, `${title} failed`) } }
  const off = state.locked; const why = state.reason; const card = (state.key || {}).needs === 'card'
  const SF = (props) => h(SecretField, { ...props, disabled: off, why, card })
  const row = (label, value) => [h('span', { key: 'l' + label, style: sub }, label), value]
  const rows = [
    ...row('type', h('span', null, kind.label)),
    ...(r.origin ? row(r.kind === 'login' ? 'website' : 'service', h('span', { className: 'flex items-center gap-2' }, h('span', { style: mono }, r.origin), copyBtn(r.origin, 'website'))) : []),
    ...(r.email ? row('username', h('span', { className: 'flex items-center gap-2' }, h('span', { style: mono }, r.email), copyBtn(r.email, 'username'))) : []),
    ...(r.has_secret ? row(kind.secret_label, SF({ label: kind.secret_label, reveal: reveal('secret'), multiline: r.kind === 'note' })) : []),
    ...(r.two_factor ? row('2FA code', SF({ label: '2FA code', reveal: reveal('code') })) : []),
    ...(r.two_factor ? row('2FA key', SF({ label: '2FA key', reveal: reveal('otp') })) : []),
    ...(r.has_notes ? row('notes', SF({ label: 'notes', reveal: reveal('notes'), multiline: true })) : []),
    ...(r.lane ? row('lane', h('span', null, r.lane)) : []),
    ...row('tags', r.tags && r.tags.length ? h('span', { className: 'flex flex-wrap gap-1' }, ...r.tags.map((t) => h('span', { key: t, className: 'rounded border px-1.5', style: { borderColor: stroke } }, t))) : h('span', { style: sub }, 'none')),
    ...row('changed', h('span', { style: sub }, `${ago(r.updated)} ago · created ${ago(r.created)} ago`)),
  ]
  const others = vaults.filter((v) => v.name !== vault)
  return h('div', { className: 'flex flex-col gap-2 p-3 text-xs' },
    detailHead(r.title, null, vault),
    off ? h('div', { style: { color: 'var(--ui-warning, #c98a00)' } }, why) : null,
    h('div', { className: 'grid items-center gap-x-3 gap-y-1.5', style: { gridTemplateColumns: '6rem 1fr' } }, ...rows),
    placed ? h(Section, { title: `On seats (${d.data.seats.length})`, open: true }, d.data.seats.length
      ? h('div', { className: 'flex flex-col gap-0.5' }, ...d.data.seats.map((s) => h('div', { key: s.lane + s.kind }, `${s.lane} · ${s.kind === 'shared' ? 'shared' : 'its own login'}`)), h('div', { style: sub }, 'Cockpit keeps these copies in step when you save, move or delete.'))
      : h('div', { style: sub }, 'no seat holds a copy')) : null,
    r.history.length ? h(Section, { title: `Previous passwords (${r.history.length})` }, h('div', { className: 'flex flex-col gap-1' }, ...r.history.map((x, i) => h('div', { key: i, className: 'flex items-center gap-3' }, h('span', { style: sub }, `replaced ${ago(x.until)} ago`), SF({ label: 'old password', reveal: reveal('history', i) }))).reverse())) : null,
    d.data.audit.length ? h(Section, { title: 'Activity' }, h('div', { className: 'flex flex-col gap-0.5' }, ...d.data.audit.map((a, i) => h('div', { key: i, style: sub }, `${ago(a.at)} ago · ${a.act}${a.field ? ' ' + a.field : ''}`)))) : null,
    h('div', { className: 'flex flex-wrap items-center gap-2 pt-1' },
      btn('Edit', onEdit, { accent: true }),
      others.length ? h('span', { className: 'flex items-center gap-1' },
        selectBox(to, setTo, [['', 'Move to…'], ...others.map((v) => [v.name, v.title])]),
        to ? btn('Move', () => act('/vault-move', { vault, id, to }, 'Move', true)) : null) : null,
      h(Danger, { label: 'Delete', what: r.title, explain: `${r.title} is removed from this vault${placed ? ' and from every seat that holds it' : ''}. Its old passwords go with it.`, run: () => act('/vault-record-delete', { vault, id, confirm: id }, 'Delete', true) })))
}

// the key behind the vault: open, locked (Unlock takes the passphrase or the card's PIN, once; gpg-agent keeps it for its
// cache time), on a security key (Show may wait for a touch), or on another machine. Nothing here stores the passphrase.
const KEY_TEXT = { '': 'vault key open on this machine', passphrase: 'vault key locked', card: 'vault key on a security key', elsewhere: 'private key not on this machine', unsealed: 'vault not sealed' }
export function KeyBar({ state, refresh }) {
  const key = state.key || {}
  const [open, setOpen] = useState(false); const [secret, setSecret] = useState(''); const [busy, setBusy] = useState(false)
  const unlock = async () => {
    if (!secret || busy) return; setBusy(true)
    try { const r = await CTX.rest('/vault-unlock', { method: 'POST', body: { secret } }); host.notify({ kind: 'success', title: 'Vault', message: r.out }); setOpen(false); refresh() }
    catch (e) { host.notifyError(e, 'unlock failed') } finally { setSecret(''); setBusy(false) }   // the passphrase never outlives the request
  }
  const act = async (path, title) => { try { const r = await post(path, {}); host.notify({ kind: 'info', title: 'Vault', message: r.out }); refresh() } catch (e) { host.notifyError(e, `${title} failed`) } }
  const mins = (s) => (s >= 60 ? `${Math.round(s / 60)} min` : `${s}s`)
  const canUnlock = key.needs === 'passphrase' || key.needs === 'card'
  const color = key.needs === '' ? 'var(--ui-success, #2a9d5c)' : key.needs === 'card' ? 'var(--ui-text-secondary)' : 'var(--ui-warning, #c98a00)'
  return h('div', { className: 'cockpit-vault-key flex flex-wrap items-center gap-2 border-b px-3 py-1 text-[0.6875rem]', style: { borderColor: stroke } },
    h('span', { style: { color } }, key.needs === '' && key.protected ? 'vault key unlocked' : KEY_TEXT[key.needs] ?? ''),
    state.reason ? h('span', { style: sub }, state.reason) : null,
    key.protected && key.ttl && key.ttl.idle ? h('span', { style: sub }, `gpg-agent keeps an unlock ${mins(key.ttl.idle)} after last use, ${mins(key.ttl.max)} at most`) : null,
    h('span', { className: 'ml-auto flex items-center gap-1' },
      canUnlock && !open ? btn(key.needs === 'card' ? 'Enter PIN' : 'Unlock', () => setOpen(true), { accent: true, title: 'handed to gpg once; gpg-agent caches it, cockpit keeps nothing. In a terminal: cockpit vault unlock' }) : null,
      (key.protected && key.cached) || key.needs === 'card' ? btn('Lock', () => act('/vault-lock', 'lock'), { title: 'gpg-agent forgets the passphrase (a security key asks for its PIN again)' }) : null,
      key.needs === '' || key.needs === 'card' ? btn('Re-read vault', () => act('/vault-reindex', 're-read'), { title: 'open every file and rebuild the list (a security key may want one touch per file)' }) : null),
    open ? h('div', { className: 'flex w-full items-center gap-2 pt-1' },
      h('input', { type: 'password', value: secret, onChange: (e) => setSecret(e.target.value), onKeyDown: (e) => { if (e.key === 'Enter') unlock() }, autoComplete: 'off', autoFocus: true, spellCheck: false,
        placeholder: key.needs === 'card' ? 'security key PIN' : 'vault key passphrase', className: 'w-64 rounded border bg-transparent px-2 py-0.5 text-xs', style: { borderColor: stroke } }),
      h('button', { type: 'button', disabled: !secret || busy, onClick: unlock, className: 'rounded px-2.5 py-0.5 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? (key.needs === 'card' ? 'touch your key if it blinks…' : 'working') : 'Unlock'),
      btn('Cancel', () => { setSecret(''); setOpen(false) })) : null)
}

function VaultRail({ vaults, vault, setVault, refresh }) {
  const [adding, setAdding] = useState(false); const [name, setName] = useState(''); const [renaming, setRenaming] = useState(false); const [to, setTo] = useState('')
  const act = async (path, body, title) => { try { const x = await post(path, body); host.notify({ kind: 'success', title, message: x.out }); refresh(); return true } catch (e) { host.notifyError(e, `${title} failed`); return false } }
  const current = vaults.find((v) => v.name === vault)
  const input = (value, set, go) => h('input', { value, onChange: (e) => set(e.target.value), onKeyDown: (e) => { if (e.key === 'Enter') go() }, autoFocus: true, className: 'w-full rounded border bg-transparent px-1.5 py-0.5 text-xs', style: { borderColor: stroke } })
  return h('div', { className: 'flex w-52 shrink-0 flex-col gap-1 border-r p-2 text-xs', style: { borderColor: stroke } },
    h('div', { className: 'cockpit-head' }, 'Vaults'),
    ...vaults.map((v) => h('div', { key: v.name, onClick: () => setVault(v.name), className: 'cockpit-row flex cursor-pointer items-center gap-2 rounded px-2 py-1', style: { background: v.name === vault ? 'var(--ui-bg-selected, rgba(127,127,127,.15))' : 'transparent' } },
      h('span', { className: 'min-w-0 flex-1 truncate', title: v.name }, v.title), v.builtin ? h('span', { style: sub, title: 'named by the pack; cannot be renamed or deleted' }, '🔒') : null, h('span', { style: sub }, v.count))),
    adding ? h('div', { className: 'flex flex-col gap-1' }, input(name, setName, async () => { if (await act('/vault-create', { name }, 'New vault')) { setVault(name); setAdding(false); setName('') } }), h('div', { style: sub }, 'letters, digits, - and _'), btn('Cancel', () => setAdding(false)))
      : btn('+ New vault', () => setAdding(true)),
    current && !current.builtin ? h('div', { className: 'mt-2 flex flex-col gap-1 border-t pt-2', style: { borderColor: stroke } },
      renaming ? h('div', { className: 'flex flex-col gap-1' }, input(to, setTo, async () => { if (await act('/vault-rename', { name: vault, to }, 'Rename')) { setVault(to); setRenaming(false) } }), btn('Cancel', () => setRenaming(false)))
        : btn('Rename vault', () => { setTo(vault); setRenaming(true) }),
      h(Danger, { label: 'Delete vault', what: current.title, explain: current.count ? `${current.title} holds ${current.count} record${current.count === 1 ? '' : 's'}. Deleting the vault removes them all.` : `${current.title} is empty.`, run: async () => { if (await act('/vault-delete', { name: vault, confirm: vault, force: current.count > 0 }, 'Delete vault')) setVault('') } })) : null)
}

export function Vault() {
  const qc = useQueryClient()
  const vq = useQuery({ queryKey: ['cockpit', 'vaults'], queryFn: () => CTX.rest('/vaults'), refetchInterval: 20000, retry: 1 })
  const [vault, setVaultRaw] = useState(() => CTX.storage.get('vault.current', ''))
  const setVault = (v) => { setVaultRaw(v); CTX.storage.set('vault.current', v); setSel(null); setMode(null) }
  const [query, setQuery] = useState(''); const [kind, setKind] = useState(''); const [tag, setTag] = useState('')
  const [sel, setSel] = useState(null); const [mode, setMode] = useState(null)   // mode: 'new' | 'edit' | null
  const vaults = (vq.data && vq.data.vaults) || []
  const active = vaults.find((v) => v.name === vault) || vaults[0]
  const name = active ? active.name : ''
  const rq = useQuery({ queryKey: ['cockpit', 'vault-records', name, query, kind, tag], queryFn: () => CTX.rest(`/vault-records?${q({ vault: name, q: query, kind, tag })}`), enabled: Boolean(name), refetchInterval: 20000, retry: 1 })
  const refresh = () => qc.invalidateQueries({ queryKey: ['cockpit'] })
  if (vq.error) return h('div', { className: 'p-3 text-xs', style: { color: DANGER } }, String(vq.error.message || vq.error))
  if (!vq.data) return h('div', { className: 'p-3 text-xs', style: sub }, 'loading')
  const state = vq.data
  const records = (rq.data && rq.data.records) || []
  const tags = (rq.data && rq.data.tags) || []
  const rec = records.find((r) => r.id === sel)
  const kinds = state.kinds || []
  const detail = mode === 'new' ? h(RecordForm, { key: 'new', vault: name, kinds, placed: active.placed, onDone: (id) => { setMode(null); setSel(id) }, onCancel: () => setMode(null) })
    : mode === 'edit' && rec ? h(RecordForm, { key: rec.id, vault: name, kinds, record: rec, placed: active.placed, onDone: () => setMode(null), onCancel: () => setMode(null) })
    : sel ? h(RecordDetail, { key: sel, vault: name, id: sel, state, vaults, placed: active.placed, onEdit: () => setMode('edit'), onGone: () => setSel(null) }) : null
  const label = (k) => (kinds.find((x) => x.name === k) || { label: k }).label
  return h('div', { className: 'flex min-h-0 flex-1', 'data-vault': '1' },
    h(VaultRail, { vaults, vault: name, setVault, refresh }),
    h('div', { className: 'flex min-h-0 min-w-0 flex-1 flex-col' },
      h(KeyBar, { state, refresh }),
      state.legacy ? h('div', { className: 'px-3 py-1 text-[0.6875rem]', style: { color: 'var(--ui-warning, #c98a00)' } }, 'Your logins are still in the older single-file store. Re-read vault moves them into the vaults (the lanes read the same logins afterwards).') : null,
      rq.data && rq.data.unread ? h('div', { className: 'px-3 py-1 text-[0.6875rem]', style: sub }, `${rq.data.unread} file${rq.data.unread === 1 ? '' : 's'} in this vault not read yet: unlock, or Re-read vault, to list ${rq.data.unread === 1 ? 'it' : 'them'}.`) : null,
      h('div', { className: 'flex flex-wrap items-center gap-2 border-b px-3 py-1.5', style: { borderColor: stroke } },
        h('input', { value: query, onChange: (e) => setQuery(e.target.value), placeholder: 'Search title, website, username, tag', className: 'w-64 rounded border bg-transparent px-2 py-0.5 text-xs', style: { borderColor: stroke } }),
        h('div', { className: 'flex items-center gap-1 rounded border p-0.5', style: { borderColor: stroke } }, seg(kind, '', 'All', setKind), ...kinds.map((k) => seg(kind, k.name, k.label, setKind))),
        tags.length ? selectBox(tag, setTag, [['', 'Any tag'], ...tags.map((t) => [t, t])]) : null,
        h('div', { className: 'ml-auto' }, btn('+ New record', () => { setSel(null); setMode('new') }, { accent: true }))),
      h(SplitList, {
        cols: COLS, labels: ['type', 'title', 'username / website', 'tags', '>changed'], rows: records, selected: sel || mode, onSelect: (v) => { setSel(v); setMode(null) },
        onClose: () => { setSel(null); setMode(null) }, detailWidth: '52%',
        empty: query || kind || tag ? 'no record matches' : `${active ? active.title : 'this vault'} is empty — add the first record`,
        renderRow: (r) => trow(COLS, { key: r.id, onClick: () => { setSel(r.id); setMode(null) }, selected: r.id === sel, children: [
          h('span', { style: sub }, label(r.kind)), h('span', { className: 'truncate font-medium' }, r.title), h('span', { className: 'truncate', style: mono }, r.email || r.origin || ''),
          h('span', { className: 'truncate', style: sub }, (r.tags || []).join(', ')), h('span', { className: 'text-right', style: sub }, ago(r.updated))] }),
        detail })))
}
