#!/bin/bash
# ---------------------------------------------------------------------------
# SAMPLE PLAYER — installer for macOS                          edition: v1
#
# repo: SAMPLE_PLAYER_MACOS
#
# A local Flask server and a web interface, run from the terminal. The same set
# of cells as the Android app: record a phrase, transcribe it, replace the
# voice, play the set back with a travelling playhead.
#
#
# WHAT THIS INSTALLS
#
#   ~/.sampleplayer-web/        the app, its virtual environment and its data
#   ~/.local/bin/sampleplayer   the launcher
#
# Nothing is written anywhere else, nothing needs sudo, and removing the two
# paths above removes the app completely.
#
#
# WHY THIS IS NOT ONE ENORMOUS HEREDOC
#
# MA Reader's installer carries its whole server and its whole page inside
# itself, and that is right for it: it is pasted into a phone over SSH, where
# a repository is not available and one file is the only thing that can arrive.
#
# On a Mac the repository IS available — this file was cloned, not pasted — and
# a five thousand line HTML page inside a quoted heredoc cannot be linted, cannot
# be diffed usefully and cannot be opened in an editor that knows what it is.
# So the server and the page are real files next to this one, and this script
# copies them. The shape of everything else is the same: banner, probe, venv,
# launcher, atomic writes through .new, and a port picked rather than assumed.
#
#
# THE DEPENDENCY LIST IS ONE LINE
#
# Flask, and nothing else. Not ffmpeg: the browser records raw samples and
# builds the WAV itself at 44.1 kHz mono 16-bit, so what reaches the server is
# already the format everything downstream reads. Not numpy: normalising a
# spoken phrase is a loop over a few hundred thousand integers and Python does
# that in a few milliseconds, once per take.
#
#
# usage:  bash 3sh_i_sample_player_v1_macos.sh
#         bash 3sh_i_sample_player_v1_macos.sh --wipe
# ---------------------------------------------------------------------------
set -e

APPDIR="$HOME/.sampleplayer-web"
BIN="$HOME/.local/bin"
CMD="$BIN/sampleplayer"
SRC="$(cd "$(dirname "$0")" && pwd)"
VERSION="v1"

# ------------------------------------------------------------------ palette --
# Sample Player is amber on black on the phone, so the installer wears amber:
# light on the top of the letterform cooling into ember at its foot. Removal
# wears the same shape in ash, cold instead of warm, so the two operations are
# told apart by temperature before a word is read.
#
# NO 24-BIT COLOUR. A 38;2;r;g;b escape comes out as literal rubbish on a
# terminal that does not have it. Three tiers, decided by asking rather than
# assuming.
NCOL=0
if [ -t 1 ]; then
  NCOL="$(tput colors 2>/dev/null || echo 8)"
  case "$NCOL" in ''|*[!0-9]*) NCOL=8 ;; esac
  B=$'\033[1m'; OFF=$'\033[0m'
else
  B=''; OFF=''
fi
if [ "$NCOL" -ge 256 ] 2>/dev/null; then
  c() { printf '\033[38;5;%sm' "$1"; }
  GLOW="$(c 223)"; GOLD="$(c 222)"; AMBER="$(c 214)"
  FLAME="$(c 208)"; EMBER="$(c 166)"; COAL="$(c 131)"
  VIOLET="$(c 141)"; GREEN="$(c 114)"; RED="$(c 203)"; DIM="$(c 245)"
  ASH1="$(c 252)"; ASH2="$(c 247)"; ASH3="$(c 243)"; ASH4="$(c 240)"
elif [ -t 1 ]; then
  GLOW=$'\033[1;33m'; GOLD=$'\033[1;33m'; AMBER=$'\033[0;33m'
  FLAME=$'\033[0;33m'; EMBER=$'\033[0;31m'; COAL=$'\033[0;31m'
  VIOLET=$'\033[0;35m'; GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; DIM=$'\033[0;37m'
  ASH1=$'\033[0;37m'; ASH2=$'\033[0;37m'; ASH3=$'\033[0;37m'; ASH4=$'\033[0;37m'
else
  GLOW=''; GOLD=''; AMBER=''; FLAME=''; EMBER=''; COAL=''
  VIOLET=''; GREEN=''; RED=''; DIM=''
  ASH1=''; ASH2=''; ASH3=''; ASH4=''
fi
KEY="$B$GLOW"; OK="$GREEN"
RULE="─────────────────────────────────────────────"

logo() {
  printf '\n'
  printf '   %s███████╗██████╗ %s\n' "$1" "$OFF"
  printf '   %s██╔════╝██╔══██╗%s\n' "$2" "$OFF"
  printf '   %s███████╗██████╔╝%s\n' "$3" "$OFF"
  printf '   %s╚════██║██╔═══╝ %s\n' "$4" "$OFF"
  printf '   %s███████║██║     %s\n' "$5" "$OFF"
  printf '   %s╚══════╝╚═╝     %s\n' "$6" "$OFF"
}
banner_amber() {
  logo "$GLOW" "$GOLD" "$AMBER" "$FLAME" "$EMBER" "$COAL"
  printf '   %sS A M P L E   P L A Y E R%s  %s%s%s\n' "$KEY" "$OFF" "$VIOLET" "$VERSION" "$OFF"
  printf '   %sthirty voices in a grid, the MA ecosystem%s\n\n' "$DIM" "$OFF"
}
banner_ash() {
  logo "$ASH1" "$ASH2" "$ASH3" "$ASH4" "$ASH4" "$ASH4"
  printf '   %sS A M P L E   P L A Y E R%s  %sremove%s\n' "$B$ASH1" "$OFF" "$VIOLET" "$OFF"
  printf '   %staking the grid down%s\n\n' "$DIM" "$OFF"
}
rule() { printf '   %s%s%s\n' "$DIM" "$RULE" "$OFF"; }
row()  { printf '    %s%-14s%s %s%s%s\n' "$DIM" "$1" "$OFF" "$3" "$2" "$OFF"; }
step() { printf '   %s%s%s\n' "$DIM" "$1" "$OFF"; }
good() { printf '   %s%s%s\n' "$OK" "$1" "$OFF"; }
bad()  { printf '   %s%s%s\n' "$RED" "$1" "$OFF"; }

# --------------------------------------------------------------------- wipe --
if [ "$1" = "--wipe" ]; then
  banner_ash
  rule
  row "app"      "$APPDIR"  "$DIM"
  row "launcher" "$CMD"     "$DIM"
  rule
  printf '   %sYour recordings are inside the app folder. Remove it? [y/N] %s' "$RED" "$OFF"
  read -r a
  case "$a" in
    y|Y)
      rm -rf "$APPDIR" "$CMD" "$BIN/sampleplayer-update"
      good "gone"
      ;;
    *) step "left alone" ;;
  esac
  exit 0
fi

banner_amber

# -------------------------------------------------------------------- probe --
# ASK, DO NOT ASSUME. A missing python3 fails here with a sentence rather than
# forty lines down with a traceback.
rule
step "checking what is here"
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  bad "python3 is not on the PATH."
  step "install it with:  brew install python"
  exit 1
fi
row "python3" "$($PY -V 2>&1)" "$OK"

if [ ! -f "$SRC/server.py" ] || [ ! -f "$SRC/static/index.html" ]; then
  bad "server.py or static/index.html is missing next to this script."
  step "run this from inside the cloned repository."
  exit 1
fi
row "sources" "found beside this script" "$OK"
rule

# ------------------------------------------------------------------ install --
step "installing into $APPDIR"
mkdir -p "$APPDIR/static" "$APPDIR/data" "$BIN"

# A VIRTUAL ENVIRONMENT, not --user and not --break-system-packages. Homebrew
# python refuses a bare pip install into itself, and it is right to: this app
# should not be able to change the version of anything else on the machine.
if [ ! -d "$APPDIR/venv" ]; then
  step "making a virtual environment"
  "$PY" -m venv "$APPDIR/venv"
fi
"$APPDIR/venv/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
step "installing Flask"
"$APPDIR/venv/bin/pip" install --quiet flask

cp "$SRC/server.py" "$APPDIR/server.py"
cp "$SRC/static/index.html" "$APPDIR/static/index.html"
good "app in place"

# THE KEY FILE IS CREATED EMPTY, WITH ITS INSTRUCTIONS INSIDE IT. A file that
# does not exist is a question; a file that exists and explains itself is an
# answer. It is never overwritten, because it holds credentials.
if [ ! -f "$APPDIR/keys.txt" ]; then
  cat > "$APPDIR/keys.txt" << 'KEYEOF'
# Paste your whole key note into this file, prose and all.
#
# It is read by the same parser as the phone: keys are found by SHAPE, so
# account names, dates, the word CANCELLED and pasted URLs are all fine and are
# never mistaken for credentials. The line above each key is kept as its label.
#
# Hume is a PAIR. Leave the account note in the shape the dashboard gives you:
#
#   Some account name
#   API key
#   <the api key>
#   Secret key
#   <the secret key>
#
# AssemblyAI transcribes and is required. Speechify and Hume are the two voice
# engines and either one is enough.
KEYEOF
  good "key file created at $APPDIR/keys.txt"
else
  row "keys" "already there, left alone" "$DIM"
fi

# ----------------------------------------------------------------- launcher --
# WRITTEN AS .new AND MOVED. A plain "cat >" truncates the file the running
# shell may be reading from, and a half-written launcher is a launcher that
# fails at a different place every time.
cat > "$BIN/sampleplayer.new" << 'LAUNCHEOF'
#!/bin/bash
APPDIR="$HOME/.sampleplayer-web"
PORTFILE="$APPDIR/port.txt"

DIMC=$'\033[38;5;245m'; KEYC=$'\033[1;38;5;222m'; OFFC=$'\033[0m'
WHTC=$'\033[38;5;252m'; GRNC=$'\033[38;5;114m'
ruleC(){ printf '   %s%s%s\n' "$DIMC" "------------------------------------------" "$OFFC"; }

# The Mac must not sleep while a take is being recorded, and must be allowed to
# the moment this exits. -w on our own pid ties the two together.
caffeinate -dimsu -w $$ >/dev/null 2>&1 &

cleanup(){
  [ -n "$SRV" ] && kill "$SRV" 2>/dev/null
  printf '\033[?25h'
}
trap 'cleanup' EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
trap 'cleanup; exit 129' HUP

rm -f "$PORTFILE"
"$APPDIR/venv/bin/python" "$APPDIR/server.py" &
SRV=$!

# WAIT FOR THE PORTFILE RATHER THAN SLEEPING. The server picks the first free
# port at or above 8084, because several of these run at once and a fixed port
# means one of them silently loses. Opening the browser on a guess opens it on
# somebody else's app.
PORT=""
for i in $(seq 1 60); do
  [ -f "$PORTFILE" ] && PORT="$(cat "$PORTFILE")" && break
  sleep 0.25
done
if [ -z "$PORT" ]; then
  echo "   the server did not come up"
  exit 1
fi

URL="http://127.0.0.1:$PORT"
echo ""
printf '   %sSAMPLE PLAYER%s  %sserver%s\n' "$KEYC" "$OFFC" "$DIMC" "$OFFC"
ruleC
printf '    %s%-14s%s %s%s%s\n' "$DIMC" "here" "$OFFC" "$WHTC" "$URL" "$OFFC"
printf '    %s%-14s%s %s%s%s\n' "$DIMC" "data" "$OFFC" "$DIMC" "$APPDIR/data" "$OFFC"
printf '    %s%-14s%s %s%s%s\n' "$DIMC" "keys" "$OFFC" "$DIMC" "$APPDIR/keys.txt" "$OFFC"
ruleC
printf '    %sspace%s      stop this cell, start the next\n' "$KEYC" "$OFFC"
printf '    %sm%s          swap REC and PLAY\n' "$KEYC" "$OFFC"
printf '    %sarrows%s     flip the page\n' "$KEYC" "$OFFC"
printf '    %sesc%s        stop everything\n' "$KEYC" "$OFFC"
printf '    %sright-click%s  a cell opens its menu\n' "$KEYC" "$OFFC"
ruleC
printf '    %sctrl-c%s to stop the server\n\n' "$DIMC" "$OFFC"

# CHROME BY PREFERENCE. Safari asks for the microphone once per page load and
# forgets; Chrome remembers the grant for 127.0.0.1, which matters in an app
# whose whole loop is press, speak, press.
open -a "Google Chrome" "$URL" >/dev/null 2>&1 || open "$URL" >/dev/null 2>&1

wait "$SRV"
LAUNCHEOF
chmod +x "$BIN/sampleplayer.new"
mv "$BIN/sampleplayer.new" "$CMD"

cat > "$BIN/sampleplayer-update.new" << 'UPDEOF'
#!/bin/bash
# Re-run the installer from wherever the repository was cloned.
set -e
REPO="${SAMPLEPLAYER_REPO:-$HOME/SAMPLE_PLAYER_MACOS}"
if [ ! -d "$REPO" ]; then
  echo "set SAMPLEPLAYER_REPO to the cloned repository, or clone it to $REPO"
  exit 1
fi
cd "$REPO" && git pull --ff-only && bash 3sh_i_sample_player_v1_macos.sh
UPDEOF
chmod +x "$BIN/sampleplayer-update.new"
mv "$BIN/sampleplayer-update.new" "$BIN/sampleplayer-update"
good "launcher at $CMD"

# ---------------------------------------------------------------------- PATH --
case ":$PATH:" in
  *":$BIN:"*) : ;;
  *)
    step ""
    bad "$BIN is not on your PATH."
    step "add this to ~/.zshrc:"
    printf '     %sexport PATH="$HOME/.local/bin:$PATH"%s\n' "$WHTC" "$OFF"
    ;;
esac

rule
good "done"
printf '\n   run it with:  %ssampleplayer%s\n\n' "$KEY" "$OFF"
