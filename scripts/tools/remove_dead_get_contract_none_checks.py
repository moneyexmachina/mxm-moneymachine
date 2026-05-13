from __future__ import annotations

from pathlib import Path

ROOT = Path(".")


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def rewrite_text(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    removed = 0

    while i < len(lines):
        line = lines[i]

        if (
            " = api.get_contract_by_id(contract_id)" in line
            and i + 1 < len(lines)
            and lines[i + 1].lstrip() == "if contract is None:\n"
        ):
            base_indent = indent_of(line)
            out.append(line)
            i += 2

            while i < len(lines):
                next_line = lines[i]

                if next_line.strip() and indent_of(next_line) <= base_indent:
                    break

                i += 1

            removed += 1
            continue

        out.append(line)
        i += 1

    return "".join(out), removed


def main() -> None:
    changed: list[Path] = []

    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts:
            continue

        text = path.read_text(encoding="utf-8")
        new_text, n = rewrite_text(text)

        if n:
            path.write_text(new_text, encoding="utf-8")
            changed.append(path)
            print(f"{path}: removed {n} dead None-check block(s)")

    print(f"\nChanged {len(changed)} file(s).")


if __name__ == "__main__":
    main()
