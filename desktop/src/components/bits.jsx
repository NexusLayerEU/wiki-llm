export function Icon({ name, s = 15 }) {
  const d = {
    forge: <path d="M3 20 L12 4 L21 20 M7.5 14h9" />,
    note: <path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9zM13 3v6h6" />,
    folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
    plus: <path d="M12 5v14M5 12h14" />,
    sync: <path d="M20 11A8 8 0 0 0 6.3 6.3L4 8.5M4 13a8 8 0 0 0 13.7 4.7L20 15.5M4 4v4.5h4.5M20 20v-4.5h-4.5" />,
    cog: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" /></>,
    trash: <path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" />,
    eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="2.6" /></>,
    check: <path d="M4 12.5l5 5L20 6.5" />,
    x: <path d="M6 6l12 12M18 6L6 18" />,
    cloud: <path d="M17.5 19a4.5 4.5 0 0 0 .5-8.98A6 6 0 0 0 6.2 10.2A3.9 3.9 0 0 0 7 19z" />,
  }[name]
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"
      style={{ flexShrink: 0 }} aria-hidden="true">
      {d}
    </svg>
  )
}

export function Spinner({ s = 14 }) {
  return (
    <svg className="spin" width={s} height={s} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.22" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

export function Toast({ toast, onClose }) {
  if (!toast) return null
  return (
    <div className={`toast${toast.bad ? ' bad' : ''}`} role="status" onClick={onClose}>
      {toast.text}
    </div>
  )
}

export const when = (secs) => {
  if (!secs) return ''
  const ago = Date.now() / 1000 - secs
  if (ago < 60) return 'just now'
  if (ago < 3600) return `${Math.floor(ago / 60)}m ago`
  if (ago < 86400) return `${Math.floor(ago / 3600)}h ago`
  return new Date(secs * 1000).toLocaleDateString()
}
