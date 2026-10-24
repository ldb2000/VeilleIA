"""Tests de la sélection du fournisseur LLM (codex / openrouter / gemini), sans appel réseau."""
import subprocess
from pathlib import Path

import pytest

from app import main


def test_default_provider_is_codex(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert main.get_llm_provider() == "codex"


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    with pytest.raises(RuntimeError):
        main.get_llm_provider()


def test_codex_command_reads_prompt_from_stdin_and_toggles_web_search(monkeypatch):
    monkeypatch.setenv("CODEX_MODEL", "gpt-test")
    cmd = main.build_codex_command("/tmp/out.md", web_search=True)
    assert cmd[:2] == [main.CODEX_BIN, "exec"]
    assert cmd[-1] == "-"
    assert 'web_search="live"' in cmd
    assert ["--model", "gpt-test"] == cmd[cmd.index("--model"):cmd.index("--model") + 2]
    assert 'web_search="disabled"' in main.build_codex_command("/tmp/out.md", web_search=False)


def test_codex_content_uses_last_message_file(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    captured = {}

    def fake_run(cmd, input, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = input
        out = cmd[cmd.index("--output-last-message") + 1]
        Path(out).write_text("## TL;DR\n- ok\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="journal", stderr="")

    monkeypatch.setattr(main.subprocess, "run", fake_run)
    result = main.generate_llm_content("Bonjour", timeout_seconds=5, web_search=True)
    assert result == "## TL;DR\n- ok"
    assert captured["input"] == "Bonjour"
    assert 'web_search="live"' in captured["cmd"]


def test_codex_failure_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Not logged in"),
    )
    with pytest.raises(RuntimeError, match="Not logged in"):
        main.generate_llm_content("x", timeout_seconds=5)


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_openrouter_payload_and_web_plugin(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/test")
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append(json)
        return FakeResponse({"choices": [{"message": {"content": "Réponse"}}]})

    monkeypatch.setattr(main.httpx, "post", fake_post)

    monkeypatch.setenv("OPENROUTER_WEB_SEARCH", "false")
    assert main.generate_llm_content("Q", timeout_seconds=5, web_search=True) == "Réponse"
    assert calls[-1]["model"] == "anthropic/test"
    assert "plugins" not in calls[-1]
    assert main.llm_supports_web_search() is False

    monkeypatch.setenv("OPENROUTER_WEB_SEARCH", "true")
    main.generate_llm_content("Q", timeout_seconds=5, web_search=True)
    assert calls[-1]["plugins"] == [{"id": "web"}]


def test_ensure_llm_ready_checks_configuration(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        main.ensure_llm_ready()

    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="Codex"):
        main.ensure_llm_ready()
