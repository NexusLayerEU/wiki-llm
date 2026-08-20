import { useCallback, useEffect, useRef, useState } from 'react'
import { api, captureTokenFromUrl, readClaims } from './api'
import { Empty, Icon, Spinner, Toast } from './components/bits'
import { FilesView } from './components/Files'
import { PipelineView } from './components/Pipeline'
import { AskView, MetricsView } from './components/Ask'
import { GraphView, WikiView } from './components/Wiki'

const TABS = [
  { id: 'pipeline', label: 'Forge', icon: 'flow' },
  { id: 'files', label: 'Files', icon: 'file' },
  { id: 'wiki', label: 'Wiki', icon: 'book' },
  { id: 'graph', label: 'Graph', icon: 'graph' },
  { id: 'ask', label: 'Ask', icon: 'ask' },
  { id: 'metrics', label: 'Usage', icon: 'chart' },
]

/** How often the pipeline view re-reads status while work is outstanding. */
const POLL_MS = 3000

export default function App() {
  const [caps, setCaps] = useState(null)
  const [projects, setProjects] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [tab, setTab] = useState('pipeline')
  const [booting, setBooting] = useState(true)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState(null)

  const [status, setStatus] = useState(null)
  const [files, setFiles] = useState([])
  const [pages, setPages] = useState([])
  const [jobs, setJobs] = useState([])
  const [graph, setGraph] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [wikiSlug, setWikiSlug] = useState(null)

  const claims = readClaims()
  const active = projects.find((project) => project.id === activeId) || null

  const notify = useCallback((message, bad = false) => {
    setToast({ message, bad })
    window.clearTimeout(notify.timer)
    notify.timer = window.setTimeout(() => setToast(null), bad ? 7000 : 3600)
  }, [])

  // --- boot -----------------------------------------------------------------
  useEffect(() => {
    captureTokenFromUrl()
    ;(async () => {
      try {
        const [capabilities, list] = await Promise.all([api.capabilities(), api.listProjects()])
        setCaps(capabilities)
        setProjects(list.projects || [])
        if (list.projects?.length) setActiveId(list.projects[0].id)
      } catch (cause) {
        notify(cause.message, true)
      } finally {
        setBooting(false)
      }
    })()
  }, [notify])

  // --- per-project data -----------------------------------------------------
  const refresh = useCallback(async (id, which = 'all') => {
    if (!id) return
    const wanted = (name) => which === 'all' || which === name
    try {
      const [s, f, p, j] = await Promise.all([
        api.status(id),
        wanted('files') ? api.listFiles(id, 'limit=300') : null,
        wanted('pages') ? api.listPages(id) : null,
        wanted('jobs') ? api.jobs(id) : null,
      ])
      setStatus(s)
      if (f) setFiles(f.files || [])
      if (p) setPages(p.pages || [])
      if (j) setJobs(j.jobs || [])
    } catch (cause) {
      // Polling failures are not worth a toast every three seconds.
      if (which === 'all') notify(cause.message, true)
    }
  }, [notify])

  useEffect(() => {
    if (!activeId) return
    setStatus(null); setFiles([]); setPages([]); setJobs([])
    setGraph(null); setMetrics(null); setWikiSlug(null)
    refresh(activeId)
  }, [activeId, refresh])

  // Poll only while something is actually moving, and stop when it settles — an
  // idle project should not generate traffic forever.
  const outstanding = status
    ? status.total_files -
      ((status.files_by_status?.published || 0) + (status.files_by_status?.error || 0))
    : 0
  const working = outstanding > 0 || (status?.active_jobs?.length || 0) > 0

  const pollRef = useRef(null)
  useEffect(() => {
    window.clearInterval(pollRef.current)
    if (!activeId || !working) return
    pollRef.current = window.setInterval(() => refresh(activeId), POLL_MS)
    return () => window.clearInterval(pollRef.current)
  }, [activeId, working, refresh])

  // Lazily fetch the tab-specific things.
  useEffect(() => {
    if (!activeId) return
    if (tab === 'graph' && !graph) api.graph(activeId).then(setGraph).catch(() => {})
    if (tab === 'metrics') api.metrics(activeId).then(setMetrics).catch(() => {})
  }, [tab, activeId, graph])

  // --- actions --------------------------------------------------------------
  const withBusy = async (work, done) => {
    setBusy(true)
    try {
      const result = await work()
      if (done) notify(done(result))
      await refresh(activeId)
      return result
    } catch (cause) {
      notify(cause.message, true)
    } finally {
      setBusy(false)
    }
  }

  const createProject = async () => {
    const name = window.prompt('Name this wiki')
    if (!name?.trim()) return
    await withBusy(
      async () => {
        const project = await api.createProject({ name: name.trim() })
        const list = await api.listProjects()
        setProjects(list.projects || [])
        setActiveId(project.id)
        return project
      },
      (project) => `“${project.name}” created. Add documents to fill it.`,
    )
  }

  const upload = async (chosen) => {
    const form = new FormData()
    chosen.forEach((file) => form.append('files', file))
    const result = await withBusy(() => api.upload(activeId, form))
    if (result) {
      const ok = result.uploaded?.length || 0
      const bad = result.rejected || []
      notify(
        bad.length
          ? `${ok} queued. Skipped: ${bad.map((r) => `${r.filename} (${r.reason})`).join(', ')}`
          : `${ok} file${ok === 1 ? '' : 's'} queued for the forge.`,
        bad.length > 0,
      )
      setTab('pipeline')
    }
  }

  const openPage = (slug) => {
    setWikiSlug(slug)
    setTab('wiki')
  }

  // --- render ---------------------------------------------------------------
  if (booting) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', height: '100%', gap: 14 }}>
        <div style={{ color: 'var(--ember)' }}><Icon name="forge" s={34} /></div>
        <Spinner s={19} />
      </div>
    )
  }

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <div className="brand-mark">
            <span style={{ color: 'var(--ember)' }}><Icon name="forge" s={21} /></span>
            <h1>Wiki<em>Forge</em></h1>
          </div>
          <div className="brand-tag">documents in · a wiki out</div>
        </div>

        <div className="rail-scroll">
          <div className="rail-head">
            <span className="eyebrow">Projects</span>
            <button className="btn btn-ghost btn-sm" onClick={createProject} disabled={busy} title="New project">
              <Icon name="plus" s={13} />
            </button>
          </div>

          {projects.map((project) => (
            <button
              key={project.id}
              className={`proj${project.id === activeId ? ' on' : ''}`}
              onClick={() => setActiveId(project.id)}
            >
              <div className="proj-name">{project.name}</div>
              <div className="proj-meta">
                {project.file_count} file{project.file_count === 1 ? '' : 's'} · {project.page_count} page{project.page_count === 1 ? '' : 's'}
              </div>
            </button>
          ))}

          {!projects.length && (
            <div className="faint" style={{ padding: '10px 12px', fontSize: 12.5 }}>
              No projects yet.
            </div>
          )}
        </div>

        <div className="rail-foot">
          <div className="eyebrow" style={{ marginBottom: 5 }}>
            {claims?.name || 'Anonymous'}
          </div>
          <div className="mono faint" style={{ fontSize: 10.5 }}>
            {caps?.llm_available ? 'model ready' : 'no model configured'}
            {claims?.tier ? ` · ${claims.tier}` : ''}
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          {active ? (
            <>
              <h2>{active.name}</h2>
              <span className={`pill pill-${active.status === 'error' ? 'bad' : working ? 'hot' : 'ok'}`}>
                <i className={working ? 'pulse' : ''} />
                {working ? 'forging' : active.status}
              </span>
              <nav className="tabs">
                {TABS.map((entry) => (
                  <button
                    key={entry.id}
                    className={`tab${tab === entry.id ? ' on' : ''}`}
                    onClick={() => setTab(entry.id)}
                  >
                    {entry.label}
                  </button>
                ))}
              </nav>
            </>
          ) : (
            <h2>WikiForge</h2>
          )}
        </header>

        <div className="pane">
          <div className="pane-inner">
            {!active && (
              <Empty
                icon="forge"
                title="Start a wiki"
                action={
                  <button className="btn btn-hot" onClick={createProject}>
                    <Icon name="plus" s={14} /> New project
                  </button>
                }
              >
                A project binds a folder of documents to a generated wiki. Drop in
                Markdown, Word, PDF, Excel or CSV files and each one is read,
                classified, written up and cross-linked.
              </Empty>
            )}

            {active && tab === 'pipeline' && (
              <PipelineView
                status={status} jobs={jobs} busy={busy}
                onRebuild={() =>
                  withBusy(() => api.rebuild(active.id), (r) => `Rebuilding ${r.total_files} file(s).`)}
              />
            )}

            {active && tab === 'files' && (
              <FilesView
                files={files} extensions={caps?.supported_extensions} busy={busy}
                onUpload={upload}
                onSync={() =>
                  withBusy(() => api.sync(active.id), (r) =>
                    `${r.new_files} new, ${r.modified_files} changed, ${r.deleted_files} gone.`)}
                onDelete={(file) => {
                  if (!window.confirm(`Delete ${file.filename} and its wiki page?`)) return
                  withBusy(() => api.deleteFile(active.id, file.id), () => 'Deleted.')
                }}
                onReprocess={(file) =>
                  withBusy(() => api.reprocess(active.id, file.id), () => `${file.filename} re-queued.`)}
              />
            )}

            {active && tab === 'wiki' && (
              <WikiView
                api={api} projectId={active.id} pages={pages}
                onToast={notify} initialSlug={wikiSlug}
              />
            )}

            {active && tab === 'graph' && <GraphView graph={graph} onOpen={openPage} />}

            {active && tab === 'ask' && (
              <AskView
                api={api} projectId={active.id} pageCount={pages.length}
                llmAvailable={caps?.llm_available} onToast={notify} onOpenPage={openPage}
              />
            )}

            {active && tab === 'metrics' && <MetricsView metrics={metrics} />}
          </div>
        </div>
      </main>

      <Toast message={toast?.message} bad={toast?.bad} onClose={() => setToast(null)} />
    </div>
  )
}
