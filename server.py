#!/usr/bin/env python3
"""
SAMPLE PLAYER — the macOS edition.

A local Flask server and a web interface, run from the terminal. The same idea as the Android
app: a set of cells, each holding one spoken phrase, transcribed and optionally re-voiced.

WHAT IS DELIBERATELY THE SAME AS THE PHONE
  the storage layout, cell for cell, so a project can be copied between them
  WAV 44.1 kHz mono 16-bit, and the original recording is never overwritten
  normalisation to -0.1 dBFS with a 20 dB gain ceiling
  the quality check runs BEFORE normalisation
  one key held for a whole transcription job, and a condemnation retries on the next key
  the User-Agent set in one place, because api.hume.ai answers 403/1010 without one

WHAT IS DIFFERENT, AND WHY
  The browser records. macOS gives a page a microphone through getUserMedia, and the page
  builds the WAV itself at 44.1/mono/16-bit rather than handing over webm/opus — so there is
  no ffmpeg in the dependency list and the bytes that arrive are already the format the rest
  of this reads.

  There is no overlay and no background triangle. That whole mechanism exists because a phone
  can only show one app at a time. A Mac shows the script and this window side by side, and
  the keyboard does what the triangle did.
"""

import base64
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.request

from flask import Flask, jsonify, request, send_from_directory

HOME = os.path.expanduser("~")
APPDIR = os.path.join(HOME, ".sampleplayer-web")
DATA = os.path.join(APPDIR, "data")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT_FILE = os.path.join(APPDIR, "port.txt")
KEYS_FILE = os.path.join(APPDIR, "keys.txt")
DEAD_FILE = os.path.join(APPDIR, "dead.txt")
BASE_PORT = int(os.environ.get("SAMPLEPLAYER_WEB_PORT", "8084"))
HOST = os.environ.get("SAMPLEPLAYER_WEB_HOST", "127.0.0.1")

# THE USER-AGENT, IN ONE PLACE. api.hume.ai sits behind Cloudflare and answers a request with
# none with `403, error code: 1010` — measured across 21 account pairs, all 21 failing without
# one and all 21 succeeding with any string at all. That reads exactly like an entire dead
# account list and has nothing to do with the credentials.
UA = "MantraSamplePlayer/1.0 (macOS)"

RATE = 44_100          # WAV, 44.1 kHz, mono, 16-bit. The same as the phone records at.
TARGET_PEAK = 0.98855  # -0.1 dBFS. Not 0: nothing downstream should have to round in our favour.
MAX_GAIN = 10.0        # 20 dB. Past this a quiet room becomes a convincing wall of hiss.
MIN_SPEECH_MS = 250
MAX_TEXT = 2000

CACHE = os.path.join(APPDIR, "cache")
VOICE_CACHE = os.path.join(CACHE, "audio")
CATALOGUE_TTL = 30 * 24 * 3600   # a month, and there is a button for the impatient


def cache_key(*parts):
    """
    THE SAME REQUEST TWICE COSTS NOTHING THE SECOND TIME.

    Everything an engine can say is a pure function of the voice, the words and the direction: ask
    Hume for Beatrice saying "This is Beatrice" angrily and it will hand back the same performance
    every time. So the answer is filed under a fingerprint of exactly those inputs.

    Auditioning is where this pays. Working down a list of a hundred voices, going back to compare
    the third against the ninth, trying six emotions on one voice and returning to the second — the
    naive version bills every one of those and waits twelve seconds for each. This bills the first
    of each and answers the rest from disk.

    SHA-256 OF THE INPUTS, not of the key: two accounts asking for the same line get the same
    audio, and the file is named after what was asked rather than after who asked.
    """
    import hashlib
    return hashlib.sha256("\u0000".join(str(p) for p in parts).encode()).hexdigest()[:32]


def cached_audio(key):
    p = os.path.join(VOICE_CACHE, key + ".wav")
    if os.path.isfile(p) and os.path.getsize(p) > 44:
        return open(p, "rb").read()
    return None


def put_audio(key, data):
    os.makedirs(VOICE_CACHE, exist_ok=True)
    p = os.path.join(VOICE_CACHE, key + ".wav")
    tmp = p + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, p)


def cache_size():
    n = 0
    total = 0
    for root, _, files in os.walk(CACHE):
        for x in files:
            n += 1
            total += os.path.getsize(os.path.join(root, x))
    return n, total

app = Flask(__name__, static_folder=None)

# THE SERVER DOES NOT NARRATE.
#
# Flask's development server prints a line for every request, and this app asks for state after
# every recording and repaints on every keystroke — so within a minute of use the terminal is a
# column of 200s scrolling past the one thing worth reading, which is the address.
#
# Silenced at ERROR rather than turned off entirely: a crash is exactly the thing that should
# still reach the screen, and it is the only thing left that will.
import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)


# ─────────────────────────────────────────────────────────────────────── paths ──
#
# THE SAME LAYOUT AS THE PHONE, cell for cell, so a project directory can be copied from one
# to the other and simply work.
#
#   projects/<id>/samples/NN/original.wav      the recording. NEVER overwritten
#   projects/<id>/samples/NN/gen/<engine>.wav  a generated voice, beside it
#   projects/<id>/samples/NN/meta.txt          words, voice, in/out points, loop flag
#
# original.wav is protected by the PATH rather than by a convention: generated audio lives one
# directory down, so no engine name and no loop index can make one become the other.

def project_dir(pid):
    return os.path.join(DATA, "projects", pid)


def slot_dir(pid, slot):
    return os.path.join(project_dir(pid), "samples", "%02d" % slot)


def original(pid, slot):
    return os.path.join(slot_dir(pid, slot), "original.wav")


def generated(pid, slot, engine):
    if not engine or "/" in engine or ".." in engine:
        raise ValueError("an engine name that is a path")
    return os.path.join(slot_dir(pid, slot), "gen", "%s.wav" % engine)


def meta_path(pid, slot):
    return os.path.join(slot_dir(pid, slot), "meta.txt")


def read_meta(pid, slot):
    p = meta_path(pid, slot)
    if not os.path.isfile(p):
        return {}
    out = {}
    for line in open(p, encoding="utf-8", errors="replace").read().split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def write_meta(pid, slot, updates):
    m = read_meta(pid, slot)
    m.update(updates)
    os.makedirs(slot_dir(pid, slot), exist_ok=True)
    with open(meta_path(pid, slot), "w", encoding="utf-8") as f:
        f.write("\n".join("%s=%s" % (k, str(v).replace("\n", " ")) for k, v in m.items()))


def playing_file(pid, slot):
    """What this cell actually sounds: the chosen voice, or the recording underneath it."""
    voice = read_meta(pid, slot).get("voice") or ""
    if voice:
        g = generated(pid, slot, voice)
        if os.path.isfile(g):
            return g
    return original(pid, slot)


# ──────────────────────────────────────────────────────────────────────── wav ──
#
# WALK THE CHUNKS. Audio does not begin at byte 44 in anything this app did not write itself:
# Speechify returns RIFF / fmt / LIST / data, so the audio starts at 78, and its data size
# field is 0xFFFFFFFF, a streaming placeholder that taken literally is four gigabytes.

def wav_layout(path):
    """(offset, rate, frames) or (44, RATE, 0) for anything that is not a readable WAV."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return 44, RATE, 0
    if size < 44:
        return 44, RATE, 0
    with open(path, "rb") as f:
        head = f.read(4096)
    if head[0:4] != b"RIFF" or head[8:12] != b"WAVE":
        return 44, RATE, 0
    rate = RATE
    i = 12
    while i + 8 <= len(head):
        cid = head[i:i + 4]
        (csize,) = struct.unpack_from("<I", head, i + 4)
        body = i + 8
        if cid == b"fmt " and body + 8 <= len(head):
            (r,) = struct.unpack_from("<I", head, body + 4)
            if 8000 <= r <= 192000:
                rate = r
        if cid == b"data":
            on_disk = size - body
            usable = on_disk if (csize == 0 or csize > on_disk) else csize
            return body, rate, usable // 2
        if csize == 0:
            break
        i = body + csize + (csize % 2)
    return 44, rate, (size - 44) // 2


def read_samples(path):
    off, rate, frames = wav_layout(path)
    if frames <= 0:
        return [], rate
    with open(path, "rb") as f:
        f.seek(off)
        raw = f.read(frames * 2)
    n = len(raw) // 2
    return list(struct.unpack("<%dh" % n, raw[:n * 2])), rate


def write_wav(path, samples, rate):
    """A temporary file and a rename. This is the one file that cannot be made again."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    data = struct.pack("<%dh" % len(samples), *samples)
    with open(tmp, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(data)))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", len(data)))
        f.write(data)
    os.replace(tmp, path)


def length_ms(path):
    _, rate, frames = wav_layout(path)
    return int(frames * 1000 / rate) if frames else 0


def normalise(samples):
    """
    Peak normalise to -0.1 dBFS, with the gain capped.

    THE CAP IS THE PART THAT WOULD BE A BUG IF LEFT OUT. Dividing by the peak of a nearly
    silent take is a very large number, and without a ceiling a recording of an empty room is
    amplified into a convincing wall of hiss under a healthy-looking waveform.
    """
    if not samples:
        return samples
    peak = max(abs(v) for v in samples)
    if peak == 0:
        return samples
    gain = min(TARGET_PEAK * 32767.0 / peak, MAX_GAIN)
    if gain <= 1.0:
        return samples
    return [max(-32767, min(32767, int(v * gain))) for v in samples]


def assess(samples, rate):
    """Judged BEFORE normalisation, or room tone and a quiet phrase look identical afterwards."""
    if not samples:
        return "silent"
    clipped = sum(1 for v in samples if v >= 32000 or v <= -32000)
    if clipped > len(samples) * 0.10:
        return "clipped"
    peak = max(abs(v) for v in samples)
    if peak < 400:
        return "silent"
    if len(samples) * 1000 // rate < MIN_SPEECH_MS:
        return "too short"
    return "good"


def waveform(samples, buckets):
    if not samples or buckets <= 0:
        return []
    per = max(1, len(samples) // buckets)
    out = []
    for b in range(buckets):
        s = b * per
        e = min(len(samples), s + per)
        if s >= e:
            out.append(0.0)
            continue
        out.append(round(max(abs(v) for v in samples[s:e]) / 32767.0, 4))
    return out


# ─────────────────────────────────────────────────────────────────────── keys ──
#
# THE CANONICAL PARSER, the same shapes as Key_Tester and the Android app. Extract by SHAPE,
# never by whitespace: the note is a working note with account names, dates, the word CANCELLED
# and pasted URLs in it, and a whitespace split has genuinely produced attempts to authenticate
# with the word "cafeteria" and with a Google srsltid tracking token.

SHAPES = [
    ("anthropic", re.compile(r"^sk-ant-[0-9A-Za-z_-]{20,}$")),
    ("gemini", re.compile(r"^(AQ\.[0-9A-Za-z._-]{20,}|AIza[0-9A-Za-z_-]{20,})$")),
    ("groq", re.compile(r"^gsk_[0-9A-Za-z_-]{20,}$")),
    ("github", re.compile(r"^(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[0-9A-Za-z_]{20,})$")),
    ("assemblyai", re.compile(r"^[0-9a-fA-F]{32}$")),
]
SK = re.compile(r"^sk_[0-9A-Za-z_-]{16,}$")
SEP = re.compile(r"[\s,;:\"'=|\[\](){}<>]+")


def classify(token):
    for name, rx in SHAPES:
        if rx.match(token):
            return name
    if SK.match(token):
        # sk_ IS SHARED. Speechify and ElevenLabs both use it and only length separates them.
        return "speechify" if len(token) >= 44 else "elevenlabs"
    return None


def parse_keys(text):
    """Hume pairs first, then single tokens, with the label taken from the line above."""
    lines = text.split("\n")
    found = []
    consumed = set()

    i = 0
    prev = ""
    while i < len(lines):
        t = lines[i].strip()
        if t.lower() == "api key":
            account = prev
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            api = lines[j].strip() if j < len(lines) else ""
            k = j + 1
            while k < len(lines) and lines[k].strip().lower() != "secret key":
                k += 1
            s = k + 1
            while s < len(lines) and not lines[s].strip():
                s += 1
            sec = lines[s].strip() if s < len(lines) else ""
            if api and sec:
                found.append({"provider": "hume", "key": api, "secret": sec, "label": account})
                consumed.add(api)
                consumed.add(sec)
                prev = ""
                i = s + 1
                continue
        if t:
            prev = t
        i += 1

    seen = {f["key"] for f in found}
    for idx, line in enumerate(lines):
        label = ""
        if idx > 0:
            p = lines[idx - 1].strip()
            if p and not any(classify(x.strip(". -_")) for x in SEP.split(p)):
                label = p
        for raw in SEP.split(line):
            tok = raw.strip(". -_")
            if not tok or tok == "DELETED" or tok in seen or tok in consumed:
                continue
            pid = classify(tok)
            if not pid:
                continue
            seen.add(tok)
            found.append({"provider": pid, "key": tok, "secret": None, "label": label})
    return found


def dead_set():
    if not os.path.isfile(DEAD_FILE):
        return set()
    return {l.strip() for l in open(DEAD_FILE) if l.strip()}


def condemn(key):
    """Fingerprints, never keys: a file of dead keys would be a file of keys."""
    import hashlib
    fp = hashlib.sha256(key.encode()).hexdigest()
    with open(DEAD_FILE, "a") as f:
        f.write(fp + "\n")


def ring(provider):
    """Every credential for a provider that is not known dead, in file order."""
    import hashlib
    if not os.path.isfile(KEYS_FILE):
        return []
    dead = dead_set()
    out = []
    for f in parse_keys(open(KEYS_FILE, encoding="utf-8", errors="replace").read()):
        if f["provider"] != provider:
            continue
        if hashlib.sha256(f["key"].encode()).hexdigest() in dead:
            continue
        out.append(f)
    return out


def masked(key):
    return key[:6] + "…" + key[-4:] if len(key) > 12 else "*" * len(key)


# ──────────────────────────────────────────────────────────────────── network ──

def http(method, url, headers=None, body=None, timeout=90):
    """(code, body). Every request in this file goes through here, so the UA cannot be forgotten."""
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return -1, str(e).encode()


def explain(code, body):
    b = (body or b"").decode("utf-8", "replace").lower()
    if code == -1:
        return "no network"
    if code == 403 and ("1010" in b or "cloudflare" in b):
        return "blocked by Cloudflare, not by the key"
    if 200 <= code < 300:
        return "working"
    if code == 401:
        return "refused: wrong, revoked, or the wrong provider for this shape"
    if code == 429:
        return "busy: throttled, and still a good key"
    if code == 400 and any(w in b for w in ("credit", "balance", "quota", "e0300", "insufficient")):
        return "out of credit"
    if code == 400:
        return "the request was wrong, not the key"
    if code == 404:
        return "wrong endpoint for this provider"
    return "HTTP %d" % code


def is_dead_answer(code, body):
    """A 400 carrying credit words is DEATH. A plain 400 blames the request, not the account."""
    b = (body or b"").decode("utf-8", "replace").lower()
    if code == 403 and ("1010" in b or "cloudflare" in b):
        return False
    if code in (401, 402, 403):
        return True
    if code == 400 and any(w in b for w in ("credit", "balance", "quota", "e0300", "insufficient")):
        return True
    return False


# ─────────────────────────────────────────────────────────────── transcription ──

def transcribe(path):
    """
    AssemblyAI, ONE KEY HELD FOR THE WHOLE JOB.

    An upload belongs to the account that made it. Asking a ring for a key on every call
    uploads on account A, submits on account B and receives `403 Cannot access uploaded file`,
    which reads as a dead key — one clip can walk through six good accounts condemning all six.

    THE HEADER IS THE RAW KEY. No `Bearer`. A 401 on a key that looks fine is almost always this.
    """
    for cred in ring("assemblyai"):
        auth = {"authorization": cred["key"]}
        code, body = http("POST", "https://api.assemblyai.com/v2/upload", auth, open(path, "rb").read())
        if code >= 300:
            if is_dead_answer(code, body):
                condemn(cred["key"])
                continue
            return None, explain(code, body)
        url = json.loads(body).get("upload_url")
        code, body = http(
            "POST", "https://api.assemblyai.com/v2/transcript",
            dict(auth, **{"Content-Type": "application/json"}),
            json.dumps({"audio_url": url, "language_code": "en"}).encode(),
        )
        if code >= 300:
            if is_dead_answer(code, body):
                condemn(cred["key"])
                continue
            return None, explain(code, body)
        tid = json.loads(body).get("id")
        waited = 0
        while waited < 90:
            time.sleep(1.5)
            waited += 1.5
            code, body = http("GET", "https://api.assemblyai.com/v2/transcript/%s" % tid, auth)
            if code >= 300:
                return None, explain(code, body)
            d = json.loads(body)
            if d.get("status") == "completed":
                text = (d.get("text") or "").strip()
                return (text, "") if text else (None, "nothing heard")
            if d.get("status") == "error":
                return None, d.get("error") or "transcription failed"
        return None, "timed out"
    return None, "no AssemblyAI key left to try"


# ───────────────────────────────────────────────────────────────────── voices ──

def speechify_catalogue():
    """
    Walked by cursor to the end. `/v1/voices` returns fifty alphabetically and nothing in the
    shape of the reply says it is a page — one call looks like the whole catalogue and is 5%
    of it, all beginning with A.
    """
    creds = ring("speechify")
    if not creds:
        return [], "no Speechify key"
    c = creds[0]
    out, cursor, pages = [], None, 0
    while pages < 20:
        url = "https://api.sws.speechify.com/v1/voices?limit=200"
        if cursor:
            url += "&cursor=" + cursor
        code, body = http("GET", url, {"Authorization": "Bearer " + c["key"]})
        if code >= 300:
            return out, "Speechify: " + explain(code, body)
        d = json.loads(body)
        for v in d.get("voices", []):
            tags = [t.lower() for t in (v.get("tags") or [])]
            out.append({
                "engine": "speechify",
                "id": v.get("id", ""),
                "name": v.get("display_name") or v.get("id", ""),
                # THE MODEL FOLLOWS THE ID. simba-3.2 answers 400 for every voice whose id does
                # not end _32, which is 984 of 992.
                "model": "simba-3.2" if v.get("id", "").endswith("_32") else "simba-english",
                "gender": (v.get("gender") or "").title(),
                "age": next((t.split(":", 1)[1] for t in tags if t.startswith("age:")), ""),
                "language": (v.get("locale") or "").split("-")[0],
                "accent": next((t.split(":", 1)[1] for t in tags if t.startswith("accent:")),
                               v.get("locale") or ""),
                "tags": tags,
                "preview": v.get("preview_audio") or None,
                "flagship": v.get("id", "").endswith("_32"),
            })
        pages += 1
        if not d.get("has_more") or not d.get("next_cursor"):
            break
        cursor = d["next_cursor"]
    return out, ""


def hume_catalogue():
    creds = ring("hume")
    if not creds:
        return [], "no Hume key"
    c = creds[0]
    out, page, total = [], 0, 1
    while page < total and page < 20:
        code, body = http(
            "GET",
            "https://api.hume.ai/v0/tts/voices?provider=HUME_AI&page_size=100&page_number=%d" % page,
            {"X-Hume-Api-Key": c["key"]},
        )
        if code >= 300:
            return out, "Hume: " + explain(code, body)
        d = json.loads(body)
        total = d.get("total_pages", 1)
        for v in d.get("voices_page", []):
            tags = v.get("tags") or {}

            def first(k):
                a = tags.get(k) or []
                return a[0] if a else ""

            flat = []
            for k, vals in tags.items():
                for val in vals:
                    flat.append("%s:%s" % (k.lower(), str(val).lower()))
            out.append({
                "engine": "hume", "id": v.get("id", ""), "name": v.get("name", ""), "model": "",
                "gender": first("GENDER"), "age": first("AGE"),
                "language": first("LANGUAGE"), "accent": first("ACCENT"),
                "tags": flat, "preview": None, "flagship": False,
            })
        page += 1
    return out, ""


def speak(engine, voice_id, model, text, direction=""):
    """
    Speak, WALKING THE RING.

    Three of the twenty-one Hume accounts on this ring answer `400 E0300 zero_credits` and the
    first one is account one. Condemning it and giving up leaves eighteen good accounts
    unreachable behind three dead ones: a condemnation means RETRY THE SAME REQUEST.
    """
    for c in ring(engine):
        if engine == "speechify":
            payload = {
                "input": text, "voice_id": voice_id, "audio_format": "wav",
                "model": model or ("simba-3.2" if voice_id.endswith("_32") else "simba-english"),
            }
            code, body = http(
                "POST", "https://api.sws.speechify.com/v1/audio/speech",
                {"Authorization": "Bearer " + c["key"], "Content-Type": "application/json"},
                json.dumps(payload).encode(),
            )
            field = "audio_data"
        else:
            utt = {"text": text, "voice": {"id": voice_id}}
            if direction.strip():
                # Sent only when there is one: an empty description is not neutral, it is a
                # field asking to be interpreted.
                utt["description"] = direction
            code, body = http(
                "POST", "https://api.hume.ai/v0/tts",
                {"X-Hume-Api-Key": c["key"], "Content-Type": "application/json"},
                json.dumps({"utterances": [utt], "format": {"type": "wav"},
                            "num_generations": 1}).encode(),
            )
            field = "audio"
        if code < 300:
            d = json.loads(body)
            b64 = d.get(field) or (d.get("generations") or [{}])[0].get("audio")
            if not b64:
                return None, "no audio in the reply"
            return base64.b64decode(b64), ""
        if is_dead_answer(code, body):
            condemn(c["key"])
            continue
        if code == 429:
            time.sleep(3)
            continue
        return None, "%s: %s" % (engine, explain(code, body))
    return None, "%s: no account left to try" % engine


def clean_text(raw):
    """
    A file is not a line of dialogue.

    Newlines become SPACES rather than vanishing: a voice reads a line break as nothing at all,
    so a paragraph broken across lines arrives as fragments run together with no space where
    the break was, which sounds like a bad voice rather than a bad import.
    """
    t = raw.lstrip("\ufeff").replace("\u00a0", " ")
    t = re.sub(r"[\r\n\t]+", " ", t)
    t = re.sub(r" {2,}", " ", t).strip()
    if len(t) <= MAX_TEXT:
        return t
    w = t[:MAX_TEXT]
    i = max(w.rfind("."), w.rfind("!"), w.rfind("?"))
    if i > MAX_TEXT // 2:
        return w[:i + 1]
    j = w.rfind(" ")
    return w[:j].strip() if j > MAX_TEXT // 2 else w


# ────────────────────────────────────────────────────────────────────── routes ──

@app.after_request
def no_store(r):
    r.headers["Cache-Control"] = "no-store"
    return r


@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/static/<path:name>")
def static_file(name):
    return send_from_directory(STATIC, name)


@app.route("/api/state")
def state():
    pid = request.args.get("project", "project-01")
    count = int(request.args.get("cells", "30"))
    buckets = int(request.args.get("buckets", "256"))
    cells = []
    for i in range(count):
        f = playing_file(pid, i)
        meta = read_meta(pid, i)
        has_original = os.path.isfile(original(pid, i))
        gen_dir = os.path.join(slot_dir(pid, i), "gen")
        gens = [os.path.splitext(x)[0] for x in os.listdir(gen_dir)] if os.path.isdir(gen_dir) else []
        wf = []
        ms = 0
        if os.path.isfile(f):
            samples, rate = read_samples(f)
            wf = waveform(samples, buckets)
            ms = int(len(samples) * 1000 / rate) if samples else 0
        cells.append({
            "index": i,
            "hasOriginal": has_original,
            "hasAudio": has_original or bool(gens),
            "words": meta.get("words", ""),
            "voice": meta.get("voice") or None,
            "voiceId": meta.get("voiceid") or "",
            "loop": meta.get("loop") == "1",
            "inMs": int(meta.get("in") or 0),
            "outMs": int(meta.get("out") or 0),
            "lengthMs": ms,
            "generated": gens,
            "waveform": wf,
        })
    return jsonify({"project": pid, "cells": cells})


@app.route("/api/record/<int:slot>", methods=["POST"])
def record(slot):
    """
    The browser sends a finished WAV. Judged, then normalised, then promoted.

    ORDER MATTERS BOTH WAYS. The check must see the take as it was recorded, or a
    quiet-but-usable phrase and a recording of an empty room look identical once both have been
    pulled to the same peak. And the file must be written before anything plays it.
    """
    pid = request.args.get("project", "project-01")
    raw = request.get_data()
    pending = os.path.join(slot_dir(pid, slot), "pending.wav")
    os.makedirs(os.path.dirname(pending), exist_ok=True)
    with open(pending, "wb") as f:
        f.write(raw)

    samples, rate = read_samples(pending)
    verdict = assess(samples, rate)
    if verdict != "good":
        # The pending file goes and whatever was in the cell is still there. A retake that goes
        # wrong must not destroy the take it was replacing.
        os.remove(pending)
        return jsonify({"ok": False, "why": verdict})

    write_wav(original(pid, slot), normalise(samples), rate)
    os.remove(pending)
    # A new take invalidates everything derived from the old one.
    gen_dir = os.path.join(slot_dir(pid, slot), "gen")
    if os.path.isdir(gen_dir):
        for x in os.listdir(gen_dir):
            os.remove(os.path.join(gen_dir, x))
    if os.path.isfile(meta_path(pid, slot)):
        os.remove(meta_path(pid, slot))
    return jsonify({"ok": True, "lengthMs": length_ms(original(pid, slot))})


@app.route("/api/audio/<int:slot>")
def audio(slot):
    pid = request.args.get("project", "project-01")
    f = playing_file(pid, slot)
    if not os.path.isfile(f):
        return "", 404
    return send_from_directory(os.path.dirname(f), os.path.basename(f), mimetype="audio/wav")


@app.route("/api/meta/<int:slot>", methods=["POST"])
def set_meta(slot):
    pid = request.args.get("project", "project-01")
    write_meta(pid, slot, request.get_json(force=True) or {})
    return jsonify({"ok": True})


@app.route("/api/delete/<int:slot>", methods=["POST"])
def delete(slot):
    pid = request.args.get("project", "project-01")
    d = slot_dir(pid, slot)
    for root, _, files in os.walk(d):
        for x in files:
            os.remove(os.path.join(root, x))
    return jsonify({"ok": True})


@app.route("/api/transcribe/<int:slot>", methods=["POST"])
def do_transcribe(slot):
    pid = request.args.get("project", "project-01")
    f = original(pid, slot)
    if not os.path.isfile(f):
        return jsonify({"ok": False, "why": "nothing recorded in that cell"})
    text, why = transcribe(f)
    if text is None:
        return jsonify({"ok": False, "why": why})
    write_meta(pid, slot, {"words": text})
    return jsonify({"ok": True, "words": text})


@app.route("/api/voices/<engine>")
def voices(engine):
    """
    THE CATALOGUE IS FETCHED ONCE AND KEPT.

    Speechify's is 992 voices over five cursor pages and Hume's is 160 over two — seven round
    trips and several seconds every time the chooser opens, to receive a list that changes when a
    provider adds a voice, which is a handful of times a year.

    Cached to disk with a month's life on it and a Refresh button beside it, because "rare" is not
    "never" and the person who notices a new voice is missing should not have to wait for a
    timeout to see it.
    """
    fresh = request.args.get("refresh") == "1"
    path = os.path.join(CACHE, "catalogue-%s.json" % engine)
    if not fresh and os.path.isfile(path):
        age = time.time() - os.path.getmtime(path)
        if age < CATALOGUE_TTL:
            d = json.load(open(path, encoding="utf-8"))
            d["cached"] = True
            d["age_days"] = round(age / 86400, 1)
            return jsonify(d)

    items, why = speechify_catalogue() if engine == "speechify" else hume_catalogue()
    payload = {"voices": items, "why": why}
    # A FAILED FETCH IS NOT CACHED. Writing an empty list under a month's TTL would mean one bad
    # minute of network hides the catalogue until October.
    if items:
        os.makedirs(CACHE, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    payload["cached"] = False
    return jsonify(payload)


@app.route("/api/cache")
def cache_state():
    n, total = cache_size()
    out = {"files": n, "bytes": total, "mb": round(total / 1048576.0, 1), "catalogues": {}}
    for e in ("speechify", "hume"):
        p = os.path.join(CACHE, "catalogue-%s.json" % e)
        out["catalogues"][e] = (round((time.time() - os.path.getmtime(p)) / 86400.0, 1)
                                if os.path.isfile(p) else None)
    return jsonify(out)


@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    """Clear the sounds, keep the catalogues. They are the expensive half and the stable half."""
    n = 0
    if os.path.isdir(VOICE_CACHE):
        for x in os.listdir(VOICE_CACHE):
            os.remove(os.path.join(VOICE_CACHE, x))
            n += 1
    return jsonify({"ok": True, "removed": n})


@app.route("/api/speak/<int:slot>", methods=["POST"])
def do_speak(slot):
    pid = request.args.get("project", "project-01")
    body = request.get_json(force=True) or {}
    words = body.get("text") or read_meta(pid, slot).get("words", "")
    if not words.strip():
        return jsonify({"ok": False, "why": "nothing to say — transcribe first"})
    # THE SAME LINE IN THE SAME VOICE IS THE SAME AUDIO. Re-recording a cell clears its generated
    # files, and regenerating the same words afterwards used to bill for them again — which is the
    # commonest thing anybody does while deciding between two voices.
    ck = cache_key("speak", body["engine"], body["voiceId"], body.get("model", ""), words,
                   body.get("direction", ""))
    audio_bytes = cached_audio(ck)
    from_cache = audio_bytes is not None
    if audio_bytes is None:
        audio_bytes, why = speak(body["engine"], body["voiceId"], body.get("model", ""),
                                 words, body.get("direction", ""))
        if audio_bytes is None:
            return jsonify({"ok": False, "why": why})
        put_audio(ck, audio_bytes)
    out = generated(pid, slot, body["engine"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(audio_bytes)
    write_meta(pid, slot, {"voice": body["engine"], "voiceid": body.get("key", "")})
    return jsonify({"ok": True, "cached": from_cache})


@app.route("/api/preview", methods=["POST"])
def preview():
    """A voice says its own name. Short on purpose: ten auditions is ten billed requests."""
    b = request.get_json(force=True) or {}
    line = b.get("line") or ("This is %s." % b.get("name", "this voice"))
    ck = cache_key("preview", b["engine"], b["voiceId"], b.get("model", ""), line,
                   b.get("direction", ""))
    hit = cached_audio(ck)
    if hit is not None:
        return jsonify({"ok": True, "wav": base64.b64encode(hit).decode(), "cached": True})
    audio_bytes, why = speak(b["engine"], b["voiceId"], b.get("model", ""), line,
                             b.get("direction", ""))
    if audio_bytes is None:
        return jsonify({"ok": False, "why": why})
    put_audio(ck, audio_bytes)
    return jsonify({"ok": True, "wav": base64.b64encode(audio_bytes).decode(), "cached": False})


@app.route("/api/text/<int:slot>", methods=["POST"])
def read_text(slot):
    pid = request.args.get("project", "project-01")
    words = clean_text((request.get_json(force=True) or {}).get("text", ""))
    if not words:
        return jsonify({"ok": False, "why": "nothing readable in that file"})
    write_meta(pid, slot, {"words": words})
    return jsonify({"ok": True, "words": words, "chars": len(words)})


@app.route("/api/keys/import", methods=["POST"])
def import_keys():
    """
    ONE FILE IN, EVERY PROVIDER SORTED OUT OF IT.

    The same behaviour as `TTT_MINI/MaKeyImport.importAll`, and for the same reason: both the
    setup and the key manager there used to ask which provider a file was for before reading it,
    which is backwards — the parser already knows which key belongs where.

    THE APP OWNS THE FILE. Baba should not be told to go and create `keys.txt` and get its shape
    right; he picks the note he already has and this writes it. The file is created if it is not
    there, and appended to if it is.

    DUPLICATES ARE DROPPED AND SAID SO. Importing the same note twice changes nothing and reports
    "nothing new" rather than silently appearing to work — which is the failure that looks
    identical to success and sends somebody looking for a bug in the ring instead.

    WHAT IS APPENDED IS THE KEY WITH ITS LABEL, not the whole file. Pasting the file wholesale
    would carry its prose in, and the line above a key is how the parser learns the account name —
    so a second copy of somebody else's heading could rename a key that was already here.
    """
    text = (request.get_json(force=True) or {}).get("text", "")
    if not text.strip():
        return jsonify({"ok": False, "why": "that file is empty"})

    found = parse_keys(text)
    if not found:
        return jsonify({"ok": False, "why": "nothing key-shaped in that file"})

    existing_text = ""
    if os.path.isfile(KEYS_FILE):
        existing_text = open(KEYS_FILE, encoding="utf-8", errors="replace").read()
    have = {f["key"] for f in parse_keys(existing_text)}
    # A Hume secret is not a key in its own right, so it is not in `have` — but importing the
    # same pair twice must not append it twice either.
    have |= {f["secret"] for f in parse_keys(existing_text) if f["secret"]}

    blocks, counts = [], {}
    for f in found:
        if f["key"] in have:
            continue
        have.add(f["key"])
        if f["secret"]:
            have.add(f["secret"])
            blocks.append("%s\nAPI key\n%s\nSecret key\n%s" %
                          (f["label"] or "imported", f["key"], f["secret"]))
        else:
            blocks.append("%s\n%s" % (f["label"] or "imported", f["key"]))
        counts[f["provider"]] = counts.get(f["provider"], 0) + 1

    if not blocks:
        return jsonify({"ok": True, "added": 0,
                        "why": "Nothing new. Every key in that file is already here."})

    # Written through a temporary file and moved. This file holds credentials and a half-written
    # one is a ring with a key cut in half in the middle of it.
    os.makedirs(APPDIR, exist_ok=True)
    tmp = KEYS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(existing_text.rstrip("\n") + "\n\n" if existing_text.strip() else "")
        f.write("\n\n".join(blocks) + "\n")
    os.replace(tmp, KEYS_FILE)

    said = ", ".join("%s +%d" % (k, v) for k, v in sorted(counts.items()))
    return jsonify({"ok": True, "added": sum(counts.values()), "why": "Imported: " + said})


@app.route("/api/keys")
def keys():
    if not os.path.isfile(KEYS_FILE):
        return jsonify({"keys": [], "file": KEYS_FILE})
    dead = dead_set()
    import hashlib
    rows = []
    for f in parse_keys(open(KEYS_FILE, encoding="utf-8", errors="replace").read()):
        rows.append({
            "provider": f["provider"],
            "label": f["label"],
            "masked": masked(f["key"]),
            "paired": bool(f["secret"]),
            "dead": hashlib.sha256(f["key"].encode()).hexdigest() in dead,
        })
    return jsonify({"keys": rows, "file": KEYS_FILE})


def _pick_port(host, start, span=40):
    """
    The first free port at or above the base one.

    Marko runs several of these servers at once, so a fixed port means one of them silently
    loses. Bind upward and write the winner where the launcher can read it.
    """
    probe = host if host not in ("0.0.0.0", "") else ""
    for p in range(start, start + span):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((probe, p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return start


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    port = _pick_port(HOST, BASE_PORT)
    with open(PORT_FILE, "w") as f:
        f.write(str(port))
    print("sample player on http://127.0.0.1:%d" % port, file=sys.stderr)
    # The banner is the launcher's job. Two panels saying the same thing, one of them wrapped in
    # asterisks warning about a development server, is one panel too many.
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None
    app.run(host=HOST, port=port, threaded=True, debug=False)
