"""
type_gate.py
Run mypy once over the whole application source tree and apply the layered
gate from docs/adr/0001-tests-first-and-no-muted-failures.md, decision 4:
an error under a "hard" module (declared in pyproject.toml's
[tool.pbot.type_gate]) fails the build immediately. Every other error is
printed and counted against the ratchet recorded in tools/mypy_ratchet.txt,
which may only move down.

WHY A WRAPPER INSTEAD OF MYPY'S OWN CONFIG
-------------------------------------------
mypy has no notion of "count these errors and compare the count to a stored
figure" — that bookkeeping has to live outside mypy. This script runs the
single, unrestricted scan declared by pyproject.toml's `files = ["src"]`
(no module is excluded by name) and buckets the errors mypy already
reported in full. That is also why this replaces the old `exclude` regex
rather than reusing it: `exclude` only stops mypy from treating a file as a
scan *root* — it does not stop mypy from following an import into that file,
so the excluded module's errors were being reported anyway whenever a
checked module imported it, which is exactly what the old CI never caught
because the run never got past mypy's exit code.
In this repo, hard entries are flat module files under src/ (e.g. src/text_rules.py)
rather than package directories.
"""
import pathlib
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_RATCHET_FILE = _REPO_ROOT / "tools" / "mypy_ratchet.txt"
_ERROR_RE = re.compile(r"^(?P<path>.+?):\d+:(?:\d+:)?\s*error:")


def _hard_prefixes() -> list[str]:
    with open(_REPO_ROOT / "pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    modules = config.get("tool", {}).get("pbot", {}).get("type_gate", {}).get("hard", [])
    return ["src/" + module + ".py" if not module.endswith(".py") else module for module in modules]


def _is_hard(path: str, hard_prefixes: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    for entry in hard_prefixes:
        target = entry if entry.endswith(".py") else f"{entry}.py"
        if not target.startswith("src/"):
            target = f"src/{target}"
        if normalized == target:
            return True
    return False


def classify(lines: Iterable[str], hard_prefixes: list[str]) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []
    for line in lines:
        m = _ERROR_RE.match(line)
        if not m:
            continue
        if _is_hard(m.group("path"), hard_prefixes):
            hard.append(line)
        else:
            soft.append(line)
    return hard, soft


def check_ratchet(soft_count: int, ratchet: int) -> int:
    """Return 0 if soft_count <= ratchet, else 1."""
    return 1 if soft_count > ratchet else 0


def evaluate_gate(hard_count: int, soft_count: int, ratchet: int) -> int:
    """Evaluate full gate: any hard error fails; soft count > ratchet fails."""
    if hard_count > 0:
        return 1
    return check_ratchet(soft_count, ratchet)


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "mypy"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)

    if result.returncode not in (0, 1):
        print(
            f"type_gate: mypy exited {result.returncode} unexpectedly "
            "— treating as a hard failure.",
            file=sys.stderr,
        )
        return 1

    hard_prefixes = _hard_prefixes()
    hard_errors, soft_errors = classify(result.stdout.splitlines(), hard_prefixes)

    ratchet = int(_RATCHET_FILE.read_text().strip())

    print()
    print(
        f"type_gate: {len(hard_errors)} hard-layer error(s) "
        f"({', '.join(hard_prefixes)}); {len(soft_errors)} soft-layer "
        f"error(s) (ratchet: {ratchet})."
    )

    if hard_errors:
        print("type_gate: hard-layer errors fail the build unconditionally:")
        for line in hard_errors:
            print(f"  {line}")
        return 1

    if check_ratchet(len(soft_errors), ratchet) != 0:
        print(
            f"type_gate: soft-layer error count rose from {ratchet} to "
            f"{len(soft_errors)}. Fix the new error(s), or if every error "
            f"above is pre-existing, lower "
            f"{_RATCHET_FILE.relative_to(_REPO_ROOT)} to match — it may "
            "only decrease."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
