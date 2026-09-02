import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加（src パッケージを解決するため）
sys.path.insert(0, str(Path(__file__).parent))
