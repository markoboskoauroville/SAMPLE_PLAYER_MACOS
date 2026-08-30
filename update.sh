#!/bin/bash
###############################################################################
# SAMPLE PLAYER — first time setup, and every update after it, in one run.
#
#   curl -fsSL -O https://raw.githubusercontent.com/markoboskoauroville/SAMPLE_PLAYER_MACOS/main/update.sh
#   bash update.sh
#
# It fetches the current version from GitHub and installs it right now, and it
# leaves behind a command called `sampleplayer-update` so that every future
# update is one word.
#
# No GitHub login is needed. The repository is public, the download is
# anonymous, and no token is ever stored on this machine.
#
#
# WHY IT DOWNLOADS THREE FILES AND NOT ONE
#
# MA Reader's updater fetches a single installer that carries its whole server
# and page inside itself. This one does not: on a Mac the page and the server
# are real files, for the reasons in DEVELOPMENT.md, so there are three things
# to fetch. They are fetched into a temporary directory, ALL of them checked,
# and only then is the installer run — so a half-finished download or a network
# that drops in the middle leaves the existing install exactly as it was.
#
# WHY IT DOES NOT USE git clone
#
# It would work, and it would need git, a clone location to remember, and a
# decision about what to do when that directory has local changes in it. Three
# curls into a temporary directory have none of those questions, and the
# validation below is stricter than a clone would give.
#
#
# WHY NOT `curl … | bash`
#
# It is one line shorter and it hands a stranger's server a shell on this
# machine with nothing in between. Downloading first means the file can be read
# before it is run, and — more usefully in practice — a truncated download is
# caught rather than executed halfway.
#
# If you want it in one line anyway, this is the honest form of it:
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/markoboskoauroville/SAMPLE_PLAYER_MACOS/main/update.sh)
###############################################################################
set -e

RAW="https://raw.githubusercontent.com/markoboskoauroville/SAMPLE_PLAYER_MACOS/main"
INSTALLER="3sh_i_sample_player_v1_macos.sh"

AMBER=$'\033[38;5;214m'; RED=$'\033[38;5;203m'; GREEN=$'\033[38;5;114m'
DIM=$'\033[38;5;245m'; KEY=$'\033[1;38;5;222m'; OFF=$'\033[0m'

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() {
  printf '%s  %s%s\n' "$RED" "$1" "$OFF"
  printf '  nothing was changed.\n'
  exit 1
}

command -v curl >/dev/null 2>&1 || fail "curl is not here. Install the Xcode command line tools."

printf '%s\n  fetching the newest Sample Player%s\n' "$AMBER" "$OFF"

mkdir -p "$TMP/static"
get() {   # $1 path in the repo, $2 where to put it
  curl -fsSL --retry 3 --connect-timeout 20 -o "$2" "$RAW/$1" \
    || fail "could not reach GitHub for $1. Check the network and try again."
}
get "$INSTALLER"       "$TMP/$INSTALLER"
get "server.py"        "$TMP/server.py"
get "static/index.html" "$TMP/static/index.html"

# ---------------------------------------------------------------- checking --
# EVERY FILE, BEFORE ANY OF THEM IS USED. A captive wifi portal answers every
# request with a login page, so a "successful" download can easily be HTML
# where a Python file should be — and a size check alone would pass it.
check_size() {   # $1 file, $2 minimum bytes, $3 what it is
  n=$(wc -c < "$1" | tr -d ' ')
  [ "$n" -ge "$2" ] || fail "$3 looks wrong ($n bytes)."
  printf '  %s%-18s%s %s bytes\n' "$DIM" "$3" "$OFF" "$n"
}
check_size "$TMP/$INSTALLER"        6000 "installer"
check_size "$TMP/server.py"        15000 "server"
check_size "$TMP/static/index.html" 15000 "page"

head -1 "$TMP/$INSTALLER" | grep -q '^#!' || fail "the installer has no shebang."
bash -n "$TMP/$INSTALLER" 2>/dev/null   || fail "the installer did not parse."

# The server is Python and either parses or does not. Compiling it here means a
# truncated file cannot reach the install, where it would fail at startup with
# a traceback and no obvious cause.
PY="$(command -v python3 || true)"
[ -n "$PY" ] || fail "python3 is not on the PATH. Install it with: brew install python"
"$PY" -c "import ast,sys;ast.parse(open(sys.argv[1]).read())" "$TMP/server.py" 2>/dev/null \
  || fail "the server did not parse."

head -1 "$TMP/static/index.html" | grep -qi 'doctype html' || fail "the page is not a page."
grep -q '</script>' "$TMP/static/index.html" || fail "the page is truncated."

EDITION="$(grep -m1 'edition: v' "$TMP/$INSTALLER" | sed 's/.*edition: //')"
printf '%s  all three arrived intact — %s%s\n' "$GREEN" "$EDITION" "$OFF"

# ---------------------------------------------------------------- installing --
bash "$TMP/$INSTALLER"

# The updater leaves ITSELF behind, so the next update does not need this file
# or the URL again. Written as .new and moved, because a half-written command
# is a command that fails somewhere different every time.
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
cat > "$BIN/sampleplayer-update.new" << UPDEOF
#!/bin/bash
# Fetch the newest Sample Player and install it. Written by update.sh.
set -e
TMP="\$(mktemp -d)"
trap 'rm -rf "\$TMP"' EXIT
curl -fsSL --retry 3 -o "\$TMP/update.sh" "$RAW/update.sh" || {
  echo "could not reach GitHub. Nothing was changed."; exit 1; }
bash -n "\$TMP/update.sh" || { echo "the update script did not parse."; exit 1; }
bash "\$TMP/update.sh"
UPDEOF
chmod +x "$BIN/sampleplayer-update.new"
mv "$BIN/sampleplayer-update.new" "$BIN/sampleplayer-update"

printf '\n%s  from now on just type%s %ssampleplayer-update%s\n' "$GREEN" "$OFF" "$KEY" "$OFF"
printf '  %sand %ssampleplayer%s %sto run it.%s\n\n' "$DIM" "$KEY" "$OFF" "$DIM" "$OFF"
