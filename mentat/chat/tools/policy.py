"""Central tool tier policy.

Single source of truth for assigning tools to tiers.

Tier semantics:
- tier1: default everyday tools
- tier2: power/ops tools (explicit intent)
"""

from typing import Dict, Literal

ToolTier = Literal["tier1", "tier2"]

# NOTE: Keep this as the single place for tier assignments.
TOOL_TIERS: Dict[str, ToolTier] = {
    # Tier 1: everyday assistant
    "find_related_thoughts": "tier1",
    "check_forgotten_ideas": "tier1",
    "capture_thought": "tier1",
    "suggest_capture": "tier1",
    "get_recent_activity": "tier1",
}

_TIER_ORDER = {"tier1": 1, "tier2": 2}


def get_tool_tier(tool_name: str) -> ToolTier:
    """Get tier for a tool name. Unassigned tools default to tier1."""
    return TOOL_TIERS.get(tool_name, "tier1")


def tier_includes(selected_tier: str, tool_tier: str) -> bool:
    """Return True if selected tier should include the tool tier (cumulative)."""
    selected_rank = _TIER_ORDER.get(selected_tier, 1)
    tool_rank = _TIER_ORDER.get(tool_tier, 1)
    return tool_rank <= selected_rank
