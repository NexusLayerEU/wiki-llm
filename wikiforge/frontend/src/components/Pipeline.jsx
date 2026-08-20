import { Icon, Spinner, StatusPill, Stat, fmtWhen } from './bits'

const STAGES = ['ingest', 'parse', 'extract', 'classify', 'generate', 'crosslink', 'publish']

/* Where a file's status sits on the seven-stage track. */
const REACHED = {
  pending: -1, ingested: 0, parsed: 1, extracted: 2,
  classified: 3, generated: 4, crosslinked: 5, published: 6,
}

/**
 * The pipeline track.
 *
 * Each stage segment shows how many files have got at least that far, so the whole
 * corpus is legible as one shape: a solid verdigris run means everything is
 * through, a ragged edge shows where work is sitting.
 */
export function Track({ filesByStatus, activeStages }) {
  const counts = Object.entries(filesByStatus || {})
  const total = counts.reduce((sum, [status, n]) => (status === 'deleted' ? sum : sum + n), 0)

  const through = STAGES.map((_, index) =>
    counts.reduce((sum, [status, n]) => {
      if (status === 'error' || status === 'deleted') return sum
      return (REACHED[status] ?? -1) >= index ? sum + n : sum
    }, 0),
  )
  const failed = filesByStatus?.error || 0

  return (
    <div className="track">
      {STAGES.map((stage, index) => {
        const done = through[index]
        const live = activeStages?.has(stage)
        const state = live ? 'live' : done > 0 && done === total - failed ? 'done' : done > 0 ? 'done' : ''
        return (
          <div key={stage} className={`track-stage ${state}`}>
            <div className="track-bar">
              <span style={state === 'done' ? { transform: `scaleX(${total ? done / (total - failed || 1) : 0})` } : undefined} />
            </div>
            <div className="track-name">{stage}</div>
            <div className="track-count">{done}{total ? `/${total - failed}` : ''}</div>
          </div>
        )
      })}
    </div>
  )
}

export function PipelineView({ status, jobs, onRebuild, busy }) {
  if (!status) return <div className="dim" style={{ padding: 30 }}><Spinner /></div>

  const activeStages = new Set((status.active_jobs || []).map((job) => job.stage))
  const errored = status.files_by_status?.error || 0

  return (
    <div style={{ display: 'grid', gap: 20 }}>
      <div className="grid-stats rise" style={{ animationDelay: '40ms' }}>
        <Stat value={status.total_files} label="files tracked" />
        <Stat
          value={status.files_by_status?.published || 0}
          label="pages published"
          accent="var(--verdigris)"
        />
        <Stat
          value={`${status.progress_pct}%`}
          label="through the forge"
          accent="var(--ember)"
          sub={status.eta_seconds ? `~${Math.ceil(status.eta_seconds / 60)} min left` : 'nothing queued'}
        />
        <Stat
          value={errored}
          label="failed"
          accent={errored ? 'var(--rust)' : undefined}
        />
      </div>

      <div className="panel rise" style={{ animationDelay: '90ms' }}>
        <div className="panel-head">
          <h3>The forge</h3>
          <span className="eyebrow">seven stages</span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            {status.queue_depth > 0 && (
              <span className="pill pill-hot"><i className="pulse" />{status.queue_depth} queued</span>
            )}
            <button className="btn btn-sm" onClick={onRebuild} disabled={busy}>
              <Icon name="sync" s={13} /> Rebuild all
            </button>
          </div>
        </div>
        <div className="panel-body">
          <Track filesByStatus={status.files_by_status} activeStages={activeStages} />
          <div className="bar" style={{ marginTop: 20 }}>
            <span style={{ width: `${status.progress_pct}%` }} />
          </div>
        </div>
      </div>

      <div className="panel rise" style={{ animationDelay: '140ms' }}>
        <div className="panel-head">
          <h3>Recent work</h3>
          <span className="eyebrow">{jobs?.length || 0} jobs</span>
        </div>
        {jobs?.length ? (
          <table className="rows">
            <thead>
              <tr>
                <th>File</th><th>Stage</th><th>Status</th><th>Took</th><th>When</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td className="cell-name">
                    {job.source_file}
                    {job.error_message && (
                      <div className="cell-sub" style={{ color: 'var(--rust)' }}>
                        {job.error_message.slice(0, 120)}
                      </div>
                    )}
                  </td>
                  <td className="mono dim" style={{ fontSize: 11.5 }}>{job.stage}</td>
                  <td><StatusPill status={job.status} spinning={job.status === 'running'} /></td>
                  <td className="mono dim" style={{ fontSize: 11.5 }}>
                    {job.duration_ms ? `${(job.duration_ms / 1000).toFixed(1)}s` : '—'}
                  </td>
                  <td className="mono faint" style={{ fontSize: 11 }}>{fmtWhen(job.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="panel-body dim">Nothing has run yet.</div>
        )}
      </div>
    </div>
  )
}
