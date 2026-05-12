#!/usr/bin/env python3
"""
mxm-marketdata SSH welcome screen banner.

- No external dependencies.
- Uses 24-bit ANSI truecolor (falls back gracefully if terminal ignores it).
- Designed for /etc/update-motd.d/ or shell profile execution.

Usage:
  python3 mxm_marketdata_banner.py
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime

# -------------------------
# MXM palette (truecolor)
# -------------------------
BG0 = (13, 23, 29)  # #0D171D  Rich Black
STRUCT = (66, 86, 90)  # #42565A  structural_blue
NEUTRAL = (170, 177, 164)  # #AAB1A4  ash_grey
ACCENT = (44, 68, 120)  # #2C4478  accent_blue
TEXT = (239, 239, 239)  # #EFEFEF  text_primary
OK = (200, 169, 123)  # #C8A97B  ecru
INFO = (227, 201, 138)  # #E3C98A  peach_yellow
WARN = (255, 91, 63)  # #FF5B3F  tomato
ALERT = (107, 15, 13)  # #6B0F0D  blood_red


def fg(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"\x1b[38;2;{r};{g};{b}m"


def bg(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"\x1b[48;2;{r};{g};{b}m"


RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"


def term_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default


def hr(width: int, char: str = "─") -> str:
    return char * max(0, width)


def pad_right(s: str, width: int) -> str:
    # Best-effort padding (ANSI not stripped); keep simple for banner.
    if len(s) >= width:
        return s
    return s + " " * (width - len(s))


def box(lines: list[str], width: int) -> list[str]:
    # Simple box with Unicode box-drawing; still readable if unsupported.
    inner_w = max(0, width - 2)
    top = "┌" + "─" * inner_w + "┐"
    bot = "└" + "─" * inner_w + "┘"
    out = [top]
    for ln in lines:
        ln = ln[:inner_w]
        out.append("│" + pad_right(ln, inner_w) + "│")
    out.append(bot)
    return out


def ascii_headline() -> list[str]:
    # Minimal built-in “banner” text (FIGlet-like), tuned to avoid external tools.
    # Width ~ 54 chars.
    return [
        " __  __ __  __ __  __            _        _        ",
        "|  \\/  |  \\/  |  \\/  | __ _ _ __| | _____| |_ __ _ ",
        "| |\\/| | |\\/| | |\\/| |/ _` | '__| |/ / _ \\ __/ _` |",
        "| |  | | |  | | |  | | (_| | |  |   <  __/ || (_| |",
        "|_|  |_|_|  |_|_|  |_|\\__,_|_|  |_|\\_\\___|\\__\\__,_|",
    ]


def detect_env() -> str:
    # Keep it simple and honest: prefer explicit env var, otherwise unknown.
    return os.environ.get("MXM_ENV", "unknown")


def main() -> None:
    w = min(max(term_width(), 72), 110)  # keep sensible bounds
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Header section
    headline = ascii_headline()
    headline_w = max(len(x) for x in headline)

    title_lines = []
    title_lines.append(f"{BOLD}{fg(TEXT)}MXM · Market Data{RESET}")
    title_lines.append(f"{fg(NEUTRAL)}Controlled market data ingress boundary{RESET}")
    title_lines.append(
        f"{fg(NEUTRAL)}Session: SSH login{RESET}  {fg(NEUTRAL)}Time: {now}{RESET}"
    )

    # “SCADA panel” contents
    env = detect_env()
    panel_lines = [
        f"{fg(ACCENT)}[|||]{RESET}  {BOLD}{fg(TEXT)}mxm-marketdata{RESET}",
        "",
        f"{fg(NEUTRAL)}Role:{RESET}    {fg(TEXT)}Historical + daily updates (idempotent){RESET}",
        f"{fg(NEUTRAL)}Ingress:{RESET}  {fg(TEXT)}Databento{RESET}",
        f"{fg(NEUTRAL)}Store:{RESET}    {fg(TEXT)}SQLite metadata · Parquet bars{RESET}",
        f"{fg(NEUTRAL)}Policy:{RESET}   {fg(TEXT)}cost-bounded · replayable · auditable{RESET}",
        "",
        f"{fg(NEUTRAL)}Env:{RESET}      {fg(TEXT)}{env}{RESET}",
        f"{fg(NEUTRAL)}State:{RESET}    {fg(OK)}ready{RESET}  {fg(NEUTRAL)}(no checks executed in banner){RESET}",
    ]

    # Compose final output
    print(bg(BG0), end="")  # set background for the whole block (best-effort)

    # Top rule
    print(f"{fg(STRUCT)}{hr(w)}{RESET}")

    # Headline left + title right (if it fits), otherwise stack.
    if w >= headline_w + 4 + 28:
        # two-column layout
        for i in range(max(len(headline), len(title_lines))):
            left = headline[i] if i < len(headline) else " " * headline_w
            right = title_lines[i] if i < len(title_lines) else ""
            # Left headline in ACCENT, right in TEXT/NEUTRAL (already colored)
            left_col = f"{fg(ACCENT)}{left}{RESET}"
            print(left_col + " " * 4 + right)
    else:
        # stacked layout
        for ln in headline:
            print(f"{fg(ACCENT)}{ln}{RESET}")
        print("")
        for ln in title_lines:
            print(ln)

    print(f"{fg(STRUCT)}{hr(w)}{RESET}")

    # Panel box
    inner_width = min(w, 96)
    boxed = box(panel_lines, inner_width)
    for ln in boxed:
        # frame in STRUCT, contents already colored
        if ln.startswith(("┌", "└")):
            print(f"{fg(STRUCT)}{ln}{RESET}")
        elif ln.startswith("│") and ln.endswith("│"):
            print(f"{fg(STRUCT)}│{RESET}{ln[1:-1]}{fg(STRUCT)}│{RESET}")
        else:
            print(ln)

    print(f"{fg(STRUCT)}{hr(w)}{RESET}")

    # Footer hint (keep minimal)
    hint = f"{fg(NEUTRAL)}Hint:{RESET} {fg(TEXT)}mxm-marketdata --help{RESET}  {fg(NEUTRAL)}·{RESET}  {fg(TEXT)}mxm v1 marketdata ops{RESET}"
    print(hint)

    # Bottom padding / reset
    print(RESET, end="")


if __name__ == "__main__":
    main()
