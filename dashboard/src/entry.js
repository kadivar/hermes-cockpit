// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { createPage } from "./page.js"

const sdk = window.__HERMES_PLUGIN_SDK__
window.__HERMES_PLUGINS__.register("cockpit", createPage(sdk))
