"""ネスティング用の幾何ヘルパー（回転・shapely変換・面積計算）。"""

from __future__ import annotations

import math

from shapely.geometry import Polygon
from shapely.validation import make_valid

Point = tuple[float, float]


def make_rectangle_polygon(width: float, height: float) -> list[Point]:
    if width <= 0 or height <= 0:
        raise ValueError("矩形の幅と高さは0より大きい値が必要です")
    return [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]


def make_circle_polygon(radius: float, segments: int = 64) -> list[Point]:
    if radius <= 0:
        raise ValueError("円の半径は0より大きい値が必要です")
    if segments < 3:
        raise ValueError("円の分割数は3以上が必要です")
    return [
        (
            radius + radius * math.cos(2.0 * math.pi * index / segments),
            radius + radius * math.sin(2.0 * math.pi * index / segments),
        )
        for index in range(segments)
    ]


def shoelace_area(points: list[Point]) -> float:
    """靴紐公式による多角形面積（絶対値）を返す。"""
    n = len(points)
    if n < 3:
        return 0.0
    s = sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )
    return abs(s) / 2.0


def net_area(outer: list[Point], holes: list[list[Point]]) -> float:
    """外周面積から穴面積合計を控除したネット面積を返す。"""
    return shoelace_area(outer) - sum(shoelace_area(h) for h in holes)


def hole_area_total(holes: list[list[Point]]) -> float:
    """穴面積の合計を返す。"""
    return sum(shoelace_area(h) for h in holes)


def rotate_points(points: list[Point], angle_deg: float) -> list[Point]:
    """原点周りに angle_deg 度だけ回転した点列を返す。"""
    if not points:
        return []
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    return [(x * c - y * s, x * s + y * c) for x, y in points]


def bounds(points: list[Point]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) を返す。"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def normalize_to_origin(
    outer: list[Point], holes: list[list[Point]]
) -> tuple[list[Point], list[list[Point]], float, float]:
    """外周のバウンディングボックス最小角を原点に揃え、(outer, holes, w, h) を返す。"""
    min_x, min_y, max_x, max_y = bounds(outer)
    shifted_outer = [(x - min_x, y - min_y) for x, y in outer]
    shifted_holes = [[(x - min_x, y - min_y) for x, y in h] for h in holes]
    return shifted_outer, shifted_holes, max_x - min_x, max_y - min_y


def to_shapely(outer: list[Point], holes: list[list[Point]]) -> Polygon:
    """穴を内側リングとして持つ shapely Polygon を生成する。"""
    if len(outer) < 3:
        return Polygon()
    valid_holes = [h for h in holes if len(h) >= 3]
    poly = Polygon(outer, valid_holes)
    if not poly.is_valid:
        poly = make_valid(poly)
    return poly


def translate_points(points: list[Point], dx: float, dy: float) -> list[Point]:
    return [(x + dx, y + dy) for x, y in points]
