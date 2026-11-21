// SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useMemo } from 'react'
import { host, useQuery, useQueryClient, CTX, h, sub, mono, stroke, btn, seg, post, openIde } from './sdk.js'

// ---------- diff viewer (unified diff → per-file collapsible blocks) ----------
function parseDiff(text) {
  const files = []; let f = null, oldN = 0, newN = 0
  for (const line of (text || '').split('\n')) {
    if (line.startsWith('diff --git ')) { const m = /^diff --git a\/(.+?) b\/(.+)$/.exec(line); f = { path: m ? m[2] : line.slice(11), old: m ? m[1] : '', lines: [], add: 0, del: 0, kind: '' }; files.push(f); continue }
    if (!f) continue
    if (line.startsWith('new file')) { f.kind = 'added'; continue }
    if (line.startsWith('deleted file')) { f.kind = 'deleted'; continue }
    if (line.startsWith('rename ') || line.startsWith('similarity ')) { f.kind = 'renamed'; continue }
    if (line.startsWith('index ') || line.startsWith('--- ') || line.startsWith('+++ ') || line.startsWith('Binary ')) { if (line.startsWith('Binary ')) f.lines.push({ k: 'hk', t: line }); continue }
    if (line.startsWith('@@')) { const m = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line); oldN = m ? +m[1] : 0; newN = m ? +m[2] : 0; f.lines.push({ k: 'hk', t: line }); continue }
    if (line.startsWith('+')) { f.add++; f.lines.push({ k: 'a', n: newN++, t: line.slice(1) }); continue }
    if (line.startsWith('-')) { f.del++; f.lines.push({ k: 'd', o: oldN++, t: line.slice(1) }); continue }
    if (line.startsWith('\\')) continue
    f.lines.push({ k: 'c', o: oldN++, n: newN++, t: line.slice(1) })
  }
  return files
}
// test files (PHPUnit, Jest/Vitest, Cypress, fixtures, snapshots) start collapsed in every diff view; the code change starts open
const TEST_PATH = /(^|\/)(tests?|__tests__|__mocks__|spec|specs|cypress|fixtures|__snapshots__|testing)\/|\.(test|spec|cy)\.[jt]sx?$|Test\.php$|\.snap$|\/factories\/|\/seeders\/|\/stories\//
const isTestFile = (path) => TEST_PATH.test(path || '')
function DiffFile({ f, repoDir, ticket, startOpen }) {
  const [open, setOpen] = useState(startOpen && !isTestFile(f.path))
  const kind = f.kind ? ` · ${f.kind}` : ''
  return h('div', { className: 'f' },
    h('div', { className: 'fh', onClick: () => setOpen(!open) },
      h('span', null, open ? '▾' : '▸'), h('span', { className: 'n', title: f.path }, f.path + kind + (isTestFile(f.path) ? ' · test' : '')),
      h('span', { style: { color: '#2ea043' } }, `+${f.add}`), h('span', { style: { color: '#f85149' } }, `−${f.del}`),
      repoDir ? btn('open', () => openIde({ ticket, file: `${repoDir}/${f.path}` }), { title: 'open this file in the ticket workspace' }) : null),
    open ? h('div', null, ...f.lines.map((l, i) => h('div', { key: i, className: 'l ' + l.k },
      h('span', { className: 'no' }, l.k === 'hk' ? '' : (l.o ?? '')), h('span', { className: 'no' }, l.k === 'hk' ? '' : (l.n ?? '')), h('span', { className: 't' }, l.t)))) : null)
}
// the commits a rebase brings under the branch
const baseCommits = (data) => data.commits_base || []
function DiffView({ data, onFetch }) {
  // code files first (in diff order), every test file after them: the change reads top-down, the tests wait at the end
  const codeFirst = (fs) => [...fs.filter((f) => !isTestFile(f.path)), ...fs.filter((f) => isTestFile(f.path))]
  const files = useMemo(() => codeFirst(parseDiff(data.diff)), [data.diff])
  const unc = useMemo(() => codeFirst(parseDiff(data.uncommitted_diff)), [data.uncommitted_diff])
  const many = files.filter((f) => !isTestFile(f.path)).length > 25   // only a very large code change starts collapsed; tests always do
  const origin = data.mode === 'origin' || data.mode === 'rebase' || data.mode === 'change'
  const dropped = data.dropped || []
  return h('div', { className: 'cockpit-diff flex flex-col gap-2' },
    data.rebase ? h('div', { className: 'rounded border p-2 text-xs flex flex-col gap-1', style: { borderColor: 'var(--ui-accent)' } },
      h('div', { className: 'font-medium' }, `Rebase only · ${data.rebase.proof}`),
      h('div', { style: sub }, 'What the push changes is the base, not the patches. Commits that move under the branch (other people\'s work already on the base branch):'),
      h('pre', { className: 'whitespace-pre-wrap text-xs', style: mono }, data.rebase.base_log || '(none)'),
      h('details', null, h('summary', { className: 'cursor-pointer', style: sub }, 'git range-diff (every row should read "=" : identical patch)'), h('pre', { className: 'whitespace-pre-wrap text-xs', style: mono }, data.rebase.range_diff))) : null,
    h('div', { className: 'flex flex-wrap items-center gap-2 text-xs', style: sub },
      h('span', null, `${data.repo} · ${data.range} · ${files.length} files`),
      origin ? h('span', { style: { color: data.remote_exists ? (data.fast_forward ? 'var(--ui-success, #2a9d5c)' : 'var(--ui-warning, #c98a00)') : 'var(--ui-text-tertiary)' } },
        data.mode === 'change' ? '· only this ticket\'s change on top of the rebase step' : data.remote_exists ? (data.fast_forward ? '· fast-forward: origin keeps every commit it has' : '· NOT a fast-forward: a force push rewrites origin') : '· branch not known locally') : null,
      origin ? h('span', null, `· origin as of ${data.last_fetch ? new Date(data.last_fetch).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }) : 'unknown'}`) : null,
      origin && onFetch ? btn('Refresh from origin', onFetch, { title: 'git fetch origin <branch> — a read; nothing is pushed' }) : null),
    origin && data.note ? h('div', { className: 'text-xs', style: sub }, data.note) : null,
    origin && dropped.length ? (() => { const st = (x) => typeof x === 'string' ? 'lost' : (x.state || (x.replaced ? 'replaced' : 'lost')); const line = (x) => typeof x === 'string' ? x : x.line
      const lost = dropped.filter((x) => st(x) === 'lost'); const rewritten = dropped.filter((x) => st(x) === 'rewritten'); const replaced = dropped.filter((x) => st(x) === 'replaced')
      return h('div', { className: 'flex flex-col gap-1' },
        lost.length ? h('div', { className: 'rounded border p-2 text-xs', style: { borderColor: 'var(--ui-danger, #d33)' } },
          h('div', { className: 'font-medium', style: { color: 'var(--ui-danger, #d33)' } }, `${lost.length} commit(s) on origin that no local commit carries — a force push LOSES them`),
          h('pre', { className: 'whitespace-pre-wrap text-xs', style: mono }, lost.map(line).join('\n'))) : null,
        rewritten.length ? h('div', { className: 'rounded border p-2 text-xs', style: { borderColor: 'var(--ui-warning, #c98a00)' } },
          h('div', { className: 'font-medium', style: { color: 'var(--ui-warning, #c98a00)' } }, `${rewritten.length} commit(s) on origin rewritten with changed content (a fixup squashed into them) — see "the change" for what changed`),
          h('pre', { className: 'whitespace-pre-wrap text-xs', style: { ...mono, ...sub } }, rewritten.map(line).join('\n'))) : null,
        replaced.length ? h('div', { className: 'rounded border p-2 text-xs', style: { borderColor: stroke } },
          h('div', { className: 'font-medium', style: sub }, `${replaced.length} commit(s) on origin replaced by equivalents with the same patch (new base) — nothing is lost`),
          h('pre', { className: 'whitespace-pre-wrap text-xs', style: { ...mono, ...sub } }, replaced.map(line).join('\n'))) : null) })() : null,
    data.mode === 'change' && data.range_diff ? h('details', { className: 'text-xs' }, h('summary', { className: 'cursor-pointer', style: sub }, 'per-commit range-diff: rebase step → this push (which commits changed, and how)'), h('pre', { className: 'whitespace-pre-wrap text-xs', style: mono }, data.range_diff)) : null,
    origin ? h('div', { className: 'text-xs font-medium' }, data.mode === 'change' ? `The branch's commits after this push (${(data.commits || []).length}); the file diff below is only what changed since the rebase step` : `This branch's own commits the push adds to origin (${(data.commits || []).length})`) : null,
    data.commits && data.commits.length ? h('pre', { className: 'whitespace-pre-wrap text-xs', style: mono }, data.commits.join('\n')) : (origin && data.remote_exists ? h('div', { className: 'text-xs', style: sub }, 'None: origin already has every own commit.') : null),
    origin && baseCommits(data).length ? h('div', null, h('div', { className: 'text-xs font-medium', style: sub }, `Commits that arrive under the branch from the base branch through the rebase (${baseCommits(data).length}) — not this ticket's work`), h('pre', { className: 'whitespace-pre-wrap text-xs', style: { ...mono, ...sub } }, baseCommits(data).join('\n'))) : null,
    data.mode === 'origin' && data.remote_exists ? h('div', { className: 'text-xs', style: sub }, 'The file diff below is origin\'s tip → the local tip: everything the force push changes on the branch.') : null,
    data.stat ? h('pre', { className: 'whitespace-pre-wrap text-xs', style: { ...mono, ...sub } }, data.stat) : null,
    ...files.flatMap((f, i) => [
      isTestFile(f.path) && (i === 0 || !isTestFile(files[i - 1].path)) ? h('div', { key: 'tests-divider', className: 'mt-1 text-xs', style: sub }, `tests (${files.length - i} file(s), collapsed)`) : null,
      h(DiffFile, { key: f.path, f, repoDir: data.repo_dir, ticket: data.ticket, startOpen: !many })]),
    !files.length && !origin ? h('div', { className: 'text-xs', style: sub }, 'No committed changes in this range.') : null,
    data.uncommitted_status ? h('div', { className: 'mt-2' },
      h('div', { className: 'text-xs font-medium', style: { color: 'var(--ui-warning, #c98a00)' } }, `Uncommitted in the worktree (${data.uncommitted_status.split('\n').length} entries) — ${data.intent ? 'not part of the intent' : 'not committed or pushed yet'}`),
      h('pre', { className: 'whitespace-pre-wrap text-xs', style: { ...mono, ...sub } }, data.uncommitted_status),
      ...unc.map((f) => h(DiffFile, { key: 'u' + f.path, f, repoDir: data.repo_dir, ticket: data.ticket, startOpen: !data.intent }))) : null)
}
function DiffPanel({ params, defaultMode, chained, rebaseOnly }) {
  const [mode, setMode] = useState(defaultMode || 'base')
  const qc = useQueryClient()
  const qs = Object.entries({ ...params, mode }).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&')
  const q = useQuery({ queryKey: ['cockpit', 'diff', qs], queryFn: () => CTX.rest('/diff?' + qs), staleTime: 15000, retry: 0 })
  const fetchOrigin = async () => {
    const d = q.data; if (!d) return
    const branch = (d.remote || '').replace(/^origin\//, '')
    try { const r = await post('/fetch', { ticket: d.ticket, repo: d.repo, branch }); host.notify({ kind: 'info', message: r.out || 'fetched' }); qc.invalidateQueries({ queryKey: ['cockpit', 'diff'] }) }
    catch (e) { host.notifyError(e, 'fetch failed') }
  }
  const toggle = h('div', { className: 'flex items-center gap-1 self-start rounded border p-0.5', style: { borderColor: stroke } },
    chained ? seg(mode, 'change', 'the change (this push adds, rebase excluded)', setMode) : seg(mode, 'origin', rebaseOnly ? 'origin → local (the rebase)' : 'origin → local (what the push overwrites)', setMode),
    seg(mode, 'base', 'vs base (what the whole branch changes)', setMode),
    chained ? seg(mode, 'rebase', 'the rebase (what the base branch brings under the branch)', setMode) : null)
  if (q.isLoading) return h('div', { className: 'flex flex-col gap-2' }, toggle, h('div', { className: 'text-xs p-2', style: sub }, 'computing diff'))
  if (q.error) return h('div', { className: 'flex flex-col gap-2' }, toggle, h('div', { className: 'text-xs p-2', style: { color: 'var(--ui-danger, #d33)' } }, String(q.error.message || q.error)))
  return h('div', { className: 'flex flex-col gap-2' }, toggle, h(DiffView, { data: q.data, onFetch: mode === 'origin' || mode === 'rebase' ? fetchOrigin : null }))
}

export { parseDiff, isTestFile, DiffFile, DiffView, DiffPanel, baseCommits }
