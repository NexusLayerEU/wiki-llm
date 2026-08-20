import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { open as openDialog } from '@tauri-apps/plugin-dialog'
import { marked } from 'marked'
import { Icon, Spinner, Toast, when } from './components/bits'
import { Settings, SyncReport } from './components/Settings'
import { makeClient } from './wikiforge'
import { hashText, planSync, runSync, summarise } from './sync'

const STARTER = `# New note\n\nStart writing. This file lives in your notes folder as plain Markdown.\n`

/** Autosave delay. Long enough not to write on every keystroke, short enough
    that closing the app never loses more than a sentence. */
const SAVE_AFTER_MS = 700

export default function App() {
  const [settings, setSettings] = useState(null)
  const [showSettings, setShowSettings] = useState(false)

  const [projects, setProjects] = useState([])   // { slug, name, remoteId }
  const [project, setProject] = useState(null)
  const [notes, setNotes] = useState([])
  const [active, setActive] = useState(null)     // note name

  const [text, setText] = useState('')
  const [savedHash, setSavedHash] = useState('')
  const [syncState, setSyncState] = useState({})
  const [preview, setPreview] = useState(true)

  const [busy, setBusy] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [report, setReport] = useState(null)
  const [toast, setToast] = useState(null)

  const say = useCallback((textValue, bad = false) => {
    setToast({ text: textValue, bad })
    window.clearTimeout(say.timer)
    say.timer = window.setTimeout(() => setToast(null), bad ? 6500 : 2800)
  }, [])

  const client = useMemo(
    () => (settings?.url ? makeClient(settings) : null),
    [settings],
  )

  // --- boot -----------------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const raw = await invoke('load_settings')
        const loaded = JSON.parse(raw || '{}')
        if (!loaded.vault) loaded.vault = await invoke('default_vault')
        if (!loaded.url) loaded.url = 'https://wikillm.nexuslayer.eu'
        if (!loaded.projects) loaded.projects = []
        setSettings(loaded)
        setProjects(loaded.projects)
        if (loaded.projects.length) setProject(loaded.projects[0])
        // First run has no server address confirmed and no token — say so once
        // rather than failing silently on the first sync.
        if (!loaded.token) setShowSettings(true)
      } catch (cause) {
        say(`Could not load settings: ${cause}`, true)
      }
    })()
  }, [say])

  const persist = useCallback(async (next) => {
    setSettings(next)
    try {
      await invoke('save_settings', { settings: JSON.stringify(next, null, 2) })
    } catch (cause) {
      say(`Could not save settings: ${cause}`, true)
    }
  }, [say])

  // --- notes ---------------------------------------------------------------
  const refreshNotes = useCallback(async (which = project) => {
    if (!settings?.vault || !which) return []
    try {
      const found = await invoke('list_notes', { vault: settings.vault, project: which.slug })
      setNotes(found)
      const raw = await invoke('read_sync_state', { vault: settings.vault, project: which.slug })
      setSyncState(JSON.parse(raw || '{}'))
      return found
    } catch (cause) {
      say(String(cause), true)
      return []
    }
  }, [settings, project, say])

  useEffect(() => {
    if (!project) return
    setActive(null)
    setText('')
    refreshNotes(project).then((found) => {
      if (found.length) openNote(found[0].name, found)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.slug, settings?.vault])

  const openNote = useCallback(async (name, list = notes) => {
    if (!settings?.vault || !project) return
    try {
      const body = await invoke('read_note', {
        vault: settings.vault, project: project.slug, name,
      })
      setActive(name)
      setText(body)
      setSavedHash(await hashText(body))
    } catch (cause) {
      say(String(cause), true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings, project, notes, say])

  // Autosave. The timer is keyed on the note so switching notes cannot flush one
  // note's text into another's file.
  const saveTimer = useRef(null)
  useEffect(() => {
    if (!active || !settings?.vault || !project) return
    window.clearTimeout(saveTimer.current)
    const name = active
    const body = text
    saveTimer.current = window.setTimeout(async () => {
      const hash = await hashText(body)
      if (hash === savedHash) return
      try {
        await invoke('write_note', {
          vault: settings.vault, project: project.slug, name, content: body,
        })
        setSavedHash(hash)
        setNotes((current) =>
          current.map((note) =>
            note.name === name
              ? { ...note, hash, size: body.length, modified: Date.now() / 1000 }
              : note))
      } catch (cause) {
        say(String(cause), true)
      }
    }, SAVE_AFTER_MS)
    return () => window.clearTimeout(saveTimer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, active, settings?.vault, project?.slug])

  const newNote = async () => {
    if (!project) return say('Create a project first.', true)
    const name = window.prompt('Note name', 'Untitled')
    if (!name?.trim()) return
    try {
      const note = await invoke('write_note', {
        vault: settings.vault, project: project.slug,
        name: name.trim(), content: STARTER,
      })
      await refreshNotes()
      openNote(note.name)
    } catch (cause) {
      say(String(cause), true)
    }
  }

  const renameActive = async (to) => {
    if (!active || !to.trim() || to === active) return
    try {
      const note = await invoke('rename_note', {
        vault: settings.vault, project: project.slug, from: active, to: to.trim(),
      })
      // The old name's sync baseline no longer applies; drop it so the renamed
      // note is treated as new rather than compared against a stale hash.
      const next = { ...syncState }
      delete next[active]
      await invoke('write_sync_state', {
        vault: settings.vault, project: project.slug, state: JSON.stringify(next),
      })
      setSyncState(next)
      await refreshNotes()
      setActive(note.name)
      say(`Renamed to ${note.name}`)
    } catch (cause) {
      say(String(cause), true)
    }
  }

  const deleteActive = async () => {
    if (!active) return
    if (!window.confirm(`Delete “${active}”? The next sync removes it from the server too.`)) return
    try {
      await invoke('delete_note', { vault: settings.vault, project: project.slug, name: active })
      setActive(null)
      setText('')
      await refreshNotes()
      say('Deleted.')
    } catch (cause) {
      say(String(cause), true)
    }
  }

  // --- projects ------------------------------------------------------------
  const newProject = async () => {
    const name = window.prompt('Project name')
    if (!name?.trim()) return
    setBusy(true)
    try {
      let remoteId = null
      let slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
      if (client && settings.token) {
        // Prefer the server's slug so the local folder and the remote project
        // agree; falling back to a local slug keeps the app usable offline.
        const created = await client.createProject(name.trim())
        remoteId = created.id
        slug = created.slug || slug
      }
      const entry = { slug, name: name.trim(), remoteId }
      const next = { ...settings, projects: [...(settings.projects || []), entry] }
      await persist(next)
      setProjects(next.projects)
      setProject(entry)
      say(remoteId ? `“${entry.name}” created here and on the server.` : `“${entry.name}” created locally.`)
    } catch (cause) {
      say(String(cause), true)
    } finally {
      setBusy(false)
    }
  }

  /** Match a local project to a server project, creating it if missing. */
  const ensureRemote = async (which) => {
    if (which.remoteId) return which.remoteId
    const { projects: remote } = await client.listProjects()
    const found = remote.find((p) => p.slug === which.slug || p.name === which.name)
    const remoteId = found ? found.id : (await client.createProject(which.name)).id
    const next = {
      ...settings,
      projects: settings.projects.map((p) => (p.slug === which.slug ? { ...p, remoteId } : p)),
    }
    await persist(next)
    setProjects(next.projects)
    setProject({ ...which, remoteId })
    return remoteId
  }

  // --- sync ----------------------------------------------------------------
  const sync = async () => {
    if (!client || !settings.token) {
      setShowSettings(true)
      return say('Add your server address and token first.', true)
    }
    if (!project) return say('Nothing to sync — create a project first.', true)

    setSyncing(true)
    try {
      // Flush any pending autosave so a just-typed edit is not left behind.
      window.clearTimeout(saveTimer.current)
      if (active) {
        await invoke('write_note', {
          vault: settings.vault, project: project.slug, name: active, content: text,
        })
        setSavedHash(await hashText(text))
      }

      const remoteId = await ensureRemote(project)
      const localNotes = await invoke('list_notes', {
        vault: settings.vault, project: project.slug,
      })
      const { files } = await client.listFiles(remoteId)

      const plan = planSync({ localNotes, remoteFiles: files, state: syncState })
      const { results, nextState } = await runSync({
        plan, state: syncState,
        io: {
          readLocal: (name) =>
            invoke('read_note', { vault: settings.vault, project: project.slug, name }),
          writeLocal: (name, content) =>
            invoke('write_note', { vault: settings.vault, project: project.slug, name, content }),
          deleteLocal: (name) =>
            invoke('delete_note', { vault: settings.vault, project: project.slug, name }),
          download: (fileId) => client.fileContent(remoteId, fileId),
          deleteRemote: (fileId) => client.deleteFile(remoteId, fileId),
          upload: async (name, body) => {
            const response = await client.upload(remoteId, name, body)
            return response?.uploaded?.[0] || null
          },
        },
      })

      await invoke('write_sync_state', {
        vault: settings.vault, project: project.slug, state: JSON.stringify(nextState, null, 2),
      })
      setSyncState(nextState)
      const found = await refreshNotes()
      // Reopen the current note if the sync rewrote it underneath us.
      if (active && found.some((n) => n.name === active)) await openNote(active, found)

      const summary = summarise(results)
      setReport({ results: results.filter((r) => r.action !== 'mark-synced'), summary })
    } catch (cause) {
      say(String(cause?.message || cause), true)
    } finally {
      setSyncing(false)
    }
  }

  const pickVault = async () => {
    const picked = await openDialog({ directory: true, multiple: false, title: 'Choose a notes folder' })
    return typeof picked === 'string' ? picked : null
  }

  // Cmd/Ctrl+S syncs, Cmd/Ctrl+N is a new note — the two things done most often.
  useEffect(() => {
    const onKey = (event) => {
      const meta = event.metaKey || event.ctrlKey
      if (!meta) return
      if (event.key === 's') { event.preventDefault(); sync() }
      if (event.key === 'n') { event.preventDefault(); newNote() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sync, newNote])

  const dirty = useMemo(() => {
    const set = new Set()
    for (const note of notes) {
      const baseline = syncState[note.name]?.syncedHash
      if (baseline !== note.hash) set.add(note.name)
    }
    return set
  }, [notes, syncState])

  const html = useMemo(() => {
    try {
      return marked.parse(text || '', { breaks: true, gfm: true })
    } catch {
      return '<p>Could not render this note.</p>'
    }
  }, [text])

  if (!settings) {
    return <div className="empty"><Spinner s={20} /></div>
  }

  return (
    <>
      <div className={`app${preview ? '' : ''}`}>
        {/* projects ------------------------------------------------------- */}
        <aside className="col col-projects">
          <div className="col-head">
            <div className="brand">
              <span style={{ color: 'var(--jade)' }}><Icon name="forge" s={17} /></span>
              <h1>Wiki<em>Forge</em></h1>
            </div>
          </div>
          <div className="col-body">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '2px 8px 8px' }}>
              <span className="eyebrow">Projects</span>
              <button className="btn btn-icon" onClick={newProject} disabled={busy} title="New project">
                <Icon name="plus" s={14} />
              </button>
            </div>
            {projects.map((entry) => (
              <button
                key={entry.slug}
                className={`row${project?.slug === entry.slug ? ' on' : ''}`}
                onClick={() => setProject(entry)}
              >
                <div className="row-title">{entry.name}</div>
                <div className="row-sub">
                  {entry.remoteId
                    ? <><i className="dot dot-synced" /> linked</>
                    : <><i className="dot dot-dirty" /> local only</>}
                </div>
              </button>
            ))}
            {!projects.length && (
              <div className="muted" style={{ padding: '8px 10px', fontSize: 12.5 }}>
                No projects yet.
              </div>
            )}
          </div>
          <div className="col-foot" style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-sm" style={{ flex: 1 }} onClick={() => setShowSettings(true)}>
              <Icon name="cog" s={13} /> Settings
            </button>
          </div>
        </aside>

        {/* notes ---------------------------------------------------------- */}
        <aside className="col col-notes">
          <div className="col-head">
            <span className="eyebrow" style={{ flex: 1 }}>
              {project ? `${notes.length} note${notes.length === 1 ? '' : 's'}` : 'No project'}
            </span>
            <button className="btn btn-icon" onClick={newNote} disabled={!project} title="New note (⌘N)">
              <Icon name="plus" s={14} />
            </button>
            <button className="btn btn-icon" onClick={sync} disabled={syncing || !project} title="Sync (⌘S)">
              {syncing ? <Spinner s={14} /> : <Icon name="sync" s={14} />}
            </button>
          </div>
          <div className="col-body">
            {notes.map((note) => (
              <button
                key={note.name}
                className={`row${active === note.name ? ' on' : ''}`}
                onClick={() => openNote(note.name)}
              >
                <div className="row-title">{note.name.replace(/\.md$/i, '')}</div>
                <div className="row-sub">
                  <i className={`dot ${note.name.includes('(server copy)')
                    ? 'dot-conflict'
                    : dirty.has(note.name) ? 'dot-dirty' : 'dot-synced'}`} />
                  {when(note.modified)}
                  <span className="sep">·</span>
                  {(note.size / 1024).toFixed(1)} KB
                </div>
              </button>
            ))}
            {project && !notes.length && (
              <div className="muted" style={{ padding: '8px 10px', fontSize: 12.5 }}>
                No notes yet. Press ⌘N.
              </div>
            )}
          </div>
        </aside>

        {/* editor --------------------------------------------------------- */}
        <main className="col">
          {active ? (
            <>
              <div className="editor-head">
                <input
                  className="title-input"
                  defaultValue={active.replace(/\.md$/i, '')}
                  key={active}
                  onBlur={(event) => renameActive(event.target.value)}
                  onKeyDown={(event) => event.key === 'Enter' && event.currentTarget.blur()}
                  aria-label="Note name"
                />
                {dirty.has(active) && <span className="eyebrow" style={{ color: 'var(--amber)' }}>unsynced</span>}
                <button className="btn btn-icon" onClick={() => setPreview((p) => !p)}
                  title={preview ? 'Hide preview' : 'Show preview'}>
                  <Icon name="eye" s={15} />
                </button>
                <button className="btn btn-icon" onClick={deleteActive} title="Delete note">
                  <Icon name="trash" s={15} />
                </button>
              </div>

              <div className={`split ${preview ? 'both' : 'one'}`}>
                <textarea
                  className="pad selectable"
                  value={text}
                  spellCheck="false"
                  onChange={(event) => setText(event.target.value)}
                  placeholder="Write in Markdown…"
                />
                {preview && (
                  <div className="preview">
                    {/* marked output from the user's own notes, rendered locally
                        and never sent anywhere to be rendered. */}
                    <div className="prose selectable" dangerouslySetInnerHTML={{ __html: html }} />
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="empty">
              <div>
                <div style={{ color: 'var(--surface3)', display: 'flex', justifyContent: 'center', marginBottom: 14 }}>
                  <Icon name="note" s={40} />
                </div>
                <h2>{project ? 'No note open' : 'No project yet'}</h2>
                <p>
                  {project
                    ? 'Pick a note on the left, or press ⌘N to start one.'
                    : 'A project is a folder of Markdown notes that syncs to WikiForge as a wiki.'}
                </p>
                <button className="btn btn-hot" onClick={project ? newNote : newProject}>
                  <Icon name="plus" s={14} /> {project ? 'New note' : 'New project'}
                </button>
              </div>
            </div>
          )}

          <div className="statusbar">
            <span>{settings.vault}</span>
            <span className="sep">|</span>
            <span>{settings.token ? settings.url.replace(/^https?:\/\//, '') : 'not connected'}</span>
            <span style={{ marginLeft: 'auto' }}>
              {dirty.size ? `${dirty.size} unsynced` : 'in step'}
            </span>
            {active && <><span className="sep">|</span><span>{text.split(/\s+/).filter(Boolean).length} words</span></>}
          </div>
        </main>
      </div>

      {showSettings && (
        <Settings
          settings={settings}
          onPickVault={pickVault}
          onClose={() => setShowSettings(false)}
          onSave={async (next) => {
            await persist({ ...settings, ...next })
            setShowSettings(false)
            say('Settings saved.')
          }}
        />
      )}
      <SyncReport report={report} onClose={() => setReport(null)} />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </>
  )
}
