# 13: Demo scenario, README, submission

**Type:** AFK (then the human records the video and submits) · **Priority:** P0 · **Blocked by:** 05, 06, 07, 09, 11 · **User stories:** 18, 19, 20

## What to build
- **`make demo-full`.** A deterministic scenario on the top spike-day window. Its scripted chaos follows the video: a worker kill at the spike, a 20% partition, duplicates, then a feed outage (if ticket 08 shipped). It prints the Scenario Report at the end.
- **DEMO_SCRIPT.md** covering the 5:00 beats from the spec, with on-screen cues.
- **README:**
  - one-paragraph pitch and screenshots/GIF
  - Mermaid architecture diagram
  - quickstart
  - **what's real vs simulated**
  - design decisions (links to DECISIONS.md)
  - SLO results
  - links to DATA.md, MODEL.md and BENCHMARKS.md
- **Clean-clone verification run.** Document it.

## Demo path
Fresh clone → `make up && make demo-full` → all SLOs pass.

## Acceptance criteria
- [ ] A clean clone runs `make up && make demo-full` successfully (run documented in the issue's evidence comment).
- [ ] The demo-full Scenario Report passes every SLO.
- [ ] Every README section is present, and the diagram renders on GitHub.
- [ ] PROGRESS.md is final, and unfinished stretch tickets are clearly marked.

## Human steps
Record the video (two takes), set repo visibility per the hackathon rules, submit by **10:30 AM Sunday**.
