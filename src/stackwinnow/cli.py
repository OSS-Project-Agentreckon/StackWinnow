"""Command-line entry point for the bootstrap release."""

import argparse
from collections.abc import Sequence

from stackwinnow import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Display help or version information without changing the environment."""
    parser = argparse.ArgumentParser(
        prog="stackwinnow",
        description="Choose suitable open-source AI tools for your project.",
        epilog="Bootstrap release: only help and version are available.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
