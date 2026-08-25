#!/usr/bin/env bash
# Create the soundvibes virtualenv and install its dependencies.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if [ ! -d .venv ]; then
  echo "==> Creating .venv"
  "$PYTHON" -m venv .venv
fi

echo "==> Installing dependencies"
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "==> ffmpeg not found (optional, but recommended): brew install ffmpeg"
fi

if [ "$(uname)" = "Darwin" ] && ! ls /Library/Audio/Plug-Ins/HAL 2>/dev/null | grep -qi blackhole; then
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

cat <<'EOF'

==> Done. Run it with:

    ./.venv/bin/python soundvibes.py --list-devices
    ./.venv/bin/python soundvibes.py -o transcripts/transcript.txt

EOF
