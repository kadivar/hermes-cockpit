// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import assert from "node:assert/strict"
import { renderAll } from "../../desktop/src/index.js"

const views = renderAll({ displayName: "Chat", rows: [{ kind: "publish" }] })
assert.equal(views.length, 11)
assert.equal(views.find((view) => view.view === "chat").label, "Chat")
assert.equal(views.find((view) => view.view === "inbox").count, 1)
console.log("page ok")
