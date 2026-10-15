"""Standalone setup script for MusicHands Console.

Usage:
    python setup.py
"""

import sys

from musichands_console.bootstrap import run_setup_only

if __name__ == "__main__":
    sys.exit(run_setup_only())
