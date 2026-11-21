// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// the form that creates or changes one record of a vault; the fields it shows come from the record's kind
import { useState } from 'react'
import { host, useQueryClient, CTX, h, sub, stroke, ClearableTextarea, btn, post } from '../lib/sdk.js'
import { genPassword } from '../lib/secret.js'

// kind -> [key, label, input kind]: mirrors cockpitlib.vault_book.KINDS; a secret or seed left blank on an edit keeps what is stored
export const KIND_FIELDS = {
  login: [['title', 'Title (optional)', 'text'], ['origin', 'Website (URL)', 'url'], ['email', 'Username', 'text'], ['secret', 'Password', 'secret'], ['otp', 'Authenticator key (2FA, optional)', 'secret'], ['lane', 'Lane that fills it (optional)', 'text']],
  key: [['title', 'Name', 'text'], ['origin', 'Service (URL, optional)', 'url'], ['secret', 'Key or token', 'secret']],
  note: [['title', 'Title', 'text'], ['secret', 'Note', 'area']],
}
const NEEDS = { login: ['origin', 'email'], key: ['title'], note: ['title'] }

export function RecordForm({ vault, kinds, record, placed, onDone, onCancel }) {
  const editing = Boolean(record)
  const [kind, setKind] = useState(record ? record.kind : 'login')
  const [f, setF] = useState(() => ({ title: record?.title || '', origin: record?.origin || '', email: record?.email || '', lane: record?.lane || '', tags: (record?.tags || []).join(', '), secret: '', otp: '', notes: '' }))
  const [notesTouched, setNotesTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }))
  const missing = NEEDS[kind].filter((k) => !String(f[k] || '').trim())
  const ok = missing.length === 0 && (editing || kind !== 'note' || f.secret.trim() || f.notes.trim())
  const loadNotes = async () => {
    try { const r = await post('/vault-reveal', { vault, id: record.id, field: 'notes' }); set('notes', r.value || ''); setNotesTouched(true) } catch (e) { host.notifyError(e, 'notes could not be loaded') }
  }
  const save = async () => {
    if (!ok || busy) return; setBusy(true)
    const body = { vault, kind, title: f.title, origin: f.origin, email: f.email, tags: f.tags, ...(placed && kind === 'login' ? { lane: f.lane } : {}) }
    if (editing) body.id = record.id
    if (f.secret) body.secret = f.secret
    if (f.otp) body.otp = f.otp.replace(/\s+/g, '')
    if (notesTouched) body.notes = f.notes
    try {
      const r = await post('/vault-save', body)
      host.notify({ kind: 'success', title: 'Vault', message: r.out })
      qc.invalidateQueries({ queryKey: ['cockpit'] })
      onDone(r.id)
    } catch (e) { host.notifyError(e, 'saving failed') } finally { setF((p) => ({ ...p, secret: '', otp: '' })); setBusy(false) }
  }
  const input = (props) => h('input', { ...props, className: 'w-full rounded border bg-transparent px-2 py-1 text-xs', style: { borderColor: stroke } })
  const field = ([k, label, type]) => h('label', { key: k, className: 'flex flex-col gap-0.5' }, h('span', { style: sub }, label + (editing && type === 'secret' ? ' — blank keeps it' : '')),
    type === 'area'
      ? h(ClearableTextarea, { rows: 6, value: f[k], onChange: (e) => set(k, e.target.value), autoComplete: 'off', spellCheck: false, className: 'rounded border bg-transparent px-2 py-1 text-xs', style: { borderColor: stroke } })
      : h('div', { className: 'flex items-center gap-1' }, input({ type: type === 'secret' ? 'password' : type === 'url' ? 'url' : 'text', value: f[k], onChange: (e) => set(k, e.target.value), autoComplete: type === 'secret' ? 'new-password' : 'off', spellCheck: false }),
        k === 'secret' && kind === 'login' ? btn('Generate', () => set('secret', genPassword()), { title: 'a random 20-character password' }) : null))
  return h('div', { className: 'cockpit-vault-form flex flex-col gap-2 p-3 text-xs' },
    h('div', { className: 'cockpit-head' }, editing ? `Change ${record.title}` : 'New record'),
    editing ? null : h('div', { className: 'flex items-center gap-1' }, ...(kinds || []).map((k) => btn(k.label, () => setKind(k.name), { accent: kind === k.name }))),
    ...KIND_FIELDS[kind].filter(([k]) => k !== 'lane' || placed).map(field),
    h('label', { className: 'flex flex-col gap-0.5' }, h('span', { style: sub }, 'Tags (comma separated)'), input({ type: 'text', value: f.tags, onChange: (e) => set('tags', e.target.value), autoComplete: 'off' })),
    kind === 'note' ? null : h('label', { className: 'flex flex-col gap-0.5' },
      h('span', { className: 'flex items-center gap-2', style: sub }, 'Notes', editing && record.has_notes && !notesTouched ? btn('Load current notes', loadNotes, { title: 'opens the stored notes (the reveal is logged)' }) : null, editing && record.has_notes && !notesTouched ? h('span', null, 'blank keeps them') : null),
      h(ClearableTextarea, { rows: 3, value: f.notes, onChange: (e) => { set('notes', e.target.value); setNotesTouched(true) }, spellCheck: false, className: 'rounded border bg-transparent px-2 py-1 text-xs', style: { borderColor: stroke } })),
    h('div', { style: sub }, 'Sealed to the vault key on this machine. The secret is never shown in a list and is cleared from this form after saving.'),
    h('div', { className: 'flex items-center gap-2' },
      h('button', { type: 'button', disabled: !ok || busy, onClick: save, className: 'rounded px-3 py-1 text-xs font-medium disabled:opacity-40', style: { background: 'var(--ui-accent)', color: '#fff' } }, busy ? 'working' : editing ? 'Save changes' : 'Add to vault'),
      btn('Cancel', onCancel)))
}
