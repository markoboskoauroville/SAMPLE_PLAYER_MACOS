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

## The voice transform, Path A — edition v3.2, 11.9.2026

**His performance, their timbre, using only what is already on the Mac.** MANTRA_VOICE clones by
text-to-speech, so what it says has the model's rhythm. The transform puts his rhythm back: his words
from `/hear?words=1`, the same words spoken by the clone through `/say`, both sets of word edges
snapped onto the sound, a plan that lays each of their words onto his window, and rubberband onto a
silent track exactly as long as his take. Written into `gen/transform-<voice>.wav`, never over the
recording.

**The plan tries the cheap things first.** A word already between 0.75x and 1.3x is left alone. A
word of his that is much longer lets its tail go silent, up to 300 ms, with the onset kept where he
said it. A word that is much shorter borrows the pause after it, and at most 50 ms before, because
sound arriving before a mouth opens is the lip sync error the eye catches first. Past that, the word
is joined to the words he ran on into and stretched as a phrase. Past that, **the report says smear or
chirp** and names the word and its time, rather than claiming it is clean.

**Word edges are snapped, because Whisper's are loose.** It places a boundary from attention, not
from the waveform, and 30-80 ms out is common, which is most of the lip sync budget. Each edge looks
50 ms either way in 10 ms frames. Measured on a synthetic take through real rubberband: the worst edge
in the rendered track landed 7.5 ms from where he said the word. That measures where sound lands, not
how it sounds; how it sounds is his to judge.

**Three facts read from MANTRA_VOICE's code before a line was written, each of which would have made
the transform quietly wrong:**

- `d` in `/hear`'s words is the word's **end time**, from `round(w.end, 3)` in `ears.py`. `API.md`'s
  example reads like a duration and the brief said "start and duration".
- `/say` takes its engine from the Mac-wide setting when none is sent. With the computer's voice set
  to Beatrice, a request naming a clone is spoken by Speechify, billed, and reported under the
  clone's name. So the transform sends `engine: clone` and refuses any answer that is not that engine
  and that voice.
- `ears.py` fixes `language='en'`. **Path A works on English lines only** until that changes.

**A local engine has no key, no credit probe and no spend line.** A gate asserts it over the whole
transform section, so the next change cannot bolt one on because the key ring is there.

### Consent, and the badge

A voice cannot be added without **who gave it, what for, and public or private**. The date defaults to
today and cannot be in the future. The note lives in MANTRA_VOICE's `meta.json` beside `ref.wav`, so
every app on the Mac that lists voices sees it, not only this one; MANTRA_VOICE checks the same rule
(`clean_consent`) and this app checks it first (`consent_problem`) so a refusal comes before the upload.

**Public or private has no default.** A default is where nobody thinks. Green is public, amber is
private, **red is no note at all**, the one real fault on the page. A voice from before notes existed
is red and is treated as stricter than private; choosing it offers to record the note.

**The warning travels in the file name.** A take goes into a Resolve bin under the words it says, and
nothing else about it is visible there, so a take made with a voice that is not cleared downloads as
`Can I talk now (PRIVATE voice kristijan, not for release).wav`. The cell remembers the usage at the
moment of the transform, the voice's current note is asked at the moment of download, and **the
stricter word wins** — a voice withdrawn later makes its old takes private at once, and a voice made
public later does not make an old take public by surprise.

### What the tests found that reading did not

- **A voice added with a note ended up with none.** The ears timed out after the reference was cut,
  and MANTRA_VOICE wrote `meta.json` last. It now writes the note the moment the cut exists, and a
  failed transcription is an empty `ref.txt` rather than a failed add.
- **A word rescued exactly to 0.75x was reported as a chirp.** Floating point landed a hair under the
  limit. A millionth of tolerance, and a test sweeping two hundred lengths both ways.
- **`.DS_Store` counted as a generated voice.** Finder writes one the first time a cell's folder is
  opened; the old code listed every file in `gen/`. Seen live on v3.1 in the upgrade test.
- **Two of the new tests proved nothing.** Found by breaking the code twelve ways and watching which
  tests went red: the 50 ms rule was never reached, because the words in that test joined into a phrase
  first. **And the mutation harness itself lied twice** until it ran with `PYTHONDONTWRITEBYTECODE=1`:
  stale bytecode attributed one mutation's failures to the next.
- **Two transforms at once read each other's clone.** Found 11.9.2026 after v3.2 was delivered, on
  the first day the code ran on the Mac. The server is threaded and `transform_cell` wrote the clone's
  audio to one fixed folder, `tmp-transform/clone.mp3`; two cells transformed together decoded the
  same file, and the test that proves it (two threads, two stand-in clips of different loudness, a
  barrier at the decode so the collision is certain) had both cells peaking at the loud clip's 13,345.
  Now a folder per transform from `tempfile.mkdtemp`, removed in a `finally`, and `write_wav` through
  `mkstemp`, so the same cell from two tabs finishes two whole files and the last one wins. A gate
  goes red if either fixed name comes back; seen red both ways.

### The updater fetches one commit, not three files from `main` (11.9.2026, for v3.3)

`update.sh` asks `api.github.com/repos/…/commits/main` for the commit `main` is at (no key, sixty
calls an hour, GitHub's own cache on that answer is 60 seconds) and fetches the installer, the server
and the page from `raw.githubusercontent.com/…/<sha>/`. A commit's files never change, so the
five-minute window in which the old updater could install half of two versions is closed. Every
refusal stays: size, shebang, `bash -n`, `ast.parse`, doctype. If the API does not answer, the three
files come from `main` and the updater says so in amber. The `sampleplayer-update` command it leaves
behind still fetches `update.sh` itself from `main`, so for five minutes after a push the updater
that runs may be the previous one; the three files it installs are still one commit's. Run for real
on this Mac: "commit 4bba925", all three intact, the installed files byte-identical to that commit.

### The trim before v3.3 (11.9.2026)

4,219 bytes of comment removed, no code and no protection: the server's module docstring (every
line of it is DEVELOPMENT.md Part One), the voice-transform header (the five steps and the limit are
in "Path A" above), the money-words essay and the probe-clip docstring (both measured 30.8.2026 and
written up in HANDOFF.md), and the page's credit-button comment (HANDOFF.md, "THE CENTRAL TRICK").
Each was cut to its one-line reason and a pointer to the document that holds the rest. The budget:
250,831 of 260,000 bytes, 9,169 free.

### First click plays, second click stops (v3.4, 11.9.2026)

Baba: "it does not repeat playing on second click. First click plays, second click stops." Until v3.3
a second click on a playing cell started the take again from its in point, while a looping cell
already stopped on the second click. Now `press()` asks first whether this cell is the one playing,
and stops it; the loop toggle and the play come after. A gate holds the order.

Same evening, the bar: "please write mode next to play … it needs to be clear that it is a mode, align
it to the left side of the screen, make the button smaller, and settings on the right without a frame."
So `bar()` puts a small "mode: PLAY" / "mode: REC" first, then the spacer, the page arrows, and a bare
gear. `mk()` sets `flex: 1` inline, which beats a class, so the button's width is set inline too.

**And the gate written for the click found the gates half blind.** `code_only` dropped every line
beginning with a star before matching block comments, so a comment's own closing `*/` line vanished
and each `/*` ran on to the next `*/` that ended a text line: 11,833 of the page's 112,337 characters
survived. Comments are matched first now. One check went red at once on `e.key`, the keyboard's key;
narrowed. Written into `MANTRA_MANIFEST/modules/checking-the-checks.md` as face 6a.

### The stale-server case

`sampleplayer-update` run in a second terminal replaces the page on disk while the panel's old server
keeps running from memory. The new page asking the old server for `/api/clones` gets a 404, and says:
*press q in the Sample Player terminal, then run sampleplayer again*. Proven by serving the v3.2 page
from the v3.1 server in Chromium.

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
