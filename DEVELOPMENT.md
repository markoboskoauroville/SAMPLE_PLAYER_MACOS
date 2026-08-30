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
