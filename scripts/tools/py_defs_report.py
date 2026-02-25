#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class DefItem:
    kind: str  # "class" | "function" | "async_function"
    qualname: str
    signature: str
    doc: str | None
    lineno: int
    decorators: list[str]


def _unparse(node: ast.AST) -> str:
    # Python 3.9+ provides ast.unparse
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparse-failed>"


def _format_args(args: ast.arguments) -> str:
    # Build a readable signature string from an ast.arguments object.
    # Note: this does not preserve exact original formatting, but is stable.
    parts: list[str] = []

    def fmt_arg(a: ast.arg, default: ast.AST | None = None) -> str:
        s = a.arg
        if a.annotation is not None:
            s += f": {_unparse(a.annotation)}"
        if default is not None:
            s += f" = {_unparse(default)}"
        return s

    # pos-only (Python 3.8+)
    posonly = getattr(args, "posonlyargs", [])
    n_posonly = len(posonly)

    # defaults align to the LAST len(defaults) of (posonlyargs + args.args)
    all_pos = list(posonly) + list(args.args)
    defaults = list(args.defaults)
    pad = len(all_pos) - len(defaults)
    defaults = [None] * max(pad, 0) + defaults

    for a, d in zip(all_pos, defaults):
        parts.append(fmt_arg(a, d))

    if n_posonly:
        parts.insert(n_posonly, "/")

    # vararg
    if args.vararg is not None:
        s = "*" + args.vararg.arg
        if args.vararg.annotation is not None:
            s += f": {_unparse(args.vararg.annotation)}"
        parts.append(s)
    else:
        # kw-only marker if there are kw-only args
        if args.kwonlyargs:
            parts.append("*")

    # kw-only args (defaults in kw_defaults)
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        parts.append(fmt_arg(a, d))

    # kwarg
    if args.kwarg is not None:
        s = "**" + args.kwarg.arg
        if args.kwarg.annotation is not None:
            s += f": {_unparse(args.kwarg.annotation)}"
        parts.append(s)

    return ", ".join(parts)


def _format_signature(fn: ast.AST) -> str:
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = _format_args(fn.args)
        ret = ""
        if fn.returns is not None:
            ret = f" -> {_unparse(fn.returns)}"
        return f"({args}){ret}"
    if isinstance(fn, ast.ClassDef):
        # We could try to find __init__ for a class signature, but keep it simple.
        bases = [_unparse(b) for b in fn.bases] if fn.bases else []
        return f"({', '.join(bases)})" if bases else ""
    return ""


class DefCollector(ast.NodeVisitor):
    def __init__(self, *, include_nested: bool) -> None:
        self.include_nested = include_nested
        self.stack: list[str] = []
        self.items: list[DefItem] = []

    def _qual(self, name: str) -> str:
        if not self.stack:
            return name
        return ".".join(self.stack + [name])

    def _decorators(self, node: ast.AST) -> list[str]:
        decs = getattr(node, "decorator_list", [])
        return [_unparse(d) for d in decs] if decs else []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qn = self._qual(node.name)
        self.items.append(
            DefItem(
                kind="class",
                qualname=qn,
                signature=_format_signature(node),
                doc=ast.get_docstring(node),
                lineno=node.lineno,
                decorators=self._decorators(node),
            )
        )
        if self.include_nested:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        qn = self._qual(node.name)
        self.items.append(
            DefItem(
                kind="function",
                qualname=qn,
                signature=_format_signature(node),
                doc=ast.get_docstring(node),
                lineno=node.lineno,
                decorators=self._decorators(node),
            )
        )
        if self.include_nested:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        qn = self._qual(node.name)
        self.items.append(
            DefItem(
                kind="async_function",
                qualname=qn,
                signature=_format_signature(node),
                doc=ast.get_docstring(node),
                lineno=node.lineno,
                decorators=self._decorators(node),
            )
        )
        if self.include_nested:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()


def extract_defs_from_file(path: Path, *, include_nested: bool) -> list[DefItem]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    col = DefCollector(include_nested=include_nested)
    col.visit(tree)
    return sorted(col.items, key=lambda x: x.lineno)


def iter_py_files(paths: list[Path], *, recursive: bool) -> Iterable[Path]:
    for p in paths:
        if p.is_file() and p.suffix == ".py":
            yield p
        elif p.is_dir():
            if recursive:
                yield from p.rglob("*.py")
            else:
                yield from p.glob("*.py")


def render_report(path: Path, items: list[DefItem]) -> str:
    lines: list[str] = []
    lines.append(f"# {path}")
    for it in items:
        lines.append("")
        if it.decorators:
            for d in it.decorators:
                lines.append(f"@{d}")
        if it.kind == "class":
            lines.append(f"class {it.qualname}{it.signature}:  # line {it.lineno}")
        elif it.kind == "async_function":
            lines.append(f"async def {it.qualname}{it.signature}:  # line {it.lineno}")
        else:
            lines.append(f"def {it.qualname}{it.signature}:  # line {it.lineno}")

        if it.doc:
            lines.append('"""')
            lines.extend(it.doc.splitlines())
            lines.append('"""')
        else:
            lines.append("(no docstring)")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Report Python class/function definitions (AST-based), including docstrings."
    )
    ap.add_argument("paths", nargs="+", help="Python file(s) or directory(ies).")
    ap.add_argument(
        "-r", "--recursive", action="store_true", help="Recurse into directories."
    )
    ap.add_argument(
        "--include-nested",
        action="store_true",
        help="Include nested defs (methods, inner functions/classes).",
    )
    ap.add_argument(
        "--out",
        type=str,
        default="-",
        help="Output file path, or '-' for stdout. If multiple inputs, writes concatenated report.",
    )
    args = ap.parse_args()

    in_paths = [Path(p) for p in args.paths]
    files = sorted(iter_py_files(in_paths, recursive=args.recursive))

    chunks: list[str] = []
    for f in files:
        items = extract_defs_from_file(f, include_nested=args.include_nested)
        chunks.append(render_report(f, items))

    report = "\n".join(chunks)

    if args.out == "-":
        print(report)
    else:
        Path(args.out).write_text(report, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
