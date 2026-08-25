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

import sys
from pathlib import Path

from soundvibes.config import CONFIG
from soundvibes.offline import required_pairs, resolve_packages


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


def fetch_argos_packages(sources: list[str], targets: list[str]) -> tuple[int, int]:
    """Install what is needed to translate every spoken language into every target.

    Both lists matter: `sources` is what may be spoken (transcription.languages)
    and `targets` is what we translate into (translation.targets). A target need
    never be spoken — translating German speech into French is the normal case —
    so planning from the spoken languages alone leaves the real work undone.
    """
    try:
        import argostranslate.package as package_api
    except ImportError:
        report("argostranslate is not installed - skipping language packages.", indent=1)
        report("install it with: pip install -r requirements-translate.txt", indent=1)
        return 0, 0

    report("argos language packages...")
    report(f"spoken: {', '.join(sources)}   targets: {', '.join(targets)}", indent=1)
    try:
        package_api.update_package_index()
        available = [(p.from_code, p.to_code) for p in package_api.get_available_packages()]
    except Exception as error:
        report(f"could not reach the package index: {error}", indent=1)
        return 0, 0

    needed = required_pairs(sources, targets)
    to_install, unreachable = resolve_packages(available, sources, targets)
    report(f"{len(needed)} pair(s) needed, {len(to_install)} package(s) cover them",
           indent=1)

    installed = {(p.from_code, p.to_code) for p in package_api.get_installed_packages()}
    catalogue = {(p.from_code, p.to_code): p for p in package_api.get_available_packages()}
    succeeded = failed = 0

    for pair in to_install:
        source, target = pair
        if pair in installed:
            report(f"{source}->{target}: already installed", indent=1)
            succeeded += 1
            continue
        try:
            package_api.install_from_path(catalogue[pair].download())
        except Exception as error:
            report(f"{source}->{target}: FAILED - {error}", indent=1)
            failed += 1
            continue
        report(f"{source}->{target}: installed", indent=1)
        succeeded += 1

    for source, target in unreachable:
        report(f"{source}->{target}: NO ROUTE - argos has no package and no "
               f"English pivot", indent=1)

    return succeeded, failed


def verify_offline_backend(sources: list[str], targets: list[str]) -> bool:
    """Translate one phrase to prove the offline path actually works.

    Verifies a pair that is genuinely needed, rather than a convenient one.
    """
    from soundvibes.translation import ArgosTranslator, TranslationError

    pairs = required_pairs(sources, targets)
    if not pairs:
        report("nothing to translate between - nothing to verify.", indent=1)
        return True

    source, target = pairs[0]
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
    sources = list(CONFIG.transcription.languages)
    targets = list(CONFIG.translation.targets) or sources
    report("Preparing soundvibes for offline use")
    report(f"spoken: {', '.join(sources)}   translating into: {', '.join(targets)}   "
           f"backend: {CONFIG.translation.backend}")
    report("")

    model_ok = fetch_whisper_model()
    report("")
    succeeded, failed = fetch_argos_packages(sources, targets)
    report("")
    verified = verify_offline_backend(sources, targets) if succeeded else False

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
