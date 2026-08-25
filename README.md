# soundvibes

Live speech-to-text for **both** sides of a conversation: your microphone (`MIC`)
and whatever your computer is playing (`SYS`). Every utterance is transcribed as
it happens and appended to a text file. Language is auto-detected per utterance
and constrained to the ones you allow — **English, German and Russian** by default.

Transcription runs locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper);
no audio leaves the machine and no API key is needed.

Runs on **macOS and Linux**.

## Install

```bash
cd soundvibes
./setup.sh
```

This creates `.venv/`, installs the dependencies, and tells you what — if
anything — is missing for your platform. The whisper model itself is downloaded
on first run (`small` ≈ 500 MB, cached in `~/.cache/huggingface`).

**Linux** needs one system library that pip cannot provide:

```bash
sudo apt install libportaudio2      # Debian/Ubuntu
sudo dnf install portaudio          # Fedora
sudo pacman -S portaudio            # Arch
```

## Run

```bash
./.venv/bin/python soundvibes.py --list-devices        # see what can be captured
./.venv/bin/python soundvibes.py                       # start transcribing
./.venv/bin/python -m soundvibes                       # identical
```

Transcript goes to `transcripts/transcript.txt` (appended, flushed after every
line — killing the process never loses what was already written). Stop with Ctrl-C.

```
===== soundvibes session started 2026-08-25 13:41:38 =====
[13:41:39] [MIC] [en] The quick brown fox jumps over the lazy dog every morning.
[13:41:41] [SYS] [de] Guten Tag, dies ist ein deutscher Testsatz für die Spracherkennung.
[13:41:44] [MIC] [ru] Добрый день, это тестовое предложение для распознавания речи.
```

## Capturing system audio

Microphone capture works out of the box everywhere. Capturing what the machine
*plays* needs a loopback source, and that differs by platform. soundvibes finds
one automatically where it can, and prints platform-specific instructions when
it cannot.

### macOS

macOS cannot record its own output without a virtual audio driver:

```bash
brew install blackhole-2ch
```

Then open **Audio MIDI Setup** → **+** → **Create Multi-Output Device**, tick both
your speakers **and** BlackHole 2ch, and select that as the system output. This
way you still *hear* the audio while soundvibes transcribes it. (Selecting
BlackHole directly as the output also works, but then you hear nothing.)

### Linux

No extra driver is needed — PulseAudio and PipeWire already expose every sink's
output as a `.monitor` source. It only has to be visible to PortAudio:

```bash
pactl list short sources | grep monitor      # find it
./.venv/bin/python soundvibes.py --system-device monitor
```

If no monitor source appears in `--list-devices`, install the PulseAudio ALSA
plugin (`libasound2-plugins` and `pulseaudio-module-alsa` on Debian/Ubuntu,
`alsa-plugins-pulseaudio` on Fedora) and try again. On a bare-ALSA system without
a sound server, load `snd-aloop` and capture from the loopback device instead.

Monitor sources, BlackHole, Soundflower, Loopback, VB-Cable, aggregate and
multi-output devices are all recognised automatically. Override with
`--system-device "<name or index>"`.

On macOS the first run asks for microphone permission for your terminal
(System Settings → Privacy & Security → Microphone).

## Useful options

| Option | What it does |
| --- | --- |
| `-o PATH` | transcript file (default `transcripts/transcript.txt`) |
| `--languages en,de,ru` | languages to allow; detection is forced into this set |
| `--split-by-language` | *also* write `transcript.en.txt`, `transcript.de.txt`, … |
| `--format jsonl` | one JSON object per line instead of plain text |
| `--model small` | `tiny`/`base`/`small`/`medium`/`large-v3` — bigger is better and slower |
| `--input-device`, `--system-device` | pick devices by index or partial name |
| `--no-mic`, `--no-system` | capture only one side |
| `--silence 0.7` | seconds of silence that end an utterance |
| `--min-speech 0.4` | discard utterances with less speech than this |
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
            ├─ 16 kHz mono (soxr resample)┤                     ├─ whisper ─ transcript
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

## Architecture

```
soundvibes/
├── constants.py      # sample rate, frame size, source labels
├── models.py         # Utterance, TranscriptLine — what flows through the pipeline
├── settings.py       # frozen settings objects, built once from the CLI
├── platforms.py      # macOS / Linux / generic differences
├── devices.py        # AudioBackend seam + DeviceRegistry
├── capture.py        # AudioPreprocessor, FrameSplitter, AudioSource thread
├── endpointing.py    # SpeechEndpointer (energy VAD)
├── transcription.py  # TranscriptionEngine seam, WhisperEngine, filters, service
├── formatters.py     # text / jsonl strategies + registry
├── writer.py         # TranscriptWriter, sinks
├── pipeline.py       # utterances in, written lines out
├── app.py            # composition root
└── cli.py            # argument parsing
```

Four seams exist so the program can be tested and extended without touching what
already works:

| Seam | Swap in | Why |
| --- | --- | --- |
| `AudioBackend` | anything that lists devices and opens a stream | tests run with no hardware |
| `TranscriptionEngine` | any speech-to-text model | whisper is not load-bearing |
| `LineFormatter` | a new output format | `register_formatter("srt", …)` |
| `Platform` | a new operating system | one class, one registry line |

### Adding an output format

```python
from soundvibes.formatters import register_formatter

class CsvFormatter:
    def format(self, line):
        return f"{line.started_at:%H:%M:%S},{line.source},{line.language},{line.text}"

    def header(self, moment):
        return "time,source,language,text"

register_formatter("csv", CsvFormatter)
```

`--format csv` now works. No existing file was edited.

## Tests

```bash
./.venv/bin/python -m pytest tests/ -q     # 118 tests, ~0.1s
```

The unit suite needs **no model, no microphone, no ffmpeg** — every external
dependency sits behind a seam with a test double. That is the point of the
structure above.

```bash
./.venv/bin/python selftest.py             # end-to-end, needs the model
```

`selftest.py` synthesises English, German and Russian speech with the platform's
offline TTS (`say` on macOS, `espeak-ng` on Linux) and drives the real pipeline
classes — still no microphone. It asserts that each phrase is transcribed, detected
in the right language, and written to the per-language files.
