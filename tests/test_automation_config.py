"""定期実行ルーチン YAML のスキーマ・参照検査 (scripts/automation/config.py) の単体テスト."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.automation.config import ConfigError, config_warnings, load_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_ROOT / "templates" / "vault" / "automation" / "routines.yaml"

BASE: dict = {
    "version": 1,
    "agents": {
        "claude": {"permission_profiles": {"read_only": {"tools": ["Read"]}}},
        "agy": {"permission_profiles": {"read_only": {}}},
    },
    "routines": [
        {
            "id": "r1",
            "steps": [
                {"id": "a", "kind": "script", "run": ["scripts/vault/find_chores.py", "--json"]},
                {"id": "b", "kind": "agent", "prompt": "要約: {{steps.a.output}} ({{today}})"},
            ],
            "brief": {"step": "b"},
        }
    ],
}


def _write(tmp_path: Path, data: dict) -> Path:
    """<tmp>/vault/automation/routines.yaml に書く（prompt_file の基準は <tmp>/vault）."""
    path = tmp_path / "vault" / "automation" / "routines.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _with(**step_b: object) -> dict:
    """BASE の 2 番目のステップを上書きした設定を返す."""
    data = yaml.safe_load(yaml.safe_dump(BASE))
    data["routines"][0]["steps"][1].update(step_b)
    return data


def _errors(tmp_path: Path, data: dict) -> list[str]:
    with pytest.raises(ConfigError) as exc:
        load_config(_write(tmp_path, data))
    return exc.value.errors


def test_template_is_valid() -> None:
    cfg = load_config(TEMPLATE)
    assert [r.id for r in cfg.routines] == ["morning-brief"]
    assert config_warnings(cfg) == []


def test_base_is_valid(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, BASE))
    assert cfg.routine("r1").step_ids() == ["a", "b"]


def test_unknown_key_is_error(tmp_path: Path) -> None:
    errors = _errors(tmp_path, _with(promt="typo"))
    assert any("promt" in e for e in errors)


def test_undefined_and_later_step_references_are_errors(tmp_path: Path) -> None:
    data = _with(prompt="{{steps.nope.output}}")
    assert any("未定義" in e for e in _errors(tmp_path, data))

    data = yaml.safe_load(yaml.safe_dump(BASE))
    data["routines"][0]["steps"][0]["run"].append("{{steps.b.output}}")
    assert any("後段" in e for e in _errors(tmp_path, data))

    data = yaml.safe_load(yaml.safe_dump(BASE))
    data["routines"][0]["steps"][0]["when"] = {"if_nonempty": "b"}
    assert any("when" in e and "後段" in e for e in _errors(tmp_path, data))


def test_unknown_placeholder_is_error(tmp_path: Path) -> None:
    assert any("未知のプレースホルダ" in e for e in _errors(tmp_path, _with(prompt="{{yesterday}}")))


def test_preamble_cannot_reference_steps(tmp_path: Path) -> None:
    data = _with()
    data["defaults"] = {"preamble": "{{steps.a.output}}"}
    assert any("preamble" in e for e in _errors(tmp_path, data))


@pytest.mark.parametrize(
    ("override", "needle"),
    [
        ({"permission": "write_vault"}, "permission"),
        ({"agent": "agy", "effort": "high"}, "effort"),
        ({"prompt_file": "p.md"}, "どちらか一方"),
        ({"prompt": None, "prompt_file": "../p.md"}, "相対パス"),
        ({"prompt": None, "prompt_file": "automation/missing.md"}, "が無い"),
        ({"output_schema": {"type": "object"}}, "output_schema"),
        ({"when": {"if_nonempty": "a", "if_failed": "a"}}, "1 つだけ"),
    ],
)
def test_agent_step_errors(tmp_path: Path, override: dict, needle: str) -> None:
    assert any(needle in e for e in _errors(tmp_path, _with(**override)))


def test_prompt_file_is_resolved_from_vault_root_and_checked(tmp_path: Path) -> None:
    prompt = tmp_path / "vault" / "automation" / "prompts" / "b.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("{{steps.a.output}}", encoding="utf-8")
    load_config(_write(tmp_path, _with(prompt=None, prompt_file="automation/prompts/b.md")))

    prompt.write_text("{{steps.b.output}}", encoding="utf-8")  # 自分自身は前段ではない
    assert any("後段" in e for e in _errors(tmp_path, _with(prompt=None, prompt_file="automation/prompts/b.md")))


def test_script_must_be_under_scripts(tmp_path: Path) -> None:
    data = yaml.safe_load(yaml.safe_dump(BASE))
    data["routines"][0]["steps"][0]["run"] = ["tools/x.py"]
    assert any("scripts/" in e for e in _errors(tmp_path, data))


def test_brief_must_be_agent_step(tmp_path: Path) -> None:
    data = yaml.safe_load(yaml.safe_dump(BASE))
    data["routines"][0]["brief"] = {"step": "a"}
    assert any("agent ステップ" in e for e in _errors(tmp_path, data))


def test_duplicate_ids_are_errors(tmp_path: Path) -> None:
    data = _with(id="a")
    assert any("重複" in e for e in _errors(tmp_path, data))


def test_unquoted_time_is_error(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE)
    # YAML 1.1 では引用符の無い 8:30 が 60 進数の整数 510 になる
    path.write_text(
        "version: 1\n"
        "agents: {claude: {permission_profiles: {read_only: {}}}}\n"
        "routines:\n"
        "  - id: r1\n"
        "    schedule: {daily_at: [8:30]}\n"
        "    steps: [{id: a, kind: script, run: [scripts/vault/find_chores.py]}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert any("引用符" in e for e in exc.value.errors)


def test_missing_agent_definition_is_error(tmp_path: Path) -> None:
    data = _with(agent="agy")
    del data["agents"]["agy"]
    assert any("agents.agy" in e for e in _errors(tmp_path, data))


def test_cli_validate_outputs_config_path(tmp_path: Path) -> None:
    path = _write(tmp_path, BASE)
    ok = subprocess.run(
        [sys.executable, "scripts/automation/run_routine.py", "validate", "--config", str(path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert ok.returncode == 0, ok.stderr
    assert Path(ok.stdout.strip()).resolve() == path.resolve()

    _write(tmp_path, _with(promt="typo"))
    ng = subprocess.run(
        [sys.executable, "scripts/automation/run_routine.py", "validate", "--config", str(path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert ng.returncode == 1
    assert ng.stdout == ""
