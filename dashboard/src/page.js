// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
const SCREEN = "/api/plugins/cockpit/screen"
const PUBLISH = "/api/plugins/cockpit/publish"
const KICKOFF = "/api/plugins/cockpit/kickoff"
const SETUP = "/api/plugins/cockpit/setup"

export const PANES = [
  ["inbox", "Inbox"],
  ["outbox", "Outbox"],
  ["board", "Board"],
  ["live", "Live"],
  ["tickets", "Tickets"],
  ["qa", "QA"],
  ["platform", "Platform"],
  ["usage", "Usage"],
  ["settings", "Settings"],
  ["chat", "Chat"],
]

export const TOOLBAR = ["Inbox", "Board", "Live", "Tickets", "QA evidence", "Platform", "Usage", "Settings"]

const MODES = ["intake", "test", "review", "analyst", "rework", "bumps"]

export async function loadScreen(fetchJSON) {
  return fetchJSON(SCREEN)
}

export function publishRequest(id) {
  return {
    url: PUBLISH,
    init: {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id, confirm: id }),
    },
  }
}

export function kickoffRequest(ticket, mode) {
  return {
    url: KICKOFF,
    init: {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ticket, mode: mode || "intake" }),
    },
  }
}

export function createPage(sdk) {
  const { React } = sdk
  const { useState, useEffect } = sdk.hooks
  const fetchJSON = sdk.fetchJSON
  const { Card, CardHeader, CardTitle, CardContent, Button, Input, Select, SelectOption, Badge } = sdk.components

  function Page() {
    const [screen, setScreen] = useState(null)
    const [pane, setPane] = useState("inbox")
    const [error, setError] = useState("")
    const [notice, setNotice] = useState("")
    const [ticket, setTicket] = useState("")
    const [mode, setMode] = useState("intake")

    useEffect(() => {
      let live = true
      loadScreen(fetchJSON).then((data) => {
        if (live) setScreen(data)
      }).catch((err) => {
        if (live) setError(message(err))
      })
      return () => {
        live = false
      }
    }, [])

    function refresh() {
      return loadScreen(fetchJSON).then((data) => {
        setScreen(data)
        return data
      })
    }

    function onPublish(id) {
      const request = publishRequest(id)
      setError("")
      return fetchJSON(request.url, request.init).then(() => {
        setNotice(`published ${id}`)
        return refresh()
      }).catch((err) => {
        setError(message(err))
      })
    }

    function onKickoff() {
      const request = kickoffRequest(ticket, mode)
      setError("")
      return fetchJSON(request.url, request.init).then((row) => {
        setNotice((row && row.title) || "ok")
        return refresh()
      }).catch((err) => {
        setError(message(err))
      })
    }

    function onSetup() {
      setError("")
      return fetchJSON(SETUP, { method: "POST" }).then(() => {
        setNotice("setup ok")
        return refresh()
      }).catch((err) => {
        setError(message(err))
      })
    }

    const name = screen ? screen.name : "Cockpit"
    const need = screen ? screen.need_you : 0
    return React.createElement("div", { className: "cockpit-page", "data-plugin-root": "cockpit" },
      React.createElement("header", { className: "cockpit-head" },
        React.createElement("h2", null, name),
        React.createElement(Badge, null, `cockpit · ${need} need you`),
        React.createElement("span", { className: "cockpit-toolbar" }, TOOLBAR.join(" · ")),
        screen ? React.createElement("span", null, `gateway ${screen.gateway}`) : null,
      ),
      React.createElement("nav", { className: "cockpit-nav" }, ...PANES.map(([id, label]) => React.createElement(Button, {
        key: id,
        onClick: () => setPane(id),
      }, label))),
      React.createElement("div", { className: "cockpit-panel" },
        error ? React.createElement("p", { className: "cockpit-error" }, error) : null,
        notice ? React.createElement("p", null, notice) : null,
        screen ? drawPane(React, { Button, Input, Select, SelectOption }, screen, pane, { onPublish, onKickoff, onSetup, ticket, setTicket, mode, setMode }) : (error ? null : React.createElement("p", null, "Loading")),
      ),
    )
  }

  return Page
}

function drawPane(React, ui, screen, pane, actions) {
  if (pane === "inbox") return inbox(React, ui, screen, actions)
  if (pane === "outbox") return rows(React, "Outbox", screen.outbox.map(intentLine))
  if (pane === "board") return board(React, screen)
  if (pane === "live") return rows(React, "Live", screen.live.map((lane) => `${lane.lane} · ${lane.kind} · open ${lane.open}`))
  if (pane === "tickets") return tickets(React, ui, screen, actions)
  if (pane === "qa") return rows(React, "QA evidence", screen.qa)
  if (pane === "platform") return platform(React, screen.platform)
  if (pane === "usage") return usage(React, screen)
  if (pane === "settings") return settings(React, ui, screen, actions)
  return chat(React, screen)
}

function board(React, screen) {
  const columns = ["ready", "running", "review", "blocked"]
  const cards = screen.board_cards || []
  return React.createElement("section", { className: "cockpit-board" },
    React.createElement("h2", null, "Board"),
    cards.length ? React.createElement("div", { className: "cockpit-columns" }, ...columns.map((status) => {
      const rows = cards.filter((card) => columnOf(card.status) === status)
      return React.createElement("div", { className: "cockpit-column", key: status },
        React.createElement("h3", null, status),
        ...rows.map((card) => React.createElement("article", { className: "cockpit-card", key: card.id },
          React.createElement("strong", null, card.title || card.id),
          React.createElement("p", null, card.lane || "unassigned"),
        )),
        rows.length ? null : React.createElement("p", { className: "cockpit-empty" }, "none"),
      )
    })) : React.createElement("p", null, "none"),
  )
}

function columnOf(status) {
  if (status === "in_progress" || status === "claimed" || status === "running") return "running"
  if (status === "review") return "review"
  if (status === "blocked") return "blocked"
  return "ready"
}

function inbox(React, ui, screen, actions) {
  const items = screen.inbox.map((row) => React.createElement("li", { key: row.kind + row.id },
    `${row.kind} · ${row.lane || "watcher"} · ${row.summary || row.id}`,
    row.kind === "publish" ? React.createElement(ui.Button, { onClick: () => actions.onPublish(row.id) }, "Publish") : null,
  ))
  return React.createElement("section", null,
    React.createElement("h2", null, "Inbox"),
    React.createElement("ul", null, ...(items.length ? items : [React.createElement("li", { key: "empty" }, "Nothing needs you.")])),
  )
}

function tickets(React, ui, screen, actions) {
  const lines = screen.tickets.map((row) => `${row.ticket} · ${(row.cards || []).join(" ") || "no card"} · ${row.intents.length} intents · ${row.plan.join(", ") || "no plan"}`)
  return React.createElement("section", null,
    React.createElement("h2", null, "Tickets"),
    list(React, lines),
    React.createElement(ui.Input, {
      value: actions.ticket,
      placeholder: "TASK-100",
      onChange: (event) => actions.setTicket(event.target.value),
    }),
    React.createElement(ui.Select, {
      value: actions.mode,
      onChange: (event) => actions.setMode(event.target.value),
    }, ...MODES.map((name) => React.createElement(ui.SelectOption, { key: name, value: name }, name))),
    React.createElement(ui.Button, { onClick: actions.onKickoff }, "Kickoff"),
  )
}

function platform(React, data) {
  if (data.hidden) return React.createElement("section", null, React.createElement("h2", null, "Platform"), React.createElement("p", null, "No map.yaml in this workspace."))
  return React.createElement("section", null, React.createElement("h2", null, "Platform"), React.createElement("pre", null, data.text))
}

function usage(React, screen) {
  const budget = screen.usage.budget || {}
  return rows(React, "Usage", [
    `monthly cap ${budget.monthly_usd}`,
    `plan window ${budget.plan_window_max_pct}%`,
    `browser loan ${screen.usage.shared_chrome_hours}h`,
    ...Object.keys(screen.capacity || {}).map((key) => `${key}: ${screen.capacity[key]}`),
  ])
}

function settings(React, ui, screen, actions) {
  const seats = screen.settings.seats || {}
  const lines = Object.keys(seats).map((key) => `${key}: ${seats[key]}`)
  return React.createElement("section", null,
    React.createElement("h2", null, "Settings"),
    list(React, lines),
    React.createElement("p", null, "Provider and model stay in the pack."),
    React.createElement(ui.Button, { onClick: actions.onSetup }, "Set up"),
  )
}

function chat(React, screen) {
  const label = screen.chat.display_name || screen.display_name || "Chat"
  const sessions = screen.chat.sessions.length ? screen.chat.sessions : ["own"]
  return React.createElement("section", null,
    React.createElement("h2", null, label),
    React.createElement("p", null, "One session per ticket. Live has Lanes and Coding."),
    list(React, sessions),
  )
}

function rows(React, heading, lines) {
  return React.createElement("section", null, React.createElement("h2", null, heading), list(React, lines))
}

function list(React, lines) {
  const body = lines.length ? lines.map((line) => React.createElement("li", { key: line }, line)) : [React.createElement("li", { key: "empty" }, "none")]
  return React.createElement("ul", null, ...body)
}

function intentLine(row) {
  return `${row.status} · ${row.type} · ${row.ticket} · ${row.lane} · ${row.summary}`
}

function message(err) {
  if (err && err.message) return err.message
  return String(err)
}
