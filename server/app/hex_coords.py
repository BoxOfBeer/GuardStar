"""Гексагональная сетка в осях (q, r), совпадающих с полями x, y в БД.

Axial coordinates, «pointy top» на клиенте. См. https://www.redblobgames.com/grids/hexagons/
"""

from __future__ import annotations

from collections import defaultdict

# Шесть соседей в осевых (q, r) == (x, y) в игре.
AXIAL_NEIGHBOR_DR: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
)


def hex_distance(q1: int, r1: int, q2: int, r2: int) -> int:
    dq = int(q1) - int(q2)
    dr = int(r1) - int(r2)
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def hex_disk(q_center: int, r_center: int, radius: int) -> list[tuple[int, int]]:
    """Все клетки с расстоянием <= radius (в шагах гекса) от центра."""
    rad = max(0, int(radius))
    qc, rc = int(q_center), int(r_center)
    out: list[tuple[int, int]] = []
    for dq in range(-rad, rad + 1):
        for dr in range(-rad, rad + 1):
            q, rr = qc + dq, rc + dr
            if hex_distance(q, rr, qc, rc) <= rad:
                out.append((q, rr))
    return out


def hex_disk_axial_bbox(qc: int, rc: int, radius: int) -> tuple[int, int, int, int]:
    """Прямоугольник min_q, max_q, min_r, max_r, покрывающий диск (для SQL)."""
    rad = max(0, int(radius))
    qc, rc = int(qc), int(rc)
    return qc - rad, qc + rad, rc - rad, rc + rad


def hex_disk_cell_count(radius: int) -> int:
    r = max(0, int(radius))
    return 1 + 3 * r * (r + 1)


def axial_to_cube(q: int, r: int) -> tuple[int, int, int]:
    x = int(q)
    z = int(r)
    y = -x - z
    return x, y, z


def cube_to_axial(x: int, y: int, z: int) -> tuple[int, int]:
    return int(x), int(z)


def _cube_round(x: float, y: float, z: float) -> tuple[int, int, int]:
    rx, ry, rz = round(x), round(y), round(z)
    x_diff = abs(rx - x)
    y_diff = abs(ry - y)
    z_diff = abs(rz - z)
    if x_diff > y_diff and x_diff > z_diff:
        rx = -ry - rz
    elif y_diff > z_diff:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return int(rx), int(ry), int(rz)


def _cube_lerp(
    a: tuple[float, float, float], b: tuple[float, float, float], t: float
) -> tuple[float, float, float]:
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def hex_line_cells_exclusive_start(
    q1: int, r1: int, q2: int, r2: int
) -> list[tuple[int, int]]:
    """Клетки прямой в кубических координатах без стартовой клетки, конечная включена.

    Семантика как у старого ``manhattan_l_path_cells`` для проверки блокировки снабжения.
    """
    a = axial_to_cube(int(q1), int(r1))
    b = axial_to_cube(int(q2), int(r2))
    n = hex_distance(int(q1), int(r1), int(q2), int(r2))
    if n <= 0:
        return []
    af = (float(a[0]), float(a[1]), float(a[2]))
    bf = (float(b[0]), float(b[1]), float(b[2]))
    out: list[tuple[int, int]] = []
    last: tuple[int, int] | None = None
    for i in range(1, n + 1):
        t = i / n
        fx, fy, fz = _cube_lerp(af, bf, t)
        cell = cube_to_axial(*_cube_round(fx, fy, fz))
        if last == cell:
            continue
        out.append(cell)
        last = cell
    return out


def hex_window_rows_sorted(
    qc: int, rc: int, radius: int
) -> list[tuple[int, list[tuple[int, int]]]]:
    """Строки окна: ключ сортировки r, в строке клетки (q,r) по возрастанию q."""
    cells = hex_disk(qc, rc, radius)
    by_r: dict[int, list[int]] = defaultdict(list)
    for q, r in cells:
        by_r[int(r)].append(int(q))
    rows: list[tuple[int, list[tuple[int, int]]]] = []
    for r in sorted(by_r.keys()):
        qs = sorted(by_r[r])
        rows.append((r, [(q, r) for q in qs]))
    return rows


def hex_axial_neighbors(q: int, r: int) -> list[tuple[int, int]]:
    q0, r0 = int(q), int(r)
    return [(q0 + dq, r0 + dr) for dq, dr in AXIAL_NEIGHBOR_DR]
