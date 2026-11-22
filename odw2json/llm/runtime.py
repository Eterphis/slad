"""Runtime adapter: the one place that knows how a local model is run (llama.cpp through llama-cpp-python, CPU).

The rest of the package talks to the small `Runtime` interface, so tests use a fake and another engine
(llama.cpp server, onnxruntime-genai) is one more adapter. Nothing here leaves the machine: weights are a local
GGUF file, there is no network code.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("odw2json.llm")
ROOT = Path(__file__).resolve().parent.parent.parent


class RuntimeUnavailable(RuntimeError):
    """The model cannot be run here (weights missing, llama-cpp-python not installed). The pipeline then keeps the
    recipe output as it is: the LLM is an optional extra, never a dependency."""


class Runtime(Protocol):
    name: str  # recorded in evidence: `llm:<name>`

    def complete(self, system: str, user: str, schema: dict[str, Any], max_tokens: int = 700) -> str:
        """One chat turn at temperature 0 whose answer must be JSON that follows `schema`."""
        ...


def model_path(name_or_path: str) -> Path:
    """`models/<file>.gguf` relative to the repo root unless absolute; env ODW2JSON_LLM_MODEL overrides."""
    p = Path(os.environ.get("ODW2JSON_LLM_MODEL") or name_or_path)
    return p if p.is_absolute() else ROOT / p


def default_threads(workers: int | None = None) -> int:
    """ODW2JSON_LLM_THREADS, else the per-worker share the pipeline sets for OCR (cores // workers), else all cores."""
    env = os.environ.get("ODW2JSON_LLM_THREADS") or os.environ.get("ODW2JSON_OCR_THREADS")
    if env:
        return max(1, int(env))
    return max(1, (os.cpu_count() or 4) // max(1, workers or 1))


class LlamaCppRuntime:
    """GGUF model on llama.cpp; the model is loaded on the first call, the grammar comes from the JSON schema."""

    def __init__(self, path: str | os.PathLike, n_ctx: int = 4096, n_threads: int | None = None):
        self.path = model_path(str(path))
        self.name = self.path.stem
        self.n_ctx = n_ctx
        self.n_threads = n_threads or default_threads()
        self._llm = None
        self._lock = threading.Lock()

    def _load(self):
        if self._llm is None:
            if not self.path.is_file():
                raise RuntimeUnavailable(f"model file not found: {self.path} (python -m odw2json.llm.fetch)")
            try:
                from llama_cpp import Llama
            except ImportError as e:
                raise RuntimeUnavailable(f"llama-cpp-python is not installed: {e}") from None
            log.info("loading %s (%d threads)", self.path.name, self.n_threads)
            self._llm = Llama(model_path=str(self.path), n_ctx=self.n_ctx, n_threads=self.n_threads, verbose=False)
        return self._llm

    def complete(self, system: str, user: str, schema: dict[str, Any], max_tokens: int = 700) -> str:
        with self._lock:
            llm = self._load()
            out = llm.create_chat_completion(
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object", "schema": schema},
                temperature=0.0,
                max_tokens=max_tokens,
            )
        return out["choices"][0]["message"]["content"] or ""
