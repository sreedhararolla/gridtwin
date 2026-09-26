---
description: Build one GridTwin ticket as a tracer bullet, commit straight to main, close the issue and update progress
argument-hint: [ticket-number e.g. 04; empty = next frontier ticket]
---
Ticket requested: $ARGUMENTS

Workflow is trunk-based (ADR-006): all work lands directly on `main`, with no branches or PRs. Prefix shell commands with `source scripts/env.sh && ` if a tool isn't found.

**Autopilot:** if the environment variable `GRIDTWIN_AUTOPILOT=1` is set or the prompt says AUTOPILOT, also follow the *Autopilot mode* section at the end. It overrides every "stop and ask" in this file.

## 1. Sync and pick
- If `git status` is not clean, stop and show the human.
- `git checkout main && git pull --rebase origin main`
- If a ticket number was given, use it. Otherwise pick the **frontier**: the lowest-numbered ticket in `docs/PROGRESS.md` with status `todo` whose blockers are all `done` and whose issue is **not** labeled `needs-human`. Cross-check with `gh issue list --label ticket --state all`. Skip `P2` and `stretch` while any `P0`/`P1` ticket is on the frontier.
- If the ticket's blockers are not done, stop and say which ones.

## 2. Load context
Read `CONTEXT.md`, the ticket file, `gh issue view <n> --comments` (a human's answers to earlier questions live there), and **only** the spec sections the ticket needs.
- **Resume parked work:** if `git ls-remote --heads origin 'wip/tNN-*'` finds a branch, restore it with `git fetch origin && git merge --squash --no-commit origin/<that branch>`. Continue from there, and delete the branch (`git push origin --delete <branch>`) once the ticket is done.

## 3. Start
- `gh issue edit <n> --add-label in-progress`. The label is the in-progress marker; PROGRESS.md only changes in the final commit.
- Post a plan comment on the issue: the **tracer bullet** first, then the expansion steps. Map each step to the acceptance criteria it satisfies and name the test seam (A or B) it uses.

## 4. Build
- Build the tracer bullet, then **run it end-to-end** and read the real output.
- Expand one step at a time, running the fastest relevant tests after each step.
- Commit locally in small steps: `feat(<module>): <summary> (Refs #<issue>)`.
- Whenever `make check` is green, push to back up the work: `git pull --rebase origin main && git push origin main`. Never push red.
- If the API changed, run `make types` and commit the regenerated types.

## 5. Verify
- `make check` must be green. Also run `make test-e2e` when any criterion mentions e2e or compose.
- Walk **every** acceptance criterion and capture evidence (the command plus a short output excerpt).
- If a criterion can't be met, **stop and ask**. Never tick an unmet criterion.
- Update README, DATA.md, MODEL.md, DECISIONS.md or CONTEXT.md if this ticket changes them.

## 6. Ship
- Set this ticket's row in `docs/PROGRESS.md` to `done`, with the Closed (CT) time from `TZ=America/Chicago date '+%a %H:%M'`.
- Make the **final commit**, including PROGRESS.md and any remaining work. Subject: `feat(<module>): <summary>` (or `docs: close ticket NN`). Body contains `Closes #<issue>`.
- `git pull --rebase origin main`. If that pulled in new commits, re-run `make check`. Then `git push origin main`.
- Watch CI for this push: `gh run list --branch main --limit 1`, then `gh run watch <run-id> --exit-status`. If it fails, fix forward immediately with a new commit (`fix: ... (Refs #<issue>)`) before anything else.

## 7. Close out
- Tick every acceptance-criteria checkbox in the issue body. Fetch it with `gh issue view <n> --json body`, edit it, and write it back with `gh issue edit <n> --body-file <file>`.
- `gh issue comment <n>` with an evidence summary and the commit link (`gh repo view --json url -q .url` + `/commit/` + `git rev-parse HEAD`).
- Make sure the issue is closed (`gh issue close <n>` if the `Closes` keyword did not close it), and remove the `in-progress` label.

## 8. Report
Tell the human what shipped, the demo path to try right now, anything deferred, and the next frontier ticket(s). End with: "Run `/clear`, then `/ship-ticket`."

## Autopilot mode
This applies when `GRIDTWIN_AUTOPILOT=1` is set or the prompt says AUTOPILOT. No human is watching.
- **Never wait for input.** Wherever this file says "stop and ask", **park** the ticket instead (below). Do exactly one ticket per session.
- **Dirty working tree at session start** means a previous session crashed. Commit the changes to `wip/tNN-<slug>`, naming it after the ticket labeled `in-progress`, or `wip/crash-<timestamp>` if there is none. Push the branch, run `git switch main && git reset --hard origin/main`, and then continue. The resume step above will pick the work back up.
- **No frontier ticket?** Write `{"ticket":"-","result":"no-frontier","message":"<why>"}` and end.
- **Missing credentials** (for example ERCOT keys) are not a reason to park. Finish everything the acceptance criteria allow without them. Park only if a criterion truly cannot be met.
- **Never** run `sudo`, create accounts, change repo visibility or edit the spec's decisions.
- **Park:**
  1. If there is any work (commits not yet pushed, or uncommitted changes): `git switch -c wip/tNN-<slug>`, then `git add -A && git commit -m "wip: tNN parked (Refs #<issue>)"`, then `git push -u origin HEAD`, then `git switch main && git reset --hard origin/main`. `main` must stay green.
  2. `gh issue edit <n> --add-label needs-human --remove-label in-progress`
  3. `gh issue comment <n>` stating what is blocked, the **exact** question or action needed from the human, and the wip branch name.
- **Always finish** by writing `.autopilot/status.json` as a single line of JSON, then end the session:
  `{"ticket":"NN","result":"done|needs-human|no-frontier|failed","message":"<one sentence>"}`
