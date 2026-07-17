"""
MENTAT ConceptExplorer Engine
Intelligent concept exploration and web generation adapted for MENTAT integration
"""

import json
import re
from typing import List, Dict, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict, Counter

from mentat.core.config import (
    CONCEPT_EXPLORATION_DEFAULT_DEPTH, CONCEPT_EXPLORATION_MAX_CONCEPTS,
    CONCEPT_DIVERSITY_BIAS, CONCEPT_NOVELTY_THRESHOLD, CONCEPT_WEB_DISPLAY_LIMIT,
    CONCEPT_EXPLORATION_BATCH_SIZE
)
from mentat.core.llm import complete, get_task_llm_route


@dataclass
class ConceptNode:
    """Individual concept representation with metadata"""
    name: str
    description: str = ""
    domain: str = "general"  # tech, philosophy, culture, science, etc.
    depth: int = 0
    parent: Optional[str] = None
    children: List[str] = field(default_factory=list)
    confidence: float = 1.0
    novelty_score: float = 0.0  # Based on user's knowledge
    user_familiarity: int = 0  # 0=unknown, 1=basic, 2=intermediate, 3=expert
    related_memories: List[Dict] = field(default_factory=list)
    
    def __post_init__(self):
        """Ensure children is always a list"""
        if not isinstance(self.children, list):
            self.children = []


@dataclass
class ConceptWeb:
    """Graph structure for concept relationships"""
    root_concept: str
    nodes: Dict[str, ConceptNode] = field(default_factory=dict)
    connections: Dict[str, List[str]] = field(default_factory=dict)
    max_depth: int = 3
    max_concepts: int = 4
    generation_timestamp: datetime = field(default_factory=datetime.now)
    
    def add_node(self, concept: ConceptNode) -> None:
        """Add a concept node to the web"""
        self.nodes[concept.name] = concept
        if concept.name not in self.connections:
            self.connections[concept.name] = []
    
    def add_connection(self, parent: str, child: str) -> None:
        """Add a connection between two concepts"""
        if parent not in self.connections:
            self.connections[parent] = []
        if child not in self.connections[parent]:
            self.connections[parent].append(child)
    
    def get_concepts_by_depth(self, depth: int) -> List[ConceptNode]:
        """Get all concepts at a specific depth level"""
        return [node for node in self.nodes.values() if node.depth == depth]
    
    def get_leaf_concepts(self) -> List[ConceptNode]:
        """Get concepts with no children (leaf nodes)"""
        return [node for node in self.nodes.values() if not node.children]


class MentatConceptExplorer:
    """
    Main exploration engine optimized for MENTAT integration
    Generates diverse, contextually relevant concept webs
    """
    
    def __init__(self, openrouter_client: Any, db: Any = None):
        """
        Initialize the concept explorer
        
        Args:
            openrouter_client: OpenRouter client for LLM interactions
            db: Optional database reference for user knowledge analysis
        """
        self.client = openrouter_client
        self.db = db
        self.concept_cache: Dict[str, ConceptWeb] = {}
        self.domain_keywords = {
            'tech': ['programming', 'software', 'algorithm', 'data', 'system', 'code', 'framework', 'api', 'database', 'cloud'],
            'philosophy': ['thinking', 'ethics', 'logic', 'meaning', 'consciousness', 'reality', 'truth', 'knowledge', 'wisdom'],
            'culture': ['society', 'art', 'music', 'literature', 'tradition', 'community', 'history', 'language', 'belief'],
            'science': ['research', 'experiment', 'theory', 'discovery', 'method', 'analysis', 'hypothesis', 'evidence'],
            'business': ['strategy', 'market', 'customer', 'revenue', 'growth', 'innovation', 'leadership', 'process'],
            'creative': ['design', 'creativity', 'innovation', 'inspiration', 'imagination', 'artistic', 'visual', 'aesthetic']
        }
    
    def explore_concept(self, concept: str, depth: int = None, max_concepts: int = None, 
                       user_knowledge_context: List[Dict] = None) -> ConceptWeb:
        """
        Main entry point for concept exploration
        
        Args:
            concept: Root concept to explore
            depth: Maximum depth to explore (default from config)
            max_concepts: Maximum concepts per level (default from config)
            user_knowledge_context: User's related memories for context
            
        Returns:
            ConceptWeb with explored concepts and relationships
        """
        depth = depth or CONCEPT_EXPLORATION_DEFAULT_DEPTH
        max_concepts = max_concepts or CONCEPT_EXPLORATION_MAX_CONCEPTS
        
        # Check cache first
        cache_key = f"{concept}_{depth}_{max_concepts}"
        if cache_key in self.concept_cache:
            cached_web = self.concept_cache[cache_key]
            # Refresh if older than 1 hour
            if (datetime.now() - cached_web.generation_timestamp).seconds < 3600:
                return cached_web
        
        # Create new concept web
        web = ConceptWeb(
            root_concept=concept,
            max_depth=depth,
            max_concepts=max_concepts
        )
        
        # Add root concept
        root_node = ConceptNode(
            name=concept,
            description=f"Root concept: {concept}",
            depth=0,
            user_familiarity=self._calculate_user_familiarity(concept, user_knowledge_context) if user_knowledge_context else 0
        )
        web.add_node(root_node)
        
        # Build concept tree level by level using batch processing
        for current_depth in range(1, depth + 1):
            parent_concepts = web.get_concepts_by_depth(current_depth - 1)
            
            if not parent_concepts or len(web.nodes) >= CONCEPT_WEB_DISPLAY_LIMIT:
                break
            
            # BATCH PROCESSING: Generate child concepts for all parents in one API call
            batch_child_concepts = self._batch_generate_child_concepts(
                parent_concepts,
                current_depth,
                max_concepts,
                user_knowledge_context,
                existing_concepts=list(web.nodes.keys())
            )
            
            # Process the batch results
            for parent_name, child_concepts in batch_child_concepts.items():
                parent_node = web.nodes.get(parent_name)
                if not parent_node:
                    continue
                    
                for child_concept in child_concepts:
                    if child_concept['name'] not in web.nodes:
                        child_node = ConceptNode(
                            name=child_concept['name'],
                            description=child_concept.get('description', ''),
                            domain=child_concept.get('domain', 'general'),
                            depth=current_depth,
                            parent=parent_name,
                            confidence=child_concept.get('confidence', 1.0),
                            novelty_score=child_concept.get('novelty_score', 0.0),
                            user_familiarity=self._calculate_user_familiarity(
                                child_concept['name'], user_knowledge_context
                            ) if user_knowledge_context else 0
                        )
                        
                        web.add_node(child_node)
                        web.add_connection(parent_name, child_concept['name'])
                        parent_node.children.append(child_concept['name'])
        
        # Cache the result
        self.concept_cache[cache_key] = web
        return web
    
    def get_diverse_concepts(self, root_concept: str, user_knowledge_context: List[Dict] = None,
                           count: int = 4, existing_concepts: List[str] = None) -> List[Dict]:
        """
        Generate diverse concepts using domain diversity algorithms
        
        Args:
            root_concept: The concept to explore from
            user_knowledge_context: User's memories for context
            count: Number of concepts to generate
            existing_concepts: List of existing concepts to avoid duplication
            
        Returns:
            List of diverse concept dictionaries
        """
        route = get_task_llm_route("CONCEPT_EXPLORATION", self.client)
        if not route.client:
            return []
        
        try:
            # Build context about user's knowledge
            user_context = ""
            if user_knowledge_context:
                user_context = f"\nUser's related knowledge context:\n"
                for i, memory in enumerate(user_knowledge_context[:3], 1):
                    content = memory.get('content', '')[:200]
                    user_context += f"{i}. {content}...\n"

            existing_context = f"\nAvoid these already explored concepts: {', '.join(existing_concepts[:10])}" if existing_concepts else ""
            
            prompt = f"""Generate {count} concepts related to \"{root_concept}\".

Return as JSON array:
[
  {{"name": "Short Concept", "domain": "tech"}},
  {{"name": "Another Concept", "domain": "philosophy"}},
  {{"name": "Third Concept", "domain": "science"}}
]

Keep names 1-3 words. Use diverse domains: tech, philosophy, culture, science, business, creative.{existing_context}"""

            content = complete(
                route.client,
                route.model,
                [{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.7  # Some creativity for diverse concepts
            ).strip()
            
            # Extract JSON from response
            json_match = re.search(r'```json\n(.*?)```', content, re.DOTALL)
            if not json_match:
                json_match = re.search(r'\[.*\]', content, re.DOTALL)

            if json_match:
                json_str = json_match.group(1) if '```json' in json_match.group(0) else json_match.group(0)
                concepts_data = json.loads(json_str)
                
                # Convert structured array to concept dictionaries
                if isinstance(concepts_data, list):
                    formatted_concepts = []
                    for concept_item in concepts_data:
                        if isinstance(concept_item, dict):
                            # Structured format with name and domain
                            formatted_concepts.append({
                                'name': concept_item.get('name', 'Unknown Concept'),
                                'description': f'Related to {root_concept}',
                                'domain': concept_item.get('domain', 'general'),
                                'confidence': 0.8,
                                'novelty_score': 0.5
                            })
                        elif isinstance(concept_item, str):
                            # Fallback for simple string format
                            formatted_concepts.append({
                                'name': concept_item,
                                'description': f'Related to {root_concept}',
                                'domain': 'general',
                                'confidence': 0.8,
                                'novelty_score': 0.5
                            })
                    return formatted_concepts[:count]
                else:
                    # Fallback for old format
                    return self._apply_diversity_filtering(concepts_data, user_knowledge_context)
            
        except Exception as e:
            print(f"Error generating diverse concepts: {e}")
            return []
        
        return []
    
    def calculate_knowledge_novelty(self, concept: str, user_memories: List[Dict]) -> float:
        """
        Calculate how novel a concept is based on user's existing knowledge
        
        Args:
            concept: Concept to analyze
            user_memories: User's memory database entries
            
        Returns:
            Float between 0-1, where 1 is completely novel
        """
        if not user_memories:
            return 1.0  # Assume novel if no user data
        
        concept_lower = concept.lower()
        mention_count = 0
        total_memories = len(user_memories)
        
        # Count direct mentions
        for memory in user_memories:
            content = memory.get('content', '').lower()
            if concept_lower in content:
                mention_count += 1
                
            # Check tags and entities if available
            metadata = memory.get('metadata')
            if metadata:
                try:
                    metadata_dict = json.loads(metadata) if isinstance(metadata, str) else metadata
                    
                    # Check tags
                    tags = metadata_dict.get('tags', [])
                    if any(concept_lower in tag.lower() for tag in tags):
                        mention_count += 0.5
                    
                    # Check entities
                    entities = metadata_dict.get('entities', {})
                    for entity_list in entities.values():
                        if any(concept_lower in entity.lower() for entity in entity_list):
                            mention_count += 0.3
                            
                except (json.JSONDecodeError, TypeError):
                    pass
        
        # Calculate novelty score (inverse of familiarity)
        familiarity_ratio = mention_count / max(total_memories, 1)
        novelty_score = max(0.0, 1.0 - familiarity_ratio * 2)  # Scale appropriately
        
        return min(1.0, novelty_score)
    
    def build_concept_mini_web(self, root_concept: str, constraints: Dict = None) -> Dict:
        """
        Build a minimal concept web for display in /view command using efficient batch processing
        
        Args:
            root_concept: Central concept to explore
            constraints: Dictionary with depth, max_concepts, user_context
            
        Returns:
            Dictionary suitable for display formatting
        """
        constraints = constraints or {}
        depth = constraints.get('depth', 2)
        max_concepts = constraints.get('max_concepts', 3)
        user_context = constraints.get('user_context', [])
        
        # Use the same efficient explore_concept method as /explore but with mini-web constraints
        mini_concept_web = self.explore_concept(
            concept=root_concept,
            depth=depth,  # Usually 2 for mini-webs
            max_concepts=max_concepts,  # Usually 3-4 for mini-webs
            user_knowledge_context=user_context
        )
        
        if not mini_concept_web or not hasattr(mini_concept_web, 'nodes'):
            return {
                'root': root_concept,
                'concepts': [],
                'total_concepts': 0,
                'generation_time': datetime.now().isoformat()
            }
        
        # Convert ConceptWeb to mini-web format for display
        formatted_concepts = []
        concept_counter = 1
        
        # Get level 1 concepts (direct children of root)
        level_1_concepts = [node for node in mini_concept_web.nodes.values() if node.depth == 1][:max_concepts]
        
        for concept in level_1_concepts:
            formatted_concepts.append({
                'number': concept_counter,
                'name': concept.name,
                'description': concept.description or '',
                'domain': getattr(concept, 'domain', 'general'),
                'connection': f"Related to {root_concept}",
                'novelty': getattr(concept, 'novelty_score', 0.0),
                'confidence': getattr(concept, 'confidence', 1.0)
            })
            concept_counter += 1
        
        return {
            'root': root_concept,
            'concepts': formatted_concepts,
            'total_concepts': len(formatted_concepts),
            'generation_time': datetime.now().isoformat(),
            'depth': depth
        }
    
    def _batch_generate_child_concepts(self, parent_concepts: List[ConceptNode], depth: int,
                                      max_concepts: int, user_knowledge_context: List[Dict],
                                      existing_concepts: List[str]) -> Dict[str, List[Dict]]:
        """
        BATCH PROCESSING: Generate child concepts for multiple parents in smaller chunks.
        This improves reliability by avoiding overly large single API calls.

        Args:
            parent_concepts: List of parent ConceptNode objects
            depth: Current depth level
            max_concepts: Maximum concepts to generate per parent
            user_knowledge_context: User's related memories
            existing_concepts: Already generated concepts to avoid duplicates

        Returns:
            Dictionary mapping parent names to their child concept lists
        """
        route = get_task_llm_route("CONCEPT_EXPLORATION", self.client)
        if not route.client or not parent_concepts:
            return {}

        # Configuration for batching
        BATCH_SIZE = CONCEPT_EXPLORATION_BATCH_SIZE  # Number of parents to process in a single API call
        all_results = {}

        # Adjust concept count for deeper levels
        concepts_to_generate = 1 if depth >= 3 else max_concepts

        # Process parents in chunks
        for i in range(0, len(parent_concepts), BATCH_SIZE):
            chunk = parent_concepts[i:i + BATCH_SIZE]
            parent_names_chunk = [parent.name for parent in chunk]

            try:
                # Build user context
                user_context = ""
                if user_knowledge_context:
                    user_context = f"\nUser's knowledge context:\n"
                    for j, memory in enumerate(user_knowledge_context[:3], 1):
                        content = memory.get('content', '')[:150]
                        user_context += f"{j}. {content}...\n"

                # Build the batch prompt for the current chunk
                existing_context = f"\nAvoid these already explored concepts: {', '.join(existing_concepts[:10])}" if existing_concepts else ""
                batch_prompt = f"""For each parent concept, generate {concepts_to_generate} related concepts. Level {depth} exploration.

Parents: {', '.join(parent_names_chunk)}

Format as JSON:
```json
{{
  "parent1": [
    {{"name": "Short Concept", "domain": "tech"}},
    {{"name": "Another Concept", "domain": "philosophy"}}
  ],
  "parent2": [
    {{"name": "Third Concept", "domain": "science"}},
    {{"name": "Fourth Concept", "domain": "culture"}}
  ]
}}
```

Keep names 1-3 words. Use diverse domains: tech, philosophy, culture, science, business, creative.{existing_context}"""

                content = complete(
                    route.client,
                    route.model,
                    [{"role": "user", "content": batch_prompt}],
                    max_tokens=800,  # Reduced tokens for simpler response
                    temperature=0.4  # Lower temperature for more consistent JSON
                ).strip()

                # Enhanced JSON extraction
                json_match = re.search(r'```json\n(.*?)```', content, re.DOTALL)
                if not json_match:
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)

                if json_match:
                    json_str = json_match.group(1) if '```json' in json_match.group(0) else json_match.group(0)
                    try:
                        batch_data = json.loads(json_str)
                    except json.JSONDecodeError as json_error:
                        print(f"JSON parsing failed, trying to fix common issues: {json_error}")
                        # Try to fix common JSON issues
                        json_str_fixed = json_str.replace('\n', ' ').replace('\r', '')
                        # Remove trailing commas
                        json_str_fixed = re.sub(r',(\s*[}\]])', r'\1', json_str_fixed)
                        try:
                            batch_data = json.loads(json_str_fixed)
                            print("JSON parsing succeeded after fixing")
                        except json.JSONDecodeError:
                            print("JSON still malformed after fixing attempts, falling back")
                            raise json_error

                    # Process the structured batch results
                    for parent_name in parent_names_chunk:
                        child_concepts = batch_data.get(parent_name, [])

                        if isinstance(child_concepts, list) and child_concepts:
                            formatted_concepts = []
                            for concept_data in child_concepts[:concepts_to_generate]:
                                if isinstance(concept_data, dict):
                                    # Structured format with name and domain
                                    formatted_concepts.append({
                                        'name': concept_data.get('name', 'Unknown Concept'),
                                        'description': f'Related to {parent_name}',
                                        'domain': concept_data.get('domain', 'general'),
                                        'confidence': 0.8,
                                        'novelty_score': 0.5
                                    })
                                elif isinstance(concept_data, str):
                                    # Fallback for simple string format
                                    formatted_concepts.append({
                                        'name': concept_data,
                                        'description': f'Related to {parent_name}',
                                        'domain': 'general',
                                        'confidence': 0.8,
                                        'novelty_score': 0.5
                                    })
                            all_results[parent_name] = formatted_concepts
                        else:
                            fallback_concepts = self._generate_child_concepts(parent_name, depth, concepts_to_generate, user_knowledge_context, existing_concepts)
                            all_results[parent_name] = fallback_concepts
                else:
                    for parent_name in parent_names_chunk:
                        fallback_concepts = self._generate_child_concepts(parent_name, depth, concepts_to_generate, user_knowledge_context, existing_concepts)
                        all_results[parent_name] = fallback_concepts

            except (json.JSONDecodeError, ValueError) as e:
                for parent_name in parent_names_chunk:
                    fallback_concepts = self._generate_child_concepts(parent_name, depth, concepts_to_generate, user_knowledge_context, existing_concepts)
                    all_results[parent_name] = fallback_concepts
            except Exception as e:
                for parent_name in parent_names_chunk:
                    all_results[parent_name] = []

        return all_results
    
    def _generate_child_concepts(self, parent_concept: str, depth: int, max_concepts: int,
                               user_knowledge_context: List[Dict], existing_concepts: List[str]) -> List[Dict]:
        """Generate child concepts for a single parent concept (fallback method)"""
        # Adjust concept count for deeper levels
        concepts_to_generate = 1 if depth >= 3 else max_concepts
        return self.get_diverse_concepts(parent_concept, user_knowledge_context, concepts_to_generate, existing_concepts)
    
    def _calculate_user_familiarity(self, concept: str, user_memories: List[Dict]) -> int:
        """
        Calculate user's familiarity level with a concept
        
        Returns:
            0=unknown, 1=basic, 2=intermediate, 3=expert
        """
        if not user_memories:
            return 0
            
        novelty = self.calculate_knowledge_novelty(concept, user_memories)
        
        # Convert novelty to reverse familiarity scale
        if novelty > 0.8:
            return 0  # Unknown
        elif novelty > 0.5:
            return 1  # Basic
        elif novelty > 0.2:
            return 2  # Intermediate
        else:
            return 3  # Expert
    
    def _apply_diversity_filtering(self, concepts: List[Dict], user_context: List[Dict] = None) -> List[Dict]:
        """
        Apply diversity algorithms to ensure concepts span different domains
        """
        if not concepts:
            return []
        
        # Group by domain
        domain_groups = defaultdict(list)
        for concept in concepts:
            domain = concept.get('domain', 'general')
            domain_groups[domain].append(concept)
        
        # Select diverse concepts (max 1-2 per domain for small lists)
        diverse_concepts = []
        domains_used = []
        
        # First pass: one from each domain
        for domain, domain_concepts in domain_groups.items():
            if domain_concepts:
                # Sort by confidence and novelty
                best_concept = max(domain_concepts, 
                                 key=lambda x: x.get('confidence', 0) + x.get('novelty_score', 0))
                diverse_concepts.append(best_concept)
                domains_used.append(domain)
        
        # If we need more concepts and have space, add seconds from high-value domains
        target_count = min(len(concepts), CONCEPT_EXPLORATION_MAX_CONCEPTS)
        while len(diverse_concepts) < target_count and len(concepts) > len(diverse_concepts):
            for domain in domains_used:
                if len(diverse_concepts) >= target_count:
                    break
                remaining = [c for c in domain_groups[domain] if c not in diverse_concepts]
                if remaining:
                    best_remaining = max(remaining,
                                       key=lambda x: x.get('confidence', 0) + x.get('novelty_score', 0))
                    diverse_concepts.append(best_remaining)
            break
        
        return diverse_concepts[:target_count]
    
    def _classify_concept_domain(self, concept: str, description: str = "") -> str:
        """
        Classify a concept into a domain based on keywords and context
        """
        text = f"{concept} {description}".lower()
        
        domain_scores = {}
        for domain, keywords in self.domain_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text)
            if score > 0:
                domain_scores[domain] = score
        
        if domain_scores:
            return max(domain_scores.items(), key=lambda x: x[1])[0]
        
        return 'general'
