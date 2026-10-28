"""PyInstaller entry script (a package's __main__ can't be frozen directly)."""
import sys

from jarvis_desktop.__main__ import main

sys.exit(main())
