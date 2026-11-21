// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// Stand-in for @hermes/plugin-sdk under node: no host, no query cache. useQuery answers synchronously from the recorded fixtures
// (test/fixtures.json) so react-dom/server can render each view in one pass.
import { forwardRef, createElement } from 'react'

const fixtures = globalThis.__cockpitFixtures || {}
export const calls = { notify: [], notifyError: [], navigate: [], haptic: [], queries: [] }

export const host = {
  notify: (m) => calls.notify.push(m),
  notifyError: (e, m) => calls.notifyError.push([e, m]),
  navigate: (p) => calls.navigate.push(p),
}
export const haptic = (k) => calls.haptic.push(k)

const lookup = (queryKey, queryFn) => {
  const byKey = Array.isArray(queryKey) ? queryKey[1] : undefined
  if (byKey != null && Object.prototype.hasOwnProperty.call(fixtures, byKey)) return fixtures[byKey]
  // fall back to the url the query would fetch: run queryFn, the ctx.rest stub records the path
  globalThis.__cockpitLastRest = null
  try { const p = queryFn && queryFn(); if (p && typeof p.catch === 'function') p.catch(() => {}) } catch { /* ignored: the fixture lookup below decides */ }
  const path = (globalThis.__cockpitLastRest || '').replace(/^\//, '').split('?')[0]
  return Object.prototype.hasOwnProperty.call(fixtures, path) ? fixtures[path] : undefined
}
export function useQuery({ queryKey, queryFn, enabled = true }) {
  calls.queries.push(queryKey)
  if (!enabled) return { data: undefined, isLoading: false, error: null }
  return { data: lookup(queryKey, queryFn), isLoading: false, error: null }
}
export const useQueryClient = () => ({ invalidateQueries: () => {} })
export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar.nav'
export const SandboxedFrame = forwardRef(function SandboxedFrame(props, ref) {
  return createElement('iframe', { ...props, ref, 'data-sandboxed': 'true' })
})
