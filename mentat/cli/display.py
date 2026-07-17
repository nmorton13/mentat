"""
MENTAT Display and Formatting Layer
Handles all presentation logic for the CLI interface
"""

import re
import time
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple, Union, Generator

# Rich imports for console rendering
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.markdown import Markdown as RichMarkdown
from rich.align import Align
from rich.layout import Layout
from rich.live import Live
from rich import box
from rich.theme import Theme

import sys
import os

# Import centralized config for themes and colors
from mentat.core.config import RICH_THEME, GRUVBOX_COLORS, AVAILABLE_MODELS

# Import shared utilities
from mentat.core.utils import standardize_truncation

# Initialize console with centralized theme
console = Console(
    color_system="auto",
    theme=Theme(RICH_THEME)
)

# DRY Utility: Progress Spinner Context Manager
@contextmanager
def show_thinking_spinner(
    message: str = "🤔 Thinking...", 
    console: Console = console
) -> Generator[Tuple[Any, Any], None, None]:
    """
    Context manager for showing thinking spinner during operations.
    
    Displays a spinner with a custom message while long-running operations execute.
    Used across all commands to provide consistent user feedback during AI processing,
    database operations, and other potentially slow tasks.
    
    Parameters:
        message (str): The message to display alongside the spinner.
            Defaults to "🤔 Thinking...".
        console (Console): Rich console instance for output.
            Defaults to the global console instance.
    
    Yields:
        Tuple[Any, Any]: A tuple containing (progress, task) objects from Rich Progress.
            The progress object controls the spinner display, and task tracks the operation.
    
    Example:
        with show_thinking_spinner("🔍 Searching...") as (progress, task):
            # Long-running operation here
            results = perform_search()
    """
    # Use Rich Progress for thinking spinners
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task(message, total=None)
        yield progress, task

def make_urls_clickable(text):
    """Convert URLs in text to clickable Rich markup with encoding-resistant formatting"""
    if not text:
        return text
        
    # First, skip processing if text already contains Rich link markup
    if '[link=' in text and '[/link]' in text:
        return text
    
    # Find and protect markdown links first [text](url) 
    markdown_link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    markdown_links = []
    
    def protect_markdown_link(match):
        # Store the original markdown link and return a placeholder
        placeholder = f"__MARKDOWN_LINK_{len(markdown_links)}__"
        markdown_links.append(match.group(0))
        return placeholder
    
    # Replace all markdown links with placeholders
    protected_text = re.sub(markdown_link_pattern, protect_markdown_link, text)
    
    # Now apply URL formatting to the protected text
    url_pattern = r'https?://(?:[-\w.])+(?:\:[0-9]+)?(?:/(?:[\w/_.\-~!$&\'(*+,;=:@])*(?:\?(?:[\w&=%.\-~!$\'(*+,;=:@])*)?(?:\#(?:[\w.\-~!$&\'(*+,;=:@])*)?)?'
    
    def replace_url(match):
        url = match.group(0)
        return f"[bright_blue][link={url}]{url}[/link][/bright_blue]"
    
    # Apply URL formatting
    result = re.sub(url_pattern, replace_url, protected_text)
    
    # Restore markdown links
    for i, original_link in enumerate(markdown_links):
        placeholder = f"__MARKDOWN_LINK_{i}__"
        result = result.replace(placeholder, original_link)
    
    return result

def format_content_with_markdown(text: Optional[str]) -> Optional[str]:
    """
    Format content with enhanced markdown support - preserves URLs and native markdown.
    
    Processes text content to make URLs clickable while preserving markdown formatting.
    This is the primary text formatting function used across search results, memory
    displays, and other content presentation throughout the application.
    
    Parameters:
        text (Optional[str]): The text content to format. If None or empty, returns as-is.
    
    Returns:
        Optional[str]: The formatted text with clickable URLs and preserved markdown,
            ready for Rich display. Returns None if input was None.
    """
    if not text:
        return text
    
    # Make URLs clickable first
    text = make_urls_clickable(text)
    
    # Return text ready for Rich Markdown widget or manual processing
    return text

def render_markdown_content(text):
    """Render content using Rich Markdown widget for better markdown support"""
    if not text:
        return ""
    
    # Apply URL clickability first
    formatted_text = make_urls_clickable(text)
    
    try:
        # Use Rich's native Markdown widget for proper markdown rendering
        markdown = RichMarkdown(formatted_text)
        return markdown
        
    except Exception as e:
        # Fallback to original formatting if markdown rendering fails
        return formatted_text

def render_markdown_to_panel(text, title, subtitle=None, border_style="bright_blue"):
    """Render markdown content directly in a panel using Rich Markdown"""
    if not text:
        return create_standard_panel("No content", title, subtitle, border_style)
    
    try:
        # Apply URL clickability first
        formatted_text = make_urls_clickable(text)
        
        # Create Rich Markdown widget
        markdown = RichMarkdown(formatted_text)
        
        # Return panel with markdown content
        return Panel(
            markdown,
            title=title,
            subtitle=subtitle,
            border_style=border_style,
            box=box.ROUNDED,
            padding=(1, 2),
            title_align="left"
        )
        
    except Exception as e:
        # Fallback to standard panel
        return create_standard_panel(format_content_with_markdown(text), title, subtitle, border_style)

def should_use_markdown_rendering(text):
    """Determine if content should use Rich Markdown widget based on content analysis"""
    if not text:
        return False
    
    # Check for markdown patterns that benefit from Rich Markdown rendering
    markdown_indicators = [
        r'^#{1,6}\s',  # Headers
        r'```',        # Code blocks
        r'\*\*.*?\*\*', # Bold
        r'\*.*?\*',    # Italic (but not **bold**)
        r'^\s*[-*+]\s', # Lists
        r'^\s*\d+\.\s', # Numbered lists
        r'\[.*?\]\(.*?\)', # Links
    ]
    
    for pattern in markdown_indicators:
        if re.search(pattern, text, re.MULTILINE):
            return True
    
    return False

def format_metadata_display(tags, date, command_type, why_matched=None, web_context=None, source_info=None):
    """Standardized metadata formatting"""
    metadata_parts = []
    
    if tags:
        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
        metadata_parts.append(f"[bright_green]Tags:[/bright_green] {tags_str}")
    
    # Add source information
    if source_info and source_info.get('type') == 'ai_response':
        model = source_info.get('model', 'AI')
        
        # Use reverse lookup from config to get friendly display name
        try:
            from mentat.core.config import AVAILABLE_MODELS
            # Find the friendly name by looking for the model path in AVAILABLE_MODELS
            model_display = None
            for friendly_name, model_path in AVAILABLE_MODELS.items():
                if model_path == model:
                    model_display = friendly_name
                    break
            
            # Fallback to the raw model name if not found in config
            if model_display is None:
                model_display = model
        except ImportError:
            model_display = model
            
        metadata_parts.append(f"[dim blue]Source:[/dim blue] {model_display} response")
    
    # Add web enrichment indicator
    if web_context and web_context.get('web_enriched'):
        source_count = web_context.get('source_count', 0)
        top_domain = web_context.get('top_domain', '')
        if source_count > 1:
            metadata_parts.append(f"[bright_cyan]🌐 Web-enriched:[/bright_cyan] {source_count} sources")
        else:
            metadata_parts.append(f"[bright_cyan]🌐 Web-enriched[/bright_cyan]")
    
    if date:
        formatted_date = date[:10] if len(date) > 10 else date
        metadata_parts.append(f"[bright_blue]Date:[/bright_blue] {formatted_date}")
    
    if command_type:
        metadata_parts.append(f"[bright_yellow]Type:[/bright_yellow] {command_type.upper()}")
    
    if why_matched:
        metadata_parts.append(f"[dim]Why matched:[/dim] {why_matched}")
    
    return "\n   ".join(metadata_parts)

def format_numbered_list_item(line):
    """Format numbered list items (1-9) with DRY approach."""
    for i in range(1, 10):  # Support numbers 1-9
        if line.startswith(f'{i}. '):
            item = line[len(f'{i}. '):].strip()
            return f"{i}. {item}"
    return None  # Not a numbered list item

def create_standard_panel(
    content: str, 
    title: str, 
    subtitle: Optional[str] = None, 
    border_style: str = "bright_blue", 
    box_style: Any = box.ROUNDED
) -> Panel:
    """
    Create a standardized panel with consistent styling across the application.
    
    Generates Rich Panel objects with unified styling parameters for consistent
    visual appearance throughout MENTAT. Used by all command outputs to ensure
    a cohesive user interface experience.
    
    Parameters:
        content (str): The text content to display inside the panel
        title (str): The panel title displayed at the top border
        subtitle (Optional[str]): Optional subtitle text. Defaults to None.
        border_style (str): Rich color style for the panel border.
            Defaults to "bright_blue".
        box_style (Any): Rich box style for the panel border appearance.
            Defaults to box.ROUNDED.
    
    Returns:
        Panel: A Rich Panel object ready for console display with standardized
            styling and consistent padding/alignment settings.
    """
    return Panel(
        content,
        title=title,
        subtitle=subtitle,
        border_style=border_style,
        box=box_style,
        padding=(1, 2),
        title_align="left"
    )

def print_banner():
    """Display beautiful MENTAT banner"""
    banner_text = """
[bold cyan]███╗   ███╗███████╗███╗   ██╗████████╗ █████╗ ████████╗[/bold cyan]
[bold cyan]████╗ ████║██╔════╝████╗  ██║╚══██╔══╝██╔══██╗╚══██╔══╝[/bold cyan]
[bold cyan]██╔████╔██║█████╗  ██╔██╗ ██║   ██║   ███████║   ██║   [/bold cyan]
[bold cyan]██║╚██╔╝██║██╔══╝  ██║╚██╗██║   ██║   ██╔══██║   ██║   [/bold cyan]
[bold cyan]██║ ╚═╝ ██║███████╗██║ ╚████║   ██║   ██║  ██║   ██║   [/bold cyan]
[bold cyan]╚═╝     ╚═╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   [/bold cyan]

[bold yellow]Opinionated memory for thoughts that keep tugging[/bold yellow]
[dim]Selective capture, search, reflection, and connection[/dim]
"""
    
    panel = Panel(
        Align.center(banner_text),
        border_style="cyan",
        box=box.DOUBLE,
        padding=(1, 2)
    )
    console.print(panel)
    console.print()

def print_colored(text, color="white", style=""):
    """Enhanced colored text printing with Rich"""
    color_map = {
        "red": "bright_red",
        "green": "bright_green", 
        "yellow": "bright_yellow",
        "blue": "bright_blue",
        "purple": "bright_magenta",
        "cyan": "bright_cyan",
        "white": "bright_white",
        "orange": "bright_red"
    }
    
    rich_color = color_map.get(color, "bright_white")
    console.print(text, style=f"{rich_color} {style}")

def print_ai_reply(reply, model_name=None):
    """Display AI reply in a beautiful chat bubble"""
    # Add model info if available
    header = "🤖 AI Assistant"
    if model_name:
        header += f" ({model_name})"
    
    # Try to detect and format code blocks
    if "```" in reply:
        # Simple markdown rendering for code blocks
        formatted_reply = reply.replace("```", "")
    else:
        formatted_reply = reply
    
    panel = Panel(
        formatted_reply,
        title=header,
        subtitle="MENTAT",
        border_style="bright_cyan",
        box=box.ROUNDED,
        padding=(1, 2),
        title_align="left"
    )
    console.print(panel)
    console.print()

def print_tool_reply(content, title, subtitle=None, border_style="bright_blue"):
    """Display tool response in a beautiful panel similar to AI replies"""
    panel = create_standard_panel(
        content,
        title,
        subtitle or "MENTAT Tool",
        border_style
    )
    console.print(panel)
    console.print()

def print_enhanced_chat_reply(result, model_name=None, global_enhanced_chat=None, last_displayed_items=None):
    """Display enhanced chat response with proper markdown rendering"""
    
    # Handle viewable items for /view integration
    if result.get('viewable_items') and last_displayed_items is not None:
        last_displayed_items.clear()
        last_displayed_items.extend(result['viewable_items'])
    
    # Create header with model info
    header = "🤖 AI Assistant"
    if model_name:
        header += f" ({model_name})"
    
    # Check if we should use enhanced markdown rendering for the AI response
    if should_use_markdown_rendering(result['response']):
        # Render metadata panel first
        metadata_parts = []
        if result['sources']:
            source_parts = []
            for source in result['sources']:
                source_parts.append(f"{source['description']} ({source['count']})")
            sources_line = f"[dim]📊 Sources: {' • '.join(source_parts)}[/dim]"
            metadata_parts.append(sources_line)
            
            if result['patterns']:
                patterns_line = f"[dim]🧩 Your patterns: {' • '.join(result['patterns'][:2])}[/dim]"
                metadata_parts.append(patterns_line)
        
        if metadata_parts:
            metadata_panel = Panel(
                "\n".join(metadata_parts),
                title=header,
                subtitle="MENTAT",
                border_style="bright_cyan",
                box=box.ROUNDED,
                padding=(0, 2),
                title_align="left"
            )
            console.print(metadata_panel)
        
        # Render AI response with enhanced markdown
        ai_response_panel = render_markdown_to_panel(
            result['response'],
            "AI Response" if metadata_parts else header,
            subtitle="MENTAT" if not metadata_parts else None,
            border_style="bright_cyan"
        )
        console.print(ai_response_panel)
        
        # Render follow-up guidance panel
        ref_count = len(global_enhanced_chat.session_references) if global_enhanced_chat else 0
        
        guidance_parts = []
        if ref_count > 0:
            guidance_parts.extend(_format_exploration_reference_guidance(global_enhanced_chat))
        elif result['suggestions']:
            guidance_parts.append("[dim]💡 Explore further:[/dim]")
            for suggestion in result['suggestions']:
                guidance_parts.append(f"   [dim]•[/dim] [cyan]{suggestion}[/cyan]")
        
        if guidance_parts:
            guidance_panel = Panel(
                "\n".join(guidance_parts),
                border_style="bright_cyan",
                box=box.ROUNDED,
                padding=(0, 2)
            )
            console.print(guidance_panel)
        
        # Show contextual commands
        has_concepts = False  # Only show /explain when actual concept references are available
        show_contextual_commands(last_displayed_items, True, has_concepts)
    
    else:
        # Use unified panel for simple responses
        content_parts = []
        
        # Add source attribution at the top if available
        if result['sources']:
            source_parts = []
            for source in result['sources']:
                source_parts.append(f"{source['description']} ({source['count']})")
            sources_line = f"[dim]📊 Sources: {' • '.join(source_parts)}[/dim]"
            content_parts.append(sources_line)
            
            # Add patterns if found
            if result['patterns']:
                patterns_line = f"[dim]🧩 Your patterns: {' • '.join(result['patterns'][:2])}[/dim]"
                content_parts.append(patterns_line)
            
            content_parts.append("")  # Add spacing
        
        # Add the main AI response
        main_response = format_content_with_markdown(result['response'])
        content_parts.append(main_response)
        
        # Add follow-up guidance
        ref_count = len(global_enhanced_chat.session_references) if global_enhanced_chat else 0
        
        if ref_count > 0:
            content_parts.append("")  # Add spacing
            content_parts.extend(_format_exploration_reference_guidance(global_enhanced_chat))
        elif result['suggestions']:
            content_parts.append("")  # Add spacing  
            content_parts.append("[dim]💡 Explore further:[/dim]")
            for suggestion in result['suggestions']:
                content_parts.append(f"   [dim]•[/dim] [cyan]{suggestion}[/cyan]")
        
        # Display in unified panel
        formatted_content = "\n".join(content_parts)
        panel = Panel(
            formatted_content,
            title=header,
            subtitle="MENTAT",
            border_style="bright_cyan",
            box=box.ROUNDED,
            padding=(1, 2),
            title_align="left"
        )
        console.print(panel)
        
        # Show contextual commands
        has_concepts = False  # Only show /explain when actual concept references are available
        show_contextual_commands(last_displayed_items, True, has_concepts)

def _format_exploration_reference_guidance(global_enhanced_chat) -> List[str]:
    """Format post-chat concept references without relying on inline markers."""
    guidance_parts = ["[dim]🔗 Explore next:[/dim]"]

    references = getattr(global_enhanced_chat, "session_references", {}) or {}
    for ref_id in sorted(references, key=lambda value: int(value) if str(value).isdigit() else str(value)):
        topic = references[ref_id].get("topic", "").strip()
        if not topic:
            continue
        guidance_parts.append(
            f"   [cyan]{ref_id}. {topic}[/cyan] "
            f"[dim]— /view {ref_id} • /explore {ref_id} • /synthesize {topic}[/dim]"
        )

    return guidance_parts

def display_llm_routes_table(current_model, chat_client=None):
    """Display resolved provider/model routes for key LLM-backed features."""
    from mentat.core.llm import get_llm_route_display_rows

    routes_table = Table(title=" Active LLM Routes", border_style="magenta", box=box.ROUNDED)
    routes_table.add_column("Feature", style="bright_cyan", width=20)
    routes_table.add_column("Provider", style="bright_yellow", width=28)
    routes_table.add_column("Model", style="bright_white", width=38)
    routes_table.add_column("Source", style="dim", width=18)
    routes_table.add_column("Endpoint", style="dim", width=28)
    routes_table.add_column("Status", style="bright_green", width=18)

    for row in get_llm_route_display_rows(chat_client=chat_client, current_model=current_model):
        routes_table.add_row(
            row["feature"],
            row["provider"],
            row["model"],
            row["source"],
            row["base_url"],
            row["status"],
        )

    console.print(routes_table)
    console.print(
        "[dim]/model changes the active chat route: saved models route through OpenRouter; "
        "/model local uses OpenAI-compatible local endpoints; /model ollama <model> uses native Ollama. "
        "Explicit feature routes still come from .env.[/dim]"
    )


def display_models_table(current_model):
    """Display models in a numbered table"""
    model_table = Table(title=" Available Models", border_style="cyan", box=box.ROUNDED)
    model_table.add_column("#", style="bright_yellow", width=3)
    model_table.add_column("Key", style="bright_blue", width=20)
    model_table.add_column("Model", style="bright_white", width=50)
    model_table.add_column("Status", style="bright_green", width=12)
    
    for i, (k, v) in enumerate(AVAILABLE_MODELS.items(), 1):
        status = "✓ Current" if v == current_model else ""
        model_table.add_row(str(i), k, v, status)
    
    console.print(model_table)
    console.print("[dim]Use /model <number|name> for OpenRouter, /model local, /model ollama <model>, or /model openrouter <model-id>[/dim]")
    console.print("[dim]Saved models route through OpenRouter; /model local uses OpenAI-compatible local settings; /model ollama uses native /api/chat[/dim]")
def display_search_results(results):
    """Display search results in a beautiful table"""
    from mentat.core.config import SEARCH_PREVIEW_LENGTH
    
    if not results:
        console.print("[yellow]No results found[/yellow]")
        return
    
    table = Table(
        title="🔍 Search Results",
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
        box=box.ROUNDED
    )
    
    table.add_column("#", style="dim", width=3)
    table.add_column("Type", style="bright_yellow", width=10)
    table.add_column("Content", style="bright_white", width=60)
    table.add_column("Tags", style="bright_green", width=20)
    table.add_column("Date", style="dim", width=12)
    
    for i, item in enumerate(results[:10], 1):
        content_preview = standardize_truncation(item['content'], SEARCH_PREVIEW_LENGTH)
        tags_str = ", ".join(item.get('tags', [])) if item.get('tags') else ""
        date_str = item.get('timestamp', "")[:10] if item.get('timestamp') else ""
        
        table.add_row(
            str(i),
            item['command_type'].upper(),
            content_preview,
            tags_str,
            date_str
        )
    
    console.print(table)
    console.print("[dim]💡 Use /view <number> to see full content[/dim]")

def show_loading_spinner(message="Processing..."):
    """Show a loading spinner with Rich"""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task(message, total=None)
        return progress, task


def show_contextual_commands(last_displayed_items=None, has_ai_response=False, has_concept_references=False):
    """Show available contextual commands based on current state"""
    commands = []
    
    # Check if we have numbered results
    if last_displayed_items:
        commands.append("Use [cyan]/view <number>[/cyan] to see full content")
        commands.append("Use [cyan]/delete <number>[/cyan] to remove item")
    
    # Check if we have concept references available
    if has_concept_references:
        commands.append("Use [cyan]/explain <number>[/cyan] to get detailed concept explanation")
    
    # Check if we have saveable AI response
    if has_ai_response:
        commands.append("Use [cyan]/save[/cyan] to capture this AI response")
    
    if commands:
        console.print("\n" + " • ".join(commands))

def get_status_indicator(status):
    """Get visual indicator for todo status"""
    indicators = {
        'pending': '□',
        'done': '✓'
    }
    return indicators.get(status, '□')

def format_todo_with_status(todo, display_number):
    """Format a single todo item with status indicators and styling"""
    status = todo.get('status', 'pending')
    indicator = get_status_indicator(status)
    action = todo['action']
    
    # Apply strikethrough for completed todos
    if status == 'done':
        action_display = f"[strike]{action}[/strike]"
    else:
        action_display = action
    
    # Color coding for different statuses
    if status == 'done':
        indicator_color = 'bright_green'
    else:  # pending
        indicator_color = 'bright_white'
    
    # Format the line
    formatted_line = f"[{indicator_color}]{indicator}[/{indicator_color}] {action_display}"
    
    # Add status label for done items
    if status == 'done':
        formatted_line += f" [dim](done)[/dim]"
    
    return f"{display_number}. {formatted_line}"

def format_todo_metadata(todo):
    """Format todo metadata (priority, timestamp, etc.)"""
    metadata_parts = []
    
    # Priority
    if todo.get('priority') and todo['priority'] != 'medium':
        priority_color = 'bright_red' if todo['priority'] == 'high' else 'bright_blue'
        metadata_parts.append(f"[{priority_color}]Priority: {todo['priority']}[/{priority_color}]")
    
    # Project
    if todo.get('project'):
        metadata_parts.append(f"[bright_magenta]Project: {todo['project']}[/bright_magenta]")
    
    # Source timestamp  
    if todo.get('timestamp'):
        date_str = todo['timestamp'][:10]
        metadata_parts.append(f"[dim]Added: {date_str}[/dim]")
    
    # Marked date
    if todo.get('marked_date'):
        marked_date = todo['marked_date'][:10]
        metadata_parts.append(f"[dim]Marked: {marked_date}[/dim]")
    
    if metadata_parts:
        return "   " + " • ".join(metadata_parts)
    return ""

# Concept Exploration Display Functions

def render_concept_exploration_section(concepts: List[Dict], user_context: Optional[Dict] = None) -> str:
    """
    Render a concept exploration section for display in MENTAT interface
    
    Args:
        concepts: List of concept dictionaries
        user_context: Optional user context for knowledge indicators
        
    Returns:
        Formatted string for Rich display
    """
    if not concepts:
        return ""
    
    lines = ["🌳 **Related Concepts to Explore:**"]
    
    for concept in concepts[:4]:  # Limit for clean display
        number = concept.get('number', 0)
        name = concept.get('name', 'Unknown')
        description = concept.get('description', '')
        domain = concept.get('domain', 'general')
        
        # Format concept with domain indicator
        domain_emoji = _get_concept_domain_emoji(domain)
        concept_line = f"    ├── **{name}** [{number}] {domain_emoji}"
        
        lines.append(concept_line)
        
        # Add description if available
        if description:
            truncated_desc = standardize_truncation(description, 60)
            lines.append(f"        [dim]{truncated_desc}[/dim]")
    
    lines.append("")
    lines.append("💡 Use `/explore <number>` to explore specific concepts")
    
    return "\n".join(lines)

def format_concept_tree_branch(concept: Dict, depth: int, knowledge_level: int = 0) -> str:
    """
    Format a concept tree branch with proper indentation and styling
    
    Args:
        concept: Concept dictionary with name, description, domain
        depth: Tree depth level for indentation
        knowledge_level: User's knowledge level (0-3)
        
    Returns:
        Formatted tree branch string
    """
    indent = "  " * depth
    branch_symbol = "├──" if depth > 0 else "──"
    
    name = concept.get('name', 'Unknown')
    description = concept.get('description', '')
    domain = concept.get('domain', 'general')
    
    # Add domain emoji
    domain_emoji = _get_concept_domain_emoji(domain)
    
    # Add knowledge indicator if enabled
    knowledge_indicator = _get_concept_knowledge_indicator(knowledge_level)
    
    concept_line = f"{indent}{branch_symbol} **{name}** {domain_emoji}"
    if knowledge_indicator:
        concept_line += f" {knowledge_indicator}"
    
    # Add description on next line if available
    if description:
        truncated_desc = standardize_truncation(description, 50)
        desc_indent = "  " * (depth + 1)
        concept_line += f"\n{desc_indent}[dim]{truncated_desc}[/dim]"
    
    return concept_line

def create_concept_web_panel(concept_web: Dict, title: str, depth_level: int = 1) -> Panel:
    """
    Create a Rich panel for concept web display
    
    Args:
        concept_web: Concept web dictionary
        title: Panel title
        depth_level: Display depth (1=mini, 2=expanded, 3=full)
        
    Returns:
        Rich Panel object
    """
    if not concept_web or not concept_web.get('concepts'):
        empty_content = "[dim]No concept web available[/dim]"
        return create_standard_panel(empty_content, title, None, "bright_blue")
    
    # Format content based on depth level
    if depth_level == 1:
        # Mini display for /view enhancement
        content = render_concept_exploration_section(concept_web['concepts'])
        border_color = "bright_green"
    else:
        # Expanded or full display
        content = _render_expanded_concept_web(concept_web)
        border_color = "bright_blue" if depth_level == 2 else "bright_magenta"
    
    return create_standard_panel(content, title, None, border_color)

def _render_expanded_concept_web(concept_web: Dict) -> str:
    """Render expanded concept web display"""
    root = concept_web.get('root', 'Unknown')
    concepts = concept_web.get('concepts', [])
    
    if not concepts:
        return f"[dim]No related concepts found for '{root}'[/dim]"
    
    lines = [f"**Root Concept:** {root}", ""]
    
    # Group by domain for better organization
    domain_groups = {}
    for concept in concepts:
        domain = concept.get('domain', 'general')
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(concept)
    
    # Display each domain group
    for domain, domain_concepts in domain_groups.items():
        if len(domain_groups) > 1:  # Show domain headers if multiple domains
            domain_emoji = _get_concept_domain_emoji(domain)
            lines.append(f"**{domain.title()}** {domain_emoji}")
        
        for concept in domain_concepts:
            number = concept.get('number', 0)
            name = concept.get('name', 'Unknown')
            description = concept.get('description', '')
            connection = concept.get('connection', '')
            
            # Main concept line
            lines.append(f"  [{number}] **{name}**")
            
            # Description
            if description:
                truncated_desc = standardize_truncation(description, 80)
                lines.append(f"      [dim]{truncated_desc}[/dim]")
            
            # Connection explanation
            if connection:
                truncated_conn = standardize_truncation(connection, 60)
                lines.append(f"      [italic]→ {truncated_conn}[/italic]")
            
            lines.append("")  # Spacing
    
    # Add interaction hints
    lines.extend([
        "💡 **Exploration Options:**",
        "   • `/explore <number>` - Deep dive into specific concept",
        "   • `/explore <concept>` - Full concept exploration",
        "   • `/save` - Capture interesting insights"
    ])
    
    return "\n".join(lines)

def _get_concept_domain_emoji(domain: str) -> str:
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

def _get_concept_knowledge_indicator(familiarity_level: int) -> str:
    """Get indicator for user's knowledge level"""
    indicators = {
        0: "🆕",  # Unknown
        1: "📚",  # Basic  
        2: "🎯",  # Intermediate
        3: "⭐"   # Expert
    }
    return indicators.get(familiarity_level, "")

def format_concept_reference_display(concept: str, reference_number: int, 
                                   description: str = "", domain: str = "general") -> str:
    """
    Format a concept for reference display in chat responses
    
    Args:
        concept: Concept name
        reference_number: Reference number for /view command
        description: Optional concept description
        domain: Concept domain
        
    Returns:
        Formatted concept reference string
    """
    domain_emoji = _get_concept_domain_emoji(domain)
    
    formatted = f"**{concept}**[{reference_number}] {domain_emoji}"
    
    if description:
        # Add brief description in hover-style format
        truncated_desc = standardize_truncation(description, 40)
        formatted += f" [dim]({truncated_desc})[/dim]"
    
    return formatted
