"""NestingEngine (NFPベースネスティング) のユニットテスト。"""

from __future__ import annotations

import math

import pytest

from src.nesting.geometry_utils import (
    bounds,
    make_circle_polygon,
    make_rectangle_polygon,
    net_area,
    normalize_to_origin,
    rotate_points,
    shoelace_area,
    to_shapely,
    translate_points,
)
from src.nesting.models import Part
from src.nesting.nfp_engine import NestingEngine

_EPS = 1e-6


class TestPrimitivePolygons:
    def test_rectangle_uses_requested_dimensions(self) -> None:
        polygon = make_rectangle_polygon(120.0, 45.0)

        assert bounds(polygon) == (0.0, 0.0, 120.0, 45.0)
        assert shoelace_area(polygon) == pytest.approx(5400.0)

    def test_circle_uses_requested_radius(self) -> None:
        polygon = make_circle_polygon(25.0)

        assert len(polygon) == 64
        assert bounds(polygon) == pytest.approx((0.0, 0.0, 50.0, 50.0))
        assert shoelace_area(polygon) == pytest.approx(3.141592653589793 * 25.0**2, rel=0.002)


def _rect(w: float, h: float) -> list[tuple[float, float]]:
    return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]


def _reconstruct_polygon(part: Part, placement):
    """エンジン内部と同じ変換 (回転→原点正規化→平行移動) で配置後ポリゴンを再構成する。"""
    rotated_outer = rotate_points(part.outer, placement.rotation_deg)
    rotated_holes = [rotate_points(h, placement.rotation_deg) for h in part.holes]
    n_outer, n_holes, _, _ = normalize_to_origin(rotated_outer, rotated_holes)
    outer = translate_points(n_outer, placement.x, placement.y)
    holes = [translate_points(h, placement.x, placement.y) for h in n_holes]
    return to_shapely(outer, holes)


def _assert_no_overlaps(candidate, parts_by_id: dict[str, Part]) -> None:
    polygons = [
        _reconstruct_polygon(parts_by_id[pl.part_id], pl) for pl in candidate.placements
    ]
    for i in range(len(polygons)):
        for j in range(i + 1, len(polygons)):
            assert polygons[i].intersection(polygons[j]).area <= _EPS


class TestGridPacking:
    def test_square_part_fills_grid_reasonably(self) -> None:
        part = Part(id="sq", name="square", outer=_rect(50, 50), quantity=30)
        engine = NestingEngine(sheet_w=300.0, sheet_h=200.0, clearance=0.0)
        candidates = engine.generate_candidates([part])
        best = candidates[0]

        theoretical_max = (300 // 50) * (200 // 50)  # 24
        assert best.count_per_part["sq"] >= theoretical_max * 0.9
        _assert_no_overlaps(best, {"sq": part})


class TestRotationRequired:
    def test_rotation_enables_placement_in_narrow_sheet(self) -> None:
        # 60x30 の部品は 0° では 40 幅のシートに入らないが、90° 回転すれば 30x60 で収まる
        part = Part(id="p", name="p", outer=_rect(60, 30), quantity=1)
        engine = NestingEngine(sheet_w=40.0, sheet_h=70.0, clearance=0.0)
        candidates = engine.generate_candidates([part])
        best = candidates[0]

        assert best.count_per_part["p"] == 1
        placement = best.placements[0]
        assert placement.rotation_deg in (90.0, 270.0)
        _assert_no_overlaps(best, {"p": part})

    def test_no_rotation_fits_returns_zero(self) -> None:
        # どの回転でもシートに収まらない部品は配置数 0 になる
        part = Part(id="p", name="p", outer=_rect(60, 60), quantity=1)
        engine = NestingEngine(sheet_w=40.0, sheet_h=40.0, clearance=0.0)
        candidates = engine.generate_candidates([part])
        best = candidates[0]
        assert best.count_per_part["p"] == 0


class TestHoleFill:
    def test_small_part_placed_inside_large_part_hole(self) -> None:
        hole = [(6.0, 6.0), (14.0, 6.0), (14.0, 14.0), (6.0, 14.0)]  # 8x8 の穴
        big = Part(id="big", name="big", outer=_rect(20, 20), holes=[hole], quantity=1)
        small = Part(id="small", name="small", outer=_rect(6, 6), quantity=1)
        engine = NestingEngine(sheet_w=20.0, sheet_h=20.0, clearance=0.0)
        candidates = engine.generate_candidates([big, small])
        best = candidates[0]

        assert best.count_per_part["big"] == 1
        assert best.count_per_part["small"] == 1
        small_placement = next(pl for pl in best.placements if pl.part_id == "small")
        assert small_placement.via_hole_fill is True

        expected_used = net_area(big.outer, big.holes) + net_area(small.outer, small.holes)
        assert best.total_used_area == pytest.approx(expected_used, rel=1e-6)

        _assert_no_overlaps(best, {"big": big, "small": small})

    def test_hole_too_small_leaves_part_unplaced(self) -> None:
        hole = [(9.0, 9.0), (11.0, 9.0), (11.0, 11.0), (9.0, 11.0)]  # 2x2 の穴 (小部品より小さい)
        big = Part(id="big", name="big", outer=_rect(20, 20), holes=[hole], quantity=1)
        small = Part(id="small", name="small", outer=_rect(6, 6), quantity=1)
        engine = NestingEngine(sheet_w=20.0, sheet_h=20.0, clearance=0.0)
        candidates = engine.generate_candidates([big, small])
        best = candidates[0]

        assert best.count_per_part["big"] == 1
        assert best.count_per_part["small"] == 0


class TestMultiStrategy:
    def test_returns_candidates_sorted_by_yield_descending(self) -> None:
        parts = [
            Part(id="a", name="a", outer=_rect(100, 60), quantity=3),
            Part(id="b", name="b", outer=_rect(40, 40), quantity=5),
        ]
        engine = NestingEngine(sheet_w=300.0, sheet_h=200.0, clearance=5.0)
        candidates = engine.generate_candidates(parts, max_candidates=3)

        assert 1 <= len(candidates) <= 3
        yields = [c.yield_pct for c in candidates]
        assert yields == sorted(yields, reverse=True)
        for candidate in candidates:
            _assert_no_overlaps(candidate, {"a": parts[0], "b": parts[1]})


class TestAutoQuantity:
    """quantity<=0 は「定尺から最大何個切り出せるか」を自動計算するセンチネル値。"""

    def test_quantity_zero_fills_grid_like_fixed_quantity(self) -> None:
        part = Part(id="sq", name="square", outer=_rect(50, 50), quantity=0)
        engine = NestingEngine(sheet_w=300.0, sheet_h=200.0, clearance=0.0)
        candidates = engine.generate_candidates([part])
        best = candidates[0]

        theoretical_max = (300 // 50) * (200 // 50)  # 24
        assert best.count_per_part["sq"] >= theoretical_max * 0.9
        _assert_no_overlaps(best, {"sq": part})

    def test_quantity_negative_one_behaves_same_as_zero(self) -> None:
        part = Part(id="sq", name="square", outer=_rect(50, 50), quantity=-1)
        engine = NestingEngine(sheet_w=300.0, sheet_h=200.0, clearance=0.0)
        candidates = engine.generate_candidates([part])
        best = candidates[0]

        theoretical_max = (300 // 50) * (200 // 50)  # 24
        assert best.count_per_part["sq"] >= theoretical_max * 0.9
        _assert_no_overlaps(best, {"sq": part})

    def test_auto_part_fills_remaining_space_after_fixed_quantity_part(self) -> None:
        fixed = Part(id="fixed", name="fixed", outer=_rect(100, 200), quantity=2)
        auto = Part(id="auto", name="auto", outer=_rect(40, 40), quantity=0)
        engine = NestingEngine(sheet_w=300.0, sheet_h=200.0, clearance=0.0)
        candidates = engine.generate_candidates([fixed, auto])
        best = candidates[0]

        assert best.count_per_part["fixed"] == 2
        assert best.count_per_part["auto"] > 0
        _assert_no_overlaps(best, {"fixed": fixed, "auto": auto})

    def test_auto_quantity_limit_is_clamped_by_hard_cap(self) -> None:
        # 1x1 の極小部品 x 巨大シートでも、ハード上限を超えて反復探索しない。
        tiny = Part(id="tiny", name="tiny", outer=_rect(1, 1), quantity=0)
        tiny.net_area = net_area(tiny.outer, tiny.holes)
        engine = NestingEngine(sheet_w=100000.0, sheet_h=100000.0, clearance=0.0)
        assert engine._auto_quantity_limit(tiny) <= 2000


class TestShelfGrid:
    """整列(グリッド+ギロチン分割)戦略: 整列と端材の連続性を優先する候補。"""

    def test_shelf_grid_candidate_is_included_and_aligned(self) -> None:
        part = Part(id="sq", name="square", outer=_rect(50, 30), quantity=20)
        engine = NestingEngine(sheet_w=300.0, sheet_h=200.0, clearance=5.0)
        candidates = engine.generate_candidates([part])

        shelf = next((c for c in candidates if c.strategy_name == "shelf_grid"), None)
        assert shelf is not None
        assert shelf.count_per_part["sq"] > 0

        # 同一部品・同一回転の配置は同じ行(y座標)を共有し、綺麗に整列しているはず。
        rows = {round(pl.y, 3) for pl in shelf.placements if pl.rotation_deg == 0.0}
        assert len(rows) <= (shelf.count_per_part["sq"])  # 過剰な行数になっていない

        _assert_no_overlaps(shelf, {"sq": part})

    def test_shelf_grid_uses_rotation_when_needed(self) -> None:
        # 60x30 の部品は 0° では 40 幅のシートに入らないが、90° 回転すれば収まる
        part = Part(id="p", name="p", outer=_rect(60, 30), quantity=1)
        engine = NestingEngine(sheet_w=40.0, sheet_h=70.0, clearance=0.0)
        candidates = engine.generate_candidates([part])

        shelf = next((c for c in candidates if c.strategy_name == "shelf_grid"), None)
        assert shelf is not None
        assert shelf.count_per_part["p"] == 1
        _assert_no_overlaps(shelf, {"p": part})

    def test_shelf_grid_handles_mixed_parts_without_overlap(self) -> None:
        parts = [
            Part(id="a", name="a", outer=_rect(100, 60), quantity=3),
            Part(id="b", name="b", outer=_rect(40, 40), quantity=5),
        ]
        engine = NestingEngine(sheet_w=300.0, sheet_h=200.0, clearance=5.0)
        candidates = engine.generate_candidates(parts, max_candidates=3)

        shelf = next((c for c in candidates if c.strategy_name == "shelf_grid"), None)
        assert shelf is not None
        _assert_no_overlaps(shelf, {"a": parts[0], "b": parts[1]})

    def test_fixed_quantity_not_starved_by_auto_max_part(self) -> None:
        # 回帰テスト: 数量指定なし(自動最大)パーツと混在した際、数量を明示指定した
        # パーツが軸選択(縦/横)の巻き添えで取りこぼされ0個になっていた不具合の修正確認。
        fixed = Part(id="fixed", name="fixed", outer=_rect(45, 90), quantity=2)
        auto = Part(id="auto", name="auto", outer=_rect(15, 15), quantity=0)
        engine = NestingEngine(sheet_w=50.0, sheet_h=200.0, clearance=0.0)
        candidates = engine.generate_candidates([fixed, auto])

        shelf = next((c for c in candidates if c.strategy_name == "shelf_grid"), None)
        assert shelf is not None
        assert shelf.count_per_part["fixed"] == 2
        _assert_no_overlaps(shelf, {"fixed": fixed, "auto": auto})

    def test_orientation_maximizes_count_per_free_rect(self) -> None:
        # 90x30 の部品は 300x100 のシートに、0°なら 3x3=9個、90°なら 10x1=10個。
        # 向きを行ごとの取れ数で選ぶため、多く取れる90°が選ばれる。
        part = Part(id="p", name="p", outer=_rect(90, 30), quantity=0)
        engine = NestingEngine(sheet_w=300.0, sheet_h=100.0, clearance=0.0)
        candidates = engine.generate_candidates([part])

        shelf = next((c for c in candidates if c.strategy_name == "shelf_grid"), None)
        assert shelf is not None
        assert shelf.count_per_part["p"] >= 10
        _assert_no_overlaps(shelf, {"p": part})

    def test_sibling_part_reuses_leftover_strip_within_its_own_quantity(self) -> None:
        # 回帰テスト: 部品Aの指定数を1つの矩形で満たした後に生じる余白帯は、部品Bが
        # まだ指定数に達していなければ(=Bを超過させることなく)自動的に埋まる。
        # A=200x300 x20個 は4列x5行のブロックとなり、右側に幅160mm(clearance込み)の
        # 帯を残す。B=100x100 x50個 は、1つの矩形(上部帯)だけでは満たしきれない数量
        # にしてあるため、既存の共有空き矩形プールにより残りが右側帯へ自動的に回る。
        large = Part(id="large", name="large", outer=_rect(200, 300), quantity=20)
        small = Part(id="small", name="small", outer=_rect(100, 100), quantity=50)
        engine = NestingEngine(sheet_w=1000.0, sheet_h=2000.0, clearance=5.0)

        shelf = next(
            candidate
            for candidate in engine.generate_candidates([large, small])
            if candidate.strategy_name == "shelf_grid"
        )

        # 指定数ちょうど(超過なし)ですべて配置される。
        assert shelf.count_per_part == {"large": 20, "small": 50}
        # 50個のうち一部が、大部品のブロック右端(x=820、4列x(200+clearance)mm)以降の
        # 余白帯に入っている。
        assert any(
            placement.part_id == "small" and placement.x >= 820.0
            for placement in shelf.placements
        )
        _assert_no_overlaps(shelf, {"large": large, "small": small})

    def test_smaller_free_rect_is_consumed_before_larger_one_shrinks_footprint(self) -> None:
        # 回帰テスト: Bの指定数が「上部の広い帯だけで丸ごと満たせてしまう」量(30個)の場合、
        # 貪欲選択が広い帯(9列x4行=36収容可)を優先すると、右側の狭い帯(1列x14行=14収容可)
        # が一切使われず取り残っていた(スクリーンショットで報告された見た目の無駄)。
        # 空き矩形自体が小さいものを優先する選択に変えたことで、まず右側帯へ入り、
        # 残りだけを上部帯で賄うため、上部帯の使用高さが縮小する。
        clearance = 5.0
        large = Part(id="large", name="large", outer=_rect(200, 300), quantity=20)
        small = Part(id="small", name="small", outer=_rect(100, 100), quantity=30)
        engine = NestingEngine(sheet_w=1000.0, sheet_h=2000.0, clearance=clearance)

        shelf = next(
            candidate
            for candidate in engine.generate_candidates([large, small])
            if candidate.strategy_name == "shelf_grid"
        )

        # 指定数ちょうど(超過なし)ですべて配置される。
        assert shelf.count_per_part == {"large": 20, "small": 30}

        large_cw, large_ch = 200 + clearance, 300 + clearance
        large_cols = int(1000.0 // large_cw)
        # 大部品ブロックの右端(=右側の狭い帯の開始x座標)、および上端(=上部帯の開始y座標)
        block_right_x = large_cols * large_cw
        top_strip_y = math.ceil(20 / large_cols) * large_ch

        side_strip_placements = [
            pl for pl in shelf.placements
            if pl.part_id == "small" and pl.x >= block_right_x - 1e-6 and pl.y < top_strip_y - 1e-6
        ]
        top_strip_placements = [
            pl for pl in shelf.placements if pl.part_id == "small" and pl.y >= top_strip_y - 1e-6
        ]

        # 右側の狭い帯が実際に使われている(以前は一切使われず空いたままだった)。
        assert side_strip_placements
        assert top_strip_placements
        # 上部帯の使用範囲が、右側帯を使わない場合の4行分より縮小している。
        small_ch = 100 + clearance
        max_top_y = max(pl.y for pl in top_strip_placements)
        assert max_top_y < top_strip_y + 3 * small_ch
        _assert_no_overlaps(shelf, {"large": large, "small": small})

    def test_right_side_remnant_is_reused(self) -> None:
        # 幅120のブロックを置いた後、右側に残る幅80の端材帯も空き矩形として再利用される。
        big = Part(id="big", name="big", outer=_rect(60, 100), quantity=2)
        small = Part(id="small", name="small", outer=_rect(40, 50), quantity=4)
        engine = NestingEngine(sheet_w=200.0, sheet_h=100.0, clearance=0.0)
        candidates = engine.generate_candidates([big, small])

        shelf = next((c for c in candidates if c.strategy_name == "shelf_grid"), None)
        assert shelf is not None
        assert shelf.count_per_part["big"] == 2
        assert shelf.count_per_part["small"] == 4
        _assert_no_overlaps(shelf, {"big": big, "small": small})


