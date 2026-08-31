# HANDOFF — Sample Player, macOS

**The finished state of the app. Nothing about how it got here.**

Installer edition v3.1. Repository public at `markoboskoauroville/SAMPLE_PLAYER_MACOS`.

Every decision and every gap is in [`DEVELOPMENT.md`](DEVELOPMENT.md).

---

## WHAT IT IS

A local Flask server and a web interface, run from the terminal. A set of cells, each holding one
spoken phrase, transcribed and optionally re-voiced. The same work as the phone edition, on the
machine where the film is cut.

## RUNNING IT

    curl -fsSL -O https://raw.githubusercontent.com/markoboskoauroville/SAMPLE_PLAYER_MACOS/main/update.sh
    bash update.sh
    sampleplayer

`update.sh` is both the install and every update after it. It fetches the installer, the server and
the page, checks all three before touching anything, runs the installer, and leaves behind
`sampleplayer-update`.

From a clone instead: `bash 3sh_i_sample_player_v1_macos.sh`. To remove it: the same with `--wipe`.

The installer writes `~/.sampleplayer-web` and `~/.local/bin` and touches nothing else. Flask is the
only dependency.

## THE TERMINAL PANEL

The launcher shows a panel, not a log — the server's own output goes to `server.log` and only a
crash reaches the screen.

    o / a   open it in Chrome, or the default browser
    f       the data folder in Finder
    l       the last of the log
    r       refresh the panel
    u       update and restart
    q       stop the server

## THE LAYOUT ON DISK

Identical to the phone, cell for cell, so a project directory copies between them.

    ~/.sampleplayer-web/
      venv/                                   Flask
      server.py  static/index.html            the app
      keys.txt                                the key note
      dead.txt                                SHA-256 fingerprints of condemned keys
      spend.jsonl                             one line per billable call
      rates.json                              what a unit costs, if it has been entered
      emotions.json                           custom acting directions
      cache/catalogue-<engine>.json           the voice lists, kept a month
      cache/audio/<sha>.wav                   every generated sound
      port.txt                                written at startup, read by the launcher
      data/projects/<id>/samples/NN/
        original.wav                          the recording. NEVER overwritten
        gen/<engine>.wav                      a generated voice, beside it
        meta.txt                              words, voice, in/out points, loop flag

## THE SCREEN

A grid that fills the window. Right-click a cell for its menu; left-click is the press.

    REC     click a cell to record into it, click again to stop
    PLAY    click a cell to play from there, or toggle its loop if it is marked

Recording over a cell that already holds a take **or a line** asks first, and offers **Play** as
well as Cancel and OK.

    space         stop this cell, start the next
    m             swap REC and PLAY
    left / right  flip the page
    i / o         mark the in and out points, on the cell page
    esc           stop everything

**Three tabs travel together** — Cell · Settings · Keyring, keyring always last. The cell tab
carries ‹ previous and next ›.

## AUDIO

- The browser records and builds the WAV itself: 44.1 kHz, mono, 16-bit.
- The server judges the take, then normalises to −0.1 dBFS with a 20 dB gain ceiling, then
  promotes it. The check runs **before** normalisation.
- Playback is Web Audio given an offset and a duration, so the points are exact and a loop has no
  gap at the join.
- The WAV reader walks chunks rather than assuming byte 44.
- Nothing is ever re-encoded. Both engines are asked for `wav`.

## VOICES

AssemblyAI transcribes and is required. Speechify and Hume are the engines and either is enough.
Emotion tags are written inline — `<angry>` — and Hume receives the pieces as one request.

Catalogues are cached for a month. Every generated sound is cached under the voice, the words and
the tags, so nothing is ever paid for twice.

---

# TESTING KEYS: EVERY TRICK, AND WHY EACH ONE EXISTS

This took longer to get right than anything else in the app, and every rule below was paid for.

## THE CENTRAL TRICK: A LIST CALL ANSWERS 200 FOR A DEAD ACCOUNT

    GET  /v1beta/models      with a spent Gemini key  →  200, here is the list
    POST …:generateContent   with the same key        →  429, "prepayment credits
                                                              are depleted"

Both answers are honest; they answer different questions. The first is *is this a real account*,
and **a spent account is a real account.**

Hume's `/oauth2-cc/token` is the same lie in a different shape: it proves the pair is genuine, and
three of the twenty-one Hume accounts on this ring pass it and refuse every synthesis.

**So the test asks the provider to DO the smallest billable thing it sells.** One word of speech,
one token of text, one second of audio. It costs a fraction of a cent when the account is alive and
**nothing** when it is not — which is the direction that matters.

## THE FIVE ANSWERS

| | colour | means | what to do |
|---|---|---|---|
| **working** | green | it did the work | use it |
| **busy** | amber | throttled this minute | wait. Never delete |
| **no credit** | violet | the key is real and the account is alive, and it can do nothing until somebody pays | top up, or delete deliberately |
| **refused** | red | wrong, revoked, or the wrong provider for the shape | delete |
| **unknown** | grey | the answer says nothing about the key — no network, Cloudflare | try again elsewhere |

**Violet is the one that matters.** Calling it green sends the ring at a wall. Calling it red has
somebody delete a live account they only needed to top up.

## THE WORK PROBE FOR EACH PROVIDER

| provider | probe | note |
|---|---|---|
| **Hume** | `POST /v0/tts`, one utterance, **no voice id** | it accepts an utterance with no voice, so the probe does not depend on a voice still existing next year |
| **Speechify** | `POST /v1/audio/speech`, three characters | the model must match the id — `simba-3.2` only for ids ending `_32` |
| **Groq** | `POST /openai/v1/chat/completions`, `max_tokens: 1` | model from `/openai/v1/models`, skipping whisper, tts and guard models |
| **Gemini** | `POST …/{model}:generateContent`, `maxOutputTokens: 1` | the model is in the **path**, so the url cannot be written down until it is known |
| **Anthropic** | `POST /v1/messages`, `max_tokens: 1` | model from `/v1/models` |
| **AssemblyAI** | upload a one-second clip, then submit it | three requests, and the money answer can arrive at any of them |

**Hume is tested twice**: the token endpoint first, because it is the only thing that proves the api
key and the secret belong together, then the work probe.

## NEVER NAME A MODEL IN A PROBE

The first version named `llama-3.1-8b-instant`, `gemini-2.0-flash` and `claude-3-5-haiku`. **All
three answered 404** — every one retired or renamed, while those accounts actually held
`openai/gpt-oss-120b`, `gemini-2.5-flash` and `claude-opus-5`.

A hard-coded model gives a probe an expiry date, and **the failure it produces looks exactly like a
broken key**, which is the worst possible way for a key tester to break. Ask for the list, take the
first model that fits, then do the work.

## WHEN A PROBE NEEDS AUDIO, MAKE THE AUDIO

AssemblyAI transcribes, so its work probe needs a file, and on a fresh install there is none.

    MANTRA_MANIFEST/fixtures/probe-1s-440hz.wav
    32,044 bytes · sha256 9e2c610d…222ec545
    1 second · 16 kHz · mono · 16-bit · 440 Hz at a quarter of full scale

This app **generates** it rather than fetching it — it must work with no network to a private
repository — and the test suite asserts the digest, so it cannot drift from what the other apps use.

**A tone rather than silence.** Both work; silence completes just as happily. But silence is
indistinguishable from a broken encoder, and the day a provider rejects empty audio, the failure
would look exactly like a dead key.

One second is a hundred-thousandth of a billed hour.

## OUT OF CREDIT AND THROTTLED BOTH SAY "QUOTA"

Gemini answers a spent account and an impatient one with **the same status and the same word**:

    429  RESOURCE_EXHAUSTED  "prepayment credits are depleted"             ← pay
    429  RESOURCE_EXHAUSTED  + QuotaFailure + RetryInfo "retryDelay":"31s"  ← wait

Match on the word alone and you tell somebody to delete a live key because they pressed Test twice
in a second.

**The retry hint is checked first and wins**: `retryDelay`, `Retry-After`, `RetryInfo`,
`QuotaFailure`, "per minute", "try again in". Anything that says how long to wait is saying come
back, not pay up.

Only then the money words, and they are split:

    STRONG, unambiguous:  credit · balance · depleted · insufficient · billing ·
                          payment · prepayment · E0300 · zero_credits
    WEAK, shared with throttles: quota · exhausted · resource_exhausted · free tier

**Match on words rather than on the code.** The same fact is a `400` at Hume, a `402` at Speechify
and a `429` at Google.

## FREE CREDIT DOES NOT COME BACK

From Hume's own billing documentation:

- A new account gets its free credit **once** — $20 on signup.
- The monthly reset belongs to a **subscription**. The cycle starts the day a paid plan begins.
  **No plan means no cycle means nothing to reset.**
- There is **no prepaid top-up**. A subscription with included usage, and overage charged to a card
  in $44 blocks.

Gemini's "prepayment credits are depleted" is the same shape under another name — a billing state,
not a window that reopens.

**So a violet verdict is a decision, not a delay.** The app says *"it needs a paid plan"* rather
than *"try again later"*.

## THE OLDER TRAPS, STILL LIVE

- **A `403` carrying `1010` is Cloudflare, not the key.** Measured across 21 Hume pairs: all 21 fail
  without a User-Agent and all 21 succeed with any string at all. It never condemns.
- **AssemblyAI takes the raw key with no `Bearer`.** Almost every mystery 401 is this.
- **Speechify is tested at `/v1/voices`, never `/v1/models`** — that returns `404 page not found`,
  which reads as a dead key and has condemned working accounts.
- **`sk_` is shared** between Speechify and ElevenLabs; only length separates them, so a 401 tries
  the other host before anything is said about the key.
- **One key per JOB, not per call.** An AssemblyAI upload belongs to the account that made it.
- **Testing is sequential.** Twenty-one accounts asked at once is twenty-one requests in one second,
  and the answer is a column of 429s that say nothing about any of them.
- **Deleting writes `DELETED` over the token** and leaves every other line where it was, because the
  parser reads a key's label from the line above it.
- **Keys are parsed by SHAPE.** A whitespace split has genuinely produced attempts to authenticate
  with the word *cafeteria* and with a Google `srsltid` tracking token.

## WHAT WAS SPENT

Every billable call writes one line with the number the **provider** says it charged for: Speechify
the characters it billed, Hume the characters it was sent, AssemblyAI the audio duration it read.

**The box is the log added up and nothing else.** No running total is stored, so clearing the log
empties the box by arithmetic. Rates default to zero and are asked for rather than invented — an
invented price would look exactly as certain as the measured count beside it.

The log holds no key, no account name, not even a fingerprint.

---

## RUNNING THE CHECKS

    python3 tests/test_server.py     96 cases, no network, no browser
    python3 scripts/gates.py         49 checks, 2 honestly not run

## WHAT HAS NEVER BEEN PROVEN

**Nothing here has run on a Mac.** Written and checked on Linux; the pure functions were walked
directly and the key probes were run against live keys, but no part of the following has been
executed there: the installer, the virtual environment, the launcher, the port file, Chrome
opening, `getUserMedia`, the recorder, the resampler, the editor's drag, the loop, or the playhead.

The likeliest first failure is the microphone: Chrome grants it to `127.0.0.1` without a
certificate and Safari does not always.
