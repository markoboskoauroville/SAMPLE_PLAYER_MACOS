#!/usr/bin/env python3
"""
SAMPLE PLAYER — the macOS edition. A local Flask server and a page, the same cells as the phone.
What is the same as the phone and what is different, and why: DEVELOPMENT.md, Part One.
"""

import base64
import json
import math
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
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

# THE VERSION THIS FILE IS. Bumped by hand in the same edit that bumps the installer, and checked
# against it by G1 — two numbers that must agree is a lie waiting to happen, so the gate compares
# them rather than trusting anybody to remember.
EDITION = "v3.3"

RAW = "https://raw.githubusercontent.com/markoboskoauroville/SAMPLE_PLAYER_MACOS/main"

SPEND_FILE = os.path.join(APPDIR, "spend.jsonl")
RATES_FILE = os.path.join(APPDIR, "rates.json")

# WHAT EACH PROVIDER IS BILLED IN, and it is a different unit for each one, so a single number
# would be three numbers added together wrongly.
#
#   Speechify bills CHARACTERS, and every synthesis reply carries `billable_characters_count`.
#   Hume bills by the SECOND, and every generation carries its own `duration`.
#   AssemblyAI bills by the audio HOUR, and a finished transcript carries `audio_duration`.
#
# All three are facts the provider states about the call that was just made. None of them is an
# estimate, which is the whole reason the log is worth keeping.
UNITS = {"speechify": "characters", "hume": "characters", "assemblyai": "seconds of audio"}

# THE RATES DEFAULT TO ZERO AND ARE ASKED FOR RATHER THAN GUESSED.
#
# I do not know what Baba pays. Published API prices change, they differ per plan, and several of
# these accounts are on terms I cannot see from here — so a number invented here would appear on
# screen looking exactly as authoritative as the character count beside it, which IS measured.
#
# Units are logged always. Money appears only once a rate has been entered, and until then the box
# shows what was actually consumed, which is the honest half.
DEFAULT_RATES = {"speechify": 0.0, "hume": 0.0, "assemblyai": 0.0}


def rates():
    if os.path.isfile(RATES_FILE):
        try:
            return dict(DEFAULT_RATES, **json.load(open(RATES_FILE, encoding="utf-8")))
        except Exception:
            pass
    return dict(DEFAULT_RATES)


def log_spend(provider, units, detail):
    """
    One line per billable call, appended and never rewritten.

    JSON LINES RATHER THAN A DATABASE OR ONE BIG ARRAY. An append cannot corrupt what is already
    there, a half-written last line is one lost call rather than a lost file, and the whole thing
    can be read in a text editor when something looks wrong — which is the only reason to keep a
    log at all.

    NO KEY, NO ACCOUNT NAME, NOT EVEN A FINGERPRINT. What was spent is a fact about the work; which
    of twenty-one accounts paid for it is not something this file needs to hold, and a log that
    grows for months is exactly the file not to put credentials near.
    """
    if not units:
        return
    os.makedirs(APPDIR, exist_ok=True)
    row = {"at": int(time.time()), "provider": provider,
           "units": round(float(units), 3), "detail": detail[:80]}
    with open(SPEND_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def spend_rows():
    if not os.path.isfile(SPEND_FILE):
        return []
    out = []
    for line in open(SPEND_FILE, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            # A torn last line is skipped rather than taking the file down with it.
            continue
    return out


def spend_totals():
    """
    THE TOTAL IS DERIVED FROM THE LOG AND NEVER STORED BESIDE IT.

    A running total kept as its own number is a number that can disagree with the log, and the day
    it does there is no way to tell which one is lying. Clearing the log therefore empties the box
    by arithmetic rather than by a second thing having to be remembered.
    """
    r = rates()
    per = {}
    for row in spend_rows():
        p = row.get("provider", "?")
        d = per.setdefault(p, {"calls": 0, "units": 0.0, "unit": UNITS.get(p, "units")})
        d["calls"] += 1
        d["units"] += float(row.get("units") or 0)
    money = 0.0
    for p, d in per.items():
        d["units"] = round(d["units"], 2)
        d["rate"] = r.get(p, 0.0)
        d["cost"] = round(d["units"] * d["rate"], 4)
        money += d["cost"]
    return per, round(money, 4)


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


def generated_voices(gen_dir):
    """
    ONLY .wav FILES ARE VOICES. The state used to list every file in gen/, and on a Mac the first
    time that folder is opened in Finder a .DS_Store appears in it: a cell with no audio then
    reported a generated voice called ".DS_Store" and counted as full. A half-written .tmp did the
    same for the length of a write.
    """
    if not os.path.isdir(gen_dir):
        return []
    return [os.path.splitext(x)[0] for x in sorted(os.listdir(gen_dir))
            if x.endswith(".wav") and not x.startswith(".")]


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
    """A temporary file OF ITS OWN and a rename. This is the one file that cannot be made again, and
    two writers at once (one cell transformed from two tabs) must each finish a whole file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=os.path.dirname(path))
    os.chmod(tmp, 0o644)
    data = struct.pack("<%dh" % len(samples), *samples)
    with os.fdopen(fd, "wb") as f:
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
                log_spend("assemblyai", d.get("audio_duration") or 0,
                          os.path.basename(path))
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
            # SPEECHIFY HAS NO DIRECTION FIELD, so the tags are stripped rather than read
            # aloud. Sending them would have a voice pronounce "less-than excited greater-than" in
            # the middle of a sentence, which is the worst of the three possible behaviours.
            payload = {
                "input": strip_tags(text), "voice_id": voice_id, "audio_format": "wav",
                "model": model or ("simba-3.2" if voice_id.endswith("_32") else "simba-english"),
            }
            code, body = http(
                "POST", "https://api.sws.speechify.com/v1/audio/speech",
                {"Authorization": "Bearer " + c["key"], "Content-Type": "application/json"},
                json.dumps(payload).encode(),
            )
            field = "audio_data"
        else:
            # ONE REQUEST, SEVERAL UTTERANCES. Hume takes a list and joins them itself, each with
            # its own description — so a line that turns from calm to furious halfway is one call
            # and one seamless piece of audio, not two files stitched together with a click in the
            # middle. This is the whole reason the tags are worth having.
            pieces = segment(text)
            utts = []
            for spoken, d in pieces:
                u = {"text": spoken, "voice": {"id": voice_id}}
                # Sent only when there is one: an empty description is not neutral, it is a field
                # asking to be interpreted.
                d = (d or direction).strip()
                if d:
                    u["description"] = d
                utts.append(u)
            code, body = http(
                "POST", "https://api.hume.ai/v0/tts",
                {"X-Hume-Api-Key": c["key"], "Content-Type": "application/json"},
                json.dumps({"utterances": utts, "format": {"type": "wav"},
                            "num_generations": 1}).encode(),
            )
            field = "audio"
        if code < 300:
            d = json.loads(body)
            b64 = d.get(field) or (d.get("generations") or [{}])[0].get("audio")
            if not b64:
                return None, "no audio in the reply"
            # WHAT THE PROVIDER SAYS IT BILLED, not what we think it should have. Speechify counts
            # the characters it actually charged for; Hume states the duration it produced.
            if engine == "speechify":
                log_spend("speechify", d.get("billable_characters_count") or len(text),
                          text[:60])
            else:
                # CHARACTERS, NOT SECONDS. Hume bills by the character — its pricing page is in
                # dollars per thousand characters — and the duration it returns is a fact about the
                # audio rather than about the invoice. Logging seconds gave a number that was
                # accurate and measured the wrong thing, which is the worst kind of wrong for a
                # figure somebody is going to budget against.
                log_spend("hume", len(text), text[:60])
            return base64.b64decode(b64), ""
        if is_dead_answer(code, body):
            condemn(c["key"])
            continue
        if code == 429:
            time.sleep(3)
            continue
        return None, "%s: %s" % (engine, explain(code, body))
    return None, "%s: no account left to try" % engine


EMOTIONS_FILE = os.path.join(APPDIR, "emotions.json")

# The ones that ship. Custom ones are added beside them and both are offered everywhere, because
# an emotion belongs to the DIRECTION and not to the actor: a note that only works on one voice is
# a note nobody can reuse.
BUILT_IN_EMOTIONS = [
    {"label": "neutral", "glyph": "—", "text": "even and unhurried, no particular emotion"},
    {"label": "happy", "glyph": "☀", "text": "genuinely happy, light and quick"},
    {"label": "excited", "glyph": "⚡", "text": "excited, can hardly get the words out fast enough"},
    {"label": "kind", "glyph": "♡", "text": "gentle and kind, unhurried"},
    {"label": "tender", "glyph": "◡", "text": "tender and low, almost private"},
    {"label": "sad", "glyph": "▽", "text": "sad and quiet, slowing at the ends of phrases"},
    {"label": "grieving", "glyph": "☂", "text": "grieving, barely holding the voice together"},
    {"label": "weary", "glyph": "…", "text": "weary, worn out, no energy left for emphasis"},
    {"label": "angry", "glyph": "✖", "text": "angry, clipped and hard on the consonants"},
    {"label": "furious", "glyph": "‼", "text": "furious, barely holding it together"},
    {"label": "firm", "glyph": "▮", "text": "firm and final, leaving no room to argue"},
    {"label": "sarcastic", "glyph": "¬", "text": "dry and sarcastic, meaning the opposite"},
    {"label": "anxious", "glyph": "◌", "text": "anxious, breath high and shallow"},
    {"label": "afraid", "glyph": "△", "text": "afraid, voice unsteady"},
    {"label": "urgent", "glyph": "!", "text": "urgent, needs to be understood immediately"},
    {"label": "whispered", "glyph": "◦", "text": "whispered, as if someone might hear"},
    {"label": "calm", "glyph": "○", "text": "calm and slow, plenty of space between phrases"},
    {"label": "meditative", "glyph": "◎", "text": "meditative, soft, guiding a breath"},
    {"label": "announcer", "glyph": "◉", "text": "confident announcer, projecting to a room"},
    {"label": "documentary", "glyph": "▦", "text": "measured documentary narration, authoritative"},
    {"label": "teaching", "glyph": "✎", "text": "explaining patiently to someone learning"},
    {"label": "storytelling", "glyph": "❦", "text": "telling a story to a child, colours in the voice"},
]

TAG = re.compile(r"<([A-Za-z0-9 _'-]{1,40})>")


def custom_emotions():
    if not os.path.isfile(EMOTIONS_FILE):
        return []
    try:
        return json.load(open(EMOTIONS_FILE, encoding="utf-8"))
    except Exception:
        # A corrupt file is not a reason to lose the built-ins. It is renamed rather than deleted,
        # because it is the only copy of whatever was written into it.
        os.replace(EMOTIONS_FILE, EMOTIONS_FILE + ".broken")
        return []


def all_emotions():
    """Built-in first, then custom, with a custom label winning if it shadows a built-in one."""
    out = {e["label"].lower(): dict(e, custom=False) for e in BUILT_IN_EMOTIONS}
    for e in custom_emotions():
        if e.get("label") and e.get("text"):
            out[e["label"].lower()] = dict(e, custom=True)
    return list(out.values())


def segment(text):
    """
    SPLIT A LINE INTO PIECES, EACH WITH THE DIRECTION IN FORCE WHEN IT STARTS.

    A tag is written inline: `<excited> this half <weary> and this half`. Everything after a tag is
    read that way until the next tag, so one line can turn on a word — which is the thing a single
    direction for a whole utterance cannot do, and the thing an actor is actually for.

    Returns [(spoken text, direction or "")]. Text before any tag has no direction rather than the
    first one: a line that begins plainly and turns angry halfway is common, and inheriting
    backwards would make it angry from the start.

    An unknown tag is left in the text rather than swallowed. It is more likely a misspelling than
    an instruction, and a voice reading "less-than excited greater-than" aloud is a bug somebody
    can SEE, where silently dropping it is a bug they cannot.
    """
    known = {e["label"].lower(): e["text"] for e in all_emotions()}
    out = []
    pos = 0
    current = ""
    for m in TAG.finditer(text):
        label = m.group(1).strip().lower()
        if label not in known:
            continue
        chunk = text[pos:m.start()].strip()
        if chunk:
            out.append((chunk, current))
        current = known[label]
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        out.append((tail, current))
    return out or [(text.strip(), "")]


def strip_tags(text):
    """The line as it will be SPOKEN, with the known tags removed. Used by Speechify, which has
    no direction field at all, and by the cache key so a re-tagged line is a different sound."""
    known = {e["label"].lower() for e in all_emotions()}
    return " ".join(TAG.sub(lambda m: "" if m.group(1).strip().lower() in known else m.group(0),
                            text).split())


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
        gens = generated_voices(gen_dir)
        wf = []
        ms = 0
        rate = RATE
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
            # Reported rather than assumed: a recording is 44.1 and an engine returns whatever it
            # returns, and the cell page says which so nobody has to open the file to find out.
            "rate": rate,
            "generated": gens,
            "transform": ({"engine": engine_for(meta["transform_voice"]), "voice": meta["transform_voice"], "usage": meta.get("transform_usage") or "none",
                           "report": meta.get("transform_report", "")} if meta.get("transform_voice") else None),
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


def slugify(text, fallback):
    """
    A FILENAME OUT OF WHAT WAS SAID.

    The line is the only name that means anything: a folder of cell-01.wav through cell-30.wav is
    thirty files nobody can tell apart in an edit, and the whole reason to download one is to drop
    it on a timeline next to a picture.

    What is stripped is what a filesystem or an edit suite will argue with — slashes, colons,
    quotes, leading dots — and nothing else. Spaces are kept as spaces rather than turned into
    underscores: this is going into Premiere and DaVinci, not into a URL, and a name that reads as
    a sentence is the point.

    Eighty characters, cut at a word. macOS allows 255 bytes and every one of them fits in a bin
    that is already too wide to read at a glance.
    """
    t = " ".join((text or "").split())
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", t)
    t = t.strip(" .")
    if not t:
        return fallback
    if len(t) > 80:
        cut = t[:80]
        space = cut.rfind(" ")
        t = cut[:space] if space > 40 else cut
    return t


@app.route("/api/render", methods=["POST"])
def render():
    """
    SPEAK A LINE AND HAND IT BACK AS A FILE, without touching any cell.

    The download button under a text box is not the same thing as the one on the cell. That one
    hands over what the cell already holds; this one is for a line that may never become a cell at
    all — a title read six ways to hear which lands, a name for a client, one word for a transition.

    THROUGH THE SAME CACHE AS EVERYTHING ELSE, so pressing download after hearing it costs nothing:
    the audition already paid for those bytes and they are on disk under the voice, the words and
    the tags. Downloading a line twice is free, and downloading one you have never heard costs
    exactly one call.

    The name is the line itself with the voice after it, because three versions of one sentence in
    three voices in a downloads folder are otherwise three files called the same thing.
    """
    b = request.get_json(force=True) or {}
    line = (b.get("text") or "").strip()
    if not line:
        return jsonify({"ok": False, "why": "nothing to render"}), 400

    ck = cache_key("speak", b["engine"], b["voiceId"], b.get("model", ""), line,
                   b.get("direction", ""))
    data = cached_audio(ck)
    from_cache = data is not None
    if data is None:
        data, why = speak(b["engine"], b["voiceId"], b.get("model", ""), line,
                          b.get("direction", ""))
        if data is None:
            return jsonify({"ok": False, "why": why}), 502
        put_audio(ck, data)

    name = slugify(strip_tags(line), "line")
    voice = slugify(b.get("name", ""), "")
    # A HYPHEN AND NOT AN EM DASH. Two header forms are sent: filename* carries UTF-8 and every
    # current browser prefers it, but the plain filename= fallback is ASCII, and an em dash comes
    # out of it as a question mark — so the one character that is always ours to choose should not
    # be the one that breaks. Croatian in the line itself survives through filename*; the
    # separator survives through both.
    filename = (name + (" - " + voice if voice else "") + ".wav")

    from flask import Response
    return Response(data, mimetype="audio/wav", headers={
        # RFC 5987 as well as the plain form: the line is very often not ASCII — Croatian is the
        # first language this app ever recorded — and a bare filename= drops every accented
        # character or, on some browsers, the whole name.
        "Content-Disposition": "attachment; filename=\"%s\"; filename*=UTF-8''%s"
                               % (filename.encode("ascii", "replace").decode(),
                                  __import__("urllib.parse", fromlist=["quote"]).quote(filename)),
        "X-From-Cache": "1" if from_cache else "0",
    })


@app.route("/api/download/<int:slot>")
def download(slot):
    """
    THE EXACT FILE THIS CELL PLAYS, uncompressed, under the name of what it says.

    Not a re-encode and not a copy: the bytes on disk, which are 16-bit PCM in a WAV from end to
    end. The browser records raw samples and writes the header itself at 44.1 kHz mono; both
    engines are asked for `wav` rather than mp3. Nothing in this app has been through a lossy
    codec, so there is nothing here to undo.
    """
    pid = request.args.get("project", "project-01")
    f = playing_file(pid, slot)
    if not os.path.isfile(f):
        return "", 404
    meta = read_meta(pid, slot)
    name = slugify(meta.get("words", ""), "cell-%02d" % (slot + 1)) + release_suffix(meta, f) + ".wav"
    return send_from_directory(
        os.path.dirname(f), os.path.basename(f),
        mimetype="audio/wav", as_attachment=True, download_name=name,
    )


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


@app.route("/api/version")
def version():
    """
    WHAT IS INSTALLED, AND WHAT IS PUBLISHED.

    Asked for rather than assumed: the answer comes from the installer at the head of the
    repository, which is the same file `u` would run, so the two can never disagree about what
    "newest" means.

    IT REPORTS AND DOES NOT ACT. A page that updates itself would be a page that restarts the
    server underneath the person reading it. Updating is `u` in the terminal panel, where the
    process that has to be replaced is the one being looked at.
    """
    code, body = http("GET", RAW + "/3sh_i_sample_player_v1_macos.sh", {}, None, timeout=20)
    if code != 200:
        return jsonify({"installed": EDITION, "latest": None,
                        "why": "could not reach GitHub: " + explain(code, body)})
    m = re.search(r"edition: (v[\d.]+)", body.decode("utf-8", "replace"))
    latest = m.group(1) if m else None

    def parts(v):
        return [int(x) for x in re.findall(r"\d+", v or "")]

    behind = bool(latest) and parts(latest) > parts(EDITION)
    return jsonify({
        "installed": EDITION,
        "latest": latest,
        "behind": behind,
        "why": "" if latest else "the published installer has no edition line",
    })


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

    # TRANSCRIPTION IS NOT A STEP, IT HAPPENS ON THE WAY.
    #
    # THIS WAS DROPPED IN THE PORT AND IT IS THE POINT OF THE WHOLE FEATURE. Nobody wants a
    # transcript; they want a different voice, and the transcript is what the app needs in order
    # to give them one. The phone edition has never asked for it — v6 built it exactly this way
    # and v11 kept it when Transcribe became an action of its own.
    #
    # Telling somebody "transcribe first" is the app knowing what has to happen next and refusing
    # to do it.
    if not words.strip():
        wav = original(pid, slot)
        if not os.path.isfile(wav):
            return jsonify({"ok": False, "why": "nothing recorded in that cell"})
        text, why = transcribe(wav)
        if text is None:
            return jsonify({"ok": False, "why": "could not transcribe it: " + why})
        write_meta(pid, slot, {"words": text})
        words = text
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


# ────────────────────────────────────────────────────────────── voice transform ──
#
# PATH A: HIS PERFORMANCE, THEIR TIMBRE. MANTRA_VOICE clones by text-to-speech and has never heard
# the take, so his words are heard with their times, the clone says them, both sets of edges are
# snapped to the sound, and each of their words is stretched onto his word's window. The five steps
# and the honest limit (smear past 1.3x, chirp under 0.75x) are in DEVELOPMENT.md, "Path A".
# A LOCAL ENGINE HAS NO KEY, NO CREDIT PROBE AND NO SPEND LINE, and none is bolted on here.

VOICE_API = os.environ.get("MANTRA_VOICE_URL", "http://127.0.0.1:8837")
SMEAR = 1.30      # longer than this and a held vowel audibly smears
CHIRP = 0.75      # shorter than this and it chirps
ABSORB = 0.30     # a pause can take 300 ms with no artefact at all; a vowel cannot
EARLY = 0.05      # how far a word may start before his onset. Lips open first; sound may not.
JOIN_GAP = 0.08   # words closer than this in his take are one breath and can be one phrase
PAD = 0.05        # context either side of a segment given to rubberband, then cut away
FADE = 0.005      # 5 ms at each join, so a cut never clicks
FRAME = 0.010     # 10 ms analysis frames for snapping edges
USAGES = ("public", "private")


def ffmpeg_path():
    """ffmpeg is not a dependency of this app. It is a dependency of MANTRA_VOICE, which this engine
    needs anyway, and a launcher started from ~/.local/bin does not always carry Homebrew's PATH."""
    for p in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if p and os.path.isfile(p):
            return p
    return None


def _clean_spans(spans, total):
    """
    WHISPER'S TIMES ARE NOT WELL-FORMED. A word can end before it starts, two words can overlap,
    and the last word can end after the clip does. Clamp into the clip, force a minimum length and
    make every span start where the one before it ended at the earliest.
    """
    out = []
    floor = 0.0
    for t0, t1 in spans:
        t0 = min(max(float(t0), floor, 0.0), total)
        t1 = min(max(float(t1), t0 + 0.02), total)
        if t1 - t0 < 0.02:            # squeezed against the end of the clip
            t0 = max(floor, t1 - 0.02)
        out.append((t0, t1))
        floor = t1
    return out


def plan_stretch(his, theirs, his_total, their_total):
    """
    Every one of THEIR words laid onto HIS word's window.

    his, theirs   lists of (start, end) in seconds, one per word, the same length and order
    returns       [{words:[i..], src:(u0,u1), dst:(t0,t1), ratio, level, verdict}]

    ratio is destination over source: 2.0 means their word is played at half speed.

    The order of what is tried is the order of what it costs:
      1  nothing, when the ratio is already clean
      2  the silence beside the word: a long word of his leaves its tail silent, a short one
         borrows the pause after it (and at most 50 ms before, because an early sound against a
         mouth that has not opened is the lip sync error the eye catches first)
      3  a phrase: the word joined to the words he ran on into after it, stretched as one
      4  nothing more — and the verdict SAYS smear or chirp rather than claiming ok
    """
    n = min(len(his), len(theirs))
    if n == 0:
        return []
    his = _clean_spans(his[:n], his_total)
    theirs = _clean_spans(theirs[:n], their_total)

    def verdict(ratio):
        # A MILLIONTH OF TOLERANCE. A word borrowed or absorbed exactly to a limit lands a hair either
        # side of it in floating point, and was reported as a chirp it had just been rescued from.
        return "smear" if ratio > SMEAR + 1e-6 else "chirp" if ratio < CHIRP - 1e-6 else "ok"

    def absorb(t0, t1, u0, u1, floor, ceiling):
        """The window after the silence either side has been given the chance to help."""
        src = u1 - u0
        dst = t1 - t0
        if dst / src > SMEAR:
            cut = min(ABSORB, dst - src * SMEAR)
            t1 -= cut
        elif dst / src < CHIRP:
            need = src * CHIRP - dst
            after = min(need, ABSORB, max(0.0, ceiling - t1))
            t1 += after
            before = min(need - after, ABSORB - after, EARLY, max(0.0, t0 - floor))
            t0 -= before
        return t0, t1

    segs = []
    i = 0
    floor = 0.0
    while i < n:                                     # bounded: i advances by at least one a pass
        # 3 — THE PHRASE. Words before i are already laid, so a phrase only grows to the right. It
        # grows while the group is extreme and joining helps, or while the group is clean and the
        # NEXT word is extreme and the two together come out clean — the clean word lends it room.
        # Compared in log ratio, so 2x and 0.5x are equally far from clean.
        lo = hi = i

        def ratio(a, b):
            return (his[b][1] - his[a][0]) / (theirs[b][1] - theirs[a][0])

        for _ in range(n):                           # bounded by the number of words
            if hi + 1 >= n or his[hi + 1][0] - his[hi][1] >= JOIN_GAP:
                break
            r, joined, alone = ratio(lo, hi), ratio(lo, hi + 1), ratio(hi + 1, hi + 1)
            if verdict(r) == "ok":
                if verdict(alone) == "ok" or verdict(joined) != "ok":
                    break
            elif abs(math.log(joined)) >= abs(math.log(r)):
                break
            hi += 1
        t0, t1 = his[lo][0], his[hi][1]
        u0, u1 = theirs[lo][0], theirs[hi][1]
        ceiling = his[hi + 1][0] if hi + 1 < n else his_total
        t0, t1 = absorb(t0, t1, u0, u1, floor, ceiling)
        ratio = (t1 - t0) / (u1 - u0)
        segs.append({"words": list(range(lo, hi + 1)), "src": (round(u0, 4), round(u1, 4)),
                     "dst": (round(t0, 4), round(t1, 4)), "ratio": round(ratio, 3),
                     "level": "phrase" if hi > lo else "word", "verdict": verdict(ratio)})
        floor = t1
        i = hi + 1
    return segs


def snap_spans(samples, rate, spans):
    """
    WORD EDGES MOVED ONTO THE SOUND.

    Whisper places a word boundary from attention, not from the waveform, and it is commonly
    30-80 ms out — which is most of the lip sync budget before a single sample has been stretched.
    Each edge looks 50 ms either way in 10 ms frames: a start moves to the first loud frame after
    a quiet one, an end to the last loud frame before a quiet one. Where speech runs straight
    through (no quiet frame in reach) the quietest frame is taken. Where nothing is loud the edge
    stays put: stretching a little silence is harmless, and cutting a consonant is not.
    """
    if not samples or not spans:
        return list(spans)
    hop = max(1, int(rate * FRAME))
    rms = []
    for k in range(0, len(samples), hop):
        chunk = samples[k:k + hop]
        rms.append((sum(x * x for x in chunk) / len(chunk)) ** 0.5)
    ordered = sorted(rms)
    quiet = max(ordered[len(ordered) // 5] * 3.0, ordered[-1] * 0.03, 1.0)
    loud = [v > quiet for v in rms]
    total = len(samples) / rate
    w = int(round(0.05 / FRAME))
    out = []
    floor = 0
    for idx, (t0, t1) in enumerate(spans):
        nxt = spans[idx + 1][0] if idx + 1 < len(spans) else total
        f0, f1 = int(round(t0 / FRAME)), int(round(t1 / FRAME))
        new0, new1 = t0, t1                          # an edge that is not moved keeps its exact value
        a, b = max(floor, f0 - w), min(len(rms) - 1, f0 + w, max(f0, f1 - 1))
        if a <= b and any(loud[a:b + 1]):
            first = next(k for k in range(a, b + 1) if loud[k])
            if first > a or (a > 0 and not loud[a - 1]):
                f0 = first
            else:
                f0 = min(range(a, b + 1), key=lambda k: rms[k])
            new0 = f0 * FRAME
        c, d = max(f0 + 1, f1 - w), min(len(rms) - 1, f1 + w, int(round(nxt / FRAME)))
        if c <= d and any(loud[c:d + 1]):
            last = max(k for k in range(c, d + 1) if loud[k])
            if last < d or (d + 1 < len(rms) and not loud[d + 1]):
                f1 = last + 1
            else:
                f1 = min(range(c, d + 1), key=lambda k: rms[k])
            new1 = f1 * FRAME
        if new1 <= new0:
            new1 = new0 + FRAME
        out.append((new0, min(new1, total)))
        floor = int(round(new1 / FRAME))
    return out


def stretch_filter(tempo, have_rubberband):
    """
    rubberband keeps the formants where atempo does not, which is the difference between a voice
    and a voice played slowly. atempo is the fallback, and its floor of 0.5 is chained around.
    """
    if have_rubberband:
        return "rubberband=tempo=%.6f:pitchq=quality:formant=preserved" % tempo
    parts = []
    t = tempo
    for _ in range(8):                                # bounded: 0.5^8 is far past any real ratio
        if t >= 0.5:
            break
        parts.append("atempo=0.5")
        t /= 0.5
    parts.append("atempo=%.6f" % min(t, 100.0))
    return ",".join(parts)


def has_rubberband(ff):
    try:
        r = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20)
        return " rubberband " in r.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def render_plan(ff, their_wav, their_total, segs, frames, rate):
    """
    A silent track exactly as long as his take, and every segment laid onto it at his time.

    Each segment is cut with PAD of context either side, stretched, and the middle taken back out,
    so rubberband's start-up and tail land in the part that is thrown away rather than on the
    first consonant. Then 5 ms fades at both ends. Returns (samples, filter name, why).
    """
    rb = has_rubberband(ff)
    track = [0] * frames
    for seg in segs:
        u0, u1 = seg["src"]
        t0, t1 = seg["dst"]
        s0, s1 = max(0.0, u0 - PAD), min(their_total, u1 + PAD)
        tempo = (u1 - u0) / (t1 - t0)
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-ss", "%.4f" % s0, "-t", "%.4f" % (s1 - s0),
               "-i", their_wav, "-af", stretch_filter(tempo, rb) + ",aresample=%d" % rate,
               "-ac", "1", "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            return None, "", "ffmpeg did not run: %s" % str(e)[:120]
        if r.returncode != 0:
            return None, "", "ffmpeg refused a segment: %s" % r.stderr.decode("utf-8", "replace")[-160:]
        got = list(struct.unpack("<%dh" % (len(r.stdout) // 2), r.stdout[:len(r.stdout) // 2 * 2]))
        lead = int(round((u0 - s0) / tempo * rate))
        want = int(round((t1 - t0) * rate))
        piece = got[lead:lead + want]
        piece += [0] * (want - len(piece))
        fade = min(int(FADE * rate), want // 2)
        for k in range(fade):
            g = k / fade
            piece[k] = int(piece[k] * g)
            piece[want - 1 - k] = int(piece[want - 1 - k] * g)
        at = int(round(t0 * rate))
        for k, v in enumerate(piece):
            j = at + k
            if 0 <= j < frames:
                track[j] = max(-32768, min(32767, track[j] + v))
    return track, ("rubberband" if rb else "atempo"), ""


def voice_api(method, path, body=None, ctype="application/json", timeout=90):
    """(json or None, why). MANTRA_VOICE's own words when it has them, a sentence when it does not."""
    code, raw = http(method, VOICE_API + path, {"Content-Type": ctype} if body is not None else None,
                     body, timeout)
    if code == -1:
        return None, ("MANTRA_VOICE is not answering at %s. Start it from the star menu's Voices "
                      "switch, or: python3 ~/Developer/MANTRA_VOICE/voiced.py" % VOICE_API)
    try:
        j = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        # A 404 PAGE IS AN OLDER MANTRA_VOICE. Flask answers a route it does not have with HTML, and
        # /consent did not exist before 11.9.2026. Said as what to do.
        if code == 404:
            return None, ("MANTRA_VOICE is older than this app and does not have %s. Update it: "
                          "cd ~/Developer/MANTRA_VOICE && git pull, then switch Voices off and on in the star menu"
                          % path.split("?")[0])
        return None, "MANTRA_VOICE answered HTTP %d with something that is not JSON" % code
    if code != 200 or (isinstance(j, dict) and j.get("error")):
        said = (j.get("error") if isinstance(j, dict) else "") or "HTTP %d" % code
        return None, "MANTRA_VOICE: %s" % re.sub(r"^ERROR\s+", "", str(said))
    return j, ""


# ── consent, and the badge that says where a voice may go ──
#
# A CLONED VOICE WITH NO NOTE OF WHO GAVE IT, WHEN, AND FOR WHAT is the one that causes trouble in
# two years when nobody remembers. The note lives in meta.json beside ref.wav in MANTRA_VOICE, so
# every app on the Mac that lists voices sees it, not only this one.
#
# USAGE IS TWO WORDS, NOT A SCALE. public: cleared for something people will see. private: for
# trying things, and nothing made with it leaves this Mac. A voice with no consent recorded is
# treated as stricter than private, because "nobody wrote it down" is not permission.

def consent_problem(c, today):
    """None, or the sentence to show. `today` is YYYY-MM-DD, passed in so the rule can be tested."""
    if not isinstance(c, dict):
        return "the consent note is missing"
    if not str(c.get("who") or "").strip():
        return "say who gave this voice"
    if not str(c.get("what_for") or "").strip():
        return "say what they gave it for"
    if c.get("usage") not in USAGES:
        return "choose public or private"
    when = str(c.get("when") or "").strip()
    if when and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
        return "the date should read like %s" % today
    if when and when > today:
        return "permission cannot be dated in the future"
    return None


def consent_record(c, today):
    """Only the four fields, stripped, with the date defaulting to today."""
    return {"who": " ".join(str(c.get("who")).split()), "when": str(c.get("when") or "").strip() or today,
            "what_for": " ".join(str(c.get("what_for")).split()), "usage": c.get("usage")}


def voice_badge(meta):
    """{usage, label, release} from a MANTRA_VOICE voice entry."""
    c = (meta or {}).get("consent") or {}
    if consent_problem(c, "9999-12-31") is not None:
        return {"usage": "none", "label": "no consent recorded", "release": False}
    if c["usage"] == "public":
        return {"usage": "public", "label": "public", "release": True}
    return {"usage": "private", "label": "private, for experiments", "release": False}


STRICTNESS = {"public": 0, "private": 1, "none": 2}


def stricter(a, b):
    """The usage that wins when a cell's snapshot and the voice's current note disagree. A voice
    made public later does not make an old take public by surprise, and a voice withdrawn later
    makes every take made with it private at once — the stricter word always wins."""
    a = a if a in STRICTNESS else "none"
    if b not in STRICTNESS:
        return a
    return a if STRICTNESS[a] >= STRICTNESS[b] else b


def release_suffix(meta, playing):
    """
    THE WARNING TRAVELS IN THE FILE NAME. A downloaded take goes into a Resolve bin under the words
    it says, and there nothing else about it is visible. So a take made with a voice that is not
    cleared for release says so where it will be read: in the name, beside the words.
    """
    engine = os.path.splitext(os.path.basename(playing))[0]
    if not engine.startswith("transform-") or meta.get("voice") != engine:
        return ""
    usage = meta.get("transform_usage") or "none"
    live, _ = voice_api("GET", "/voices", timeout=3)
    if isinstance(live, dict):
        name = meta.get("transform_voice", "")
        for v in live.get("voices", []):
            if v.get("name") == name:
                usage = stricter(usage, voice_badge(v)["usage"])
    if usage == "public":
        return " (voice %s)" % meta.get("transform_voice", "")
    return " (PRIVATE voice %s, not for release)" % meta.get("transform_voice", "")


def note_kept(answer, name, record):
    """
    CHECK THE NOTE THAT CAME BACK, NOT THE 200. MANTRA_VOICE from before 11.9.2026 accepts a consent
    field on /add, answers ok, and throws the note away — measured against its master branch. An add
    that reported success there would leave a friend's voice with nobody's permission written down.
    """
    for v in (answer or {}).get("voices") or []:
        if v.get("name") == name:
            return (v.get("consent") or {}) == record
    return False


def engine_for(voice):
    return "transform-" + re.sub(r"[^A-Za-z0-9_-]", "_", voice)[:40]


@app.route("/api/clones")
def clones():
    """The voices on MANTRA_VOICE, each with its badge. Free and local, so nothing about keys."""
    j, why = voice_api("GET", "/voices", timeout=5)
    if j is None:
        return jsonify({"ok": False, "why": why, "voices": []})
    out = []
    for v in j.get("voices", []):
        out.append({"name": v.get("name"), "text": v.get("text", ""), "consent": v.get("consent") or None,
                     "badge": voice_badge(v)})
    return jsonify({"ok": True, "voices": out, "ffmpeg": bool(ffmpeg_path())})


@app.route("/api/clones/add", methods=["POST"])
def clone_add():
    """
    A NEW VOICE FROM A FILE HE PICKS, AND IT CANNOT BE ADDED WITHOUT THE CONSENT NOTE.

    The upload is kept under ~/.sampleplayer-web/voice-sources rather than deleted, because
    MANTRA_VOICE writes the source path into meta.json so the reference can be cut again later.
    """
    today = time.strftime("%Y-%m-%d")
    f = request.files.get("file")
    form = request.form
    consent = {k: form.get(k, "") for k in ("who", "when", "what_for", "usage")}
    problem = consent_problem(consent, today)
    name = re.sub(r"[^A-Za-z0-9_-]", "_", (form.get("name") or "").strip())[:40]
    if not f or not f.filename:
        return jsonify({"ok": False, "why": "choose a recording first"})
    if not name:
        return jsonify({"ok": False, "why": "give the voice a name"})
    if problem:
        return jsonify({"ok": False, "why": problem})
    src_dir = os.path.join(APPDIR, "voice-sources")
    os.makedirs(src_dir, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", f.filename)[-80:]
    src = os.path.join(src_dir, "%d_%s" % (int(time.time()), safe))
    f.save(src)
    record = consent_record(consent, today)
    body = json.dumps({"name": name, "source": src, "start": form.get("start") or 0,
                       "length": form.get("length") or 12, "consent": record})
    j, why = voice_api("POST", "/add", body.encode(), timeout=320)
    if j is None:
        return jsonify({"ok": False, "why": why})
    added = j.get("name", name)
    if not note_kept(j, added, record):
        return jsonify({"ok": False, "name": added, "why": (
            "MANTRA_VOICE added %s but did not keep the note, so it shows as no consent recorded. "
            "Update it: cd ~/Developer/MANTRA_VOICE && git pull, switch Voices off and on in the star menu, "
            "then choose %s and record the note" % (added, added))})
    return jsonify({"ok": True, "name": added})


@app.route("/api/clones/consent", methods=["POST"])
def clone_consent():
    """The note for a voice that was added before notes existed, or corrected afterwards."""
    b = request.get_json(force=True) or {}
    today = time.strftime("%Y-%m-%d")
    problem = consent_problem(b, today)
    if problem:
        return jsonify({"ok": False, "why": problem})
    body = json.dumps({"name": b.get("name", ""), "consent": consent_record(b, today)})
    j, why = voice_api("POST", "/consent", body.encode(), timeout=10)
    return jsonify({"ok": j is not None, "why": why})


def sweep_transform_tmp(appdir):
    """The folders a transform works in, left by a crash or by v3.2 (which never removed its one fixed
    folder). Swept at start, never during a run: a live transform's folder is younger than the server."""
    gone = 0
    for x in os.listdir(appdir) if os.path.isdir(appdir) else []:
        if x.startswith("tmp-transform"):
            shutil.rmtree(os.path.join(appdir, x), ignore_errors=True)
            gone += 1
    return gone


def transform_cell(pid, slot, voice):
    """(report, why). Everything that can fail says which of its five steps it failed at."""
    wav = original(pid, slot)
    if not os.path.isfile(wav):
        return None, "nothing recorded in that cell"
    ff = ffmpeg_path()
    if not ff:
        return None, "the transform needs ffmpeg (brew install ffmpeg), the same one MANTRA_VOICE uses"
    listing, why = voice_api("GET", "/voices", timeout=5)
    if listing is None:
        return None, why
    entry = next((v for v in listing.get("voices", []) if v.get("name") == voice), None)
    if entry is None:
        return None, "MANTRA_VOICE has no voice called %s" % voice

    with open(wav, "rb") as fh:
        take = fh.read()
    heard, why = voice_api("POST", "/hear?words=1", take, "audio/wav", timeout=320)
    if heard is None:
        return None, "listening to your take: " + why
    # THE "d" IN /hear IS THE END TIME, NOT A DURATION. ears.py writes round(w.end, 3) into it; the
    # example in API.md reads like a duration and the brief said "start and duration". Taken at its
    # word it would put every one of their words in the wrong place.
    words = [(re.sub(r"\s+", "", w.get("w", "")), w.get("t", 0), w.get("d", 0))
             for w in heard.get("words", [])]
    words = [w for w in words if w[0]]
    if not words:
        return None, "no words were heard in your take"
    text = " ".join(w[0] for w in words)

    # engine IS SENT, AND CHECKED ON THE WAY BACK. /say takes the engine from the Mac-wide setting
    # when none is named, so with the computer's voice set to Beatrice a clone's name would be
    # spoken by Speechify, billed, and reported under the clone's name.
    said, why = voice_api("POST", "/say", json.dumps({"text": text, "engine": "clone", "voice": voice}).encode(),
                          timeout=600)
    if said is None:
        return None, "the cloned voice: " + why
    if said.get("engine") != "clone" or said.get("voice") != voice:
        return None, "MANTRA_VOICE answered with %s/%s, not the clone %s" % (said.get("engine"), said.get("voice"), voice)
    tokens = said.get("tokens") or []
    if len(tokens) != len(words):
        return None, "the clone's words (%d) do not line up with yours (%d)" % (len(tokens), len(words))
    code, mp3 = http("GET", VOICE_API + said.get("url", ""), timeout=30)
    if code != 200 or not mp3:
        return None, "could not fetch the clone's audio (HTTP %d)" % code

    # ONE FOLDER PER TRANSFORM, gone when it ends. The server is threaded, and a fixed folder had two
    # cells transformed together read each other's clone (found 11.9.2026, after v3.2 shipped).
    os.makedirs(APPDIR, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="tmp-transform-", dir=APPDIR)
    try:
        mp3_path, theirs_wav = os.path.join(tmp, "clone.mp3"), os.path.join(tmp, "clone.wav")
        with open(mp3_path, "wb") as fh:
            fh.write(mp3)
        try:
            r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", mp3_path, "-ac", "1",
                                "-ar", str(RATE), "-c:a", "pcm_s16le", theirs_wav], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            return None, "ffmpeg did not run: %s" % str(e)[:120]
        if r.returncode != 0:
            return None, "ffmpeg could not read the clone's audio"

        mine, rate = read_samples(wav)
        theirs, trate = read_samples(theirs_wav)
        if not mine or not theirs:
            return None, "one of the two recordings is empty"
        his_total, their_total = len(mine) / rate, len(theirs) / trate
        his = snap_spans(mine, rate, _clean_spans([(w[1], w[2]) for w in words], his_total))
        their = snap_spans(theirs, trate, _clean_spans([(t.get("t", 0), t.get("d", 0)) for t in tokens], their_total))
        segs = plan_stretch(his, their, his_total, their_total)
        track, filt, why = render_plan(ff, theirs_wav, their_total, segs, len(mine), rate)
        if track is None:
            return None, why
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    engine = engine_for(voice)
    write_wav(generated(pid, slot, engine), track, rate)       # gen/, one level down: never original.wav
    badge = voice_badge(entry)
    counts = {k: sum(len(s["words"]) for s in segs if s["verdict"] == k) for k in ("ok", "smear", "chirp")}
    worst = max((s["ratio"] if s["ratio"] >= 1 else 1 / s["ratio"] for s in segs), default=1.0)
    write_meta(pid, slot, {"voice": engine, "transform_voice": voice, "transform_usage": badge["usage"],
                           "transform_report": "ok %d smear %d chirp %d worst %.2fx %s" % (
                               counts["ok"], counts["smear"], counts["chirp"], worst, filt)})
    return {"engine": engine, "filter": filt, "badge": badge, "counts": counts, "worst": round(worst, 2),
            "segments": [{"words": " ".join(words[k][0] for k in s["words"]), "ratio": s["ratio"],
                          "level": s["level"], "verdict": s["verdict"], "at": s["dst"][0]} for s in segs]}, ""


@app.route("/api/transform/<int:slot>", methods=["POST"])
def do_transform(slot):
    pid = request.args.get("project", "project-01")
    voice = (request.get_json(force=True) or {}).get("voice", "")
    if not voice:
        return jsonify({"ok": False, "why": "choose a cloned voice first"})
    report, why = transform_cell(pid, slot, voice)
    if report is None:
        return jsonify({"ok": False, "why": why})
    return jsonify({"ok": True, "report": report})


@app.route("/api/preview", methods=["POST"])
def preview():
    """A voice says its own name. Short on purpose: ten auditions is ten billed requests."""
    b = request.get_json(force=True) or {}
    line = b.get("line") or ("This is %s." % b.get("name", "this voice"))
    # The raw line INCLUDING its tags: the same words tagged differently are a different
    # performance and must not be served from one another's cache entry.
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


@app.route("/api/emotions")
def emotions():
    return jsonify({"emotions": all_emotions()})


@app.route("/api/emotions", methods=["POST"])
def add_emotion():
    """
    ONE DATABASE OF DIRECTIONS, SHARED BY EVERY VOICE.

    An emotion belongs to the direction and not to the actor: "the way my father says it" is a
    note about a delivery, and a note that only works on one voice out of eleven hundred is a note
    nobody will ever reuse. Added on any card, offered on all of them.
    """
    b = request.get_json(force=True) or {}
    label = (b.get("label") or "").strip().lower()
    text = (b.get("text") or "").strip()
    if not label or not text:
        return jsonify({"ok": False, "why": "an emotion needs a name and a description"})
    if not re.fullmatch(r"[a-z0-9 _'-]{1,40}", label):
        # The label becomes a tag inside the line, so it cannot contain the brackets that delimit
        # it or anything a filename would argue with later.
        return jsonify({"ok": False, "why": "letters, digits, spaces and dashes only"})
    items = [e for e in custom_emotions() if e.get("label", "").lower() != label]
    items.append({"label": label, "glyph": (b.get("glyph") or "•")[:2], "text": text})
    os.makedirs(APPDIR, exist_ok=True)
    tmp = EMOTIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, EMOTIONS_FILE)
    return jsonify({"ok": True, "emotions": all_emotions()})


@app.route("/api/emotions/<label>", methods=["DELETE"])
def remove_emotion(label):
    items = [e for e in custom_emotions() if e.get("label", "").lower() != label.lower()]
    with open(EMOTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    return jsonify({"ok": True, "emotions": all_emotions()})


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


# ── testing a key, the Key_Tester table ───────────────────────────────────────────────────────
#
# WHERE EACH PROVIDER IS ASKED, AND WHERE IT IS NOT. Ported from `Key_Tester/Providers.kt` rather
# than rewritten, because every entry here is a measurement somebody already paid for:
#
#   Speechify is `/v1/voices?limit=1`. NOT `/v1/models` — that answers `404 page not found`, which
#   reads as a dead key and has condemned working accounts.
#   AssemblyAI is `/v2/transcript?limit=1`, and its header is the RAW key with no `Bearer`.
#   Hume is the TOKEN endpoint with the pair as Basic auth. `/v0/tts/voices` tests the api key
#   alone, which proves nothing about the secret, and an account is the pair.
#   Groq, Gemini and Anthropic are here because the note contains them; the app never calls them.

PROBES = {
    "speechify": ("GET", "https://api.sws.speechify.com/v1/voices?limit=1",
                  lambda k: {"Authorization": "Bearer " + k}),
    "elevenlabs": ("GET", "https://api.elevenlabs.io/v1/user",
                   lambda k: {"xi-api-key": k}),
    "assemblyai": ("GET", "https://api.assemblyai.com/v2/transcript?limit=1",
                   lambda k: {"authorization": k}),
    "groq": ("GET", "https://api.groq.com/openai/v1/models",
             lambda k: {"Authorization": "Bearer " + k}),
    "gemini": ("GET", "https://generativelanguage.googleapis.com/v1beta/models",
               lambda k: {"x-goog-api-key": k}),
    "anthropic": ("GET", "https://api.anthropic.com/v1/models",
                  lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}),
}


def test_credential(cred):
    """
    One real call. Returns (status, sentence).

    THE FOUR ANSWERS ARE NOT THREE. Working, busy, refused — and a fourth that says nothing about
    the key at all: no network, or Cloudflare. Folding that fourth into "refused" is how a good
    account gets deleted because the wifi was captive.
    """
    provider = cred["provider"]

    if provider == "hume":
        # THE PAIR, TESTED AS A PAIR, BEFORE ANYTHING ELSE. Base64 without newlines: a wrapped
        # Authorization header is a corrupt one, and the wrap only appears once the pair is long
        # enough. This proves the ACCOUNT exists; the work probe below proves it can do anything.
        if not cred.get("secret"):
            return "unknown", "this Hume key has no secret beside it"
        basic = base64.b64encode(
            ("%s:%s" % (cred["key"], cred["secret"])).encode()).decode().replace("\n", "")
        code, body = http("POST", "https://api.hume.ai/oauth2-cc/token",
                          {"Authorization": "Basic " + basic,
                           "Content-Type": "application/x-www-form-urlencoded"},
                          b"grant_type=client_credentials", timeout=30)
        if code != 200 or b"access_token" not in body:
            return status_word(code, body), explain(code, body)

    # THE WORK PROBE IS THE ONE THAT TELLS THE TRUTH.
    #
    # A list call says "this key is a real key", and it says it just as cheerfully for an account
    # that cannot generate a single word — which is the trick that sent this ring at a wall three
    # times. Hume's token endpoint is the same lie in a different shape. Only asking for WORK asks
    # whether work is possible.
    #
    # Hume's billing page is why this matters beyond one provider: a new account gets its free
    # credit ONCE, and the monthly reset applies only to a paid subscription — so a spent free
    # account is spent for good rather than until the first of the month.
    verdict = work_probe(cred)
    if verdict:
        return verdict

    probe = PROBES.get(provider)
    if not probe:
        return "unknown", "nothing here knows how to test a %s key" % provider
    method, url, headers = probe
    code, body = http(method, url, headers(cred["key"]), None, timeout=30)
    if 200 <= code < 300:
        return "working", "working"

    # sk_ IS SHARED between Speechify and ElevenLabs and only length separates them. A key on the
    # wrong side of that line is tested against the wrong host and answers 401, which is
    # indistinguishable from dead — so the other one is tried before anything is said.
    if code == 401 and provider in ("speechify", "elevenlabs"):
        other = "elevenlabs" if provider == "speechify" else "speechify"
        m, u, h = PROBES[other]
        c2, b2 = http(m, u, h(cred["key"]), None, timeout=30)
        if 200 <= c2 < 300:
            return "working", "working, but it is a %s key rather than a %s one" % (other, provider)

    return status_word(code, body), explain(code, body)


# THE WORDS EVERY PROVIDER USES WHEN THE MONEY HAS RUN OUT, and they all use different ones: Hume
# 400 E0300, Anthropic 400 "credit balance", Gemini 429 RESOURCE_EXHAUSTED, Speechify 402. Matched
# as words because the CODE is what they disagree about. Gemini says RESOURCE_EXHAUSTED for a spent
# account AND for two requests in one second, so the retry hint (RetryInfo, QuotaFailure) is
# checked FIRST and wins: measured 30.8.2026, HANDOFF.md "OUT OF CREDIT AND THROTTLED".
STRONG_MONEY = (
    "credit", "e0300", "zero_credits", "balance", "depleted", "insufficient",
    "billing", "payment", "out of funds", "upgrade your plan", "prepayment",
)

# These appear in both, so they only count when nothing suggests waiting.
WEAK_MONEY = ("quota", "exhausted", "resource_exhausted", "free tier", "plan limit")

WAIT_HINTS = ("retrydelay", "retry-after", "retryinfo", "quotafailure",
              "per minute", "per-minute", "rate limit", "rate_limit", "try again in")


def sounds_like_money(body):
    """True when the answer means PAY, false when it means WAIT or anything else."""
    b = (body or b"").decode("utf-8", "replace").lower()
    if any(h in b for h in WAIT_HINTS):
        # It told us how long to wait, so it is a throttle whatever else it says.
        return False
    if any(w in b for w in STRONG_MONEY):
        return True
    return any(w in b for w in WEAK_MONEY)


# THE CHEAPEST REAL PIECE OF WORK EACH PROVIDER CAN DO.
#
# A LIST CALL ANSWERS THE WRONG QUESTION. `/v1/voices` and `/v1/models` say "this key is a real
# key", and they say it just as cheerfully for an account that cannot generate a single word —
# which is the trick that sent this ring at a wall three times. Only asking for WORK asks whether
# work is possible.
#
# Each of these is the smallest billable unit that provider sells: one word of speech, one token
# of text. It costs a fraction of a cent when the account is alive and NOTHING when it is not,
# which is the direction that matters.
WORK_PROBES = {
    "hume": ("POST", "https://api.hume.ai/v0/tts",
             lambda c: {"X-Hume-Api-Key": c["key"], "Content-Type": "application/json"},
             lambda c: json.dumps({"utterances": [{"text": "Hi."}],
                                   "format": {"type": "wav"}, "num_generations": 1}).encode()),
    "speechify": ("POST", "https://api.sws.speechify.com/v1/audio/speech",
                  lambda c: {"Authorization": "Bearer " + c["key"],
                             "Content-Type": "application/json"},
                  lambda c: json.dumps({"input": "Hi.", "voice_id": "beatrice_32",
                                        "audio_format": "wav", "model": "simba-3.2"}).encode()),
    # THE MODEL IS ASKED FOR RATHER THAN NAMED.
    #
    # The first version of this named llama-3.1-8b-instant, gemini-2.0-flash and
    # claude-3-5-haiku, and all three answered 404 — every one of them had been retired or
    # renamed. A probe that hard-codes a model is a probe with an expiry date, and the failure it
    # produces looks exactly like a broken key, which is the worst possible way for it to break.
    #
    # So the list call comes first and the probe uses whatever that account actually has. It costs
    # one extra request, on a button somebody presses by hand.
    "groq": ("POST", "https://api.groq.com/openai/v1/chat/completions",
             lambda c: {"Authorization": "Bearer " + c["key"],
                        "Content-Type": "application/json"},
             lambda c: json.dumps({
                 "model": first_model(c) or "llama-3.3-70b-versatile", "max_tokens": 1,
                 "messages": [{"role": "user", "content": "hi"}]}).encode()),
    "gemini": ("POST", None,
               lambda c: {"x-goog-api-key": c["key"], "Content-Type": "application/json"},
               lambda c: json.dumps({"contents": [{"parts": [{"text": "hi"}]}],
                                     "generationConfig": {"maxOutputTokens": 1}}).encode()),
    "anthropic": ("POST", "https://api.anthropic.com/v1/messages",
                  lambda c: {"x-api-key": c["key"], "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"},
                  lambda c: json.dumps({
                      "model": first_model(c) or "claude-3-5-haiku-20241022", "max_tokens": 1,
                      "messages": [{"role": "user", "content": "hi"}]}).encode()),
    # ASSEMBLYAI IS NOT IN THIS TABLE because its probe is three requests rather than one — the
    # audio has to be uploaded before it can be submitted. It has its own function, and it is a
    # real work probe like the rest: see assemblyai_probe.
}


def first_model(cred):
    """
    The first model this account can actually use, asked for rather than assumed.

    Measured 30.8.2026: Groq's list has whisper and gpt-oss on it, Gemini's has gemini-2.5-flash,
    Anthropic's has claude-opus-5. None of the names written into the first version of this probe
    existed any more.
    """
    provider = cred["provider"]
    if provider == "groq":
        code, body = http("GET", "https://api.groq.com/openai/v1/models",
                          {"Authorization": "Bearer " + cred["key"]})
        if code != 200:
            return None
        for m in (json.loads(body).get("data") or []):
            i = m.get("id", "")
            # Text models only: asking a speech model for a chat completion is a 400 that reads
            # like a dead key.
            if i and "whisper" not in i and "tts" not in i and "guard" not in i:
                return i
        return None
    if provider == "anthropic":
        code, body = http("GET", "https://api.anthropic.com/v1/models",
                          {"x-api-key": cred["key"], "anthropic-version": "2023-06-01"})
        if code != 200:
            return None
        data = json.loads(body).get("data") or []
        return data[0].get("id") if data else None
    if provider == "gemini":
        code, body = http("GET", "https://generativelanguage.googleapis.com/v1beta/models",
                          {"x-goog-api-key": cred["key"]})
        if code != 200:
            return None
        for m in (json.loads(body).get("models") or []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                name = m.get("name", "")
                if "tts" not in name and "image" not in name:
                    return name
        return None
    return None


def probe_clip():
    """
    A SECOND OF AUDIO THIS APP MAKES ITSELF, for asking AssemblyAI whether it can work: it transcribes,
    so its probe needs audio, and a fresh install has none. A tone, not silence, because silence is
    indistinguishable from a broken encoder. One second is a hundred-thousandth of a billed hour.
    Measured 30.8.2026: HANDOFF.md "WHEN A PROBE NEEDS AUDIO".
    """
    import math
    rate = 16000
    frames = rate  # one second
    samples = [int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(frames)]
    data = struct.pack("<%dh" % frames, *samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) +
            b"data" + struct.pack("<I", len(data)) + data)


def assemblyai_probe(cred):
    """
    Upload a second of tone, submit it, and see which of the three stages refuses.

    THE MONEY ANSWER CAN ARRIVE AT ANY OF THE THREE. Upload, submit and poll are three separate
    requests to three endpoints, and a provider is free to refuse at whichever it notices first.
    Checking only the last one is how a probe reports "unknown" for an account that said plainly
    at the first step that it was out of funds.

    It does NOT poll to completion. The submit being accepted is the question — whether the
    transcription then finds words in a sine wave is not.
    """
    auth = {"authorization": cred["key"]}
    code, body = http("POST", "https://api.assemblyai.com/v2/upload", auth, probe_clip())
    if code >= 300:
        if sounds_like_money(body):
            return "no credit", "account live, free credit spent \u2014 it needs a paid plan"
        return status_word(code, body), explain(code, body)

    url = json.loads(body).get("upload_url")
    code, body = http("POST", "https://api.assemblyai.com/v2/transcript",
                      dict(auth, **{"Content-Type": "application/json"}),
                      json.dumps({"audio_url": url, "language_code": "en"}).encode())
    if code >= 300:
        if sounds_like_money(body):
            return "no credit", "account live, free credit spent \u2014 it needs a paid plan"
        return status_word(code, body), explain(code, body)

    log_spend("assemblyai", 1, "key test")
    return "working", "working, and it has credit"


def work_probe(cred):
    """
    Ask the provider to do the smallest real thing it sells.

    Returns (state, sentence) or None when there is no cheap probe for that provider.
    """
    if cred["provider"] == "assemblyai":
        return assemblyai_probe(cred)
    probe = WORK_PROBES.get(cred["provider"])
    if not probe:
        return None
    method, url, headers, body = probe
    if url is None:
        # Gemini puts the model in the PATH, so its url cannot be written down until the model is
        # known. A missing url here means "ask first", rather than a hole somebody has to notice.
        model = first_model(cred)
        if not model:
            return "unknown", "could not ask which models this account has"
        url = "https://generativelanguage.googleapis.com/v1beta/%s:generateContent" % model
    code, resp = http(method, url, headers(cred), body(cred), timeout=45)
    if 200 <= code < 300:
        if cred["provider"] == "hume":
            log_spend("hume", len("Hi."), "key test")
        elif cred["provider"] == "speechify":
            log_spend("speechify", 3, "key test")
        return "working", "working, and it has credit"
    if sounds_like_money(resp):
        # ITS OWN STATE, NEITHER WORKING NOR REFUSED. The key is real and the account is alive; it
        # simply cannot do anything until somebody pays. Calling it working sends the ring at a
        # wall; calling it refused has somebody delete a live account they only needed to top up.
        return "no credit", "account live, free credit spent \u2014 it needs a paid plan"
    if code == 429:
        return "busy", "alive, and throttled this minute"
    return status_word(code, resp), explain(code, resp)


def status_word(code, body):
    b = (body or b"").decode("utf-8", "replace").lower()
    if code == -1:
        return "unknown"
    if code == 403 and ("1010" in b or "cloudflare" in b):
        return "unknown"
    if code == 429:
        return "busy"
    if 200 <= code < 300:
        return "working"
    if is_dead_answer(code, body):
        return "refused"
    return "unknown"


@app.route("/api/spend")
def spend():
    per, money = spend_totals()
    return jsonify({"per": per, "money": money, "rates": rates(),
                    "rows": spend_rows()[-500:], "count": len(spend_rows())})


@app.route("/api/spend/clear", methods=["POST"])
def spend_clear():
    """Clearing the log empties the box, because the box was only ever the log added up."""
    n = len(spend_rows())
    if os.path.isfile(SPEND_FILE):
        os.remove(SPEND_FILE)
    return jsonify({"ok": True, "removed": n})


@app.route("/api/spend/rates", methods=["POST"])
def spend_rates():
    b = request.get_json(force=True) or {}
    r = rates()
    for k in DEFAULT_RATES:
        if k in b:
            try:
                r[k] = float(b[k])
            except (TypeError, ValueError):
                return jsonify({"ok": False, "why": "%s is not a number" % k})
    tmp = RATES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(r, f)
    os.replace(tmp, RATES_FILE)
    return jsonify({"ok": True, "rates": r})


@app.route("/api/keys/credit", methods=["POST"])
def key_credit():
    """
    HAS THIS HUME ACCOUNT GOT CREDIT.

    HUME IS THE ONLY PROVIDER HERE THAT CAN ANSWER THIS, and it does not answer it directly.
    Probed on 30.8.2026: `/v0/usage`, `/v0/billing` and `/v0/account` are all 404, AssemblyAI's
    `/v2/account` returns an empty object, Speechify has no usage surface at all, and Anthropic's
    usage report needs an Admin key which is a different key from the one in the note. So there is
    no balance to read anywhere.

    What Hume does is refuse: a synthesis on an exhausted account answers `400 E0300 zero_credits`.
    So the test is the cheapest possible real call — one word — and the answer is the refusal or
    the absence of it. It costs a word of synthesis when the account is alive and nothing at all
    when it is not, which is the direction that matters.
    """
    want = (request.get_json(force=True) or {}).get("masked")
    if not os.path.isfile(KEYS_FILE):
        return jsonify({"ok": False, "why": "no keys"})
    for cred in parse_keys(open(KEYS_FILE, encoding="utf-8", errors="replace").read()):
        if masked(cred["key"]) != want:
            continue
        if cred["provider"] != "hume":
            return jsonify({"ok": False,
                            "why": "only Hume can be asked this — nothing else publishes it"})
        code, body = http(
            "POST", "https://api.hume.ai/v0/tts",
            {"X-Hume-Api-Key": cred["key"], "Content-Type": "application/json"},
            json.dumps({"utterances": [{"text": "Hi."}], "format": {"type": "wav"},
                        "num_generations": 1}).encode(),
        )
        if 200 <= code < 300:
            d = json.loads(body)
            gens = d.get("generations") or [{}]
            log_spend("hume", len("Hi."), "credit test")
            return jsonify({"ok": True, "state": "has credit", "why": "has credit"})
        b = body.decode("utf-8", "replace").lower()
        if "credit" in b or "e0300" in b:
            return jsonify({"ok": True, "state": "exhausted",
                            "why": "out of credit — safe to delete"})
        return jsonify({"ok": True, "state": "unknown", "why": explain(code, body)})
    return jsonify({"ok": False, "why": "no such key"})


@app.route("/api/keys/test", methods=["POST"])
def test_keys():
    """
    Test one key, or every key.

    ONE AT A TIME AND SEQUENTIALLY. Twenty-one Hume accounts asked at once is twenty-one requests
    from one address in one second, which is what a rate limiter is for — and the answer would be
    a column of 429s that say nothing about any of the keys.
    """
    b = request.get_json(force=True) or {}
    want = b.get("masked")
    out = []
    if not os.path.isfile(KEYS_FILE):
        return jsonify({"results": out})
    for cred in parse_keys(open(KEYS_FILE, encoding="utf-8", errors="replace").read()):
        if want and masked(cred["key"]) != want:
            continue
        state, why = test_credential(cred)
        out.append({"provider": cred["provider"], "label": cred["label"],
                    "masked": masked(cred["key"]), "state": state, "why": why})
    return jsonify({"results": out})


@app.route("/api/keys/delete", methods=["POST"])
def delete_key():
    """
    Write DELETED over the token, and leave every other line where it was.

    NOT CUT OUT. The parser reads a key's account name from the line ABOVE it, so removing a line
    shifts what the next key thinks it is called — and a note where every account has the previous
    account's name is worse than a note with a dead key in it.
    """
    want = (request.get_json(force=True) or {}).get("masked")
    if not want or not os.path.isfile(KEYS_FILE):
        return jsonify({"ok": False, "why": "no such key"})
    text = open(KEYS_FILE, encoding="utf-8", errors="replace").read()
    hit = None
    for cred in parse_keys(text):
        if masked(cred["key"]) == want:
            hit = cred
            break
    if not hit:
        return jsonify({"ok": False, "why": "no such key"})
    out = text.replace(hit["key"], "DELETED")
    if hit.get("secret"):
        out = out.replace(hit["secret"], "DELETED")
    tmp = KEYS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, KEYS_FILE)
    return jsonify({"ok": True, "why": "deleted, and the note's shape is unchanged"})


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
    sweep_transform_tmp(APPDIR)
    port = _pick_port(HOST, BASE_PORT)
    with open(PORT_FILE, "w") as f:
        f.write(str(port))
    print("sample player on http://127.0.0.1:%d" % port, file=sys.stderr)
    # The banner is the launcher's job. Two panels saying the same thing, one of them wrapped in
    # asterisks warning about a development server, is one panel too many.
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None
    app.run(host=HOST, port=port, threaded=True, debug=False)
