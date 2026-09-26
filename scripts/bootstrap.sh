#!/usr/bin/env bash
# GridTwin bootstrap: installs everything the project needs, without sudo where possible.
# Idempotent: safe to run again at any time.
#   bash scripts/bootstrap.sh           -> user-level installs + checks (run by Claude Code)
#   sudo bash scripts/bootstrap.sh --admin  -> Linux/WSL only: system packages (docker, make, git)
# Exit codes: 0 = ready, 2 = a human step is needed (see .autopilot/human-steps.txt)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$ROOT/.autopilot"; mkdir -p "$STATE"
HUMAN="$STATE/human-steps.txt"; : > "$HUMAN"
LOCAL_BIN="$HOME/.local/bin"; mkdir -p "$LOCAL_BIN"
export PATH="$LOCAL_BIN:$PATH"
export UV_NATIVE_TLS=1   # use the OS certificate store (works behind corporate/venue proxies)
ME="${USER:-$(id -un)}"

OS="$(uname -s)"; ARCH_RAW="$(uname -m)"
IS_WINDOWS=0; case "$OS" in MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;; esac
case "$ARCH_RAW" in x86_64|amd64) ARCH=amd64; NODE_ARCH=x64 ;; arm64|aarch64) ARCH=arm64; NODE_ARCH=arm64 ;; *) ARCH="$ARCH_RAW"; NODE_ARCH="$ARCH_RAW" ;; esac
IS_WSL=0; grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=1
have() { command -v "$1" >/dev/null 2>&1; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
info() { printf '  • %s\n' "$*"; }
need() { printf '  \033[33m✗\033[0m %s\n' "$*"; echo "$*" >> "$HUMAN"; }
can_sudo() { [ "$(id -u)" -eq 0 ] || sudo -n true 2>/dev/null; }
as_root() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo -n "$@"; fi; }

# ---------------------------------------------------------------- admin mode (Linux/WSL)
if [ "${1:-}" = "--admin" ]; then
  [ "$OS" = "Linux" ] || { echo "--admin is for Linux/WSL only"; exit 1; }
  [ "$(id -u)" -eq 0 ] || { echo "Run with sudo: sudo bash scripts/bootstrap.sh --admin"; exit 1; }
  TARGET_USER="${SUDO_USER:-${USER:-$(id -un)}}"
  if have apt-get; then apt-get update -y && apt-get install -y make git curl ca-certificates unzip; fi
  if ! have docker; then curl -fsSL https://get.docker.com | sh; fi
  usermod -aG docker "$TARGET_USER" || true
  (systemctl enable --now docker 2>/dev/null || service docker start 2>/dev/null) || true
  echo "Admin setup done. Log out/in (or run 'newgrp docker') so '$TARGET_USER' can use docker without sudo."
  exit 0
fi

echo "GridTwin bootstrap ($OS/$ARCH_RAW$( [ "$IS_WSL" = 1 ] && echo ", WSL"))"

# ---------------------------------------------------------------- git + make
for t in git make curl tar unzip; do
  if have "$t"; then ok "$t"; continue; fi
  if [ "$OS" = "Darwin" ]; then need "$t missing: run 'xcode-select --install' and click Install (one-time Apple dialog)"
  elif can_sudo && have apt-get; then as_root apt-get install -y "$t" >/dev/null && ok "$t (installed)" || need "$t missing: run 'sudo bash scripts/bootstrap.sh --admin'"
  else need "$t missing: run 'sudo bash scripts/bootstrap.sh --admin'"; fi
done

# ---------------------------------------------------------------- uv + Python 3.12
if ! have uv; then info "installing uv"; curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"; fi
if have uv; then ok "uv $(uv --version | awk '{print $2}')"; uv python install 3.12 >/dev/null 2>&1 && ok "python 3.12 (uv-managed)" || need "uv could not install Python 3.12 (check network)"; else need "uv install failed (check network / proxy)"; fi

# ---------------------------------------------------------------- Node.js LTS (user-level tarball, no sudo)
node_major() { node -v 2>/dev/null | sed 's/v\([0-9]*\).*/\1/'; }
if have node && [ "$(node_major)" -ge 20 ] 2>/dev/null; then ok "node $(node -v)"
else
  info "installing Node.js LTS into ~/.local/node"
  NODE_OS=linux; [ "$OS" = "Darwin" ] && NODE_OS=darwin
  VER="$(curl -fsSL https://nodejs.org/dist/index.tab 2>/dev/null | awk -F'\t' 'NR>1 && $10!="-" {print $1; exit}')"
  if [ -n "$VER" ]; then
    PKG="node-$VER-$NODE_OS-$NODE_ARCH"; TMP="$(mktemp -d)"
    if curl -fsSL "https://nodejs.org/dist/$VER/$PKG.tar.gz" -o "$TMP/node.tgz"; then
      rm -rf "$HOME/.local/node" && mkdir -p "$HOME/.local/node" && tar -xzf "$TMP/node.tgz" -C "$HOME/.local/node" --strip-components=1
      for b in node npm npx corepack; do ln -sfn "$HOME/.local/node/bin/$b" "$LOCAL_BIN/$b"; done
      have node && ok "node $(node -v) (installed)" || need "Node install failed"
    else need "Node download failed for $PKG"; fi
    rm -rf "$TMP"
  else need "Could not resolve the Node.js LTS version (check network)"; fi
fi

# ---------------------------------------------------------------- GitHub CLI
if have gh; then ok "gh $(gh --version | head -1 | awk '{print $3}')"
else
  info "installing GitHub CLI"
  if [ "$OS" = "Darwin" ] && have brew; then brew install gh >/dev/null 2>&1
  else
    GH_OS=linux; EXT=tar.gz; BIN_NAME=gh
    if [ "$OS" = "Darwin" ]; then GH_OS=macOS; EXT=zip
    elif [ "$IS_WINDOWS" = 1 ]; then GH_OS=windows; EXT=zip; BIN_NAME=gh.exe
    fi
    GHV="$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/cli/cli/releases/latest 2>/dev/null | sed -n 's#.*/tag/v##p')"
    if [ -n "$GHV" ]; then
      TMP="$(mktemp -d)"; PKG="gh_${GHV}_${GH_OS}_${ARCH}"
      if curl -fsSL "https://github.com/cli/cli/releases/download/v$GHV/$PKG.$EXT" -o "$TMP/gh.$EXT"; then
        if [ "$EXT" = zip ]; then unzip -q "$TMP/gh.zip" -d "$TMP"; else tar -xzf "$TMP/gh.tar.gz" -C "$TMP"; fi
        SRC="$TMP/$PKG/bin/$BIN_NAME"; [ -f "$SRC" ] || SRC="$TMP/bin/$BIN_NAME"
        cp "$SRC" "$LOCAL_BIN/$BIN_NAME" && chmod +x "$LOCAL_BIN/$BIN_NAME"
      fi
      rm -rf "$TMP"
    fi
  fi
  have gh && ok "gh (installed)" || need "GitHub CLI install failed"
fi

# ---------------------------------------------------------------- Docker (engine + compose)
docker_ready() { docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; }
wait_docker() { for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && return 0; sleep 3; done; return 1; }
if [ "${BOOTSTRAP_SKIP_DOCKER:-0}" = 1 ]; then info "docker check skipped (BOOTSTRAP_SKIP_DOCKER=1)"
elif docker_ready; then ok "docker + compose ready"
elif [ "$OS" = "Darwin" ]; then
  if [ -d "/Applications/Docker.app" ]; then info "starting Docker Desktop"; open -a Docker; wait_docker && ok "Docker Desktop running" || need "Docker Desktop did not start: open it once and accept the prompt"
  elif have brew; then
    info "installing Colima + Docker CLI (no Docker Desktop needed)"
    brew install colima docker docker-compose >/dev/null 2>&1
    mkdir -p "$HOME/.docker/cli-plugins"; ln -sfn "$(brew --prefix)/opt/docker-compose/bin/docker-compose" "$HOME/.docker/cli-plugins/docker-compose"
    colima status >/dev/null 2>&1 || colima start --cpu 4 --memory 8 --disk 40 >/dev/null 2>&1
    docker_ready && ok "docker via Colima" || need "Colima failed to start: run 'colima start' and read its error"
  else
    need "Docker missing and Homebrew not installed. EITHER install Docker Desktop (docker.com/products/docker-desktop) OR install Homebrew with: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"  — then re-run /setup"
  fi
else  # Linux / WSL
  if have docker && ! docker info >/dev/null 2>&1 && can_sudo; then as_root systemctl start docker 2>/dev/null || as_root service docker start 2>/dev/null || true; fi
  if docker_ready; then ok "docker + compose ready"
  elif can_sudo; then info "installing Docker Engine (passwordless sudo available)"; curl -fsSL https://get.docker.com | as_root sh >/dev/null 2>&1; as_root usermod -aG docker "$ME"
    docker_ready && ok "docker installed" || need "Docker installed; run 'newgrp docker' (or log out/in) so you can use it without sudo, then re-run /setup"
  elif [ "$IS_WSL" = 1 ]; then need "Docker missing in WSL. EITHER enable WSL integration in Docker Desktop for Windows, OR run: sudo bash scripts/bootstrap.sh --admin"
  else need "Docker missing. Run once in your own terminal: sudo bash scripts/bootstrap.sh --admin"; fi
fi

# ---------------------------------------------------------------- env file
[ -f "$ROOT/.env" ] || { [ -f "$ROOT/.env.example" ] && cp "$ROOT/.env.example" "$ROOT/.env" || touch "$ROOT/.env"; ok ".env created (empty keys are fine)"; }

echo
if [ -s "$HUMAN" ]; then
  echo "Human steps needed (also saved to .autopilot/human-steps.txt):"; nl -ba "$HUMAN"; exit 2
fi
echo "All prerequisites ready."; exit 0
