---
description: One command does everything - set up the machine, create the repo and tickets, then build all tickets on autopilot
argument-hint: [yolo]  (optional: skip permission checks in autopilot)
---
The human wants everything done for them. Run these phases in order, skipping any phase that is already complete. The human is present during this command, so ask them only for the steps the files mark as human-only.

1. **Setup.** Follow `.claude/commands/setup.md` completely.
2. **Kickoff.** Follow `.claude/commands/kickoff.md`. Skip it if `origin` is set and issues labeled `ticket` already exist.
3. **Autopilot.**
   - Start it in the background so it survives this session: `nohup ./scripts/autopilot.sh <flag> > .autopilot/autopilot.log 2>&1 &`
   - `<flag>` is `--yolo` if "$ARGUMENTS" contains "yolo", and empty otherwise.
   - Confirm it started: `.autopilot/autopilot.pid` exists and the log shows "session 1".
4. **Brief the human in five lines or fewer.** Cover:
   - Autopilot builds one ticket per fresh session, commits to `main`, closes the GitHub issue and moves to the next ticket.
   - How to watch: `tail -f .autopilot/autopilot.log`, the repo's Issues page, or `/status` in Claude Code.
   - How to stop: `touch .autopilot/STOP` (it finishes the current ticket first).
   - What it may need from them: issues labeled `needs-human` (answer in a comment, then remove the label and restart autopilot), and on Sunday morning the video and submission.
   - While autopilot runs, this session should only use `/status`, with no edits to the repo.
