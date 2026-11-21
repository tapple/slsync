# AGENTS.md — slsync

Python CLI client for the Second Life viewer's editor WebSocket server.
Collaborator: tapple (she/her); learning French — occasional light French
practice/corrections are welcome. **Announce before every live probe** (she may have
things turned off in-world) and prefer read-only calls unless asked otherwise.

Formatting when replying to tapple inside pi: do NOT use markdown blockquotes
(`>`) — pi renders them with a leading pipe character, which makes paste-ready
text hard to copy. For paste-ready blocks: use fenced code blocks, and inside
them avoid indents and hard line-wrapping (write long single lines) — both make
pasting into web forms mangled.

## Where to look / where to append

| Doc | What it is | Append here for… |
|---|---|---|
| `TASKS.md` | Remaining work, phase checkboxes | new tasks; checking items off |
| `NOTES.md` | Findings, decisions, test notes, bug-report master copies | **new findings** (viewer anomalies → "Viewer bug report notes") |
| `FOLLOWUPS.md` | Known issues / verification debts outside the phased tasks | new follow-ups; resolved items move to NOTES.md |
| `ARCHITECTURE.md` | How it works, design rules, protocol gotchas | architecture changes, new spec gotchas |

Doc-invalidation rule: any task/follow-up that will change the CLI surface,
module layout, or a documented design rule MUST carry an explicit note in its
item naming which of TASKS.md / ARCHITECTURE.md (or this file) it invalidates
and what to update; when the work lands, make those doc updates in the same
change. When adding a new follow-up, check whether it invalidates a doc.

Protocol spec: `external-editor-json-rpc.md`. Reference implementation:
`../sl-vscode-plugin` (esp. `packages/sl-ide-ws-client/`).

## Quick orientation

- `cd ~/cabbage/secondlife/slsync && uv run slsync status` — sanity check.
- Viewers: **Alchemy on 9020**, **official SL viewer on 9021**
  (`--url ws://127.0.0.1:9021`, or `SLSYNC_URL`). Avatar regions vary per
  session — check the viewer log before assuming an object is addressable
  (NOTES Decisions #7).
- A persistent `slsync tail` per viewer keeps the "Explore in IDE" button working —
  start/stop commands are in NOTES.md ("Testing notes").
- Viewer logs (connection/handshake/publish lines; official 26.5.0+ logs no
  per-call RPC entries): official
  `~/.secondlife/logs/SecondLife.log`, Alchemy `~/.local/state/alchemynext/Alchemy.log`.
  Sources: official `../viewer`, Alchemy built locally from `../NewAlchemy`.
  Test objects do NOT persist between sessions; never assume an object UUID from an
  old note is still in-world.
