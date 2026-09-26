---
description: Create the GitHub repo and publish the GridTwin spec and tickets as issues
argument-hint: [repo-name]
---
Set up the repository and tracker for GridTwin. **Do not write application code in this command.** Prefix shell commands with `source scripts/env.sh && `.

Repo name: $ARGUMENTS (use `gridtwin` if empty). Owner: the signed-in GitHub account. Visibility: **private**.

1. **Preconditions.** `gh auth status` must succeed. If it doesn't, run `.claude/commands/setup.md` first.
2. **Collision check.**
   - If `origin` is already set and points at a GitHub repo, reuse it and skip step 3.
   - If `gh repo view <owner>/<name>` finds an existing repo but this folder has no `origin`, stop and ask the human whether to use a different name. Never overwrite an existing repo.
3. **Repo.**
   - If this is not already a git repo, run `git init -b main`.
   - Commit the kit files: `chore: add GridTwin spec, tickets and agent workflow`.
   - `gh repo create <name> --private --source=. --remote=origin --push`
4. **Labels.** Create them idempotently with `gh label create ... --force`: `spec`, `ticket`, `AFK`, `HITL`, `P0`, `P1`, `P2`, `stretch`, `in-progress`, `needs-human`, `needs-keys`.
5. **Spec issue.**
   - Title: `Spec: GridTwin`. Label: `spec`.
   - Body: the spec's Problem Statement and Solution sections, then a link to `docs/SPEC.md` on `main`.
   - Do **not** paste the full spec; long issue bodies truncate when read back.
6. **Ticket issues,** created **in number order 01 → 14** so that blocker issue numbers already exist:
   - Title: `NN: <ticket title>`. Labels: `ticket` + type (`AFK`/`HITL`) + priority (`P0`/`P1`/`P2`/`stretch`).
   - Body: the ticket file's content with "Blocked by: NN" rewritten to issue references (`#n`), plus the lines `Spec: #<spec>` and `Ticket file: docs/tickets/<file>`.
   - Native links: if `gh issue create --help` lists `--blocked-by` or `--parent`, use them. If `gh issue edit --help` lists `--add-sub-issue`, attach each ticket to the spec issue. Otherwise the text references are enough.
7. **Progress.** Fill the **Issue** column in `docs/PROGRESS.md`. Commit `chore: publish spec and tickets (#<spec>)` and push to `main`.
8. **Report.** Print a table of ticket → issue URL, and name the frontier ticket (01).
