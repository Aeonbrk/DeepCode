"""
Configuration API Routes
Handles LLM provider and settings management
"""

from fastapi import APIRouter, HTTPException
import os
import tempfile
import yaml

from settings import (
    load_mcp_config,
    load_secrets,
    get_llm_provider,
    get_llm_models,
    is_indexing_enabled,
    CONFIG_PATH,
)
from models.requests import LLMProviderUpdateRequest
from models.responses import ConfigResponse, SettingsResponse


router = APIRouter()


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """Get current application settings"""
    config = load_mcp_config()
    provider = get_llm_provider()
    models = get_llm_models(provider)

    return SettingsResponse(
        llm_provider=provider,
        models=models,
        indexing_enabled=is_indexing_enabled(),
        document_segmentation=config.get("document_segmentation", {}),
    )


@router.get("/llm-providers", response_model=ConfigResponse)
async def get_llm_providers():
    """Get available LLM providers and their configurations"""
    secrets = load_secrets()

    # Get available providers (those with API keys configured)
    available_providers = []
    for provider in ["google", "anthropic", "openai"]:
        if secrets.get(provider, {}).get("api_key"):
            available_providers.append(provider)

    current_provider = get_llm_provider()
    models = get_llm_models(current_provider)

    return ConfigResponse(
        llm_provider=current_provider,
        available_providers=available_providers,
        models=models,
        indexing_enabled=is_indexing_enabled(),
    )


@router.put("/llm-provider")
async def set_llm_provider(request: LLMProviderUpdateRequest):
    """Update the preferred LLM provider"""
    secrets = load_secrets()

    # Verify provider has an API key
    if not secrets.get(request.provider, {}).get("api_key"):
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{request.provider}' does not have an API key configured",
        )

    # Update config file
    try:
        config = load_mcp_config()
        config["llm_provider"] = request.provider

        config_dir = os.path.dirname(CONFIG_PATH)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=config_dir,
                delete=False,
            ) as temp_file:
                yaml.safe_dump(config, temp_file, sort_keys=False)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = temp_file.name

            os.replace(temp_path, CONFIG_PATH)
            dir_fd = os.open(config_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

        return {
            "status": "success",
            "message": f"LLM provider updated to '{request.provider}'",
            "provider": request.provider,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update configuration: {str(e)}",
        )
