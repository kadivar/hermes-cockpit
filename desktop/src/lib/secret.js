// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// shared widgets for anything that shows a stored login: the copy button, the masked rows, and a field that opens a value only when asked
import { useState, useEffect, useRef } from 'react'
import { host, CTX, h, sub, mono, stroke } from './sdk.js'

// copy a value to the clipboard with a short confirmation
export const copy = async (text, what) => { try { await CTX.os.writeClipboard(text); host.notify({ kind: 'info', message: `${what} copied` }) } catch (e) { host.notifyError(e, 'copy failed') } }
export const copyBtn = (text, what) => h('button', { type: 'button', onClick: (e) => { e.stopPropagation(); copy(text, what) }, title: `copy ${what}`, className: 'rounded px-1.5 py-0.5 text-[0.6875rem]', style: { border: `1px solid ${stroke}`, color: 'var(--ui-accent)' } }, '⧉ copy')

// a login as label · value · copy rows, the password masked until shown (the slot card and the staging card share it)
export function CredRows({ username, password }) {
  const [show, setShow] = useState(false)
  return h('div', { className: 'grid items-center gap-x-3 gap-y-1', style: { gridTemplateColumns: '6rem 1fr auto' } },
    h('span', { style: sub }, 'username'), h('span', { style: mono }, username), copyBtn(username, 'username'),
    h('span', { style: sub }, 'password'), h('span', { style: mono }, show ? password : '•'.repeat(12), ' ', h('button', { type: 'button', onClick: () => setShow(!show), className: 'text-[0.6875rem]', style: { color: 'var(--ui-text-tertiary)' } }, show ? 'hide' : 'show')), copyBtn(password, 'password'))
}

const POOL = { letters: 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ', digits: '23456789', symbols: '!@#$%^&*-_=+?' }
// a random password from the browser's own generator; every class is used at least once
export const genPassword = (length = 20, symbols = true) => {
  const pools = [POOL.letters, POOL.digits, ...(symbols ? [POOL.symbols] : [])]
  const all = pools.join('')
  const pick = (set) => { const b = new Uint32Array(1); const max = Math.floor(0x100000000 / set.length) * set.length; do { crypto.getRandomValues(b) } while (b[0] >= max); return set[b[0] % set.length] }
  const out = pools.map(pick)
  while (out.length < length) out.push(pick(all))
  for (let i = out.length - 1; i > 0; i--) { const r = new Uint32Array(1); crypto.getRandomValues(r); const k = r[0] % (i + 1); [out[i], out[k]] = [out[k], out[i]] }
  return out.join('')
}

// one stored value, closed until asked: Show and Copy fetch it through `reveal` ({value, expires_in}), and it closes itself after the time the backend names
export function SecretField({ label, reveal, disabled, why, multiline, card }) {
  const [value, setValue] = useState(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)
  const hide = () => { clearTimeout(timer.current); setValue(null) }
  useEffect(() => hide, [])
  const open = async (keep) => {
    if (busy) return null
    setBusy(true)
    try {
      const r = await reveal()
      if (keep) { setValue(r.value); clearTimeout(timer.current); timer.current = setTimeout(hide, (r.expires_in || 30) * 1000) }
      return r.value
    } catch (e) { host.notifyError(e, `${label} could not be shown`); return null } finally { setBusy(false) }
  }
  const copyIt = async () => { const v = value !== null ? value : await open(false); if (v !== null && v !== undefined) await copy(v, label) }
  const off = Boolean(disabled)
  const small = { color: 'var(--ui-text-tertiary)' }
  return h('div', { className: 'flex items-start gap-2' },
    value !== null
      ? h('span', { style: { ...mono, whiteSpace: multiline ? 'pre-wrap' : 'normal', wordBreak: 'break-all' } }, value)
      : busy && card ? h('span', { style: { color: 'var(--ui-warning, #c98a00)' } }, 'touch your security key if it blinks…')
      : h('span', { style: mono }, '•'.repeat(12)),
    h('button', { type: 'button', disabled: off || busy, title: off ? why : '', onClick: () => (value !== null ? hide() : open(true)), className: 'text-[0.6875rem] disabled:opacity-40', style: small }, value !== null ? 'hide' : 'show'),
    h('button', { type: 'button', disabled: off || busy, title: off ? why : `copy ${label}`, onClick: copyIt, className: 'rounded px-1.5 py-0.5 text-[0.6875rem] disabled:opacity-40', style: { border: `1px solid ${stroke}`, color: 'var(--ui-accent)' } }, '⧉ copy'))
}
