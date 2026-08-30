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


if __name__ == "__main__":
    unittest.main(verbosity=2)
