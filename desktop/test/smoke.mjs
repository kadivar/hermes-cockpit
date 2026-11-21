// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// Render smoke test: bundle src/ with the SDK stubbed, register the plugin with a stub context, render every view once with
// react-dom/server. A view passes when it renders without throwing and the output carries its title text.
import { build } from 'esbuild'
import { readFileSync, mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const fixtures = JSON.parse(readFileSync(path.join(here, 'fixtures.json'), 'utf8'))
globalThis.__cockpitFixtures = fixtures

// the bundle under test: same options as `npm run build`, with the SDK aliased to the stub; react stays external so the
// renderer and the page share one React
const outDir = path.join(root, '.tmp')
mkdirSync(outDir, { recursive: true })
const outfile = path.join(outDir, 'plugin.test.mjs')
await build({
  entryPoints: [path.join(root, 'src/index.js')],
  bundle: true, format: 'esm', outfile, target: 'es2022', logLevel: 'silent',
  external: ['react', 'react/jsx-runtime'],
  alias: { '@hermes/plugin-sdk': path.join(here, 'sdk-stub.js') },
})

// the host's DOM, as far as register() touches it
globalThis.document = { head: { appendChild() {} }, createElement: () => ({ setAttribute() {}, remove() {}, textContent: '' }) }

const restCalls = []
const ctx = {
  rest: (p, opts) => { globalThis.__cockpitLastRest = p; restCalls.push([p, opts]); const key = p.replace(/^\//, '').split('?')[0]; return Promise.resolve(fixtures[key] ?? {}) },
  storage: { get: (k, d) => d, set() {} },
  os: { openExternal() {}, revealPath() {}, notify() {}, writeClipboard() {} },
  onDispose() {},
  registered: [],
  registerMany(items) { this.registered.push(...items) },
}

const mod = await import(pathToFileURL(outfile).href)
const plugin = mod.default
if (!plugin || plugin.id !== 'cockpit' || typeof plugin.register !== 'function') throw new Error('plugin.js does not export the plugin object')
plugin.register(ctx)
const page = ctx.registered.find((x) => x.id === 'page')
const chip = ctx.registered.find((x) => x.id === 'chip')
if (!page || !chip) throw new Error('register() did not register the page and the chip')

// the view's title text in the toolbar, and one thing the fixture puts on the page
const views = {
  inbox: ['intake asks: Should a removed line change the total at once', 'In flight · ', 'Published today · ', 'Dropped · '],
  outbox: ['Gate tools', 'Inbox'],   // the stored "outbox" view opens the Inbox: the gate lives under the to-do now
  live: ['the bots at work: lane run logs and coding tool transcripts', 'all jobs (1)'],
  worktrees: ['every ticket this machine holds', 'at the gate'],
  board: ['Running', 'Fix the total colour on the PDF cover', 'show 2 done'],
  qa: ['every ticket with test runs under qa/', 'TASK-136'],
  platform: ['what the platform does, down to the code', 'Cross-cutting components'],
  usage: ['tokens and estimated cost: every lane and every coding tool run', 'provider plan windows'],
  vault: ['vaults and the logins, keys and notes they hold', 'Staging admin', 'Lane logins'],
}
// h() passes `key` inside the props object (pre-existing, fine in React 18); dev React logs one warning per keyed element. Everything else on console.error stays visible.
const consoleError = console.error
console.error = (...a) => { if (String(a[0]).includes('containing a "key" prop is being spread')) return; consoleError(...a) }
const failures = []
for (const [view, needles] of Object.entries(views)) {
  let html = ''
  try { html = renderToString(createElement(page.render().type, { initialView: view })) }
  catch (e) { failures.push(`${view}: threw ${e && e.stack || e}`); continue }
  for (const n of needles) if (!html.includes(n)) failures.push(`${view}: rendered ${html.length} chars but no "${n}"`)
  console.log(`${failures.some((f) => f.startsWith(view + ':')) ? 'FAIL' : 'ok  '} ${view.padEnd(9)} ${html.length} chars`)
}
try { const html = renderToString(page.render()); if (!html.includes('your to-do')) failures.push('page.render(): no default view') ; console.log(`ok   page      ${html.length} chars (default view)`) }
catch (e) { failures.push(`page.render(): threw ${e && e.stack || e}`) }
try { const html = renderToString(chip.render()); if (!html.includes('cockpit')) failures.push('chip: no chip text'); console.log(`ok   chip      ${html.length} chars`) }
catch (e) { failures.push(`chip: threw ${e && e.stack || e}`) }

if (failures.length) { console.error('\n' + failures.join('\n')); process.exit(1) }
console.log(`\nsmoke: ${Object.keys(views).length} views + page + chip rendered`)
