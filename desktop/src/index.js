// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// Cockpit desktop page: inbox, outbox gate, live view, tickets, evidence.
// Reads through the plugin backend. Hold and drop happen here. Publish runs only after the human confirms.
// npm run build writes plugin.js, the file the host loads.
import { ROUTES_AREA, SIDEBAR_NAV_AREA, jsx, setCTX, CSS } from './lib/sdk.js'
import { OutboxPage, Chip } from './app.js'
import { startOverrides } from './lib/overrides.js'

export default {
  id: 'cockpit',
  name: 'Cockpit',
  defaultEnabled: true,
  register(ctx) {
    setCTX(ctx)
    const style = document.createElement('style'); style.setAttribute('data-plugin', 'cockpit'); style.textContent = CSS; document.head.appendChild(style)
    ctx.onDispose(() => style.remove())
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: '/cockpit' }, render: () => jsx(OutboxPage, {}) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, order: 61, data: { path: '/cockpit', label: 'Cockpit', codicon: 'dashboard' } },
      { id: 'chip', area: 'statusBar.right', order: 120, render: () => jsx(Chip, {}) }
    ])
    // the Desktop fixes the pack opts into (none unless it names them)
    startOverrides((path) => ctx.rest(path)).catch(() => {})
  }
}
