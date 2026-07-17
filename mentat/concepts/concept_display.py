"""
MENTAT ConceptExplorer Display Enhancement
Rich terminal display for concept webs and exploration UI
"""

from typing import List, Dict, Optional, Any
from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.align import Align

from mentat.core.config import (
    CONCEPT_TREE_MAX_WIDTH, CONCEPT_KNOWLEDGE_INDICATORS, CONCEPT_COLOR_CODING,
    GRUVBOX_COLORS
)
from mentat.cli.display import create_standard_panel, console


def render_concept_mini_tree(concepts: List[Dict], max_depth: int = 2) -> str:
    """
    Render a mini concept tree for display in /view command enhancement
    
    Args:
        concepts: List of concept dictionaries with name, description, domain, etc.
        max_depth: Maximum depth to display
        
    Returns:
        Formatted string for Rich display
    """
    if not concepts:
        return ""
    
    lines = ["🌳 **Related Concepts to Explore:**"]
    
    for concept in concepts[:4]:  # Limit for mini display
        number = concept.get('number', 0)
        name = concept.get('name', 'Unknown')
        description = concept.get('description', '')
        domain = concept.get('domain', 'general')
        novelty = concept.get('novelty', 0.0)
        
        # Format concept line with indicators
        domain_emoji = _get_domain_emoji(domain)
        novelty_indicator = _get_novelty_indicator(novelty) if CONCEPT_KNOWLEDGE_INDICATORS else ""
        
        # Clean display without descriptions
        
        concept_line = f"    ├── **{name}** [{number}] {domain_emoji}"
        if novelty_indicator:
            concept_line += f" {novelty_indicator}"
        
        lines.append(concept_line)
    
    lines.append("")
    lines.append("💡 Use `/explore <number>` to explore specific concepts")
    
    return "\n".join(lines)


def format_concept_with_knowledge_indicator(concept: Dict, user_knowledge: int) -> str:
    """
    Format a concept with knowledge level indicators
    
    Args:
        concept: Concept dictionary
        user_knowledge: User familiarity level (0-3)
        
    Returns:
        Formatted concept string with indicators
    """
    name = concept.get('name', 'Unknown')
    domain = concept.get('domain', 'general')
    
    # Knowledge level indicators
    knowledge_indicators = {
        0: "🆕",  # Unknown/New
        1: "📚",  # Basic knowledge
        2: "🎯",  # Intermediate 
        3: "⭐"   # Expert
    }
    
    # Domain coloring
    domain_colors = {
        'tech': 'bright_blue',
        'philosophy': 'bright_magenta', 
        'culture': 'bright_yellow',
        'science': 'bright_green',
        'business': 'bright_cyan',
        'creative': 'bright_red',
        'general': 'white'
    }
    
    domain_emoji = _get_domain_emoji(domain)
    knowledge_icon = knowledge_indicators.get(user_knowledge, "📝") if CONCEPT_KNOWLEDGE_INDICATORS else ""
    
    if CONCEPT_COLOR_CODING:
        color = domain_colors.get(domain, 'white')
        formatted = f"[{color}]{name}[/{color}] {domain_emoji}"
    else:
        formatted = f"**{name}** {domain_emoji}"
    
    if knowledge_icon:
        formatted += f" {knowledge_icon}"
    
    return formatted


def create_exploration_panel(concept_web: Dict, title: str) -> Panel:
    """
    Create a Rich panel for concept exploration display
    
    Args:
        concept_web: Concept web dictionary
        title: Panel title
        
    Returns:
        Rich Panel object
    """
    if not concept_web or not concept_web.get('concepts'):
        return create_standard_panel(
            "[dim]No concepts to explore at this time.[/dim]",
            title,
            None,
            "bright_blue"
        )
    
    content = display_progressive_concepts(concept_web)
    
    return create_standard_panel(
        content,
        title,
        None,
        "bright_green"
    )


def display_progressive_concepts(concept_hierarchy: Dict) -> str:
    """
    Display concepts with progressive disclosure
    
    Args:
        concept_hierarchy: Hierarchical concept data
        
    Returns:
        Formatted string for display
    """
    root = concept_hierarchy.get('root', 'Unknown')
    concepts = concept_hierarchy.get('concepts', [])
    depth = concept_hierarchy.get('depth', 1)
    
    if not concepts:
        return f"[dim]No related concepts found for '{root}'[/dim]"
    
    lines = []
    
    # Show root concept
    lines.append(f"**Root:** {root}")
    lines.append("")
    
    # Group concepts by domain for better organization
    domain_groups = {}
    for concept in concepts:
        domain = concept.get('domain', 'general')
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(concept)
    
    # Display by domain
    for domain, domain_concepts in domain_groups.items():
        if len(domain_groups) > 1:  # Only show domain headers if multiple domains
            domain_emoji = _get_domain_emoji(domain)
            lines.append(f"**{domain.title()}** {domain_emoji}")
        
        for concept in domain_concepts:
            number = concept.get('number', 0)
            name = concept.get('name', 'Unknown')
            description = concept.get('description', '')
            connection = concept.get('connection', '')
            confidence = concept.get('confidence', 1.0)
            
            # Format main concept line
            concept_line = f"  [{number}] **{name}**"
            
            # Add confidence indicator if low
            if confidence < 0.7:
                concept_line += " [dim](uncertain)[/dim]"
            
            lines.append(concept_line)
            
            lines.append("")  # Spacing between concepts
    
    # Add exploration hints
    lines.append("💡 **Next Steps:**")
    lines.append("   • Use `/explore <number>` to explore specific concepts")
    lines.append("   • Use `/explore <concept>` for full concept exploration")
    lines.append("   • Use `/save` to capture interesting concepts as memories")
    
    return "\n".join(lines)


def format_concept_tree_branch(concept: Dict, depth: int, knowledge_level: int) -> str:
    """
    Format a single concept tree branch with proper indentation and styling
    
    Args:
        concept: Concept dictionary
        depth: Tree depth level
        knowledge_level: User's knowledge level of concept
        
    Returns:
        Formatted tree branch string
    """
    indent = "  " * depth
    branch_symbol = "├──" if depth > 0 else "──"
    
    formatted_concept = format_concept_with_knowledge_indicator(concept, knowledge_level)
    
    # Clean tree branch display without descriptions
    
    branch_line = f"{indent}{branch_symbol} {formatted_concept}"
    
    return branch_line


def create_concept_web_panel(concept_web: Dict, title: str, depth_level: int = 1) -> Panel:
    """
    Create a concept web panel with appropriate styling based on depth level
    
    Args:
        concept_web: Concept web data
        title: Panel title
        depth_level: Display depth (1=mini, 2=expanded, 3=full)
        
    Returns:
        Rich Panel object
    """
    if not concept_web or not concept_web.get('concepts'):
        empty_content = "[dim]No concept web available[/dim]"
        return create_standard_panel(empty_content, title, None, "bright_blue")
    
    if depth_level == 1:
        # Mini display for /view enhancement
        content = render_concept_mini_tree(concept_web['concepts'], max_depth=2)
        border_color = "bright_green"
    elif depth_level == 2:
        # Expanded display
        content = display_progressive_concepts(concept_web)
        border_color = "bright_blue"
    else:
        # Full exploration display
        content = _render_full_concept_web(concept_web)
        border_color = "bright_magenta"
    
    return create_standard_panel(content, title, None, border_color)


def render_interactive_concept_tree(concept_web: Dict, current_focus: str = None) -> str:
    """
    Render an interactive concept tree for exploration sessions
    
    Args:
        concept_web: Full concept web data
        current_focus: Currently focused concept (highlighted)
        
    Returns:
        Formatted interactive tree string
    """
    if not concept_web or not concept_web.get('concepts'):
        return "[dim]No concepts to display[/dim]"
    
    root = concept_web.get('root', 'Unknown')
    concepts = concept_web.get('concepts', [])
    
    lines = []
    lines.append(f"🌳 **Concept Exploration Tree**")
    lines.append(f"**Root:** {root}")
    lines.append("")
    
    # Show concepts in tree format
    for i, concept in enumerate(concepts, 1):
        name = concept.get('name', 'Unknown')
        domain = concept.get('domain', 'general')
        description = concept.get('description', '')
        
        # Highlight current focus
        if current_focus and name.lower() == current_focus.lower():
            concept_line = f"  [{i}] **[bright_yellow]{name}[/bright_yellow]** ← [dim]Current focus[/dim]"
        else:
            domain_emoji = _get_domain_emoji(domain)
            concept_line = f"  [{i}] **{name}** {domain_emoji}"
        
        lines.append(concept_line)
        
        lines.append("")
    
    # Add interaction hints
    lines.append("🎯 **Commands:**")
    lines.append("   • Type number to explore concept")
    lines.append("   • Type 'back' to return to previous level")
    lines.append("   • Type 'save <number>' to capture concept")
    lines.append("   • Type 'quit' to exit exploration")
    
    return "\n".join(lines)


def _render_full_concept_web(concept_web: Dict) -> str:
    """Render full concept web for complete exploration"""
    return display_progressive_concepts(concept_web)


def _get_domain_emoji(domain: str) -> str:
    """Get emoji indicator for concept domain"""
    domain_emojis = {
        'tech': '💻',
        'philosophy': '🤔', 
        'culture': '🎭',
        'science': '🔬',
        'business': '💼',
        'creative': '🎨',
        'general': '📝'
    }
    return domain_emojis.get(domain, '📝')


def _get_novelty_indicator(novelty_score: float) -> str:
    """Get indicator for concept novelty level"""
    if novelty_score > 0.7:
        return "🆕"  # New to user
    elif novelty_score > 0.4:
        return "🔍"  # Worth exploring  
    else:
        return ""   # Familiar, no indicator needed


def _get_knowledge_indicator(familiarity_level: int) -> str:
    """Get indicator for user's knowledge level"""
    indicators = {
        0: "🆕",  # Unknown
        1: "📚",  # Basic
        2: "🎯",  # Intermediate
        3: "⭐"   # Expert
    }
    return indicators.get(familiarity_level, "📝")


# Utility functions for creating Rich components

def create_concept_table(concepts: List[Dict], title: str = "Concepts") -> Table:
    """
    Create a Rich table for concept display
    
    Args:
        concepts: List of concept dictionaries
        title: Table title
        
    Returns:
        Rich Table object
    """
    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=3)
    table.add_column("Concept", style="bold")
    table.add_column("Domain", width=10)
    table.add_column("Description", style="dim")
    
    for i, concept in enumerate(concepts, 1):
        name = concept.get('name', 'Unknown')
        domain = concept.get('domain', 'general')
        description = concept.get('description', '')
        
        # Truncate description for table display
        if description and len(description) > 40:
            description = description[:37] + "..."
        
        domain_emoji = _get_domain_emoji(domain)
        domain_display = f"{domain} {domain_emoji}"
        
        table.add_row(str(i), name, domain_display, description)
    
    return table


def create_concept_columns(concepts: List[Dict], columns: int = 2) -> Columns:
    """
    Create Rich columns layout for concept display
    
    Args:
        concepts: List of concept dictionaries
        columns: Number of columns
        
    Returns:
        Rich Columns object
    """
    concept_panels = []
    
    for concept in concepts:
        name = concept.get('name', 'Unknown')
        description = concept.get('description', '')
        domain = concept.get('domain', 'general')
        
        domain_emoji = _get_domain_emoji(domain)
        
        panel_content = f"**{name}** {domain_emoji}"
        if description:
            truncated = description[:60] + "..." if len(description) > 60 else description
            panel_content += f"\n[dim]{truncated}[/dim]"
        
        panel = Panel(
            panel_content,
            title=f"[{len(concept_panels) + 1}]",
            title_align="left",
            border_style="bright_blue",
            width=30
        )
        concept_panels.append(panel)
    
    return Columns(concept_panels, equal=True, expand=True)