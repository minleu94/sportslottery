#!/usr/bin/env python3
"""Compatibility entry point for the unified LINE + web service manager.

Older releases started a separate webhook server and a public router on the
same port. Keep this command available, but route it through the tray manager
so there is only one FastAPI process, tunnel, and runtime URL source.
"""

from __future__ import annotations

import sys

from scripts.tray_manager import AppTrayManager


def main() -> int:
    return AppTrayManager().run()


if __name__ == "__main__":
    sys.exit(main())
