// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// Fixes to the Hermes Desktop a pack opts into by name (pack.yaml desktop.overrides; cockpit's pack check knows the
// names). Each writes one setting the Desktop keeps in its own storage, where Hermes offers no way to change it on
// that platform. They are named here, not in the pack: a pack chooses among these and cannot write anything else.
export const OVERRIDES = {
  // Hermes hides Appearance → Translucency on Linux, taking window opacity for a no-op there, but WSLg applies it: the
  // default intensity 29 leaves the window see-through, with no setting to turn it off.
  'opaque-window': {
    key: 'hermes.desktop.translucency.v2',
    value: { mode: 'clear', base: { intensity: 0 }, light: { intensity: 0 }, dark: { intensity: 0 } }
  }
}
const RELOADED = 'cockpit.desktop-overrides.reloaded'

// Write each named override that differs from what is stored. True when one changed and reads back as written: the
// Desktop reads these at start, so the caller reloads the window once.
export function applyOverrides(names, storage) {
  let changed = false
  for (const name of names || []) {
    const entry = OVERRIDES[name]
    if (!entry) continue
    const want = JSON.stringify(entry.value)
    try {
      if (storage.getItem(entry.key) === want) continue
      storage.setItem(entry.key, want)
      changed = storage.getItem(entry.key) === want || changed
    } catch (e) { /* storage refused: nothing to reload for */ }
  }
  return changed
}

// At start: ask the pack which overrides it wants (the gateway may not be up yet, so a few tries), apply them, and
// reload once if one changed. At most one reload per window session, whatever happens, so it can never loop.
export async function startOverrides(rest, win = window, tries = 5, waitMs = 10000) {
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      const { overrides } = await rest('/desktop-overrides')
      if (!applyOverrides(overrides, win.localStorage)) return false
      if (win.sessionStorage.getItem(RELOADED)) return false
      win.sessionStorage.setItem(RELOADED, '1')
      win.location.reload()
      return true
    } catch (e) {
      await new Promise((resolve) => setTimeout(resolve, waitMs))
    }
  }
  return false
}
