"""定期実行ルーチン YAML（vault/automation/routines.yaml）のスキーマと読み込み（SSOT）.

- 型・許容値・未知キーの誤りは Pydantic の ValidationError とし、``load_config`` が ``ConfigError`` にまとめる。
- ステップ間の参照（``when`` / プレースホルダ / ``brief.step``）・権限プロファイルの存在・``prompt_file`` の実在は
  ``check_references`` / ``check_files`` で検査する。後段のステップや未定義のステップを参照したらエラー。
- 動作に影響しないが紛らわしい書き方（無効なルーチンにスケジュールがある等）は ``config_warnings`` の警告。

プレースホルダは ``{{name}}`` 形式。使えるのは ``GLOBAL_PLACEHOLDERS`` と ``steps.<id>.output`` / ``steps.<id>.status``
（``<id>`` は同じルーチンの前段のステップ）。展開は実行エンジンが行う。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

AgentName = Literal["claude", "agy"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WriteScope = Literal["none", "data", "vault"]

ID_PATTERN = r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$"
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
STEP_REF_RE = re.compile(r"^steps\.([a-z0-9_-]+)\.(output|status)$")

# ステップ参照以外に使えるプレースホルダ（値は実行エンジンが入れる）
GLOBAL_PLACEHOLDERS: dict[str, str] = {
    "today": "実行日（YYYY-MM-DD）",
    "tomorrow": "実行日の翌日（YYYY-MM-DD）",
    "now": "実行開始時刻（YYYY-MM-DD HH:MM）",
    "routine": "ルーチン id",
    "run_dir": "この実行の出力ディレクトリ（リポジトリルート相対）",
}

SUPPORTED_VERSION = 1


class ConfigError(Exception):
    """ルーチン YAML の誤り. ``errors`` に 1 件 1 行のメッセージを持つ."""

    def __init__(self, path: Path, errors: list[str]) -> None:
        self.path = path
        self.errors = errors
        super().__init__(f"{path}: {len(errors)} 件のエラー\n" + "\n".join(f"  - {e}" for e in errors))


class ConfigModel(BaseModel):
    """全モデル共通の設定. 未知キーは禁止（打ち間違いを無人実行で黙って無視しないため）."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _check_relative(v: str, what: str) -> str:
    p = Path(v)
    if p.is_absolute() or v.startswith(("/", "\\")) or ".." in p.parts or ":" in v:
        raise ValueError(f"{what} は相対パスで書く（絶対パス・.. は不可）: {v}")
    return v


# ---------------------------------------------------------------------------
# エージェント（CLI ごとの実行プロファイル）
# ---------------------------------------------------------------------------


class ClaudePermission(ConfigModel):
    """claude の権限プロファイル. ``--tools`` / ``--allowedTools`` / ``--disallowedTools`` に渡す."""

    writes: WriteScope = Field(
        default="none",
        description="書き込む範囲。vault は作業ツリーに未コミット変更が無いときだけ実行し、あれば none に格下げする",
    )
    tools: list[str] | None = Field(default=None, description="使えるツール（--tools）。省略時は CLI の既定")
    allow: list[str] = Field(
        default_factory=list, description="許可ルール（--allowedTools。例: Bash(uv run python scripts/x.py *)）"
    )
    deny: list[str] = Field(default_factory=list, description="拒否ルール（--disallowedTools）")


class AgyPermission(ConfigModel):
    """agy の権限プロファイル.

    agy は実行ごとに許可ルールを渡せない（グローバルの ~/.gemini/antigravity-cli/settings.json だけ）。
    ここに書くのは「settings.json に入っているべきルール」の宣言で、実行エンジンは不足をブリーフで知らせるだけ。
    """

    writes: WriteScope = Field(
        default="none", description="書き込む範囲（agy は防げないので、実行前後の差分で検出する）"
    )
    allow: list[str] = Field(default_factory=list, description="settings.json の permissions.allow にあるべきルール")
    deny: list[str] = Field(default_factory=list, description="settings.json の permissions.deny にあるべきルール")


class ClaudeAgent(ConfigModel):
    command: str | None = Field(default=None, description="実行ファイル（省略時は PATH の claude）")
    extra_args: list[str] = Field(default_factory=list, description="毎回付ける追加引数")
    model: str | None = Field(default=None, description="既定モデル（--model。例: sonnet / haiku）")
    effort: Effort | None = Field(default=None, description="既定の推論努力（--effort）")
    max_budget_usd: float | None = Field(default=None, gt=0, description="1 ステップの費用上限（--max-budget-usd）")
    permission_profiles: dict[str, ClaudePermission] = Field(min_length=1, description="権限プロファイル名 → 内容")


class AgyAgent(ConfigModel):
    command: str | None = Field(default=None, description="実行ファイル（省略時は PATH の agy）")
    extra_args: list[str] = Field(default_factory=list, description="毎回付ける追加引数")
    model: str | None = Field(default=None, description="既定モデル（--model。例: gemini-3.8-flash-medium）")
    permission_profiles: dict[str, AgyPermission] = Field(min_length=1, description="権限プロファイル名 → 内容")


class Agents(ConfigModel):
    claude: ClaudeAgent | None = None
    agy: AgyAgent | None = None

    def get(self, name: str) -> ClaudeAgent | AgyAgent | None:
        return getattr(self, name, None)


class Defaults(ConfigModel):
    agent: AgentName = Field(default="claude", description="agent ステップの既定 CLI")
    timeout_minutes: int = Field(default=15, gt=0, description="ステップの既定タイムアウト（分）")
    preamble: str = Field(default="", description="全 agent ステップのプロンプト先頭に付ける無人実行の約束")


# ---------------------------------------------------------------------------
# ルーチン・ステップ
# ---------------------------------------------------------------------------


class Schedule(ConfigModel):
    """タスク スケジューラに登録するトリガー（YAML が正。スケジューラ側はここから生成する）."""

    daily_at: list[str] = Field(default_factory=list, description='毎日の実行時刻 "HH:MM"（引用符で囲む）')
    weekdays: list[Weekday] | None = Field(default=None, description="実行する曜日（省略時は毎日）")
    on_logon: bool = Field(default=False, description="ログオン時にも起動する")
    once_per_day: bool = Field(default=True, description="同じ日に 2 回目以降の起動は何もしない")

    @field_validator("daily_at", mode="before")
    @classmethod
    def _check_times(cls, v: Any) -> Any:
        if not isinstance(v, list):
            return v
        for t in v:
            if not isinstance(t, str):
                # YAML 1.1 は 8:30 を 60 進数の整数 510 と読む
                raise ValueError(f'時刻は "HH:MM" の文字列で書く（引用符で囲む）: {t!r}')
            if not TIME_PATTERN.match(t.strip()):
                raise ValueError(f'時刻は "HH:MM"（00:00〜23:59）で書く: {t!r}')
        return v


class When(ConfigModel):
    """ステップの実行条件. いずれか 1 つだけを書く（値は前段のステップ id）."""

    if_nonempty: str | None = Field(default=None, description="そのステップの出力が空でないとき")
    if_empty: str | None = Field(default=None, description="そのステップの出力が空のとき")
    if_succeeded: str | None = Field(default=None, description="そのステップが成功したとき")
    if_failed: str | None = Field(default=None, description="そのステップが失敗したとき")

    @model_validator(mode="after")
    def _exactly_one(self) -> When:
        if len(self.conditions()) != 1:
            raise ValueError("when には if_nonempty / if_empty / if_succeeded / if_failed のどれか 1 つだけを書く")
        return self

    def conditions(self) -> list[tuple[str, str]]:
        return [(k, v) for k, v in self.model_dump().items() if v is not None]

    @property
    def step(self) -> str:
        return self.conditions()[0][1]


class StepBase(ConfigModel):
    id: str = Field(pattern=ID_PATTERN, description="ルーチン内で一意な id（プレースホルダ・when から参照する）")
    when: Literal["always"] | When = Field(default="always", description="実行条件")
    on_failure: Literal["continue", "stop"] = Field(default="continue", description="失敗したら後続を続けるか止めるか")
    timeout_minutes: int | None = Field(default=None, gt=0, description="タイムアウト（分）。省略時は defaults")


class ScriptStep(StepBase):
    """リポジトリの CLI を決定的に実行するステップ（``uv run python`` は実行エンジンが付ける）."""

    kind: Literal["script"]
    run: list[str] = Field(min_length=1, description="[scripts/ 配下の .py, 引数...]。引数にはプレースホルダを使える")
    capture: Literal["stdout", "file"] = Field(
        default="stdout",
        description="output にするもの。stdout: 標準出力そのもの / file: 標準出力に出たパス（1 行 1 パス）のファイル内容",
    )

    @field_validator("run")
    @classmethod
    def _check_script(cls, v: list[str]) -> list[str]:
        script = _check_relative(v[0], "run の先頭")
        if not script.replace("\\", "/").startswith("scripts/") or not script.endswith(".py"):
            raise ValueError(f"run の先頭は scripts/ 配下の .py にする: {script}")
        return v


class AgentStep(StepBase):
    """CLI（claude / agy）にプロンプトを渡すステップ."""

    kind: Literal["agent"]
    agent: AgentName | None = Field(default=None, description="使う CLI（省略時は defaults.agent）")
    model: str | None = Field(default=None, description="モデルの上書き")
    effort: Effort | None = Field(default=None, description="推論努力の上書き（claude のみ）")
    permission: str = Field(
        default="read_only", description="使う権限プロファイル名（agents.<agent>.permission_profiles）"
    )
    prompt: str | None = Field(default=None, description="プロンプト本文（prompt_file とどちらか一方）")
    prompt_file: str | None = Field(
        default=None, description="プロンプトのファイル（vault 相対。公開パスに置かせない）"
    )
    output_schema: dict[str, Any] | str | None = Field(
        default=None,
        description="構造化出力の JSON Schema（インライン、または vault 相対の .json）。brief のステップには書かない",
    )

    @field_validator("prompt_file")
    @classmethod
    def _check_prompt_file(cls, v: str | None) -> str | None:
        return None if v is None else _check_relative(v, "prompt_file")

    @field_validator("output_schema")
    @classmethod
    def _check_output_schema(cls, v: dict[str, Any] | str | None) -> dict[str, Any] | str | None:
        if isinstance(v, str):
            _check_relative(v, "output_schema")
            if not v.endswith(".json"):
                raise ValueError(f"output_schema のファイルは .json にする: {v}")
        return v

    @model_validator(mode="after")
    def _one_prompt(self) -> AgentStep:
        if (self.prompt is None) == (self.prompt_file is None):
            raise ValueError("prompt と prompt_file はどちらか一方だけを書く")
        return self


Step = Annotated[ScriptStep | AgentStep, Field(discriminator="kind")]


class Brief(ConfigModel):
    step: str = Field(
        description="ブリーフ（今日やること）を返す agent ステップの id。出力スキーマは実行エンジンが付ける"
    )
    notify: bool = Field(default=True, description="ブリーフができたらトースト通知する")


class Routine(ConfigModel):
    id: str = Field(
        pattern=ID_PATTERN, description="ルーチン id（タスク スケジューラのタスク名・出力ディレクトリ名になる）"
    )
    description: str | None = Field(default=None, description="説明")
    enabled: bool = Field(default=True, description="false ならスケジューラに登録しない（手動実行はできる）")
    schedule: Schedule | None = Field(default=None, description="省略時は手動実行専用")
    steps: list[Step] = Field(min_length=1, description="上から順に実行するステップ")
    brief: Brief | None = Field(default=None, description="省略時はブリーフを作らない")

    def step_ids(self) -> list[str]:
        return [s.id for s in self.steps]


class RoutinesConfig(ConfigModel):
    version: Literal[1] = Field(description="スキーマ版")
    defaults: Defaults = Field(default_factory=Defaults)
    agents: Agents = Field(description="CLI ごとの実行プロファイル")
    routines: list[Routine] = Field(default_factory=list)

    def routine(self, routine_id: str) -> Routine:
        for r in self.routines:
            if r.id == routine_id:
                return r
        raise KeyError(
            f"ルーチン {routine_id!r} は無い（定義済み: {', '.join(r.id for r in self.routines) or 'なし'}）"
        )


# ---------------------------------------------------------------------------
# 参照整合性・ファイル・警告
# ---------------------------------------------------------------------------


def placeholders(text: str) -> list[str]:
    """文字列中のプレースホルダ名（``{{ x }}`` の x）を出現順に返す."""
    return PLACEHOLDER_RE.findall(text)


def _check_placeholders(text: str, where: str, earlier: list[str], all_ids: list[str]) -> Iterator[str]:
    for name in placeholders(text):
        if name in GLOBAL_PLACEHOLDERS:
            continue
        m = STEP_REF_RE.match(name)
        if not m:
            yield f"{where}: 未知のプレースホルダ {{{{{name}}}}}（使えるのは {', '.join(GLOBAL_PLACEHOLDERS)}, steps.<id>.output, steps.<id>.status）"
        elif m.group(1) not in earlier:
            what = "後段" if m.group(1) in all_ids else "未定義"
            yield f"{where}: {{{{{name}}}}} は{what}のステップを参照している（参照できるのは前段のステップだけ）"


def _effective_agent(cfg: RoutinesConfig, step: AgentStep) -> str:
    return step.agent or cfg.defaults.agent


def check_references(cfg: RoutinesConfig) -> list[str]:
    """id の重複・ステップ間の参照・エージェントと権限プロファイルの存在を検査し、エラーを返す."""
    errors: list[str] = []
    for name in placeholders(cfg.defaults.preamble):
        if name not in GLOBAL_PLACEHOLDERS:
            errors.append(f"defaults.preamble: ステップに依らないプレースホルダだけを使える（{{{{{name}}}}}）")
    if cfg.agents.get(cfg.defaults.agent) is None:
        errors.append(f"defaults.agent: agents.{cfg.defaults.agent} が定義されていない")

    seen_routines: set[str] = set()
    for r in cfg.routines:
        if r.id in seen_routines:
            errors.append(f"routines.{r.id}: ルーチン id が重複している")
        seen_routines.add(r.id)
        all_ids = r.step_ids()
        earlier: list[str] = []
        for s in r.steps:
            where = f"routines.{r.id}.steps.{s.id}"
            if s.id in earlier:
                errors.append(f"{where}: ステップ id が重複している")
            if isinstance(s.when, When) and s.when.step not in earlier:
                what = "後段" if s.when.step in all_ids else "未定義"
                errors.append(
                    f"{where}.when: {what}のステップ {s.when.step!r} を参照している（参照できるのは前段のステップだけ）"
                )
            if isinstance(s, ScriptStep):
                for arg in s.run[1:]:
                    errors.extend(_check_placeholders(arg, f"{where}.run", earlier, all_ids))
            else:
                agent_name = _effective_agent(cfg, s)
                agent = cfg.agents.get(agent_name)
                if agent is None:
                    errors.append(f"{where}: agents.{agent_name} が定義されていない")
                elif s.permission not in agent.permission_profiles:
                    errors.append(
                        f"{where}.permission: agents.{agent_name}.permission_profiles に {s.permission!r} が無い"
                        f"（定義済み: {', '.join(agent.permission_profiles)}）"
                    )
                if agent_name == "agy" and s.effort is not None:
                    errors.append(f"{where}.effort: effort は claude だけで使える（agy はモデル名で選ぶ）")
                if s.prompt is not None:
                    errors.extend(_check_placeholders(s.prompt, f"{where}.prompt", earlier, all_ids))
            earlier.append(s.id)

        if r.brief is not None:
            target = next((s for s in r.steps if s.id == r.brief.step), None)
            if target is None:
                errors.append(f"routines.{r.id}.brief.step: ステップ {r.brief.step!r} が無い")
            elif not isinstance(target, AgentStep):
                errors.append(f"routines.{r.id}.brief.step: ブリーフは agent ステップで作る（{target.id} は script）")
            elif target.output_schema is not None:
                errors.append(
                    f"routines.{r.id}.brief.step: ブリーフのステップに output_schema は書かない（実行エンジンが付ける）"
                )
    return errors


def vault_root_of(config_path: Path) -> Path:
    """YAML（``<vault>/automation/routines.yaml``）から、prompt_file 等の基準になる vault ルートを返す."""
    return config_path.resolve().parent.parent


def check_files(cfg: RoutinesConfig, vault_root: Path) -> list[str]:
    """prompt_file・output_schema のファイルが実在するか、prompt_file のプレースホルダが正しいかを検査する."""
    errors: list[str] = []
    for r in cfg.routines:
        all_ids = r.step_ids()
        for i, s in enumerate(r.steps):
            if not isinstance(s, AgentStep):
                continue
            where = f"routines.{r.id}.steps.{s.id}"
            if s.prompt_file is not None:
                path = vault_root / s.prompt_file
                if not path.is_file():
                    errors.append(f"{where}.prompt_file: {path} が無い")
                else:
                    text = path.read_text(encoding="utf-8")
                    errors.extend(_check_placeholders(text, f"{where}.prompt_file", all_ids[:i], all_ids))
            if isinstance(s.output_schema, str) and not (vault_root / s.output_schema).is_file():
                errors.append(f"{where}.output_schema: {vault_root / s.output_schema} が無い")
    return errors


def config_warnings(cfg: RoutinesConfig) -> list[str]:
    """動作はするが意図と違いそうな書き方を返す."""
    warnings: list[str] = []
    for r in cfg.routines:
        if not r.enabled and r.schedule is not None:
            warnings.append(f"routines.{r.id}: enabled: false なので schedule はスケジューラに登録されない")
        if r.schedule is not None and not r.schedule.daily_at and not r.schedule.on_logon:
            warnings.append(f"routines.{r.id}.schedule: daily_at も on_logon も無いので自動では起動しない")
        if r.brief is not None and r.steps[-1].id != r.brief.step:
            warnings.append(f"routines.{r.id}.brief.step: ブリーフのステップ {r.brief.step!r} の後にもステップがある")
        if r.brief is None:
            warnings.append(f"routines.{r.id}: brief が無いので、今日やることのブリーフは作られない")
    return warnings


def _format_validation_error(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        out.append(f"{loc}: {msg}" if loc else msg)
    return out


def load_config(path: Path, *, check_vault_files: bool = True) -> RoutinesConfig:
    """YAML を読み、スキーマ・参照整合性・（任意で）ファイルの実在を検査して返す. 誤りは ConfigError."""
    if not path.is_file():
        raise ConfigError(path, ["ファイルが無い（templates/vault/automation/routines.yaml をコピーして作る）"])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(path, [f"YAML として読めない: {e}"]) from e
    if not isinstance(data, dict):
        raise ConfigError(path, ["トップレベルはマッピングにする"])
    if data.get("version") not in (None, SUPPORTED_VERSION):
        raise ConfigError(path, [f"version: 未対応の版 {data.get('version')!r}（対応: {SUPPORTED_VERSION}）"])
    try:
        cfg = RoutinesConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(path, _format_validation_error(e)) from e
    errors = check_references(cfg)
    if check_vault_files:
        errors += check_files(cfg, vault_root_of(path))
    if errors:
        raise ConfigError(path, errors)
    return cfg
