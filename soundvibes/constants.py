"""Audio and source constants shared across the package."""

SAMPLE_RATE = 16_000          # what whisper expects
FRAME_MS = 30                 # endpointer granularity
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

SOURCE_MICROPHONE = "MIC"
SOURCE_SYSTEM = "SYS"

# Retained for callers that used the older names.
SOURCE_MIC = SOURCE_MICROPHONE
SOURCE_SYS = SOURCE_SYSTEM
