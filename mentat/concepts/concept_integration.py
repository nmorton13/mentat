"""
MENTAT ConceptExplorer Integration Layer
Bridge between MENTAT's existing systems and ConceptExplorer functionality
"""

import json
import re
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime

from .concept_explorer import MentatConceptExplorer, ConceptWeb, ConceptNode
from mentat.core.database import MemoryDatabase
from mentat.core.config import (
    CONCEPT_EXPLORATION_DEFAULT_DEPTH, CONCEPT_EXPLORATION_MAX_CONCEPTS,
    CONCEPT_NOVELTY_THRESHOLD, REFERENCE_RELATED_MEMORIES_LIMIT
)
from mentat.core.llm import complete


class ConceptIntegrationManager:
    """
    Manages the integration between MENTAT's reference system and ConceptExplorer
    Handles concept generation, user knowledge analysis, and display formatting
    """
    
    def __init__(self, db: MemoryDatabase, openrouter_client: Any):
        """
        Initialize the integration manager
        
        Args:
            db: MENTAT database instance
            openrouter_client: OpenRouter client for LLM interactions
        """
        self.db = db
        self.client = openrouter_client
        self.explorer = MentatConceptExplorer(openrouter_client, db)
        self.reference_concept_cache = {}  # Cache concept mini-webs for references

    def _concept_hint(self, interactive: bool, depth_label: str = "deeper") -> str:
        if interactive:
            return f"💡 Use `/explore <number>` for {depth_label} exploration • `/explain <number>` for detailed explanations"
        return '💡 Use `mentat explore "<concept>"` for deeper exploration • `mentat explain "<concept>"` for detailed explanations'
    
    def enhance_reference_with_concepts(self, reference_item: Dict, user_context: List[Dict],
                                      user_id: str) -> Dict:
        """
        Enhance a reference explanation with related concept exploration
        
        Args:
            reference_item: Dictionary with 'topic', 'context', 'personal_context'
            user_context: User's related memories for knowledge analysis
            user_id: User identifier for memory searches
            
        Returns:
            Enhanced reference with concept mini-web data
        """
        topic = reference_item.get('topic', '')
        if not topic:
            return reference_item
        
        # Check cache first
        cache_key = f"{topic}_{user_id}"
        if cache_key in self.reference_concept_cache:
            cached_result = self.reference_concept_cache[cache_key]
            # Use cache if less than 30 minutes old
            if (datetime.now() - cached_result['timestamp']).seconds < 1800:
                reference_item['concept_web'] = cached_result['concept_web']
                return reference_item
        
        # Generate concept mini-web
        try:
            # Get user's knowledge context for this topic
            knowledge_context = self.analyze_user_knowledge_gaps(topic, user_context, user_id)
            
            # Build mini-web with constraints
            constraints = {
                'depth': 2,  # Keep shallow for reference enhancement
                'max_concepts': 3,  # Small number for reference display
                'user_context': knowledge_context.get('related_memories', [])
            }
            
            concept_web = self.explorer.build_concept_mini_web(topic, constraints)
            
            # Cache the result
            self.reference_concept_cache[cache_key] = {
                'concept_web': concept_web,
                'timestamp': datetime.now()
            }
            
            # Add to reference item
            reference_item['concept_web'] = concept_web
            reference_item['knowledge_gaps'] = knowledge_context.get('knowledge_gaps', [])
            reference_item['user_familiarity'] = knowledge_context.get('familiarity_level', 0)
            
        except Exception as e:
            print(f"Error enhancing reference with concepts: {e}")
            # Gracefully degrade - reference still works without concepts
            reference_item['concept_web'] = None
        
        return reference_item
    
    def analyze_user_knowledge_gaps(self, concept: str, user_memories: List[Dict], 
                                  user_id: str) -> Dict:
        """
        Analyze user's knowledge gaps and familiarity with a concept
        
        Args:
            concept: The concept to analyze
            user_memories: User's related memories
            user_id: User identifier
            
        Returns:
            Dictionary with knowledge analysis results
        """
        analysis_result = {
            'concept': concept,
            'familiarity_level': 0,  # 0-3 scale
            'knowledge_gaps': [],
            'related_memories': user_memories[:REFERENCE_RELATED_MEMORIES_LIMIT],
            'novelty_score': 1.0,
            'learning_opportunities': []
        }
        
        try:
            # Calculate novelty and familiarity
            all_user_memories = self.db.get_all_memories(user_id)
            novelty_score = self.explorer.calculate_knowledge_novelty(concept, all_user_memories)
            familiarity_level = self._novelty_to_familiarity(novelty_score)
            
            analysis_result['novelty_score'] = novelty_score
            analysis_result['familiarity_level'] = familiarity_level
            
            # Identify knowledge gaps if user has some familiarity
            if familiarity_level > 0 and user_memories:
                knowledge_gaps = self._identify_knowledge_gaps(concept, user_memories)
                analysis_result['knowledge_gaps'] = knowledge_gaps
            
            # Generate learning opportunities
            if novelty_score > CONCEPT_NOVELTY_THRESHOLD:
                learning_opps = self._generate_learning_opportunities(concept, user_memories, familiarity_level)
                analysis_result['learning_opportunities'] = learning_opps
                
        except Exception as e:
            print(f"Error analyzing user knowledge gaps: {e}")
        
        return analysis_result
    
    def format_concept_web_display(self, concept_web: Dict, depth_level: int = 1, interactive: bool = True) -> str:
        """
        Format concept web for display in MENTAT's Rich terminal interface
        
        Args:
            concept_web: Concept web dictionary from explorer
            depth_level: Display depth (1=mini, 2=expanded, 3=full)
            
        Returns:
            Formatted string ready for Rich display
        """
        if not concept_web or not concept_web.get('concepts'):
            return ""
        
        root = concept_web.get('root', 'Unknown')
        concepts = concept_web.get('concepts', [])
        
        # Adjust display based on depth level
        if depth_level == 1:  # Mini display for /view enhancement
            display_concepts = concepts[:3]
            header = f"🌳 **Related Concepts to Explore:**"
        elif depth_level == 2:  # Expanded display
            display_concepts = concepts[:5]
            header = f"🌳 **Concept Web for '{root}':**"
        else:  # Full display
            display_concepts = concepts
            header = f"🌳 **Full Concept Exploration for '{root}':**"
        
        if not display_concepts:
            return ""
        
        # Build formatted display
        formatted_lines = [header]
        
        for concept in display_concepts:
            number = concept.get('number', 0)
            name = concept.get('name', 'Unknown')
            description = concept.get('description', '')
            domain = concept.get('domain', 'general')
            novelty = concept.get('novelty', 0.0)
            
            # Format concept line with domain indicator and novelty hint
            domain_emoji = self._get_domain_emoji(domain)
            novelty_indicator = self._get_novelty_indicator(novelty)
            
            # Truncate description for clean display
            if description and len(description) > 60:
                description = description[:57] + "..."
            
            concept_line = f"    ├── **{name}** [{number}] {domain_emoji}"
            if novelty_indicator:
                concept_line += f" {novelty_indicator}"
            
            formatted_lines.append(concept_line)
            
            if description:
                formatted_lines.append(f"        {description}")
        
        # Add exploration hint
        if depth_level == 1:
            formatted_lines.append("")
            if interactive:
                formatted_lines.append("💡 Use `/explore <number>` to explore concepts • `/explain <number>` for detailed explanations")
            else:
                formatted_lines.append('💡 Use `mentat explore "<concept>"` to explore concepts • `mentat explain "<concept>"` for detailed explanations')
        
        return "\n".join(formatted_lines)
    
    def format_hierarchical_concept_tree(self, concept_tree: Dict, interactive: bool = True) -> str:
        """
        Format hierarchical concept tree for display in MENTAT's Rich terminal interface
        
        Args:
            concept_tree: Hierarchical concept tree dictionary
            
        Returns:
            Formatted string ready for Rich display with full tree structure
        """
        if not concept_tree or not concept_tree.get('concepts'):
            return ""
        
        root = concept_tree.get('root', 'Unknown')
        concepts = concept_tree.get('concepts', [])
        
        if not concepts:
            return ""
        
        # Build formatted hierarchical display
        header = f"🌳 **Related Concepts to Explore:**"
        formatted_lines = [header]
        
        for i, main_concept in enumerate(concepts):
            # Determine if this is the last main concept for proper tree formatting
            is_last_main = (i == len(concepts) - 1)
            main_prefix = "└──" if is_last_main else "├──"
            
            # Format main concept
            name = main_concept.get('name', 'Unknown')
            number = main_concept.get('number', 0)
            domain = main_concept.get('domain', 'general')
            novelty = main_concept.get('novelty', 0.0)
            
            domain_emoji = self._get_domain_emoji(domain)
            novelty_indicator = self._get_novelty_indicator(novelty)
            
            main_line = f"{main_prefix} **{name}** [{number}] {domain_emoji}"
            if novelty_indicator:
                main_line += f" {novelty_indicator}"
            
            formatted_lines.append(main_line)
            
            # Format sub-concepts
            sub_concepts = main_concept.get('sub_concepts', [])
            for j, sub_concept in enumerate(sub_concepts):
                # Determine proper indentation and tree symbols
                is_last_sub = (j == len(sub_concepts) - 1)
                if is_last_main:
                    # For the last main concept, use spaces for proper tree structure
                    sub_prefix = "        └──" if is_last_sub else "        ├──"
                else:
                    # For non-last main concepts, use vertical line continuation
                    sub_prefix = "│       └──" if is_last_sub else "│       ├──"
                
                sub_name = sub_concept.get('name', 'Unknown')
                sub_number = sub_concept.get('number', 0)
                sub_domain = sub_concept.get('domain', 'general')
                sub_novelty = sub_concept.get('novelty', 0.0)
                
                sub_domain_emoji = self._get_domain_emoji(sub_domain)
                sub_novelty_indicator = self._get_novelty_indicator(sub_novelty)
                
                sub_line = f"{sub_prefix} **{sub_name}** [{sub_number}] {sub_domain_emoji}"
                if sub_novelty_indicator:
                    sub_line += f" {sub_novelty_indicator}"
                
                formatted_lines.append(sub_line)
        
        # Add exploration hint
        formatted_lines.append("")
        formatted_lines.append(self._concept_hint(interactive, "deeper"))
        
        return "\n".join(formatted_lines)
    
    def format_deep_hierarchical_concept_tree(self, concept_tree: Dict, interactive: bool = True) -> str:
        """
        Format 3-level hierarchical concept tree for display in /explore command
        
        Args:
            concept_tree: Deep hierarchical concept tree dictionary
            
        Returns:
            Formatted string ready for Rich display with 3-level tree structure
        """
        if not concept_tree or not concept_tree.get('concepts'):
            return ""
        
        root = concept_tree.get('root', 'Unknown')
        concepts = concept_tree.get('concepts', [])
        
        if not concepts:
            return ""
        
        # Build formatted deep hierarchical display
        header = f"🌳 **Deep Concept Exploration for '{root}':**"
        formatted_lines = [header]
        
        for i, main_concept in enumerate(concepts):
            # Determine if this is the last main concept for proper tree formatting
            is_last_main = (i == len(concepts) - 1)
            main_prefix = "└──" if is_last_main else "├──"
            
            # Format main concept
            name = main_concept.get('name', 'Unknown')
            number = main_concept.get('number', 0)
            domain = main_concept.get('domain', 'general')
            novelty = main_concept.get('novelty', 0.0)
            
            domain_emoji = self._get_domain_emoji(domain)
            novelty_indicator = self._get_novelty_indicator(novelty)
            
            main_line = f"{main_prefix} **{name}** [{number}] {domain_emoji}"
            if novelty_indicator:
                main_line += f" {novelty_indicator}"
            
            formatted_lines.append(main_line)
            
            # Format sub-concepts
            sub_concepts = main_concept.get('sub_concepts', [])
            for j, sub_concept in enumerate(sub_concepts):
                # Determine proper indentation and tree symbols for sub-concepts
                is_last_sub = (j == len(sub_concepts) - 1)
                if is_last_main:
                    # For the last main concept, use spaces for proper tree structure
                    sub_prefix = "        └──" if is_last_sub else "        ├──"
                    deep_continuation = "            " if is_last_sub else "        │   "
                else:
                    # For non-last main concepts, use vertical line continuation
                    sub_prefix = "│       └──" if is_last_sub else "│       ├──"
                    deep_continuation = "│           " if is_last_sub else "│       │   "
                
                sub_name = sub_concept.get('name', 'Unknown')
                sub_number = sub_concept.get('number', 0)
                sub_domain = sub_concept.get('domain', 'general')
                sub_novelty = sub_concept.get('novelty', 0.0)
                
                sub_domain_emoji = self._get_domain_emoji(sub_domain)
                sub_novelty_indicator = self._get_novelty_indicator(sub_novelty)
                
                sub_line = f"{sub_prefix} **{sub_name}** [{sub_number}] {sub_domain_emoji}"
                if sub_novelty_indicator:
                    sub_line += f" {sub_novelty_indicator}"
                
                formatted_lines.append(sub_line)
                
                # Format deep concepts (3rd level)
                deep_concepts = sub_concept.get('deep_concepts', [])
                for k, deep_concept in enumerate(deep_concepts):
                    # Determine proper indentation for deep concepts
                    is_last_deep = (k == len(deep_concepts) - 1)
                    deep_prefix = f"{deep_continuation}└──" if is_last_deep else f"{deep_continuation}├──"
                    
                    deep_name = deep_concept.get('name', 'Unknown')
                    deep_number = deep_concept.get('number', 0)
                    deep_domain = deep_concept.get('domain', 'general')
                    deep_novelty = deep_concept.get('novelty', 0.0)
                    
                    deep_domain_emoji = self._get_domain_emoji(deep_domain)
                    deep_novelty_indicator = self._get_novelty_indicator(deep_novelty)
                    
                    deep_line = f"{deep_prefix} **{deep_name}** [{deep_number}] {deep_domain_emoji}"
                    if deep_novelty_indicator:
                        deep_line += f" {deep_novelty_indicator}"
                    
                    formatted_lines.append(deep_line)
        
        # Add exploration hint
        formatted_lines.append("")
        formatted_lines.append(self._concept_hint(interactive, "even deeper"))
        
        return "\n".join(formatted_lines)
    
    def create_explorable_references(self, concept_list: List[str], user_id: str,
                                   reference_counter_start: int = 1) -> Dict:
        """
        Create numbered references for concepts that can be explored via /view
        
        Args:
            concept_list: List of concept names to make explorable
            user_id: User identifier for knowledge context
            reference_counter_start: Starting number for references
            
        Returns:
            Dictionary mapping reference numbers to concept data
        """
        explorable_refs = {}
        
        for i, concept in enumerate(concept_list, reference_counter_start):
            # Get user's related memories for this concept
            related_memories = self.db.comprehensive_search(user_id, concept)[:3]
            
            # Create reference entry compatible with existing /view system
            explorable_refs[str(i)] = {
                'topic': concept,
                'context': f"Concept exploration from ConceptExplorer",
                'personal_context': f"Generated while exploring related concepts",
                'timestamp': datetime.now(),
                'concept_exploration': True,  # Flag to identify concept references
                'related_memories': related_memories
            }
        
        return explorable_refs
    
    def generate_concept_explanation(self, concept: str, user_id: str, current_model: str) -> str:
        """
        Generate a comprehensive explanation for a concept with user context
        Similar to reference explanations but concept-focused
        
        Args:
            concept: Concept to explain
            user_id: User identifier 
            current_model: LLM model to use
            
        Returns:
            Formatted explanation string
        """
        try:
            # Get user's related memories
            related_memories = self.db.comprehensive_search(user_id, concept)[:3]
            
            # Build context for explanation
            user_context = ""
            if related_memories:
                user_context = f"\n\nUser's related memories:\n"
                for i, memory in enumerate(related_memories, 1):
                    content = memory.get('content', '')[:200]
                    timestamp = memory.get('timestamp', 'Unknown date')
                    user_context += f"{i}. [{timestamp}] {content}...\n"
            
            # Generate explanation prompt
            prompt = f"""Provide a comprehensive explanation of the concept: **{concept}**

Structure your response as:
**What it is:** Clear definition and overview
**Why it matters:** Significance and real-world applications  
**Key aspects:** Important details, features, or components
**Learning pathways:** Suggested areas to explore further
**Connection to user:** How this relates to their interests/work (if evident from their memories)

{user_context}

Keep the explanation informative but accessible (2-3 paragraphs for each section). Focus on practical understanding and learning value."""

            explanation = complete(
                self.client,
                current_model,
                [{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.3  # Balanced creativity for explanations
            )
            
            # Add personal context if available
            if related_memories:
                explanation += "\n\n**From your memories:**\n"
                for mem in related_memories:
                    preview = mem['content'][:100].replace('\n', ' ')
                    timestamp = mem.get('timestamp', 'Unknown date')[:10]
                    explanation += f"• [{timestamp}] {preview}...\n"
            
            return explanation
            
        except Exception as e:
            print(f"Error generating concept explanation: {e}")
            return f"**{concept}**\n\nUnable to generate detailed explanation at this time. This concept was identified as related and worth exploring further."
    
    def _novelty_to_familiarity(self, novelty_score: float) -> int:
        """Convert novelty score to familiarity level"""
        if novelty_score > 0.8:
            return 0  # Unknown
        elif novelty_score > 0.5:
            return 1  # Basic
        elif novelty_score > 0.2:
            return 2  # Intermediate
        else:
            return 3  # Expert
    
    def _identify_knowledge_gaps(self, concept: str, user_memories: List[Dict]) -> List[str]:
        """Identify potential knowledge gaps in user's understanding"""
        gaps = []
        
        # Analyze content depth and coverage
        if len(user_memories) == 1:
            gaps.append("Limited exploration - only one related memory found")
        elif len(user_memories) < 3:
            gaps.append("Could benefit from deeper exploration")
        
        # Check for specific technical vs. conceptual knowledge
        technical_content = sum(1 for mem in user_memories 
                              if any(tech_word in mem.get('content', '').lower() 
                                   for tech_word in ['implementation', 'code', 'technical', 'how to']))
        
        conceptual_content = sum(1 for mem in user_memories
                               if any(concept_word in mem.get('content', '').lower()
                                    for concept_word in ['theory', 'concept', 'principle', 'why', 'philosophy']))
        
        if technical_content > conceptual_content * 2:
            gaps.append("Strong technical knowledge - could explore theoretical foundations")
        elif conceptual_content > technical_content * 2:
            gaps.append("Good conceptual understanding - could explore practical applications")
        
        return gaps[:2]  # Limit to most relevant gaps
    
    def _generate_learning_opportunities(self, concept: str, user_memories: List[Dict], 
                                       familiarity_level: int) -> List[str]:
        """Generate learning opportunity suggestions"""
        opportunities = []
        
        if familiarity_level == 0:  # Unknown concept
            opportunities.append(f"Start with fundamentals and basic principles of {concept}")
            opportunities.append(f"Look for real-world examples and applications")
        elif familiarity_level == 1:  # Basic familiarity
            opportunities.append(f"Explore advanced applications and edge cases")
            opportunities.append(f"Connect {concept} to related domains and technologies")
        elif familiarity_level == 2:  # Intermediate
            opportunities.append(f"Dive into implementation details and best practices")
            opportunities.append(f"Explore cutting-edge developments in {concept}")
        else:  # Expert level
            opportunities.append(f"Share knowledge and teach others about {concept}")
            opportunities.append(f"Contribute to the field or explore research frontiers")
        
        return opportunities[:2]  # Keep concise
    
    def _get_domain_emoji(self, domain: str) -> str:
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
    
    def _get_novelty_indicator(self, novelty_score: float) -> str:
        """Get indicator for concept novelty"""
        if novelty_score > 0.7:
            return "🆕"  # New to user
        elif novelty_score > 0.4:
            return "🔍"  # Worth exploring
        else:
            return ""  # Familiar, no indicator needed


# Utility functions for integration with existing MENTAT commands

def enhance_view_with_concepts(reference_data: Dict, user_id: str, db: MemoryDatabase, 
                             openrouter_client: Any) -> Dict:
    """
    Convenience function to enhance /view command with concept exploration
    
    Args:
        reference_data: Reference dictionary from enhanced_chat
        user_id: User identifier
        db: Database instance
        openrouter_client: OpenRouter client
        
    Returns:
        Enhanced reference with concept web data
    """
    integration_manager = ConceptIntegrationManager(db, openrouter_client)
    
    # Get user context for the reference topic
    topic = reference_data.get('topic', '')
    user_memories = db.comprehensive_search(user_id, topic)[:REFERENCE_RELATED_MEMORIES_LIMIT]
    
    return integration_manager.enhance_reference_with_concepts(reference_data, user_memories, user_id)


def create_concept_mini_web_display(concept: str, user_id: str, db: MemoryDatabase,
                                  openrouter_client: Any) -> str:
    """
    Create a formatted concept mini-web for display in MENTAT interface
    
    Args:
        concept: Root concept to explore
        user_id: User identifier
        db: Database instance  
        openrouter_client: OpenRouter client
        
    Returns:
        Formatted string for Rich display
    """
    integration_manager = ConceptIntegrationManager(db, openrouter_client)
    
    # Get user's knowledge context
    user_memories = db.comprehensive_search(user_id, concept)[:3]
    
    # Build mini-web
    constraints = {
        'depth': 2,
        'max_concepts': 3,
        'user_context': user_memories
    }
    
    concept_web = integration_manager.explorer.build_concept_mini_web(concept, constraints)
    
    return integration_manager.format_concept_web_display(concept_web, depth_level=1)


def build_full_hierarchical_concept_tree(concept: str, user_id: str, db: MemoryDatabase,
                                        openrouter_client: Any) -> Dict:
    """
    Build a full hierarchical concept tree for display in /view command

    Args:
        concept: Root concept to explore
        user_id: User identifier
        db: Database instance
        openrouter_client: OpenRouter client

    Returns:
        Hierarchical concept tree dictionary with nested structure
    """
    from mentat.core.config import CONCEPT_EXPLORATION_DEFAULT_DEPTH, CONCEPT_EXPLORATION_MAX_CONCEPTS
    
    integration_manager = ConceptIntegrationManager(db, openrouter_client)
    
    # Get user's knowledge context
    user_memories = db.comprehensive_search(user_id, concept)[:3]
    
    # Use config values for full tree - this aligns with your desired structure
    depth = CONCEPT_EXPLORATION_DEFAULT_DEPTH  # Default: 3
    max_concepts = CONCEPT_EXPLORATION_MAX_CONCEPTS  # Default: 4
    
    # Build full concept web using the explorer
    concept_web = integration_manager.explorer.explore_concept(
        concept=concept,
        depth=depth,  # Use config depth: 3 levels by default
        max_concepts=max_concepts,
        user_knowledge_context=user_memories
    )
    
    if not concept_web or not hasattr(concept_web, 'nodes'):
        # Fallback to mini-web if full exploration fails
        constraints = {
            'depth': 2,
            'max_concepts': max_concepts,
            'user_context': user_memories
        }
        return integration_manager.explorer.build_concept_mini_web(concept, constraints)
    
    # Convert ConceptWeb to hierarchical dictionary structure
    return _convert_concept_web_to_hierarchy(concept_web, max_concepts)


def _convert_concept_web_to_hierarchy(concept_web, max_concepts: int) -> Dict:
    """
    Convert ConceptWeb object to hierarchical dictionary for tree display
    """
    if not concept_web or not hasattr(concept_web, 'nodes'):
        return {'root': 'Unknown', 'concepts': [], 'total_concepts': 0}
    
    # Get root concept
    root_nodes = [node for node in concept_web.nodes.values() if node.depth == 0]
    root_concept = root_nodes[0].name if root_nodes else 'Unknown'
    
    # Get main concepts (depth 1)
    main_concepts = [node for node in concept_web.nodes.values() if node.depth == 1][:max_concepts]
    
    hierarchical_concepts = []
    concept_counter = 1
    
    for main_concept in main_concepts:
        # Get sub-concepts for this main concept (depth 2)
        sub_concepts = [node for node in concept_web.nodes.values() 
                       if node.depth == 2 and node.parent == main_concept.name][:max_concepts]
        
        # Format main concept
        main_concept_data = {
            'number': concept_counter,
            'name': main_concept.name,
            'description': main_concept.description or '',
            'domain': getattr(main_concept, 'domain', 'general'),
            'novelty': getattr(main_concept, 'novelty_score', 0.0),
            'sub_concepts': []
        }
        concept_counter += 1
        
        # Add sub-concepts
        for sub_concept in sub_concepts:
            sub_concept_data = {
                'number': concept_counter,
                'name': sub_concept.name,
                'description': sub_concept.description or '',
                'domain': getattr(sub_concept, 'domain', 'general'),
                'novelty': getattr(sub_concept, 'novelty_score', 0.0)
            }
            main_concept_data['sub_concepts'].append(sub_concept_data)
            concept_counter += 1
        
        hierarchical_concepts.append(main_concept_data)
    
    return {
        'root': root_concept,
        'concepts': hierarchical_concepts,
        'total_concepts': concept_counter - 1,
        'hierarchical': True  # Flag to indicate this is hierarchical structure
    }


def build_deep_hierarchical_concept_tree(concept: str, user_id: str, db: MemoryDatabase,
                                        openrouter_client: Any) -> Dict:
    """
    Build a deep 3-level hierarchical concept tree for /explore command

    Args:
        concept: Root concept to explore
        user_id: User identifier
        db: Database instance
        openrouter_client: OpenRouter client

    Returns:
        3-level hierarchical concept tree dictionary with nested structure
    """
    from mentat.core.config import CONCEPT_EXPLORATION_DEFAULT_DEPTH, CONCEPT_EXPLORATION_MAX_CONCEPTS
    
    integration_manager = ConceptIntegrationManager(db, openrouter_client)
    
    # Get user's knowledge context
    user_memories = db.comprehensive_search(user_id, concept)[:5]  # More context for deeper exploration
    
    # Use config values for deep tree - 3 levels
    depth = CONCEPT_EXPLORATION_DEFAULT_DEPTH  # Default: 3
    max_concepts = CONCEPT_EXPLORATION_MAX_CONCEPTS  # Default: 4
    
    # Build deep concept web using the explorer
    concept_web = integration_manager.explorer.explore_concept(
        concept=concept,
        depth=3,  # 3 levels: main concepts → sub-concepts → deep concepts
        max_concepts=max_concepts,
        user_knowledge_context=user_memories
    )
    
    if not concept_web or not hasattr(concept_web, 'nodes'):
        # Fallback to 2-level if deep exploration fails
        return build_full_hierarchical_concept_tree(concept, user_id, db, openrouter_client)
    
    # Convert ConceptWeb to 3-level hierarchical dictionary structure
    return _convert_concept_web_to_deep_hierarchy(concept_web, max_concepts)


def _convert_concept_web_to_deep_hierarchy(concept_web, max_concepts: int) -> Dict:
    """
    Convert ConceptWeb object to 3-level hierarchical dictionary for deep tree display
    """
    if not concept_web or not hasattr(concept_web, 'nodes'):
        return {'root': 'Unknown', 'concepts': [], 'total_concepts': 0}
    
    # Get root concept
    root_nodes = [node for node in concept_web.nodes.values() if node.depth == 0]
    root_concept = root_nodes[0].name if root_nodes else 'Unknown'
    
    # Get main concepts (depth 1)
    main_concepts = [node for node in concept_web.nodes.values() if node.depth == 1][:max_concepts]
    
    hierarchical_concepts = []
    concept_counter = 1
    
    for main_concept in main_concepts:
        # Get sub-concepts for this main concept (depth 2)
        sub_concepts = [node for node in concept_web.nodes.values() 
                       if node.depth == 2 and node.parent == main_concept.name][:max_concepts]
        
        # Format main concept
        main_concept_data = {
            'number': concept_counter,
            'name': main_concept.name,
            'description': main_concept.description or '',
            'domain': getattr(main_concept, 'domain', 'general'),
            'novelty': getattr(main_concept, 'novelty_score', 0.0),
            'sub_concepts': []
        }
        concept_counter += 1
        
        # Add sub-concepts with their deep concepts
        for sub_concept in sub_concepts:
            # Get deep concepts for this sub-concept (depth 3)
            deep_concepts = [node for node in concept_web.nodes.values() 
                           if node.depth == 3 and node.parent == sub_concept.name][:max_concepts]
            
            sub_concept_data = {
                'number': concept_counter,
                'name': sub_concept.name,
                'description': sub_concept.description or '',
                'domain': getattr(sub_concept, 'domain', 'general'),
                'novelty': getattr(sub_concept, 'novelty_score', 0.0),
                'deep_concepts': []
            }
            concept_counter += 1
            
            # Add deep concepts
            for deep_concept in deep_concepts:
                deep_concept_data = {
                    'number': concept_counter,
                    'name': deep_concept.name,
                    'description': deep_concept.description or '',
                    'domain': getattr(deep_concept, 'domain', 'general'),
                    'novelty': getattr(deep_concept, 'novelty_score', 0.0)
                }
                sub_concept_data['deep_concepts'].append(deep_concept_data)
                concept_counter += 1
            
            main_concept_data['sub_concepts'].append(sub_concept_data)
        
        hierarchical_concepts.append(main_concept_data)
    
    return {
        'root': root_concept,
        'concepts': hierarchical_concepts,
        'total_concepts': concept_counter - 1,
        'hierarchical': True,
        'deep_hierarchy': True  # Flag to indicate this is 3-level structure
    }
