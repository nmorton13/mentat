"""
Centralized configuration for MENTAT applications.
Contains model definitions, defaults, and shared settings.

CONFIGURATION GUIDE:
===================
All settings in this file can be customized by creating a .env file in the project root.
Settings are loaded with sensible defaults if not specified in .env.

COMMON CUSTOMIZATIONS:
=====================
Create a .env file with these popular settings:

    # REQUIRED API KEYS
    OPENROUTER_API_KEY=your_openrouter_key_here
    # OR for direct OpenAI access:
    OPENAI_API_KEY=your_openai_key_here
    
    # MODEL SELECTION (pick one from AVAILABLE_MODELS below)
    OPENROUTER_MODEL=x-ai/grok-4.5
    # Optional: route normal chat/capture/summaries to a local/OpenAI-compatible server
    CHAT_BASE_URL=http://localhost:1234/v1
    CHAT_API_KEY=local
    CHAT_MODEL=qwen-local
    # Optional: native Ollama route, selectable with /model ollama <model>
    OLLAMA_BASE_URL=http://127.0.0.1:11434
    OLLAMA_MODEL=gemma4:12b-mlx
    OLLAMA_THINK=false
    OLLAMA_TEMPERATURE=1.0
    OLLAMA_TOP_P=0.95
    OLLAMA_TOP_K=64
    # Optional: shared helper/task model defaults, with per-helper overrides below
    HELPERS_PROVIDER=openrouter
    HELPERS_MODEL=google/gemini-3.1-flash-lite
    # Optional: separate OpenRouter model for web-backed calls
    # Leave blank to use the active model with OpenRouter's web_search server tool
    ONLINE_MODEL=openai/gpt-chat-latest
    
    # PERFORMANCE TUNING
    CHAT_MEMORY_K=15                           # More context in chat
    CHAT_MIN_SIMILARITY=0.2                    # Chat semantic match strictness
    CHAT_HYBRID_SEARCH_K=50                    # Chat retrieval breadth
    SEMANTIC_SEARCH_MIN_SIMILARITY=0.2         # Higher quality search results
    EMBEDDING_MODEL=all-mpnet-base-v2          # Better embeddings (slower)
    
    # SEARCH & DISPLAY CUSTOMIZATION
    SEARCH_RESULTS_K=12                        # More search results
    LINKS_DISPLAY_LIMIT=30                     # More links displayed
    CHAT_PREVIEW_LENGTH=200                    # Longer previews
    
    # CONCEPT EXPLORATION
    CONCEPT_EXPLORATION_DEFAULT_DEPTH=4        # Deeper concept exploration
    CONCEPT_NOVELTY_THRESHOLD=0.4              # Higher novelty detection

CATEGORIES EXPLAINED:
====================
- MODEL CONFIGURATION: AI model selection and API setup
- EMBEDDING CONFIGURATION: Local semantic search settings
- SEARCH & MEMORY: How much context to retrieve and use
- DISPLAY LIMITS: How much information to show in UI
- CONCEPT EXPLORATION: ConceptExplorer system settings
- PERFORMANCE: Cache sizes, timeouts, and optimization
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# MODEL CONFIGURATION
# =============================================================================

# Model configuration file (curated list)
MODEL_CONFIG_PATH = os.getenv("MODEL_CONFIG_PATH", "config/models.json")


def _load_model_config() -> Dict[str, Any]:
    config_path = Path(MODEL_CONFIG_PATH)
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"Warning: Failed to load model config from {MODEL_CONFIG_PATH}: {exc}")
        return {}


def _build_model_registry(config: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    models = config.get("models") if isinstance(config, dict) else None
    if not isinstance(models, list):
        return {}, {}
    available: Dict[str, str] = {}
    metadata: Dict[str, Dict[str, Any]] = {}
    for entry in models:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        label = entry.get("label") or model_id
        if not model_id or not label:
            continue
        available[label] = model_id
        metadata[model_id] = {
            "label": label,
            "reasoning": bool(entry.get("reasoning", False)),
        }
    return available, metadata


MODEL_CONFIG = _load_model_config()

# Default OpenRouter model - this is the fallback if no environment variable is set
# You can change this to any model from AVAILABLE_MODELS below
DEFAULT_OPENROUTER_MODEL = MODEL_CONFIG.get("default_model", "x-ai/grok-4.5")

# Get model from environment or use default
# Set in .env as: OPENROUTER_MODEL=x-ai/grok-4.5
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)

# Optional OpenAI-compatible endpoint for normal chat/capture/summary calls.
# Leave these unset to preserve the existing OpenRouter behavior.
CHAT_BASE_URL = os.getenv("CHAT_BASE_URL", "").strip() or None
CHAT_API_KEY = os.getenv("CHAT_API_KEY", "").strip() or None
CHAT_MODEL = os.getenv("CHAT_MODEL", "").strip() or None

# Native Ollama provider settings. This is intentionally separate from the
# OpenAI-compatible local route because Ollama's native /api/chat supports
# options like think=false more reliably than its /v1 compatibility endpoint.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/") or "http://127.0.0.1:11434"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:12b-mlx").strip() or None
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "false").strip().lower() in {"1", "true", "yes", "on"}
OLLAMA_TEMPERATURE = os.getenv("OLLAMA_TEMPERATURE", "").strip() or None
OLLAMA_TOP_P = os.getenv("OLLAMA_TOP_P", "").strip() or None
OLLAMA_TOP_K = os.getenv("OLLAMA_TOP_K", "").strip() or None
OLLAMA_NUM_PREDICT = os.getenv("OLLAMA_NUM_PREDICT", "").strip() or None

# Shared local OpenAI-compatible provider settings for per-feature routing.
# Set in .env as: LOCAL_BASE_URL=http://localhost:1234/v1
LOCAL_BASE_URL = os.getenv("LOCAL_BASE_URL", "").strip() or None
LOCAL_API_KEY = os.getenv("LOCAL_API_KEY", "local").strip() or "local"
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "").strip() or None

# Optional shared helper/task routing defaults. Individual <TASK>_* settings
# below override these; unset values fall back to active chat routing.
# Set in .env as: HELPERS_PROVIDER=openrouter and HELPERS_MODEL=google/gemini-3.1-flash-lite
HELPERS_PROVIDER = os.getenv("HELPERS_PROVIDER", "").strip().lower() or None
HELPERS_MODEL = os.getenv("HELPERS_MODEL", "").strip() or None

# Optional OpenRouter model for explicit web-backed calls.
# Set in .env as: ONLINE_MODEL=openai/gpt-chat-latest
# Leave unset to use the active model with OpenRouter's web_search server tool.
# Legacy values ending in :online are normalized before requests are sent.
ONLINE_MODEL = os.getenv("ONLINE_MODEL", "").strip() or None

AVAILABLE_MODELS, MODEL_METADATA = _build_model_registry(MODEL_CONFIG)

if not AVAILABLE_MODELS:
    print("Warning: No curated models found, using fallback list")
    AVAILABLE_MODELS = {
        "grok-4.5": "x-ai/grok-4.5",
        "gpt-5.6-terra": "openai/gpt-5.6-terra",
        "gpt-chat-latest": "openai/gpt-chat-latest",
        "claude-sonnet-5": "anthropic/claude-sonnet-5",
        "claude-opus-4.8": "anthropic/claude-opus-4.8",
        "gemini-3.5-flash": "google/gemini-3.5-flash",
        "minimax-m3": "minimax/minimax-m3",
        "glm-5.2": "z-ai/glm-5.2",
    }
    MODEL_METADATA = {
        "x-ai/grok-4.5": {"label": "grok-4.5", "reasoning": True},
        "openai/gpt-5.6-terra": {"label": "gpt-5.6-terra", "reasoning": True},
        "openai/gpt-chat-latest": {"label": "gpt-chat-latest", "reasoning": False},
        "anthropic/claude-sonnet-5": {"label": "claude-sonnet-5", "reasoning": True},
        "anthropic/claude-opus-4.8": {"label": "claude-opus-4.8", "reasoning": True},
        "google/gemini-3.5-flash": {"label": "gemini-3.5-flash", "reasoning": True},
        "minimax/minimax-m3": {"label": "minimax-m3", "reasoning": True},
        "z-ai/glm-5.2": {"label": "glm-5.2", "reasoning": True},
    }

# =============================================================================
# API CONFIGURATION
# =============================================================================

# API Keys - Set these in your .env file
# Required: OPENROUTER_API_KEY (for most models) or OPENAI_API_KEY (for direct OpenAI)
# Optional: ANTHROPIC_API_KEY, GEMINI_API_KEY (for direct API access)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# API Base URLs - normally you don't need to change these
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def is_custom_chat_provider_configured() -> bool:
    """Return True when normal LLM calls should use custom CHAT_* routing/model settings."""
    return bool(CHAT_BASE_URL or CHAT_MODEL)


def _runtime_chat_provider() -> Optional[str]:
    """Return the runtime-selected chat provider, if one has been selected."""
    provider = _load_runtime_settings().get("chat_provider")
    if not isinstance(provider, str):
        return None
    provider = provider.strip().lower()
    return provider if provider in {"openrouter", "local", "custom", "ollama"} else None


def get_chat_provider() -> str:
    """Return the effective normal chat provider.

    Runtime selection from `/model` wins over .env. The .env CHAT_* values are
    fallback defaults for users who have not selected a route in the CLI.
    """
    runtime_provider = _runtime_chat_provider()
    if runtime_provider:
        return runtime_provider
    if CHAT_BASE_URL:
        if "localhost" in CHAT_BASE_URL or "127.0.0.1" in CHAT_BASE_URL:
            return "local"
        return "custom"
    return "openrouter"


def get_chat_base_url() -> str:
    """Base URL for normal chat/capture/summary LLM calls."""
    provider = get_chat_provider()
    if provider == "openrouter":
        return OPENROUTER_BASE_URL
    if provider == "local":
        return LOCAL_BASE_URL or CHAT_BASE_URL or "http://localhost:1234/v1"
    if provider == "ollama":
        return OLLAMA_BASE_URL
    return CHAT_BASE_URL or OPENROUTER_BASE_URL


def get_chat_api_key() -> Optional[str]:
    """API key for normal LLM calls, with a harmless local default for local endpoints."""
    provider = get_chat_provider()
    if provider == "openrouter":
        return OPENROUTER_API_KEY or None
    if provider == "local":
        return CHAT_API_KEY or LOCAL_API_KEY or "local"
    if provider == "ollama":
        return None
    if CHAT_API_KEY:
        return CHAT_API_KEY
    if CHAT_BASE_URL:
        return "local"
    return OPENROUTER_API_KEY or None

# =============================================================================
# EMBEDDING MODEL CONFIGURATION
# =============================================================================

# Local embedding model for semantic search
# Options: all-MiniLM-L6-v2 (fast, 384d), all-mpnet-base-v2 (better quality, 768d)
# Set in .env as: EMBEDDING_MODEL=all-mpnet-base-v2
# Default changed to all-mpnet-base-v2 for better semantic understanding
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'all-mpnet-base-v2')

# Model dimension mapping for supported sentence-transformer models
# Don't change these unless you know what you're doing
EMBEDDING_MODEL_DIMENSIONS = {
    'all-MiniLM-L6-v2': 384,        # Fast, good for most use cases
    'all-mpnet-base-v2': 768,       # Better quality, slower
    'multi-qa-MiniLM-L6-cos-v1': 384,  # Optimized for Q&A
    'all-MiniLM-L12-v2': 384,       # Larger variant
    'paraphrase-MiniLM-L6-v2': 384  # Optimized for paraphrase detection
}

# Get current model dimensions (automatically set based on EMBEDDING_MODEL)
CURRENT_EMBEDDING_DIMENSIONS = EMBEDDING_MODEL_DIMENSIONS.get(EMBEDDING_MODEL, 384)

# =============================================================================
# USER CONFIGURATION
# =============================================================================

# Default user ID for the system
# Set in .env as: MENTAT_USER_ID=your_name
DEFAULT_USER_ID = os.getenv("MENTAT_USER_ID", "mentat")
#DEFAULT_USER_ID = os.getenv("MENTAT_USER_ID", "nmorton")

# =============================================================================
# CACHE & PERFORMANCE CONFIGURATION
# =============================================================================

# How many embeddings to cache in memory (higher = faster, more RAM)
# Set in .env as: EMBEDDING_CACHE_SIZE=2000
EMBEDDING_CACHE_SIZE = int(os.getenv("EMBEDDING_CACHE_SIZE", "1000"))

# Number of recent chat messages to keep in context
# Set in .env as: CHAT_HISTORY_LENGTH=10
CHAT_HISTORY_LENGTH = int(os.getenv("CHAT_HISTORY_LENGTH", "6"))

USER_TIMEZONE = os.getenv("USER_TIMEZONE", "America/Chicago")

# =============================================================================
# LLM LOGGING CONFIGURATION
# =============================================================================

# Enable logging of all LLM prompts and responses to disk
# Useful for debugging, prompt optimization, and token usage analysis
# Set in .env as: LLM_LOGGING_ENABLED=true
LLM_LOGGING_ENABLED = os.getenv("LLM_LOGGING_ENABLED", "false").lower() == "true"

# Directory where LLM logs will be saved
# Set in .env as: LLM_LOG_DIR=data/llm_logs
LLM_LOG_DIR = os.getenv("LLM_LOG_DIR", "data/llm_logs")

# =============================================================================
# SEARCH & MEMORY CONFIGURATION
# =============================================================================

# Number of memories to retrieve for different contexts
# Higher values = more context but slower processing
CHAT_MEMORY_K = int(os.getenv("CHAT_MEMORY_K", "10"))           # General chat context
SEARCH_RESULTS_K = int(os.getenv("SEARCH_RESULTS_K", "8"))       # /search command results
PROJECT_ANALYSIS_K = int(os.getenv("PROJECT_ANALYSIS_K", "25"))  # /project command analysis
SYNTHESIS_K = int(os.getenv("SYNTHESIS_K", "15"))               # /synthesize command gathering
# Chat-specific semantic search controls (defaults mirror previous hardcoded values)
CHAT_MIN_SIMILARITY = float(os.getenv("CHAT_MIN_SIMILARITY", "0.2"))  # Min similarity for chat semantic matches
CHAT_HYBRID_SEARCH_K = int(os.getenv("CHAT_HYBRID_SEARCH_K", str(PROJECT_ANALYSIS_K)))  # How many chat results to fetch


def resolve_chat_retrieval_limits(memory_count: int) -> Dict[str, Any]:
    """Resolve corpus-sized chat limits while preserving explicit overrides."""
    memory_count = max(0, memory_count)
    automatic_search_k = min(memory_count, 25)
    automatic_candidate_count = min(memory_count, 75)
    automatic_multiplier = (
        automatic_candidate_count / automatic_search_k
        if automatic_search_k
        else 1.0
    )

    return {
        "search_k": int(os.environ.get("CHAT_HYBRID_SEARCH_K", automatic_search_k)),
        "internal_multiplier": float(
            os.environ.get(
                "HYBRID_SEARCH_INTERNAL_MULTIPLIER",
                automatic_multiplier,
            )
        ),
        "context_limit": int(
            os.environ.get("CHAT_CONTEXT_LIMIT", min(memory_count, 50))
        ),
    }

# Minimum similarity threshold for semantic search (0.0-1.0)
# Lower values = more results but potentially less relevant
# Higher values = fewer but more relevant results
# Set in .env as: SEMANTIC_SEARCH_MIN_SIMILARITY=0.2
SEMANTIC_SEARCH_MIN_SIMILARITY = float(os.getenv("SEMANTIC_SEARCH_MIN_SIMILARITY", "0.1"))

# Similarity thresholds for different search contexts
# These can be tuned separately for optimal results in each use case
CHAT_SEARCH_MIN_SIMILARITY = float(os.getenv("CHAT_SEARCH_MIN_SIMILARITY", "0.1"))
PROJECT_SEARCH_MIN_SIMILARITY = float(os.getenv("PROJECT_SEARCH_MIN_SIMILARITY", "0.25"))

# =============================================================================
# CONNECTION SURFACING CONFIGURATION
# =============================================================================

# "This reminds me of..." feature settings
# Number of connections to find and display
CONNECTION_SURFACING_K = int(os.getenv("CONNECTION_SURFACING_K", "6"))      # How many to find
CONNECTION_DISPLAY_LIMIT = int(os.getenv("CONNECTION_DISPLAY_LIMIT", "5"))  # How many to show

# =============================================================================
# REFERENCE/CONCEPT DETECTION CONFIGURATION
# =============================================================================

# Maximum number of post-chat exploration references to show
MAX_TOTAL_REFERENCES = int(os.getenv("MAX_TOTAL_REFERENCES", "5"))

# =============================================================================
# WEB SEARCH CONFIGURATION
# =============================================================================

# When to trigger web searches for entities (based on how often they appear)
# Set in .env as: WEB_SEARCH_ENTITY_FREQUENCY_THRESHOLD=5
WEB_SEARCH_ENTITY_FREQUENCY_THRESHOLD = int(os.getenv("WEB_SEARCH_ENTITY_FREQUENCY_THRESHOLD", "3"))

# How many characters to include in web context summaries
# Set in .env as: WEB_CONTEXT_SUMMARY_LENGTH=500
WEB_CONTEXT_SUMMARY_LENGTH = int(os.getenv("WEB_CONTEXT_SUMMARY_LENGTH", "300"))

# =============================================================================
# ENTITY FRESHNESS CONFIGURATION
# =============================================================================

# Days before re-searching entities by category (prevents stale information)
# Adjust these based on how quickly information changes for each category
ENTITY_FRESHNESS_DAYS = {
    "technologies": int(os.getenv("ENTITY_FRESHNESS_TECHNOLOGIES", "30")),      # AI/tech changes fast
    "organizations": int(os.getenv("ENTITY_FRESHNESS_ORGANIZATIONS", "90")),    # Companies change slowly  
    "projects": int(os.getenv("ENTITY_FRESHNESS_PROJECTS", "14")),              # Projects evolve quickly
    "people": int(os.getenv("ENTITY_FRESHNESS_PEOPLE", "180")),                 # People info stable
    "concepts": int(os.getenv("ENTITY_FRESHNESS_CONCEPTS", "60")),              # Ideas evolve moderately
    "locations": int(os.getenv("ENTITY_FRESHNESS_LOCATIONS", "365")),           # Geography very stable
    "dates": int(os.getenv("ENTITY_FRESHNESS_DATES", "365")),                   # Historical dates don't change
    "default": int(os.getenv("ENTITY_FRESHNESS_DEFAULT", "45"))                 # Fallback for other types
}

# =============================================================================
# DISPLAY LIMITS CONFIGURATION
# =============================================================================

# Control how many items are shown in various UI contexts
# Increase for more information, decrease for cleaner interface
LINKS_DISPLAY_LIMIT = int(os.getenv("LINKS_DISPLAY_LIMIT", "20"))                    # Max links to show
SEARCH_RESULTS_PER_SECTION = int(os.getenv("SEARCH_RESULTS_PER_SECTION", "10"))      # Results per category
WEAK_SEMANTIC_FALLBACK_LIMIT = int(os.getenv("WEAK_SEMANTIC_FALLBACK_LIMIT", "5"))  # Fallback search results
CONNECTION_PREVIEW_LENGTH = int(os.getenv("CONNECTION_PREVIEW_LENGTH", "100"))       # Connection text preview
TIMELINE_CONTENT_LENGTH = int(os.getenv("TIMELINE_CONTENT_LENGTH", "100"))           # Timeline item preview
ENTITY_SEARCH_LIMIT = int(os.getenv("ENTITY_SEARCH_LIMIT", "8"))                     # Entity-based search results
CHAT_CONTEXT_LIMIT = int(os.getenv("CHAT_CONTEXT_LIMIT", "30"))                      # Chat context items

# =============================================================================
# ANALYSIS CONFIGURATION
# =============================================================================

# Limits for various analysis features
# These control the depth and breadth of analysis operations
TOP_ENTITIES_PER_CATEGORY = int(os.getenv("TOP_ENTITIES_PER_CATEGORY", "5"))         # Top entities to show per type
TIMELINE_RECENT_ITEMS_LIMIT = int(os.getenv("TIMELINE_RECENT_ITEMS_LIMIT", "5"))     # Recent timeline items
REFERENCE_RELATED_MEMORIES_LIMIT = int(os.getenv("REFERENCE_RELATED_MEMORIES_LIMIT", "3"))  # Related memories per reference
PERSONAL_CONTEXT_MEMORIES_LIMIT = int(os.getenv("PERSONAL_CONTEXT_MEMORIES_LIMIT", "2"))   # Personal context memories

# =============================================================================
# AI PROCESSING CONFIGURATION
# =============================================================================

# Maximum tokens for reference explanations (controls response length)
# Set in .env as: REFERENCE_EXPLANATION_MAX_TOKENS=600
REFERENCE_EXPLANATION_MAX_TOKENS = int(os.getenv("REFERENCE_EXPLANATION_MAX_TOKENS", "400"))

# Maximum tokens for concept connection analysis (controls response completeness)
# Increase if connection analyses are getting cut off mid-sentence
# Set in .env as: CONCEPT_CONNECTION_MAX_TOKENS=2000
CONCEPT_CONNECTION_MAX_TOKENS = int(os.getenv("CONCEPT_CONNECTION_MAX_TOKENS", "2000"))

# Legacy: entity extraction now uses ENTITY_EXTRACTION_PROVIDER/ENTITY_EXTRACTION_MODEL.
# Kept only so older imports/config do not fail; active entity/connection routing does not use it.
FAST_ENTITY_MODEL = os.getenv("FAST_ENTITY_MODEL", "") or None

# =============================================================================
# TIME-BASED CONFIGURATION
# =============================================================================

# Default time ranges for various operations
DEFAULT_SUMMARY_DAYS = int(os.getenv("DEFAULT_SUMMARY_DAYS", "7"))     # Days for summary commands
DEFAULT_WEEKLY_DAYS = int(os.getenv("DEFAULT_WEEKLY_DAYS", "7"))       # Weekly analysis range

# =============================================================================
# OPERATION LIMITS
# =============================================================================

# Maximum items returned by various commands
# Increase for more comprehensive results, decrease for faster performance
DEFAULT_TODO_LIMIT = int(os.getenv("DEFAULT_TODO_LIMIT", "20"))         # Max todos to display
DEFAULT_MEMORY_LIMIT = int(os.getenv("DEFAULT_MEMORY_LIMIT", "10"))     # Max memories per query
SYNTHESIS_ITEM_LIMIT = int(os.getenv("SYNTHESIS_ITEM_LIMIT", "15"))     # Max items in synthesis

# Todo display filter setting
# Controls which todos are shown by default when running /todo command
# Options: "pending" (hide completed), "done" (show only completed), "none" (show all)
# Set in .env as: DEFAULT_TODO_FILTER=pending
DEFAULT_TODO_FILTER = os.getenv("DEFAULT_TODO_FILTER", "pending")       # Default: hide completed todos
if DEFAULT_TODO_FILTER.lower() == "none":
    DEFAULT_TODO_FILTER = None  # Convert "none" string to None to show all todos

# =============================================================================
# CONTENT PREVIEW LENGTHS
# =============================================================================

# Character limits for content previews in different contexts
# Adjust based on your preferred verbosity level
CHAT_PREVIEW_LENGTH = int(os.getenv("CHAT_PREVIEW_LENGTH", "120"))         # Chat message previews
SEARCH_PREVIEW_LENGTH = int(os.getenv("SEARCH_PREVIEW_LENGTH", "80"))       # Search result previews
PROJECT_PREVIEW_LENGTH = int(os.getenv("PROJECT_PREVIEW_LENGTH", "200"))     # Project analysis previews
GENERAL_PREVIEW_LENGTH = int(os.getenv("GENERAL_PREVIEW_LENGTH", "150"))     # General content previews
LONG_PREVIEW_LENGTH = int(os.getenv("LONG_PREVIEW_LENGTH", "300"))          # Longer content previews

# =============================================================================
# CHAT CONTEXT OPTIMIZATION
# =============================================================================

# Smart truncation for chat context injection to reduce token usage
# Content shorter than this threshold is shown in full; longer content uses ai_summary or truncation
# Set in .env as: CHAT_CONTENT_TRUNCATION_LENGTH=600
CHAT_CONTENT_TRUNCATION_LENGTH = int(os.getenv("CHAT_CONTENT_TRUNCATION_LENGTH", "500"))

# Maximum length for entity connection previews (shorter than main content to avoid duplication)
# Set in .env as: ENTITY_CONNECTION_PREVIEW_LENGTH=250
ENTITY_CONNECTION_PREVIEW_LENGTH = int(os.getenv("ENTITY_CONNECTION_PREVIEW_LENGTH", "200"))

# Whether to always use ai_summary for saved AI responses (they tend to be very long)
# Set in .env as: CHAT_USE_SUMMARY_FOR_AI_RESPONSES=false (to disable)
CHAT_USE_SUMMARY_FOR_AI_RESPONSES = os.getenv("CHAT_USE_SUMMARY_FOR_AI_RESPONSES", "true").lower() == "true"

# =============================================================================
# SEARCH RESULT LIMITS
# =============================================================================

# Number of results to retrieve for different search contexts
# Higher values provide more comprehensive results but are slower
CHAT_SEARCH_K = int(os.getenv("CHAT_SEARCH_K", "5"))           # Chat-context searches
PROJECT_SEARCH_K = int(os.getenv("PROJECT_SEARCH_K", "15"))     # Project analysis searches
GENERAL_SEARCH_K = int(os.getenv("GENERAL_SEARCH_K", "50"))     # General /search command

# Hybrid Search Configuration (Enhanced Chat)
# Set in .env as: HYBRID_SEARCH_INTERNAL_MULTIPLIER=2.5
HYBRID_SEARCH_INTERNAL_MULTIPLIER = float(os.getenv("HYBRID_SEARCH_INTERNAL_MULTIPLIER", "3.0"))  # Fetch 3x results internally for better ranking
KEYWORD_MATCH_BASELINE_SCORE = float(os.getenv("KEYWORD_MATCH_BASELINE_SCORE", "0.4"))  # Treat keyword matches as this similarity score

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

# SQLite database settings
# Set in .env as: DATABASE_PATH=custom/path/mentat.db
# Ensure database path is absolute to prevent working directory issues
_config_dir = os.path.dirname(os.path.abspath(__file__))  # core/
_project_root = os.path.dirname(os.path.dirname(_config_dir))  # project root
_db_path = os.getenv("DATABASE_PATH", "data/mentat.db")
if not os.path.isabs(_db_path):
    # Convert relative path to absolute, anchored from project root
    DATABASE_PATH = os.path.join(_project_root, _db_path)
else:
    DATABASE_PATH = _db_path
DATABASE_MAX_CONNECTIONS = int(os.getenv("DATABASE_MAX_CONNECTIONS", "5"))    # Connection pool size
DATABASE_TIMEOUT = int(os.getenv("DATABASE_TIMEOUT", "30"))                  # Query timeout (seconds)
DATABASE_CHECK_SAME_THREAD = os.getenv("DATABASE_CHECK_SAME_THREAD", "false").lower() == "true"  # SQLite threading

# =============================================================================
# MARKDOWN EXPORT CONFIGURATION
# =============================================================================

# Whether to export captured content as markdown files
# Set in .env as: MARKDOWN_EXPORT_ENABLED=false to disable
MARKDOWN_EXPORT_ENABLED = os.getenv("MARKDOWN_EXPORT_ENABLED", "true").lower() == "true"
# Directory for exported markdown files
# Set in .env as: MARKDOWN_EXPORT_PATH=exports/markdown
_markdown_export_path = os.getenv("MARKDOWN_EXPORT_PATH", "data/markdown")
if not os.path.isabs(_markdown_export_path):
    MARKDOWN_EXPORT_PATH = os.path.join(_project_root, _markdown_export_path)
else:
    MARKDOWN_EXPORT_PATH = _markdown_export_path

# =============================================================================
# LLM REQUEST CONFIGURATION
# =============================================================================

# Timeout for AI model requests (in seconds)
# Increase if you're getting timeout errors, decrease for faster failure detection
# Set in .env as: LLM_REQUEST_TIMEOUT=60
LLM_REQUEST_TIMEOUT = int(os.getenv("LLM_REQUEST_TIMEOUT", "30"))

# =============================================================================
# UI/UX CONFIGURATION
# =============================================================================

# Default theme for the interface
# Set in .env as: DEFAULT_THEME=light or DEFAULT_THEME=dark
DEFAULT_THEME = os.getenv("DEFAULT_THEME", "dark_soft")

# =============================================================================
# COLOR THEMES
# =============================================================================

# Gruvbox Soft Dark color palette (used throughout the interface)
# You can modify these hex values to customize the color scheme
GRUVBOX_COLORS = {
    "bg": "#32302f",        # Background color
    "fg": "#fbf1c7",        # Foreground (text) color
    "red": "#cc241d",       # Error/warning colors
    "green": "#98971a",     # Success colors
    "yellow": "#d79921",    # Highlight colors
    "blue": "#458588",      # Info colors
    "purple": "#b16286",    # Special elements
    "aqua": "#689d6a",      # Links/accents
    "gray": "#928374",      # Muted text
    "orange": "#d65d0e"     # Emphasis colors
}

# Rich library theme configuration (for terminal output formatting)
# These map to Rich library color names
RICH_THEME = {
    "info": "bright_blue",      # Information messages
    "warning": "bright_yellow",  # Warning messages
    "danger": "bright_red",     # Error messages
    "success": "bright_green",  # Success messages
    "neutral": "bright_white"   # Default text
}

# Strong similarity threshold for semantic matching (higher = more strict)
# Set in .env as: STRONG_SEMANTIC_SIMILARITY_THRESHOLD=0.3
STRONG_SEMANTIC_SIMILARITY_THRESHOLD = float(os.getenv("STRONG_SEMANTIC_SIMILARITY_THRESHOLD", "0.25"))

# =============================================================================
# CONCEPT EXPLORATION CONFIGURATION
# =============================================================================

# Settings for the ConceptExplorer system (/explore command)
# These control how concepts are discovered and presented
CONCEPT_EXPLORATION_DEFAULT_DEPTH = int(os.getenv("CONCEPT_EXPLORATION_DEFAULT_DEPTH", "3"))  # Exploration depth
CONCEPT_EXPLORATION_MAX_CONCEPTS = int(os.getenv("CONCEPT_EXPLORATION_MAX_CONCEPTS", "4"))    # Max concepts per level
CONCEPT_DIVERSITY_BIAS = float(os.getenv("CONCEPT_DIVERSITY_BIAS", "0.8"))                   # Diversity vs similarity (0-1)
CONCEPT_NOVELTY_THRESHOLD = float(os.getenv("CONCEPT_NOVELTY_THRESHOLD", "0.3"))              # Novelty detection threshold
CONCEPT_WEB_DISPLAY_LIMIT = int(os.getenv("CONCEPT_WEB_DISPLAY_LIMIT", "182"))               # Max concept web display
CONCEPT_EXPLORATION_BATCH_SIZE = int(os.getenv("CONCEPT_EXPLORATION_BATCH_SIZE", "4"))        # Parent concepts per LLM batch
CONCEPT_EXPLORATION_PROVIDER = os.getenv("CONCEPT_EXPLORATION_PROVIDER", "").strip().lower() or HELPERS_PROVIDER or "chat"  # chat/openrouter/local/ollama/custom
CONCEPT_EXPLORATION_MODEL = os.getenv("CONCEPT_EXPLORATION_MODEL", "").strip() or HELPERS_MODEL       # Optional model override for concept generation

# Entity extraction model routing. Defaults to HELPERS_* then chat provider/current model unless overridden.
ENTITY_EXTRACTION_PROVIDER = os.getenv("ENTITY_EXTRACTION_PROVIDER", "").strip().lower() or HELPERS_PROVIDER or "chat"
ENTITY_EXTRACTION_MODEL = os.getenv("ENTITY_EXTRACTION_MODEL", "").strip() or HELPERS_MODEL

# Concept connection analysis routing. Defaults to HELPERS_* then chat provider/current model unless overridden.
CONCEPT_CONNECTION_PROVIDER = os.getenv("CONCEPT_CONNECTION_PROVIDER", "").strip().lower() or HELPERS_PROVIDER or "chat"
CONCEPT_CONNECTION_MODEL = os.getenv("CONCEPT_CONNECTION_MODEL", "").strip() or HELPERS_MODEL

# Additional structured task routing. Defaults to HELPERS_* then chat provider/current model unless overridden.
CAPTURE_ANALYSIS_PROVIDER = os.getenv("CAPTURE_ANALYSIS_PROVIDER", "").strip().lower() or HELPERS_PROVIDER or "chat"
CAPTURE_ANALYSIS_MODEL = os.getenv("CAPTURE_ANALYSIS_MODEL", "").strip() or HELPERS_MODEL
TODO_EXTRACTION_PROVIDER = os.getenv("TODO_EXTRACTION_PROVIDER", "").strip().lower() or HELPERS_PROVIDER or "chat"
TODO_EXTRACTION_MODEL = os.getenv("TODO_EXTRACTION_MODEL", "").strip() or HELPERS_MODEL
TEMPORAL_INTENT_PROVIDER = os.getenv("TEMPORAL_INTENT_PROVIDER", "").strip().lower() or HELPERS_PROVIDER or "chat"
TEMPORAL_INTENT_MODEL = os.getenv("TEMPORAL_INTENT_MODEL", "").strip() or HELPERS_MODEL

# Concept display and visual settings
CONCEPT_TREE_MAX_WIDTH = int(os.getenv("CONCEPT_TREE_MAX_WIDTH", "60"))                              # Tree display width
CONCEPT_KNOWLEDGE_INDICATORS = os.getenv("CONCEPT_KNOWLEDGE_INDICATORS", "true").lower() == "true"   # Show knowledge indicators
CONCEPT_COLOR_CODING = os.getenv("CONCEPT_COLOR_CODING", "true").lower() == "true"                  # Enable color coding

# Concept system performance settings
CONCEPT_CACHE_SIZE = int(os.getenv("CONCEPT_CACHE_SIZE", "100"))                    # Concept cache size
CONCEPT_GENERATION_TIMEOUT = int(os.getenv("CONCEPT_GENERATION_TIMEOUT", "30"))     # Generation timeout (seconds)

# =============================================================================
# VOICE SESSION CONFIGURATION
# =============================================================================

# Voice session auto-capture behavior
# Set to True for automatic capture (original behavior, backward compatible)
# Set to False to prompt user before capturing
# Set in .env as: VOICE_AUTO_CAPTURE=true
VOICE_AUTO_CAPTURE = os.getenv("VOICE_AUTO_CAPTURE", "false").lower() == "true"

# Command type for voice conversation captures
# Set in .env as: VOICE_CAPTURE_TYPE=voice_conversation
VOICE_CAPTURE_TYPE = os.getenv("VOICE_CAPTURE_TYPE", "voice_conversation")

# Timeout for capture prompt response (seconds)
# Set in .env as: VOICE_CAPTURE_PROMPT_TIMEOUT=30
VOICE_CAPTURE_PROMPT_TIMEOUT = int(os.getenv("VOICE_CAPTURE_PROMPT_TIMEOUT", "30"))

# Enable autonomous capture suggestions during voice sessions
# When True, AI can suggest captures (user still approves)
# When False, only explicit "/capture" commands work
# Set in .env as: VOICE_SUGGEST_CAPTURES=true
VOICE_SUGGEST_CAPTURES = os.getenv("VOICE_SUGGEST_CAPTURES", "true").lower() == "true"

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_model_by_number(model_number):
    """Get model by number (1-based indexing) for CLI interface.
    
    Example: get_model_by_number(1) returns the first model in AVAILABLE_MODELS
    """
    try:
        model_num = int(model_number)
        if 1 <= model_num <= len(AVAILABLE_MODELS):
            return list(AVAILABLE_MODELS.values())[model_num - 1]
        return None
    except (ValueError, IndexError):
        return None

def get_model_by_key(model_key):
    """Get model ID from user-friendly key.
    
    Example: get_model_by_key('gpt-4o-mini') returns 'openai/gpt-4o-mini'
    """
    return AVAILABLE_MODELS.get(model_key)

RUNTIME_SETTINGS_PATH = os.getenv("RUNTIME_SETTINGS_PATH", "data/runtime_settings.json")
DEFAULT_REASONING_EFFORT = os.getenv("REASONING_DEFAULT_EFFORT", "minimal")
REASONING_EFFORT_OPTIONS = {"xhigh", "high", "medium", "low", "minimal", "off", "none"}


def _normalize_reasoning_effort(effort: Optional[str]) -> Optional[str]:
    if not effort:
        return None
    normalized = effort.strip().lower()
    if normalized == "none":
        normalized = "off"
    if normalized not in REASONING_EFFORT_OPTIONS:
        return None
    return normalized


def _load_runtime_settings() -> Dict[str, Any]:
    settings_path = Path(RUNTIME_SETTINGS_PATH)
    if not settings_path.exists():
        return {}
    try:
        with settings_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"Warning: Failed to load runtime settings from {RUNTIME_SETTINGS_PATH}: {exc}")
        return {}


def _save_runtime_settings(settings: Dict[str, Any]) -> None:
    from .private_files import ensure_private_directory, open_private_text

    settings_path = Path(RUNTIME_SETTINGS_PATH)
    ensure_private_directory(settings_path.parent)
    with open_private_text(settings_path) as file:
        json.dump(settings, file, indent=2)


def model_supports_reasoning(model_id: str) -> bool:
    return bool(MODEL_METADATA.get(model_id, {}).get("reasoning"))


def get_reasoning_effort() -> str:
    settings = _load_runtime_settings()
    raw_effort = settings.get("reasoning_effort", DEFAULT_REASONING_EFFORT)
    normalized = _normalize_reasoning_effort(str(raw_effort))
    if normalized is None:
        normalized = _normalize_reasoning_effort(DEFAULT_REASONING_EFFORT) or "minimal"
    return normalized


def set_reasoning_effort(effort: str) -> bool:
    normalized = _normalize_reasoning_effort(effort)
    if normalized is None:
        return False
    settings = _load_runtime_settings()
    settings["reasoning_effort"] = normalized
    _save_runtime_settings(settings)
    return True


def get_reasoning_extra_body(model_id: str) -> Optional[Dict[str, Any]]:
    if not model_supports_reasoning(model_id):
        return None
    effort = get_reasoning_effort()
    if effort in {"off", "none"}:
        return None
    return {"reasoning": {"effort": effort}}


def _is_selectable_model(model_id: Any) -> bool:
    if not isinstance(model_id, str) or not model_id.strip():
        return False
    return model_id in AVAILABLE_MODELS.values() or is_custom_chat_provider_configured()


def get_current_model():
    """Get the currently configured model ID.

    When a runtime chat route has been selected, trust the runtime model string
    even if it is not in the curated OpenRouter list. This supports pasted
    OpenRouter IDs and local model names.
    """
    settings = _load_runtime_settings()
    model_id = settings.get("current_model")
    if isinstance(model_id, str) and model_id.strip():
        if settings.get("chat_provider") or _is_selectable_model(model_id):
            return model_id
    provider = get_chat_provider()
    if provider == "local":
        return CHAT_MODEL or LOCAL_MODEL or OPENROUTER_MODEL
    if provider == "ollama":
        return OLLAMA_MODEL or CHAT_MODEL or OPENROUTER_MODEL
    return CHAT_MODEL or OPENROUTER_MODEL


def get_concept_exploration_model():
    """Get the model selected for ConceptExplorer generation.

    This is a model-only compatibility helper. Provider/client routing lives in
    mentat.core.llm.get_task_llm_route().
    """
    if CONCEPT_EXPLORATION_PROVIDER == "openrouter":
        return CONCEPT_EXPLORATION_MODEL or OPENROUTER_MODEL
    if CONCEPT_EXPLORATION_PROVIDER == "local":
        return CONCEPT_EXPLORATION_MODEL or LOCAL_MODEL or get_current_model()
    return CONCEPT_EXPLORATION_MODEL or get_current_model()


def set_current_model(model_id):
    """Set the current model at runtime (shared across processes).

    Legacy helper: updates only the model string. Route-aware callers should use
    set_chat_route(provider, model_id) so provider and endpoint switch together.
    """
    global OPENROUTER_MODEL
    if _is_selectable_model(model_id):
        settings = _load_runtime_settings()
        settings["current_model"] = model_id
        _save_runtime_settings(settings)
        OPENROUTER_MODEL = model_id
        return True
    return False


def set_chat_route(provider: str, model_id: str) -> bool:
    """Persist the active normal-chat provider and model.

    `provider` is one of openrouter/local/custom/ollama. The model can be any
    non-empty string because OpenRouter pasted IDs and local/Ollama aliases are
    not always present in config/models.json.
    """
    global OPENROUTER_MODEL
    normalized_provider = (provider or "").strip().lower()
    if normalized_provider not in {"openrouter", "local", "custom", "ollama"}:
        return False
    if not isinstance(model_id, str) or not model_id.strip():
        return False

    settings = _load_runtime_settings()
    settings["chat_provider"] = normalized_provider
    settings["current_model"] = model_id.strip()
    _save_runtime_settings(settings)
    if normalized_provider == "openrouter":
        OPENROUTER_MODEL = model_id.strip()
    return True


def refresh_available_models():
    """Reload the curated model list from the config file."""
    global AVAILABLE_MODELS, MODEL_METADATA, DEFAULT_OPENROUTER_MODEL
    config = _load_model_config()
    if not config:
        print(f"Warning: Model config not found at {MODEL_CONFIG_PATH}; keeping current list")
        return AVAILABLE_MODELS
    available, metadata = _build_model_registry(config)
    if not available:
        print("Warning: Model config is empty; keeping current list")
        return AVAILABLE_MODELS
    AVAILABLE_MODELS = available
    MODEL_METADATA = metadata
    DEFAULT_OPENROUTER_MODEL = config.get("default_model", DEFAULT_OPENROUTER_MODEL)
    print(f"Loaded {len(AVAILABLE_MODELS)} curated models from {MODEL_CONFIG_PATH}")
    return AVAILABLE_MODELS


def get_model_cache_info():
    """Get information about the curated model config file."""
    config_path = Path(MODEL_CONFIG_PATH)
    return {
        "source": str(config_path),
        "exists": config_path.exists(),
    }
