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

from webapp import db

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


def _run_job(
    job_id: str,
    parts: list[dict],
    sheet_w: float,
    sheet_h: float,
    thickness: float,
    clearance: float,
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
    from src.pipeline import FlattenPipeline
    from webapp.services.export_service import ExportService
    from webapp.services.nesting_service import NestingService

    known_errors = (StepReadError, UnfoldError, DxfExportError, PngExportError, ResultWriteError)

    pipeline = FlattenPipeline(samples_per_edge=50)
    results: list[dict] = []
    for i, part in enumerate(parts):
        stored_path = part["stored_path"]
        orig_filename = part["orig_filename"]
        quantity = part["quantity"]
        progress_queue.put((job_id, f"処理中 ({i + 1}/{len(parts)}): {orig_filename}"))
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

    progress_queue.put((job_id, "ネスティング計算中"))
    nesting_parts = [
        {
            "id": r["part_id"],
            "name": _safe_stem(r["step_path"]),
            "points": r.get("points", []),
            "holes": r.get("holes", []),
            "quantity": r.get("quantity", 1),
        }
        for r in results
    ]
    candidates = NestingService().calculate_candidates(nesting_parts, sheet_w, sheet_h, clearance)

    if candidates:
        try:
            ExportService().append_to_summary(
                results,
                candidates[0],
                {"sheet_w": sheet_w, "sheet_h": sheet_h, "thickness": thickness, "clearance": clearance},
                output_dir=output_dir,
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
        parts: list[dict],
        sheet_w: float,
        sheet_h: float,
        thickness: float,
        clearance: float,
        output_dir: str,
    ) -> None:
        db.update_job(job_id, status="running")
        future = self._executor.submit(
            _run_job, job_id, parts, sheet_w, sheet_h, thickness, clearance, output_dir,
            self._progress_queue,
        )
        future.add_done_callback(lambda f: self._on_done(job_id, f))

    def _on_done(self, job_id: str, future) -> None:
        try:
            outcome = future.result()
        except Exception as exc:
            logger.error("ジョブ失敗 (job=%s): %s", job_id, exc)
            db.update_job(job_id, status="error", error=str(exc), progress="")
            return
        db.update_job(
            job_id,
            status="done",
            progress="完了",
            results=outcome["results"],
            candidates=outcome["candidates"],
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._mp_manager.shutdown()
