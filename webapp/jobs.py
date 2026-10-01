"""ジョブ実行管理: ProcessPoolExecutor でパイプライン処理をプロセス分離して実行する。

QThread(gui/services/pipeline_service.py) の代替。cadquery/OCP のネイティブクラッシュが
Web サーバー本体プロセスへ波及しないよう、各ジョブは別プロセスで実行する。
"""

from __future__ import annotations

import logging
import multiprocessing
import re
import threading
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from src.nesting.geometry_utils import (
    bounds,
    make_circle_polygon,
    make_rectangle_polygon,
    shoelace_area,
)
from webapp import db, storage

logger = logging.getLogger(__name__)

MAX_WORKERS = 2

_ERROR_MESSAGES_BY_NAME = {
    "StepReadError": "STEP ファイルの読み込みに失敗しました",
    "UnfoldError": "面の展開処理に失敗しました",
    "DxfExportError": "DXF ファイルの出力に失敗しました",
    "PngExportError": "PNG プレビューの出力に失敗しました",
    "ResultWriteError": "結果 JSON の出力に失敗しました",
}


def _safe_stem(name: str) -> str:
    """アップロード元ファイル名から出力サブフォルダ名として安全な文字列を作る。"""
    stem = Path(name).stem
    stem = re.sub(r"[^\w\-. ぁ-んァ-ヶ一-龠]", "_", stem).strip() or "part"
    return stem


def _build_manual_result(part: dict, index: int) -> dict:
    shape_type = part["shape_type"]
    if shape_type == "rectangle":
        width = float(part["width"])
        height = float(part["height"])
        points = make_rectangle_polygon(width, height)
        display_name = f"矩形{index + 1}_{width:g}x{height:g}mm"
    else:
        radius = float(part["radius"])
        points = make_circle_polygon(radius)
        _, _, max_x, max_y = bounds(points)
        width = max_x
        height = max_y
        display_name = f"円形{index + 1}_R{radius:g}mm"

    area = shoelace_area(points)
    return {
        "part_area": area,
        "flattened_area": area,
        "area_diff_pct": 0.0,
        "points": points,
        "holes": [],
        "width": width,
        "height": height,
        "dxf_path": None,
        "png_path": None,
        "result_path": None,
        "best_method": "manual",
        "error_rate": 0.0,
        "quality": "A",
        "neutral_radius": None,
        "warning": None,
        "step_path": display_name,
        "display_name": display_name,
        "source_type": "manual",
        "quantity": part.get("quantity", 1),
        "part_id": f"manual_{index}_{shape_type}",
    }


def _run_job(
    job_id: str,
    parts: list[dict],
    manual_parts: list[dict],
    sheet_w: float,
    sheet_h: float,
    thickness: float,
    clearance: float,
    density: float,
    output_dir: str,
    progress_queue,
) -> dict:
    """ワーカープロセス内で実行される。src/pipeline.py 等のコアロジックは無改変のまま呼び出す。"""
    # cadquery import はコストが大きいため、実際にジョブが実行されるまで遅延させる。
    from src.exceptions import (
        DxfExportError,
        PngExportError,
        ResultWriteError,
        StepReadError,
        UnfoldError,
    )
    from src.export.dxf_exporter import DxfExporter
    from src.pipeline import FlattenPipeline
    from webapp.services.export_service import ExportService
    from webapp.services.nesting_service import NestingService

    known_errors = (StepReadError, UnfoldError, DxfExportError, PngExportError, ResultWriteError)

    pipeline = FlattenPipeline(samples_per_edge=50)
    results: list[dict] = []
    total_parts = len(parts) + len(manual_parts)
    for i, part in enumerate(parts):
        stored_path = part["stored_path"]
        orig_filename = part["orig_filename"]
        quantity = part["quantity"]
        progress_queue.put((job_id, f"処理中 ({i + 1}/{total_parts}): {orig_filename}"))
        part_output_dir = Path(output_dir) / f"{i}_{_safe_stem(orig_filename)}"
        try:
            result = pipeline.run(stored_path, part_output_dir)
        except known_errors as exc:
            prefix = _ERROR_MESSAGES_BY_NAME.get(type(exc).__name__, "処理に失敗しました")
            raise RuntimeError(f"{prefix} [{orig_filename}]: {exc}") from exc
        result["step_path"] = orig_filename
        result["quantity"] = quantity
        # 描画・集計側とキーを一致させるため、part_id を結果に明示的に保持する。
        result["part_id"] = f"{_safe_stem(orig_filename)}_{i}"
        results.append(result)

    for i, part in enumerate(manual_parts):
        result = _build_manual_result(part, i)
        progress_queue.put((
            job_id,
            f"処理中 ({len(parts) + i + 1}/{total_parts}): {result['display_name']}",
        ))
        results.append(result)

    progress_queue.put((job_id, "ネスティング計算中"))
    nesting_parts = [
        {
            "id": r["part_id"],
            "name": r.get("display_name") or _safe_stem(r["step_path"]),
            "points": r.get("points", []),
            "holes": r.get("holes", []),
            "quantity": r.get("quantity", 1),
        }
        for r in results
    ]
    candidates = NestingService().calculate_candidates(
        nesting_parts,
        sheet_w,
        sheet_h,
        clearance,
    )

    for i, candidate in enumerate(candidates):
        dxf_name = f"nesting_案{i + 1}_{candidate['strategy_name']}.dxf"
        try:
            DxfExporter().export_nesting(
                results, candidate, sheet_w, sheet_h, Path(output_dir) / dxf_name
            )
        except Exception:
            logger.warning("ネスティングDXF出力失敗 (job=%s, %s)", job_id, dxf_name, exc_info=True)

    if candidates:
        try:
            ExportService().append_to_summary(
                results,
                candidates[0],
                {
                    "sheet_w": sheet_w, "sheet_h": sheet_h, "thickness": thickness,
                    "clearance": clearance, "density": density,
                },
                output_dir=output_dir,
                candidates=candidates,
            )
        except Exception:
            logger.warning("summary.xlsx 追記失敗 (job=%s)", job_id, exc_info=True)

    progress_queue.put((job_id, "完了"))
    return {"results": results, "candidates": candidates}


class JobManager:
    """アプリ起動時に1つ生成し、app.state 経由で共有するジョブ実行マネージャ。"""

    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self._executor = ProcessPoolExecutor(max_workers=max_workers)
        self._mp_manager = multiprocessing.Manager()
        self._progress_queue = self._mp_manager.Queue()
        self._consumer_thread = threading.Thread(target=self._consume_progress, daemon=True)
        self._consumer_thread.start()

    def _consume_progress(self) -> None:
        while True:
            job_id, message = self._progress_queue.get()
            try:
                # status は submit()/_on_done() でのみ更新する。ここで status="running" を
                # 併せて書き込むと、ジョブ完了後に届いた最後の進捗メッセージが
                # status="done" を "running" に巻き戻すレースが発生するため触らない。
                db.update_job(job_id, progress=message)
            except Exception:
                logger.error("進捗更新に失敗しました (job=%s)", job_id, exc_info=True)

    def submit(
        self,
        job_id: str,
        user_id: int,
        upload_ids: list[str],
        parts: list[dict],
        manual_parts: list[dict],
        sheet_w: float,
        sheet_h: float,
        thickness: float,
        clearance: float,
        density: float,
        output_dir: str,
    ) -> None:
        db.update_job(job_id, status="running")
        future = self._executor.submit(
            _run_job, job_id, parts, manual_parts, sheet_w, sheet_h, thickness, clearance, density,
            output_dir, self._progress_queue,
        )
        future.add_done_callback(lambda f: self._on_done(job_id, user_id, upload_ids, f))

    def _on_done(self, job_id: str, user_id: int, upload_ids: list[str], future) -> None:
        try:
            outcome = future.result()
        except Exception as exc:
            logger.error("ジョブ失敗 (job=%s): %s", job_id, exc)
            db.update_job(job_id, status="error", error=str(exc), progress="")
        else:
            db.update_job(
                job_id,
                status="done",
                progress="完了",
                results=outcome["results"],
                candidates=outcome["candidates"],
            )
        finally:
            for upload_id in upload_ids:
                row = db.get_upload(upload_id, user_id)
                if row is None:
                    continue
                try:
                    storage.delete_upload_file(row["stored_path"])
                    db.delete_upload(upload_id)
                except Exception:
                    logger.warning(
                        "使用済みアップロードの削除に失敗しました (job=%s, upload=%s)",
                        job_id,
                        upload_id,
                        exc_info=True,
                    )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._mp_manager.shutdown()
