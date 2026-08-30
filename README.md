# Sample Player — macOS

A local Flask server and a web interface, run from the terminal. The same set of cells as the
Android app: record a phrase, transcribe it, replace the voice, play the set back with a
travelling playhead.

Mantra Productions. One person, one Mac.

## Install, and update, with one command

    curl -fsSL -O https://raw.githubusercontent.com/markoboskoauroville/SAMPLE_PLAYER_MACOS/main/update.sh
    bash update.sh

That fetches the app, checks every file before it touches anything, installs it, and leaves
behind two commands:

    sampleplayer            run it
    sampleplayer-update     fetch the newest version and install it

`sampleplayer-update` is the whole update from then on. It asks GitHub for the current version
every time, so there is nothing to remember and no clone to keep tidy.

If you would rather read the script before running it, that is what the two lines above are
for — the file is downloaded first and can be opened. The one-line form exists and is the
honest version of `curl | bash`:

    bash <(curl -fsSL https://raw.githubusercontent.com/markoboskoauroville/SAMPLE_PLAYER_MACOS/main/update.sh)

## Or from a clone

    git clone https://github.com/markoboskoauroville/SAMPLE_PLAYER_MACOS.git
    cd SAMPLE_PLAYER_MACOS
    bash 3sh_i_sample_player_v1_macos.sh
    sampleplayer

## Removing it

    bash 3sh_i_sample_player_v1_macos.sh --wipe

- [`HANDOFF.md`](HANDOFF.md) — the finished state of the app. Start here to pick it up.
- [`DEVELOPMENT.md`](DEVELOPMENT.md) — every decision and why, and what is not ported yet.

The phone edition is [`SAMPLE_PLAYER`](https://github.com/markoboskoauroville/SAMPLE_PLAYER).
The two share a storage layout cell for cell, so a project directory copies between them.
