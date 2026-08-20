/**
 * Two-way sync between the local vault and a WikiForge project.
 *
 * The model is deliberately the simplest one that cannot lose work:
 *
 *   For each note we remember the hash it had the last time local and remote
 *   agreed (`syncedHash`). Comparing that baseline against the current local hash
 *   and the current remote hash tells us who changed since, which a plain
 *   local-vs-remote comparison cannot.
 *
 *     local == remote                  → nothing to do
 *     only local moved                 → push
 *     only remote moved                → pull
 *     both moved                       → CONFLICT
 *     new locally                      → push
 *     new remotely                     → pull
 *     gone locally, unchanged remotely → delete remote
 *     gone remotely, unchanged locally → delete local
 *
 * A conflict is never resolved by guessing. The remote copy is written beside the
 * local one as `name (server copy).md` and both are left for the user, because
 * silently overwriting somebody's notes is the one unrecoverable outcome here.
 */

export const CONFLICT_SUFFIX = ' (server copy)'

/** SHA-256 of a string, matching what the server and the Rust side compute. */
export async function hashText(text) {
  const bytes = new TextEncoder().encode(text)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/**
 * Work out what to do, without doing any of it.
 *
 * Kept pure so the decisions can be tested and shown to the user before anything
 * is written. `state` maps note name → { fileId, syncedHash }.
 */
export function planSync({ localNotes, remoteFiles, state }) {
  const plan = []
  const localByName = new Map(localNotes.map((note) => [note.name, note]))
  const remoteByName = new Map(
    remoteFiles
      // Only markdown participates in sync; a PDF uploaded through the web UI is
      // not something this editor should try to own.
      .filter((file) => /\.(md|markdown)$/i.test(file.filename))
      .map((file) => [file.filename, file]),
  )

  const names = new Set([...localByName.keys(), ...remoteByName.keys()])

  for (const name of names) {
    // A conflict copy is a working file, never itself synced.
    if (name.includes(CONFLICT_SUFFIX)) continue

    const local = localByName.get(name)
    const remote = remoteByName.get(name)
    const synced = state[name]?.syncedHash || null
    const fileId = state[name]?.fileId || remote?.id || null

    if (local && !remote) {
      // Never seen remotely → new. Seen before → the server copy was removed.
      plan.push(
        synced && synced === local.hash
          ? { name, action: 'delete-local', reason: 'removed on the server' }
          : { name, action: 'push', reason: synced ? 'server copy gone, keeping local' : 'new note' },
      )
      continue
    }

    if (!local && remote) {
      plan.push(
        synced && synced === remote.content_hash
          ? { name, action: 'delete-remote', fileId, reason: 'deleted locally' }
          : { name, action: 'pull', fileId, reason: synced ? 'local copy gone' : 'new on server' },
      )
      continue
    }

    if (!local || !remote) continue

    const localMoved = local.hash !== synced
    const remoteMoved = remote.content_hash !== synced

    if (local.hash === remote.content_hash) {
      // Already identical; just record the baseline so future runs are cheap.
      plan.push({ name, action: 'mark-synced', fileId, hash: local.hash })
    } else if (localMoved && remoteMoved) {
      plan.push({ name, action: 'conflict', fileId, reason: 'edited in both places' })
    } else if (localMoved) {
      plan.push({ name, action: 'push', fileId, reason: 'edited here' })
    } else {
      plan.push({ name, action: 'pull', fileId, reason: 'edited on the server' })
    }
  }

  return plan
}

/**
 * Carry out a plan. `io` supplies the side effects so this stays testable.
 *
 * Returns a per-note outcome list rather than throwing on the first failure: one
 * unreachable file should not abandon the rest of the sync.
 */
export async function runSync({ plan, state, io }) {
  const results = []
  const nextState = { ...state }

  for (const step of plan) {
    try {
      switch (step.action) {
        case 'push': {
          const text = await io.readLocal(step.name)
          const uploaded = await io.upload(step.name, text)
          nextState[step.name] = {
            fileId: uploaded?.id || step.fileId || null,
            syncedHash: await hashText(text),
          }
          results.push({ ...step, ok: true, detail: 'pushed' })
          break
        }
        case 'pull': {
          const text = await io.download(step.fileId)
          await io.writeLocal(step.name, text)
          nextState[step.name] = { fileId: step.fileId, syncedHash: await hashText(text) }
          results.push({ ...step, ok: true, detail: 'pulled' })
          break
        }
        case 'conflict': {
          const text = await io.download(step.fileId)
          const copy = step.name.replace(/\.md$/i, `${CONFLICT_SUFFIX}.md`)
          await io.writeLocal(copy, text)
          // No baseline is recorded: the conflict stays open until the user
          // resolves it, so the next sync sees it again rather than forgetting.
          results.push({
            ...step, ok: false, conflict: true,
            detail: `both changed — server copy saved as “${copy}”`,
          })
          break
        }
        case 'delete-remote': {
          if (step.fileId) await io.deleteRemote(step.fileId)
          delete nextState[step.name]
          results.push({ ...step, ok: true, detail: 'removed from server' })
          break
        }
        case 'delete-local': {
          await io.deleteLocal(step.name)
          delete nextState[step.name]
          results.push({ ...step, ok: true, detail: 'removed locally' })
          break
        }
        case 'mark-synced': {
          nextState[step.name] = { fileId: step.fileId, syncedHash: step.hash }
          results.push({ ...step, ok: true, detail: 'already in step' })
          break
        }
        default:
          break
      }
    } catch (cause) {
      results.push({ ...step, ok: false, detail: cause?.message || String(cause) })
    }
  }

  return { results, nextState }
}

export function summarise(results) {
  const count = (action) => results.filter((r) => r.action === action && r.ok).length
  return {
    pushed: count('push'),
    pulled: count('pull'),
    removed: count('delete-remote') + count('delete-local'),
    conflicts: results.filter((r) => r.conflict).length,
    failed: results.filter((r) => !r.ok && !r.conflict).length,
    unchanged: count('mark-synced'),
  }
}
