#! /usr/bin/env python3
import sys
from subprocess import PIPE, run

__version__ = "1.0.0"


def cmd(command: str) -> list[str]:
    """Run a shell command and return the stdout split up by line."""
    result = run(command.split(), stdout=PIPE, encoding="utf-8")

    return result.stdout.splitlines()


# TODO: Only run on a commit to main, or merge into main.
def go() -> None:
    """Abort commit if package version not incremented. Quick and dirty."""
    # Just prints the current branch, we check if it's `main`.
    branch = cmd("git branch --show-current")[0]
    if branch != "main":
        sys.exit(0)

    # Very hacky. Print out the staged vs HEAD diff of pyproject.toml, and
    #   look for a line that seems like it's the `version` declaration.
    version_changed = any(
        line.startswith("+version = ") for line in
        cmd("git diff -U0 --no-ext-diff --cached -- pyproject.toml")
    )

    if version_changed:
        sys.exit(0)
    sys.exit("Committing to main with no version bump. Shame.")


if __name__ == "__main__":
    go()
