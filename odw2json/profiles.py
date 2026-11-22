"""Processing profiles: `profiles/<name>.yaml` choose which components the pipeline builds (D-015, D-019).

Selection: `--profile` > env `ODW2JSON_PROFILE` > `ocr`. Profiles directory: env `ODW2JSON_PROFILES` > <repo>/profiles.

File format (all keys optional except description):
    description: one line
    ocr: {enabled: true}      # RapidOCR on pages without a usable text layer
    ingest: {dpi: 200}        # any PdfIngestor option (see odw2json/ingest/pdf.py)
    reader: null              # slot for the local-model reader (T016): {kind: llm, model: <path>, ...}

A profile only switches components the factory already knows; an unknown key or an unsupported reader is an error
(a typo must not silently run another profile). T016 adds the `llm` profile by registering its kind in READERS.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = "ocr"
KEYS = {"description", "ocr", "ingest", "reader"}
READERS: set[str] = {"llm"}  # reader kinds the factory can build (odw2json/llm, T016)


class ProfileError(ValueError):
    pass


@dataclass
class Profile:
    name: str
    description: str = ""
    ocr: dict = field(default_factory=dict)
    ingest: dict = field(default_factory=dict)
    reader: dict | None = None

    @property
    def ocr_enabled(self) -> bool:
        return bool(self.ocr.get("enabled", True))

    def ingest_config(self) -> dict:
        """Config dict for odw2json.ingest.default_ingestor."""
        return {"ocr": dict(self.ocr, enabled=self.ocr_enabled), "ingest": dict(self.ingest)}


def profiles_dir(explicit=None) -> Path:
    return Path(explicit or os.environ.get("ODW2JSON_PROFILES") or ROOT / "profiles")


def resolve_name(explicit: str | None = None) -> str:
    return explicit or os.environ.get("ODW2JSON_PROFILE") or DEFAULT_PROFILE


def list_profiles(directory=None) -> list[str]:
    d = profiles_dir(directory)
    return sorted(p.stem for p in d.glob("*.yaml")) if d.is_dir() else []


def load_profile(name: str, directory=None) -> Profile:
    import yaml

    if not re.fullmatch(r"[A-Za-z0-9_-]+", name or ""):
        raise ProfileError(f"invalid profile name {name!r}")
    path = profiles_dir(directory) / f"{name}.yaml"
    if not path.is_file():
        raise ProfileError(f"unknown profile {name!r}; available: {', '.join(list_profiles(directory)) or 'none'}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ProfileError(f"{path}: expected a mapping")
    unknown = set(raw) - KEYS
    if unknown:
        raise ProfileError(f"{path}: unknown key(s) {sorted(unknown)}; allowed: {sorted(KEYS)}")
    for k in ("ocr", "ingest"):
        if raw.get(k) is not None and not isinstance(raw[k], dict):
            raise ProfileError(f"{path}: '{k}' must be a mapping")
    reader = raw.get("reader")
    if reader is not None:
        kind = reader.get("kind") if isinstance(reader, dict) else None
        if kind not in READERS:
            raise ProfileError(f"{path}: reader kind {kind!r} is not available in this build (known: {sorted(READERS) or 'none'})")
    return Profile(name, str(raw.get("description", "")), dict(raw.get("ocr") or {}), dict(raw.get("ingest") or {}), reader)
