import { useEffect, useMemo, useState } from 'react'
import { Empty, Icon, Spinner, fmtWhen } from './bits'

/** The wiki reader: category tree on the left, the page on the right. */
export function WikiView({ api, projectId, pages, onToast, initialSlug }) {
  const [slug, setSlug] = useState(null)
  const [page, setPage] = useState(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState('')

  const byCategory = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const shown = needle
      ? pages.filter((p) =>
          `${p.title} ${p.category} ${p.snippet}`.toLowerCase().includes(needle))
      : pages
    const groups = new Map()
    for (const item of shown) {
      if (!groups.has(item.category)) groups.set(item.category, [])
      groups.get(item.category).push(item)
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [pages, filter])

  // Open the first page automatically; a reader with nothing in it looks broken.
  useEffect(() => {
    if (!slug && pages.length) setSlug(pages[0].slug)
  }, [pages, slug])

  // Arriving from a citation in Ask, or a node in the graph, opens that page.
  useEffect(() => {
    if (initialSlug) setSlug(initialSlug)
  }, [initialSlug])

  useEffect(() => {
    if (!slug) return
    let cancelled = false
    setLoading(true)
    api.getPage(projectId, slug)
      .then((data) => { if (!cancelled) setPage(data) })
      .catch((cause) => { if (!cancelled) onToast(cause.message, true) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [slug, projectId, api, onToast])

  if (!pages.length) {
    return (
      <Empty icon="book" title="The wiki is empty">
        Once a document finishes the pipeline its page appears here, cross-linked to
        everything related.
      </Empty>
    )
  }

  return (
    <div className="reader rise">
      <aside className="toc">
        <div style={{ position: 'relative', marginBottom: 16 }}>
          <span style={{ position: 'absolute', left: 10, top: 9, color: 'var(--bone-faint)' }}>
            <Icon name="search" s={13} />
          </span>
          <input
            className="field" placeholder="Filter pages" value={filter}
            onChange={(event) => setFilter(event.target.value)}
            style={{ paddingLeft: 31, fontSize: 12.5 }}
          />
        </div>

        {byCategory.map(([category, items]) => (
          <div className="toc-cat" key={category}>
            <div className="eyebrow">{category}</div>
            {items.map((item) => (
              <button
                key={item.slug}
                className={`toc-link${item.slug === slug ? ' on' : ''}`}
                onClick={() => setSlug(item.slug)}
              >
                {item.title}
              </button>
            ))}
          </div>
        ))}
        {!byCategory.length && <div className="faint" style={{ padding: '0 9px' }}>Nothing matches.</div>}
      </aside>

      <article style={{ minWidth: 0 }}>
        {loading && !page && <Spinner />}
        {page && (
          <>
            <div style={{ display: 'flex', gap: 9, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
              <span className="pill pill-brass">{page.category}</span>
              {page.subcategory && <span className="pill pill-idle">{page.subcategory}</span>}
              <span className="mono faint" style={{ fontSize: 10.5 }}>
                v{page.version} · {page.word_count} words · {fmtWhen(page.updated_at)}
              </span>
              <a
                className="btn btn-sm" style={{ marginLeft: 'auto' }}
                href={`/api/v1/projects/${projectId}/pages/${page.slug}?format=md`}
                target="_blank" rel="noreferrer"
              >
                <Icon name="out" s={12} /> Markdown
              </a>
            </div>

            {/* Server-rendered and sanitised on the way in: the renderer strips
                scripts, iframes, inline handlers and javascript: URLs, because the
                content originates from a model reading user documents. */}
            <div className="prose" dangerouslySetInnerHTML={{ __html: page.content_html || '' }} />

            {!!page.cross_refs?.length && (
              <div className="panel" style={{ marginTop: 34 }}>
                <div className="panel-head">
                  <h3 style={{ fontSize: 14 }}>Related pages</h3>
                  <span className="eyebrow">{page.cross_refs.length}</span>
                </div>
                <div className="panel-body" style={{ display: 'grid', gap: 10 }}>
                  {page.cross_refs.map((ref) => (
                    <button
                      key={ref.slug}
                      onClick={() => setSlug(ref.slug)}
                      style={{
                        background: 'none', border: 0, textAlign: 'left', padding: 0,
                        display: 'flex', gap: 12, alignItems: 'baseline', color: 'inherit',
                      }}
                    >
                      <span className="mono" style={{ color: 'var(--ember)', fontSize: 11, minWidth: 34 }}>
                        {(ref.relevance * 100).toFixed(0)}%
                      </span>
                      <span>
                        <span style={{ fontWeight: 600 }}>{ref.title}</span>
                        {ref.reason && <div className="dim" style={{ fontSize: 12.5 }}>{ref.reason}</div>}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {!!page.sources?.length && (
              <div style={{ marginTop: 22, paddingTop: 14, borderTop: '1px solid var(--rule-soft)' }}>
                <div className="eyebrow" style={{ marginBottom: 7 }}>Forged from</div>
                {page.sources.map((source, index) => (
                  <div key={index} className="mono dim" style={{ fontSize: 11.5 }}>
                    {source.file}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </article>
    </div>
  )
}

/** Cross-reference graph, laid out deterministically on a circle. */
export function GraphView({ graph, onOpen }) {
  const [hover, setHover] = useState(null)

  if (!graph?.nodes?.length) {
    return (
      <Empty icon="graph" title="No graph yet">
        The graph draws itself once there are pages with cross-references between them.
      </Empty>
    )
  }

  const size = 640
  const radius = size / 2 - 74
  const centre = size / 2

  // Grouping by category before placing means related pages sit together on the
  // ring, so edges tend to be short chords instead of noise across the middle.
  const ordered = [...graph.nodes].sort((a, b) =>
    (a.category || '').localeCompare(b.category || '') || a.title.localeCompare(b.title))

  const positions = new Map()
  ordered.forEach((node, index) => {
    const angle = (index / ordered.length) * Math.PI * 2 - Math.PI / 2
    positions.set(node.slug, {
      x: centre + Math.cos(angle) * radius,
      y: centre + Math.sin(angle) * radius,
      angle,
    })
  })

  const categories = [...new Set(ordered.map((n) => n.category))]
  const hues = ['#e4622f', '#4f9e8c', '#c9a227', '#8a7bd8', '#d86f9e', '#5b9bd8']
  const colourOf = (category) => hues[categories.indexOf(category) % hues.length]

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        {categories.map((category) => (
          <span key={category} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <i style={{ width: 8, height: 8, borderRadius: 9, background: colourOf(category) }} />
            <span className="dim">{category}</span>
          </span>
        ))}
        <span className="mono faint" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {graph.nodes.length} pages · {graph.edges.length} links
        </span>
      </div>

      <div className="graph-wrap rise">
        <svg viewBox={`0 0 ${size} ${size}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
          {graph.edges.map((edge, index) => {
            const from = positions.get(edge.source)
            const to = positions.get(edge.target)
            if (!from || !to) return null
            const lit = hover === edge.source || hover === edge.target
            return (
              <path
                key={index}
                // Quadratic through the centre: a straight line between two points
                // on a circle crowds the middle; bowing them inward reads cleaner.
                d={`M${from.x} ${from.y} Q ${centre} ${centre} ${to.x} ${to.y}`}
                fill="none"
                stroke={lit ? 'var(--ember)' : 'var(--rule)'}
                strokeWidth={lit ? 1.6 : 0.7 + edge.weight}
                opacity={hover && !lit ? 0.14 : 0.75}
              />
            )
          })}

          {ordered.map((node) => {
            const at = positions.get(node.slug)
            const r = 5 + Math.min(node.degree, 6) * 1.1
            const lit = hover === node.slug
            const flip = Math.cos(at.angle) < 0
            return (
              <g
                key={node.slug} className="graph-node"
                onMouseEnter={() => setHover(node.slug)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onOpen?.(node.slug)}
                opacity={hover && !lit ? 0.35 : 1}
              >
                <circle
                  cx={at.x} cy={at.y} r={r}
                  fill={colourOf(node.category)}
                  stroke="var(--iron-900)" strokeWidth="1.5"
                />
                <text
                  x={at.x + Math.cos(at.angle) * (r + 7)}
                  y={at.y + Math.sin(at.angle) * (r + 7)}
                  fill={lit ? 'var(--bone)' : 'var(--bone-dim)'}
                  fontSize="10.5"
                  fontFamily="IBM Plex Mono, monospace"
                  textAnchor={flip ? 'end' : 'start'}
                  dominantBaseline="middle"
                >
                  {node.title.length > 26 ? `${node.title.slice(0, 25)}…` : node.title}
                </text>
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}
