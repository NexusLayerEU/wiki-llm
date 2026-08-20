/** Talks to a WikiForge server. Nothing here touches the filesystem. */

export class ServerError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

export function makeClient({ url, token }) {
  const base = (url || '').replace(/\/+$/, '')

  async function call(path, options = {}) {
    if (!base) throw new ServerError('No server address set. Open Settings.', 0)
    const headers = { ...(options.headers || {}) }
    if (token) headers.Authorization = `Bearer ${token}`
    if (options.body && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json'
    }

    let response
    try {
      response = await fetch(`${base}${path}`, { ...options, headers })
    } catch {
      throw new ServerError(`Could not reach ${base}. Is the address right?`, 0)
    }

    if (response.status === 401) {
      throw new ServerError('The server rejected your token. Check Settings.', 401)
    }
    if (response.status === 204) return null

    const type = response.headers.get('content-type') || ''
    const payload = type.includes('json') ? await response.json() : await response.text()

    if (!response.ok) {
      const detail =
        (typeof payload === 'object' && (payload?.detail || payload?.error?.message)) ||
        (typeof payload === 'string' ? payload.slice(0, 180) : '')
      throw new ServerError(
        typeof detail === 'string' && detail ? detail : `Server error ${response.status}`,
        response.status,
      )
    }
    return payload
  }

  return {
    health: () => call('/health'),
    listProjects: () => call('/api/v1/projects'),
    createProject: (name) =>
      call('/api/v1/projects', { method: 'POST', body: JSON.stringify({ name }) }),
    listFiles: (projectId) => call(`/api/v1/projects/${projectId}/files?limit=500`),
    fileContent: (projectId, fileId) =>
      call(`/api/v1/projects/${projectId}/files/${fileId}/content`),
    deleteFile: (projectId, fileId) =>
      call(`/api/v1/projects/${projectId}/files/${fileId}`, { method: 'DELETE' }),
    upload: (projectId, name, text) => {
      const form = new FormData()
      form.append('files', new File([text], name, { type: 'text/markdown' }))
      return call(`/api/v1/projects/${projectId}/files`, { method: 'POST', body: form })
    },
    listPages: (projectId) => call(`/api/v1/projects/${projectId}/pages`),
    status: (projectId) => call(`/api/v1/projects/${projectId}/status`),
  }
}
