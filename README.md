# soundvibes

Live speech-to-text for **both** sides of a conversation: your microphone (`MIC`)
and whatever your computer is playing (`SYS`). Every utterance is transcribed as
it happens and appended to a text file. Language is auto-detected per utterance
and constrained to the ones you allow — **English, German and Russian** by default.

Transcription runs locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper);
no audio leaves the machine and no API key is needed.

## Install

```bash
cd soundvibes
./setup.sh
```

This creates `.venv/` and installs `numpy`, `sounddevice`, `soxr` and
`faster-whisper`. The whisper model itself is downloaded on first run
(`small` ≈ 500 MB, cached in `~/.cache/huggingface`).

## Run

```bash
./.venv/bin/python soundvibes.py --list-devices        # see what can be captured
./.venv/bin/python soundvibes.py                       # start transcribing
```

Transcript goes to `transcripts/transcript.txt` (appended, flushed after every
line — killing the process never loses what was already written). Stop with Ctrl-C.

```
===== soundvibes session started 2026-08-08 18:35:13 =====
[18:35:14] [MIC] [en] The quick brown fox jumps over the lazy dog every morning.
[18:35:18] [SYS] [de] Guten Tag, dies ist ein deutscher Testsatz für die Spracherkennung.
[18:35:20] [MIC] [ru] Добрый день, это тестовое предложение для распознавания речи.
```

## Capturing system audio on macOS

macOS cannot record its own output without a virtual audio driver. Microphone
capture works out of the box; for `SYS` you need a loopback device:

```bash
brew install blackhole-2ch
```

Then open **Audio MIDI Setup** → **+** → **Create Multi-Output Device**, tick both
your speakers **and** BlackHole 2ch, and select that as the system output. This way
you still *hear* the audio while soundvibes transcribes it. (Selecting BlackHole
directly as the output also works, but then you hear nothing.)

soundvibes finds the loopback input automatically — BlackHole, Soundflower,
Loopback, VB-Cable, aggregate/multi-output devices and PulseAudio monitors are all
recognised. Override with `--system-device "BlackHole"`. If no loopback is found it
prints setup instructions and carries on with the microphone alone.

On the first run macOS will ask for microphone permission for your terminal
(System Settings → Privacy & Security → Microphone).

## Useful options

| Option | What it does |
| --- | --- |
| `-o PATH` | transcript file (default `transcripts/transcript.txt`) |
| `--languages en,de,ru` | languages to allow; detection is forced into this set |
| `--split-by-language` | *also* write `transcript.en.txt`, `transcript.de.txt`, `transcript.ru.txt` |
| `--format jsonl` | one JSON object per line instead of plain text |
| `--model small` | `tiny`/`base`/`small`/`medium`/`large-v3` — bigger is better and slower |
| `--input-device`, `--system-device` | pick devices by index or partial name |
| `--no-mic`, `--no-system` | capture only one side |
| `--silence 0.7` | seconds of silence that end an utterance |
| `--sensitivity 3.0` | speech threshold as a multiple of the noise floor (lower = more sensitive) |
| `--quiet` | do not echo lines to the console |

Tips:

- On Apple Silicon `--model small` transcribes roughly in real time on CPU. Use
  `--model tiny` for a slow machine, `--model medium` for accuracy if you can spare
  the latency.
- Pinning a single language (`--languages de`) skips detection entirely and is both
  faster and more accurate when you know what will be spoken.
- If quiet speech is missed, lower `--sensitivity` to ~2.0; if background noise
  triggers empty lines, raise it to ~4.0.

## How it works

```
mic device ─┐                             ┌─ energy endpointer ─┐
            ├─ 16 kHz mono (soxr resample)┤                     ├─ faster-whisper ─ transcript file
loopback  ──┘                             └─ energy endpointer ─┘
```

Lines are appended in the order transcription *finishes*, which with two sources is
not always strictly chronological — a long `SYS` utterance can land after a short
`MIC` one that started later. Every line carries its own start timestamp, so
`sort` (or the `timestamp` field in `--format jsonl`) restores the true order. This
is deliberate: buffering to enforce ordering would add latency to a live transcript.

Each source runs its own capture thread with an independent adaptive noise floor,
so a loud speaker output does not desensitise the microphone. Utterances are cut on
~0.7 s of silence (max 20 s) and queued to a single transcription thread. Whisper's
own VAD filter and a no-speech/low-confidence check drop the "Thank you." style
hallucinations it produces on silence and music.

## Self-test

`selftest.py` synthesises English, German and Russian speech with the macOS `say`
command and drives the real pipeline classes — no microphone involved:

```bash
./.venv/bin/python selftest.py
```

It asserts that each phrase is transcribed and detected in the right language, and
that the per-language files are written.
