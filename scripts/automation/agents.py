"""claude / agy の無人実行アダプタ.

共通の ``AgentRequest`` からコマンドを組み立て、プロンプトを stdin で渡して実行し、``AgentResult`` を返す。

両 CLI とも権限拒否・タイムアウトでも exit 0 になるので、成否は終了コードではなく出力の封筒で判定する
（docs/automation/README.md の「両 CLI の無人実行の挙動」）。
- claude: ``--output-format json`` の ``is_error`` / ``permission_denials`` / ``structured_output``
- agy: ``status`` / ``response`` が空か / ``denied_actions``（ドキュメントに無い項目）/ stderr の
  ``print timeout`` / ``auto-denied``

``--dangerously-skip-permissions`` は使わない。claude は ``--permission-mode dontAsk --permission-prompts none``
＋ ``--tools`` / ``--allowedTools`` / ``--disallowedTools``、agy は settings.json の許可ルールに任せる。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from scripts.automation.config import AgyAgent, AgyPermission, ClaudeAgent, ClaudePermission

# 認証切れ・未ログインの文言（大文字小文字は無視）
AUTH_ERROR_RE = re.compile(
    r"authentication required|not logged in|please run /login|invalid api key|oauth token|unauthori[sz]ed",
    re.IGNORECASE,
)
# CLI 自身の --print-timeout が切れたあと、プロセスを殺すまでの猶予（秒）
KILL_GRACE_SECONDS = 60


@dataclass
class AgentRequest:
    prompt: str
    permission: ClaudePermission | AgyPermission
    cwd: Path
    timeout_seconds: int
    model: str | None = None
    effort: str | None = None
    json_schema: dict[str, Any] | None = None


@dataclass
class AgentResult:
    ok: bool
    text: str = ""
    structured: Any = None
    auth_required: bool = False
    denied: list[str] = field(default_factory=list)
    timed_out: bool = False
    error: str | None = None
    cost_usd: float | None = None
    stdout: str = ""
    stderr: str = ""


class Adapter(Protocol):
    name: str

    def build_command(self, req: AgentRequest) -> list[str]: ...

    def run(self, req: AgentRequest) -> AgentResult: ...


def _resolve(command: str | None, default: str) -> str:
    """実行ファイルを解決する（Windows の PATHEXT を考慮。shell=False で起動するため）."""
    name = command or default
    return shutil.which(name) or name


def _run_process(cmd: list[str], req: AgentRequest, timeout: int) -> tuple[int | None, str, str]:
    """プロンプトを stdin で渡して実行する. タイムアウトしたら returncode は None."""
    try:
        proc = subprocess.run(
            cmd,
            input=req.prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=req.cwd,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        return None, out, err
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _load_json_envelope(stdout: str) -> dict[str, Any] | None:
    """stdout の JSON 封筒を読む. 全体が JSON でなければ、末尾から JSON として読める行を探す."""
    text = stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


# ---------------------------------------------------------------------------
# claude
# ---------------------------------------------------------------------------


class ClaudeAdapter:
    name = "claude"

    def __init__(self, agent: ClaudeAgent) -> None:
        self.agent = agent

    def build_command(self, req: AgentRequest) -> list[str]:
        perm = req.permission
        assert isinstance(perm, ClaudePermission)
        cmd = [
            _resolve(self.agent.command, "claude"),
            "-p",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--permission-prompts",
            "none",
        ]
        if model := req.model or self.agent.model:
            cmd += ["--model", model]
        if effort := req.effort or self.agent.effort:
            cmd += ["--effort", effort]
        if self.agent.max_budget_usd is not None:
            cmd += ["--max-budget-usd", str(self.agent.max_budget_usd)]
        if perm.tools is not None:
            cmd += ["--tools", ",".join(perm.tools)]
        # 規則には空白が入るので 1 規則 1 引数で渡す（可変長引数は次の -- で終わる）
        if perm.allow:
            cmd += ["--allowedTools", *perm.allow]
        if perm.deny:
            cmd += ["--disallowedTools", *perm.deny]
        if req.json_schema is not None:
            cmd += ["--json-schema", json.dumps(req.json_schema, ensure_ascii=False)]
        cmd += self.agent.extra_args
        return cmd

    def parse(self, returncode: int | None, stdout: str, stderr: str, req: AgentRequest) -> AgentResult:
        res = AgentResult(ok=False, stdout=stdout, stderr=stderr)
        if returncode is None:
            res.timed_out = True
            res.error = f"{req.timeout_seconds} 秒でタイムアウトした"
            return res
        env = _load_json_envelope(stdout)
        if env is None:
            res.error = f"出力を JSON として読めない（exit {returncode}）: {(stderr or stdout).strip()[:300]}"
            res.auth_required = bool(AUTH_ERROR_RE.search(stderr + stdout))
            return res
        res.text = str(env.get("result") or "")
        res.structured = env.get("structured_output")
        res.cost_usd = env.get("total_cost_usd")
        for d in env.get("permission_denials") or []:
            tool = d.get("tool_name", "?")
            inp = d.get("tool_input") or {}
            detail = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
            res.denied.append(f"{tool}({detail})" if detail else tool)
        if env.get("is_error") or returncode != 0:
            res.error = res.text.strip()[:300] or f"is_error（subtype: {env.get('subtype')}）"
            res.auth_required = bool(AUTH_ERROR_RE.search(res.text))
            return res
        if req.json_schema is not None and res.structured is None:
            res.error = "構造化出力（structured_output）が返らなかった"
            return res
        res.ok = True
        return res

    def run(self, req: AgentRequest) -> AgentResult:
        code, out, err = _run_process(self.build_command(req), req, req.timeout_seconds)
        return self.parse(code, out, err, req)


# ---------------------------------------------------------------------------
# agy
# ---------------------------------------------------------------------------


AGY_SETTINGS_PATH = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"


def missing_agy_rules(perm: AgyPermission, settings_path: Path = AGY_SETTINGS_PATH) -> list[str]:
    """権限プロファイルで宣言したルールのうち、settings.json に無いものを ``"allow: ..."`` の形で返す."""
    if not perm.allow and not perm.deny:
        return []
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        perms = data.get("permissions") or {}
    except (OSError, json.JSONDecodeError, AttributeError):
        perms = {}
    missing = []
    for kind, rules in (("allow", perm.allow), ("deny", perm.deny)):
        have = set(perms.get(kind) or [])
        missing += [f"{kind}: {r}" for r in rules if r not in have]
    return missing


class AgyAdapter:
    name = "agy"

    def __init__(self, agent: AgyAgent) -> None:
        self.agent = agent

    def build_command(self, req: AgentRequest) -> list[str]:
        # -p を付けずに stdin でプロンプトを渡す（Step1 で確認）。--print-timeout は無限待ち対策で必ず付ける
        cmd = [
            _resolve(self.agent.command, "agy"),
            "--output-format",
            "json",
            "--print-timeout",
            f"{req.timeout_seconds}s",
        ]
        if model := req.model or self.agent.model:
            cmd += ["--model", model]
        if req.json_schema is not None:
            cmd += ["--json-schema", json.dumps(req.json_schema, ensure_ascii=False)]
        cmd += self.agent.extra_args
        return cmd

    def parse(self, returncode: int | None, stdout: str, stderr: str, req: AgentRequest) -> AgentResult:
        res = AgentResult(ok=False, stdout=stdout, stderr=stderr)
        res.auth_required = bool(AUTH_ERROR_RE.search(stderr)) or "authentication required" in stdout.lower()
        res.timed_out = returncode is None or "print timeout" in stderr
        if "auto-denied" in stderr:
            res.denied += [m.group(0) for m in re.finditer(r'the "[^"]+" permission', stderr)] or ["(auto-denied)"]
        env = _load_json_envelope(stdout)
        if env is not None:
            res.text = str(env.get("response") or "")
            for d in env.get("denied_actions") or []:
                label = f"{d.get('action', '?')}({d.get('display_name', '')})"
                if label not in res.denied:
                    res.denied.append(label)
            res.structured = env.get("structured_output")
            if res.structured is None and req.json_schema is not None and res.text:
                try:
                    res.structured = json.loads(res.text)
                except json.JSONDecodeError:
                    pass
        if res.auth_required:
            res.error = "agy の認証が必要（authentication required）"
        elif res.timed_out:
            res.error = f"{req.timeout_seconds} 秒でタイムアウトした（部分的な出力のみ）"
        elif env is None:
            res.error = f"出力を JSON として読めない（exit {returncode}）: {(stderr or stdout).strip()[:300]}"
        elif env.get("status") != "SUCCESS":
            err = env.get("error")
            res.error = f"status: {env.get('status')}" + (f"（{err}）" if err else "")
        elif not res.text.strip() and res.structured is None:
            res.error = "応答が空（許可されていない操作で止まった可能性）" if res.denied else "応答が空"
        elif req.json_schema is not None and res.structured is None:
            res.error = "構造化出力が返らなかった"
        else:
            res.ok = returncode == 0
            if not res.ok:
                res.error = f"exit {returncode}"
        return res

    def run(self, req: AgentRequest) -> AgentResult:
        code, out, err = _run_process(self.build_command(req), req, req.timeout_seconds + KILL_GRACE_SECONDS)
        return self.parse(code, out, err, req)


def make_adapter(name: str, agent: ClaudeAgent | AgyAgent) -> Adapter:
    if name == "claude":
        assert isinstance(agent, ClaudeAgent)
        return ClaudeAdapter(agent)
    assert isinstance(agent, AgyAgent)
    return AgyAdapter(agent)
