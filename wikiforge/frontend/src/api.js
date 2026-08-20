/**
 * API client.
 *
 * The SSO token is read from the same localStorage keys the other NexusLayer
 * products write, and from `?sso_token=` on the URL, which is how the identity
 * server hands a session over on redirect.
 */
const TOKEN_KEYS = ['wf_token', 'ids_token', 'jwt', 'nl_token']

export function captureTokenFromUrl() {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('sso_token')
  if (!token) return
  localStorage.setItem('wf_token', token)
  // Drop the token from the address bar so it is not left in history or copied
  // into a shared link.
  params.delete('sso_token')
  const query = params.toString()
  window.history.replaceState({}, '', window.location.pathname + (query ? `?${query}` : ''))
}

export function getToken() {
  for (const key of TOKEN_KEYS) {
    const value = localStorage.getItem(key)
    if (value) return value
  }
  return ''
}

export function readClaims() {
  const token = getToken()
  if (!token) return null
  try {
    const payload = token.split('.')[1]
    return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
  } catch {
    return null
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }

  let response
  try {
    response = await fetch(path, { ...options, headers })
  } catch (cause) {
    throw new ApiError('Could not reach the server.', 0)
  }

  if (response.status === 204) return null

  const isJson = (response.headers.get('content-type') || '').includes('json')
  const payload = isJson ? await response.json() : await response.text()

  if (!response.ok) {
    const detail =
      (isJson && (payload?.detail || payload?.error?.message)) ||
      (typeof payload === 'string' ? payload.slice(0, 200) : '') ||
      `Request failed (${response.status})`
    throw new ApiError(
      typeof detail === 'string' ? detail : JSON.stringify(detail),
      response.status,
    )
  }
  return payload
}

const json = (body) => ({ body: JSON.stringify(body) })

export const api = {
  health: () => request('/health'),
  capabilities: () => request('/capabilities'),

  listProjects: () => request('/api/v1/projects'),
  createProject: (body) => request('/api/v1/projects', { method: 'POST', ...json(body) }),
  updateProject: (id, body) => request(`/api/v1/projects/${id}`, { method: 'PUT', ...json(body) }),
  deleteProject: (id) => request(`/api/v1/projects/${id}`, { method: 'DELETE' }),
  rebuild: (id) => request(`/api/v1/projects/${id}/rebuild`, { method: 'POST' }),
  sync: (id) => request(`/api/v1/projects/${id}/trigger-sync`, { method: 'POST' }),

  listFiles: (id, params = '') => request(`/api/v1/projects/${id}/files?${params}`),
  upload: (id, formData) =>
    request(`/api/v1/projects/${id}/files`, { method: 'POST', body: formData }),
  deleteFile: (id, fileId) =>
    request(`/api/v1/projects/${id}/files/${fileId}`, { method: 'DELETE' }),
  reprocess: (id, fileId) =>
    request(`/api/v1/projects/${id}/files/${fileId}/reprocess`, { method: 'POST' }),

  listPages: (id) => request(`/api/v1/projects/${id}/pages`),
  getPage: (id, slug) => request(`/api/v1/projects/${id}/pages/${slug}?format=json`),
  tree: (id) => request(`/api/v1/projects/${id}/tree`),
  graph: (id) => request(`/api/v1/projects/${id}/graph`),
  search: (id, q) =>
    request(`/api/v1/projects/${id}/search?q=${encodeURIComponent(q)}&max_results=10`),

  status: (id) => request(`/api/v1/projects/${id}/status`),
  jobs: (id, params = 'limit=40') => request(`/api/v1/projects/${id}/jobs?${params}`),
  metrics: (id, period = 'all') => request(`/api/v1/projects/${id}/metrics?period=${period}`),

  ask: (body) => request('/api/v1/agent/query', { method: 'POST', ...json(body) }),
}
