"""Optional local-LLM reader (T016): a small GGUF model on llama.cpp, CPU only, grounded and never overriding."""
from .extractor import LlmExtractor, make_extractor
from .reader import Decision, LlmReader
from .runtime import LlamaCppRuntime, Runtime, RuntimeUnavailable

__all__ = ["LlmExtractor", "make_extractor", "LlmReader", "Decision", "LlamaCppRuntime", "Runtime", "RuntimeUnavailable"]
