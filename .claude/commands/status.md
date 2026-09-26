---
description: Show GridTwin progress, autopilot state, tickets waiting on the human, and time left
---
Read-only: don't change files or issues.

1. Print the table from `docs/PROGRESS.md`, and cross-check each ticket's state with `gh issue list --label ticket --state all`. Flag any mismatch.
2. **Autopilot:**
   - If `.autopilot/autopilot.pid` exists and that process is alive, say it's running.
   - Show the last 5 lines of `.autopilot/autopilot.log`.
   - Show the latest `.autopilot/status.json`.
3. **Waiting on the human:**
   - Open issues labeled `needs-human`, each with the question from its latest comment.
   - The contents of `.autopilot/human-steps.txt`, if it is non-empty.
   - Explain how to unblock a ticket: answer in an issue comment, remove the `needs-human` label, then restart autopilot with `nohup ./scripts/autopilot.sh > .autopilot/autopilot.log 2>&1 &`.
4. **Frontier:** list the `todo` tickets whose blockers are all done.
5. **Time left:** until **Sun Sep 27, 2026, 10:30 AM America/Chicago** (`TZ=America/Chicago date`). Compare with the schedule in PROGRESS.md, and if behind, recommend cuts from the spec's *Cut lines* section. Recommend only.
