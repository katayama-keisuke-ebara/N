"""エントリポイント: STEP ファイルを平面化して DXF / PNG / JSON を出力する。"""

from __future__ import annotations

import argparse
import sys

from src.log_setup import setup_logging
from src.pipeline import FlattenPipeline


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SolidWorks STEP → 平面 DXF 変換ツール (複数部品ネスティング等の対話操作は webapp を使用)"
    )
    p.add_argument("step_file", help="入力 STEP ファイルのパス")
    p.add_argument(
        "--output-dir", default="output", help="成果物の出力先ディレクトリ (デフォルト: output)"
    )
    p.add_argument(
        "--samples",
        type=int,
        default=50,
        help="エッジあたりのサンプリング点数 (デフォルト: 50)",
    )
    return p


def main() -> int:
    setup_logging()
    args = _build_parser().parse_args()

    pipeline = FlattenPipeline(samples_per_edge=args.samples)
    result = pipeline.run(args.step_file, args.output_dir)

    print(f"部品面積 (3D)     : {result['part_area']:.2f} mm²")
    print(f"展開面積          : {result['flattened_area']:.2f} mm²")
    print(f"面積差分率        : {result['area_diff_pct']:.4f} %")
    print(f"展開手法          : {result['best_method']}")
    if result.get("neutral_radius") is not None:
        print(f"中立面半径        : {result['neutral_radius']:.4f} mm")
    print(f"展開誤差率        : {result['error_rate']:.4f} %")
    print(f"展開品質          : {result['quality']}")
    print(f"DXF 出力先        : {result['dxf_path']}")
    print(f"PNG 出力先        : {result['png_path']}")
    print(f"JSON 出力先       : {result['result_path']}")

    # 品質 C は警告が pipeline 内で stderr に出力済み
    return 1 if result["quality"] == "C" else 0


if __name__ == "__main__":
    sys.exit(main())
