"""設定パラメータを config.json へ永続化するサービス (CLI/バッチ用途向け、Web版はDBベースの設定を使用)。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULTS: dict = {
    "parts": [],  # [{"path": str, "quantity": int}, ...]
    "sheet_w": 1000.0,
    "sheet_h": 2000.0,
    "thickness": 10.0,
    "clearance": 5.0,
}


class ConfigService:
    """設定ファイルの読み書きを担当する。"""

    def __init__(self, config_path: str | Path = "config.json") -> None:
        self._path = Path(config_path)

    def load(self) -> dict:
        """設定を読み込む。ファイルが存在しない場合はデフォルト値を返す。"""
        if not self._path.exists():
            logger.info("config.json が存在しないためデフォルト値を使用します")
            return dict(_DEFAULTS)
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            data = self._migrate(data)
            config = dict(_DEFAULTS)
            config.update({k: v for k, v in data.items() if k in _DEFAULTS})
            logger.info("設定を読み込みました: %s", self._path)
            return config
        except Exception as exc:
            logger.warning("config.json の読み込みに失敗しました: %s", exc)
            return dict(_DEFAULTS)

    @staticmethod
    def _migrate(data: dict) -> dict:
        """旧形式 (単一 step_path) を新形式 (parts リスト) へ変換する。"""
        if "parts" not in data and data.get("step_path"):
            data = dict(data)
            data["parts"] = [{"path": data["step_path"], "quantity": 1}]
        return data

    def save(self, config: dict) -> None:
        """設定をファイルに書き込む。"""
        data = {k: config[k] for k in _DEFAULTS if k in config}
        try:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("設定を保存しました: %s", self._path)
        except Exception as exc:
            logger.warning("config.json の保存に失敗しました: %s", exc)
