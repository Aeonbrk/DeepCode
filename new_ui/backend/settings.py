"""
Configuration management for DeepCode New UI Backend
Reads from existing mcp_agent.config.yaml and mcp_agent.secrets.yaml
"""

import copy
from functools import lru_cache
from pathlib import Path
from typing import Optional, Dict, Any

import yaml
from pydantic_settings import BaseSettings


# Project paths
BACKEND_DIR = Path(__file__).resolve().parent
NEW_UI_DIR = BACKEND_DIR.parent
PROJECT_ROOT = NEW_UI_DIR.parent
CONFIG_PATH = PROJECT_ROOT / "mcp_agent.config.yaml"
SECRETS_PATH = PROJECT_ROOT / "mcp_agent.secrets.yaml"


class Settings(BaseSettings):
    """Application settings"""

    # Server settings
    # Safer default: bind to localhost unless explicitly overridden (for example via Docker).
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True

    # Environment: "docker" for production, anything else for development
    env: str = ""

    # CORS settings - in Docker mode, frontend is served by FastAPI (same origin)
    cors_origins: list = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]

    # File upload settings
    max_upload_size: int = 100 * 1024 * 1024  # 100MB
    upload_dir: str = str(PROJECT_ROOT / "uploads")

    # Session settings
    session_timeout: int = 3600  # 1 hour

    # WebSocket log streaming can expose sensitive info. Keep it off by default.
    enable_logs_ws: bool = False
    # When enabled, require ws/logs/{session_id} to map to a specific log file.
    strict_logs_ws_session: bool = True

    class Config:
        env_prefix = "DEEPCODE_"


settings = Settings()


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    try:
        mtime_ns = path.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    # Return a defensive copy so callers can mutate without polluting the cache.
    return copy.deepcopy(_load_yaml_file_cached(str(path), mtime_ns))


@lru_cache(maxsize=8)
def _load_yaml_file_cached(path_str: str, mtime_ns: int) -> Dict[str, Any]:
    # mtime_ns is included to invalidate cache when the file changes.
    _ = mtime_ns
    path = Path(path_str)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_mcp_config() -> Dict[str, Any]:
    """Load main MCP agent configuration"""
    return _load_yaml_file(CONFIG_PATH)


def load_secrets() -> Dict[str, Any]:
    """Load API secrets configuration"""
    return _load_yaml_file(SECRETS_PATH)


def get_llm_provider() -> str:
    """Get the preferred LLM provider from config"""
    config = load_mcp_config()
    return config.get("llm_provider", "google")


def get_llm_models(provider: Optional[str] = None) -> Dict[str, str]:
    """Get the model configuration for a provider"""
    config = load_mcp_config()
    provider = provider or get_llm_provider()

    provider_config = config.get(provider, {})
    return {
        "default": provider_config.get("default_model", ""),
        "planning": provider_config.get("planning_model", ""),
        "implementation": provider_config.get("implementation_model", ""),
    }


def get_api_key(provider: str) -> Optional[str]:
    """Get API key for a specific provider"""
    secrets = load_secrets()
    provider_secrets = secrets.get(provider, {})
    return provider_secrets.get("api_key")


def is_indexing_enabled() -> bool:
    """Check if document indexing is enabled"""
    config = load_mcp_config()
    doc_seg = config.get("document_segmentation", {})
    return doc_seg.get("enabled", False)
