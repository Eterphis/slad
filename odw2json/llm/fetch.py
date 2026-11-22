"""One-time model download: `python -m odw2json.llm.fetch [name]` (sha256 checked, weights stay out of git).

After this step the pipeline runs fully offline. `--list` shows the known models; `--dest` changes the folder
(default `models/` in the repository, ignored by git).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

from .runtime import ROOT

HF = "https://huggingface.co/{repo}/resolve/main/{file}"

# name -> (repo, file, size in bytes, sha256, licence). Only OSI-approved permissive licences.
MODELS = {
    "qwen3-0.6b": ("Qwen/Qwen3-0.6B-GGUF", "Qwen3-0.6B-Q8_0.gguf", 639446688, "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031", "Apache-2.0"),
    "qwen3-1.7b": ("Qwen/Qwen3-1.7B-GGUF", "Qwen3-1.7B-Q8_0.gguf", 1834426016, "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a", "Apache-2.0"),
    "qwen3-4b": ("Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf", 2497280256, "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5", "Apache-2.0"),
    "bielik-1.5b": ("speakleash/Bielik-1.5B-v3.0-Instruct-GGUF", "Bielik-1.5B-v3.0-Instruct.Q8_0.gguf", 1699568288, "014fc8a22eb85c557e395476071bacd14dd8c8a69dedb96e5dd17e8bb7cee9c3", "Apache-2.0"),
}
DEFAULT = "qwen3-1.7b"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(name: str, dest: Path) -> Path:
    repo, file, size, digest, _lic = MODELS[name]
    target = dest / file
    if target.is_file() and target.stat().st_size == size and sha256(target) == digest:
        return target
    dest.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    print(f"downloading {repo}/{file} ({size / 1e9:.2f} GB) ...", file=sys.stderr)
    urllib.request.urlretrieve(HF.format(repo=repo, file=file), part)
    if sha256(part) != digest:
        part.unlink(missing_ok=True)
        raise SystemExit(f"sha256 mismatch for {file}: download discarded")
    part.replace(target)
    return target


def ensure_model(reader: dict) -> None:
    """Called once by the CLI for a profile with `reader: {kind: llm, model: ...}`: when the weights are missing and the
    file name is a known model, download it (profile key `fetch: false` turns this off). Never raises: offline or a
    failed download only means the reader stays off and the recipe output is used."""
    from .runtime import model_path

    path = model_path(reader.get("model", ""))
    if path.is_file() or reader.get("fetch", True) is False:
        return
    name = next((n for n, m in MODELS.items() if m[1] == path.name), None)
    if name is None:
        return
    try:
        fetch(name, path.parent)
    except (OSError, SystemExit) as e:
        print(f"LLM model download failed ({e}); continuing without the LLM reader", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", nargs="?", default=DEFAULT, choices=sorted(MODELS))
    ap.add_argument("--dest", default=str(ROOT / "models"))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        for n, (repo, file, size, _d, lic) in MODELS.items():
            print(f"{n:12} {size / 1e9:5.2f} GB  {lic:10} {repo}/{file}" + ("  (default)" if n == DEFAULT else ""))
        return 0
    print(fetch(a.name, Path(a.dest)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
