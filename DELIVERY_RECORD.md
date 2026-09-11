# DELIVERY RECORD — Sample Player, macOS — v3.2 — 11.9.2026

**What was measured for this release, what failed on the way, and what was not tested.** Rewritten
per release. The decisions are in [`DEVELOPMENT.md`](DEVELOPMENT.md); the state is in
[`HANDOFF.md`](HANDOFF.md).

## ARTEFACT

The three files `update.sh` fetches from `main`, plus the updater itself:

    server.py                          110,651 bytes   sha256 d8bb5f83250180e6…
    static/index.html                  119,644 bytes   sha256 f5960d7b2528edf1…
    3sh_i_sample_player_v1_macos.sh     17,475 bytes   sha256 0819455c8b09e255…
    update.sh                            5,631 bytes   sha256 00c35bb66b4da7e3…   (unchanged)

    VERSION     new v3.2    previous v3.1, commit fbbbc2b on main before this merge
    DEPENDS ON  MANTRA_VOICE master from commit 49a07a2 for the consent note.
                The transform itself works with older MANTRA_VOICE.

## WHAT IS NEW

The voice transform, Path A: a take keeps its performance and gets a cloned voice's timbre. Cloned
voices listed with a consent badge. A voice cannot be added without who gave it, what for, and public
or private. A take from a voice not cleared for release downloads with PRIVATE in its file name.

## GATES — `python3 scripts/gates.py`, on the committed tree

    G1 provenance   pass   clean tree, server and installer agree on v3.2, the updater fetches
                           exactly the three files
    G2 secrets      pass   12 files scanned, no key-shaped literal; NEW: the transform section
                           (17,464 characters) holds no ring, probe, spend line or key file
    G3 analysis     pass   the server parses, both scripts bash -n clean, the page's brackets
                           balance (505/505, 1540/1540, 179/179), 46 onclick handlers all exist,
                           31 server routes, 28 called by the page, none missing
    G4 dead code    pass   100 server functions, 33 routes, unreached none; page functions,
                           unreached none
    G5 dead loops   pass   9 whiles in the server, unbounded none; every request through one
                           wrapper with a timeout; every subprocess with a timeout
    G6 stress       pass   NEW, five: the transform writes into gen/ and nowhere else; it names
                           engine clone and checks the answer; the consent note is checked before
                           the upload is kept; the download name carries the release suffix; only
                           .wav files count as generated voices
                    not run: the soak and the monkey, which need a Mac with a microphone
    G7 budgets      pass   253,401 bytes of source against a 260,000 ceiling. 6,599 bytes are
                           left: the next feature starts with a trim
                    not run: cold start, memory and battery, which need the machine
    G8 upgrade      pass   see below, run for real rather than asserted
    G9 record       this document

    checks run 55, failures 0, not run 2          (v3.1: 49 checks)

**Every new gate was seen red** by removing the protection it guards, one at a time: writing over the
take, dropping the engine check, adding a spend line to the transform, dropping the release suffix, and
keeping the upload before checking the note.

## TESTS — `python3 tests/test_server.py`

    135 cases, 0 failures                         (v3.1: 96)

The new ones cover the stretch plan's invariants, the edge snapping, consent, the badge, the stricter
word winning, the release name, the note that came back, and the generated-voice list. One case runs
real ffmpeg and rubberband and measures the rendered track: **worst word edge 7.5 ms from his timing,
over 4 segments.**

**Twelve deliberate breakages, each caught.** The code was broken twelve ways — no absorbing, starting
far too early, joining across a breath, never joining, a private take named public, the looser word
winning, edges not snapped, rubberband's lead ignored, a future date allowed, Finder files as voices,
any note as public, Whisper's nonsense believed — and a test went red for each.

## G8 — UPGRADE, AND THE WAY BACK

**Forward, v3.1 to v3.2, run for real.** v3.1 installed with its installer under a throwaway home,
checked to be v3.1 (`/api/clones` answered 404), and used: a recorded cell with a Speechify take, loop
on, in and out points, a key note at mode 600, rates, and a `.DS_Store` in the cell's `gen/`. v3.2
installed over it.

    every data file, the key note and the rates    byte-identical (7 files)
    keys.txt mode                                  600, kept
    loop, in 120, out 1800                         kept
    generated voices of that cell                  v3.1 ['.DS_Store', 'speechify'] -> v3.2 ['speechify']
    the Speechify take's download name             "Scene six, the lift.wav", unchanged

**Back, v3.2 to v3.1, run for real.** A private-voice transform made on v3.2, then v3.1 installed
over it.

    v3.1 reads the cell                            yes: plays transform-kristijan, 3000 ms
    v3.1 downloads the take                        the exact file
    files touched by the rollback                  none (digests compared)
    tracebacks                                     0
    forward to v3.2 again                          the PRIVATE name is back

**Across the two apps.** v3.2 against MANTRA_VOICE's `master` from before this release, running for
real: the add is refused with the update command, the voice shows red, and `/consent` names the
older MANTRA_VOICE rather than failing on a 404 page. And the v3.2 page served by a v3.1 server, in
Chromium, says to press q and start again.

## FAILED ON THE WAY

- **A voice added with a note ended up with none.** MANTRA_VOICE wrote `meta.json` after the ears, and
  the ears timed out. Fixed in MANTRA_VOICE: the note is written when the cut exists.
- **An older MANTRA_VOICE answers ok and drops the note.** Measured on its master branch. The add is now
  judged by the note that came back.
- **A word rescued exactly to 0.75x was reported as a chirp**, by floating point.
- **`.DS_Store` counted as a generated voice** in v3.1, seen live.
- **Two new tests proved nothing** until the code was broken to check them: one never reached the rule
  it named, and one mutation harness run was misattributed by stale bytecode.
- **Two sandbox commands killed their own shell**, by matching a process name the command itself
  contained. The tests now record process ids in files.
- **One "old version" check ran the new code**, because a worktree of `main` failed (MANTRA_VOICE's
  branch is `master`) and Python imported from the current folder. Caught by asserting the imported
  file's path before believing the result.
- **Found after delivery, 11.9.2026, for the next edition: two transforms at once overwrote each
  other's clone.** The server is threaded and the clone's audio went to one fixed folder. A test with
  two threads and two clips of different loudness had both cells come out loud. Fixed with a folder
  per transform and `mkstemp` in `write_wav`; a new gate refuses a fixed temporary name. Tests 137,
  gates 56.

## MEASURED ON THE MAC, 11.9.2026

By Claude Code on Baba's Mac (M-series, macOS 15, Python 3.10.14, Homebrew ffmpeg 9.0.1_1), the first
day this code ran where it is meant to run. Each line is a thing that was on NOT TESTED below.

- **MANTRA_VOICE under its LaunchAgent after a pull.** `git pull` to 8fc0373, then `launchctl kickstart
  -k gui/501/com.mantra.voiced`: up again in 1 s. Before the restart `POST /consent {}` answered a 404
  page (the old process); after it, `400 {"error":"name the voice"}`. The running process is the new one.
- **The installer and the updater, on a Mac.** `sampleplayer-update` over a 30.8.2026 build: all three
  files arrived intact as v3.2, Flask installed into the existing venv, the key file left alone. The
  installed `server.py` and `static/index.html` are byte-identical to commit 4bba925; the launcher says
  edition v3.2. The server started the launcher's way took port 8084; `/api/version` answers
  `{"installed":"v3.2","latest":"v3.2","behind":false}` and `/api/clones` answers JSON with eight voices.
- **Homebrew's ffmpeg has NO rubberband.** `ffmpeg -filters | grep rubberband` finds nothing and the
  build configuration has no `--enable-librubberband`; Homebrew's ffmpeg 9.0.1 formula no longer
  depends on rubberband (its dependency list has eleven entries and rubberband is not one). The
  `rubberband` command itself, version 4.0.0, is installed at `/opt/homebrew/bin/rubberband`. So on
  this Mac every transform falls back to **atempo**, which does not keep formants, and the report
  says so. The renderer test measured 7.5 ms worst edge with atempo, the same as on Linux.
- **Eight voices, none with a consent note**: actress1, gwyneth, marko, old_actor, rowan, snoop, voice,
  voice1. All show red. The notes are Baba's to give (brief 2.2).
- **MANTRA_VOICE's add without a note, and the red badge.** `POST /add` with a name, a source and a
  cut and no `consent` (what its own Voices page sends) answered 200 and listed the voice with no
  note; Sample Player's `/api/clones` showed it as `no consent recorded`, release false. Removed with
  `/remove`; the eight voices are as they were. The page itself was not clicked; its request was sent.
- **The real models on one English line of Baba's** (cell 00, recorded on the 30.8.2026 build, 4.52 s,
  "There's everything they do. His answer is simple."), clone `marko` (his own voice), model qwen06:
  `/hear?words=1` 1.4 s then 1.0 s (the ears do not cache; the first call of the day was 6.2 s while
  the ears warmed); 8 words heard. `/say` engine clone: **8 tokens for 8 words**, 37.6 s the first
  time, 0.0 s cached. The transform: 1.6 s with the clone cached; report ok 1, smear 0, **chirp 7**,
  worst 2.18x, atempo; output 4.523 s, exactly the take. The clone's clip was 5.44 s for a 4.52 s take,
  and the clone's words were longer than his, so nearly every word was squeezed. `snap_spans` on the
  output against the plan: **worst edge 40 ms** on real speech (7.5 ms on tone bursts). Four more
  English lines are needed for 2.5 and 2.6; they are Baba's to record.
- **Croatian through the English ears, measured, and it is worse than "no alignment".** Five sentences
  cut from Baba's own Croatian recording (`~/Music/VOICES_CLONING/MARKO.wav`, a Patanjali scene) and
  a 60-second stretch of it were put in cells 1 to 6. `/hear?words=1` **translated** them: "Teacher,
  I'm leaving tomorrow at dawn." for *Učitelju, sutra u zoru odlazim*, with a start and end for every
  English word. Whisper medium with detection on says `hr` or `bs` for all six and `en` for cell 00.
  The transform then runs to the end and reports success: the clone says the English translation,
  tokens match words on all six (6/6, 6/6, 9/9, 14/14, 6/6, 142/142), and the result is an English
  sentence in the clone's voice squeezed onto Croatian timing, chirp on 26 of 41 words across the five
  short lines, worst 8.2x. Nothing in the route can tell. Those six cells are left as they are for
  Baba to hear or delete.
- **A 60-second take through the transform.** 142 words heard in 6.1 s (4.7 s the second time; the
  ears do not cache); the clone said them in 17.6 s the first time and 0.0 s cached; the transform
  route, with the clone cached, took 9.7 s, of which the edge snapping in pure Python was 0.1 s and
  the 73 ffmpeg calls of the render the rest. Output 60.000 s, exactly the take. **No speed-up was
  needed**: the brief's worry about `snap_spans` did not survive measurement (on a synthetic 60 s take
  with 150 words: read 0.03 s, snap 0.11 s, plan 0.00 s, write 0.04 s, render 5.7 s).

## NOT TESTED

- **Nothing ran on a Mac.** Not the installer, the launcher, Homebrew's ffmpeg or its rubberband, Chrome
  on macOS, or the file chooser there. *11.9.2026: the installer, the updater, the server and ffmpeg
  now have (see MEASURED ON THE MAC). Still not: the launcher's panel and keys, Chrome, the file chooser.*
- **The real models were never called.** `/hear` and `/say` were a stand-in in their exact response
  shapes. Unexercised: Whisper's actual word times on his voice, a real clone's line and its tokens,
  and whether the clone's word count matches his on real speech (the route refuses when it does not;
  how often that happens is unknown). *11.9.2026: called, on one English line and six Croatian ones;
  the count matched on all seven. Four more English lines wait on Baba's microphone.*
- **How the transform sounds.** The 7.5 ms is where sound lands on tone bursts, not whether a stretched
  vowel of a real voice smears. That is question three of the brief, and it is his.
- **Croatian.** MANTRA_VOICE's ears are fixed to English; a Croatian take was not tried. *11.9.2026:
  tried, see above: the ears translate and the transform cannot tell. Moved.*
- **MANTRA_VOICE under its LaunchAgent after a pull** — *measured 11.9.2026, see above* — and its own
  Voices page after the change.
- **Long takes.** The longest take transformed was 3 seconds with 4 words. The edge snapping reads
  samples in pure Python; a 60-second take has not been timed. *11.9.2026: timed, see above. Moved.*
- **Two transforms of one cell at once**, from two tabs. Both write the same `gen/` file through a
  temporary file and a rename, so the last one wins; not exercised. *11.9.2026: two DIFFERENT cells
  at once is now a test, and it found the clone folder shared (see FAILED ON THE WAY). The same cell
  twice is covered by `write_wav`'s own temporary name per writer, still not driven from two tabs.*

## KNOWN

- **Rolling back to v3.1 removes the PRIVATE warning** from the download names of takes made with private
  voices. The takes and their notes are untouched; going forward to v3.2 restores the names. v3.1 cannot
  be taught a warning it does not have.
- **`sampleplayer-update` from a second terminal** leaves the panel's old server running until q is
  pressed. The page says so; the updater does not stop it.
- **For five minutes after a push, `update.sh` can install a mixture of two versions.** GitHub's raw
  files are cached for 300 seconds, per file, and the updater fetches its three files separately.
  Measured at this delivery: server and page arrived as v3.2 while the installer arrived as v3.1 and
  the updater announced "v3.1". Here the installers differed only in that word; a release where they
  differ in substance would install half of each. Fetching by commit rather than by `main` would close
  it, and is a change to the updater, so it is not in this release. Run on a fresh home five minutes
  later: "all three arrived intact — v3.2", server and page matching the build byte for byte.
- **6,599 bytes of the source budget remain.**
