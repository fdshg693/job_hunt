"""テスト全体の共通設定."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# `from scripts...` をテストファイル単独・収集順に依らず解決できるようにする
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# entrypoint_guard を通るテストが実リポジトリの data/ を自動プルーニングしないようにする
os.environ.setdefault("JOB_HUNT_NO_PRUNE", "1")
