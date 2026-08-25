#!/usr/bin/env python3
"""Launcher kept so the documented `python soundvibes.py ...` still works.

The implementation lives in the `soundvibes/` package. Running this file
executes it as __main__, so the package name is free for the real import.
Equivalent: `python -m soundvibes`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from soundvibes.cli import main

if __name__ == "__main__":
    sys.exit(main())
