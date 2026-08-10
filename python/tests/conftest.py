from __future__ import annotations

import os
import sys
from pathlib import Path

# The runner and provenance checks fail closed on group/world-writable helper
# files and directories.  pytest creates tmp_path entries with the process
# umask, so on a host with umask 0002 every fixture would land 0775/0664 and
# trip those checks for environmental rather than behavioral reasons.  Pin a
# conventional umask for the whole test process so fixture permissions match
# the environment the security checks were designed for.
os.umask(0o022)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "python" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
