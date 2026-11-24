"""Build committed archives and check clean installs; see build_release.py for static checks."""

from __future__ import annotations

import sys
import tempfile

from build_release import main

if __name__ == "__main__":
    arguments = sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix="stackwinnow-dist-check-") as directory:
        if "--dist-dir" not in arguments and not any(
            a.startswith("--dist-dir=") for a in arguments
        ):
            arguments += ["--dist-dir", directory]
        raise SystemExit(main([*arguments, "--install-check"]))
