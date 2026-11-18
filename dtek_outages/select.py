"""Address picking: fzf when it is installed, a plain prompt otherwise.

fzf is optional on purpose: macOS and the BSDs usually do not ship it, and the
tool should still be usable there.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Sequence


class SelectionCancelled(Exception):
    """The user pressed Esc / Ctrl-C / Ctrl-D."""


def have_fzf() -> bool:
    return shutil.which("fzf") is not None


def choose(
    prompt: str,
    lines: Sequence[str],
    *,
    header: str = "",
    extra: Sequence[str] = (),
    use_fzf: bool = True,
) -> str:
    """Return one line from ``lines`` that the user picked."""

    if not lines:
        raise SelectionCancelled(prompt)
    if len(lines) == 1:
        return lines[0]
    if use_fzf and have_fzf():
        return _choose_fzf(prompt, lines, header=header, extra=extra)
    return _choose_prompt(prompt, lines, header=header)


def _choose_fzf(
    prompt: str,
    lines: Sequence[str],
    *,
    header: str,
    extra: Sequence[str],
) -> str:
    command = [
        "fzf",
        "--height=70%",
        "--reverse",
        "--border",
        f"--prompt={prompt} ",
    ]
    if header:
        command.append(f"--header={header}")
    command.extend(extra)

    try:
        completed = subprocess.run(
            command,
            input="\n".join(lines) + "\n",
            text=True,
            stdout=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:  # fzf vanished or is not executable
        print(f"fzf failed ({exc}); falling back to a plain prompt", file=sys.stderr)
        return _choose_prompt(prompt, lines, header=header)

    if completed.returncode != 0 or not completed.stdout.strip():
        raise SelectionCancelled(prompt)
    return completed.stdout.rstrip("\n")


def _choose_prompt(prompt: str, lines: Sequence[str], *, header: str) -> str:
    """Numbered list with substring filtering; works on any terminal."""

    shown = list(lines)
    if header:
        print(header)
    while True:
        for index, line in enumerate(shown, start=1):
            print(f"{index:>3}) {line}")
        try:
            answer = input(f"{prompt} [номер або частина назви]: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SelectionCancelled(prompt) from None

        if not answer:
            continue
        if answer.isdigit():
            number = int(answer)
            if 1 <= number <= len(shown):
                return shown[number - 1]
            print(f"Немає пункту {number}.", file=sys.stderr)
            continue

        needle = answer.casefold()
        matches = [line for line in lines if needle in line.casefold()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            print(f"Нічого не знайдено за «{answer}».", file=sys.stderr)
            shown = list(lines)
            continue
        shown = matches
