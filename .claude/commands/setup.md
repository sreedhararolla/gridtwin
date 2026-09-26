---
description: Install and verify everything GridTwin needs on this machine (no manual installs)
---
Get this machine ready for GridTwin. Do everything yourself; involve the human only where noted.

1. **Install tools.** Run `bash scripts/bootstrap.sh` and allow it up to 10 minutes. It installs uv, Python 3.12, Node.js LTS and the GitHub CLI into the user's home directory without sudo, and gets Docker running where it can. It is idempotent. Show its summary.
2. **Human-only setup steps.** If the script exits with code 2:
   - Read `.autopilot/human-steps.txt`.
   - Give the human each step in one plain sentence plus the exact command to paste into **their own terminal**. These are steps that need their password or a click, such as a one-time admin install of Docker or Apple's command-line tools.
   - Wait for them to say done, then re-run the script. Repeat until it exits 0.
   - Never run `sudo` yourself.
3. **PATH.** Tools may have just been installed, so for the rest of this session prefix shell commands with `source scripts/env.sh && `.
4. **GitHub sign-in.** Skip this step if `gh auth status` already succeeds.
   - Start the browser device flow in the background: `(echo | gh auth login --hostname github.com --git-protocol https --web > .autopilot/gh-auth.log 2>&1 &)`
   - Wait 5 seconds, then read `.autopilot/gh-auth.log`.
   - Tell the human: "Open https://github.com/login/device and enter code XXXX-XXXX", using the real code from the log.
   - Poll `gh auth status` every 10 s for up to 10 minutes.
   - If no code appears in the log, ask the human to run `gh auth login` in their own terminal and pick GitHub.com → HTTPS → browser.
   - Then run `gh auth setup-git`.
5. **Git identity.** If `git config user.email` is empty, set a repo-local identity from their GitHub account:
   - name: `gh api user --jq '.name // .login'`
   - email: `<id>+<login>@users.noreply.github.com`, built from `gh api user --jq .id` and `.login`
6. **Docker smoke test.** Run `docker run --rm hello-world`.
7. **ERCOT keys (optional, never blocking).**
   - Check whether keys are present **without printing them**: `grep -cE '^ERCOT_[A-Z_]+=.+' .env`.
   - If none are set, tell the human in one line: *"Optional: create an account at apiexplorer.ercot.com and fill in `ERCOT_API_USERNAME`, `ERCOT_API_PASSWORD` and `ERCOT_API_SUBSCRIPTION_KEY` in `.env`. This unlocks forecast and outage history; everything else works without it."*
   - Never create accounts for them, and never ask them to paste secrets into the chat.
8. **Report** a short checklist: tools ✓, Docker ✓, GitHub ✓ (as whom), git identity ✓, ERCOT keys (present / optional).
