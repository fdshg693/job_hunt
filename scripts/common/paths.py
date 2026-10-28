"""個人データ（vault/）パス定数モジュール.

個人データ（プロフィール・track別の企業/選考ログ・リクルーターログ）の
格納先パスを一元定義します。I/Oや import 副作用は持たず、定数と薄いヘルパーのみを提供します。

媒体スナップショット（data/）の各媒体ディレクトリは対象外です（各スクリプトで PROJECT_ROOT / "data" を直接参照）。
ただし vault から派生する索引 DB と、data/ 全体を扱う保持期間プルーナーのパスはここで定義します。
"""

from __future__ import annotations

from pathlib import Path

from scripts.common.cli import PROJECT_ROOT

# 個人データのルート
VAULT_DIR = PROJECT_ROOT / "vault"

# 外部媒体から取った生データ（使い捨てのキャッシュ。保持期間を過ぎると scripts/common/data_retention.py が消す）
DATA_DIR = PROJECT_ROOT / "data"
PRUNE_STATE_PATH = DATA_DIR / ".prune_state.json"  # 保持期間プルーナーの最終実行時刻

# vault と data/*/jobs から作る派生キャッシュ（SQLite 索引。正本ではないので消しても再生成できる）
VAULT_INDEX_PATH = DATA_DIR / "vault_index.sqlite"

# 人のSSOT（track非依存）
PROFILE_DIR = VAULT_DIR / "profile"
PROFILE_EN_DIR = PROFILE_DIR / "en"
PROFILE_INTERNAL_DIR = PROFILE_DIR / "internal"
PROFILE_SITES_DIR = PROFILE_DIR / "sites"
EMPLOYERS_DIR = PROFILE_DIR / "employers"

# 技術詳細ノート（resume.md / skills.md の要約に対する一次情報。1 テーマ 1 ファイル）
PROFILE_TECH_DIR = PROFILE_DIR / "tech"
TECH_PROJECTS_DIR = PROFILE_TECH_DIR / "projects"
TECH_AREAS_DIR = PROFILE_TECH_DIR / "areas"

RESUME_PATH = PROFILE_DIR / "resume.md"
RIREKISHO_PATH = PROFILE_DIR / "rirekisho.md"  # 履歴書（JIS/厚労省様式）の汎用項目
SKILLS_PATH = PROFILE_DIR / "skills.md"
PREFERENCES_PATH = PROFILE_DIR / "preferences.md"
ACCOUNTS_PATH = PROFILE_DIR / "accounts.md"

# 転職活動の単位（track）
TRACKS_DIR = VAULT_DIR / "tracks"
TRACKS = ("domestic", "overseas")
DEFAULT_TRACK = "domestic"

# リクルーター（track横断。frontmatter `tracks:` で区別）
RECRUITERS_DIR = VAULT_DIR / "recruiters"

# 定期実行エージェントルーチン（scripts/automation/）。定義 YAML は vault、実行ログ・ブリーフは data
AUTOMATION_DIR = VAULT_DIR / "automation"
AUTOMATION_CONFIG_PATH = AUTOMATION_DIR / "routines.yaml"
AUTOMATION_DATA_DIR = DATA_DIR / "automation"


def track_dir(name: str = DEFAULT_TRACK) -> Path:
    """指定 track のディレクトリ（vault/tracks/{name}/）を返す."""
    if name not in TRACKS:
        raise ValueError(f"未知の track です: {name}（有効値: {', '.join(TRACKS)}）")
    return TRACKS_DIR / name


def track_companies_dir(name: str = DEFAULT_TRACK) -> Path:
    """指定 track の企業フォルダ群のルート（vault/tracks/{name}/companies/）を返す."""
    return track_dir(name) / "companies"


def track_screening_dir(name: str = DEFAULT_TRACK) -> Path:
    """指定 track のスクリーニング集約ログ置き場（vault/tracks/{name}/screening/）を返す."""
    return track_dir(name) / "screening"


def track_archive_path(name: str = DEFAULT_TRACK) -> Path:
    """指定 track の見送り台帳（vault/tracks/{name}/archive.md）を返す. 圧縮した終了企業・古いスクリーニングを集約する."""
    return track_dir(name) / "archive.md"


def track_criteria_path(name: str = DEFAULT_TRACK) -> Path:
    """指定 track の足切り基準ファイル（vault/tracks/{name}/criteria.md）を返す."""
    return track_dir(name) / "criteria.md"


def track_strategy_path(name: str = DEFAULT_TRACK) -> Path:
    """指定 track 固有の希望条件ファイル（vault/tracks/{name}/strategy.md）を返す."""
    return track_dir(name) / "strategy.md"


def track_pipeline_path(name: str = DEFAULT_TRACK) -> Path:
    """指定 track の選考ダッシュボード（vault/tracks/{name}/pipeline.md）を返す."""
    return track_dir(name) / "pipeline.md"
