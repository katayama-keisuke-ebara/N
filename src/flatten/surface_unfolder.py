"""高精度展開アルゴリズム統合クラス。

アルゴリズム:
  1. 曲率解析 (CurvatureAnalyzer)
  2. 中立面推定 (_estimate_neutral_radius)
  3. 最小ひずみ平面化 (unfold_min_strain)  — 既存 FaceProjector を再利用
  4. LSCM — Least Squares Conformal Mapping
  5. ARAP — As-Rigid-As-Possible (初期値: LSCM, 局所-大域交互最適化)

品質グレード: A (<1%), B (<5%), C (≥5%)
"""

from __future__ import annotations

import math
from collections import defaultdict

import cadquery as cq
import numpy as np
from scipy import sparse
from scipy.sparse import linalg as splinalg

from .curvature_analyzer import CurvatureAnalyzer
from .models import CurvatureInfo, UnfoldResult


class SurfaceUnfolder:
    """全展開アルゴリズムをオーケストレーションし最良結果を返す。"""

    _QUALITY_A = 1.0   # error_rate < 1%  → A
    _QUALITY_B = 5.0   # error_rate < 5%  → B  (≥5% → C)

    def __init__(self, samples_per_edge: int = 50, tess_tol: float = 0.1) -> None:
        self._samples = samples_per_edge
        self._tol = tess_tol
        self._analyzer = CurvatureAnalyzer()

    # ================================================================== #
    # Public API
    # ================================================================== #

    def unfold(
        self,
        face: cq.Face,
        solid: cq.Shape | None = None,
    ) -> UnfoldResult:
        """全アルゴリズムを実行し展開誤差が最小の結果を返す。"""
        neutral_r = self._estimate_neutral_radius(solid, face) if solid else None

        results: list[UnfoldResult] = []

        r = self._safe_call(lambda: self.unfold_min_strain(face, neutral_r))
        if r:
            results.append(r)

        r = self._safe_call(lambda: self.unfold_lscm(face))
        if r:
            results.append(r)

        r = self._safe_call(lambda: self.unfold_arap(face))
        if r:
            results.append(r)

        if not results:
            # フォールバック: min_strain は必ず成功するはず
            results = [self.unfold_min_strain(face, neutral_r)]

        best = self._select_best(results)
        best.neutral_radius = neutral_r
        if best.quality == "C":
            best.warning = (
                f"[警告] 展開品質 C — 誤差率 {best.error_rate:.2f}% が許容値 5% を超えています。"
                " 部品の曲率が高すぎる可能性があります。"
            )
        return best

    def analyze_curvature(self, face: cq.Face) -> CurvatureInfo:
        return self._analyzer.analyze(face)

    def unfold_min_strain(
        self,
        face: cq.Face,
        neutral_radius: float | None = None,
    ) -> UnfoldResult:
        """最小ひずみ展開: CYLINDER は中立面展開、PLANE は法線投影。"""
        from .face_projector import FaceProjector  # 循環 import 回避

        proj = FaceProjector(self._samples)
        if face.geomType() == "CYLINDER":
            points = proj.project_to_xy(face, neutral_radius=neutral_radius)
        else:
            points = proj.project_to_xy(face)
        holes = proj.project_inner_wires_to_xy(face, neutral_radius)

        area_3d = face.Area()
        # 穴面積を控除しネット面積にする（LSCM/ARAP のメッシュ面積と単位を揃える）
        area_flat = self._shoelace(points) - sum(self._shoelace(h) for h in holes)
        error = abs(area_3d - area_flat) / area_3d * 100.0 if area_3d > 0 else 0.0
        return UnfoldResult(
            method="min_strain",
            points=points,
            holes=holes,
            area_3d=area_3d,
            area_flat=area_flat,
            error_rate=error,
            quality=self._compute_quality(error),
            neutral_radius=neutral_radius,
        )

    def unfold_lscm(self, face: cq.Face) -> UnfoldResult:
        """LSCM (Least Squares Conformal Mapping) — 角度保存展開。"""
        V, F = self._tessellate(face)
        UV = self._lscm(V, F)
        area_3d = face.Area()
        area_flat = self._uv_mesh_area(F, UV)
        error = abs(area_3d - area_flat) / area_3d * 100.0 if area_3d > 0 else 0.0
        outer, inners = self._ordered_boundaries(F, UV)
        points = [(float(UV[i, 0]), float(UV[i, 1])) for i in outer]
        holes = [[(float(UV[i, 0]), float(UV[i, 1])) for i in lp] for lp in inners]
        return UnfoldResult(
            method="lscm",
            points=points,
            holes=holes,
            area_3d=area_3d,
            area_flat=area_flat,
            error_rate=error,
            quality=self._compute_quality(error),
        )

    def unfold_arap(self, face: cq.Face, max_iter: int = 20) -> UnfoldResult:
        """ARAP (As-Rigid-As-Possible) — LSCM を初期値に剛性保存展開。"""
        V, F = self._tessellate(face)
        uv_init = self._lscm(V, F)
        UV = self._arap(V, F, uv_init, max_iter)
        area_3d = face.Area()
        area_flat = self._uv_mesh_area(F, UV)
        error = abs(area_3d - area_flat) / area_3d * 100.0 if area_3d > 0 else 0.0
        outer, inners = self._ordered_boundaries(F, UV)
        points = [(float(UV[i, 0]), float(UV[i, 1])) for i in outer]
        holes = [[(float(UV[i, 0]), float(UV[i, 1])) for i in lp] for lp in inners]
        return UnfoldResult(
            method="arap",
            points=points,
            holes=holes,
            area_3d=area_3d,
            area_flat=area_flat,
            error_rate=error,
            quality=self._compute_quality(error),
        )

    # ================================================================== #
    # Private — neutral radius
    # ================================================================== #

    def _estimate_neutral_radius(
        self, solid: cq.Shape, outer_face: cq.Face
    ) -> float | None:
        """外周円柱と同軸の内周円柱を探し中立面半径 (r_outer+r_inner)/2 を返す。"""
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Cylinder

            adaptor = BRepAdaptor_Surface(outer_face.wrapped)
            if adaptor.GetType() != GeomAbs_Cylinder:
                return None

            outer_cyl = adaptor.Cylinder()
            r_outer = outer_cyl.Radius()
            loc = outer_cyl.Axis().Location()
            cx, cy, cz = loc.X(), loc.Y(), loc.Z()

            r_inner: float | None = None
            for f in solid.Faces():
                if f.geomType() != "CYLINDER":
                    continue
                fa = BRepAdaptor_Surface(f.wrapped)
                if fa.GetType() != GeomAbs_Cylinder:
                    continue
                cyl = fa.Cylinder()
                fl = cyl.Axis().Location()
                dist = ((fl.X() - cx) ** 2 + (fl.Y() - cy) ** 2 + (fl.Z() - cz) ** 2) ** 0.5
                if dist < 1.0 and cyl.Radius() < r_outer * 0.99:
                    if r_inner is None or cyl.Radius() > r_inner:
                        r_inner = cyl.Radius()

            return (r_outer + r_inner) / 2.0 if r_inner is not None else None
        except Exception:
            return None

    # ================================================================== #
    # Private — tessellation
    # ================================================================== #

    def _tessellate(self, face: cq.Face) -> tuple[np.ndarray, np.ndarray]:
        """面を三角形メッシュ化し (V: N×3, F: M×3) を返す。"""
        raw_v, raw_f = face.tessellate(self._tol)
        V = np.array([[v.x, v.y, v.z] for v in raw_v], dtype=float)
        F = np.asarray(raw_f, dtype=int)
        return V, F

    # ================================================================== #
    # Private — LSCM
    # ================================================================== #

    def _lscm(self, V: np.ndarray, F: np.ndarray) -> np.ndarray:
        """LSCM で UV (N×2) を計算する。頂点 0,1 をピン固定。"""
        N, M = len(V), len(F)
        if N < 3 or M < 1:
            return np.zeros((N, 2))

        rows: list[int] = []
        cols: list[int] = []
        vals: list[float] = []

        for t_idx, (vi, vj, vk) in enumerate(F):
            e1 = V[vj] - V[vi]
            e2 = V[vk] - V[vi]
            len_e1 = float(np.linalg.norm(e1))
            if len_e1 < 1e-12:
                continue
            len_e2 = float(np.linalg.norm(e2))

            # 三角形の局所 2D 座標 (vi = 原点)
            cos_t = float(np.dot(e1, e2)) / (len_e1 * len_e2 + 1e-15)
            cos_t = float(np.clip(cos_t, -1.0, 1.0))
            sin_t = math.sqrt(max(0.0, 1.0 - cos_t ** 2))
            p_j = complex(len_e1, 0.0)
            p_k = complex(len_e2 * cos_t, len_e2 * sin_t)

            if abs(p_k) < 1e-12:
                continue
            # 共形比率 c = p_j / p_k
            c = p_j / p_k
            a, b = c.real, c.imag

            # 変数レイアウト: x = [u_0..u_{N-1}, v_0..v_{N-1}]
            # 実部方程式: (a-1)u_i + u_j - a*u_k - b*v_i + b*v_k = 0
            # 虚部方程式:  b*u_i - b*u_k + (a-1)v_i + v_j - a*v_k = 0
            r0, r1 = 2 * t_idx, 2 * t_idx + 1

            def _add(r: int, c_: int, v: float) -> None:
                rows.append(r); cols.append(c_); vals.append(v)

            _add(r0, vi, a - 1);  _add(r0, vj, 1.0);   _add(r0, vk, -a)
            _add(r0, N + vi, -b);                         _add(r0, N + vk, b)
            _add(r1, vi, b);                               _add(r1, vk, -b)
            _add(r1, N + vi, a - 1); _add(r1, N + vj, 1.0); _add(r1, N + vk, -a)

        A = sparse.coo_matrix((vals, (rows, cols)), shape=(2 * M, 2 * N)).tocsr()

        d01 = float(np.linalg.norm(V[1] - V[0])) if N > 1 else 1.0
        # ピン: u[0]=0, u[1]=d01, v[0]=0, v[1]=0
        pinned = {0: 0.0, 1: d01, N: 0.0, N + 1: 0.0}
        free_idx = [i for i in range(2 * N) if i not in pinned]

        if not free_idx:
            x = np.zeros(2 * N)
            for idx, v in pinned.items():
                x[idx] = v
            return np.column_stack([x[:N], x[N:]])

        pin_cols = list(pinned.keys())
        pin_vals_arr = np.array([pinned[c_] for c_ in pin_cols])
        rhs = -(A[:, pin_cols] @ pin_vals_arr)

        A_free = A[:, free_idx]
        AtA = (A_free.T @ A_free).tocsr()
        Atb = A_free.T @ rhs

        try:
            x_free = splinalg.spsolve(AtA, Atb)
            if np.any(np.isnan(x_free)):
                raise ValueError("NaN")
        except Exception:
            x_free = np.zeros(len(free_idx))

        x = np.zeros(2 * N)
        for local_i, global_i in enumerate(free_idx):
            x[global_i] = float(x_free[local_i])
        for idx, v in pinned.items():
            x[idx] = v

        return np.column_stack([x[:N], x[N:]])

    # ================================================================== #
    # Private — ARAP
    # ================================================================== #

    def _arap(
        self,
        V: np.ndarray,
        F: np.ndarray,
        uv_init: np.ndarray,
        max_iter: int,
    ) -> np.ndarray:
        """ARAP 局所-大域交互最適化。初期値 uv_init から収束まで反復する。"""
        N = len(V)
        UV = uv_init.copy()
        E_ref = uv_init.copy()  # 参照フレーム (LSCM 結果)

        # 辺のウェイト (辺の登場回数 = 1 or 2)
        edge_w: dict[tuple[int, int], int] = {}
        for tri in F:
            for a, b in [(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])]:
                key = (min(a, b), max(a, b))
                edge_w[key] = edge_w.get(key, 0) + 1

        # 隣接リスト {i: [(j, w), ...]}
        adj: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for (a, b), w in edge_w.items():
            adj[a].append((b, w))
            adj[b].append((a, w))

        # 重み付きグラフ Laplacian
        L = self._weighted_laplacian(N, edge_w)

        d01 = float(np.linalg.norm(V[1] - V[0])) if N > 1 else 1.0
        pinned = {0: np.array([0.0, 0.0]), 1: np.array([d01, 0.0])}
        free = [i for i in range(N) if i not in pinned]
        if not free:
            return UV

        L_free = L[np.ix_(free, free)].tocsr()

        for _ in range(max_iter):
            # ローカルステップ: 頂点 i ごとに最良 2D 回転 R_i を SVD で求める
            R: dict[int, np.ndarray] = {}
            for i in range(N):
                S = np.zeros((2, 2))
                for j, w in adj[i]:
                    e_ref = E_ref[j] - E_ref[i]
                    e_cur = UV[j] - UV[i]
                    S += w * np.outer(e_cur, e_ref)
                try:
                    U, _, Vt = np.linalg.svd(S)
                    Ri = U @ Vt
                    if np.linalg.det(Ri) < 0:
                        U[:, -1] *= -1
                        Ri = U @ Vt
                except Exception:
                    Ri = np.eye(2)
                R[i] = Ri

            # グローバルステップ: ARAP 系 L * UV = -b を解く
            # b[a] = Σ_{j∈N(a)} w * (R_a + R_j)/2 * (E_ref_j - E_ref_a)
            rhs = np.zeros((N, 2))
            for (a, b_), w in edge_w.items():
                e_ref = E_ref[b_] - E_ref[a]
                Re = ((R[a] + R[b_]) * 0.5) @ e_ref
                rhs[a] += w * Re
                rhs[b_] -= w * Re

            # ARAP 系は L * UV = -b (符号反転)
            rhs = -rhs

            # ピン固定の寄与を RHS に統合
            for pin_i, pin_uv in pinned.items():
                L_col = np.asarray(L[:, pin_i].todense()).flatten()
                rhs -= np.outer(L_col, pin_uv)

            rhs_free = rhs[free]

            try:
                UV_new = UV.copy()
                for axis in range(2):
                    x_sol = splinalg.spsolve(L_free, rhs_free[:, axis])
                    for loc_i, glob_i in enumerate(free):
                        UV_new[glob_i, axis] = float(x_sol[loc_i])
            except Exception:
                break

            for pin_i, pin_uv in pinned.items():
                UV_new[pin_i] = pin_uv

            if float(np.linalg.norm(UV_new - UV)) < 1e-6:
                UV = UV_new
                break
            UV = UV_new

        return UV

    def _weighted_laplacian(
        self, N: int, edge_w: dict[tuple[int, int], int]
    ) -> sparse.csr_matrix:
        """辺ウェイトによる重み付きグラフ Laplacian を構築する。"""
        rows, cols, vals = [], [], []
        for (a, b), w in edge_w.items():
            rows += [a, b, a, b]
            cols += [b, a, a, b]
            vals += [float(w), float(w), -float(w), -float(w)]
        return sparse.coo_matrix((vals, (rows, cols)), shape=(N, N)).tocsr()

    # ================================================================== #
    # Private — boundary extraction
    # ================================================================== #

    def _ordered_boundaries(
        self, F, UV
    ):
        """境界ループを全収集し (outer_loop, [inner_loops...]) を返す。"""
        from collections import defaultdict as _dd
        edge_cnt = _dd(int)
        for tri in F:
            i, j, k = int(tri[0]), int(tri[1]), int(tri[2])
            for a, b in [(i, j), (j, k), (k, i)]:
                edge_cnt[(min(a, b), max(a, b))] += 1
        b_next = _dd(list)
        for tri in F:
            i, j, k = int(tri[0]), int(tri[1]), int(tri[2])
            for a, b in [(i, j), (j, k), (k, i)]:
                if edge_cnt[(min(a, b), max(a, b))] == 1:
                    b_next[a].append(b)
        if not b_next:
            return list(range(len(UV))), []
        visited = set()
        loops = []
        for start in sorted(b_next.keys()):
            if start in visited:
                continue
            loop = [start]
            visited.add(start)
            cur = b_next[start][0] if b_next[start] else -1
            while cur != start and cur != -1 and cur not in visited:
                loop.append(cur)
                visited.add(cur)
                nexts = [v for v in b_next.get(cur, []) if v not in visited or v == start]
                cur = nexts[0] if nexts else -1
            loops.append(loop)
        if not loops:
            return list(range(len(UV))), []

        def _area(lp):
            pts = UV[lp]
            n = len(pts)
            if n < 3:
                return 0.0
            return abs(sum(pts[i][0]*pts[(i+1)%n][1]-pts[(i+1)%n][0]*pts[i][1] for i in range(n))) / 2.0

        outer = max(loops, key=_area)
        inners = [lp for lp in loops if lp is not outer]
        return outer, inners

    def _ordered_outer_boundary(self, F, UV):
        outer, _ = self._ordered_boundaries(F, UV)
        return outer


    def _uv_mesh_area(self, F: np.ndarray, UV: np.ndarray) -> float:
        """全三角形の UV 面積の総和を返す。"""
        total = 0.0
        for i, j, k in F:
            e1 = UV[j] - UV[i]
            e2 = UV[k] - UV[i]
            total += abs(e1[0] * e2[1] - e1[1] * e2[0]) / 2.0
        return total

    def _shoelace(self, points: list[tuple[float, float]]) -> float:
        n = len(points)
        if n < 3:
            return 0.0
        s = sum(
            points[i][0] * points[(i + 1) % n][1]
            - points[(i + 1) % n][0] * points[i][1]
            for i in range(n)
        )
        return abs(s) / 2.0

    def _compute_quality(self, error_rate: float) -> str:
        if error_rate < self._QUALITY_A:
            return "A"
        if error_rate < self._QUALITY_B:
            return "B"
        return "C"

    def _select_best(self, results: list[UnfoldResult]) -> UnfoldResult:
        return min(results, key=lambda r: r.error_rate)

    def _safe_call(self, fn) -> UnfoldResult | None:
        try:
            return fn()
        except Exception:
            return None
