from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DEPENDENCY_DIR = PROJECT_ROOT / ".deps"

if DEPENDENCY_DIR.exists():
    sys.path.insert(0, str(DEPENDENCY_DIR))

from pdf_combiner.ui import run


if __name__ == "__main__":
    raise SystemExit(run())
