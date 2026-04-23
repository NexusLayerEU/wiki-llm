# WikiForge — Web UI Specification

## Technology

- **Framework**: React 18+ with TypeScript
- **Build**: Vite
- **Styling**: Tailwind CSS (or CSS modules)
- **State**: React Query (TanStack Query) for server state
- **Routing**: React Router v6
- **Charts**: Recharts
- **Real-time**: WebSocket via native browser API

## Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Topbar: Logo · Project Selector · + New Project · Settings  │
├────────────┬─────────────────────────────────────────────────┤
│            │                                                 │
│  Sidebar   │  Main Content Area                              │
│            │                                                 │
│  Projects  │  ┌─────────────────────────────────────────┐   │
│  - OSPD    │  │ Tab Navigation                          │   │
│  - Risk BU │  │ Dashboard|Files|Wiki|Pipeline|Monitor   │   │
│  - Infra   │  └─────────────────────────────────────────┘   │
│            │                                                 │
│  Quick     │  Tab Content (varies)                           │
│  Links     │                                                 │
│  - Monitor │                                                 │
│  - API     │                                                 │
│            │                                                 │
├────────────┤                                                 │
│  Status    │                                                 │
│  v0.1.0    │                                                 │
│  LLM: OK   │                                                 │
└────────────┴─────────────────────────────────────────────────┘
```

## Pages / Views

### 1. Dashboard (`/projects/{slug}`)

The default view when a project is selected.

**Components:**
- **Stats Cards** (4 across): Total Files, Wiki Pages, Processing, Coverage %
- **Pipeline Progress**: Visual pipeline with 7 stage indicators (done/active/pending), progress bar, ETA
- **Recent Activity Log**: Scrollable list of timestamped log entries with severity (INFO/OK/WARN/ERR)

**Data Sources:**
- `GET /api/v1/projects/{id}/status`
- `GET /api/v1/projects/{id}/metrics`
- `WS /ws/projects/{id}/events` for real-time updates

### 2. Files (`/projects/{slug}/files`)

**Components:**
- **Action Bar**: Rescan button, Add Files button (opens file picker), filter dropdowns
- **File Table**: Columns — File (icon + name), Type, Size, Modified, Status (badge), Wiki Page (link)
- **File Row Actions**: Reprocess, Delete, View parsed content

**Status Badges:**
- `Done` — Green
- `Processing` — Orange (animated)
- `Queued` — Purple
- `Error` — Red (clickable → shows error details)

**Data Sources:**
- `GET /api/v1/projects/{id}/files`
- `POST /api/v1/projects/{id}/files` (upload)
- `POST /api/v1/projects/{id}/trigger-sync`

### 3. Wiki Preview (`/projects/{slug}/wiki`)

**Layout:** Split pane — sidebar navigation tree + content viewer

**Left Pane — Navigation Tree:**
- Collapsible category sections
- Pages listed under categories/subcategories
- Active page highlighted
- Page count per category

**Right Pane — Page Content:**
- Rendered wiki page (HTML)
- Action buttons: Edit, Export, View Markdown
- Metadata banner: "Auto-generated from X files · Last updated · Sources: ..."
- Cross-references section at bottom

**Data Sources:**
- `GET /api/v1/projects/{id}/tree`
- `GET /api/v1/projects/{id}/pages/{slug}?format=html`

### 4. Pipeline (`/projects/{slug}/pipeline`)

**Components:**
- **Stage Summary**: 7 columns showing count at each stage (Ingested, Parsed, etc.)
- **Active Jobs List**: Cards showing currently processing files with progress bars, stage, token count
- **Processing Log**: Detailed log with LLM call details (tokens in/out, latency, model)

**Data Sources:**
- `GET /api/v1/projects/{id}/status`
- `GET /api/v1/projects/{id}/jobs?status=running`
- `WS /ws/projects/{id}/events`

### 5. Monitoring (`/projects/{slug}/monitoring`)

**Components:**
- **Stats Cards**: LLM Tokens Today (with cost), Avg Latency, Success Rate, Active Watchers
- **File Watcher Status**: List of watched directories with health indicator, poll interval, last check time
- **LLM Usage Chart**: Bar chart showing token usage per hour over last 24 hours (Recharts)
- **Cost Breakdown**: By provider and by pipeline stage

**Data Sources:**
- `GET /api/v1/projects/{id}/metrics?period=today`
- `GET /api/v1/projects/{id}/watcher`

### 6. Settings (`/projects/{slug}/settings`)

**Components:**
- **Form**: Editable fields for all project configuration
  - Project Name
  - Source Directory (with path validation)
  - Wiki Export Directory
  - Wiki URL (read-only, auto-populated)
  - LLM Provider (dropdown: Anthropic, Gemini, Ollama)
  - LLM Model (dropdown, filtered by provider)
  - File Watch Interval (seconds)
  - Auto-Update Mode (delta/full)
- **Actions**: Save, Reset to Defaults, Delete Project (with confirmation)

**Data Sources:**
- `GET /api/v1/projects/{id}`
- `PUT /api/v1/projects/{id}`

### 7. API Explorer (`/api-explorer`)

**Components:**
- **Endpoint List**: Grouped by category (Wiki Content, Ingestion, Pipeline, Agent)
- **Each Endpoint**: HTTP method badge + path + description
- **Interactive Testing** (stretch goal): Select endpoint, fill parameters, execute, see response
- **Example Request/Response**: Shown for the Agent RAG query endpoint

**Static content** — not connected to live API. Acts as documentation reference.

## Component Architecture

```
src/
├── App.tsx                    # Root component with routing
├── api/
│   ├── client.ts              # Axios/fetch wrapper with base URL
│   ├── projects.ts            # Project API calls
│   ├── files.ts               # File API calls
│   ├── wiki.ts                # Wiki API calls
│   ├── pipeline.ts            # Pipeline/monitoring API calls
│   └── agent.ts               # Agent API calls
├── hooks/
│   ├── useProject.ts          # React Query hook for current project
│   ├── useFiles.ts            # React Query hook for file list
│   ├── usePipelineStatus.ts   # Real-time pipeline status
│   └── useWebSocket.ts        # WebSocket connection hook
├── pages/
│   ├── Dashboard.tsx
│   ├── Files.tsx
│   ├── WikiPreview.tsx
│   ├── Pipeline.tsx
│   ├── Monitoring.tsx
│   ├── Settings.tsx
│   └── ApiExplorer.tsx
├── components/
│   ├── layout/
│   │   ├── Topbar.tsx
│   │   ├── Sidebar.tsx
│   │   └── MainLayout.tsx
│   ├── shared/
│   │   ├── StatusBadge.tsx
│   │   ├── ProgressBar.tsx
│   │   ├── LogViewer.tsx
│   │   ├── StatCard.tsx
│   │   └── FileIcon.tsx
│   ├── wiki/
│   │   ├── NavTree.tsx
│   │   ├── PageViewer.tsx
│   │   └── CrossRefLinks.tsx
│   ├── pipeline/
│   │   ├── PipelineSteps.tsx
│   │   ├── JobCard.tsx
│   │   └── StageCounter.tsx
│   └── modals/
│       ├── NewProjectModal.tsx
│       └── ConfirmDialog.tsx
└── types/
    ├── project.ts
    ├── file.ts
    ├── wiki.ts
    └── pipeline.ts
```

## Real-Time Updates

The UI subscribes to WebSocket events for the active project:

```typescript
// hooks/useWebSocket.ts
function useProjectEvents(projectId: string) {
  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/ws/projects/${projectId}/events`);

    ws.onmessage = (event) => {
      const { event: eventType, data } = JSON.parse(event.data);

      switch (eventType) {
        case "job_started":
        case "job_completed":
          // Invalidate pipeline status query
          queryClient.invalidateQueries(["pipeline-status", projectId]);
          break;
        case "page_published":
          // Invalidate wiki pages query
          queryClient.invalidateQueries(["wiki-pages", projectId]);
          break;
        case "file_detected":
          // Invalidate files query
          queryClient.invalidateQueries(["files", projectId]);
          break;
      }
    };

    return () => ws.close();
  }, [projectId]);
}
```

## Responsive Behavior

- **Desktop** (>1024px): Full layout with sidebar
- **Tablet** (768–1024px): Collapsible sidebar
- **Mobile** (<768px): Bottom navigation, stacked layout

## Accessibility

- Semantic HTML elements (nav, main, article, table)
- ARIA labels on interactive elements
- Keyboard navigation for all controls
- Color contrast ratio ≥ 4.5:1
- Status communicated via text, not color alone (badges include text labels)
