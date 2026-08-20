import { useRef, useState } from 'react'
import { Empty, Icon, Spinner, StatusPill, fmtBytes, fmtWhen } from './bits'

/** Upload dropzone plus the file table. */
export function FilesView({ files, extensions, busy, onUpload, onDelete, onReprocess, onSync }) {
  const [over, setOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const input = useRef(null)

  const send = async (fileList) => {
    const chosen = Array.from(fileList || [])
    if (!chosen.length) return
    setUploading(true)
    try {
      await onUpload(chosen)
    } finally {
      setUploading(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div style={{ display: 'grid', gap: 20 }}>
      <div
        className={`drop rise${over ? ' over' : ''}`}
        onDragOver={(event) => { event.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault()
          setOver(false)
          send(event.dataTransfer.files)
        }}
      >
        <div style={{ color: over ? 'var(--ember)' : 'var(--rule)', display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
          <Icon name="up" s={30} />
        </div>
        <h3>Drop documents into the forge</h3>
        <p className="dim" style={{ margin: '0 0 16px' }}>
          They are parsed, read, classified and written up as wiki pages.
        </p>
        <input
          ref={input} type="file" multiple hidden
          accept={extensions?.join(',')}
          onChange={(event) => send(event.target.files)}
        />
        <div style={{ display: 'flex', gap: 9, justifyContent: 'center', flexWrap: 'wrap' }}>
          <button className="btn btn-hot" onClick={() => input.current?.click()} disabled={uploading}>
            {uploading ? <Spinner s={13} /> : <Icon name="plus" s={13} />}
            {uploading ? 'Uploading…' : 'Choose files'}
          </button>
          <button className="btn" onClick={onSync} disabled={busy}>
            <Icon name="sync" s={13} /> Re-scan directory
          </button>
        </div>
        <div className="mono faint" style={{ fontSize: 10.5, marginTop: 14 }}>
          {(extensions || []).join('  ·  ')}
        </div>
      </div>

      <div className="panel rise" style={{ animationDelay: '80ms' }}>
        <div className="panel-head">
          <h3>Source files</h3>
          <span className="eyebrow">{files?.length || 0} tracked</span>
        </div>
        {files?.length ? (
          <table className="rows">
            <thead>
              <tr><th>File</th><th>Size</th><th>Status</th><th>Page</th><th>Seen</th><th /></tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.id}>
                  <td>
                    <div className="cell-name" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span className="faint"><Icon name="file" s={13} /></span>
                      {file.filename}
                    </div>
                    {file.error_message && (
                      <div className="cell-sub" style={{ color: 'var(--rust)' }}>{file.error_message}</div>
                    )}
                  </td>
                  <td className="mono dim" style={{ fontSize: 11.5 }}>{fmtBytes(file.file_size)}</td>
                  <td><StatusPill status={file.status} /></td>
                  <td className="mono" style={{ fontSize: 11.5 }}>
                    {file.wiki_page_slug
                      ? <span style={{ color: 'var(--verdigris)' }}>{file.wiki_page_slug}</span>
                      : <span className="faint">—</span>}
                  </td>
                  <td className="mono faint" style={{ fontSize: 11 }}>{fmtWhen(file.discovered_at)}</td>
                  <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                    <button
                      className="btn btn-ghost btn-sm" title="Run the pipeline again"
                      onClick={() => onReprocess(file)} disabled={busy}
                    >
                      <Icon name="sync" s={13} />
                    </button>
                    <button
                      className="btn btn-ghost btn-sm" title="Remove this file and its page"
                      onClick={() => onDelete(file)} disabled={busy}
                    >
                      <Icon name="trash" s={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty icon="file" title="No documents yet">
            Drop a Markdown, Word, PDF, Excel or CSV file above and the pipeline starts
            immediately.
          </Empty>
        )}
      </div>
    </div>
  )
}
