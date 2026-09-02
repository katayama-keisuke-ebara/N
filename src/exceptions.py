"""業務ロジック固有の例外クラス群。"""

from __future__ import annotations


class StepReadError(RuntimeError):
    """STEP ファイルの読み込みに失敗したとき。"""


class UnfoldError(RuntimeError):
    """面の展開処理に失敗したとき。"""


class DxfExportError(RuntimeError):
    """DXF ファイルの出力に失敗したとき。"""


class PngExportError(RuntimeError):
    """PNG プレビューの出力に失敗したとき。"""


class ResultWriteError(RuntimeError):
    """result.json の出力に失敗したとき。"""


class NestingError(RuntimeError):
    """ネスティング計算に失敗したとき。"""
