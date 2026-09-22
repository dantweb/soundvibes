"""Audio and source constants, read from config.yaml."""

from .config import CONFIG

SAMPLE_RATE = CONFIG.audio.sample_rate
FRAME_MS = CONFIG.audio.frame_ms
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

SOURCE_MICROPHONE = CONFIG.sources.microphone_label
SOURCE_SYSTEM = CONFIG.sources.system_label

# Retained for callers that used the older names.
SOURCE_MIC = SOURCE_MICROPHONE
SOURCE_SYS = SOURCE_SYSTEM
