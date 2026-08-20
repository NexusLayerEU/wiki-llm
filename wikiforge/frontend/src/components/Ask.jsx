import { useState } from 'react'
import { Empty, Icon, Spinner, Stat } from './bits'

/** RAG query over the wiki. */
export function AskView({ api, projectId, pageCount, llmAvailable, onToast, onOpenPage }) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [asking, setAsking] = useState(false)

  const ask = async () => {
    const text = question.trim()
    if (!text) return
    setAsking(true)
    setAnswer(null)
    try {
      setAnswer(await api.ask({ question: text, project_id: projectId, max_results: 5 }))
    } catch (cause) {
      onToast(cause.message, true)
    } finally {
      setAsking(false)
    }
  }

  if (!pageCount) {
    return (
      <Empty icon="ask" title="Nothing to ask yet">
        Questions are answered from published wiki pages. Add a document first.
      </Empty>
    )
  }

  return (
    <div style={{ display: 'grid', gap: 20, maxWidth: 860 }}>
      <div className="rise">
        <label className="eyebrow field-lbl" htmlFor="q">Ask the wiki</label>
        <textarea
          id="q" className="ask-input" value={question}
          placeholder="How is the cluster sized? Which host runs nginx?"
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends, Shift+Enter for a newline — the convention for a box
            // whose main job is one short question.
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              ask()
            }
          }}
        />
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 12 }}>
          <button className="btn btn-hot" onClick={ask} disabled={asking || !question.trim()}>
            {asking ? <Spinner s={13} /> : <Icon name="ask" s={13} />}
            {asking ? 'Reading the wiki…' : 'Ask'}
          </button>
          <span className="mono faint" style={{ fontSize: 11 }}>
            {llmAvailable
              ? 'answered from the pages below · enter to send'
              : 'no model configured — returns matching page extracts'}
          </span>
        </div>
      </div>

      {answer && (
        <div className="panel rise">
          <div className="panel-head">
            <h3>Answer</h3>
            <span className="pill pill-brass">
              {(answer.confidence * 100).toFixed(0)}% match
            </span>
          </div>
          <div className="panel-body">
            {/* Plain text, not HTML: this is model output going straight to the
                page, so it is never treated as markup. */}
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.75, color: '#ddd4cb' }}>
              {answer.answer}
            </div>

            {!!answer.sources?.length && (
              <div style={{ marginTop: 22, paddingTop: 16, borderTop: '1px solid var(--rule-soft)' }}>
                <div className="eyebrow" style={{ marginBottom: 10 }}>Drawn from</div>
                <div style={{ display: 'grid', gap: 8 }}>
                  {answer.sources.map((source, index) => (
                    <button
                      key={index}
                      onClick={() => source.wiki_page && onOpenPage(source.wiki_page)}
                      style={{
                        background: 'none', border: 0, padding: 0, textAlign: 'left',
                        display: 'flex', gap: 12, alignItems: 'baseline', color: 'inherit',
                      }}
                    >
                      <span className="mono" style={{ color: 'var(--ember)', fontSize: 11, minWidth: 34 }}>
                        {(source.relevance * 100).toFixed(0)}%
                      </span>
                      <span className="mono" style={{ fontSize: 12 }}>{source.filename}</span>
                      {source.wiki_page && (
                        <span className="faint mono" style={{ fontSize: 11 }}>→ {source.wiki_page}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** LLM usage and cost metrics. */
export function MetricsView({ metrics }) {
  if (!metrics) return <Spinner />
  const stages = Object.entries(metrics.by_stage || {})

  if (!metrics.total_calls) {
    return (
      <Empty icon="chart" title="No model calls yet">
        Token usage per stage appears here once documents have been through the pipeline.
      </Empty>
    )
  }

  const peak = Math.max(...stages.map(([, s]) => s.tokens_in + s.tokens_out), 1)

  return (
    <div style={{ display: 'grid', gap: 20 }}>
      <div className="grid-stats rise">
        <Stat value={metrics.total_calls} label="model calls" />
        <Stat value={metrics.total_tokens_in.toLocaleString()} label="tokens in" accent="var(--brass)" />
        <Stat value={metrics.total_tokens_out.toLocaleString()} label="tokens out" accent="var(--ember)" />
        <Stat
          value={`${(metrics.avg_latency_ms / 1000).toFixed(1)}s`}
          label="avg latency" accent="var(--verdigris)"
        />
      </div>

      <div className="panel rise" style={{ animationDelay: '80ms' }}>
        <div className="panel-head">
          <h3>Tokens by stage</h3>
          <span className="eyebrow">in + out</span>
        </div>
        <div className="panel-body" style={{ display: 'grid', gap: 15 }}>
          {stages.map(([stage, data]) => {
            const total = data.tokens_in + data.tokens_out
            return (
              <div key={stage}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', marginBottom: 6 }}>
                  <span className="mono" style={{ fontSize: 12, minWidth: 92 }}>{stage}</span>
                  <span className="mono dim" style={{ fontSize: 11.5 }}>
                    {total.toLocaleString()} tok · {data.calls} call{data.calls === 1 ? '' : 's'}
                    {' · '}{(data.avg_latency_ms / 1000).toFixed(1)}s avg
                  </span>
                </div>
                {/* Two-tone bar: input tokens in brass, output in ember, so the
                    read-heavy stages are visibly different from the write-heavy ones. */}
                <div className="bar" style={{ display: 'flex', height: 7 }}>
                  <span style={{ width: `${(data.tokens_in / peak) * 100}%`, background: 'var(--brass)' }} />
                  <span style={{ width: `${(data.tokens_out / peak) * 100}%`, background: 'var(--ember)' }} />
                </div>
              </div>
            )
          })}
          <div className="mono faint" style={{ fontSize: 10.5, marginTop: 4 }}>
            Cost is not shown: SwitchBoard does not report per-call pricing, and an
            invented figure would be worse than none.
          </div>
        </div>
      </div>
    </div>
  )
}
