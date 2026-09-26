#!/usr/bin/env bash
# GridTwin autopilot: builds tickets unattended, ONE fresh Claude Code session per ticket.
#   ./scripts/autopilot.sh          run until nothing is left that doesn't need a human
#   ./scripts/autopilot.sh --yolo   skip all permission checks (only on a machine you don't mind it touching)
# Stop gracefully (after the current ticket):  touch .autopilot/STOP
# Env overrides: AUTOPILOT_DEADLINE="2026-09-27 08:30" (CT)  AUTOPILOT_MAX_TICKETS=20
#                AUTOPILOT_MAX_TURNS=300  AUTOPILOT_BUDGET_USD=<per-session cap, optional>
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
# shellcheck disable=SC1091
source scripts/env.sh
STATE=.autopilot; mkdir -p "$STATE/logs"; echo $$ > "$STATE/autopilot.pid"
trap 'rm -f "$STATE/autopilot.pid"' EXIT

DEADLINE="${AUTOPILOT_DEADLINE:-2026-09-27 08:30}"
MAX_TICKETS="${AUTOPILOT_MAX_TICKETS:-20}"
MAX_TURNS="${AUTOPILOT_MAX_TURNS:-300}"
PERM=(--permission-mode dontAsk)          # uses the allow/deny lists in .claude/settings.json
[ "${1:-}" = "--yolo" ] && PERM=(--dangerously-skip-permissions)
BUDGET=(); [ -n "${AUTOPILOT_BUDGET_USD:-}" ] && BUDGET=(--max-budget-usd "$AUTOPILOT_BUDGET_USD")

command -v claude >/dev/null || { echo "Claude Code CLI ('claude') not found on PATH."; exit 1; }

read -r -d '' PROMPT << 'P'
You are running in AUTOPILOT mode for GridTwin. No human is watching this session.
Follow .claude/commands/ship-ticket.md exactly with NO ticket argument (pick the frontier ticket),
and apply its "Autopilot mode" section: never wait for a human; park the ticket instead.
Work on exactly ONE ticket, write .autopilot/status.json as described there, then end the session.
P

field() { sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" "$STATE/status.json" 2>/dev/null | head -1; }
n=0; fails=0; parked=0
while :; do
  [ -f "$STATE/STOP" ] && { rm -f "$STATE/STOP"; echo "■ STOP file found; stopping."; break; }
  now="$(TZ=America/Chicago date '+%Y-%m-%d %H:%M')"
  [[ "$now" > "$DEADLINE" ]] && { echo "■ Deadline $DEADLINE CT reached; not starting new tickets."; break; }
  [ "$n" -ge "$MAX_TICKETS" ] && { echo "■ Max tickets ($MAX_TICKETS) reached."; break; }

  rm -f "$STATE/status.json"
  log="$STATE/logs/$(date +%Y%m%d-%H%M%S).log"
  echo "▶ [$now CT] session $((n+1)) → $log"
  GRIDTWIN_AUTOPILOT=1 claude -p "$PROMPT" "${PERM[@]}" --max-turns "$MAX_TURNS" "${BUDGET[@]}" \
    --output-format text > "$log" 2>&1
  rc=$?; n=$((n+1))
  result="$(field result)"; ticket="$(field ticket)"; msg="$(field message)"
  echo "  ↳ exit=$rc ticket=${ticket:-?} result=${result:-none} ${msg}"

  case "$result" in
    done)        fails=0; parked=0 ;;
    needs-human) fails=0; parked=$((parked+1))
                 [ "$parked" -ge 3 ] && { echo "■ 3 tickets in a row need a human; stopping."; break; } ;;
    no-frontier) echo "■ Nothing left that autopilot can do without a human."; break ;;
    *)           fails=$((fails+1))
                 [ "$fails" -ge 3 ] && { echo "■ 3 failed sessions in a row; stopping. Last log: $log"; break; }
                 echo "  retrying in 5 minutes (usage limit, crash or timeout)"; sleep 300 ;;
  esac
  sleep 5
done

echo; echo "Tickets waiting on you:"
gh issue list --label needs-human --state open 2>/dev/null || true
[ -s "$STATE/human-steps.txt" ] && { echo "Setup steps waiting on you:"; cat "$STATE/human-steps.txt"; }
