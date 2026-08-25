# soundvibes

Live speech-to-text for **both** sides of a conversation: your microphone (`MIC`)
and whatever your computer is playing (`SYS`). Every utterance is transcribed as
it happens and appended to a text file. Language is auto-detected per utterance
and constrained to the ones you allow — **English, German and Russian** by default.

Transcription runs locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper);
no audio leaves the machine and no API key is needed.

Runs on **macOS and Linux**.

## Quick start

```bash
make install            # create the venv and install dependencies
make start              # transcribe in this terminal; Ctrl-C stops it
```

Everything is a make target:

| Command | What it does |
| --- | --- |
| `make install` | create the venv, install dependencies, check your platform |
| `make install offline` | ...and add fully offline translation, pre-fetching the model and language packages |
| `make start` | transcribe in this terminal; Ctrl-C stops it |
| `make start fr` | ...and show a French translation as you speak |
| `make start fr de` | ...several languages at once |
| `make start-d` | transcribe in the background |
| `make start-d fr` | ...with a French translation running alongside |
| `make stop` | stop the background transcription (drains the queue first) |
| `make status` | is it running, and what has it written |
| `make logs` | follow the background transcript live |
| `make test` | fast unit suite — no model, no microphone |
| `make selftest` | end-to-end check against the real model |

> **`make start -d` does not work, and cannot.** GNU make claims `-d` as its own
> debug flag wherever it appears on the command line, so it never reaches the
> target — you get make's debug trace instead of a background transcription.
> **`make start-d`** is the working spelling.

Background runs write their pid to `var/soundvibes.pid` and their output to
`var/soundvibes.log`. `make stop` sends SIGTERM so the queue is drained and the
last utterances still land in the transcript; it escalates to SIGKILL only if the
process is still alive after 15 seconds.

Asking for a translation without a working backend stops before recording rather
than filling `translate.FR.txt` with nothing:

```
$ make start fr
Translation into [fr] was requested, but the offline backend
is not installed, so the translate.*.txt files would stay empty.

  make install offline      install it (large: stanza, spacy, torch)
  --translator claude       use the API instead (text leaves the machine)
```

## Install

```bash
cd soundvibes
make install          # or ./setup.sh directly
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
make start                                             # the usual way
./.venv/bin/python soundvibes.py --list-devices        # see what can be captured
./.venv/bin/python soundvibes.py                       # same as `make start`
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

## Translation

Transcribe a multilingual conversation once, then read it in whichever language
you want. The transcript stays mixed-language; each target language additionally
gets a `translate.<LANG>.txt` file containing **everything**, translated.

```bash
make start ru en fr                                    # or:
./.venv/bin/python soundvibes.py --translate ru,en,fr
```

With translation on, the translated lines are echoed as you speak, not just
written to the files:

```
[14:30:00] [MIC] [de] Guten Tag, wie geht es dir?
[14:30:00] [MIC] [fr] Bonjour, comment allez-vous ?
```

```
transcripts/
├── transcript.txt      # as spoken: de, en, ru interleaved
├── translate.RU.txt    # all of it, in Russian
├── translate.EN.txt    # all of it, in English
└── translate.FR.txt    # all of it, in French
```

Lines already in the target language are copied through rather than round-tripped,
and repeated phrases are cached — live speech says "yes" and "one moment" a lot.

### Choosing a backend

| `--translator` | Where it runs | Trade-off |
| --- | --- | --- |
| `argos` (default) | fully offline | keeps the "nothing leaves the machine" guarantee; needs an extra install |
| `claude` | Anthropic API | better quality, nothing to install — **your transcript text is sent to a third party** |
| `none` | nowhere | passthrough; useful for testing |

The offline backend is an optional dependency because it is genuinely heavy —
it pulls stanza, spacy and torch, roughly 2–3 GB:

```bash
make install offline          # installs it and pre-fetches everything
pip install -r requirements-translate.txt   # or just the dependency
```

`make install offline` goes further than installing the package: it pre-downloads
the whisper model and the Argos language packages for your configured languages,
then translates one phrase to prove the offline path works. After it finishes,
soundvibes needs no network at all.

Language packages are downloaded on first use, like the whisper model; after that
it runs with no network at all.

The API backend needs `ANTHROPIC_API_KEY` (or an `ant auth login` profile) and
`pip install anthropic`. Use it only where sending transcript text off the machine
is acceptable.

A failing backend never takes down the recording: the failure is reported on
stderr, that one target file misses that one line, and everything else continues.

Note that translation happens inline, so a slow backend adds latency between
speech and the transcript line appearing. The utterance queue absorbs it — nothing
is lost — but the transcript can lag behind the conversation.

## Configuration

Every tunable value lives in one file: **`config.yaml`**. The modules read from
it and carry no defaults of their own, so there is one place to look and no
chance of a literal in the source disagreeing with the documented value.

```yaml
endpointer:
  silence_seconds: 0.7        # silence that ends an utterance
  sensitivity: 3.0            # threshold as a multiple of the noise floor

transcription:
  languages: [en, de, ru]
  model_size: small
  hallucinations:             # phrases whisper invents from silence
    - "thank you."
```

### Which languages?

Two separate lists, doing different jobs:

```yaml
transcription:
  languages: [en, de, ru]     # what may be SPOKEN — detection is forced into this set

translation:
  targets: [ru, pl, fr]       # what to translate INTO -> translate.RU.txt, ...
```

`transcription.languages` constrains whisper's detection: it knows ~100 languages
and this narrows it to yours, per utterance. Listing exactly one skips detection
entirely, which is faster and more accurate when you know what will be spoken.

`translation.targets` is the output side. A target need never be spoken —
translating German speech into French is the ordinary case.

Command-line flags override either for a single run: `--languages en,de` and
`--translate fr` (or `make start fr`).

`make install offline` plans from **both** lists: it works out every
spoken-language → target pair and installs the packages that cover them, using
English as a pivot where Argos has no direct package. With four spoken languages
and six targets that is 23 pairs covered by 9 packages.

It covers audio framing, endpointer tuning, whisper settings, the hallucination
blocklist, loopback device hints, translation, and output defaults. Command-line
flags override it for a single run.

Load order — first hit wins:

1. `$SOUNDVIBES_CONFIG`
2. `./config.yaml` in the working directory
3. the copy shipped next to the package


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
| `--translate ru,en,fr` | also write `translate.RU.txt`, `translate.EN.txt`, … |
| `--translator argos` | translation backend: `argos` (offline), `claude` (API), `none` |
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
├── config.py         # loads config.yaml — the one source of every constant
├── transcription.py  # TranscriptionEngine seam, WhisperEngine, filters, service
├── translation.py    # Translator seam: argos (offline), claude (API), none
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
| `Translator` | a new translation backend | `register_translator("deepl", …)` |

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
make test                                  # 185 tests, ~0.1s
```

The unit suite needs **no model, no microphone, no ffmpeg, no network** — every external
dependency sits behind a seam with a test double. That is the point of the
structure above.

```bash
make selftest                              # end-to-end, needs the model
```

`selftest.py` synthesises English, German and Russian speech with the platform's
offline TTS (`say` on macOS, `espeak-ng` on Linux) and drives the real pipeline
classes — still no microphone. It asserts that each phrase is transcribed, detected
in the right language, and written to the per-language files.
