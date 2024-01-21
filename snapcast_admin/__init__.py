#! /usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
"""Remote control script for the `https://www.peanut.one/snapcast` podcast host.

This script does not ask for confirmation and does not back up data before
destructive commands. Be careful.
"""

from .cli import cli

if __name__ == "__main__":
    cli()
