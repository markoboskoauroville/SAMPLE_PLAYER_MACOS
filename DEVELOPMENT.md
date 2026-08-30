# DEVELOPMENT — Sample Player, macOS

**Every decision and why, and what is not ported yet.**

[`HANDOFF.md`](HANDOFF.md) is the finished state. This is the record of getting there.

Written 30.8.2026, from the framework in
[`MA_READER_TERMUX_MACOS`](https://github.com/markoboskoauroville/MA_READER_TERMUX_MACOS) and the
twenty versions of [`SAMPLE_PLAYER`](https://github.com/markoboskoauroville/SAMPLE_PLAYER).

---

# PART ONE — THE DECISIONS

## The installer follows MA Reader, except for one thing

Taken from it directly: the three-tier colour probe, the ASCII logo in the same fire-to-ember
gradient with an ash version for removal, `rule`/`row`/`step`/`good`/`bad`, the probe before the
install so a missing `python3` fails with a sentence rather than a traceback, the launcher written
as `.new` and moved, the port picked by binding upward, `caffeinate -dimsu -w $$`, and Chrome by
preference with the system default as a fallback.

**What is different: this installer does not carry the app inside itself.**

MA Reader's does, and that is right for it — it is pasted into a phone over SSH, where a repository
is not available and one file is the only thing that can arrive. On a Mac the repository *is*
available, because this script was cloned rather than pasted. And a five thousand line HTML page
inside a quoted heredoc cannot be linted, cannot be diffed usefully, and cannot be opened in an
editor that knows what it is looking at. So `server.py` and `static/index.html` are real files and
the installer copies them.

## The browser records, and builds the WAV itself

`MediaRecorder` gives webm/opus, which would need ffmpeg on the far side to become anything this
app can read, draw or loop. So the page takes raw samples through a `ScriptProcessor`, downmixes to
mono, resamples to 44 100 and writes the WAV header in JavaScript.

**The dependency list stays at Flask**, and the bytes that reach the server are already the format
everything downstream expects. The resampling is linear and says so in the source: the browser
gives 48 kHz on this machine and 44.1 is one ratio away, so the artefacts sit far below the noise
floor of a room microphone.

`ScriptProcessor` is deprecated in favour of `AudioWorklet`. It is used anyway because it works in
every browser today with no separate module file to load, and replacing it is a contained change
when it finally goes.

## Playback is Web Audio, not an `<audio>` tag

A tag would need a seek to honour the in point, and **a seek that has not landed when playback
starts plays from zero** — which is exactly the bug the phone edition had at v17, where
`MediaPlayer.seekTo` turned out to be asynchronous and broke both ends of the trim silently.

A buffer source is given the offset and the duration when it is started, so the boundaries are the
ones asked for. `loop` with `loopStart` and `loopEnd` on the same node is sample-accurate, so the
gapless loop needs no separate mechanism at all — on Android it needed `AudioTrack` in
`MODE_STATIC`.

## There is no overlay, and no triangle

That whole mechanism exists because a phone shows one app at a time. A Mac shows the script and
this window side by side, so **space** does what the triangle did: stop this cell, start the next.
It does not wrap at the last cell, for the same reason it does not there — wrapping would overwrite
cell 1 while nobody is looking at the grid.

## Everything carried across from the phone without argument

These were all paid for once already and are not re-decided here:

- `original.wav` protected by the **path**, generated audio one directory down in `gen/`
- the quality check **before** normalisation, or room tone and a quiet phrase are
  indistinguishable once both sit at the same peak
- the gain capped at 20 dB, or an empty room becomes a convincing wall of hiss
- a temporary file and a rename for the one file that cannot be made again
- the WAV reader **walking chunks**, because Speechify writes `RIFF / fmt / LIST / data` and its
  data size is `0xFFFFFFFF`
- one key held for a whole transcription job; a condemnation **retries** on the next key
- a 403 carrying `1010` is Cloudflare and never condemns; the User-Agent set in one place
- the Speechify model derived from the voice id; the catalogue walked by cursor to the end
- the direction sent to Hume only when there is one
- keys parsed by **shape** and never displayed; the dead list holds fingerprints
- controls first, help in one block at the bottom, one × per screen

## The Flask app is one file, and stays one file

MA Reader's server is four thousand lines in one file and it is navigable, because the sections are
marked and the traps are written where they bite. Splitting this into a package would buy nothing
at this size and would cost the property that the whole server can be read top to bottom.

---

## One bug worth writing down, and it was in the tooling rather than the app

Writing this repository's documents through shell heredocs ran three of them.

An unquoted heredoc performs command substitution, so a backtick in prose is a command. The
README's `` `sampleplayer-update` `` ran as a command and left a hole where the word should have
been. Worse, the handoff's `` `bash 3sh_i_sample_player_v1_macos.sh` `` **ran the installer**, and
its ASCII banner and thirty lines of progress output were substituted into the middle of the
document — which is how a handoff came to contain a picture of its own installation.

The heredoc had already bitten twice earlier in the same session on commit messages. The rule that
comes out of it, and it is not subtle: **prose with backticks in it never goes through a shell.**
Write the file, or write a script that writes the file. The apostrophes, the em dashes and the
backticks that make documentation readable are all shell metacharacters, and a document is exactly
the kind of text that is full of them.

---

# PART TWO — WHAT IS NOT PORTED YET

Said plainly rather than discovered. The phone edition is at v20 and this is v1.

- **The key screen.** Keys are read from `keys.txt` and shown in settings, but there is no Test,
  no Test all and no Delete. The parser, the ring, the classifier and the dead list are all here;
  only the screen is missing.
- **Projects.** One project, `project-01`. The storage layout is per-project already, so this is a
  picker rather than a rewrite.
- **The Seq view.** No custom running order; the sequence is the filled cells in order.
- **Facet chips in the voice chooser.** Search works and is the same word-prefix multi-term rule.
  The facets are in the data and are not yet drawn as filters.
- **The full emotion set.** Sixteen of the phone's thirty-eight, chosen across the same groups.
- **Save a take to a file.** The recording is on disk at a known path, so this is a convenience
  rather than a capability.
- **A delivery gate and Test 1.** The phone edition has 234 cases and 182 structural checks and
  this has none. The pure functions were walked by hand — normalise, classify, parse_keys,
  clean_text, assess, waveform, explain — and that is not the same thing as a suite.

---

# PART THREE — WHAT HAS NEVER RUN

**Nothing in this repository has been executed on a Mac.** It was written and syntax-checked on
Linux; the shell parses, the Python parses, the page's braces balance, and every pure function in
the server was walked directly with real values.

None of the following has been run even once: the installer, the virtual environment, the launcher,
the port file, Chrome opening, `getUserMedia`, the recorder, the resampler, the WAV the browser
builds, any network call from this machine, the editor's drag, the loop, or the playhead.

That list is the first thing to work through, and the most likely place for it to fail first is the
microphone: Chrome grants it to `127.0.0.1` without a certificate, and Safari does not always.

---

# THE TWO EDITIONS, COMPARED

Written 30.8.2026, with the phone at v21 and the terminal at v2.5. The terminal edition was built
in a day from twenty versions of the phone one, and then went past it in several places because a
Mac makes some things cheap that a phone makes dear.

**Both have:** the storage layout cell for cell, `original.wav` protected by the path, the quality
check before normalisation, the 20 dB gain ceiling, the WAV chunk walker, one key per
transcription job, a condemnation retrying on the next key, 403/1010 never condemning, the
User-Agent in one place, the Speechify model derived from the voice id, both catalogues walked to
the end, keys parsed by shape and never displayed, the faceted voice browser, per-cell loop flags,
in and out points that cut nothing, and controls first with help in one block.

## WHAT THE TERMINAL HAS AND THE PHONE DOES NOT

| | Why it landed there first |
|---|---|
| **Inline emotion tags** `<angry>` mid-line, with Hume receiving the pieces as one request | A keyboard makes a tag cheap to type. It is the biggest gap and the one worth closing first |
| **Custom emotions**, shared by every voice | Same reason: two text fields and a button |
| **An editable line** on the cell page and the card, both writing to the same cell | The phone shows the transcript read-only, so a wrong word means re-recording |
| **A cache** of catalogues and of every generated sound | The phone re-fetches 1152 voices on every open and re-bills every repeat |
| **The remembered last voice** | The phone asks per cell |
| **Render and download a line** without touching a cell | The phone can only save a cell's own recording |
| **Download named after the transcript** | The phone's save uses the cell number |
| **▶ on every row** of the voice list | The phone opens a card to hear one voice |
| **Facet chips carrying counts** computed against the other filters | The phone's chips have no counts |
| **A status line with a spinner that cannot be forgotten** | Every network call goes through one wrapper |
| **A live three-second scope while recording** | The phone draws a live waveform already, but not a wrapping window |
| **Check for updates** | *Closed in phone v21* |

## WHAT THE PHONE HAS AND THE TERMINAL DOES NOT

| | Why it stays there |
|---|---|
| **The overlay: hairline, triangle, status** | A phone shows one app at a time. A Mac shows the script and the app side by side, so the keyboard does what the triangle did |
| **Recording from another app** | The same reason |
| **The key test screen** — test, test all, delete | The parser, the ring and the classifier are all in the terminal already; only the screen is missing |
| **Projects** | The terminal has one, `project-01`. The storage is per-project already, so this is a picker |
| **234 test cases and 182 structural checks** | The terminal has 74 and 49, and its gates say plainly which two cannot run without a Mac |

## THE ORDER THESE SHOULD BE CLOSED IN

1. **The cache.** It costs money and time on every session and it is server-side logic that ports
   directly. Nothing else on this list is spent in credits.
2. **Inline emotion tags.** The largest behavioural difference, and the reason Hume is in the app.
3. **The editable line.** A transcript with one wrong word currently means re-recording a take.
4. **The remembered voice.** Turns a thirty-cell set from ninety presses into three.
5. **Render and download.** The phone can already save a take; this is the same door for a line.
6. Counts on the facet chips, and ▶ in the list.

None of these is hard. They are listed rather than done because a list of five ports done badly in
one sitting is worse than one done properly, and because writing them down is how they stop being
things only one session remembers.
