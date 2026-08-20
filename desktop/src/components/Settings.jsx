import { useState } from 'react'
import { Icon, Spinner } from './bits'
import { makeClient } from '../wikiforge'

/** Server address, token, and where notes live on disk. */
export function Settings({ settings, onSave, onClose, onPickVault }) {
  const [form, setForm] = useState(settings)
  const [probe, setProbe] = useState(null)
  const [testing, setTesting] = useState(false)

  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value })

  const test = async () => {
    setTesting(true)
    setProbe(null)
    try {
      const client = makeClient(form)
      const health = await client.health()
      // /health is open, so it proves reachability but not the token. Hitting a
      // guarded route is the only way to know the token actually works.
      await client.listProjects()
      setProbe({
        ok: true,
        text: `Connected — WikiForge ${health.version}, model ${health.llm?.model || 'unknown'}.`,
      })
    } catch (cause) {
      setProbe({ ok: false, text: cause.message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="veil" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet">
        <div className="sheet-head">
          <h2>Settings</h2>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 3 }}>
            Where your notes live, and which server they sync to.
          </div>
        </div>

        <div className="sheet-body">
          <div className="field">
            <label className="eyebrow" htmlFor="vault">Notes folder</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input id="vault" value={form.vault || ''} onChange={set('vault')}
                placeholder="~/Documents/WikiForge" className="mono" />
              <button className="btn" onClick={async () => {
                const picked = await onPickVault()
                if (picked) setForm({ ...form, vault: picked })
              }}>
                <Icon name="folder" s={13} /> Browse
              </button>
            </div>
            <div className="field-hint">
              Plain .md files, one folder per project. Open them in any editor, back
              them up, put them in git — nothing here is locked away.
            </div>
          </div>

          <div className="field">
            <label className="eyebrow" htmlFor="url">WikiForge server</label>
            <input id="url" value={form.url || ''} onChange={set('url')}
              placeholder="https://wikillm.nexuslayer.eu" className="mono" />
          </div>

          <div className="field">
            <label className="eyebrow" htmlFor="token">NexusLayer SSO token</label>
            <input id="token" type="password" value={form.token || ''} onChange={set('token')}
              placeholder="paste your SSO token" className="mono" />
            <div className="field-hint">
              The same token the other NexusLayer products use. Stored in this app's
              config folder, never in your notes folder.
            </div>
          </div>

          <div>
            <button className="btn" onClick={test} disabled={testing || !form.url}>
              {testing ? <Spinner s={13} /> : <Icon name="cloud" s={13} />}
              {testing ? 'Checking…' : 'Test connection'}
            </button>
            {probe && (
              <div style={{
                marginTop: 10, fontSize: 12.5,
                color: probe.ok ? 'var(--jade)' : 'var(--rose)',
              }}>
                {probe.text}
              </div>
            )}
          </div>
        </div>

        <div className="sheet-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-hot" onClick={() => onSave(form)}>Save</button>
        </div>
      </div>
    </div>
  )
}

/** What a sync did, per note. Shown afterwards rather than as a silent spinner. */
export function SyncReport({ report, onClose }) {
  if (!report) return null
  const { results, summary } = report
  const mark = (row) =>
    row.conflict ? { cls: 'mark-warn', glyph: '!' }
      : row.ok ? { cls: 'mark-ok', glyph: '✓' }
      : { cls: 'mark-bad', glyph: '✕' }

  return (
    <div className="veil" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet">
        <div className="sheet-head">
          <h2>Sync finished</h2>
          <div className="muted mono" style={{ fontSize: 11.5, marginTop: 5 }}>
            {summary.pushed} pushed · {summary.pulled} pulled · {summary.unchanged} unchanged
            {summary.removed ? ` · ${summary.removed} removed` : ''}
            {summary.conflicts ? ` · ${summary.conflicts} conflict` : ''}
            {summary.failed ? ` · ${summary.failed} failed` : ''}
          </div>
        </div>
        <div className="sheet-body">
          {!results.length && <div className="muted">Everything was already in step.</div>}
          {!!results.length && (
            <div className="report">
              {results.map((row, index) => {
                const m = mark(row)
                return (
                  <div className="report-row" key={index}>
                    <span className={`mark ${m.cls}`}>{m.glyph}</span>
                    <span>
                      <div style={{ fontWeight: 500 }}>{row.name}</div>
                      <div className="what">{row.detail}</div>
                    </span>
                    <span className="what">{row.action}</span>
                  </div>
                )
              })}
            </div>
          )}
          {!!summary.conflicts && (
            <div className="field-hint" style={{ color: 'var(--amber)' }}>
              A conflict means the note changed here and on the server. Nothing was
              overwritten — the server's version is saved beside yours as
              “(server copy)”. Merge them by hand, delete the copy, then sync again.
            </div>
          )}
        </div>
        <div className="sheet-foot">
          <button className="btn btn-hot" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  )
}
