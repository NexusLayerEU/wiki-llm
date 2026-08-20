# WikiForge Desktop

A local-first Markdown notebook that syncs to a [WikiForge](../wikiforge) server.
Notes are plain `.md` files in a folder you choose — open them in any editor, back
them up, put them in git, or stop using this app without losing anything.

Tauri v2 + React. Runs on macOS, Windows and Linux.

## Run it

```bash
npm install
npm run app          # dev, with hot reload
npm run bundle       # produce installers for the current platform
```

`npm run bundle` writes to `src-tauri/target/release/bundle/`:

| Platform | Artefacts |
|---|---|
| macOS | `WikiForge.app`, `WikiForge_<ver>_<arch>.dmg` |
| Windows | `WikiForge_<ver>_x64-setup.exe` (NSIS) |
| Linux | `.deb`, `.AppImage` |

Cross-compiling is not set up: each installer is built on its own platform. For all
three from one push, add a GitHub Actions matrix on `macos-latest`,
`windows-latest` and `ubuntu-22.04`.

## First run

Settings opens automatically when no token is stored. Fill in:

- **Notes folder** — defaults to `~/Documents/WikiForge`
- **WikiForge server** — e.g. `https://wikillm.nexuslayer.eu`
- **NexusLayer SSO token** — the same JWT the other products use

*Test connection* checks both reachability and the token, because `/health` is open
and would otherwise pass with a bad token.

## How sync works

Per note, the app remembers the hash from the last time local and remote agreed
(`syncedHash`, kept in `.wikiforge-sync.json` beside the notes). Comparing that
baseline against the current local and remote hashes says who changed:

| Situation | Action |
|---|---|
| Neither changed | nothing |
| Only local changed | push |
| Only remote changed | pull |
| **Both changed** | **conflict — nothing is overwritten** |
| New locally / remotely | push / pull |
| Deleted one side, other unchanged | delete the other side |
| Deleted one side, other *changed* | keep the surviving copy |

A conflict writes the server's version beside yours as `name (server copy).md` and
leaves both. The baseline is deliberately **not** advanced, so the conflict
resurfaces on the next sync until you resolve it by hand.

Only `.md` files sync. PDFs or spreadsheets uploaded through the web UI are left
alone — this editor does not try to own them.

## Shortcuts

`⌘/Ctrl+S` sync · `⌘/Ctrl+N` new note

## Tests

```bash
node tests/sync.test.mjs     # 14 cases, no network
WF_URL=… WF_TOKEN=… node tests/live.mjs   # end-to-end against a real server
```

`sync.js` is pure: `planSync` decides, `runSync` performs via injected IO. That
split is what makes the table above testable without a filesystem or a server.

## Requires

Server-side, two endpoints added for this client:

- `GET /api/v1/projects/{id}/files/{fid}/content` — read a note back
- `content_hash` on `GET /api/v1/projects/{id}/files` — diff without downloading

A server older than that cannot pull, only push.
