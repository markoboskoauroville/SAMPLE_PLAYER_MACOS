# CLAUDE.md — Sample Player, macOS

Loaded by Claude Code at launch in this folder. Short on purpose: the rules live in the manifest, and
the unfinished work lives in one brief.

## THE UNFINISHED WORK

**[`CLAUDE_CODE_FINISH.md`](CLAUDE_CODE_FINISH.md) is the brief.** While it has an unticked box, that
is the job. Tick a box in the file and commit when a step is done and its result is written down, so a
new session knows where to continue. When every box is ticked, say so to Baba and delete nothing.

## THE NETWORK

**Baba is often on a corporate network where outbound SSH on port 22 is blocked.** Anything that uses
`ssh` to the Oracle machine will time out there. The brief's Part 0.3 measures what gets through and
Part 4.0 sets up a route; do not start Oracle work before both are done, and ask Baba before carrying
SSH through the company's network in any form.

## BEFORE ANYTHING

Read `~/Developer/MANTRA_MANIFEST/START_HERE.md` and the modules it routes you to. Always:
`secrets.md`, `four-tests.md`, `checking-the-checks.md`. For this work also `voice-clone.md`,
`free-machine.md`, `delivery-gate.md`, `download-monitor.md`.

## ON EVERY CHANGE

    python3 tests/test_server.py        138 cases at v3.3 (135 at v3.2)
    python3 scripts/gates.py            57 checks at v3.3 (55 at v3.2), 2 honestly not run

Run them with `PYTHONDONTWRITEBYTECODE=1`. A red gate is read, not obeyed: three times out of four the
check was wrong and the code was right, and the fix belongs in the check with the reason above it. A
new test is not believed until it has been seen failing on the old code.

## HOW BABA WORKS

- **He dictates and has low vision.** Plain sentences, short, one question at a time. No tables of
  options: say what you recommend and why, then ask yes or no.
- **Measure, do not assume.** If you are about to write down a fact about an API, a machine or a
  price, call it or read the provider's own page on the day.
- **Correct a document in place**, quoting the old wording with the date. Never a second version below.
- **Secrets are never printed**, not in a command, a log, a commit or a message. Keys live in
  `~/Developer/api/`. Length and first four characters only.
- **A local engine needs no key, no credit probe and no spend line.**
- **Ask before:** tunnelling SSH through the company network, restarting or resizing the Oracle machine, anything that costs money, writing
  anybody's consent note (the words are his), deleting anything, and pushing to `main` or `master`.
  **Baba, 11.9.2026: the brief, its log and the records (`CLAUDE_CODE_FINISH.md`, `DELIVERY_RECORD.md`,
  `HANDOFF.md`, `DEVELOPMENT.md`, `CLAUDE.md`) may be pushed without asking. Any change to `server.py`,
  `static/index.html`, the installer or `update.sh` still needs his yes before it is pushed.**
- **SSH through the company network is not allowed** (Baba, 11.9.2026): no tunnel, no Cloudflare SSH
  route. Anything that needs a shell on the Oracle machine waits for his phone hotspot or home, and is
  kept ready as the list under 4.0 in the brief so it runs the moment port 22 answers.
- **Never create a second Oracle machine, not even for a test** (Baba, 11.9.2026). At 4 OCPUs and 24 GB
  the one machine uses almost the whole free allowance of a paid tenancy; a test machine for a day goes over it.
- **Do not touch** `MANTRA_MANIFEST/EXCHANGE.md` or anything belonging to THE BRAIN BRAKE.
