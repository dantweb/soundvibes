#!/usr/bin/env bash
# Create the soundvibes virtualenv and install its dependencies.
# Works on macOS and Linux.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
OS="$(uname -s)"

if [ ! -d .venv ]; then
  echo "==> Creating .venv"
  "$PYTHON" -m venv .venv
fi

echo "==> Installing dependencies"
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-dev.txt

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "==> ffmpeg not found (needed only by selftest.py)"
  case "$OS" in
    Darwin) echo "    brew install ffmpeg" ;;
    Linux)  echo "    sudo apt install ffmpeg      # or your distro's equivalent" ;;
  esac
fi

case "$OS" in
Darwin)
  if ! ls /Library/Audio/Plug-Ins/HAL 2>/dev/null | grep -qi blackhole; then
    cat <<'EOF'

==> No BlackHole driver found.
    System-audio (SYS) capture on macOS needs a loopback driver:

        brew install blackhole-2ch

    Then create a Multi-Output Device in "Audio MIDI Setup" (speakers +
    BlackHole 2ch) and select it as your system output, so you still hear
    the audio while soundvibes transcribes it.
    Microphone (MIC) capture works without this.
EOF
  fi
  ;;
Linux)
  # PortAudio is a hard requirement of sounddevice and is NOT pulled in by pip.
  if ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
    cat <<'EOF'

==> PortAudio not found. The `sounddevice` wheel needs the system library:

        sudo apt install libportaudio2          # Debian / Ubuntu
        sudo dnf install portaudio              # Fedora
        sudo pacman -S portaudio                # Arch
EOF
  fi

  if ! command -v espeak-ng >/dev/null 2>&1; then
    echo "==> espeak-ng not found (needed only by selftest.py)"
    echo "    sudo apt install espeak-ng"
  fi

  if command -v pactl >/dev/null 2>&1; then
    echo
    echo "==> System-audio (SYS) capture: these monitor sources were found"
    pactl list short sources 2>/dev/null | grep -i monitor | sed 's/^/    /' \
      || echo "    (none - see README, you may need the PulseAudio ALSA plugin)"
  else
    echo
    echo "==> pactl not found; if you use PulseAudio/PipeWire install pulseaudio-utils"
    echo "    to list monitor sources for SYS capture."
  fi
  ;;
esac

cat <<'EOF'

==> Done. Run it with:

    ./.venv/bin/python soundvibes.py --list-devices
    ./.venv/bin/python soundvibes.py -o transcripts/transcript.txt

    Tests:
    ./.venv/bin/python -m pytest tests/ -q     # fast, no model needed
    ./.venv/bin/python selftest.py             # end-to-end, needs the model

EOF
