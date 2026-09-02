from __future__ import annotations

import logging
import math

import cadquery as cq
import numpy as np

logger = logging.getLogger(__name__)


class FaceProjector:
    """面の外側輪郭を平坦化し、2D ポリゴン点列を生成する。

    - PLANE 面: 法線を Z 軸に揃える回転行列で投影
    - CYLINDER 面: 円柱アンローリング（展開）
    """

    def __init__(self, samples_per_edge: int = 50) -> None:
        self._samples = samples_per_edge

    def project_to_xy(
        self,
        face: cq.Face,
        neutral_radius: float | None = None,
    ) -> list[tuple[float, float]]:
        """面種別を判定し、適切な平坦化手法で 2D 点列を返す。

        neutral_radius: CYLINDER 面のみ有効。中立面半径で弧長をスケールする。
        """
        if face.geomType() == "CYLINDER":
            return self._develop_cylinder(face, neutral_radius)
        normal = self._get_face_normal(face)
        R = self.compute_rotation_matrix(normal)
        points_3d = self._sample_wire(face.outerWire())
        rotated = [R @ np.array(p) for p in points_3d]
        return [(float(p[0]), float(p[1])) for p in rotated]

    def project_inner_wires_to_xy(
        self,
        face: cq.Face,
        neutral_radius: float | None = None,
    ) -> list[list[tuple[float, float]]]:
        """内側ワイヤ（穴）を外周と同じ変換で 2D 投影する。"""
        inner_wires = face.innerWires()
        if not inner_wires:
            return []
        if face.geomType() == "CYLINDER":
            return [self._develop_wire_cylinder(face, w, neutral_radius) for w in inner_wires]
        normal = self._get_face_normal(face)
        R = self.compute_rotation_matrix(normal)
        holes = []
        for wire in inner_wires:
            pts_3d = self._sample_wire(wire)
            rotated = [R @ np.array(p) for p in pts_3d]
            holes.append([(float(p[0]), float(p[1])) for p in rotated])
        return holes

    def compute_rotation_matrix(
        self, normal: tuple[float, float, float]
    ) -> np.ndarray:
        """法線ベクトルを Z 軸に揃える回転行列を Rodrigues 公式で計算する。"""
        n = np.array(normal, dtype=float)
        n = n / np.linalg.norm(n)
        z = np.array([0.0, 0.0, 1.0])

        if np.allclose(n, z):
            return np.eye(3)

        if np.allclose(n, -z):
            # X 軸周り 180° 回転
            return np.array(
                [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]
            )

        v = np.cross(n, z)
        c = float(np.dot(n, z))
        s = float(np.linalg.norm(v))

        # v の反対称行列
        vx = np.array(
            [
                [0.0, -v[2], v[1]],
                [v[2], 0.0, -v[0]],
                [-v[1], v[0], 0.0],
            ]
        )
        return np.eye(3) + vx + vx @ vx * ((1.0 - c) / (s**2))

    def get_polygon_area(self, points: list[tuple[float, float]]) -> float:
        """靴紐公式 (Shoelace formula) で 2D ポリゴンの面積を算出する。"""
        n = len(points)
        if n < 3:
            return 0.0
        area = 0.0
        for i in range(n):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        return abs(area) / 2.0

    # ------------------------------------------------------------------
    # private
    # ------------------------------------------------------------------

    def _develop_cylinder(
        self,
        face: cq.Face,
        neutral_radius: float | None = None,
    ) -> list[tuple[float, float]]:
        """円柱面をアンローリングし、展開した 2D 点列を返す。

        角度は面表面半径で計算し、弧長スケールに neutral_radius を使う。
        neutral_radius が None の場合は面表面半径をそのまま使用する。
        """
        from OCP.BRepAdaptor import BRepAdaptor_Surface

        adaptor = BRepAdaptor_Surface(face.wrapped)
        cyl = adaptor.Cylinder()
        params = self._cylinder_unroll_params(cyl, neutral_radius)
        pts_3d = self._sample_wire(face.outerWire())
        raw = self._unroll_points(pts_3d, params)
        if not raw:
            return []
        min_u = min(p[0] for p in raw)
        min_v = min(p[1] for p in raw)
        return [(p[0] - min_u, p[1] - min_v) for p in raw]

    def _develop_wire_cylinder(
        self,
        face: cq.Face,
        wire: cq.Wire,
        neutral_radius: float | None = None,
    ) -> list[tuple[float, float]]:
        """内側ワイヤを外周と同じ円柱座標系で展開する。"""
        from OCP.BRepAdaptor import BRepAdaptor_Surface

        adaptor = BRepAdaptor_Surface(face.wrapped)
        params = self._cylinder_unroll_params(adaptor.Cylinder(), neutral_radius)
        outer_raw = self._unroll_points(self._sample_wire(face.outerWire()), params)
        min_u = min(p[0] for p in outer_raw) if outer_raw else 0.0
        min_v = min(p[1] for p in outer_raw) if outer_raw else 0.0
        inner_raw = self._unroll_points(self._sample_wire(wire), params)
        return [(p[0] - min_u, p[1] - min_v) for p in inner_raw]

    @staticmethod
    def _cylinder_unroll_params(cyl, neutral_radius: float | None) -> dict:
        """円柱アンローリングに必要なパラメータをまとめて返す。"""
        surface_radius = cyl.Radius()
        ax1 = cyl.Axis()
        loc = ax1.Location()
        center = np.array([loc.X(), loc.Y(), loc.Z()])
        ax_dir = ax1.Direction()
        axis_vec = np.array([ax_dir.X(), ax_dir.Y(), ax_dir.Z()])
        x_dir = cyl.XAxis().Direction()
        ref_vec = np.array([x_dir.X(), x_dir.Y(), x_dir.Z()])
        y_vec = np.cross(axis_vec, ref_vec)
        arc_radius = neutral_radius if neutral_radius is not None else surface_radius
        return dict(
            center=center, axis_vec=axis_vec, ref_vec=ref_vec,
            y_vec=y_vec, surface_radius=surface_radius, arc_radius=arc_radius,
        )

    @staticmethod
    def _unroll_points(
        pts_3d: list[tuple[float, float, float]], params: dict
    ) -> list[tuple[float, float]]:
        """3D 点列を円柱パラメータで 2D アンローリング座標に変換する。"""
        center = params["center"]
        axis_vec = params["axis_vec"]
        ref_vec = params["ref_vec"]
        y_vec = params["y_vec"]
        sr = params["surface_radius"]
        ar = params["arc_radius"]
        raw: list[tuple[float, float]] = []
        for p3d in pts_3d:
            v = np.array(p3d) - center
            h = float(np.dot(v, axis_vec))
            v_perp = v - h * axis_vec
            cos_a = float(np.clip(np.dot(v_perp, ref_vec) / sr, -1.0, 1.0))
            sin_a = float(np.clip(np.dot(v_perp, y_vec) / sr, -1.0, 1.0))
            raw.append((ar * math.atan2(sin_a, cos_a), h))
        return raw

    def _get_face_normal(
        self, face: cq.Face
    ) -> tuple[float, float, float]:
        n = face.normalAt()
        return (n.x, n.y, n.z)

    def _sample_wire(
        self, wire: cq.Wire
    ) -> list[tuple[float, float, float]]:
        """ワイヤのエッジを接続順にサンプリングして 3D 点列を返す。"""
        edges = wire.Edges()
        if not edges:
            return []
        chained = self._chain_wire_edges(edges)
        points: list[tuple[float, float, float]] = []
        for edge, rev in chained:
            for i in range(self._samples):
                t = i / self._samples
                if rev:
                    t = 1.0 - t
                p = edge.positionAt(t)
                points.append((p.x, p.y, p.z))
        return points

    def _sample_outer_wire(
        self, face: cq.Face
    ) -> list[tuple[float, float, float]]:
        pts = self._sample_wire(face.outerWire())
        if not pts:
            raise ValueError("外側ワイヤにエッジが存在しません")
        return pts

    def _chain_wire_edges(self, edges: list) -> list[tuple]:
        """wire.Edges() の順序に依存せず、エッジを端点で連鎖させる。

        Returns list of (edge, is_reversed) tuples forming a closed polygon.
        """
        tol = 1e-3
        remaining = list(edges)
        chained: list[tuple] = [(remaining.pop(0), False)]

        def _end(edge, rev: bool) -> tuple:
            p = edge.positionAt(0 if rev else 1)
            return (p.x, p.y, p.z)

        def _close(a: tuple, b: tuple) -> bool:
            return all(abs(x - y) < tol for x, y in zip(a, b))

        while remaining:
            cur_end = _end(*chained[-1])
            matched = False
            for i, e in enumerate(remaining):
                s = e.positionAt(0)
                if _close(cur_end, (s.x, s.y, s.z)):
                    chained.append((remaining.pop(i), False))
                    matched = True
                    break
                t_pt = e.positionAt(1)
                if _close(cur_end, (t_pt.x, t_pt.y, t_pt.z)):
                    chained.append((remaining.pop(i), True))
                    matched = True
                    break
            if not matched:
                # ワイヤが断裂しており順序を保証できないため、残りをそのまま追加する
                logger.warning("ワイヤのエッジ連鎖に失敗しました。頂点順序が不正確になる可能性があります")
                for e in remaining:
                    chained.append((e, False))
                break
        return chained
