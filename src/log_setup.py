"""アプリケーション共通ロギング設定。"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: str | Path = "logs") -> None:
    """ファイル + コンソール両方にログを出力するハンドラを設定する。"""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        return  # 二重初期化を防ぐ

    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ローテーション付きファイルハンドラ
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=1_048_576,  # 1 MB
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # コンソールハンドラ (WARNING 以上のみ表示)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)
