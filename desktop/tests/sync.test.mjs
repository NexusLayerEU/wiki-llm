import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
if (!globalThis.crypto) globalThis.crypto = webcrypto

const { planSync, runSync, summarise, hashText, CONFLICT_SUFFIX } =
  await import('../src/sync.js')

const H = await hashText('hello')
const H2 = await hashText('changed')
const H3 = await hashText('changed differently')

let pass = 0, fail = 0
const check = (label, fn) => {
  try { fn(); console.log(`  ok   ${label}`); pass++ }
  catch (e) { console.log(`  FAIL ${label}\n       ${e.message}`); fail++ }
}
const only = (plan, name) => plan.find(p => p.name === name)

check('new local note is pushed', () => {
  const plan = planSync({
    localNotes: [{ name: 'a.md', hash: H }], remoteFiles: [], state: {},
  })
  assert.equal(only(plan, 'a.md').action, 'push')
})

check('new remote file is pulled', () => {
  const plan = planSync({
    localNotes: [], remoteFiles: [{ id: 'f1', filename: 'a.md', content_hash: H }], state: {},
  })
  assert.equal(only(plan, 'a.md').action, 'pull')
})

check('identical copies are just marked synced', () => {
  const plan = planSync({
    localNotes: [{ name: 'a.md', hash: H }],
    remoteFiles: [{ id: 'f1', filename: 'a.md', content_hash: H }],
    state: {},
  })
  assert.equal(only(plan, 'a.md').action, 'mark-synced')
})

check('edited locally only -> push', () => {
  const plan = planSync({
    localNotes: [{ name: 'a.md', hash: H2 }],
    remoteFiles: [{ id: 'f1', filename: 'a.md', content_hash: H }],
    state: { 'a.md': { fileId: 'f1', syncedHash: H } },
  })
  assert.equal(only(plan, 'a.md').action, 'push')
})

check('edited remotely only -> pull', () => {
  const plan = planSync({
    localNotes: [{ name: 'a.md', hash: H }],
    remoteFiles: [{ id: 'f1', filename: 'a.md', content_hash: H2 }],
    state: { 'a.md': { fileId: 'f1', syncedHash: H } },
  })
  assert.equal(only(plan, 'a.md').action, 'pull')
})

check('edited in BOTH places -> conflict, never a silent overwrite', () => {
  const plan = planSync({
    localNotes: [{ name: 'a.md', hash: H2 }],
    remoteFiles: [{ id: 'f1', filename: 'a.md', content_hash: H3 }],
    state: { 'a.md': { fileId: 'f1', syncedHash: H } },
  })
  assert.equal(only(plan, 'a.md').action, 'conflict')
})

check('deleted locally, remote untouched -> delete remote', () => {
  const plan = planSync({
    localNotes: [], remoteFiles: [{ id: 'f1', filename: 'a.md', content_hash: H }],
    state: { 'a.md': { fileId: 'f1', syncedHash: H } },
  })
  assert.equal(only(plan, 'a.md').action, 'delete-remote')
})

check('deleted locally BUT remote changed -> pull it back, do not delete', () => {
  const plan = planSync({
    localNotes: [], remoteFiles: [{ id: 'f1', filename: 'a.md', content_hash: H2 }],
    state: { 'a.md': { fileId: 'f1', syncedHash: H } },
  })
  assert.equal(only(plan, 'a.md').action, 'pull')
})

check('deleted remotely, local untouched -> delete local', () => {
  const plan = planSync({
    localNotes: [{ name: 'a.md', hash: H }], remoteFiles: [],
    state: { 'a.md': { fileId: 'f1', syncedHash: H } },
  })
  assert.equal(only(plan, 'a.md').action, 'delete-local')
})

check('deleted remotely BUT local changed -> keep local, push it', () => {
  const plan = planSync({
    localNotes: [{ name: 'a.md', hash: H2 }], remoteFiles: [],
    state: { 'a.md': { fileId: 'f1', syncedHash: H } },
  })
  assert.equal(only(plan, 'a.md').action, 'push')
})

check('non-markdown remote files are ignored', () => {
  const plan = planSync({
    localNotes: [],
    remoteFiles: [{ id: 'f1', filename: 'report.pdf', content_hash: H }],
    state: {},
  })
  assert.equal(plan.length, 0)
})

check('conflict copies are never themselves synced', () => {
  const plan = planSync({
    localNotes: [{ name: `a${CONFLICT_SUFFIX}.md`, hash: H }], remoteFiles: [], state: {},
  })
  assert.equal(plan.length, 0)
})

// --- runSync side effects -------------------------------------------------
check('conflict writes a server copy and leaves the baseline open', async () => {
  const written = {}
  const plan = [{ name: 'a.md', action: 'conflict', fileId: 'f1' }]
  const { results, nextState } = await runSync({
    plan, state: { 'a.md': { fileId: 'f1', syncedHash: H } },
    io: {
      download: async () => 'server text',
      writeLocal: async (n, t) => { written[n] = t },
      readLocal: async () => '', upload: async () => ({}),
      deleteRemote: async () => {}, deleteLocal: async () => {},
    },
  })
  assert.equal(written[`a${CONFLICT_SUFFIX}.md`], 'server text')
  assert.equal(results[0].conflict, true)
  // baseline must be untouched so the conflict resurfaces next run
  assert.equal(nextState['a.md'].syncedHash, H)
})

check('one failing note does not abandon the rest', async () => {
  const plan = [
    { name: 'bad.md', action: 'push' },
    { name: 'good.md', action: 'push' },
  ]
  const { results } = await runSync({
    plan, state: {},
    io: {
      readLocal: async (n) => { if (n === 'bad.md') throw new Error('disk error'); return 'ok' },
      upload: async () => ({ id: 'f9' }),
      download: async () => '', writeLocal: async () => {},
      deleteRemote: async () => {}, deleteLocal: async () => {},
    },
  })
  assert.equal(results.find(r => r.name === 'bad.md').ok, false)
  assert.equal(results.find(r => r.name === 'good.md').ok, true)
  assert.equal(summarise(results).pushed, 1)
  assert.equal(summarise(results).failed, 1)
})

await new Promise(r => setTimeout(r, 30))
console.log(`\n  ${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
