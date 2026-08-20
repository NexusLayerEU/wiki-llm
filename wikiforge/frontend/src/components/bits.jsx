/** Small shared pieces: icons, pills, stats, empty states, toasts. */

/* Stroked line icons at 1.6 weight, sized by the `s` prop. Inline rather than an
   icon package — a dozen glyphs is not worth a dependency. */
export function Icon({ name, s = 15 }) {
  const paths = {
    forge: <path d="M3 20 L12 4 L21 20 M7.5 14h9" />,
    file: <path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9zM13 3v6h6" />,
    book: <path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2zM8 7h7M8 11h7" />,
    flow: <path d="M4 7h5M15 7h5M4 17h5M15 17h5M9 7a3 3 0 0 1 6 10" />,
    graph: <><circle cx="6" cy="7" r="2.4" /><circle cx="18" cy="6" r="2.4" /><circle cx="12" cy="18" r="2.4" /><path d="M8 8.5 10.5 16M16.5 8 13.5 16M8.2 6.6 15.7 6.2" /></>,
    ask: <path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z" />,
    chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
    plus: <path d="M12 5v14M5 12h14" />,
    up: <path d="M12 19V5M5 12l7-7 7 7" />,
    sync: <path d="M20 11A8 8 0 0 0 6.3 6.3L4 8.5M4 13a8 8 0 0 0 13.7 4.7L20 15.5M4 4v4.5h4.5M20 20v-4.5h-4.5" />,
    trash: <path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" />,
    search: <><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></>,
    x: <path d="M6 6l12 12M18 6L6 18" />,
    dot: <circle cx="12" cy="12" r="3.5" />,
    out: <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />,
  }
  return (
    <svg
      width={s} height={s} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      style={{ flexShrink: 0 }} aria-hidden="true"
    >
      {paths[name] || paths.dot}
    </svg>
  )
}

/* A file or project status, mapped to one of five visual tones. */
const TONE = {
  published: 'ok', active: 'ok', completed: 'ok', healthy: 'ok',
  error: 'bad', failed: 'bad',
  pending: 'idle', queued: 'idle', created: 'idle', deleted: 'idle', paused: 'idle',
}
export function StatusPill({ status, spinning = false }) {
  const known = ['ingested', 'parsed', 'extracted', 'classified', 'generated', 'crosslinked', 'running']
  const tone = TONE[status] || (known.includes(status) ? 'hot' : 'idle')
  return (
    <span className={`pill pill-${tone}`}>
      <i className={spinning || tone === 'hot' ? 'pulse' : ''} />
      {status}
    </span>
  )
}

export function Stat({ value, label, accent, sub }) {
  return (
    <div className="stat" style={accent ? { '--accent': accent } : undefined}>
      <div className="stat-num">{value}</div>
      <div className="stat-lbl eyebrow">{label}</div>
      {sub && <div className="mono faint" style={{ fontSize: 10.5, marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

export function Empty({ icon = 'forge', title, children, action }) {
  return (
    <div className="empty">
      <div style={{ color: 'var(--rule)', display: 'flex', justifyContent: 'center', marginBottom: 14 }}>
        <Icon name={icon} s={40} />
      </div>
      <h3>{title}</h3>
      <p className="dim" style={{ maxWidth: 420, margin: '0 auto 18px' }}>{children}</p>
      {action}
    </div>
  )
}

export function Spinner({ s = 15 }) {
  return (
    <svg className="spin" width={s} height={s} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.4" opacity="0.2" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  )
}

export function Toast({ message, bad, onClose }) {
  if (!message) return null
  return (
    <div className={`toast${bad ? ' bad' : ''}`} role="status">
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <div style={{ flex: 1, fontSize: 13 }}>{message}</div>
        <button className="btn-ghost btn btn-sm" onClick={onClose} aria-label="Dismiss">
          <Icon name="x" s={13} />
        </button>
      </div>
    </div>
  )
}

export const fmtBytes = (n) => {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), 3)
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`
}

export const fmtWhen = (iso) => {
  if (!iso) return '—'
  const then = new Date(iso)
  const secs = (Date.now() - then.getTime()) / 1000
  if (secs < 60) return 'just now'
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  if (secs < 604800) return `${Math.floor(secs / 86400)}d ago`
  return then.toLocaleDateString()
}
