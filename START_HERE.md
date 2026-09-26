# GridTwin: Start Here

You don't install anything by hand. Claude Code does it.

1. Unzip this kit into an empty folder and open a terminal there.
2. Run `claude`.
3. Type `/go`.

That's it. `/go` will:
- **Install** uv, Python 3.12, Node.js LTS and the GitHub CLI, and get Docker running (`scripts/bootstrap.sh`, no sudo where possible).
- **Sign you in to GitHub.** It shows you a code; you enter it at github.com/login/device.
- **Create a private `gridtwin` repo**, the spec issue and 14 ticket issues.
- **Start autopilot,** which builds one ticket per fresh session, commits to `main`, closes the issue and moves on.

You'll only be asked for things that need you personally:
- the GitHub sign-in code
- an admin password **only if** Docker or Apple's command-line tools are missing (it prints the exact command)
- optional ERCOT API keys in `.env`
- answers to issues labeled `needs-human`
- the demo video on Sunday

**Watch:** `tail -f .autopilot/autopilot.log`, the repo's Issues tab, or `/status` in Claude Code.
**Stop:** `touch .autopilot/STOP` (it finishes the current ticket first).
**Restart:** `nohup ./scripts/autopilot.sh > .autopilot/autopilot.log 2>&1 &`
