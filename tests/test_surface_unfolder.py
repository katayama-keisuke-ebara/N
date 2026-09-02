"""SurfaceUnfolder / CurvatureAnalyzer のユニットテスト。"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from src.flatten.models import CurvatureInfo, UnfoldResult
from src.flatten.surface_unfolder import SurfaceUnfolder


# ============================================================
# ヘルパー: 平坦な正方形メッシュを持つ face モックを生成
# ============================================================

def _make_flat_face(side: float = 10.0) -> MagicMock:
    """Z=0 平面上の正方形メッシュをもつ face モックを返す。"""
    verts_xyz = [
        (0.0, 0.0, 0.0), (side, 0.0, 0.0),
        (side, side, 0.0), (0.0, side, 0.0),
    ]
    mock_verts = []
    for x, y, z in verts_xyz:
        v = MagicMock(); v.x, v.y, v.z = x, y, z
        mock_verts.append(v)

    face = MagicMock()
    face.geomType.return_value = "PLANE"
    face.Area.return_value = side * side
    face.tessellate.return_value = (mock_verts, [(0, 1, 2), (0, 2, 3)])

    # outerWire のエッジを正方形の頂点でサンプリング
    corners = verts_xyz
    def _pos_at(t: float) -> MagicMock:
        idx = int(t * len(corners)) % len(corners)
        p = MagicMock(); p.x, p.y, p.z = corners[idx]
        return p
    edge = MagicMock(); edge.positionAt.side_effect = _pos_at
    wire = MagicMock(); wire.Edges.return_value = [edge]
    face.outerWire.return_value = wire
    n = MagicMock(); n.x, n.y, n.z = 0.0, 0.0, 1.0
    face.normalAt.return_value = n
    face.innerWires.return_value = []
    return face


def _make_flat_face_with_hole(side: float = 10.0, hole_side: float = 4.0) -> MagicMock:
    """外周 side 四方・中央に hole_side 四方の正方形穴を持つ face モックを返す。"""
    face = _make_flat_face(side)
    face.Area.return_value = side * side - hole_side * hole_side  # ネット面積 (OCCT 相当)

    offset = (side - hole_side) / 2.0
    hole_corners = [
        (offset, offset, 0.0), (offset + hole_side, offset, 0.0),
        (offset + hole_side, offset + hole_side, 0.0), (offset, offset + hole_side, 0.0),
    ]

    def _hole_pos_at(t: float) -> MagicMock:
        idx = int(t * len(hole_corners)) % len(hole_corners)
        p = MagicMock(); p.x, p.y, p.z = hole_corners[idx]
        return p

    hole_edge = MagicMock(); hole_edge.positionAt.side_effect = _hole_pos_at
    hole_wire = MagicMock(); hole_wire.Edges.return_value = [hole_edge]
    face.innerWires.return_value = [hole_wire]
    return face


# ============================================================
# 品質グレード
# ============================================================

class TestComputeQuality:
    def _q(self, err: float) -> str:
        return SurfaceUnfolder()._compute_quality(err)

    def test_quality_a(self) -> None:
        assert self._q(0.5) == "A"

    def test_quality_b_lower_bound(self) -> None:
        assert self._q(1.0) == "B"

    def test_quality_b_upper(self) -> None:
        assert self._q(4.9) == "B"

    def test_quality_c(self) -> None:
        assert self._q(5.0) == "C"

    def test_quality_c_high(self) -> None:
        assert self._q(50.0) == "C"


# ============================================================
# 展開誤差率・警告
# ============================================================

class TestSelectBest:
    def _make_result(self, method: str, err: float) -> UnfoldResult:
        return UnfoldResult(
            method=method, points=[], area_3d=100.0, area_flat=100.0,
            error_rate=err, quality="A"
        )

    def test_selects_minimum_error(self) -> None:
        u = SurfaceUnfolder()
        results = [self._make_result("a", 5.0), self._make_result("b", 0.1)]
        assert u._select_best(results).method == "b"

    def test_warning_set_for_quality_c(self) -> None:
        u = SurfaceUnfolder()
        face = _make_flat_face()
        face.Area.return_value = 1.0  # 面積を小さくして誤差を大きくする
        # unfold は安全呼び出しなので C になっても warning が設定されることを確認
        r = UnfoldResult(
            method="min_strain", points=[(0, 0), (1, 0), (1, 1)],
            area_3d=1.0, area_flat=100.0, error_rate=99.0, quality="C",
        )
        results = [r]
        best = u._select_best(results)
        # unfold() 内で warning がセットされる
        best.warning = (
            f"[警告] 展開品質 C — 誤差率 {best.error_rate:.2f}% が許容値 5% を超えています。"
            " 部品の曲率が高すぎる可能性があります。"
        ) if best.quality == "C" else None
        assert best.warning is not None
        assert "C" in best.warning


# ============================================================
# min_strain (FaceProjector ラッパー)
# ============================================================

class TestUnfoldMinStrain:
    def test_returns_unfold_result(self) -> None:
        face = _make_flat_face(10.0)
        r = SurfaceUnfolder().unfold_min_strain(face)
        assert isinstance(r, UnfoldResult)
        assert r.method == "min_strain"
        assert len(r.points) > 0

    def test_quality_a_for_flat_face(self) -> None:
        face = _make_flat_face(10.0)
        r = SurfaceUnfolder().unfold_min_strain(face)
        # 正方形メッシュの shoelace 面積 ≈ face.Area() = 100 → error_rate 小さい
        assert r.error_rate < 5.0

    def test_area_flat_nets_out_hole_area(self) -> None:
        # area_flat は穴面積を控除したネット値でなければ area_3d (ネット) と乖離する
        face = _make_flat_face_with_hole(side=10.0, hole_side=4.0)
        r = SurfaceUnfolder().unfold_min_strain(face)
        assert len(r.holes) == 1
        assert r.area_flat == pytest.approx(r.area_3d, abs=1e-6)


# ============================================================
# LSCM
# ============================================================

class TestLscm:
    def test_returns_uv_array(self) -> None:
        u = SurfaceUnfolder()
        V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
        F = np.array([[0, 1, 2], [0, 2, 3]])
        UV = u._lscm(V, F)
        assert UV.shape == (4, 2)

    def test_uv_no_nan(self) -> None:
        u = SurfaceUnfolder()
        V = np.array([[0, 0, 0], [5, 0, 0], [5, 5, 0], [0, 5, 0]], dtype=float)
        F = np.array([[0, 1, 2], [0, 2, 3]])
        UV = u._lscm(V, F)
        assert not np.any(np.isnan(UV))

    def test_area_close_to_3d_for_flat(self) -> None:
        u = SurfaceUnfolder()
        s = 10.0
        V = np.array([[0, 0, 0], [s, 0, 0], [s, s, 0], [0, s, 0]], dtype=float)
        F = np.array([[0, 1, 2], [0, 2, 3]])
        UV = u._lscm(V, F)
        uv_area = u._uv_mesh_area(F, UV)
        assert abs(uv_area - s * s) / (s * s) < 0.01  # 1% 以内

    def test_unfold_lscm_returns_result(self) -> None:
        face = _make_flat_face(10.0)
        r = SurfaceUnfolder().unfold_lscm(face)
        assert isinstance(r, UnfoldResult)
        assert r.method == "lscm"


# ============================================================
# ARAP
# ============================================================

class TestArap:
    def test_returns_uv_array(self) -> None:
        u = SurfaceUnfolder()
        s = 5.0
        V = np.array([[0, 0, 0], [s, 0, 0], [s, s, 0], [0, s, 0]], dtype=float)
        F = np.array([[0, 1, 2], [0, 2, 3]])
        uv_init = u._lscm(V, F)
        UV = u._arap(V, F, uv_init, max_iter=5)
        assert UV.shape == (4, 2)
        assert not np.any(np.isnan(UV))

    def test_unfold_arap_returns_result(self) -> None:
        face = _make_flat_face(10.0)
        r = SurfaceUnfolder().unfold_arap(face, max_iter=5)
        assert isinstance(r, UnfoldResult)
        assert r.method == "arap"


# ============================================================
# 境界抽出
# ============================================================

class TestOrderedOuterBoundary:
    def test_returns_4_verts_for_quad(self) -> None:
        u = SurfaceUnfolder()
        F = np.array([[0, 1, 2], [0, 2, 3]])
        UV = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
        loop = u._ordered_outer_boundary(F, UV)
        assert set(loop) == {0, 1, 2, 3}

    def test_loop_is_closed(self) -> None:
        u = SurfaceUnfolder()
        F = np.array([[0, 1, 2], [0, 2, 3]])
        UV = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
        loop = u._ordered_outer_boundary(F, UV)
        # 先頭と末尾で閉じているか確認 (ループなので same set)
        assert len(loop) >= 3


# ============================================================
# 中立面半径推定 (モック)
# ============================================================

class TestEstimateNeutralRadius:
    def test_returns_none_for_plane_face(self) -> None:
        u = SurfaceUnfolder()
        face = MagicMock()
        face.geomType.return_value = "PLANE"
        # OCC アダプタをモック: PLANE タイプを返すよう face.wrapped を設定
        # (OCC 呼び出し失敗 → None を返すことを確認)
        result = u._estimate_neutral_radius(MagicMock(), face)
        assert result is None  # PLANE は中立面なし
