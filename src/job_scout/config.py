import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from job_scout.models import ResumeProfile, SiteTarget

logger = logging.getLogger(__name__)

VALID_SCRAPE_TIERS = {"http", "playwright"}

KNOWN_RESUME_LABELS: dict[str, str] = {
    "software_engineer_ai.md": "Software Engineer (AI Focused)",
    "ai_engineer.md": "AI Engineer",
    "data_scientist.md": "Data Scientist",
}


class ConfigurationError(Exception):
    pass


@dataclass
class AppConfig:
    anthropic_api_key: str
    supabase_url: str
    supabase_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    match_threshold: float
    dry_run: bool
    targets: list[SiteTarget]
    resumes_dir: Path
    resumes: list[ResumeProfile]


def load_config() -> AppConfig:
    anthropic_api_key = _require_env("ANTHROPIC_API_KEY")
    supabase_url = _require_env("SUPABASE_URL")
    supabase_key = _require_env("SUPABASE_KEY")
    telegram_bot_token = _require_env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = _require_env("TELEGRAM_CHAT_ID")

    match_threshold = float(os.getenv("MATCH_THRESHOLD", "0.70"))
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    targets_file = Path(os.getenv("TARGETS_FILE", "config/targets.yaml"))
    targets = _load_targets(targets_file)

    resumes_dir = Path(os.getenv("RESUMES_DIR", "resumes"))
    resumes = _load_resumes(resumes_dir)

    return AppConfig(
        anthropic_api_key=anthropic_api_key,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        match_threshold=match_threshold,
        dry_run=dry_run,
        targets=targets,
        resumes_dir=resumes_dir,
        resumes=resumes,
    )


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _load_targets(targets_file: Path) -> list[SiteTarget]:
    with targets_file.open() as f:
        data = yaml.safe_load(f)

    sites = data.get("sites", [])
    if not sites:
        raise ConfigurationError("targets list is empty — add at least one site to targets.yaml")

    targets = []
    for entry in sites:
        tier = entry["scrape_tier"]
        if tier not in VALID_SCRAPE_TIERS:
            raise ConfigurationError(
                f"Invalid scrape_tier '{tier}' for site '{entry['name']}'. "
                f"Must be one of: {sorted(VALID_SCRAPE_TIERS)}"
            )
        targets.append(SiteTarget(
            name=entry["name"],
            url=entry["url"],
            scrape_tier=tier,
        ))

    return targets


def _load_resumes(resumes_dir: Path) -> list[ResumeProfile]:
    if not resumes_dir.exists():
        raise ConfigurationError(
            f"resumes directory not found: {resumes_dir}"
        )

    md_files = sorted(resumes_dir.glob("*.md"))
    if not md_files:
        raise ConfigurationError(
            f"No .md resume files found in {resumes_dir}"
        )

    resumes = []
    for path in md_files:
        filename = path.name
        label = KNOWN_RESUME_LABELS.get(filename) or _filename_to_label(filename)
        content = path.read_text(encoding="utf-8")
        resumes.append(ResumeProfile(
            role_label=label,
            filename=filename,
            content=content,
        ))
        logger.info("Loaded resume: %s (%s)", filename, label)

    return resumes


def _filename_to_label(filename: str) -> str:
    stem = Path(filename).stem
    return stem.replace("_", " ").title()
