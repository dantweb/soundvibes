#!/usr/bin/env python3
"""Prepare soundvibes to run with no network at all.

`make install offline` runs this after installing the offline translation
dependencies. It pre-fetches everything that would otherwise be downloaded on
first use — the whisper model and the Argos language packages — so that a later
run needs no connection.

Run it directly to re-check or top up an existing install:

    ./.venv/bin/python offline_setup.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

from soundvibes.config import CONFIG


def report(message: str, indent: int = 0) -> None:
    print(f"{'  ' * indent}{message}", flush=True)


def fetch_whisper_model() -> bool:
    """Download and cache the transcription model."""
    model_size = CONFIG.transcription.model_size
    report(f"whisper model {model_size!r}...")
    try:
        from faster_whisper import WhisperModel

        WhisperModel(model_size,
                     device=CONFIG.transcription.device,
                     compute_type=CONFIG.transcription.compute_type)
    except Exception as error:
        report(f"FAILED: {error}", indent=1)
        return False
    report("cached", indent=1)
    return True


def fetch_argos_packages(languages: list[str]) -> tuple[int, int]:
    """Install every available direct pair between the configured languages."""
    try:
        import argostranslate.package as package_api
    except ImportError:
        report("argostranslate is not installed - skipping language packages.", indent=1)
        report("install it with: pip install -r requirements-translate.txt", indent=1)
        return 0, 0

    report("argos language packages...")
    try:
        package_api.update_package_index()
        available = package_api.get_available_packages()
    except Exception as error:
        report(f"could not reach the package index: {error}", indent=1)
        return 0, 0

    installed = {(p.from_code, p.to_code) for p in package_api.get_installed_packages()}
    wanted = list(itertools.permutations(languages, 2))
    succeeded = failed = 0

    for source, target in wanted:
        if (source, target) in installed:
            report(f"{source}->{target}: already installed", indent=1)
            succeeded += 1
            continue
        match = next((p for p in available
                      if p.from_code == source and p.to_code == target), None)
        if match is None:
            # Argos often has no direct pair and routes through English instead.
            report(f"{source}->{target}: no direct package (usually routed via en)",
                   indent=1)
            continue
        try:
            package_api.install_from_path(match.download())
        except Exception as error:
            report(f"{source}->{target}: FAILED - {error}", indent=1)
            failed += 1
            continue
        report(f"{source}->{target}: installed", indent=1)
        succeeded += 1

    return succeeded, failed


def verify_offline_backend() -> bool:
    """Translate one phrase to prove the offline path actually works."""
    from soundvibes.translation import ArgosTranslator, TranslationError

    languages = list(CONFIG.transcription.languages)
    if len(languages) < 2:
        report("only one language configured - nothing to verify.", indent=1)
        return True

    source, target = languages[0], languages[1]
    report(f"verifying offline translation {source}->{target}...")
    try:
        translated = ArgosTranslator().translate("Hello, this is a test.",
                                                 source, target)
    except TranslationError as error:
        report(f"FAILED: {error}", indent=1)
        return False
    report(f"ok: {translated!r}", indent=1)
    return True


def main() -> int:
    languages = list(CONFIG.transcription.languages)
    report("Preparing soundvibes for offline use")
    report(f"languages: {', '.join(languages)}   "
           f"config: {CONFIG.translation.backend} backend")
    report("")

    model_ok = fetch_whisper_model()
    report("")
    succeeded, failed = fetch_argos_packages(languages)
    report("")
    verified = verify_offline_backend() if succeeded else False

    report("")
    if model_ok and verified:
        report("Ready. soundvibes can now transcribe and translate with no network.")
        return 0
    if model_ok and not succeeded:
        report("Transcription is ready offline; translation is not.")
        report("Install it with: pip install -r requirements-translate.txt")
        return 1
    report(f"Incomplete: model_ok={model_ok}, packages_installed={succeeded}, "
           f"failures={failed}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
