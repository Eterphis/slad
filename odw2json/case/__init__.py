"""Case step: data-consistency checks and cross-document repairs, driven by recipes/case/relations.yaml."""
from .step import apply_case, load_config, run_case

__all__ = ["apply_case", "load_config", "run_case"]
