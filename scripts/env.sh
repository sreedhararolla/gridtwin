# Source this to put GridTwin's user-level tools on PATH:  source scripts/env.sh
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$HOME/.cargo/bin:$PATH"
export PATH="$HOME/AppData/Local/Microsoft/WinGet/Packages/ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe/bin:$PATH"
[ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
[ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
true
