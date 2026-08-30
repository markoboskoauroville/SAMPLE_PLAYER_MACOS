# HANDOFF — Sample Player, macOS

**The finished state of the app. Nothing about how it got here.**

Version 1. Repository public at `markoboskoauroville/SAMPLE_PLAYER_MACOS`.

Every decision and every gap is in [`DEVELOPMENT.md`](DEVELOPMENT.md).

---

## WHAT IT IS

A local Flask server and a web interface, run from the terminal. A set of cells, each holding one
spoken phrase, transcribed and optionally re-voiced. The same work as the phone edition, on the
machine where the film is cut.

## RUNNING IT

    bash 3sh_i_sample_player_v1_macos.sh
    sampleplayer

The installer writes `~/.sampleplayer-web` and `~/.local/bin/sampleplayer` and touches nothing
else. Flask is the only dependency. The launcher starts the server, waits for the port file, opens
Chrome, and holds the Mac awake until it exits.

## THE LAYOUT ON DISK

Identical to the phone, cell for cell, so a project directory copies between them.

    ~/.sampleplayer-web/
      venv/                                   Flask
      server.py  static/index.html            the app
      keys.txt                                the key note, with its instructions inside it
      dead.txt                                SHA-256 fingerprints of condemned keys
      port.txt                                written at startup, read by the launcher
      data/projects/<id>/samples/NN/
        original.wav                          the recording. NEVER overwritten
        gen/<engine>.wav                      a generated voice, beside it
        meta.txt                              words, voice, in/out points, loop flag

## THE SCREEN

A grid that fills the window. Two settings decide the layout: how many cells and how many pages.
Right-click a cell for its menu; left-click is the press.

    REC     click a cell to record into it, click again to stop
    PLAY    click a cell to play from there, or toggle its loop if it is marked

One toggle bottom right. Recording over a cell that already holds something asks first, and offers
**Play** as well as Cancel and OK.

    space         stop this cell, start the next
    m             swap REC and PLAY
    ← →           flip the page
    esc           stop everything
    right-click   a cell's menu

## AUDIO

- The browser records and builds the WAV itself: 44.1 kHz, mono, 16-bit.
- The server judges the take, then normalises to −0.1 dBFS with a 20 dB gain ceiling, then
  promotes it. The check runs **before** normalisation.
- Playback is Web Audio, given an offset and a duration, so the in and out points are exact and a
  loop has no gap at the join.
- The WAV reader walks chunks rather than assuming byte 44.

## VOICES

AssemblyAI transcribes and is required. Speechify and Hume are the engines and either is enough.
Keys go in `keys.txt` as one paste of the whole note; they are found by shape and never displayed.

- One key is held for a whole transcription job.
- A condemnation retries the same request on the next key.
- A 403 carrying `1010` is Cloudflare and never condemns.
- The User-Agent is set in one place.
- The Speechify model follows the voice id.

## WHAT HAS NEVER BEEN PROVEN

**Nothing here has run on a Mac.** It was written and syntax-checked on Linux, and its pure
functions were walked directly, but no part of the following has been executed:

- the installer, the venv, the launcher, the port file, Chrome opening
- `getUserMedia`, the ScriptProcessor recorder, the resampler, the WAV the browser builds
- any transcription or voice call from this machine
- the editor's drag, the loop, the playhead
