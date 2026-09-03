"""CI/自動化向けのテスト実行ラッパー。

`python -m pytest` は cadquery/OCP をimportするテストを含めると、全テスト成功後に
インタプリタ終了処理でネイティブクラッシュ (exit code -1073741819 / 0xC0000005) する
既知の不具合があり、素の exit code だけを見る自動化フローでは誤って失敗判定されてしまう。
pytest.main() の戻り値を同一プロセス内で受け取ってから os._exit() で即時終了することで、
クラッシュを引き起こす通常のインタプリタ終了処理そのものを回避する。
"""

from __future__ import annotations

import os
import sys

import pytest


def main() -> int:
    return int(pytest.main(sys.argv[1:]))


if __name__ == "__main__":
    _exit_code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_exit_code)
