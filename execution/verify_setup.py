#!/usr/bin/env python3
"""Verify dependencies and API keys for the Instagram workflow."""

from __future__ import annotations

import importlib
import sys

from utils import has_key, load_env


def check_package(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def main() -> int:
    load_env()
    packages = {
        "requests": "requests",
        "dotenv": "python-dotenv",
        "openai": "openai",
        "google.generativeai": "google-generativeai",
    }
    keys = [
        "PERPLEXITY_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ELEVENLABS_API_KEY",
        "CREATOMATE_API_KEY",
        "CREATOMATE_TEMPLATE_ID",
    ]

    print("Packages:")
    ok = True
    for module, label in packages.items():
        present = check_package(module)
        print(f"  [{'OK' if present else 'MISSING'}] {label}")
        ok = ok and present

    print("\nAPI keys / config:")
    for key in keys:
        present = has_key(key)
        print(f"  [{'OK' if present else 'MISSING'}] {key}")

    print("\nNotes:")
    print("  - Agent dry-run works without API keys.")
    print("  - Live research needs PERPLEXITY_API_KEY.")
    print("  - Live script needs OPENAI_API_KEY and/or GEMINI_API_KEY.")
    print("  - Live video needs CREATOMATE_* and ELEVENLABS_*.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
