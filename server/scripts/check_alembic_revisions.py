"""Проверка цепочки Alembic: одна голова, все down_revision существуют.

Запуск из каталога server/:
  python scripts/check_alembic_revisions.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _revision_pair(path: Path) -> tuple[str, str | None]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rev: str | None = None
    down: str | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name):
                if t.id == "revision" and isinstance(node.value, ast.Constant):
                    rev = str(node.value.value)
                elif t.id == "down_revision":
                    v = node.value
                    if isinstance(v, ast.Constant) and v.value is None:
                        down = None
                    elif isinstance(v, ast.Constant) and isinstance(v.value, str):
                        down = str(v.value)
                    elif isinstance(v, ast.Tuple) and v.elts:
                        # merge: ("a", "b") — не используем в GuardStar
                        raise SystemExit(
                            f"{path.name}: tuple down_revision не поддержан скриптом"
                        )
    if not rev:
        raise SystemExit(f"{path.name}: не найден revision =")
    return rev, down


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    versions = root / "app" / "db" / "migrations" / "versions"
    if not versions.is_dir():
        print("Нет каталога migrations/versions", file=sys.stderr)
        return 2

    by_rev: dict[str, tuple[str | None, str]] = {}
    for p in sorted(versions.glob("*.py")):
        if p.name == "__init__.py":
            continue
        rid, down = _revision_pair(p)
        if rid in by_rev:
            print(f"Дубликат revision {rid!r}", file=sys.stderr)
            return 1
        by_rev[rid] = (down, p.name)

    missing_down: list[tuple[str, str, str | None]] = []
    for rid, (down, fname) in by_rev.items():
        if down is not None and down not in by_rev:
            missing_down.append((fname, rid, down))

    if missing_down:
        print("Сломанные down_revision:", file=sys.stderr)
        for fn, rid, down in missing_down:
            print(f"  {fn}: revision={rid!r} down_revision={down!r} — нет файла", file=sys.stderr)
        return 1

    referenced = {d for d, _ in by_rev.values() if d is not None}
    heads = [r for r in by_rev if r not in referenced]
    if len(heads) != 1:
        print(f"Ожидалась ровно одна голова Alembic, получено {len(heads)}: {heads}", file=sys.stderr)
        return 1

    # линейная цепочка от головы к base
    chain: list[str] = []
    cur = heads[0]
    while cur is not None:
        chain.append(cur)
        d, _ = by_rev[cur]
        cur = d
    print(f"OK: head={heads[0]}, ревизий в цепочке={len(chain)}")
    print("От head к base:")
    for i, rid in enumerate(chain):
        _, fn = by_rev[rid]
        print(f"  {i + 1:2d}  {rid}  ({fn})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
