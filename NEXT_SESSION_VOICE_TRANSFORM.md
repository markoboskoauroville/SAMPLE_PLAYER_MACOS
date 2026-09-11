# NEXT SESSION — the voice transform engine

**A brief for whoever picks this up. Read [`HANDOFF.md`](HANDOFF.md) first for what the app is.**

Written 31.8.2026 at the end of a long session, so that the next one starts from what is known
rather than rediscovering it. Everything below marked *measured* was run against live systems.

> **Status, 11.9.2026: Path A is built** (edition v3.2) and the three opening questions in §8 are
> answered there. Three facts in this brief were wrong and are corrected where they stand, with the
> old wording quoted: the meaning of `d` (§3, §4), the Oracle allowance (§5), and what NVIDIA offers
> (§5). The decisions and measurements are in [`DEVELOPMENT.md`](DEVELOPMENT.md).

---

# 1. WHAT BABA ASKED FOR, IN HIS WORDS

> "I clone my friend's voice or another actor in the film who gave clear permission. And then in the
> timeline I right-click and it just picks up my own performance and just changes the voice. It
> follows closely the timings, it's a lip sync. Complete lip sync."

That is DaVinci Resolve's **Voice Convert**, and it is the correct thing to aim at.

# 2. THE DISTINCTION THAT DECIDES THE WHOLE DESIGN

**Do not skip this. Building the wrong one produces something that sounds fine in isolation and is
useless against picture.**

| | takes | timing of the result |
|---|---|---|
| **Text-to-speech cloning** | **text** + a reference wav | the model's invention |
| **Speech-to-speech conversion** | **his audio** + a reference | **his, untouched** |

`MANTRA_VOICE` — which is already installed on his Mac — does the **first**. Qwen3-TTS and
chatterbox are zero-shot TTS. They have never heard the performance, so the pauses, the emphasis,
the breath before the hard line do not survive. Against picture it drifts inside one sentence.

His own API confirms it: `/hear` and `/say`, and no `/convert`.

# 3. WHAT IS ALREADY ON THE MAC

Private repo **`MANTRA_VOICE`**. Read its `README.md` and `API.md` before writing anything.

    voiced.py    Flask on 127.0.0.1:8837, always up via a LaunchAgent
    clone.py     the clone models behind ~/.voice/clone.sock
    ears.py      Whisper (mlx-whisper) behind ~/.voice/ears.sock
    timing.py    aligns heard words to written words — HALF THE JOB IS ALREADY HERE

    POST /hear?words=1   → {"words": [{"w": "Can", "t": 0.12, "d": 0.3}, …]}
                           t is the START and d is the END, both in seconds. d is NOT a duration:
                           ears.py writes round(w.end, 3) into it. (Read from the code 11.9.2026;
                           the example above reads like a duration and nearly built the stretch wrong.)
    POST /say            → mp3 + tokens + sents
    GET  /health         → {"engine": "clone", "voice": "voice1", "model": "qwen06"}

    No key. CORS open. Any app on the Mac may call it.

Models, all free, all local, on the GPU through **mlx-audio**:

| key | model | size | clones from |
|---|---|---|---|
| `qwen06` | `mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit` | 2.0 GB | reference wav **+ its words** |
| `qwen17` | `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` | 3.1 GB | the same, bigger |
| `turbo` | `mlx-community/chatterbox-turbo-8bit` | 1.2 GB | reference wav **alone**, English |

**"The voice is shown, not trained."** Zero-shot: twelve seconds of reference, one speaker. There
is nothing to train and nothing to store but the wav. Adding a voice is one ffmpeg cut.

# 4. THE TWO PATHS, AND WHICH TO BUILD FIRST

## PATH A — performance-locked cloning, using only what is installed

1. `POST /hear?words=1` on Baba's take → **his** words, each with a start `t` and an end `d`
2. `POST /say` in the friend's cloned voice, **with `engine: clone`** → the line, wrong rhythm, and
   **their** word times already measured: `/say` runs the ears on the clip and returns `tokens`
3. Both sets of word edges snapped onto the sound, because Whisper's are tens of milliseconds loose
4. Stretch each of their words onto his word's start and end

His rhythm, his pauses, his emphasis placement, their timbre.

> Until 11.9.2026 step 1 said "each with `t` and `d`", step 3 was a second `/hear` on the clone, step 4
> said "start and duration", and this line said "`timing.py` already does step 4's alignment". Three
> corrections: `d` is the end; `/say` already returns the clone's word times, so the second `/hear` is
> not needed; and `timing.py` aligns heard words to the **written text**, not to another take's
> times — the stretch plan is new code (`plan_stretch` in `server.py`). And `/say` must be sent
> `engine: clone`, or on a Mac set to Beatrice it speaks with Speechify under the clone's name.

**The honest limit, and it must be told to him plainly:** where his word is much longer than
theirs, the stretch smears. Past roughly **1.3×** it is audible, and below **0.75×** it chirps.

Mitigations, in order of how much they buy:
- stretch at **phrase** level rather than per word when a word's ratio is extreme
- **`rubberband`** rather than `atempo`, so formants hold — ffmpeg has it
- spread the difference into the **silences** either side of a word before stretching the word
  itself. A pause can absorb 300 ms with no artefact at all; a vowel cannot

**Build this first.** It reuses the socket, costs nothing per line, and within an hour he can hear
whether the smearing matters on *his* voice against *his* picture. If it does, the next path becomes
a justified install rather than a guess.

## PATH B — real speech-to-speech conversion

Candidates, best first for this case:

| | zero-shot | notes |
|---|---|---|
| **seed-vc** | yes, a few seconds | closest to Resolve's behaviour. The one to try first |
| **OpenVoice v2** | yes | tone-colour conversion; strong, well documented |
| **knn-vc** | yes | simplest of the three, surprisingly good |
| **RVC** | **no** — trains per voice | best quality, but minutes of audio and a training step |

**None is on MLX.** They are torch, so on the Mac they run on CPU or MPS rather than the clean GPU
path everything else uses. That is the real cost of Path B, and it is why Path A is first.

# 5. THE FREE COMPUTE QUESTION, ANSWERED

Baba asked whether Streamlit Cloud, Oracle Cloud and Colab can host this. They are three very
different things and only one of them is a serving platform.

## Oracle Cloud Always Free — **YES, and it is the real answer**

    Ampere A1 (ARM):  2 OCPUs and 12 GB RAM across the tenancy, always free, no expiry
    2 AMD micro VMs:  1/8 OCPU, 1 GB each — too small for this
    Public IP, persistent, root, 10 TB egress a month
    NO GPU on the free tier

> Until 11.9.2026 this said "up to 4 OCPUs and 24 GB RAM" and "**24 GB of RAM is a lot**". Oracle
> halved the allowance to 1,500 OCPU hours and 9,000 GB hours a month (2 OCPUs, 12 GB), from 15.6.2026,
> enforced from 18.8.2026. `MAHA_TRANSCRIBE_VM/MIGRATION_PROMPT.md` already knew on 3.9.2026.

**12 GB and two ARM cores** is enough for Whisper and Piper and not for a cloned voice, which the
teacher's record measured at minutes a sentence on four cores. He is already running one:
`teacher-vm`, the machine behind `ttt-lll.pages.dev`.

This is the only one of the three that can be **an API endpoint his phone calls**. That matters:
the Android app cannot reach `127.0.0.1:8837` on the Mac, so anything the phone needs must live
somewhere with an address.

**What to check first:** `nproc`, `free -g`, and whether his tenancy is in a region where A1
capacity is actually available — Oracle frequently answers "out of host capacity" for A1, which is
the single most likely blocker and has nothing to do with his account.

> **Answered 11.9.2026, and capacity was not the blocker.** Frankfurt gave `teacher-vm` its A1 on
> 7.9.2026. The blocker is the allowance: that machine was launched at 4 OCPUs and 24 GB on the day the
> account was made, inside the free trial, and Oracle's own Free Tier page says an Always Free tenancy
> over the allowance has **all** its A1 instances disabled when the trial ends and deleted thirty days
> after. `nproc` and `free -g` could not be run from the session (no key for the machine); they are
> his to run, before about 7.10.2026.

## Google Colab free — **for experiments, not for serving**

    T4 GPU, ~12 hour ceiling, disconnects on idle, no fixed address
    Serving through a tunnel is against the spirit of the terms and gets accounts limited

**Use it to answer questions, not to answer requests.** It is the right place to benchmark seed-vc
against OpenVoice against knn-vc on Baba's own voice and Manan's, and report seconds-per-second and
a listenable wav. That is a day's work that would take a week on ARM CPU.

## Streamlit Community Cloud — **no, and it is not that kind of thing**

    CPU only, ~1 GB RAM, sleeps after inactivity, cold start measured in tens of seconds
    It hosts an app, not an API

It cannot hold a 2 GB model, let alone run one. It is fine as a **control panel** — a page that
shows what the Oracle box is doing — and nothing more.

## NVIDIA — **worth a real look, and he asked specifically**

Two separate things, do not confuse them:

**`build.nvidia.com` (NIM)** — hosted models with free credits, OpenAI-shaped API. Ask it for:
- **Parakeet** ASR. On English it is faster and more accurate than Whisper large, by a wide margin.
  A genuine Whisper replacement for `ears.py`.
- **FastPitch / RAD-TTS / Magpie** TTS, and check whether any exposes a **voice-conversion** or
  speaker-reference endpoint. If one does, Path B may need no local install at all.

**NeMo** — the same models, open source, to run on the Oracle box or in Colab. ARM CPU support is
the thing to verify; NeMo is CUDA-first and ARM is not its happy path.

**What to measure and report back:** free credit size, rate limits, whether a voice reference can be
supplied at all, and latency for one sentence.

> **Answered 11.9.2026 from NVIDIA's public catalogue, all 105 endpoints walked: there is no voice
> conversion.** Magpie TTS Zeroshot takes a reference recording and **text** — the same side of the
> line as MANTRA_VOICE — needs access approval, and the catalogue marks it unavailable. The page's
> "Speech-to-speech" label is on Background Noise Removal and Studio Voice, which are enhancement.
> Speech models are served over Riva's gRPC and do not appear in `/v1/models` at all. **Parakeet
> tdt-0.6b-v3 transcribes 25 languages including Croatian, with word timestamps.** Not measured,
> because the session had no NVIDIA key: credit size, rate limits, latency.
> See `MANTRA_MANIFEST/apis/nvidia.md`.

## The ranking, for serving

    1  Oracle A1          persistent, free, has an address. CPU-only, so small models
    2  NVIDIA build API   free credits, real GPU, someone else's problem to keep up
    3  Colab              experiments and benchmarks only
    4  Streamlit          a control panel, nothing more

# 6. WHAT TO BUILD IN THE APP

The UI is the same whichever engine wins, so none of it is wasted.

- **A file picker** that takes any recording, cuts twelve seconds with ffmpeg, and adds a voice
- **The voice list** beside Speechify and Hume, with local clones marked as **free**
- **Transform this cell**: take the recording in a cell, keep its performance, change the timbre
- **The cell keeps the original**, exactly as it does for generated voices — `gen/<engine>.wav`
  beside `original.wav`, never over it

**Consent belongs in `meta.json` beside `ref.wav`: who, when, and what for.** Baba raised this
himself — *"who give clear permission"*. A cloned voice with no consent note attached is the one
that causes trouble in two years when nobody remembers. Make the field required by the picker.

# 7. HOW TO WORK

- `MANTRA_MANIFEST` first. `keyring.md` §2c–§2i for anything touching a key, and
  `generating-audio.md` for anything touching an engine.
- The gates and Test 1 run on every change: `python3 tests/test_server.py` and
  `python3 scripts/gates.py`. They are green today at 96 and 49.
- **Measure, do not assume.** Every hard-won thing in this repository came from running something
  against a live system and being surprised. The model names in a probe were all retired; the role
  data was in the name and not the tags; AssemblyAI's cheap probe was called impossible until it
  was tried.
- **A local engine needs no key, no credit probe and no spend line.** Do not bolt it onto the key
  ring because the key ring is there.

# 8. THE FIRST THREE QUESTIONS TO ANSWER

Before writing app code, answer these — they change what gets built:

1. **Does his Oracle tenancy actually have A1 capacity?** `nproc`, `free -g`, region.

   *11.9.2026:* it had capacity in Frankfurt; what it lacks is allowance. Resize `teacher-vm` to 2 and
   12, or upgrade the account, before about 7.10.2026. No second free machine exists to be had, and a
   cloned voice will not run usefully on two ARM cores.

2. **Does `build.nvidia.com` expose voice conversion, or only TTS?** If conversion, Path B is an
   API call rather than an install.

   *11.9.2026:* only TTS. **Path B is an install.** Parakeet is worth having for the ears.

3. **On his own voice, how bad is the smearing in Path A?** One line, one friend's reference, his
   own ears. That answer decides whether Path B is needed at all.

   *Open.* It cannot be answered anywhere but his Mac. Path A is built so that it can: record a line
   in a cell, choose the voice, press Transform this take, listen, and read which words the report
   names. The mechanism was measured at 7.5 ms worst edge on a synthetic take; the sound is his to
   judge.
