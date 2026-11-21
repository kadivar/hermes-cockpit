// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// What a pack may word or name its own way. Each helper takes what a route sent and falls back to the kernel's own
// words where it sent none.

// ---------- a test run's names (the /qa route's `names`) ----------
export const RUN_NAMES = { title: 'Test run', results: 'test-results.md', evidence: 'evidence', plan: 'test-plan.md' }
export const runNames = (names) => ({ ...RUN_NAMES, ...Object.fromEntries(Object.entries(names || {}).filter(([k, v]) => k in RUN_NAMES && typeof v === 'string' && v)) })
const escapeRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
// a results row links its proof as <evidence folder>/<file>: the file's path inside that folder
export const evidenceRel = (rel, evidence) => String(rel).replace(new RegExp('^\\.?\\/?' + escapeRe(evidence) + '\\/'), '')

// ---------- help text that names a pack's way of working (the /repos route's `hints`) ----------
// The kernel's own words, which the route sends for a pack that sets no desktop.hints; kept here for a page whose
// route has not answered yet. Each is written as JSON reads it, so a test can hold it against the kernel's copy.
export const HINTS = {
  "bumps_tab": "Bumps → reviewer",
  "review": "The reviewer checks each PR head out in a worktree, reviews it against the real code, leaves the findings on the card and writes one review intent per PR. You publish them from the Outbox; nothing reaches the forge before that.",
  "bumps": "Tick the repos. Per repo a reviewer card lists its open dependency-bot pull requests and asks you which; every write it then prepares comes back here for you to publish. The weekday scan offers the candidates in the Inbox by itself.",
  "rereview": "the reviewer lane checks whether each of your threads was answered, reviews only the diff since your last review, and writes one review intent for your publish",
  "bumps_start": "Nothing has started. Pick the batch and Start: a reviewer card works through it, and every write comes back here for you to publish. Dismiss what a colleague takes."
}
export const hintsOf = (hints) => ({ ...HINTS, ...Object.fromEntries(Object.entries(hints || {}).filter(([k, v]) => k in HINTS && typeof v === 'string' && v)) })

// ---------- the tracker's name on a page (the /repos route's `tracker_kind`) ----------
// A pack on the Jira tracker (its kinds: jira, and connector, which is the default) reads "Jira"; every other
// tracker, and a route that names none, reads "Tracker".
const JIRA_KINDS = ['jira', 'connector']
export const trackerWord = (kind) => (JIRA_KINDS.includes(kind) ? 'Jira' : 'Tracker')

// ---------- the order of the lanes on the Live page (the /job-stream route's `lane_order`) ----------
// The seats come from the kernel, in its order: the pack's own seats, each kind's in number order. A Hermes profile that
// is no seat of the pack keeps the place it always had beside them: the two named here after the seats of a kind, the
// root profile after every seat, and any other name last, by name.
// Identifiers of one coding tool as a machine may carry them: a Hermes profile named after it, and the prefix of its
// model ids. Matched against what the kernel sends, never printed.
export const TOOL_PROFILE = 'claude'
export const MODEL_PREFIX = 'claude-'
export const LANES_BEFORE = ['intake', 'orchestrator', 'worker-1', 'worker-2', 'worker-3', 'tester-1', 'tester-2', 'tester-3', 'reviewer', 'gatekeeper', 'analyst', TOOL_PROFILE, 'advisor', 'default']
const AFTER_KIND = { orchestrator: 'intake', [TOOL_PROFILE]: 'analyst' }
const ROOT_PROFILE = 'default'
const kindOf = (lane) => String(lane).replace(/-\d+$/, '')
export function laneOrder(seats) {
  if (!Array.isArray(seats) || !seats.length) return LANES_BEFORE   // no order sent yet: the kernel's own seats in their usual order
  const out = seats.filter((s) => typeof s === 'string' && s)
  for (const [name, kind] of Object.entries(AFTER_KIND)) {
    if (out.includes(name)) continue
    let at = -1
    out.forEach((s, i) => { if (kindOf(s) === kind) at = i })
    if (at < 0) at = kind === 'intake' ? -1 : out.length - 1 - (out.includes('advisor') ? 1 : 0)   // no seat of that kind: first, or before the advisor
    out.splice(at + 1, 0, name)
  }
  if (!out.includes(ROOT_PROFILE)) out.push(ROOT_PROFILE)
  return out
}
export const sortLanes = (names, seats) => { const order = laneOrder(seats); return [...names].sort((a, b) => (order.indexOf(a) + 1 || order.length + 1) - (order.indexOf(b) + 1 || order.length + 1) || a.localeCompare(b)) }
