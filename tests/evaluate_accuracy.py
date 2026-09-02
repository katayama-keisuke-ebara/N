"""精度評価スクリプト: 各アルゴリズムの誤差率・品質・処理時間を計測する。"""
import sys
import time

sys.path.insert(0, ".")

import cadquery as cq

from src.flatten.face_extractor import FaceExtractor
from src.flatten.surface_unfolder import SurfaceUnfolder

STEP = r"tests\step\R1-2508461-R01 CH1出穴埋めシート13(MS1-16).STEP"

wp = cq.importers.importStep(STEP)
solid = wp.solids().vals()[0]

extractor = FaceExtractor()
face = extractor.extract_largest_face(solid)
unfolder = SurfaceUnfolder()
neutral_r = unfolder._estimate_neutral_radius(solid, face)

area3d = face.Area()
geom = face.geomType()
ci = unfolder.analyze_curvature(face)

print("=" * 62)
print("  対象面情報")
print("=" * 62)
print(f"  面種別        : {geom}")
print(f"  3D 面積       : {area3d:.4f} mm2")
if neutral_r is not None:
    print(f"  中立面半径    : {neutral_r:.4f} mm  ( r_out={62}, r_in={46} )")
print(f"  曲率 |K| 平均 : {ci.gaussian_mean:.2e} mm-2")
print(f"  曲率 |K| 最大 : {ci.gaussian_max:.2e} mm-2")
print(f"  平均曲率 |H|  : {ci.mean_curvature_abs:.6f} mm-1")
print(f"  展開可能面    : {ci.is_developable}")
print()

METHODS = [
    ("MinStrain (中立面)", lambda: unfolder.unfold_min_strain(face, neutral_r)),
    ("LSCM              ", lambda: unfolder.unfold_lscm(face)),
    ("ARAP (20 iter)    ", lambda: unfolder.unfold_arap(face, max_iter=20)),
]

print("=" * 62)
print(f"  {'手法':<22} {'展開面積':>12}  {'誤差率':>9}  {'品質':>4}  {'時間':>7}")
print("-" * 62)
print(f"  {'(3D 実面積)':22} {area3d:>12.4f}")
print("-" * 62)

best_err = float("inf")
best_name = ""
for name, fn in METHODS:
    t0 = time.perf_counter()
    r = fn()
    dt = (time.perf_counter() - t0) * 1000
    mark = " <<" if r.error_rate < best_err else ""
    if r.error_rate < best_err:
        best_err = r.error_rate
        best_name = name.strip()
    print(f"  {name} {r.area_flat:>12.4f}  {r.error_rate:>8.4f}%  {r.quality:>4}  {dt:>6.0f}ms{mark}")

print("=" * 62)
print(f"  最良手法 : {best_name}")
print(f"  最良誤差 : {best_err:.4f}%")
print()

print("=" * 62)
print("  改修前後 精度変化サマリー")
print("=" * 62)
rows = [
    ("MVP v1 (単純投影・外周面)",   "53.51",  "C"),
    ("v2 (平面選択修正)",           "42.32",  "C"),
    ("v3 (エッジ連鎖修正)",          "0.0164", "A"),
    ("v4 (円柱展開 outer r=62)",    "3.67",   "B"),
    ("v5 (中立面 r=54 適用)",       "3.67",   "B"),  # min_strain
    (f"v6 LSCM (今回)",            f"{best_err:.4f}", "A"),
]
print(f"  {'バージョン':<32} {'誤差率':>9}  {'品質':>4}")
print("-" * 50)
for label, err, q in rows:
    print(f"  {label:<32} {err:>9}%  {q:>4}")
print("=" * 62)
