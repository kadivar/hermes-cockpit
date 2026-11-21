// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import assert from "node:assert/strict"
import { PANES, createPage, kickoffRequest, loadScreen, publishRequest } from "../../dashboard/src/page.js"

const screen = {
  name: "acme",
  display_name: "Chat",
  gateway: "running",
  need_you: 2,
  capacity: { intake: 1, test: 0 },
  inbox: [
    { kind: "publish", id: "TASK-1/001-push-branch", ticket: "TASK-1", lane: "gatekeeper", summary: "ship it", ask: "", options: [] },
    { kind: "fix watcher", id: "ci-watch", ticket: "", lane: "", summary: "the run timed out", ask: "", options: [] },
  ],
  outbox: [
    { id: "TASK-1/001-push-branch", type: "push-branch", status: "endorsed", ticket: "TASK-1", lane: "worker-1", summary: "ship it" },
  ],
  board_cards: [{ id: "c1", title: "TASK-1: intake", lane: "intake", status: "ready" }],
  live: [{ lane: "intake", kind: "intake", open: 1 }, { lane: "worker-1", kind: "worker", open: 0 }],
  tickets: [{ ticket: "TASK-1", intents: ["TASK-1/001-push-branch"], plan: ["Brief"] }],
  qa: ["TASK-1/plan.md"],
  platform: { hidden: false, text: "repos: api" },
  usage: { budget: { monthly_usd: 0, plan_window_max_pct: 90 }, shared_chrome_hours: 4 },
  settings: { seats: { intake: 1, slots: 1, reviewer: 1, analyst: 1 } },
  chat: { display_name: "Chat", sessions: ["TASK-1"] },
}

let payload = screen
const fetchJSON = async (url, init) => {
  if (url.endsWith("/screen")) return payload
  if (url.endsWith("/publish")) {
    assert.equal(JSON.parse(init.body).confirm, "TASK-1/001-push-branch")
    return { ok: true }
  }
  if (url.endsWith("/kickoff")) return { ok: true, title: "TASK-2: review" }
  if (url.endsWith("/setup")) return { ok: true }
  throw new Error("unexpected " + url)
}

assert.equal((await loadScreen(fetchJSON)).name, "acme")
assert.equal(publishRequest("TASK-1/001-push-branch").init.body.includes("confirm"), true)
assert.equal(kickoffRequest("TASK-2", "review").init.method, "POST")
assert.equal(PANES.length, 10)

const slots = []
let cursor = 0
function useState(init) {
  const index = cursor
  cursor += 1
  if (slots.length <= index) slots.push(init)
  return [slots[index], (value) => {
    slots[index] = typeof value === "function" ? value(slots[index]) : value
  }]
}
const effects = []
function useEffect(fn) {
  effects.push(fn)
}
const tree = []
function createElement(type, props, ...children) {
  return { type, props: props || {}, children }
}
function walk(node, into) {
  if (!node) return
  if (Array.isArray(node)) {
    node.forEach((child) => walk(child, into))
    return
  }
  if (typeof node === "string" || typeof node === "number") {
    into.push(String(node))
    return
  }
  into.push(node)
  walk(node.children, into)
}
const Page = createPage({
  React: { createElement },
  hooks: { useState, useEffect },
  fetchJSON,
  components: {
    Card: "Card",
    CardHeader: "CardHeader",
    CardTitle: "CardTitle",
    CardContent: "CardContent",
    Button: "Button",
    Input: "Input",
    Select: "Select",
    SelectOption: "SelectOption",
    Badge: "Badge",
  },
})

function render() {
  cursor = 0
  tree.length = 0
  const root = Page()
  walk(root, tree)
  return tree.map((node) => typeof node === "string" ? node : "").join("\n") + JSON.stringify(tree)
}

Page()
effects[0]()
for (let step = 0; step < 6; step += 1) await Promise.resolve()
let text = render()
assert.match(text, /Inbox/)
assert.match(text, /ship it/)
assert.match(text, /cockpit · 2 need you/)
const publish = tree.find((node) => node.type === "Button" && node.children && node.children.includes("Publish"))
await publish.props.onClick()
text = render()
assert.match(text, /published TASK-1/)

function click(label) {
  const button = tree.find((node) => node.type === "Button" && node.children && node.children.includes(label))
  button.props.onClick()
}
for (const label of ["Outbox", "Board", "Live", "Tickets", "QA", "Platform", "Usage", "Settings", "Chat"]) {
  click(label)
  text = render()
  assert.match(text, new RegExp(label === "QA" ? "QA evidence" : label))
}
click("Tickets")
text = render()
const kick = tree.find((node) => node.type === "Button" && node.children && node.children.includes("Kickoff"))
await kick.props.onClick()
text = render()
assert.match(text, /TASK-2: review/)
click("Settings")
render()
const setup = tree.find((node) => node.type === "Button" && node.children && node.children.includes("Set up"))
await setup.props.onClick()
text = render()
assert.match(text, /setup ok/)
console.log("dashboard ok")
