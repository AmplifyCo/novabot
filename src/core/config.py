"""Configuration loader for the autonomous agent."""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from .types import AgentConfig


def load_config(env_file: str = ".env", config_file: str = "config/agent.yaml") -> AgentConfig:
    """Load configuration from environment and yaml files.

    Args:
        env_file: Path to .env file
        config_file: Path to agent.yaml config file

    Returns:
        AgentConfig instance with all settings
    """
    # Load environment variables
    load_dotenv(env_file)

    # Load YAML config if exists
    yaml_config = {}
    if Path(config_file).exists():
        with open(config_file, 'r') as f:
            yaml_config = yaml.safe_load(f) or {}

    # Build config from environment (takes precedence) and YAML
    config = AgentConfig(
        # API
        api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        default_model=os.getenv("DEFAULT_MODEL", yaml_config.get("agent", {}).get("models", {}).get("default", "claude-opus-4-6")),
        subagent_model=os.getenv("SUBAGENT_MODEL", yaml_config.get("agent", {}).get("models", {}).get("subagent", "claude-sonnet-4-5")),

        # Execution
        max_iterations=int(os.getenv("MAX_ITERATIONS", yaml_config.get("agent", {}).get("execution", {}).get("max_iterations", 50))),
        timeout_seconds=int(os.getenv("TIMEOUT_SECONDS", yaml_config.get("agent", {}).get("execution", {}).get("timeout_seconds", 300))),
        retry_attempts=int(os.getenv("RETRY_ATTEMPTS", yaml_config.get("agent", {}).get("execution", {}).get("retry_attempts", 3))),
        self_build_mode=os.getenv("SELF_BUILD_MODE", "true").lower() == "true",

        # Brain
        vector_db_path=os.getenv("VECTOR_DB_PATH", "./data/chroma"),
        core_brain_path=os.getenv("CORE_BRAIN_PATH", "./data/core_brain"),
        digital_clone_brain_path=os.getenv("DIGITAL_CLONE_BRAIN_PATH", "./data/digital_clone_brain"),
        memory_path=os.getenv("MEMORY_PATH", "./data/memory"),

        # Git
        auto_commit=os.getenv("AUTO_COMMIT", "true").lower() == "true",
        git_user_name=os.getenv("GIT_USER_NAME", "Autonomous Agent"),
        git_user_email=os.getenv("GIT_USER_EMAIL", "agent@autonomous.ai"),

        # Monitoring
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        dashboard_enabled=yaml_config.get("monitoring", {}).get("dashboard", {}).get("enabled", True),
        dashboard_host=os.getenv("DASHBOARD_HOST", yaml_config.get("monitoring", {}).get("dashboard", {}).get("host", "0.0.0.0")),
        dashboard_port=int(os.getenv("DASHBOARD_PORT", yaml_config.get("monitoring", {}).get("dashboard", {}).get("port", 18789))),

        # Logging
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_file=os.getenv("LOG_FILE", "./data/logs/agent.log"),
    )

    # Validate required fields
    if not config.api_key:
        raise ValueError("ANTHROPIC_API_KEY is required but not set in .env file")

    return config
