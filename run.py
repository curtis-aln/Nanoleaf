#!/usr/bin/env python3
"""Convenience launcher: `python run.py [options]` (same as `python -m nanoleaf_strip`)."""
import sys

from nanoleaf_strip.cli import main

sys.exit(main())
