# DELIVERY RECORD — Sample Player, macOS — v3.4 — 11.9.2026

**What was measured for this release, what failed on the way, and what was not tested.** Rewritten
per release. The decisions are in [`DEVELOPMENT.md`](DEVELOPMENT.md); the state is in
[`HANDOFF.md`](HANDOFF.md). The v3.2 record is at commit 4bba925 and v3.3's at 76ff4ba.

## ARTEFACT

The three files `update.sh` fetches from one commit of `main`, plus the updater itself:

    server.py                           108,139 bytes   sha256 a05f8ca596db35c2…
    static/index.html                   119,918 bytes   sha256 71de5efbc597b989…
    3sh_i_sample_player_v1_macos.sh      17,694 bytes   sha256 91781c0c8aa38f50…
    update.sh                             6,684 bytes   sha256 dd8084ffe7e1cf25…

    VERSION     new v3.4    previous v3.3, commit 72694e8 on main (v3.2 at 4bba925)
    DEPENDS ON  MANTRA_VOICE master from commit 49a07a2 for the consent note (8fc0373 is on this Mac).
    BUILT BY    Claude Code on Baba's Mac, from this repository's tree: the first edition made where
                it runs. No CI; accepted in the record as v3.2's was.

## WHAT IS NEW

**v3.4, the same evening, two things Baba asked for on the page:** a second click on the playing cell
stops it (it used to start the take again; only a looping cell stopped), and the bar reads as a mode:
"mode: PLAY" or "mode: REC", small, at the left, with the settings gear alone on the right and no frame.
Nothing on the server changed but the edition.

**v3.3, earlier that day.** Three fixes and no feature. Two transforms at once no longer read each other's clone (a folder per
transform, removed when it ends; `write_wav` through `mkstemp`, so one cell from two tabs finishes two
whole files). The updater fetches the installer, the server and the page from one commit rather than
three separately cached files from `main`. Stale transform folders are swept at start, and the
installer creates the key file at mode 600. 4,219 bytes of comment that repeated the documents were cut.

## GATES — `python3 scripts/gates.py`, on the committed tree

    G1 provenance   pass   clean tree, server and installer agree on v3.3, the updater resolves main
                           to one commit and fetches exactly the three files from it (NEW)
    G2 secrets      pass   files scanned, no key-shaped literal; the transform section holds no ring,
                           probe, spend line or key file
    G3 analysis     pass   the server parses, both scripts bash -n clean, the page's brackets balance,
                           every onclick handler exists, every route the page calls exists
    G4 dead code    pass   server functions and routes, unreached none; page functions, unreached none
    G5 dead loops   pass   whiles bounded; every request through one wrapper with a timeout; every
                           subprocess with a timeout; the Run Command poll and the test's barrier
                           both have deadlines
    G6 stress       pass   the five of v3.2, and NEW: two transforms at once cannot share a temporary
                           file (a fixed name in transform_cell or write_wav is red)
                    not run: the soak and the monkey
    G7 budgets      pass   251,439 bytes of source against a 260,000 ceiling: 8,561 free after the
                           trim (v3.2 had 6,599)
                    not run: cold start, memory and battery
    G8 upgrade      pass   see below, run for real on this Mac
    G9 record       this document

    checks run 58, failures 0, not run 2          (v3.3: 57, v3.2: 55)

**The v3.4 gate, "a second click on the playing cell stops it", was seen red** with the stop line
removed. **And writing it found that the gates' comment stripper had been eating nine tenths of the
page**: a closing `*/` on its own line begins with a star, the stripper dropped star lines before
matching comments, and every block comment ran on to the next `*/` that ended a text line. The
page's stripped code was 11,833 of 112,337 characters. Fixed (comments first, lines second); the
page's code is 82,158 characters now, and one older check, "nothing in the app can render a key",
promptly went red on `e.key`, the keyboard's key, seven times — the check had never looked at that
part of the page. Narrowed, with the reason beside it. Both v3.3 gates were seen red: the fixed folder and the fixed `.tmp` name each put back in turn,
and the updater's commit resolution removed.

## TESTS — `python3 tests/test_server.py`

    138 cases, 0 failures                         (v3.3: 138, v3.2: 135)

The three new ones: two threads transform two cells against a stand-in MANTRA_VOICE answering two
clips of different loudness, with a barrier at the decode so the collision is certain — **red on v3.2
every run** (both cells came out at the loud clip's peak 13,345; after the fix 1,950 and 13,345); the
transform's temporary folder is gone when it ends; stale folders are swept at start.

## G8 — UPGRADE, AND THE WAY BACK, RUN FOR REAL ON THIS MAC

Run for v3.3 and again for v3.4 (v3.2 → v3.4 → v3.2 → v3.4), the same results both times.

Under a throwaway home. v3.2's three files from commit 4bba925, installed with its own installer,
checked to be v3.2, and used: a real take recorded into cell 3 through `/api/record`, words, loop, in
and out points, a label-only key note at mode 600, rates, a `.DS_Store` in `gen/`, and a transform
with the real MANTRA_VOICE (voice marko, no consent note). The server stopped as the panel's `u` stops
it, v3.3 installed over it, the server started again.

    /api/version                                   v3.3; /api/clones 200
    every data file, the key note and the rates    byte-identical (6 files)
    keys.txt mode                                  600, kept
    meta: words, loop, in 120, out 1800, report    kept, byte for byte
    the transform plays                            200, 398,942 bytes
    the download name                              "Scene six, the lift (PRIVATE voice marko, not for release).wav", unchanged
    a transform again on v3.3                      ok; no tmp-transform* folder left, no .tmp in gen/
    tracebacks                                     0

**Back, v3.3 to v3.2.** v3.2 installed over it: v3.2 reads the cell (200, the same bytes), the same
download name, **files touched by the rollback: 0** (digests compared), tracebacks 0. Forward again:
the same name, and the second install changed nothing.

**The first run of this test found a fault**: after v3.3's transform one temporary folder remained. It
was v3.2's fixed `tmp-transform/`, which v3.2 never removed. v3.3 now sweeps `tmp-transform*` at start.

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

- **The updater's own Test 4, run for real after the push.** v3.3 pushed as d633bdb; `sampleplayer-update`
  installed it ("commit d633bdb", server and page byte-identical to it). A trivial change to the
  installer pushed as 72694e8 at 17:50:59; an update one second later still resolved d633bdb (GitHub's
  API answer is cached 60 s) and installed **all three files from d633bdb**, no mixture; an update at
  17:52:30 resolved 72694e8 and the installer arrived at 17,694 bytes, 72694e8's size (d633bdb's is
  17,577). Three files, one commit, every time.
- **The eight voices have their notes**, written 11.9.2026 in Baba's words through `clone.py consent`:
  all private, "private experiments only"; marko and voice1 given by "Marko Bosko, myself"; voice by
  "Manan Periwal; his parent has not yet confirmed permission for a clone"; gwyneth, snoop, rowan,
  actress1 and old_actor "no permission is recorded; taken from a recording". `/api/clones` shows all
  eight amber, "private, for experiments".

## FAILED ON THE WAY

- **The gates read a tenth of the page for months and said PASS** (v3.4). See GATES above. A check
  that finds nothing and a check that runs on nothing look the same; this one printed counts from
  the raw page while its stripped copy was nearly empty. In the manifest's checking-the-checks.

- **Two transforms at once overwrote each other's clone** (Part 1 of the brief). Found after v3.2 was
  delivered; the test was red on v3.2 every run; fixed as above.
- **v3.2 left its temporary folder behind, for ever.** Seen in the upgrade test, not by reading.
- **The installer created the key file at mode 644.** Measured in the upgrade test on v3.2's
  installer; the file holds credentials. 600 now, on creation only; an existing file is never touched.
- **The English ears translate Croatian.** Not a fault of this app, and it cannot see it: see MEASURED
  ON THE MAC. A Croatian take gives an English sentence in the clone's voice, on the take's timing.
- **Homebrew's ffmpeg 9.0.1 has no rubberband filter.** The fallback to atempo works and is reported;
  formants are not kept. The `rubberband` command, 4.0.0, is installed separately and unused.
- **The old updater could mix two versions for five minutes after a push** (known at v3.2). Closed.

## NOT TESTED

- **Four of the five English lines** of brief 2.5 and 2.6, and the microphone path on this Mac: only
  one English take of Baba's existed on the Mac. The count of tokens against words matched on all
  seven lines tried (one English, six Croatian).
- **How the transform sounds**, against picture: Baba's ears, `~/Desktop/transform-listening/`.
- **The page in Chrome on macOS**: the badge colours, Transform this take, the report, Add a voice…
  with the file picker, the dimmed button, ⤓ Download's file name in Downloads. The routes behind
  every one of them ran; the clicks did not. *v3.4's bar was looked at in Chrome from a throwaway
  server: "mode: REC" small at the left, the gear at the right. The second click was not clicked.*
- **The launcher's panel and its keys** (o, f, l, r, u, q): the server was started the launcher's way,
  the panel was not driven.
- **The soak and the monkey**; cold start, memory and battery.

## KNOWN

- **Rolling back to v3.1 removes the PRIVATE warning** from download names (v3.1 cannot be taught it).
  Rolling back to v3.2 keeps it, measured.
- **`sampleplayer-update` from a second terminal** leaves the panel's old server running until q.
- **For five minutes after a push the `sampleplayer-update` command may run the previous `update.sh`**
  (it fetches that one file from `main`); the three files it installs still come from one commit.
- **On this Mac every transform uses atempo**, until an ffmpeg with rubberband is installed.
- **`/api/version` can say "latest v3.2" for five minutes after a release**: it reads the published
  installer from `raw/main`, which is cached 300 s. Seen at 17:51 on 11.9.2026 with v3.3 installed.
- **The six Croatian takes** put into cells 1 to 6 of project-01 for the measurement are Baba's to
  keep or delete.
- **7,565 bytes of the source budget remain.**
