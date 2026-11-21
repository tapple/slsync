# Handoff: "Explore in IDE" — silent failure when no editor client is connected

Status: handoff brief, 2026-11-21. Written for an agent that may fix this in the
viewer source — official viewer checkout `~/cabbage/secondlife/viewer`, Alchemy
checkout `~/cabbage/secondlife/NewAlchemy` (built locally; today's builds are
official Release 26.5.1.44155260796 and Alchemy Test 26.5.1.68594). Tapple
considers this "definitely the most annoying of the bugs". Context lives in the
slsync repo `~/cabbage/secondlife/slsync` (NOTES.md bug notes B1/B6/B7,
AGENTS.md orientation, spec copy `external-editor-json-rpc.md`).

## The bug in one paragraph

The Contents floater's "Explore in IDE" button publishes the selected object to
the viewer's editor WebSocket server ONLY when at least one WebSocket client is
already connected. With no client connected, it instead tries to launch VS Code
(`code --open-url vscode://lindenlab.sl-vscode-plugin/connect?port=...&object=...`).
On this machine `code` is not installed (deliberately — see Environment), so
every such click fails SILENTLY: no dialog, no toast, no in-world feedback —
only a WARNING pair in the viewer log. The user has no idea anything was
attempted, let alone why the object was not published. Worse, each failed click
leaves the button's toggle state desynced (B7 below), so later clicks WITH a
client connected can publish/unpublish the wrong way.

## Design context (what NOT to change)

The object-explorer protocol (spec: slsync/external-editor-json-rpc.md)
publishes objects to connected editor clients. The two-branch button design is
intentional:
- client connected → toggle publish/unpublish directly (this branch WORKS on
  both viewers — verified 2026-11-19 and 2026-11-21);
- no client → launch the external editor with the object in its context.
Tapple's intended workflow is a persistent `slsync tail` client (keeps branch 1
active). The fix target is branch 2's SILENT FAILURE and the resulting toggle
desync — not the design. Do not remove or reorder branch 1.

## Root cause (source)

Official viewer, `indra/newview/llpanelcontents.cpp`:

```cpp
// L395
void LLPanelContents::onClickPublish()
{
    ...
    const LLUUID object_id = object->getID();
    if (server->getConnectionCount())
    {   // at least one connection: toggle the publish state
        if (server->isObjectPublished(object_id))
            server->unpublishObject(object_id, "user");
        else
            server->publishObject(object_id);
    }
    else
    {   // no connections: build the url and launch vscode
        LLScriptEditorWSServer::launchVSCode(object_id);   // L427 — return value IGNORED
    }
}
```

Launch failure path, `indra/newview/llscripteditorws.cpp` L371-405:

```cpp
LLProcessPtr process = LLProcess::create(params);   // params.executable = "code"
if (!process)
{
    LL_WARNS("ScriptEditorWS") << "Failed to launch VS Code. "
        << "Ensure the 'code' command is available on your PATH." << LL_ENDL;
    return false;   // <- caller ignores this; the user sees NOTHING
}
```

There is no UI feedback anywhere in the failure path. (buildVSCodeURI:
llscripteditorws.cpp L349 official / L410 Alchemy.)

### B7 — toggle-state desync after failed clicks (NEW, 2026-11-21)

The button is an XUI toggle: `floater_tools.xml` (en skin) L3094-3100:
`is_toggle="true"`, `label="Explore in IDE"`, `label_selected="Stop
Exploring"`, `name="button publish"`. Clicking a toggle flips its visual state;
the code re-syncs the toggle state from the server ONLY in the
selection/panel-update path (llpanelcontents.cpp L182):

```cpp
mPublishButton->setToggleState(server && server->isObjectPublished(objectp->getID()));
```

A failed launch-click flips the visual state but changes nothing server-side,
and nothing re-syncs afterwards → the button shows "Stop Exploring" for an
object that was never published, until some later refresh. Consequence observed
2026-11-21: after 7 failed clicks, the button needed TWO "Stop Exploring"
clicks before "Explore in IDE" became available; those two clicks actually
PUBLISHED then UNPUBLISHED the object (see Evidence).

Alchemy notes (`NewAlchemy/indra/newview/llpanelcontents.cpp`):
- Same two-branch onClickPublish (L486-530), same ignored return value (L528).
- Alchemy has an EXTRA branch the official lacks: when the WS server is
  DISABLED entirely (not merely client-less), the button routes to Script
  Studio and explicitly resets the state — L496-504:
  ```cpp
  if (!LLScriptEditorWSServer::isEnabled())
  {
      ALScriptStudio::explore(object_id);
      mPublishButton->setToggleState(false);   // state hygiene exists HERE,
      return;                                  // but is missing in the launchVSCode branch
  }
  ```
- B6 (label never swaps to "Stop Exploring" on Alchemy 26.4.0.68225): the
  2026-11-19 note cited a per-refresh `setLabel(getString(...))` overwrite.
  The CURRENT checkout uses `setLabelUnselected(getString(ide ? "ide_label"
  : "studio_label"))` (L243-246) with a comment saying setLabel would write
  over the selected label — B6 may already be fixed in current source; verify
  against a build that exhibits it before reporting.

Button gating (intentional, do not "fix"): `new_button_enabled = editable &&
all_volume && (single_root || (object_count == 1))` (L143 official) — the
button is DISABLED for multi-root selections.

## Evidence

### 2026-11-21 — official 9021 (PippinGao avatar, Equestrian), 26.5.1.44155260796
Full timeline (viewer log + slsync tail broadcasts):
- 09:05Z viewer start; nothing published (test objects are created per session
  and do NOT persist between sessions).
- 10:24:45Z, 10:27:54Z, 10:27:58Z, 10:28:01Z, 10:28:08Z, 10:28:14Z,
  10:28:17Z — SEVEN button clicks, no WebSocket client connected. Each logged:
  ```
  WARNING #LLProcess# llcommon/llprocess.cpp(736) LLProcess::launch : Could not locate 'code' on PATH -- launch will likely fail
  WARNING #ScriptEditorWS# newview/llscripteditorws.cpp(414) launchVSCode : Failed to launch VS Code. Ensure the 'code' command is available on your PATH.
  ```
  (Clicks spanned Pippin's own new prim and Tapple's prim — both named
  "Object"; cross-ownership is fine, they hold edit perms on each other's
  objects.) Nothing published; user saw zero feedback.
- 11:26:12Z — a `slsync tail` client connects (direct-publish branch active).
- 12:29:49Z PUBLISH → 12:29:51Z UNPUBLISH (user) → 12:29:52Z PUBLISH
  (slsync tail, broadcast notifications; the viewer log shows the two
  buildAndSendPublish entries but NO unpublish line — see fix #4).
  User report: the button showed "Stop Exploring" although nothing was
  published; she had to click "Stop Exploring" twice before "Explore in IDE"
  became available; the final click published. Net: 7 silent failures, then 3
  clicks (with a spurious publish/unpublish pair) to publish one object.

### 2026-11-21 — Alchemy 9020 (Tapple avatar), 26.5.1.68594
- 10:24:16Z, 10:28:34Z, 10:28:37Z — three pre-client failed clicks (same log
  pair at llprocess.cpp(738) / llscripteditorws.cpp(463)).
- 12:29:43Z — clean single-click publish after the client connected
  (buildAndSendPublish logged; tail saw `PUB Object [587338a9-...]`).
  Whether the 9020 button label was desynced at 12:29 was not observed —
  ask tapple.

### 2026-11-17/18 — original discovery (official 26.5.0, Alchemy 26.4.0)
- Every button press with no client: the log pair above, and ZERO
  buildAndSendPublish entries (only protocol probes published). Full write-up:
  slsync NOTES.md, bug note B1 (incl. why objects sometimes appeared in
  object.list — protocol `objects explore` conflated with the button).
- VS Code not installed: `code` not on PATH; Alchemy's ExternalEditor setting
  pointed at missing /usr/share/code/code. Tapple has VSCodium (provides
  `codium`, not `code`) and does NOT want the VS Code path — the connected
  client route is the intended usage.

### 2026-11-19 — the good path works (both viewers, client connected)
First press published on BOTH viewers (official 11:32:04Z, Alchemy
11:32:29Z; tails saw the object events). Branch 1 is not the problem.

### Posted reports
- Linden Lab (official viewer): item 6 of
  https://feedback.secondlife.com/slua-alpha/p/bugs-with-the-lua-plugin-websocket
  ("clicking 'Explore in IDE' does not publish unless a websocket client is
  already connected, or launching code (VS Code) succeeds — in all other cases
  the click silently does nothing").
- Alchemy report (sent to Rye, trimmed): B6 + the UX gripes (silent failure,
  no indication of which mode applies).
- B7 (toggle desync) is NEW (2026-11-21) and not posted anywhere yet.

## Proposed fixes, in priority order

1. **Visible failure (the core ask).** onClickPublish must check
   launchVSCode's return value and, on failure, tell the user — a dialog or
   floater notice stating the two conditions and remedies: (a) start a
   WebSocket client (e.g. `slsync tail`, https://github.com/tapple/slsync),
   or (b) make the external editor launchable. Log-only warnings are not
   acceptable for a primary UI action.
2. **Toggle-state hygiene (B7).** After any click that did not change the
   server-side publish state (launch failure, no-op), re-sync the button:
   `mPublishButton->setToggleState(server->isObjectPublished(object_id))`.
   Alchemy's Script-Studio branch already does `setToggleState(false)` (L503)
   — the same discipline is missing from the launchVSCode branch of BOTH
   viewers.
3. **Editor binary handling.** Validate the configured editor before launch;
   on Alchemy the ExternalEditor setting pointed at a missing binary — surface
   that specifically. (Keep `code` as the official default; the URI scheme is
   the spec contract.)
4. **Unpublish logging gap.** The 12:29:51Z unpublish produced no
   buildAndSendPublish-style log line (only the broadcast notification
   existed). Add a log line so every button action is auditable in the log.
5. **B6 (Alchemy only, if still reproducible).** Verify the label-swap fix in
   current source (setLabelUnselected, L243-246) against a build that
   exhibited it (26.4.0.68225: pressed/dark-grey state applied but label
   stayed "Explore in IDE", active colour grey instead of the bright blue of
   other active toggle buttons).

## How to verify (on this machine)

Setup: viewer build with the editor server enabled; ports 9020 (Alchemy) /
9021 (official) per local setup. `code` is deliberately NOT on PATH — that is
the repro condition, do not install VS Code to "fix" the repro. Create a
scratch prim in-world (tapple does this per session; select it; you need edit
perms — your own object works).

1. No-client failure is VISIBLE: with no client connected, click Explore in
   IDE → expect the new user-visible error (today: silence). The log still
   shows the launchVSCode failure pair.
2. Toggle hygiene: after that failed click the button must read "Explore in
   IDE" (unpressed) — today it can desync to "Stop Exploring" (B7).
3. Client-connected path unchanged:
   ```
   cd ~/cabbage/secondlife/slsync && uv run slsync --url ws://127.0.0.1:90NN tail
   ```
   (or `... objects list`). With it connected, one click publishes —
   `objects list` shows the object, the tail prints `PUB  Object [<uuid>]`;
   click again → unpublish (`UNPUB ...` line).
4. Logs: official `~/.secondlife/logs/SecondLife.log`, Alchemy
   `~/.local/state/alchemynext/Alchemy.log` — grep `ScriptEditorWS`,
   `launchVSCode`, `buildAndSendPublish`. NOTE: official 26.5.x does NOT log
   per-call RPC entries — verify via the tail client's broadcasts, not the log.

## Key files (line numbers for today's checkouts)

- `viewer/indra/newview/llpanelcontents.cpp` — onClickPublish L395 (branch at
  L413-428), state sync L176-188, gating L143
- `viewer/indra/newview/llscripteditorws.cpp` — buildVSCodeURI L349,
  launchVSCode L371-405 (failure at L400-404)
- `NewAlchemy/indra/newview/llpanelcontents.cpp` — onClickPublish L486,
  Script-Studio branch L496-504, label handling L238-262
- `NewAlchemy/indra/newview/llscripteditorws.cpp` — launchVSCode failure L463
- `.../indra/newview/skins/default/xui/en/floater_tools.xml` — `button
  publish` L3094-3100 (is_toggle, label / label_selected)
- slsync repo: NOTES.md (B1 full write-up, B6, B7), AGENTS.md (orientation +
  live-probe etiquette), external-editor-json-rpc.md (protocol spec)

## Environment / etiquette

- Ubuntu 26.04; avatars in Equestrian (luau region) on both viewers today, but
  regions vary per session — never assume world state (see slsync NOTES.md
  Decisions #7: test objects do NOT persist between sessions).
- Announce before live probing (tapple may have things turned off in-world).
- slsync CLI: `cd ~/cabbage/secondlife/slsync && uv run slsync [--url
  ws://127.0.0.1:90NN] <cmd>`; `status`, `objects list`, `objects explore
  <uuid>`, `tail` are the relevant read-only/verification commands.
