#!/usr/bin/env python3
"""
TEST 1 — THE MECHANISM, ALONE.

No network, no browser, no microphone. Every case here is a pure function fed a value, which is
the layer where a bug can be proven absent rather than merely not observed.

Run with:  python3 tests/test_server.py

The cases are weighted towards the things that destroy work or spend money: the paths that protect
the original recording, the key parser, the cache keys, and the classifier that decides whether an
account gets buried.
"""

import base64
import importlib.util
import json
import os
import shutil
import struct
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The server imports Flask at module scope and this must run without it installed — a test suite
# that needs the app's dependencies is a test suite that stops running the day one of them breaks.
sys.modules.setdefault("flask", types.SimpleNamespace(
    Flask=lambda *a, **k: types.SimpleNamespace(
        after_request=lambda f: f,
        route=lambda *a, **k: (lambda f: f),
        run=lambda **k: None,
    ),
    jsonify=lambda *a, **k: None,
    request=None,
    send_from_directory=None,
))

spec = importlib.util.spec_from_file_location("srv", os.path.join(ROOT, "server.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def wav_bytes(rate, frames, extra_chunk=False, placeholder=False, value=1000):
    """A real WAV, optionally in Speechify's shape: RIFF / fmt / LIST / data."""
    data = struct.pack("<%dh" % frames, *([value] * frames))
    parts = [b"WAVE"]
    parts.append(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
    if extra_chunk:
        parts.append(b"LIST" + struct.pack("<I", 26) + b"x" * 26)
    size = 0xFFFFFFFF if placeholder else len(data)
    parts.append(b"data" + struct.pack("<I", size) + data)
    body = b"".join(parts)
    return b"RIFF" + struct.pack("<I", len(body)) + body


class Paths(unittest.TestCase):
    """The rules that protect the one file that cannot be made again."""

    def test_generated_is_never_the_original(self):
        for engine in ["speechify", "hume", "original", "original.wav", "pending"]:
            self.assertNotEqual(
                S.original("p", 3),
                S.generated("p", 3, engine),
                "engine %r collided with the recording" % engine,
            )

    def test_generated_lives_one_directory_down(self):
        self.assertEqual(os.path.basename(os.path.dirname(S.generated("p", 3, "hume"))), "gen")
        self.assertEqual(os.path.basename(os.path.dirname(S.original("p", 3))), "03")

    def test_an_engine_name_that_is_a_path_is_refused(self):
        for bad in ["../original", "a/b", "..", ""]:
            with self.assertRaises(ValueError, msg="accepted %r" % bad):
                S.generated("p", 3, bad)

    def test_slot_numbers_are_two_digits(self):
        self.assertTrue(S.slot_dir("p", 3).endswith("03"))
        self.assertTrue(S.slot_dir("p", 29).endswith("29"))


class Wav(unittest.TestCase):
    """Walking chunks, because audio does not start at byte 44 in anything we did not write."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, data):
        # Closed properly. An unclosed handle is a ResourceWarning on every run, and a suite that
        # prints warnings is a suite whose output stops being read.
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_a_plain_file_reads_from_44(self):
        p = self.write("ours.wav", wav_bytes(44100, 100))
        self.assertEqual(S.wav_layout(p)[0], 44)
        self.assertEqual(S.wav_layout(p)[1], 44100)
        self.assertEqual(len(S.read_samples(p)[0]), 100)

    def test_a_LIST_chunk_does_not_shift_every_sample(self):
        # Measured on a real Speechify WAV: the audio begins at byte 78.
        p = self.write("speechify.wav", wav_bytes(48000, 100, extra_chunk=True))
        off, rate, frames = S.wav_layout(p)
        self.assertEqual(off, 78)
        self.assertEqual(rate, 48000)
        self.assertEqual(frames, 100)

    def test_a_streaming_placeholder_size_is_not_believed(self):
        # 0xFFFFFFFF taken literally is four gigabytes.
        p = self.write("streamed.wav", wav_bytes(48000, 100, extra_chunk=True, placeholder=True))
        self.assertEqual(S.wav_layout(p)[2], 100)
        self.assertLess(S.length_ms(p), 100)

    def test_something_that_is_not_a_wav_does_not_crash(self):
        p = self.write("no.bin", b"\x07" * 200)
        self.assertEqual(S.wav_layout(p)[1], S.RATE)
        self.assertEqual(S.read_samples(p)[0], [])

    def test_a_missing_file_is_zero_rather_than_an_exception(self):
        self.assertEqual(S.length_ms(os.path.join(self.dir, "nope.wav")), 0)

    def test_a_round_trip_keeps_every_sample(self):
        p = os.path.join(self.dir, "rt.wav")
        samples = [0, 1000, -1000, 32767, -32767, 5]
        S.write_wav(p, samples, 44100)
        back, rate = S.read_samples(p)
        self.assertEqual(back, samples)
        self.assertEqual(rate, 44100)

    def test_writing_leaves_no_temporary_behind(self):
        p = os.path.join(self.dir, "tmp.wav")
        S.write_wav(p, [1, 2, 3], 44100)
        self.assertFalse(os.path.exists(p + ".tmp"))


class Normalise(unittest.TestCase):
    def test_a_quiet_take_reaches_just_under_full_scale(self):
        out = S.normalise([6000, -6000] * 500)
        self.assertEqual(max(abs(v) for v in out), int(S.TARGET_PEAK * 32767))

    def test_it_never_reaches_the_rail(self):
        self.assertLess(max(abs(v) for v in S.normalise([1000] * 500)), 32767)

    def test_a_hot_take_is_left_exactly_alone(self):
        hot = [32767, -32767] * 50
        self.assertIs(S.normalise(hot), hot)

    def test_silence_is_not_amplified_into_anything(self):
        self.assertEqual(max(abs(v) for v in S.normalise([0] * 500)), 0)

    def test_the_gain_is_capped(self):
        # Without a ceiling this multiplies by four hundred and an empty room becomes a wall of
        # hiss under a healthy-looking waveform.
        self.assertEqual(max(abs(v) for v in S.normalise([80] * 500)), int(80 * S.MAX_GAIN))

    def test_an_empty_take_is_returned_rather_than_crashing(self):
        self.assertEqual(S.normalise([]), [])


class Assess(unittest.TestCase):
    """Judged BEFORE normalisation, or room tone and a quiet phrase look identical afterwards."""

    def test_silence(self):
        self.assertEqual(S.assess([0] * 44100, 44100), "silent")

    def test_nothing_at_all(self):
        self.assertEqual(S.assess([], 44100), "silent")

    def test_too_short(self):
        self.assertEqual(S.assess([9000] * 1000, 44100), "too short")

    def test_clipped(self):
        self.assertEqual(S.assess([32700, -32700] * 22050, 44100), "clipped")

    def test_good(self):
        self.assertEqual(S.assess([9000, -9000] * 22050, 44100), "good")

    def test_the_minimum_is_a_duration_not_a_sample_count(self):
        # The same half second must pass at both rates. A frame count would be three times more
        # permissive the moment the recorder improved.
        half = [9000] * 22050
        self.assertEqual(S.assess(half, 44100), "good")
        self.assertEqual(S.assess([9000] * 24000, 48000), "good")


class Keys(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(S.classify("gsk_" + "a" * 40), "groq")
        self.assertEqual(S.classify("sk-ant-" + "a" * 30), "anthropic")
        self.assertEqual(S.classify("a" * 32), "assemblyai")
        self.assertEqual(S.classify("AIza" + "a" * 30), "gemini")

    def test_sk_underscore_splits_on_length_alone(self):
        self.assertEqual(S.classify("sk_" + "a" * 43), "speechify")
        self.assertEqual(S.classify("sk_" + "a" * 20), "elevenlabs")

    def test_prose_is_never_a_key(self):
        # A whitespace split has genuinely produced an attempt to authenticate with this word.
        for word in ["cafeteria", "CANCELLED", "Marko personal", ""]:
            self.assertIsNone(S.classify(word))

    def test_a_tracking_token_in_a_pasted_url_is_not_a_key(self):
        note = "https://speechify.ai/?srsltid=" + "A" * 56
        found = [f for f in S.parse_keys(note) if f["provider"] != "unknown"]
        self.assertEqual(found, [])

    def test_the_label_is_the_line_above(self):
        note = "Marko personal\nsk_" + "a" * 43 + "\n"
        f = S.parse_keys(note)[0]
        self.assertEqual(f["label"], "Marko personal")
        self.assertEqual(f["provider"], "speechify")

    def test_hume_is_parsed_as_a_pair(self):
        note = "Baba main\nAPI key\n" + "A" * 48 + "\nSecret key\n" + "B" * 64 + "\n"
        found = S.parse_keys(note)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["provider"], "hume")
        self.assertEqual(found[0]["label"], "Baba main")
        self.assertEqual(len(found[0]["secret"]), 64)

    def test_a_hume_secret_is_not_also_a_key_of_its_own(self):
        note = "acct\nAPI key\n" + "A" * 48 + "\nSecret key\n" + "B" * 64 + "\n"
        self.assertEqual(len(S.parse_keys(note)), 1)

    def test_duplicates_are_folded(self):
        k = "gsk_" + "c" * 40
        self.assertEqual(len(S.parse_keys(k + "\n" + k + "\n")), 1)

    def test_a_masked_key_never_shows_its_middle(self):
        # ASSEMBLED FROM PIECES rather than written as one string. G2 scans every file for key
        # SHAPES and cannot tell a plausible fixture from a real key — nor should it try. A test
        # that trips the secret scanner teaches you to ignore the scanner.
        m = S.masked("sk" + "_abc" + "defghijklmnop" + "qrstuvwxyz012345")
        self.assertTrue(m.startswith("sk_abc"))
        self.assertTrue(m.endswith("2345"))
        self.assertNotIn("jklmno", m)


class Classifier(unittest.TestCase):
    """Which answers bury an account and which do not."""

    def test_429_is_alive(self):
        self.assertFalse(S.is_dead_answer(429, b""))
        self.assertIn("good key", S.explain(429, b""))

    def test_cloudflare_1010_is_not_the_key(self):
        # Measured across 21 Hume pairs: all 21 fail without a User-Agent and all 21 work with one.
        self.assertFalse(S.is_dead_answer(403, b"error code: 1010"))
        self.assertIn("not by the key", S.explain(403, b"error code: 1010"))

    def test_a_plain_403_is_the_key(self):
        self.assertTrue(S.is_dead_answer(403, b"forbidden"))

    def test_400_with_credit_words_is_death(self):
        body = b'{"status_code":400,"code":"E0300","message":"Exhausted credit balance."}'
        self.assertTrue(S.is_dead_answer(400, body))
        self.assertIn("credit", S.explain(400, body))

    def test_a_plain_400_blames_the_request(self):
        self.assertFalse(S.is_dead_answer(400, b"bad request"))
        self.assertIn("not the key", S.explain(400, b"bad request"))

    def test_no_network_is_not_a_dead_key(self):
        self.assertFalse(S.is_dead_answer(-1, b"URLError"))
        self.assertEqual(S.explain(-1, b""), "no network")


class Cache(unittest.TestCase):
    """The same request twice costs nothing the second time — and no more than that."""

    def test_the_same_inputs_give_the_same_key(self):
        a = S.cache_key("preview", "hume", "v1", "", "This is Beatrice.", "angry")
        b = S.cache_key("preview", "hume", "v1", "", "This is Beatrice.", "angry")
        self.assertEqual(a, b)

    def test_every_input_changes_it(self):
        base = ("preview", "hume", "v1", "", "line", "")
        seen = {S.cache_key(*base)}
        for i in range(len(base)):
            other = list(base)
            other[i] = str(other[i]) + "x"
            self.assertNotIn(S.cache_key(*other), seen, "input %d did not change the key" % i)
            seen.add(S.cache_key(*other))

    def test_a_direction_changes_the_audio_and_so_the_key(self):
        plain = S.cache_key("preview", "hume", "v1", "", "line", "")
        angry = S.cache_key("preview", "hume", "v1", "", "line", "furious")
        self.assertNotEqual(plain, angry)

    def test_the_key_is_a_fingerprint_and_not_the_inputs(self):
        k = S.cache_key("preview", "hume", "v1", "", "secret line", "")
        self.assertEqual(len(k), 32)
        self.assertNotIn("secret", k)


class ProbeClip(unittest.TestCase):
    """
    The second of audio the app makes for asking AssemblyAI whether it can work.

    Every other provider is asked for a fraction of a cent of work in one request. AssemblyAI
    transcribes, so its probe needs AUDIO, and there is none lying around on a fresh install.
    """

    def test_it_is_a_readable_wav(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "probe.wav")
            with open(p, "wb") as f:
                f.write(S.probe_clip())
            off, rate, frames = S.wav_layout(p)
            self.assertEqual(off, 44)
            self.assertEqual(rate, 16000)
            self.assertEqual(frames, 16000)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_it_is_exactly_one_second(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "probe.wav")
            with open(p, "wb") as f:
                f.write(S.probe_clip())
            self.assertEqual(S.length_ms(p), 1000)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_it_is_sound_rather_than_silence(self):
        # Both work today. Silence is indistinguishable from a broken encoder, and the day a
        # provider starts rejecting empty audio the failure would look exactly like a dead key.
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "probe.wav")
            with open(p, "wb") as f:
                f.write(S.probe_clip())
            samples, _ = S.read_samples(p)
            self.assertGreater(max(abs(v) for v in samples), 1000)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_it_does_not_clip(self):
        # A probe that arrives distorted is a probe that invites a different explanation for a
        # failure than the one that happened.
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "probe.wav")
            with open(p, "wb") as f:
                f.write(S.probe_clip())
            samples, _ = S.read_samples(p)
            self.assertLess(max(abs(v) for v in samples), 32000)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_it_is_the_same_every_time(self):
        # A probe that differs run to run is one that cannot be compared with a previous run.
        self.assertEqual(S.probe_clip(), S.probe_clip())

    def test_it_is_the_manifest_fixture_byte_for_byte(self):
        # THE DIGEST IS THE POINT OF THE FIXTURE. Four apps in three languages each rolling their
        # own tone is four slightly different files, and the day two of them disagreed about what
        # a probe failure meant there would be no way to say which was right.
        #
        # MANTRA_MANIFEST/fixtures/probe-1s-440hz.wav, verified 30.8.2026.
        import hashlib
        self.assertEqual(
            hashlib.sha256(S.probe_clip()).hexdigest(),
            "9e2c610d9b40fbfe83c6de65590d815834bfd2669e493c58ec526874222ec545",
        )
        self.assertEqual(len(S.probe_clip()), 32_044)

    def test_it_is_small_enough_to_upload_in_a_moment(self):
        self.assertLess(len(S.probe_clip()), 64 * 1024)


class Spend(unittest.TestCase):
    """
    The log is the box and the box is the log. A running total kept beside it is a number that can
    disagree with the lines it came from, and the day it does there is no way to tell which lies.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old_spend, self.old_rates = S.SPEND_FILE, S.RATES_FILE
        S.SPEND_FILE = os.path.join(self.dir, "spend.jsonl")
        S.RATES_FILE = os.path.join(self.dir, "rates.json")
        S.APPDIR = self.dir

    def tearDown(self):
        S.SPEND_FILE, S.RATES_FILE = self.old_spend, self.old_rates
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_nothing_logged_is_nothing_spent(self):
        per, money = S.spend_totals()
        self.assertEqual(per, {})
        self.assertEqual(money, 0.0)

    def test_a_call_is_one_line(self):
        S.log_spend("speechify", 120, "Danas je lijep dan")
        self.assertEqual(len(S.spend_rows()), 1)

    def test_units_add_up_per_provider(self):
        S.log_spend("speechify", 100, "a")
        S.log_spend("speechify", 50, "b")
        S.log_spend("hume", 3.5, "c")
        per, _ = S.spend_totals()
        self.assertEqual(per["speechify"]["units"], 150)
        self.assertEqual(per["speechify"]["calls"], 2)
        self.assertEqual(per["hume"]["units"], 3.5)

    def test_each_provider_is_counted_in_what_it_bills(self):
        # Speechify and Hume both bill CHARACTERS — Hume's pricing page is in dollars per thousand
        # of them — so they share a unit. AssemblyAI bills by audio duration and must not be added
        # to either: seconds and characters in one total is a number that means nothing.
        S.log_spend("speechify", 100, "a")
        S.log_spend("hume", 10, "b")
        S.log_spend("assemblyai", 30, "c")
        per, _ = S.spend_totals()
        self.assertEqual(per["speechify"]["unit"], per["hume"]["unit"])
        self.assertNotEqual(per["assemblyai"]["unit"], per["hume"]["unit"])

    def test_a_throttle_is_not_read_as_an_empty_account(self):
        # Gemini answers both with 429 RESOURCE_EXHAUSTED. The one that says how long to wait is
        # saying come back, not pay up — and reading it wrongly would have somebody delete a live
        # key because they pressed Test twice in a second.
        throttled = b'{"error":{"status":"RESOURCE_EXHAUSTED","details":[{"@type":"RetryInfo",\
"retryDelay":"31s"}]}}'
        spent = b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"Your prepayment credits \
are depleted."}}'
        self.assertFalse(S.sounds_like_money(throttled))
        self.assertTrue(S.sounds_like_money(spent))

    def test_the_hume_and_anthropic_wordings_are_both_recognised(self):
        self.assertTrue(S.sounds_like_money(b'{"code":"E0300","message":"Exhausted credit balance"}'))
        self.assertTrue(S.sounds_like_money(b'{"error":{"message":"credit balance is too low"}}'))

    def test_an_ordinary_failure_is_not_a_money_failure(self):
        self.assertFalse(S.sounds_like_money(b"404 page not found"))
        self.assertFalse(S.sounds_like_money(b'{"error":"invalid api key"}'))
        self.assertFalse(S.sounds_like_money(b""))

    def test_money_is_zero_until_a_rate_is_entered(self):
        S.log_spend("speechify", 1000, "a")
        _, money = S.spend_totals()
        self.assertEqual(money, 0.0)

    def test_money_appears_once_a_rate_is_entered(self):
        S.log_spend("speechify", 1000, "a")
        with open(S.RATES_FILE, "w") as f:
            json.dump({"speechify": 0.00002}, f)
        per, money = S.spend_totals()
        self.assertAlmostEqual(per["speechify"]["cost"], 0.02, places=4)
        self.assertAlmostEqual(money, 0.02, places=4)

    def test_a_zero_call_is_not_logged(self):
        # A refused call bills nothing, and a row saying zero is a row that has to be read to
        # discover it says nothing.
        S.log_spend("hume", 0, "refused")
        self.assertEqual(S.spend_rows(), [])

    def test_a_torn_last_line_does_not_take_the_file_down(self):
        S.log_spend("speechify", 100, "good")
        with open(S.SPEND_FILE, "a") as f:
            f.write('{"at": 1, "provider": "hu')
        self.assertEqual(len(S.spend_rows()), 1)

    def test_the_log_holds_no_key_and_no_account(self):
        # What was spent is a fact about the work. Which of twenty-one accounts paid for it is not
        # something a file that grows for months needs to hold.
        S.log_spend("hume", 2, "Danas je lijep dan")
        row = S.spend_rows()[0]
        self.assertEqual(sorted(row.keys()), ["at", "detail", "provider", "units"])

    def test_the_detail_is_capped(self):
        S.log_spend("speechify", 10, "x" * 500)
        self.assertLessEqual(len(S.spend_rows()[0]["detail"]), 80)

    def test_clearing_empties_the_box_by_arithmetic(self):
        S.log_spend("speechify", 100, "a")
        os.remove(S.SPEND_FILE)
        per, money = S.spend_totals()
        self.assertEqual(per, {})
        self.assertEqual(money, 0.0)

    def test_a_corrupt_rates_file_falls_back_rather_than_raising(self):
        with open(S.RATES_FILE, "w") as f:
            f.write("not json at all")
        self.assertEqual(S.rates(), S.DEFAULT_RATES)


class Text(unittest.TestCase):
    def test_newlines_become_spaces(self):
        # A voice reads a line break as nothing at all, so a paragraph broken across lines
        # arrives as "the end ofone line".
        self.assertEqual(S.clean_text("one\ntwo\r\nthree"), "one two three")

    def test_a_byte_order_mark_is_not_read_aloud(self):
        self.assertEqual(S.clean_text("\ufeffDanas"), "Danas")

    def test_runs_of_space_collapse_and_ends_are_trimmed(self):
        self.assertEqual(S.clean_text("   a     b   "), "a b")

    def test_a_non_breaking_space_is_a_space(self):
        self.assertEqual(S.clean_text("a\u00a0b"), "a b")

    def test_nothing_readable_yields_nothing(self):
        self.assertEqual(S.clean_text("   \n\n  "), "")

    def test_a_long_file_is_cut_at_a_sentence(self):
        out = S.clean_text("This is a sentence. " * 300)
        self.assertLessEqual(len(out), S.MAX_TEXT)
        self.assertTrue(out.endswith("."))

    def test_with_no_sentence_it_is_cut_at_a_space(self):
        out = S.clean_text("word " * 1000)
        self.assertLessEqual(len(out), S.MAX_TEXT)
        self.assertFalse(out.endswith("wor"))

    def test_one_enormous_word_is_cut_rather_than_refused(self):
        self.assertEqual(len(S.clean_text("x" * 5000)), S.MAX_TEXT)


class Tags(unittest.TestCase):
    """
    Inline emotion tags. A line that begins calm and turns furious halfway is the ordinary case,
    and a single direction for a whole utterance cannot express it.
    """

    def test_a_line_with_no_tags_is_one_piece_with_no_direction(self):
        self.assertEqual(S.segment("Danas je lijep dan."), [("Danas je lijep dan.", "")])

    def test_a_tag_directs_everything_after_it(self):
        out = S.segment("quietly <angry> and then not")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][0], "quietly")
        self.assertEqual(out[0][1], "")
        self.assertEqual(out[1][0], "and then not")
        self.assertIn("angry", out[1][1])

    def test_text_before_the_first_tag_keeps_no_direction(self):
        # Inheriting backwards would make a line angry from the start when it turns angry halfway.
        out = S.segment("plain <furious> loud")
        self.assertEqual(out[0][1], "")

    def test_several_tags_give_several_pieces(self):
        out = S.segment("<calm> one <angry> two <sad> three")
        self.assertEqual([p[0] for p in out], ["one", "two", "three"])
        self.assertEqual(len({p[1] for p in out}), 3)

    def test_a_tag_at_the_very_start_directs_the_whole_line(self):
        out = S.segment("<whispered> all of it")
        self.assertEqual(len(out), 1)
        self.assertIn("whisper", out[0][1])

    def test_an_unknown_tag_is_left_in_the_text_rather_than_swallowed(self):
        # More likely a misspelling than an instruction, and a voice reading it aloud is a bug you
        # can see, where dropping it silently is one you cannot.
        out = S.segment("hello <notanemotion> world")
        self.assertEqual(len(out), 1)
        self.assertIn("notanemotion", out[0][0])

    def test_empty_pieces_are_not_sent(self):
        out = S.segment("<angry><sad> only this")
        self.assertEqual([p[0] for p in out], ["only this"])

    def test_strip_tags_removes_the_known_ones_only(self):
        self.assertEqual(S.strip_tags("a <angry> b"), "a b")
        self.assertEqual(S.strip_tags("a <notanemotion> b"), "a <notanemotion> b")

    def test_strip_tags_leaves_one_space_where_a_tag_was(self):
        self.assertEqual(S.strip_tags("<calm>   spaced   out  "), "spaced out")

    def test_tags_are_case_blind(self):
        self.assertEqual(len(S.segment("a <ANGRY> b")), 2)


class Emotions(unittest.TestCase):
    def test_the_built_in_set_is_a_real_starting_point(self):
        self.assertGreaterEqual(len(S.BUILT_IN_EMOTIONS), 20)

    def test_every_built_in_has_a_name_a_glyph_and_prose(self):
        for e in S.BUILT_IN_EMOTIONS:
            self.assertTrue(e["label"] and e["label"] == e["label"].lower())
            self.assertEqual(len(e["glyph"]), 1)
            self.assertGreater(len(e["text"]), 8)

    def test_no_two_share_a_name_or_a_glyph(self):
        labels = [e["label"] for e in S.BUILT_IN_EMOTIONS]
        glyphs = [e["glyph"] for e in S.BUILT_IN_EMOTIONS]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(len(glyphs), len(set(glyphs)))

    def test_a_label_can_be_written_as_a_tag(self):
        # It becomes <label> inside the line, so it cannot contain the brackets that delimit it.
        for e in S.BUILT_IN_EMOTIONS:
            self.assertNotIn("<", e["label"])
            self.assertNotIn(">", e["label"])


class Slug(unittest.TestCase):
    """A download named after what it says, because thirty cell-NN files cannot be told apart."""

    def test_the_line_becomes_the_name(self):
        self.assertEqual(S.slugify("Danas je lijep dan.", "cell-01"), "Danas je lijep dan")

    def test_nothing_said_falls_back_to_the_number(self):
        self.assertEqual(S.slugify("", "cell-03"), "cell-03")
        self.assertEqual(S.slugify("   ", "cell-03"), "cell-03")

    def test_characters_a_filesystem_argues_with_are_removed(self):
        out = S.slugify('a/b\\c:d*e?f"g<h>i|j', "x")
        for ch in '/\\:*?"<>|':
            self.assertNotIn(ch, out)

    def test_spaces_are_kept_because_this_goes_on_a_timeline(self):
        self.assertIn(" ", S.slugify("two words", "x"))

    def test_it_is_cut_at_a_word(self):
        out = S.slugify("word " * 40, "x")
        self.assertLessEqual(len(out), 80)
        self.assertFalse(out.endswith("wor"))

    def test_a_leading_dot_cannot_make_a_hidden_file(self):
        self.assertFalse(S.slugify("...hidden", "x").startswith("."))


class Waveform(unittest.TestCase):
    def test_it_returns_the_number_of_buckets_asked_for(self):
        for n in (64, 128, 256, 512):
            self.assertEqual(len(S.waveform(list(range(9000)), n)), n)

    def test_nothing_in_gives_nothing_out(self):
        self.assertEqual(S.waveform([], 256), [])
        self.assertEqual(S.waveform([1, 2, 3], 0), [])

    def test_the_values_are_a_fraction_of_full_scale(self):
        wf = S.waveform([32767] * 1000, 10)
        self.assertTrue(all(0 <= v <= 1 for v in wf))
        self.assertAlmostEqual(max(wf), 1.0, places=3)

    def test_a_signal_shorter_than_the_buckets_does_not_crash(self):
        self.assertEqual(len(S.waveform([100, 200], 256)), 256)


# ─────────────────────────────────────────────────────────── voice transform ──

def bursts(rate, total, spans, amp=8000, freq=180.0, noise=40):
    """Speech-shaped enough for edges: a voiced tone inside each span, faint noise everywhere else.
    Deterministic noise, so a failure reproduces."""
    import math
    out = []
    seed = 12345
    for k in range(int(total * rate)):
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        v = (seed % (2 * noise + 1)) - noise
        t = k / rate
        if any(a <= t < b for a, b in spans):
            v += int(amp * math.sin(2 * math.pi * freq * t))
        out.append(max(-32768, min(32767, v)))
    return out


class Plan(unittest.TestCase):
    """The plan that lays their words onto his. Its invariants are what lip sync rests on."""

    def check_invariants(self, segs, n, total):
        seen = [w for s in segs for w in s["words"]]
        self.assertEqual(seen, list(range(n)), "every word once, in order")
        end = 0.0
        for s in segs:
            t0, t1 = s["dst"]
            self.assertGreaterEqual(t0, end - 1e-9, "segments never overlap")
            self.assertGreater(t1, t0)
            self.assertLessEqual(t1, total + 1e-9)
            end = t1

    def test_clean_ratios_are_left_exactly_where_he_said_them(self):
        his = [(0.10, 0.40), (0.60, 0.90), (1.20, 1.50)]
        theirs = [(0.05, 0.33), (0.40, 0.70), (0.90, 1.18)]
        segs = S.plan_stretch(his, theirs, 2.0, 1.5)
        self.assertEqual([s["dst"] for s in segs], his)
        self.assertEqual({s["level"] for s in segs}, {"word"})
        self.assertEqual({s["verdict"] for s in segs}, {"ok"})

    def test_a_long_word_of_his_lets_its_tail_go_silent_rather_than_smear(self):
        # his word 0.60 s, theirs 0.30 s: 2.0x. A pause follows. The onset stays; the tail absorbs.
        segs = S.plan_stretch([(0.20, 0.80)], [(0.10, 0.40)], 2.0, 1.0)
        self.assertEqual(segs[0]["dst"][0], 0.20, "the onset is his")
        self.assertAlmostEqual(segs[0]["ratio"], 1.30, places=2)
        self.assertEqual(segs[0]["verdict"], "ok")

    def test_a_word_rescued_exactly_to_a_limit_is_called_ok(self):
        # Measured 11.9.2026 through the route: "I" was borrowed up to exactly 0.75 and reported as a
        # chirp, because floating point landed a hair under the limit. Swept, so no lucky pair hides it.
        wrong = []
        for k in range(200):
            src = 0.20 + k * 0.0017
            for his in (src * 0.5, src * 2.4):               # one that borrows, one that absorbs
                seg = S.plan_stretch([(0.8, 0.8 + his)], [(0.0, src)], 5.0, 5.0)[0]
                need = src * S.CHIRP - his if his < src else his - src * S.SMEAR
                rescuable = need <= S.ABSORB
                if (seg["verdict"] == "ok") != rescuable:    # rescued is ok; beyond 300 ms it must say so
                    wrong.append((round(src, 4), round(his, 4), seg["ratio"], seg["verdict"]))
        self.assertEqual(wrong, [], "%d boundary cases misreported, first %s" % (len(wrong), wrong[:2]))

    def test_absorbing_stops_at_300_ms_and_then_says_smear(self):
        # 1.00 s against 0.25 s is 4x: 300 ms cannot fix it, and the verdict must not claim ok
        segs = S.plan_stretch([(0.0, 1.0)], [(0.0, 0.25)], 2.0, 1.0)
        self.assertAlmostEqual(segs[0]["dst"][1], 0.70, places=3)
        self.assertEqual(segs[0]["verdict"], "smear")

    def test_a_short_word_borrows_the_pause_after_it(self):
        segs = S.plan_stretch([(0.20, 0.35), (0.80, 1.10)], [(0.10, 0.40), (0.50, 0.80)], 2.0, 1.0)
        self.assertEqual(segs[0]["dst"][0], 0.20, "borrowed from after, so the onset did not move")
        self.assertAlmostEqual(segs[0]["ratio"], 0.75, places=2)
        self.assertEqual(segs[0]["verdict"], "ok")

    def test_a_short_word_with_little_pause_after_starts_at_most_50_ms_early(self):
        # The next word is exactly JOIN_GAP away, so the two cannot become a phrase, and the 80 ms
        # after is all the room there is behind. The rest has to come from before, and at most 50 ms
        # of it. (The first version of this test put the next word flush against it; the two then
        # joined into a phrase and the 50 ms rule was never reached, so the test passed with the
        # rule deleted. Found by deleting the rule, 11.9.2026.)
        his = [(0.50, 0.60), (0.68, 0.98)]
        theirs = [(0.00, 0.60), (0.60, 0.90)]
        segs = S.plan_stretch(his, theirs, 2.0, 1.0)
        self.assertEqual(segs[0]["words"], [0], "no phrase: the rule under test is reached")
        self.assertAlmostEqual(segs[0]["dst"][0], 0.45, places=6)
        self.assertAlmostEqual(segs[0]["dst"][1], 0.68, places=6)
        self.check_invariants(segs, 2, 2.0)

    def test_a_word_he_ran_into_its_neighbour_is_stretched_as_a_phrase(self):
        # word 0 is 3x, word 1 is 0.5x, with no gap: alone both fail, together 1.0x
        his = [(0.00, 0.30), (0.30, 0.40)]
        theirs = [(0.00, 0.10), (0.10, 0.30)]
        segs = S.plan_stretch(his, theirs, 0.40, 0.30)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["level"], "phrase")
        self.assertEqual(segs[0]["words"], [0, 1])
        self.assertEqual(segs[0]["verdict"], "ok")

    def test_a_clean_word_lends_room_to_an_extreme_word_after_it(self):
        his = [(0.00, 0.40), (0.40, 0.45)]          # the second word he clipped very short
        theirs = [(0.00, 0.30), (0.30, 0.45)]
        segs = S.plan_stretch(his, theirs, 0.45, 0.45)
        self.assertEqual(segs[0]["words"], [0, 1])
        self.assertEqual(segs[0]["verdict"], "ok")

    def test_words_separated_by_a_breath_are_never_joined(self):
        his = [(0.00, 0.30), (0.60, 0.70)]          # a 300 ms pause between them
        theirs = [(0.00, 0.10), (0.10, 0.30)]
        segs = S.plan_stretch(his, theirs, 1.0, 0.30)
        self.assertEqual(len(segs), 2)
        self.assertEqual({s["level"] for s in segs}, {"word"})

    def test_joining_that_would_not_help_is_refused(self):
        # both words are 3x and run together: joining leaves it 3x, so they stay two words
        segs = S.plan_stretch([(0.0, 0.3), (0.3, 0.6)], [(0.0, 0.1), (0.1, 0.2)], 1.0, 0.2)
        self.assertEqual(len(segs), 2)

    def test_whisper_nonsense_is_cleaned_rather_than_believed(self):
        his = [(0.5, 0.4), (0.3, 0.9), (0.8, 5.0)]    # backwards, overlapping, past the end
        theirs = [(0.0, 0.0), (0.2, 0.1), (0.3, 0.6)]
        segs = S.plan_stretch(his, theirs, 1.0, 0.6)
        self.check_invariants(segs, 3, 1.0)
        self.assertTrue(all(s["ratio"] > 0 for s in segs))

    def test_nothing_in_gives_nothing_out(self):
        self.assertEqual(S.plan_stretch([], [], 1.0, 1.0), [])
        self.assertEqual(S.plan_stretch([(0, 1)], [], 1.0, 1.0), [])

    def test_a_long_line_keeps_every_invariant(self):
        import random
        rnd = random.Random(7)
        his, theirs, a, b = [], [], 0.0, 0.0
        for _ in range(60):
            a += rnd.uniform(0.0, 0.25); d = rnd.uniform(0.08, 0.6); his.append((a, a + d)); a += d
            b += rnd.uniform(0.0, 0.15); e = rnd.uniform(0.08, 0.6); theirs.append((b, b + e)); b += e
        segs = S.plan_stretch(his, theirs, a + 0.5, b + 0.5)
        self.check_invariants(segs, 60, a + 0.5)


class Snap(unittest.TestCase):
    RATE = 16000

    def test_loose_whisper_edges_move_onto_the_sound(self):
        true = [(0.30, 0.62), (0.90, 1.25)]
        sig = bursts(self.RATE, 1.6, true)
        loose = [(0.34, 0.58), (0.86, 1.29)]         # 40 ms out each way, as Whisper is
        got = S.snap_spans(sig, self.RATE, loose)
        for (a, b), (c, d) in zip(got, true):
            self.assertLessEqual(abs(a - c), 0.011, "start within one frame")
            self.assertLessEqual(abs(b - d), 0.011, "end within one frame")

    def test_an_edge_with_nothing_loud_near_it_stays_put(self):
        sig = bursts(self.RATE, 2.0, [(0.30, 0.60)])
        got = S.snap_spans(sig, self.RATE, [(0.30, 0.60), (1.40, 1.60)])
        self.assertEqual(got[1], (1.40, 1.60))

    def test_it_never_returns_a_span_that_ends_before_it_starts(self):
        sig = bursts(self.RATE, 1.0, [(0.1, 0.9)])  # one long sound, words run straight through
        got = S.snap_spans(sig, self.RATE, [(0.1, 0.3), (0.3, 0.6), (0.6, 0.9)])
        for a, b in got:
            self.assertGreater(b, a)

    def test_silence_or_nothing_does_not_crash(self):
        self.assertEqual(S.snap_spans([], self.RATE, [(0, 1)]), [(0, 1)])
        self.assertEqual(len(S.snap_spans([0] * 16000, self.RATE, [(0.2, 0.5)])), 1)


class Consent(unittest.TestCase):
    TODAY = "2026-09-11"
    GOOD = {"who": "Manan Periwal", "when": "2026-09-10", "what_for": "the brain brake film", "usage": "public"}

    def test_a_complete_note_passes(self):
        self.assertIsNone(S.consent_problem(self.GOOD, self.TODAY))

    def test_each_missing_part_is_named(self):
        for field, words in (("who", "who"), ("what_for", "what"), ("usage", "public or private")):
            c = dict(self.GOOD); c[field] = "  " if field != "usage" else ""
            self.assertIn(words, S.consent_problem(c, self.TODAY))

    def test_usage_is_one_of_two_words_and_nothing_else(self):
        for bad in ("Public", "maybe", "film only", None):
            c = dict(self.GOOD); c["usage"] = bad
            self.assertIsNotNone(S.consent_problem(c, self.TODAY))

    def test_permission_cannot_be_dated_tomorrow(self):
        c = dict(self.GOOD); c["when"] = "2026-09-12"
        self.assertIn("future", S.consent_problem(c, self.TODAY))

    def test_an_empty_date_means_today_and_is_written_as_today(self):
        c = dict(self.GOOD); c["when"] = ""
        self.assertIsNone(S.consent_problem(c, self.TODAY))
        self.assertEqual(S.consent_record(c, self.TODAY)["when"], self.TODAY)

    def test_the_record_keeps_four_fields_and_drops_the_rest(self):
        c = dict(self.GOOD, extra="x", who="  Manan   Periwal ")
        rec = S.consent_record(c, self.TODAY)
        self.assertEqual(set(rec), {"who", "when", "what_for", "usage"})
        self.assertEqual(rec["who"], "Manan Periwal")


class Badge(unittest.TestCase):
    def test_a_voice_from_before_consent_notes_is_not_releasable(self):
        b = S.voice_badge({"name": "voice1", "source": "/x.wav"})
        self.assertEqual((b["usage"], b["release"]), ("none", False))

    def test_public_and_private(self):
        c = dict(Consent.GOOD)
        self.assertEqual(S.voice_badge({"consent": c})["usage"], "public")
        c["usage"] = "private"
        b = S.voice_badge({"consent": c})
        self.assertEqual((b["usage"], b["release"]), ("private", False))

    def test_a_half_written_note_is_no_note(self):
        self.assertEqual(S.voice_badge({"consent": {"usage": "public"}})["usage"], "none")

    def test_the_stricter_word_always_wins(self):
        self.assertEqual(S.stricter("public", "private"), "private")
        self.assertEqual(S.stricter("private", "public"), "private")
        self.assertEqual(S.stricter("public", "none"), "none")
        self.assertEqual(S.stricter("public", None), "public", "unreachable: the snapshot stands")
        self.assertEqual(S.stricter("garbage", "public"), "none")


class ReleaseName(unittest.TestCase):
    """The warning that reaches the Resolve bin, because the file name is all that is seen there."""

    def setUp(self):
        self.saved = S.voice_api

    def tearDown(self):
        S.voice_api = self.saved

    def meta(self, usage):
        return {"voice": "transform-mira", "transform_voice": "mira", "transform_usage": usage}

    def test_a_private_take_says_so_in_its_name(self):
        S.voice_api = lambda *a, **k: (None, "not running")
        self.assertIn("PRIVATE", S.release_suffix(self.meta("private"), "/x/gen/transform-mira.wav"))

    def test_a_public_take_made_private_later_is_named_private(self):
        c = dict(Consent.GOOD, usage="private")
        S.voice_api = lambda *a, **k: ({"voices": [{"name": "mira", "consent": c}]}, "")
        self.assertIn("PRIVATE", S.release_suffix(self.meta("public"), "/x/gen/transform-mira.wav"))

    def test_a_public_take_stays_public(self):
        S.voice_api = lambda *a, **k: ({"voices": [{"name": "mira", "consent": Consent.GOOD}]}, "")
        self.assertNotIn("PRIVATE", S.release_suffix(self.meta("public"), "/x/gen/transform-mira.wav"))

    def test_an_engine_take_or_his_own_recording_gets_no_suffix(self):
        S.voice_api = lambda *a, **k: self.fail("no lookup is needed for these")
        self.assertEqual(S.release_suffix({"voice": "speechify"}, "/x/gen/speechify.wav"), "")
        self.assertEqual(S.release_suffix(self.meta("private"), "/x/original.wav"), "")


class GeneratedList(unittest.TestCase):
    def test_finder_and_half_written_files_are_not_voices(self):
        d = tempfile.mkdtemp()
        for name in (".DS_Store", "hume.wav", "speechify.wav.tmp", "transform-mira.wav", "._hume.wav"):
            open(os.path.join(d, name), "wb").close()
        self.assertEqual(S.generated_voices(d), ["hume", "transform-mira"])
        self.assertEqual(S.generated_voices(os.path.join(d, "absent")), [])
        shutil.rmtree(d)


class Stretch(unittest.TestCase):
    def test_atempo_below_its_floor_is_chained(self):
        f = S.stretch_filter(0.3, False)
        self.assertTrue(f.startswith("atempo=0.5,"))
        product = 1.0
        for part in f.split(","):
            product *= float(part.split("=")[1])
        self.assertAlmostEqual(product, 0.3, places=5)

    def test_rubberband_is_asked_for_by_tempo(self):
        self.assertIn("tempo=1.250000", S.stretch_filter(1.25, True))

    def test_the_engine_name_cannot_become_a_path(self):
        self.assertEqual(S.engine_for("../../original"), "transform-______original")
        S.generated("p", 0, S.engine_for("../x"))   # does not raise


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed here")
class RenderAgainstTheClock(unittest.TestCase):
    """
    NOT A MOCK OF THE MODEL, A MEASUREMENT OF THE RENDERER. Their "words" are tone bursts at known
    times, his windows are other known times, and the rendered track is read back and every onset
    and offset found in it is compared with where he said the word. This is the lip sync claim at
    the level of the mechanism: given correct word times, where does the sound land.
    """

    def test_every_word_lands_on_his_timing(self):
        rate = 44100
        d = tempfile.mkdtemp()
        theirs_spans = [(0.10, 0.38), (0.55, 0.90), (1.05, 1.25), (1.40, 1.80)]
        his_spans = [(0.30, 0.62), (0.80, 1.05), (1.60, 1.84), (2.10, 2.60)]
        their_wav = os.path.join(d, "theirs.wav")
        S.write_wav(their_wav, bursts(rate, 2.0, theirs_spans), rate)
        segs = S.plan_stretch(his_spans, theirs_spans, 3.0, 2.0)
        track, filt, why = S.render_plan(shutil.which("ffmpeg"), their_wav, 2.0, segs, 3 * rate, rate)
        self.assertEqual(why, "")
        self.assertEqual(len(track), 3 * rate, "exactly as long as his take")
        found = S.snap_spans(track, rate, [s["dst"] for s in segs])
        worst = 0.0
        for s, (a, b) in zip(segs, found):
            worst = max(worst, abs(a - s["dst"][0]), abs(b - s["dst"][1]))
        print("\n      renderer %s: worst edge error %.1f ms over %d segments" % (filt, worst * 1000, len(segs)))
        self.assertLessEqual(worst, 0.015)
        shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
