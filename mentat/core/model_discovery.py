"""
Dynamic model discovery for OpenRouter zero data retention endpoints.
Fetches available models and updates MENTAT's model configuration.
"""

import json
import requests
import time
from typing import Dict, List, Optional
import os

# Cache duration for model list (24 hours)
CACHE_DURATION_HOURS = 24
CACHE_FILE_PATH = "data/model_cache.json"

class ModelDiscovery:
    """Handles dynamic discovery and management of OpenRouter zero-retention models."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize with optional API key for authenticated requests."""
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.base_url = "https://openrouter.ai/api/v1"

    def fetch_zero_retention_models(self) -> Dict[str, str]:
        """
        Fetch models with zero data retention from OpenRouter API.

        Returns:
            Dict mapping user-friendly names to OpenRouter model IDs
            Example: {"Claude 3.7 Sonnet": "anthropic/claude-3-7-sonnet-20250219"}
        """
        try:
            # Try to load from cache first
            cached_models = self._load_cached_models()
            if cached_models:
                return cached_models

            # Fetch fresh data from API
            models = self._fetch_models_from_api()
            processed_models = self._process_models(models)

            # Cache the results
            self._cache_models(processed_models)

            return processed_models

        except Exception as e:
            print(f"Warning: Failed to fetch dynamic models: {e}")
            return {}

    def _fetch_models_from_api(self) -> List[Dict]:
        """Fetch raw model data from OpenRouter zero-retention endpoint."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = requests.get(
            f"{self.base_url}/endpoints/zdr",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()

        data = response.json()
        return data.get("data", [])

    def _process_models(self, models: List[Dict]) -> Dict[str, str]:
        """
        Process and deduplicate models from API response.

        Args:
            models: Raw model data from OpenRouter API

        Returns:
            Dict mapping friendly names to model IDs
        """
        seen_models = {}
        processed = {}

        for model in models:
            # Extract model ID from "name" field (after " | " separator)
            full_name = model.get("name", "")
            if " | " in full_name:
                model_id = full_name.split(" | ", 1)[1]  # Get part after " | "
            else:
                model_id = full_name

            # Skip if we can't extract a valid model ID
            if not model_id or "/" not in model_id:
                continue

            # Create user-friendly name from model_name field
            model_name = model.get("model_name", "")
            friendly_name = self._create_friendly_name(model_name, model_id)

            # Handle duplicates - prefer models with better characteristics
            if friendly_name in seen_models:
                existing_model = seen_models[friendly_name]
                if self._is_better_model(model, existing_model):
                    seen_models[friendly_name] = model
                    processed[friendly_name] = model_id
            else:
                seen_models[friendly_name] = model
                processed[friendly_name] = model_id

        return processed

    def _create_friendly_name(self, model_name: str, model_id: str) -> str:
        """
        Create a user-friendly name for a model.

        Args:
            model_name: The model_name field from API (e.g., "Anthropic: Claude 3.7 Sonnet")
            model_id: The extracted model ID (e.g., "anthropic/claude-3-7-sonnet-20250219")

        Returns:
            Clean, user-friendly name
        """
        if model_name:
            # Clean up the model name
            name = model_name.strip()

            # Remove provider prefixes (e.g., "Anthropic: " -> "")
            for prefix in ["Anthropic:", "OpenAI:", "Google:", "Meta:", "Mistral:", "DeepSeek:", "Qwen:"]:
                if name.startswith(prefix):
                    name = name[len(prefix):].strip()
                    break

            return name
        else:
            # Fallback: create name from model ID
            # Convert "anthropic/claude-3-7-sonnet-20250219" -> "Claude 3 7 Sonnet"
            parts = model_id.split("/")
            if len(parts) > 1:
                model_part = parts[1]
                # Remove dates and version numbers, convert dashes to spaces
                clean_name = model_part.split("-202")[0]  # Remove dates like -20250219
                clean_name = clean_name.replace("-", " ").replace("_", " ")
                return " ".join(word.capitalize() for word in clean_name.split())
            return model_id

    def _is_better_model(self, model1: Dict, model2: Dict) -> bool:
        """
        Compare two models to determine which is preferable.

        Priority: Higher uptime > Lower cost > Newer model
        """
        # Prefer models with higher uptime
        uptime1 = model1.get("uptime_last_30m") or 0
        uptime2 = model2.get("uptime_last_30m") or 0

        if uptime1 != uptime2:
            return uptime1 > uptime2

        # Prefer models with lower costs
        pricing1 = model1.get("pricing", {})
        pricing2 = model2.get("pricing", {})

        cost1 = float(pricing1.get("prompt", 0)) + float(pricing1.get("completion", 0))
        cost2 = float(pricing2.get("prompt", 0)) + float(pricing2.get("completion", 0))

        if cost1 != cost2:
            return cost1 < cost2

        # Prefer models with higher context length
        context1 = model1.get("context_length", 0)
        context2 = model2.get("context_length", 0)

        return context1 > context2

    def _load_cached_models(self) -> Optional[Dict[str, str]]:
        """Load models from cache if still valid."""
        try:
            if not os.path.exists(CACHE_FILE_PATH):
                return None

            # Check if cache is still valid
            cache_age_hours = (time.time() - os.path.getmtime(CACHE_FILE_PATH)) / 3600
            if cache_age_hours > CACHE_DURATION_HOURS:
                return None

            with open(CACHE_FILE_PATH, 'r') as f:
                cache_data = json.load(f)
                return cache_data.get("models", {})

        except Exception:
            return None

    def _cache_models(self, models: Dict[str, str]) -> None:
        """Cache models to disk."""
        try:
            # Ensure cache directory exists
            cache_dir = os.path.dirname(CACHE_FILE_PATH)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)

            cache_data = {
                "models": models,
                "timestamp": time.time(),
                "cached_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "model_count": len(models)
            }

            with open(CACHE_FILE_PATH, 'w') as f:
                json.dump(cache_data, f, indent=2)

        except Exception as e:
            print(f"Warning: Failed to cache models: {e}")


# Convenience functions for external use

def get_dynamic_models() -> Dict[str, str]:
    """
    Get zero-retention models from OpenRouter.

    Returns:
        Dict mapping user-friendly names to OpenRouter model IDs
        Example: {"Claude 3.7 Sonnet": "anthropic/claude-3-7-sonnet-20250219"}
    """
    discovery = ModelDiscovery()
    return discovery.fetch_zero_retention_models()


def get_curated_models() -> Dict[str, str]:
    """
    Get a curated list of top/popular zero-retention models for cleaner UI display.

    Returns:
        Dict mapping user-friendly names to OpenRouter model IDs for top models
    """
    all_models = get_dynamic_models()

    # Priority list of model patterns to include (in order of preference)
    priority_patterns = [
        # Anthropic Claude models
        ("claude 4.1 opus", "claude-4.1-opus"),
        ("claude opus 4", "claude-4-opus"),
        ("claude 4 sonnet", "claude-4-sonnet"),
        ("claude 3.7 sonnet", "claude-3-7-sonnet"),
        ("claude 3.5 sonnet", "claude-3.5-sonnet"),

        # Google Gemini models
        ("gemini 2.5 pro", "gemini-2.5-pro"),
        ("gemini 2.5 flash", "gemini-2.5-flash"),
        ("gemini 2.0 flash", "gemini-2.0-flash"),

        # Meta Llama models
        ("llama 4 maverick", "llama-4-maverick"),
        ("llama 3.1 405b", "llama-3.1-405b"),
        ("llama 3.3 70b", "llama-3.3-70b"),
        ("llama 3.1 70b", "llama-3.1-70b"),

        # Qwen models
        ("qwen3 235b", "qwen3-235b"),
        ("qwen3 32b", "qwen3-32b"),

        # DeepSeek models
        ("deepseek v3.1", "deepseek-chat-v3.1"),
        ("deepseek r1", "deepseek-r1"),

        # Other notable models
        ("mixtral 8x22b", "mixtral-8x22b"),
        ("gpt-oss-120b", "gpt-oss-120b"),
        ("kimi k2", "kimi-k2"),
        ("glm 4.5v", "glm-4.5v"),
        ("ernie 4.5", "ernie-4.5"),
        ("r1 1776", "r1-1776"),
    ]

    curated = {}
    seen_base_models = set()

    # Find models matching priority patterns
    for search_term, base_key in priority_patterns:
        if len(curated) >= 20:  # Limit to ~15 top models
            break

        # Skip if we already have a variant of this base model
        if base_key in seen_base_models:
            continue

        # Find best match for this pattern
        best_match = None
        for model_name, model_id in all_models.items():
            name_lower = model_name.lower()
            if all(word in name_lower for word in search_term.split()):
                # Prefer models without ":free" suffix (better performance usually)
                if best_match is None or (":free" not in model_id and ":free" in best_match[1]):
                    best_match = (model_name, model_id)

        if best_match:
            curated[best_match[0]] = best_match[1]
            seen_base_models.add(base_key)

    return curated


def refresh_model_cache() -> Dict[str, str]:
    """
    Force refresh of model cache by deleting existing cache and fetching fresh data.

    Returns:
        Dict of refreshed models
    """
    try:
        if os.path.exists(CACHE_FILE_PATH):
            os.remove(CACHE_FILE_PATH)
    except Exception:
        pass

    return get_dynamic_models()


def get_cached_model_info() -> Optional[Dict]:
    """
    Get information about the current model cache status.

    Returns:
        Dict with cache metadata, or None if no cache exists
    """
    try:
        if not os.path.exists(CACHE_FILE_PATH):
            return None

        with open(CACHE_FILE_PATH, 'r') as f:
            cache_data = json.load(f)

        cache_age_hours = (time.time() - cache_data.get("timestamp", 0)) / 3600

        return {
            "cached_at": cache_data.get("cached_at"),
            "model_count": cache_data.get("model_count", 0),
            "age_hours": round(cache_age_hours, 1),
            "is_stale": cache_age_hours > CACHE_DURATION_HOURS
        }

    except Exception:
        return None
