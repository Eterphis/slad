"""Where the UZP challenge data lives for tests: $UZP_DATA, else the nearest `uzp-data/` in the repo or a parent
folder (git worktrees under .worktrees/ find the main checkout's clone). Tests that need it skip when it is absent."""
import os
from pathlib import Path


def uzp_data() -> Path:
    env = os.environ.get("UZP_DATA")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        if (base / "uzp-data").is_dir():
            return base / "uzp-data"
    return here.parent / "uzp-data"  # absent: dependent tests skip


UZP = uzp_data()
