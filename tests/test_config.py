import os
from pathlib import Path

import pytest

from job_scout.config import ConfigurationError, load_config


BASE_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-test",
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_KEY": "eyJtest",
    "TELEGRAM_BOT_TOKEN": "123:AAFtest",
    "TELEGRAM_CHAT_ID": "999",
}


def test_raises_configuration_error_on_missing_anthropic_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path)
    env = {k: v for k, v in BASE_ENV.items() if k != "ANTHROPIC_API_KEY"}
    _set_env(monkeypatch, tmp_path, env)
    with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
        load_config()


def test_raises_configuration_error_on_missing_supabase_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path)
    env = {k: v for k, v in BASE_ENV.items() if k != "SUPABASE_URL"}
    _set_env(monkeypatch, tmp_path, env)
    with pytest.raises(ConfigurationError, match="SUPABASE_URL"):
        load_config()


def test_raises_configuration_error_on_missing_telegram_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path)
    env = {k: v for k, v in BASE_ENV.items() if k != "TELEGRAM_BOT_TOKEN"}
    _set_env(monkeypatch, tmp_path, env)
    with pytest.raises(ConfigurationError, match="TELEGRAM_BOT_TOKEN"):
        load_config()


def test_raises_on_invalid_scrape_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path, scrape_tier="ftp")
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    with pytest.raises(ConfigurationError, match="scrape_tier"):
        load_config()


def test_raises_on_empty_targets_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path, empty_targets=True)
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    with pytest.raises(ConfigurationError, match="targets"):
        load_config()


def test_raises_when_no_resumes_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path, no_resumes=True)
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    with pytest.raises(ConfigurationError, match="resumes"):
        load_config()


def test_match_threshold_defaults_to_0_70(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path)
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    config = load_config()
    assert config.match_threshold == 0.70


def test_dry_run_defaults_to_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path)
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    config = load_config()
    assert config.dry_run is False


def test_loads_targets_correctly_from_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path)
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    config = load_config()
    assert len(config.targets) == 1
    assert config.targets[0].name == "Test Corp"
    assert config.targets[0].url == "https://test.com/jobs"
    assert config.targets[0].scrape_tier == "http"


# ── Resume loader tests ────────────────────────────────────────────────────────

def test_loads_all_md_files_from_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path, resume_files=["resume_a.md", "resume_b.md"])
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    config = load_config()
    assert len(config.resumes) == 2


def test_applies_correct_label_to_known_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path, resume_files=["ai_engineer.md"])
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    config = load_config()
    assert config.resumes[0].role_label == "AI Engineer"


def test_fallback_label_converts_filename_to_title_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path, resume_files=["senior_data_analyst.md"])
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    config = load_config()
    assert config.resumes[0].role_label == "Senior Data Analyst"


def test_resume_content_is_not_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_content = "x" * 10_000
    _setup_valid_files(tmp_path, resume_files=["my_resume.md"], resume_content=long_content)
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    config = load_config()
    assert config.resumes[0].content == long_content


def test_returns_empty_list_when_directory_has_no_md_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path, no_resumes=True)
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    with pytest.raises(ConfigurationError, match="resumes"):
        load_config()


def test_raises_when_resume_directory_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_valid_files(tmp_path)
    _set_env(monkeypatch, tmp_path, BASE_ENV)
    monkeypatch.setenv("RESUMES_DIR", str(tmp_path / "nonexistent"))
    with pytest.raises(ConfigurationError, match="resumes"):
        load_config()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _setup_valid_files(
    tmp_path: Path,
    scrape_tier: str = "http",
    empty_targets: bool = False,
    no_resumes: bool = False,
    resume_files: list[str] | None = None,
    resume_content: str = "# Resume placeholder",
) -> None:
    targets_dir = tmp_path / "config"
    targets_dir.mkdir()
    if empty_targets:
        (targets_dir / "targets.yaml").write_text("sites: []\n")
    else:
        (targets_dir / "targets.yaml").write_text(
            f"sites:\n"
            f"  - name: Test Corp\n"
            f"    url: https://test.com/jobs\n"
            f"    scrape_tier: {scrape_tier}\n"
        )

    resumes_dir = tmp_path / "resumes"
    resumes_dir.mkdir()
    if not no_resumes:
        files = resume_files or ["software_engineer_ai.md"]
        for fname in files:
            (resumes_dir / fname).write_text(resume_content)


def _set_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env: dict[str, str],
) -> None:
    # Clear all relevant env vars first
    for key in [*BASE_ENV.keys(), "MATCH_THRESHOLD", "DRY_RUN", "RESUMES_DIR"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("TARGETS_FILE", str(tmp_path / "config" / "targets.yaml"))
    monkeypatch.setenv("RESUMES_DIR", str(tmp_path / "resumes"))
