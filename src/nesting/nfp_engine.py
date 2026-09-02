"""NFP (No-Fit-Polygon) を用いた実形状ネスティング配置アルゴリズム。

- 8方向回転 (45°刻み) それぞれで形状をキャッシュ。
- シート境界とのIFPは矩形なのでバウンディングボックス差分で厳密に算出。
- 既配置部品とのNFPは pyclipper.MinkowskiSum で算出し、NFP頂点候補点から
  bottom-left-fill 方式で採用点を選択する（穴を除いた外周同士の衝突回避）。
- 重なり最終判定は shapely の交差面積で行うため、穴の内側リングを持つ
  Polygon(outer, holes) 同士なら他部品が穴の内部に収まる配置も許容される。
- 穴埋め二次パス (`_fill_holes`) は既配置部品の穴へ残り部品を詰めるが、
  厳密な内側NFP計算ではなく重心合わせ+contains判定による近似ヒューリスティック。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pyclipper
from shapely.geometry import Polygon

from .geometry_utils import (
    Point,
    bounds,
    hole_area_total,
    net_area,
    normalize_to_origin,
    rotate_points,
    shoelace_area,
    to_shapely,
    translate_points,
)
from .models import NestingCandidate, Part, PlacedInstance

logger = logging.getLogger(__name__)

_SCALE = 100000.0  # pyclipper は整数座標のみ対応のためスケーリングする
# 軸整列(0/90/180/270)を優先角度、対角(45系)は「軸整列では置けない場合のみ」の
# フォールバック角度として扱う(下記 _find_best_placement 参照)。矩形に近い部品では
# 対角配置は見た目のyがわずかに低くなるだけで後続部品の詰めを阻害し、全体の歩留まりを
# 悪化させる(斜めに取られて隙間が多い、というユーザー報告の原因)ため。
_AXIS_ROTATIONS: tuple[float, ...] = (0.0, 90.0, 180.0, 270.0)
_DIAGONAL_ROTATIONS: tuple[float, ...] = (45.0, 135.0, 225.0, 315.0)
_ROTATIONS: tuple[float, ...] = _AXIS_ROTATIONS + _DIAGONAL_ROTATIONS
# NFP頂点は pyclipper の整数丸め (1/_SCALE mm 単位) を経由するため、理論上ぴったり
# 密着するはずの配置でも量子化誤差分だけ僅かに重なり判定される。閾値が厳しすぎると
# その丸め誤差(面積にして 1e-3〜1e-2 mm² オーダー)を「衝突」と誤判定し、密着配置
# (グリッド詰め)を棄却して無駄な回転・隙間だらけの配置にフォールバックしてしまう。
_EPS_AREA = 1e-2  # 重なり判定の許容誤差 (mm²)
# quantity<=0 (自動計算モード) 時、極小部品×巨大シートで反復回数が爆発しないための安全上限。
_AUTO_QUANTITY_HARD_CAP = 2000


def _to_int_path(points: list[Point]) -> list[tuple[int, int]]:
    return [(int(round(x * _SCALE)), int(round(y * _SCALE))) for x, y in points]


def _from_int_path(path: list[tuple[int, int]]) -> list[Point]:
    return [(x / _SCALE, y / _SCALE) for x, y in path]


@dataclass
class _RotatedShape:
    outer: list[Point]
    holes: list[list[Point]]
    buffered_outer: list[Point]
    bbox_w: float
    bbox_h: float


@dataclass
class _Placed:
    part_id: str
    angle: float
    x: float
    y: float
    shape: _RotatedShape
    buffered_polygon: Polygon
    full_polygon: Polygon  # 穴を内側リングとして持つ Polygon(outer, holes)
    aabb: tuple[float, float, float, float]  # 高速リジェクト用のバウンディングボックス


def _aabb_overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


class NestingEngine:
    """複数部品種別・数量を対象にNFPベースでシートへ配置するエンジン。"""

    def __init__(self, sheet_w: float, sheet_h: float, clearance: float) -> None:
        self._sheet_w = sheet_w
        self._sheet_h = sheet_h
        self._clearance = max(0.0, clearance)
        self._rotated_cache: dict[tuple[str, float], _RotatedShape] = {}
        self._nfp_cache: dict[tuple[str, float, str, float], list[list[Point]]] = {}

    # ================================================================== #
    # 公開 API
    # ================================================================== #

    def generate_candidates(
        self, parts: list[Part], max_candidates: int = 3
    ) -> list[NestingCandidate]:
        """複数戦略を実行し、歩留まり上位 max_candidates 件の分布案を返す。"""
        for part in parts:
            part.net_area = net_area(part.outer, part.holes)

        strategies = [
            ("area_desc", lambda p: net_area(p.outer, p.holes)),
            ("long_side_desc", lambda p: self._long_side(p)),
            ("width_desc", lambda p: bounds(p.outer)[2] - bounds(p.outer)[0]),
        ]

        candidates: list[NestingCandidate] = []
        seen_signatures: set[tuple] = set()
        seen_orderings: set[tuple[str, ...]] = set()
        for name, key in strategies:
            # 部品種が1種類のみ、または並び替えキーが同点の場合、他戦略と全く同じ
            # 順序(=全く同じ配置結果)になる。配置探索自体が最も時間のかかる処理なので、
            # 既に試した並び順ならスキップして無駄な再計算(単一部品種で最大3倍)を避ける。
            ordering = tuple(p.id for p in sorted(parts, key=key, reverse=True))
            if ordering in seen_orderings:
                continue
            seen_orderings.add(ordering)

            candidate = self._run_strategy(parts, name, key)
            signature = tuple(
                sorted(
                    (pl.part_id, round(pl.x, 2), round(pl.y, 2), pl.rotation_deg)
                    for pl in candidate.placements
                )
            )
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            candidates.append(candidate)

        candidates.sort(key=lambda c: c.yield_pct, reverse=True)
        return candidates[:max_candidates]

    # ================================================================== #
    # 戦略実行
    # ================================================================== #

    @staticmethod
    def _long_side(part: Part) -> float:
        min_x, min_y, max_x, max_y = bounds(part.outer)
        return max(max_x - min_x, max_y - min_y)

    def _run_strategy(self, parts: list[Part], strategy_name: str, sort_key) -> NestingCandidate:
        ordered = sorted(parts, key=sort_key, reverse=True)
        placed: list[_Placed] = []
        placements: list[PlacedInstance] = []
        count_per_part: dict[str, int] = {p.id: 0 for p in parts}

        for part in ordered:
            variants = {angle: self._get_rotated(part, angle) for angle in _ROTATIONS}
            iteration_limit = part.quantity if part.quantity > 0 else self._auto_quantity_limit(part)
            for _ in range(iteration_limit):
                best = self._find_best_placement(part, variants, placed)
                if best is None:
                    break
                oy, ox, angle, shape = best
                self._commit_placement(part, shape, angle, ox, oy, placed, placements, count_per_part)

        self._fill_holes(ordered, placed, placements, count_per_part)

        return self._build_candidate(strategy_name, parts, placements, count_per_part)

    def _auto_quantity_limit(self, part: Part) -> int:
        """quantity<=0 (自動計算モード) 用に、定尺面積から導出した配置回数上限を返す。

        sheet_area // part.net_area は面積からの真の理論上限(これを超える配置は幾何学的に
        不可能)だが、部品が極小の場合に理論値が桁違いに大きくなり得るため、性能保護用の
        ハード上限でもクランプする。
        """
        part_area = part.net_area
        if part_area <= 0:
            return _AUTO_QUANTITY_HARD_CAP
        theoretical = max(1, int((self._sheet_w * self._sheet_h) // part_area))
        if theoretical > _AUTO_QUANTITY_HARD_CAP:
            logger.warning(
                "part_id=%s: 自動計算の理論上限(%d)がハード上限(%d)を超えるため打ち切ります。"
                "実際の最大取り数より少なく報告される可能性があります。",
                part.id, theoretical, _AUTO_QUANTITY_HARD_CAP,
            )
        return min(theoretical, _AUTO_QUANTITY_HARD_CAP)

    def _commit_placement(
        self,
        part: Part,
        shape: _RotatedShape,
        angle: float,
        ox: float,
        oy: float,
        placed: list[_Placed],
        placements: list[PlacedInstance],
        count_per_part: dict[str, int],
        via_hole_fill: bool = False,
    ) -> None:
        full_poly = to_shapely(
            translate_points(shape.outer, ox, oy),
            [translate_points(h, ox, oy) for h in shape.holes],
        )
        buffered_outer_translated = translate_points(shape.buffered_outer, ox, oy)
        buffered_poly = Polygon(buffered_outer_translated)
        aabb = bounds(buffered_outer_translated)
        placed.append(_Placed(part.id, angle, ox, oy, shape, buffered_poly, full_poly, aabb))
        placements.append(
            PlacedInstance(part.id, count_per_part[part.id], ox, oy, angle, via_hole_fill)
        )
        count_per_part[part.id] += 1

    # ================================================================== #
    # 形状キャッシュ
    # ================================================================== #

    def _get_rotated(self, part: Part, angle: float) -> _RotatedShape:
        key = (part.id, angle)
        cached = self._rotated_cache.get(key)
        if cached is not None:
            return cached

        outer = rotate_points(part.outer, angle)
        holes = [rotate_points(h, angle) for h in part.holes]
        n_outer, n_holes, w, h = normalize_to_origin(outer, holes)
        buffered_outer = self._buffer_outer(n_outer)
        shape = _RotatedShape(n_outer, n_holes, buffered_outer, w, h)
        self._rotated_cache[key] = shape
        return shape

    def _buffer_outer(self, outer: list[Point]) -> list[Point]:
        if self._clearance <= 0 or len(outer) < 3:
            return outer
        try:
            poly = Polygon(outer).buffer(self._clearance / 2.0, join_style=2, mitre_limit=5.0)
            if poly.is_empty:
                return outer
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda g: g.area)
            return list(poly.exterior.coords)[:-1]
        except Exception as exc:  # pragma: no cover - shapely の異常系保護
            logger.warning("クリアランスバッファ生成に失敗しました: %s", exc)
            return outer

    # ================================================================== #
    # NFP 計算
    # ================================================================== #

    def _nfp_polygons(
        self,
        placed_item: _Placed,
        orbit_part_id: str,
        orbit_angle: float,
        orbit_shape: _RotatedShape,
    ) -> list[list[Point]]:
        cache_key = (placed_item.part_id, placed_item.angle, orbit_part_id, orbit_angle)
        cached = self._nfp_cache.get(cache_key)
        if cached is not None:
            return cached

        path_a = _to_int_path(placed_item.shape.buffered_outer)
        path_b_reflected = _to_int_path([(-x, -y) for x, y in orbit_shape.buffered_outer])
        try:
            solution = pyclipper.MinkowskiSum(path_b_reflected, path_a, True)
        except Exception as exc:
            logger.warning("NFP計算に失敗しました: %s", exc)
            solution = []
        polys = [_from_int_path(p) for p in solution]
        self._nfp_cache[cache_key] = polys
        return polys

    # ================================================================== #
    # 配置候補選択 (bottom-left-fill)
    # ================================================================== #

    def _find_best_placement(
        self,
        part: Part,
        variants: dict[float, _RotatedShape],
        placed: list[_Placed],
    ) -> tuple[float, float, float, _RotatedShape] | None:
        # まず軸整列角度だけで探索する。1つでも置ければ対角角度は一切試さない
        # (対角は局所的なyのみを僅かに縮めて他部品の詰めを阻害するため、軸整列で
        # 置ける限りは常にそちらを優先する)。軸整列で全滅した場合のみ対角角度を
        # フォールバックとして探索し、置けないよりはマシな対角配置を許容する。
        best = self._search_angles(part, variants, placed, _AXIS_ROTATIONS)
        if best is not None:
            return best
        return self._search_angles(part, variants, placed, _DIAGONAL_ROTATIONS)

    def _search_angles(
        self,
        part: Part,
        variants: dict[float, _RotatedShape],
        placed: list[_Placed],
        angles: tuple[float, ...],
    ) -> tuple[float, float, float, _RotatedShape] | None:
        best: tuple[float, float, float, _RotatedShape] | None = None

        for angle in angles:
            shape = variants[angle]
            bx0, by0, bx1, by1 = bounds(shape.buffered_outer)
            bw, bh = bx1 - bx0, by1 - by0
            if bw > self._sheet_w + 1e-6 or bh > self._sheet_h + 1e-6:
                continue

            candidates: set[tuple[float, float]] = {(-bx0, -by0)}
            for placed_item in placed:
                for poly in self._nfp_polygons(placed_item, part.id, angle, shape):
                    for vx, vy in poly:
                        ox, oy = placed_item.x + vx, placed_item.y + vy
                        candidates.add((ox, oy))
                        candidates.add((-bx0, oy))  # シート左端に寄せる
                        candidates.add((ox, -by0))  # シート下端に寄せる

            for ox, oy in sorted(candidates, key=lambda p: (p[1], p[0])):
                if ox + bx0 < -1e-6 or oy + by0 < -1e-6:
                    continue
                if ox + bx1 > self._sheet_w + 1e-6 or oy + by1 > self._sheet_h + 1e-6:
                    continue
                candidate_translated = translate_points(shape.buffered_outer, ox, oy)
                candidate_aabb = bounds(candidate_translated)
                # AABBが重ならない部品とは shapely を呼ぶまでもなく衝突しないため、
                # 重なり得る部品が1つも無ければ Polygon構築/intersection計算を省略する
                # (shapely呼び出しがこの探索全体で最も重い処理のため)。
                overlapping = [p for p in placed if _aabb_overlaps(candidate_aabb, p.aabb)]
                if overlapping:
                    candidate_poly = Polygon(candidate_translated)
                    if any(
                        candidate_poly.intersection(p.buffered_polygon).area > _EPS_AREA
                        for p in overlapping
                    ):
                        continue
                if best is None or (oy, ox) < (best[0], best[1]):
                    best = (oy, ox, angle, shape)
                break  # bottom-left 順に見て最初の有効候補を採用

        return best

    # ================================================================== #
    # 穴埋め二次パス (近似ヒューリスティック)
    # ================================================================== #

    def _fill_holes(
        self,
        ordered_parts: list[Part],
        placed: list[_Placed],
        placements: list[PlacedInstance],
        count_per_part: dict[str, int],
    ) -> None:
        remaining = [p for p in ordered_parts if count_per_part[p.id] < p.quantity]
        if not remaining or not placed:
            return
        remaining_sorted = sorted(remaining, key=lambda p: p.net_area)

        hole_slots: list[tuple[float, list[Point], _Placed]] = []
        for placed_item in placed:
            for hole in placed_item.shape.holes:
                translated = translate_points(hole, placed_item.x, placed_item.y)
                area = shoelace_area(translated)
                if area > 0:
                    hole_slots.append((area, translated, placed_item))
        hole_slots.sort(key=lambda t: t[0], reverse=True)

        for _, hole_ring, _host in hole_slots:
            hole_poly = Polygon(hole_ring)
            shrunk = hole_poly.buffer(-self._clearance / 2.0) if self._clearance > 0 else hole_poly
            if shrunk.is_empty:
                continue
            placed_one = False
            for part in remaining_sorted:
                if count_per_part[part.id] >= part.quantity:
                    continue
                for angle in _ROTATIONS:
                    shape = self._get_rotated(part, angle)
                    target = shrunk.centroid
                    ox = target.x - shape.bbox_w / 2.0
                    oy = target.y - shape.bbox_h / 2.0
                    candidate_outer = translate_points(shape.outer, ox, oy)
                    candidate_poly = Polygon(candidate_outer)
                    if not candidate_poly.is_valid or not shrunk.contains(candidate_poly):
                        continue
                    candidate_aabb = bounds(candidate_outer)
                    if any(
                        _aabb_overlaps(candidate_aabb, p.aabb)
                        and candidate_poly.intersection(p.full_polygon).area > _EPS_AREA
                        for p in placed
                    ):
                        continue
                    self._commit_placement(
                        part, shape, angle, ox, oy, placed, placements, count_per_part,
                        via_hole_fill=True,
                    )
                    placed_one = True
                    break
                if placed_one:
                    break

    # ================================================================== #
    # 結果集計
    # ================================================================== #

    def _build_candidate(
        self,
        strategy_name: str,
        parts: list[Part],
        placements: list[PlacedInstance],
        count_per_part: dict[str, int],
    ) -> NestingCandidate:
        net_area_by_id = {p.id: p.net_area for p in parts}
        hole_area_by_id = {p.id: hole_area_total(p.holes) for p in parts}

        total_used = sum(net_area_by_id[pl.part_id] for pl in placements)
        total_hole = sum(hole_area_by_id[pl.part_id] for pl in placements)
        sheet_area = self._sheet_w * self._sheet_h
        remaining = max(0.0, sheet_area - total_used)
        yield_pct = (total_used / sheet_area * 100.0) if sheet_area > 0 else 0.0

        return NestingCandidate(
            strategy_name=strategy_name,
            placements=placements,
            count_per_part=dict(count_per_part),
            total_used_area=total_used,
            total_hole_area=total_hole,
            sheet_area=sheet_area,
            remaining_area=remaining,
            yield_pct=yield_pct,
        )
