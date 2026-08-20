// End-to-end: the app's own sync engine and API client against the real server,
// with the filesystem stubbed by an in-memory vault.
import { webcrypto } from 'node:crypto'
if (!globalThis.crypto) globalThis.crypto = webcrypto
const { makeClient } = await import('../src/wikiforge.js')
const { planSync, runSync, summarise, hashText } = await import('../src/sync.js')

const client = makeClient({ url: process.env.WF_URL, token: process.env.WF_TOKEN })

const vault = new Map()
const io = {
  readLocal: async (n) => vault.get(n),
  writeLocal: async (n, t) => { vault.set(n, t) },
  deleteLocal: async (n) => { vault.delete(n) },
  download: (id) => client.fileContent(PID, id),
  deleteRemote: (id) => client.deleteFile(PID, id),
  upload: async (n, body) => (await client.upload(PID, n, body))?.uploaded?.[0] || null,
}
const localNotes = async () => Promise.all(
  [...vault.entries()].map(async ([name, text]) => ({ name, hash: await hashText(text) })))

const step = async (label, state) => {
  const { files } = await client.listFiles(PID)
  const plan = planSync({ localNotes: await localNotes(), remoteFiles: files, state })
  const out = await runSync({ plan, state, io })
  const s = summarise(out.results)
  console.log(`  ${label}`)
  console.log(`     ${JSON.stringify(s)}`)
  for (const r of out.results.filter(r => r.action !== 'mark-synced'))
    console.log(`     · ${r.name}: ${r.action} — ${r.detail}`)
  return out.nextState
}

const h = await client.health()
console.log(`server: WikiForge ${h.version}, auth required=${h.auth.required}\n`)

const created = await client.createProject(`Desktop Client Test ${Date.now() % 100000}`)
const PID = created.id
console.log(`project: ${created.slug}\n`)

let state = {}
vault.set('meeting-notes.md', '# Meeting notes\n\nDiscussed the Athens migration.\n')
vault.set('todo.md', '# Todo\n\n- Rotate the SSO secret\n')
state = await step('1. push two new notes', state)

state = await step('2. no-op run (nothing changed)', state)

vault.set('todo.md', '# Todo\n\n- Rotate the SSO secret\n- Back up the wikillm volume\n')
state = await step('3. edit one note locally -> push', state)

// Simulate a second machine: drop a note locally, keep it on the server.
vault.delete('meeting-notes.md')
const before = state['meeting-notes.md']
delete state['meeting-notes.md']
state = await step('4. fresh machine (no local copy, no baseline) -> pull', state)
console.log(`     pulled back ${vault.get('meeting-notes.md')?.length} bytes`)

// Genuine conflict: change both sides away from the shared baseline.
vault.set('todo.md', '# Todo\n\nLOCAL edit\n')
await client.upload(PID, 'todo.md', '# Todo\n\nSERVER edit\n')
state = await step('5. edited in both places -> conflict, nothing lost', state)
console.log(`     local kept:  ${JSON.stringify(vault.get('todo.md'))}`)
console.log(`     server copy: ${JSON.stringify(vault.get('todo (server copy).md'))}`)

await client.deleteFile(PID, (await client.listFiles(PID)).files.find(f => f.filename === 'todo.md').id)
console.log('\ncleanup: test project left on the server as ' + created.slug)
