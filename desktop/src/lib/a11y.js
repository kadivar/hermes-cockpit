// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later

// The one place that makes a clickable element reachable without a mouse. h() (lib/sdk.js) passes every element's props
// through pressable(), so a view writes `h('div', { onClick })` and gets what a button has by nature: a role, a place in
// the tab order, and Enter and Space. An element that only stops a click from reaching what is behind it (a dialog's
// body, its backdrop) is no control: it says so with `role: 'presentation'` and is left as it is.

// what the browser already treats as a control, or labels one
const NATIVE = new Set(['button', 'a', 'input', 'select', 'textarea', 'summary', 'label', 'option'])

// text that is letters or digits in any script; a button without any shows a sign only
const WORD = /[\p{L}\p{N}]/u

function textOf(children) {
  if (children == null || typeof children === 'boolean') return ''
  if (typeof children === 'string' || typeof children === 'number') return String(children)
  if (Array.isArray(children)) return children.map(textOf).join('')
  return children.props ? textOf(children.props.children) : ''
}

// whether a button shows a sign and no word (✕, ▾, ⟳): its title is then the only name it has
export const iconOnly = (children) => !WORD.test(textOf(children))

export function pressable(tag, props, children) {
  if (typeof tag !== 'string' || !props) return props
  if (tag === 'button') {
    return props.title && !props['aria-label'] && iconOnly(children) ? { ...props, 'aria-label': props.title } : props
  }
  if (typeof props.onClick !== 'function' || NATIVE.has(tag) || props.role) return props
  const { onClick, onKeyDown } = props
  return {
    role: 'button',
    tabIndex: 0,
    ...props,
    onKeyDown: (e) => {
      if (onKeyDown) onKeyDown(e)
      // a key pressed in a field or on a button inside the element is that control's own
      if (e.defaultPrevented || e.target !== e.currentTarget || (e.key !== 'Enter' && e.key !== ' ')) return
      e.preventDefault()
      onClick(e)
    },
  }
}
