"""Resolve the existing TokenLabs credential without evaluating shell code."""
import os
from pathlib import Path
import shlex


def token():
    value = os.environ.get("DGX_TOKENLABS_KEY")
    if value:
        return value
    for line in (Path.home() / ".zshrc").read_text().splitlines():
        if "DGX_TOKENLABS_KEY=" not in line:
            continue
        for item in shlex.split(line, comments=True):
            if item.startswith("DGX_TOKENLABS_KEY="):
                value = item.partition("=")[2]
                if value and not any(char in value for char in "$`\n\r"):
                    return value
    raise RuntimeError("DGX_TOKENLABS_KEY is unavailable; configure the existing credential")


if __name__ == "__main__":
    print(token())
