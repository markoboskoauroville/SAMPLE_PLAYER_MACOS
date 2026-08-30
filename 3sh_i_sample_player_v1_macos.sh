#!/bin/bash
# ---------------------------------------------------------------------------
# SAMPLE PLAYER — installer for macOS                        edition: v1.4
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
# The launcher. It runs the server, shows a small status panel, and waits on a
# key — it does not tail a log.
#
# WHY THE SERVER IS SILENT
#
# Flask's development server prints a line for every request, and this app polls
# state after every recording and repaints on every keystroke. The terminal
# filled with 200s within a minute of use, which is a window doing nothing
# except scrolling past the one thing worth reading, which is the address. The
# access log is turned off in the server itself and werkzeug's logger is set to
# ERROR, so what remains on screen is a crash — the only thing worth showing.
APPDIR="$HOME/.sampleplayer-web"
PORTFILE="$APPDIR/port.txt"
LOG="$APPDIR/server.log"

DIMC=$'\033[38;5;245m'; KEYC=$'\033[1;38;5;222m'; OFFC=$'\033[0m'
WHTC=$'\033[38;5;252m'; GRNC=$'\033[38;5;114m'; REDC=$'\033[38;5;203m'
AMBC=$'\033[38;5;214m'
ruleC(){ printf '   %s%s%s\n' "$DIMC" "------------------------------------------" "$OFFC"; }

# The Mac must not sleep while a take is being recorded, and must be allowed to
# the moment this exits. -w on our own pid ties the two together.
caffeinate -dimsu -w $$ >/dev/null 2>&1 &
CAFF=$!

# THE TERMINAL IS PUT INTO SINGLE-KEY MODE AND MUST BE PUT BACK.
# A shell left with echo off after a crash looks like a broken machine, so the
# restore is on every exit path there is, not just the clean one.
TTY_SAVED=""
[ -t 0 ] && TTY_SAVED="$(stty -g 2>/dev/null || true)"
tty_restore(){
  [ -n "$TTY_SAVED" ] && stty "$TTY_SAVED" 2>/dev/null || true
  [ -t 0 ] && stty echo 2>/dev/null || true
  printf '\033[?25h'
}
cleanup(){
  tty_restore
  [ -n "$SRV" ]  && kill "$SRV"  2>/dev/null
  [ -n "$CAFF" ] && kill "$CAFF" 2>/dev/null
}
trap 'cleanup' EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
trap 'cleanup; exit 129' HUP

rm -f "$PORTFILE"
"$APPDIR/venv/bin/python" "$APPDIR/server.py" >"$LOG" 2>&1 &
SRV=$!

# WAIT FOR THE PORTFILE RATHER THAN SLEEPING. The server takes the first free
# port at or above 8084, because several of these run at once and a fixed port
# means one of them silently loses. Opening the browser on a guess opens it on
# somebody else's app.
PORT=""
for i in $(seq 1 60); do
  [ -s "$PORTFILE" ] && PORT="$(cat "$PORTFILE")" && break
  kill -0 "$SRV" 2>/dev/null || break
  sleep 0.25
done
if [ -z "$PORT" ]; then
  printf '\n   %sthe server did not come up%s\n' "$REDC" "$OFFC"
  printf '   %slast lines of %s:%s\n' "$DIMC" "$LOG" "$OFFC"
  tail -n 12 "$LOG" 2>/dev/null | sed 's/^/     /'
  exit 1
fi
URL="http://127.0.0.1:$PORT"

lan_ip(){
  for i in en0 en1 en2; do
    a="$(ipconfig getifaddr "$i" 2>/dev/null)"
    [ -n "$a" ] && { echo "$a"; return 0; }
  done
  return 0
}

cells(){
  find "$APPDIR/data" -name original.wav 2>/dev/null | wc -l | tr -d ' '
}
disk(){
  du -sh "$APPDIR/data" 2>/dev/null | cut -f1
}
keycount(){
  [ -f "$APPDIR/keys.txt" ] || { echo 0; return; }
  grep -cE '(sk_|gsk_|sk-ant-|AIza|[0-9a-f]{32})' "$APPDIR/keys.txt" 2>/dev/null || echo 0
}

show_head(){
  clear 2>/dev/null || true
  IP="$(lan_ip)"
  printf '\n   %s███████╗██████╗ %s  %sSAMPLE PLAYER%s\n' "$AMBC" "$OFFC" "$KEYC" "$OFFC"
  printf '   %s██╔════╝██╔══██╗%s  %sserver running%s\n' "$AMBC" "$OFFC" "$DIMC" "$OFFC"
  printf '   %s███████╗██████╔╝%s\n' "$AMBC" "$OFFC"
  printf '   %s╚════██║██╔═══╝ %s  %s%s%s\n' "$AMBC" "$OFFC" "$WHTC" "$URL" "$OFFC"
  printf '   %s███████║██║     %s\n' "$AMBC" "$OFFC"
  printf '   %s╚══════╝╚═╝     %s\n\n' "$AMBC" "$OFFC"
  ruleC
  printf '    %s%-12s%s %s%s recorded%s   %s%s on disk%s   %s%s keys%s\n' \
    "$DIMC" "state" "$OFFC" "$GRNC" "$(cells)" "$OFFC" \
    "$WHTC" "$(disk)" "$OFFC" "$WHTC" "$(keycount)" "$OFFC"
  [ -n "$IP" ] && printf '    %s%-12s%s %shttp://%s:%s%s\n' \
    "$DIMC" "on the wifi" "$OFFC" "$DIMC" "$IP" "$PORT" "$OFFC"
  printf '    %s%-12s%s %s%s%s\n' "$DIMC" "data" "$OFFC" "$DIMC" "$APPDIR/data" "$OFFC"
  printf '    %s%-12s%s %s%s%s\n' "$DIMC" "keys" "$OFFC" "$DIMC" "$APPDIR/keys.txt" "$OFFC"
  ruleC
  printf '    %so%s  open it in Chrome        %sr%s  refresh this panel\n' \
    "$KEYC" "$OFFC" "$KEYC" "$OFFC"
  printf '    %sa%s  open in the default one  %sl%s  the last of the log\n' \
    "$KEYC" "$OFFC" "$KEYC" "$OFFC"
  printf '    %sf%s  the data folder in Finder %sq%s  stop the server\n' \
    "$KEYC" "$OFFC" "$KEYC" "$OFFC"
  ruleC
  printf '\n'
}

open_url(){ open -a "Google Chrome" "$1" >/dev/null 2>&1 || open "$1" >/dev/null 2>&1; }

# CHROME BY PREFERENCE. Safari asks for the microphone once per page load and
# forgets; Chrome remembers the grant for 127.0.0.1, which matters in an app
# whose whole loop is click, speak, click.
open_url "$URL"
show_head

if [ -t 0 ]; then
  # A ONE SECOND READ RATHER THAN A BLOCKING ONE, so the panel notices when the
  # server has died instead of waiting for a key that will never come.
  while kill -0 "$SRV" 2>/dev/null; do
    if IFS= read -rsn1 -t 1 K 2>/dev/null; then
      case "$K" in
        o|O) printf '   %sopening in Chrome%s\n' "$DIMC" "$OFFC"; open_url "$URL" ;;
        a|A) printf '   %sopening in the default browser%s\n' "$DIMC" "$OFFC"; open "$URL" >/dev/null 2>&1 ;;
        f|F) open "$APPDIR/data" >/dev/null 2>&1 ;;
        l|L) printf '\n'; tail -n 15 "$LOG" 2>/dev/null | sed 's/^/     /'; printf '\n' ;;
        r|R) show_head ;;
        q|Q) break ;;
      esac
    fi
  done
  printf '\n   %sstopped%s\n\n' "$DIMC" "$OFFC"
else
  # Not a terminal — piped or launched from somewhere else. Just hold the server.
  wait "$SRV"
fi
LAUNCHEOF
chmod +x "$BIN/sampleplayer.new"
mv "$BIN/sampleplayer.new" "$CMD"

# THE UPDATE COMMAND IS WRITTEN BY update.sh, NOT HERE.
#
# It used to be written here and it re-ran the installer out of a cloned
# repository, which meant it only worked if the clone was still where it had
# been and had no local changes in it. update.sh fetches and CHECKS everything
# before it touches the install, which is the behaviour worth having, and it
# leaves itself behind — so whichever way this app was installed, updating it
# is one word.
#
# Installed straight from the repository rather than through update.sh? Then
# there is no sampleplayer-update yet, and this says so rather than leaving a
# command that half works.
if [ ! -x "$BIN/sampleplayer-update" ]; then
  step "no update command yet — install once through update.sh to get one:"
  printf '     %scurl -fsSL -O %s/update.sh && bash update.sh%s\n' \
    "$DIM" "https://raw.githubusercontent.com/markoboskoauroville/SAMPLE_PLAYER_MACOS/main" "$OFF"
fi
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
