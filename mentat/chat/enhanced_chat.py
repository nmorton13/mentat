"""
Enhanced Chat System for MENTAT
Provides intelligent, context-aware conversations that combine:
- User's personal knowledge/patterns
- Entity-based connections  
- AI knowledge synthesis
- Transparent source attribution
"""

import json
import re
import time
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
import sys
import os

from mentat.core.database import MemoryDatabase
from mentat.core.ai import extract_structured_entities, get_embedding_for_content, log_llm_interaction
from mentat.core.llm import complete, complete_online
from mentat.core.config import (
    CHAT_SEARCH_K, CHAT_PREVIEW_LENGTH, PROJECT_ANALYSIS_K,
    MAX_TOTAL_REFERENCES,
    LLM_REQUEST_TIMEOUT, ENTITY_SEARCH_LIMIT, CHAT_CONTEXT_LIMIT,
    HYBRID_SEARCH_INTERNAL_MULTIPLIER, KEYWORD_MATCH_BASELINE_SCORE, CHAT_MIN_SIMILARITY,
    CHAT_HYBRID_SEARCH_K, resolve_chat_retrieval_limits,
)
from mentat.chat.prompts import get_system_prompt
from openai import OpenAI
import os

# Global state will be passed in as parameters to avoid circular imports

DEBUG_TIMING = os.getenv("MENTAT_DEBUG_TIMING", "false").lower() == "true"


def _debug_timing(message: str) -> None:
    if not DEBUG_TIMING:
        return
    try:
        from mentat.cli.display import console
        console.print(f"[dim][DEBUG] {message}[/dim]")
    except Exception:
        pass


class EnhancedChatSystem:
    """
    Intelligent chat system that acts as a thinking partner by:
    1. Gathering rich contextual information (semantic + entity + pattern-based)
    2. Analyzing user's thinking patterns and preferences
    3. Synthesizing personal context with AI knowledge
    4. Providing transparent source attribution
    """
    
    def __init__(self, db: MemoryDatabase, openrouter_client: Any) -> None:
        """
        Initialize the Enhanced Chat System with database and AI clients.
        
        Sets up the intelligent chat system that acts as a thinking partner by
        combining user's personal knowledge, entity relationships, and AI synthesis
        with transparent source attribution.
        
        Parameters:
            db (MemoryDatabase): Database interface for accessing stored memories
                and performing semantic/entity searches
            openrouter_client (Any): OpenRouter client for LLM operations and
                AI response generation
        
        Returns:
            None: Initializes instance with database connections and reference tracking
        """
        self.db = db
        self.client = openrouter_client
        
        # Initialize OpenAI client for embeddings
        self.openai_client = None
        if os.getenv('OPENAI_API_KEY'):
            self.openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'), timeout=LLM_REQUEST_TIMEOUT)
        
        # Session-based reference storage for dynamic chat
        self.session_references = {}
        self.reference_counter = 1

    def _is_ai_derived_memory(self, mem: Dict) -> bool:
        """Return True for saved AI replies, including older metadata-marked items."""
        if mem.get('command_type') == 'ai_response':
            return True

        metadata = mem.get('metadata')
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        elif metadata is None:
            metadata = {}

        source_info = metadata.get('source', {}) if isinstance(metadata, dict) else {}
        return source_info.get('type') == 'ai_response'
    
    def _hybrid_search(
        self,
        user_id: str,
        query: str,
        k: int = CHAT_HYBRID_SEARCH_K,
        internal_multiplier: float = HYBRID_SEARCH_INTERNAL_MULTIPLIER,
    ) -> List[Dict]:
        """
        Hybrid search combining semantic similarity + keyword matching with intelligent ranking.

        Uses MENTAT's existing search infrastructure with enhanced result merging:
        1. Semantic search via brute_sem_search (vector similarity) - fetches 2x candidates internally
        2. Keyword search via safe_memory_search (FTS5 full-text)
        3. Intelligent ranking by combined score (semantic similarity vs keyword baseline)
        4. Deduplication and return top k results

        This ensures queries like "titles of my essays" find results via both
        semantic understanding AND exact keyword matches, with the best results rising to the top.

        Configuration:
            HYBRID_SEARCH_INTERNAL_MULTIPLIER: How many extra candidates to fetch (default 2.0)
            KEYWORD_MATCH_BASELINE_SCORE: Similarity score assigned to keyword matches (default 0.4)
        """
        all_results = []
        seen_ids = set()

        # Calculate internal search limit (fetch more candidates for better ranking)
        internal_k = int(k * internal_multiplier)

        # Strategy 1: Semantic search (conceptual similarity)
        if self.openai_client:
            try:
                t0 = time.perf_counter()
                query_embedding = get_embedding_for_content(query, client=self.openai_client)
                _debug_timing(f"hybrid.query_embedding: {(time.perf_counter() - t0):.2f}s")
                if query_embedding:
                    t0 = time.perf_counter()
                    mem_ids = self.db.brute_sem_search(query_embedding, internal_k, min_similarity=CHAT_MIN_SIMILARITY)
                    _debug_timing(f"hybrid.brute_sem_search: {(time.perf_counter() - t0):.2f}s results={len(mem_ids)}")
                    if mem_ids:
                        # Convert to enhanced chat format with similarity scores
                        t0 = time.perf_counter()
                        with self.db.db_pool.get_connection() as conn:
                            cursor = conn.cursor()
                            memory_ids_only = [mem_id for mem_id, similarity in mem_ids]
                            placeholders = ','.join(['?'] * len(memory_ids_only))

                            cursor.execute(f"""
                                SELECT id, user_id, content, command_type, tags, metadata, timestamp
                                FROM memories
                                WHERE user_id = ? AND id IN ({placeholders})
                            """, [user_id] + memory_ids_only)

                            for row in cursor.fetchall():
                                mem_id = row[0]
                                if mem_id not in seen_ids:
                                    similarity = next((sim for mid, sim in mem_ids if mid == mem_id), 0.0)
                                    result = {
                                        'id': mem_id,
                                        'user_id': row[1],
                                        'content': row[2],
                                        'command_type': row[3],
                                        'tags': json.loads(row[4]) if row[4] else [],
                                        'metadata': row[5],
                                        'timestamp': row[6],
                                        'why_matched': f"Semantic similarity (score: {similarity:.2f})",
                                        '_search_score': similarity  # Internal score for ranking
                                    }
                                    if self._is_ai_derived_memory(result):
                                        continue
                                    all_results.append(result)
                                    seen_ids.add(mem_id)
                        _debug_timing(f"hybrid.semantic_fetch: {(time.perf_counter() - t0):.2f}s")
            except Exception as e:
                _debug_timing(f"hybrid.semantic_error: {type(e).__name__}: {e}")
                pass  # Continue to keyword search even if semantic fails

        # Strategy 2: Keyword search (exact/partial phrase matching)
        try:
            t0 = time.perf_counter()
            keyword_results = self.db.safe_memory_search(query, user_id)
            _debug_timing(f"hybrid.keyword_search: {(time.perf_counter() - t0):.2f}s results={len(keyword_results)}")
            t0 = time.perf_counter()
            for result in keyword_results[:15]:  # Allow more keyword candidates
                # safe_memory_search returns dicts without 'id', need to get it from DB
                content = result.get('content', '')

                # Check if we've seen this content already (deduplicate)
                is_duplicate = False
                for existing in all_results:
                    if existing.get('content') == content:
                        # Found duplicate! Boost its score if keyword baseline is higher
                        current_score = existing.get('_search_score', 0.0)
                        if KEYWORD_MATCH_BASELINE_SCORE > current_score:
                            existing['_search_score'] = KEYWORD_MATCH_BASELINE_SCORE
                        # Update why_matched to show it's also a keyword match
                        if "Keyword match" not in existing.get('why_matched', ''):
                            existing['why_matched'] = f"{existing['why_matched']} + Keyword match"
                        is_duplicate = True
                        break

                if not is_duplicate:
                    # Fetch the memory id and metadata from database
                    with self.db.db_pool.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT id, user_id, metadata
                            FROM memories
                            WHERE user_id = ? AND content = ?
                            LIMIT 1
                        """, [user_id, content])
                        row = cursor.fetchone()
                        if row:
                            # Add complete result with baseline score for ranking
                            complete_result = {
                                'id': row[0],
                                'user_id': row[1],
                                'content': content,
                                'command_type': result.get('command_type'),
                                'tags': result.get('tags', []),
                                'metadata': row[2],
                                'timestamp': result.get('timestamp'),
                                'why_matched': result.get('why_matched', 'Keyword match'),
                                '_search_score': KEYWORD_MATCH_BASELINE_SCORE  # Baseline score for keywords
                            }
                            if self._is_ai_derived_memory(complete_result):
                                continue
                            all_results.append(complete_result)
            _debug_timing(f"hybrid.keyword_hydrate: {(time.perf_counter() - t0):.2f}s")
        except Exception as e:
            _debug_timing(f"hybrid.keyword_error: {type(e).__name__}: {e}")
            pass  # If keyword search fails, at least we have semantic results

        # Rank all results by search score (highest first)
        all_results.sort(key=lambda r: r.get('_search_score', 0.0), reverse=True)

        # Remove internal scoring field and return top k results
        for result in all_results:
            if '_search_score' in result:
                del result['_search_score']

        return all_results[:k]

    def _query_likely_benefits_from_entities(self, query: str) -> bool:
        """
        Return True when the query shape suggests entity connections could add value.

        Keep this conservative: named concepts, acronyms, domains, quoted phrases,
        and explicit connection/comparison language still get entity extraction.
        """
        if re.search(r'"[^"]+"|\'[^\']+\'', query):
            return True

        if re.search(r"\b[\w.-]+\.[a-zA-Z]{2,}\b", query):
            return True

        if re.search(r"\b[A-Z]{2,}s?\b", query):
            return True

        if re.search(r"\b[A-Z][\w-]+(?:\s+[A-Z][\w-]+)+\b", query):
            return True

        connection_words = (
            " clash ", " connect ", " connection ", " connections ", " relate ",
            " related ", " compare ", " contrast ", " between ", " versus ",
            " vs ",
        )
        query_lower = f" {query.lower()} "
        return any(word in query_lower for word in connection_words)

    def _should_extract_query_entities(
        self,
        query: str,
        memories: List[Dict],
        temporal_context: Optional[str],
    ) -> bool:
        """
        Decide whether to spend an LLM call extracting entities for chat context.

        Entity extraction is still used when retrieval is weak or the query looks
        entity/connection-heavy. Generic questions with enough retrieved context
        can skip this helper call without removing entity-based search as a feature.
        """
        if not self.client:
            return False

        if self._query_likely_benefits_from_entities(query):
            return True

        # Temporal searches already constrain context by date; run entities only if
        # the timeframe search did not find enough to work with.
        minimum_results = 5 if temporal_context else 8
        return len(memories) < minimum_results
    
    def enhanced_chat_response(
        self,
        query: str,
        user_id: str,
        current_model: str,
        update_global_state=None,
        status_callback=None,
    ) -> Dict[str, Any]:
        """
        Generate an enhanced chat response that combines multiple intelligence sources
        
        Returns:
            {
                'response': str,           # Main AI response
                'sources': List[Dict],     # Detailed source attribution
                'patterns': List[str],     # User patterns identified
                'connections': List[Dict], # Cross-memory connections found
                'suggestions': List[str]   # Follow-up suggestions
            }
        """
        
        start_time = time.perf_counter()

        def _set_status(message: str) -> None:
            if status_callback:
                status_callback(message)

        # Step 0: Check for structured data queries that should use command logic
        _set_status("🧠 Checking what kind of question this is...")
        structured_response = self._check_for_structured_query(query, user_id)
        if structured_response:
            return structured_response
        
        # Step 1: Multi-layered context gathering
        _set_status("🔍 Searching your memories...")
        t0 = time.perf_counter()
        context_data = self._gather_comprehensive_context(query, user_id)
        _debug_timing(f"Context gather: {(time.perf_counter() - t0):.2f}s")

        memory_count = len(context_data.get('memories', []))
        connection_count = len(context_data.get('entity_connections', []))
        if connection_count:
            _set_status(f"🔗 Found {memory_count} relevant memories and {connection_count} connections...")
        else:
            _set_status(f"🧭 Reading {memory_count} relevant memories...")
        
        # Step 2: Analyze user patterns and preferences  
        if memory_count:
            _set_status(f"🧭 Reading {memory_count} relevant memories...")
        else:
            _set_status("🧭 Reading the surrounding context...")
        t0 = time.perf_counter()
        user_patterns = self._identify_user_patterns(context_data['memories'], user_id)
        _debug_timing(f"Pattern analysis: {(time.perf_counter() - t0):.2f}s")
        
        # Step 2.5: Detect user intent for response mode
        _set_status("🎚️ Choosing response style...")
        t0 = time.perf_counter()
        intent = self._detect_intent(query)
        _debug_timing(f"Intent detection: {(time.perf_counter() - t0):.2f}s")
        
        # Step 3: Generate enhanced response with AI knowledge synthesis
        _set_status("💭 Writing the reply...")
        t0 = time.perf_counter()
        response = self._generate_enhanced_response(
            query, context_data, user_patterns, current_model, intent, user_id=user_id
        )
        _debug_timing(f"LLM response: {(time.perf_counter() - t0):.2f}s")
        
        # Step 4: Prepare explorable references for the follow-up card
        _set_status("🔗 Preparing explorable references...")
        t0 = time.perf_counter()
        response_with_refs = self._prepare_exploration_references(response, context_data, intent)
        _debug_timing(f"Reference preparation: {(time.perf_counter() - t0):.2f}s")
        
        # Step 5: Generate follow-up suggestions
        _set_status("✨ Preparing follow-ups...")
        t0 = time.perf_counter()
        suggestions = self._generate_follow_up_suggestions(query, context_data, user_patterns)
        _debug_timing(f"Suggestions: {(time.perf_counter() - t0):.2f}s")
        
        # Step 6: Store AI response globally for potential saving
        if update_global_state:
            update_global_state(response_with_refs, "chat", query)

        _debug_timing(f"Total enhanced_chat_response: {(time.perf_counter() - start_time):.2f}s")
        
        return {
            'response': response_with_refs,
            'sources': context_data['source_attribution'],
            'patterns': user_patterns,
            'connections': context_data['entity_connections'],
            'suggestions': suggestions
        }

    def _gather_comprehensive_context(self, query: str, user_id: str) -> Dict[str, Any]:
        """
        Gather context using multiple strategies:
        1. Semantic search (existing)
        2. Entity-based connections
        3. Temporal analysis if applicable
        4. Cross-content pattern matching
        """
        memory_count = self.db.get_database_stats(user_id)["total_memories"]
        retrieval_limits = resolve_chat_retrieval_limits(memory_count)

        # 1. Semantic search (existing approach)
        temporal_context = None
        temporal_start_date = None
        temporal_end_date = None
        query_without_temporal = None
        try:
            t0 = time.perf_counter()
            from .temporal import extract_temporal_intent
            temporal_intent = extract_temporal_intent(query, client=self.client) or {}
            _debug_timing(
                "context.temporal_intent: "
                f"{(time.perf_counter() - t0):.2f}s has_temporal={temporal_intent.get('has_temporal_intent')} "
                f"start={temporal_intent.get('start_date')} end={temporal_intent.get('end_date')}"
            )
            
            if temporal_intent.get('has_temporal_intent', False) and temporal_intent.get('start_date'):
                query_without_temporal = temporal_intent.get('query_without_temporal', query)
                temporal_start_date = temporal_intent.get('start_date')
                temporal_end_date = temporal_intent.get('end_date')
                t0 = time.perf_counter()
                semantic_memories = self.db.search_by_timeframe(
                    user_id, 
                    query=query_without_temporal if query_without_temporal.strip() else None,
                    start_date=temporal_start_date,
                    end_date=temporal_end_date,
                    k=CHAT_SEARCH_K
                )
                _debug_timing(
                    "context.timeframe_search: "
                    f"{(time.perf_counter() - t0):.2f}s results={len(semantic_memories)} "
                    f"user_id={user_id} query_without_temporal={query_without_temporal!r} "
                    f"start={temporal_start_date} end={temporal_end_date}"
                )
                temporal_context = temporal_intent.get('temporal_context', 'time period')
            else:
                # Use hybrid search: combine semantic + keyword search
                t0 = time.perf_counter()
                semantic_memories = self._hybrid_search(
                    user_id,
                    query,
                    k=retrieval_limits["search_k"],
                    internal_multiplier=retrieval_limits["internal_multiplier"],
                )
                _debug_timing(f"context.hybrid_search: {(time.perf_counter() - t0):.2f}s results={len(semantic_memories)}")
        except Exception as e:
            _debug_timing(f"context.temporal_or_search_error: {type(e).__name__}: {e}")
            t0 = time.perf_counter()
            semantic_memories = self._hybrid_search(
                user_id,
                query,
                k=retrieval_limits["search_k"],
                internal_multiplier=retrieval_limits["internal_multiplier"],
            )
            _debug_timing(f"context.hybrid_search_fallback: {(time.perf_counter() - t0):.2f}s results={len(semantic_memories)}")
            temporal_context = None
            temporal_start_date = None
            temporal_end_date = None
            query_without_temporal = None

        semantic_memories = [
            mem for mem in semantic_memories
            if not self._is_ai_derived_memory(mem)
        ]

        # Extract entities only when the query/retrieval suggests they are useful.
        query_entities = []
        should_extract_entities = self._should_extract_query_entities(query, semantic_memories, temporal_context)
        _debug_timing(
            "context.entity_extraction_gate: "
            f"should_extract={should_extract_entities} results={len(semantic_memories)} "
            f"temporal={bool(temporal_context)}"
        )
        if should_extract_entities:
            try:
                t0 = time.perf_counter()
                entities = extract_structured_entities(query, client=self.client)
                _debug_timing(f"context.entity_extraction: {(time.perf_counter() - t0):.2f}s")
                if entities:
                    query_entities = entities
            except Exception as e:
                _debug_timing(f"context.entity_extraction_error: {type(e).__name__}: {e}")
                pass
        
        # 2. Entity-based connections if we found entities
        entity_memories = []
        entity_connections = []
        if query_entities:
            try:
                t0 = time.perf_counter()
                entity_results = self.db.find_entity_connections(query_entities, user_id, k=ENTITY_SEARCH_LIMIT)
                entity_results = [
                    (mem, shared_entities)
                    for mem, shared_entities in entity_results
                    if not self._is_ai_derived_memory(mem)
                ]
                _debug_timing(f"context.entity_connections: {(time.perf_counter() - t0):.2f}s results={len(entity_results)}")
                entity_memories = [mem for mem, shared_entities in entity_results]
                entity_connections = entity_results
            except Exception as e:
                _debug_timing(f"context.entity_connections_error: {type(e).__name__}: {e}")
                pass
        
        # 3. Combine and deduplicate memories
        all_memories = []
        seen_ids = set()

        def _memory_dedupe_key(mem: Dict) -> Any:
            memory_id = mem.get('id')
            if memory_id is not None:
                return ('id', memory_id)
            return (
                'content',
                mem.get('content'),
                mem.get('timestamp'),
                mem.get('command_type'),
            )
        
        # Add primary retrieval results first (highest priority)
        primary_source_type = 'timeframe' if temporal_context else 'semantic'
        for mem in semantic_memories:
            dedupe_key = _memory_dedupe_key(mem)
            if dedupe_key not in seen_ids:
                mem['source_type'] = primary_source_type
                all_memories.append(mem)
                seen_ids.add(dedupe_key)
        
        # Add entity results that aren't duplicates
        for mem in entity_memories:
            dedupe_key = _memory_dedupe_key(mem)
            if dedupe_key not in seen_ids:
                mem['source_type'] = 'entity'
                all_memories.append(mem)
                seen_ids.add(dedupe_key)

        # 4. Build source attribution
        t0 = time.perf_counter()
        source_attribution = self._build_source_attribution(all_memories, temporal_context)
        _debug_timing(f"context.source_attribution: {(time.perf_counter() - t0):.2f}s")
        
        return {
            'memories': all_memories,
            'query_entities': query_entities,
            'entity_connections': entity_connections,
            'temporal_context': temporal_context,
            'temporal_start_date': temporal_start_date,
            'temporal_end_date': temporal_end_date,
            'query_without_temporal': query_without_temporal,
            'source_attribution': source_attribution,
            'chat_context_limit': retrieval_limits["context_limit"],
        }
    
    def _identify_user_patterns(self, memories: List[Dict], user_id: str) -> List[str]:
        """
        Analyze user's thinking patterns and preferences from their memories
        """
        patterns = []
        
        if not memories:
            return patterns
        
        # Analyze content types and preferences
        content_types = {}
        technologies = {}
        thinking_words = {}
        
        for mem in memories:
            # Content type patterns
            cmd_type = mem.get('command_type', 'unknown')
            content_types[cmd_type] = content_types.get(cmd_type, 0) + 1
            
            # Extract entities and count them
            metadata = mem.get('metadata')
            if metadata:
                try:
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    entities = metadata.get('entities', [])
                    for entity in entities:
                        if entity.startswith('Technology:') or entity.startswith('Tool:'):
                            tech_name = entity.split(':', 1)[1].strip()
                            technologies[tech_name] = technologies.get(tech_name, 0) + 1
                except:
                    pass
            
            # Analyze language patterns (thinking style indicators)
            content = mem.get('content', '').lower()
            thinking_indicators = ['simple', 'complex', 'elegant', 'minimal', 'powerful', 'clean']
            for indicator in thinking_indicators:
                if indicator in content:
                    thinking_words[indicator] = thinking_words.get(indicator, 0) + 1
        
        # Generate pattern insights
        if content_types:
            most_common_type = max(content_types, key=content_types.get)
            patterns.append(f"Prefers {most_common_type} content ({content_types[most_common_type]} examples)")
        
        if technologies:
            top_techs = sorted(technologies.items(), key=lambda x: x[1], reverse=True)[:3]
            tech_list = [f"{tech} ({count})" for tech, count in top_techs]
            patterns.append(f"Most mentioned technologies: {', '.join(tech_list)}")
        
        if thinking_words:
            top_words = sorted(thinking_words.items(), key=lambda x: x[1], reverse=True)[:2]
            if top_words:
                patterns.append(f"Thinking style: values {', '.join([word for word, _ in top_words])}")
        
        return patterns
    
    def _generate_enhanced_response(
        self,
        query: str,
        context_data: Dict,
        patterns: List[str],
        model: str,
        intent: str = 'standard',
        user_id: Optional[str] = None,
    ) -> str:
        """
        Generate enhanced response using comprehensive context and AI knowledge synthesis
        """
        
        # Build rich context prompt
        context_prompt = self._build_context_prompt(context_data, patterns)
        
        # Generate system prompt based on detected intent
        system_prompt = get_system_prompt(intent)
        
        use_online = intent == 'research'

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context_prompt}
        ]
        messages.append({"role": "user", "content": f"User question: {query}"})

        try:
            if use_online:
                result = complete_online(self.client, model, messages)
                response_content = result.text
                logged_model = result.model
            else:
                response_content = complete(self.client, model, messages)
                logged_model = model

            prompt_memories = [
                {
                    "prompt_index": index,
                    "id": mem.get('id'),
                    "source_type": mem.get('source_type'),
                    "timestamp": mem.get('timestamp'),
                }
                for index, mem in enumerate(
                    context_data.get('memories', [])[
                        :context_data.get('chat_context_limit', CHAT_CONTEXT_LIMIT)
                    ],
                    1,
                )
            ]

            # Log the interaction
            log_llm_interaction(
                model=logged_model,
                messages=messages,
                response=response_content,
                function_name="enhanced_chat_response",
                metadata={
                    "intent": intent,
                    "query": query,
                    "user_id": user_id,
                    "num_memories": len(context_data.get('memories', [])),
                    "num_prompt_memories": len(prompt_memories),
                    "temporal_context": context_data.get('temporal_context'),
                    "start_date": context_data.get('temporal_start_date'),
                    "end_date": context_data.get('temporal_end_date'),
                    "query_without_temporal": context_data.get('query_without_temporal'),
                    "prompt_memories": prompt_memories,
                }
            )

            return response_content
        except Exception as e:
            return f"Error generating response: {str(e)}"
    
    def _build_context_prompt(self, context_data: Dict, patterns: List[str]) -> str:
        """
        Build comprehensive context prompt for the AI with smart content truncation.

        Uses ai_summary for long content and saved AI responses to dramatically
        reduce token usage while preserving key signal. Short content is shown in full.
        Entity connections are deduplicated to avoid repeating memories already shown.
        """
        from mentat.core.config import ENTITY_CONNECTION_PREVIEW_LENGTH

        prompt = "**USER'S PERSONAL CONTEXT:**\n\n"

        # Add user patterns
        if patterns:
            prompt += "**Thinking Patterns & Preferences:**\n"
            for pattern in patterns:
                prompt += f"- {pattern}\n"
            prompt += "\n"

        # Add temporal context if available
        is_temporal_query = bool(context_data.get('temporal_context'))
        if is_temporal_query:
            memory_count = len(context_data.get('memories', []))
            memory_noun = "memory was" if memory_count == 1 else "memories were"
            prompt += f"**Time Context:** {context_data['temporal_context']}\n\n"
            prompt += "**Temporal Grounding Rules:**\n"
            prompt += "- This is a temporal retrospective. Answer only from the listed memories for this time period.\n"
            prompt += "- Cite memory numbers and dates inline for factual claims; use this exact format instead of bare memory references: (Memory 1, 2026-06-25).\n"
            prompt += "- Preserve uncertainty and hedging from source memories; do not turn maybe/probably/might/seems into certainty.\n"
            prompt += "- Do not invent projects, events, dates, people, plans, or details that are not explicitly supported by the listed memories.\n"
            prompt += f"- Only {memory_count} {memory_noun} found for this timeframe; state that limitation and treat sparse evidence as incomplete rather than filling gaps.\n"
            prompt += "- If the memories do not answer the question, say the evidence is insufficient.\n\n"

        # Track seen memory IDs to avoid duplication in entity connections
        seen_memory_ids = set()

        # Add memories with SMART TRUNCATION (uses ai_summary for long content)
        if context_data['memories']:
            prompt += "**Relevant Memories:**\n"
            for i, mem in enumerate(
                context_data['memories'][
                    :context_data.get('chat_context_limit', CHAT_CONTEXT_LIMIT)
                ],
                1,
            ):
                seen_memory_ids.add(mem.get('id'))

                # Use smart content formatting (summary/truncation for long content)
                content_display = self._format_memory_content(mem)

                tags = ', '.join(mem.get('tags', []))
                timestamp = mem.get('timestamp', 'Unknown date')
                source_type = mem.get('source_type', 'semantic')

                # Check if this is a saved AI response for labeling
                source_attribution = ""
                metadata = mem.get('metadata')
                if metadata:
                    try:
                        if isinstance(metadata, str):
                            metadata = json.loads(metadata)
                        source_info = metadata.get('source', {})
                        if source_info.get('type') == 'ai_response':
                            model_name = source_info.get('model', 'AI')
                            source_attribution = f" [AI RESPONSE from {model_name}]"
                    except:
                        pass

                prompt += f"{i}. [{mem.get('command_type', '').upper()}] {timestamp} ({source_type} match):{source_attribution}"
                if tags:
                    prompt += f" (tags: {tags})"
                prompt += f"\n  {content_display}\n\n"

        # Add entity connections with SHORTER previews and DEDUPLICATION
        if context_data.get('entity_connections'):
            # Filter out already-seen memories to avoid duplication
            unique_connections = [
                (mem, entities) for mem, entities in context_data['entity_connections']
                if mem.get('id') not in seen_memory_ids
            ]

            if unique_connections:
                prompt += "\n**Entity Connections Found:**\n"
                for mem, shared_entities in unique_connections[:3]:  # Show top 3 unique
                    shared_str = ", ".join(shared_entities[:3])  # Limit entities shown
                    # Use shorter preview for entity connections
                    content_preview = self._format_memory_content(
                        mem,
                        max_length=ENTITY_CONNECTION_PREVIEW_LENGTH
                    )
                    prompt += f"- Connected by: {shared_str}\n  {content_preview}\n\n"

        if not context_data['memories']:
            if is_temporal_query:
                prompt += "- No memories were found for this timeframe. Say that the retrieved evidence is insufficient; do not use general knowledge to infer what happened.\n"
            else:
                prompt += "- No specific relevant memories found. Use general knowledge and encourage exploration.\n"

        return prompt
    
    def _prepare_exploration_references(self, response: str, context_data: Dict, intent: str = 'standard') -> str:
        """
        Populate /view and /explore references from already-gathered context.

        The response text is intentionally left unchanged. Numbered concepts are
        shown in the follow-up card after the chat, which avoids brittle inline
        mutation while preserving explorable references.
        """
        self.clear_references()

        # Quick mode should stay terse and avoid follow-up reference work.
        if intent == 'quick':
            _debug_timing(f"Skipping exploration references - intent='{intent}'")
            return response

        candidates = self._build_exploration_reference_candidates(context_data)
        _debug_timing(f"Prepared {len(candidates)} exploration references: {[c['topic'] for c in candidates]}")

        for candidate in candidates:
            self.add_reference(
                topic=candidate['topic'],
                context=candidate['context'],
                personal_context=candidate.get('personal_context', '')
            )

        return response

    def _build_exploration_reference_candidates(self, context_data: Dict) -> List[Dict[str, str]]:
        """
        Build explorable reference topics from retrieval context instead of a post-answer LLM call.
        """
        candidates = []
        seen = set()

        def add_candidate(topic: Any, context: str, personal_context: str = "", priority: int = 0) -> None:
            normalized_topic = self._normalize_reference_topic(topic)
            if not normalized_topic:
                return

            key = normalized_topic.lower()
            if key in seen:
                return

            seen.add(key)
            candidates.append({
                'topic': normalized_topic,
                'context': context,
                'personal_context': personal_context,
                'priority': priority
            })

        query_entities = context_data.get('query_entities') or {}
        entity_priority = {
            'concepts': 100,
            'projects': 90,
            'technologies': 80,
            'organizations': 70,
            'people': 60,
            'locations': 40,
            'dates': 30,
        }

        if isinstance(query_entities, dict):
            for category, entities in query_entities.items():
                if not isinstance(entities, list):
                    continue
                priority = entity_priority.get(category, 50)
                category_label = category[:-1] if category.endswith('s') else category
                for entity in entities:
                    add_candidate(
                        entity,
                        f"{category_label.title()} from the user question",
                        priority=priority
                    )
        elif isinstance(query_entities, list):
            for entity in query_entities:
                add_candidate(entity, "Entity from the user question", priority=80)

        tag_counts = {}
        tag_context = {}
        tag_first_seen = {}
        for memory_index, mem in enumerate(
            context_data.get('memories', [])[
                :context_data.get('chat_context_limit', CHAT_CONTEXT_LIMIT)
            ]
        ):
            for tag in mem.get('tags') or []:
                normalized_tag = self._normalize_reference_topic(tag)
                if not normalized_tag:
                    continue
                key = normalized_tag.lower()
                tag_counts[key] = tag_counts.get(key, 0) + 1
                tag_first_seen.setdefault(key, memory_index)
                tag_context.setdefault(
                    key,
                    {
                        'topic': normalized_tag,
                        'context': 'Tag from retrieved memories',
                        'personal_context': f"Appears in retrieved {mem.get('command_type', 'memory')} from {mem.get('timestamp', 'unknown date')}",
                    }
                )

        ranked_tags = sorted(
            tag_context.items(),
            key=lambda item: (-tag_counts[item[0]], tag_first_seen[item[0]], item[1]['topic'])
        )
        for key, tag_data in ranked_tags:
            add_candidate(
                tag_data['topic'],
                tag_data['context'],
                tag_data['personal_context'],
                priority=40 + tag_counts[key]
            )

        for mem, shared_entities in context_data.get('entity_connections') or []:
            for entity in shared_entities[:2]:
                add_candidate(
                    entity,
                    'Shared entity from connected memories',
                    f"Connected through {mem.get('command_type', 'memory')} from {mem.get('timestamp', 'unknown date')}",
                    priority=35
                )

        candidates.sort(key=lambda item: item['priority'], reverse=True)
        return candidates[:MAX_TOTAL_REFERENCES]

    def _normalize_reference_topic(self, topic: Any) -> Optional[str]:
        if not topic:
            return None

        text = str(topic).strip()
        if ':' in text and text.split(':', 1)[0].lower() in {
            'person', 'people', 'organization', 'organizations', 'technology',
            'technologies', 'project', 'projects', 'concept', 'concepts',
            'location', 'locations', 'date', 'dates', 'tool', 'tools'
        }:
            text = text.split(':', 1)[1].strip()

        text = text.strip('#').strip()
        text = text.replace('_', ' ').replace('-', ' ')
        text = ' '.join(text.split())

        if len(text) < 3:
            return None

        generic_topics = {
            'note', 'notes', 'capture', 'captures', 'reflection', 'reflections',
            'idea', 'ideas', 'question', 'questions', 'task', 'tasks', 'todo',
            'todos', 'link', 'links', 'research', 'summary'
        }
        if text.lower() in generic_topics:
            return None

        return text
    
    def _check_for_structured_query(self, query: str, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Check if query should use structured command logic instead of AI interpretation
        """
        query_lower = query.lower().strip()
        
        # Todo queries should use rich structured data like /todo command
        if any(pattern in query_lower for pattern in ['my todos', 'my todo', 'todo list', 'todos', 'actionable items']):
            return self._generate_structured_todo_response(user_id)
        
        return None
    
    def _generate_structured_todo_response(self, user_id: str) -> Dict[str, Any]:
        """
        Generate rich, analytical todo response with /view integration
        """
        try:
            # Use the same method as /todo command
            todos = self.db.get_user_todos(user_id)
            
            if todos:
                # Analyze todo patterns for personalized insights
                analysis = self._analyze_todo_patterns(todos)
                
                # Build analytical response
                response = f"**Looking at your {len(todos)} todos, I notice some interesting patterns:**\n\n"
                response += f"{analysis['insight']}\n\n"
                response += "**Your current todos:**\n"
                for i, todo in enumerate(todos, 1):
                    response += f"{i}. {todo['action']} (Priority: {todo['priority']})\n"
                
                response += "\n💡 Use `/view <number>` to explore the context behind specific todos."
                
                # Convert todos to viewable format with rich source context
                viewable_todos = []
                for todo in todos:
                    # Create rich viewable item that shows the source context
                    viewable_content = f"**Todo:** {todo['action']}\n\n"
                    viewable_content += f"**Original Context:**\n{todo.get('source_content', 'No source context available')}"
                    
                    if todo.get('context'):
                        viewable_content += f"\n\n**Additional Context:** {todo['context']}"
                    
                    viewable_todos.append({
                        'id': f"todo_{len(viewable_todos)}",
                        'content': viewable_content,
                        'command_type': 'todo',
                        'tags': todo.get('tags', []) + [todo['priority']],
                        'timestamp': todo.get('timestamp', 'Unknown'),
                        'metadata': todo.get('source_content', '')[:100] + '...' if todo.get('source_content') else ''
                    })
                
                return {
                    'response': response,
                    'sources': [{
                        'type': 'structured_data',
                        'description': f'Todo analysis of {len(todos)} actionable items',
                        'count': len(todos)
                    }],
                    'patterns': [analysis['pattern_summary']],
                    'connections': [],
                    'suggestions': analysis['suggestions'],
                    'viewable_items': viewable_todos  # For /view integration
                }
            else:
                return {
                    'response': "No pending todos found in your memories. Todos are automatically extracted from content you capture with `/capture`.",
                    'sources': [{
                        'type': 'structured_data', 
                        'description': 'Todo extraction scan',
                        'count': 0
                    }],
                    'patterns': [],
                    'connections': [],
                    'suggestions': [
                        'Try `/capture` with actionable content to create todos',
                        'Use `/search` to find task-related memories'
                    ]
                }
                
        except Exception as e:
            # Fallback to regular enhanced chat if todo extraction fails
            return None
    
    def _analyze_todo_patterns(self, todos: List[Dict]) -> Dict[str, Any]:
        """
        Analyze todo patterns to provide personalized insights
        """
        if not todos:
            return {'insight': '', 'pattern_summary': '', 'suggestions': []}
        
        # Categorize todos
        categories = {
            'learning': ['read', 'learn', 'study', 'research'],
            'entertainment': ['play', 'game', 'watch', 'listen'],
            'productivity': ['install', 'setup', 'organize', 'balance'],
            'social': ['engagement', 'connect', 'share', 'collaborate'],
            'technical': ['checkout', 'code', 'build', 'deploy']
        }
        
        todo_categories = {cat: 0 for cat in categories}
        for todo in todos:
            action_lower = todo['action'].lower()
            for category, keywords in categories.items():
                if any(keyword in action_lower for keyword in keywords):
                    todo_categories[category] += 1
                    break
        
        # Generate insights
        top_categories = sorted(todo_categories.items(), key=lambda x: x[1], reverse=True)
        active_categories = [cat for cat, count in top_categories if count > 0]
        
        if len(active_categories) >= 3:
            insight = f"You're balancing {len(active_categories)} different areas: {', '.join(active_categories[:3])}. This shows a well-rounded approach to personal growth."
        elif len(active_categories) == 2:
            insight = f"Your focus is split between {active_categories[0]} and {active_categories[1]}, suggesting you value both growth and enjoyment."
        elif len(active_categories) == 1:
            insight = f"You're currently focused on {active_categories[0]} activities - a clear area of priority right now."
        else:
            insight = "Your todos show a diverse mix of interests and responsibilities."
        
        # Priority analysis
        priorities = [todo['priority'] for todo in todos]
        priority_dist = {p: priorities.count(p) for p in set(priorities)}
        
        if priority_dist.get('high', 0) > 0:
            insight += f" You have {priority_dist['high']} high-priority items that need immediate attention."
        elif priority_dist.get('medium', 0) == len(todos):
            insight += " All items are medium priority - consider which deserve more urgent focus."
        
        pattern_summary = f"Balanced across {len(active_categories)} categories: {', '.join(active_categories)}"
        
        suggestions = [
            f"Consider prioritizing your {active_categories[0]} todos first" if active_categories else "Add more specific deadlines to your todos",
            "Use /synthesize to group related todos into projects",
            "Try time-blocking similar todos together"
        ]
        
        return {
            'insight': insight,
            'pattern_summary': pattern_summary,
            'suggestions': suggestions
        }
    
    def _generate_follow_up_suggestions(self, query: str, context_data: Dict, patterns: List[str]) -> List[str]:
        """
        Generate thoughtful follow-up suggestions based on the conversation
        """
        suggestions = []
        
        # Entity-based suggestions
        if context_data.get('query_entities'):
            entities = context_data['query_entities']
            if isinstance(entities, list) and entities:
                for entity in entities[:2]:  # Top 2 entities
                    if isinstance(entity, str) and ':' in entity:
                        entity_name = entity.split(':', 1)[-1].strip()
                        suggestions.append(f"Explore all work related to {entity_name}")
        
        # Pattern-based suggestions
        if any('Technology:' in str(mem.get('metadata', '')) for mem in context_data['memories']):
            suggestions.append("Compare your technology choices and evolution")
        
        # Temporal suggestions
        if not context_data.get('temporal_context'):
            suggestions.append("Try asking about this topic from a specific time period")
        
        # General exploration
        suggestions.append("Use /synthesize to combine related notes into a structured document")
        
        return suggestions[:3]  # Limit to 3 suggestions
    
    def _build_source_attribution(self, memories: List[Dict], temporal_context: Optional[str]) -> List[Dict]:
        """
        Build detailed source attribution for transparency
        """
        attribution = []
        
        if temporal_context:
            attribution.append({
                'type': 'temporal',
                'description': f"Time-based search: {temporal_context}",
                'count': len([m for m in memories if m.get('source_type') == 'timeframe'])
            })
        
        semantic_count = len([m for m in memories if m.get('source_type') == 'semantic'])
        if semantic_count > 0:
            attribution.append({
                'type': 'semantic',
                'description': f"Semantic similarity matches",
                'count': semantic_count
            })
        
        entity_count = len([m for m in memories if m.get('source_type') == 'entity'])
        if entity_count > 0:
            attribution.append({
                'type': 'entity',
                'description': f"Entity-based connections",
                'count': entity_count
            })
        
        return attribution
    
    def _detect_intent(self, query: str) -> str:
        """
        Detect user intent from query patterns to determine response mode
        """
        query_lower = query.lower().strip()
        word_count = len(query_lower.split())
        
        # Personal/Memory queries - these should use standard enhanced chat
        personal_patterns = [
            'my todos', 'my thoughts', 'what do i think', 'my work on', 'my projects',
            'my notes on', 'what did i', 'when did i', 'show me my', 'my ideas about',
            'how does my', 'my current', 'my recent', 'connections between my',
            'relate to my', 'similar to my', 'my perspective on', 'my essays',
            'my captures', 'my memories', 'my links', 'my new', 'my latest',
            'my essay', 'my writing', 'my project', 'my ideas', 'my research',
            'my note', 'my work', 'my capture'
        ]
        
        # Quick mode patterns - explicit brevity requests
        explicit_quick_patterns = [
            'quick', 'brief', 'briefly', 'just tell me', 'simple', 'short answer',
            'tldr', 'in short', 'keep it brief'
        ]
        # Definition-style prompts should only be quick when they are short and non-personal.
        definition_patterns = ['what is', 'what are', 'define']
        
        # Research mode patterns  
        research_patterns = [
            'deep dive', 'full picture', 'research', 'comprehensive', 
            'everything about', 'let\'s go deep', 'tell me all about',
            'complete analysis', 'thorough', 'detailed study', 'go deep'
        ]
        
        # Decision mode patterns
        decision_patterns = [
            'should i', 'help me choose', 'what do you think', 
            'pros and cons', 'compare', 'which is better',
            'recommend', 'suggestion', 'advice', 'decide between',
            'better for', 'best for', 'vs ', ' or '
        ]
        
        # Explore mode patterns
        explore_patterns = [
            'i\'m thinking about', 'considering', 'help me understand',
            'explain more', 'break down', 'explore', 'dive into'
        ]

        personal_markers = [
            " my ",
            " i ",
            " me ",
            " mine ",
            " my ",
            " i'm ",
            " i've ",
            " i'd ",
        ]
        padded_query = f" {query_lower} "
        has_personal_marker = any(marker in padded_query for marker in personal_markers)
        
        # Check patterns in order of priority
        # 1. Check for explicit mode requests first (these override everything)
        if any(pattern in query_lower for pattern in research_patterns):
            return 'research'
        elif any(pattern in query_lower for pattern in decision_patterns):
            return 'decision'
        elif any(pattern in query_lower for pattern in explore_patterns):
            return 'explore'
        # 2. Personal queries use standard mode (checked before quick mode to avoid conflicts)
        elif any(pattern in query_lower for pattern in personal_patterns):
            return 'standard'
        # 3. Explicit quick/brevity requests.
        elif any(pattern in query_lower for pattern in explicit_quick_patterns):
            return 'quick'
        # 4. Short definition prompts only (e.g., "what is Rust?").
        elif (
            any(pattern in query_lower for pattern in definition_patterns)
            and not has_personal_marker
            and word_count <= 8
        ):
            return 'quick'

        return 'standard'  # Default to existing enhanced chat behavior
    
    def add_reference(self, topic: str, context: str, personal_context: str = None) -> str:
        """
        Add a numbered reference for later exploration via /view
        """
        ref_id = str(self.reference_counter)
        self.session_references[ref_id] = {
            'topic': topic,
            'context': context,
            'personal_context': personal_context,
            'timestamp': datetime.now()
        }
        self.reference_counter += 1
        return f"[{ref_id}]"
    
    def get_reference(self, ref_id: str) -> Optional[Dict]:
        """
        Retrieve reference by ID for /view command
        """
        if ref_id and ref_id.startswith("[") and ref_id.endswith("]"):
            ref_id = ref_id[1:-1]
        return self.session_references.get(ref_id)
    
    def clear_references(self):
        """
        Clear session references (useful for new chat sessions)
        """
        self.session_references = {}
        self.reference_counter = 1

    def _format_memory_content(self, mem: Dict, max_length: int = None) -> str:
        """
        Smart content formatting for chat context injection.

        Reduces token usage by intelligently choosing between full content,
        ai_summary, or truncated content based on content characteristics.

        Strategy:
        1. If content is short (< threshold), return full content
        2. If saved AI response, always use ai_summary (they're huge)
        3. If ai_summary available and content is long, use summary
        4. Otherwise, truncate with standardize_truncation

        Parameters:
            mem (Dict): Memory dictionary with 'content' and optional 'metadata'
            max_length (int): Override for truncation length (uses config default if None)

        Returns:
            str: Formatted content string ready for prompt injection
        """
        from mentat.core.config import (
            CHAT_CONTENT_TRUNCATION_LENGTH,
            CHAT_USE_SUMMARY_FOR_AI_RESPONSES
        )
        from mentat.core.utils import standardize_truncation

        max_len = max_length or CHAT_CONTENT_TRUNCATION_LENGTH
        content = mem.get('content', '')
        metadata = mem.get('metadata')

        # Parse metadata if string
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}
        elif metadata is None:
            metadata = {}

        # Check if this is a saved AI response
        source_info = metadata.get('source', {})
        is_ai_response = source_info.get('type') == 'ai_response'

        # Get ai_summary if available
        ai_summary = metadata.get('ai_summary', '')

        # Strategy 1: Short content - show in full
        if len(content) <= max_len:
            return content.replace('\n', '\n  ')

        # Strategy 2: AI responses - always use summary (they're typically 2000-4000+ chars)
        if is_ai_response and ai_summary and CHAT_USE_SUMMARY_FOR_AI_RESPONSES:
            return f"[AI Response Summary] {ai_summary}"

        # Strategy 3: Long content with summary - use summary
        if ai_summary and len(ai_summary) > 20:
            return f"[Summary] {ai_summary}"

        # Strategy 4: Fallback - truncate content intelligently
        truncated = standardize_truncation(content, max_len)
        return truncated.replace('\n', '\n  ') + "..."

    def generate_reference_explanation(self, reference: Dict, user_id: str, current_model: str) -> str:
        """
        Generate a comprehensive explanation for an AI reference with web search and personal context
        
        Args:
            reference: Reference dictionary with 'topic', 'context', 'personal_context'
            user_id: User identifier for personal context retrieval
            current_model: Model to use for explanation generation
            
        Returns:
            Formatted explanation string with markdown
        """
        topic = reference['topic']
        context = reference['context']
        personal_context = reference.get('personal_context', '')
        
        # Search for personal memories related to this topic
        personal_memories = self.db.comprehensive_search(user_id, topic)[:3]
        
        # Build the explanation prompt
        system_prompt = f"""You are providing a focused, comprehensive explanation of a concept the user wants to explore.

Topic: {topic}
Context: {context}
Personal Context: {personal_context}

Provide a detailed explanation that includes:
1. What it is and why it matters
2. Key concepts and practical applications  
3. How it relates to the user's interests and work (based on personal context)
4. Actionable next steps or resources

Use markdown formatting for headers, lists, and emphasis. Be thorough but accessible."""

        # Include personal memories if found (full content)
        memory_context = ""
        if personal_memories:
            memory_context = "\n\nPersonal context from your memories:\n"
            for memory in personal_memories[:2]:  # Top 2 most relevant memories
                # comprehensive_search returns dictionaries with keys
                content = memory.get('content', '') if isinstance(memory, dict) else str(memory)
                memory_context += f"- {content}\n\n"
        
        try:
            # Generate comprehensive explanation
            result = complete_online(
                self.client,
                current_model,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Provide a comprehensive explanation of {topic} in the context of {context}.{memory_context}"}
                ],
                max_tokens=1500,
                temperature=0.3
            )
            
            explanation = result.text.strip()
            
            # Add personal connection section if memories were found (full content)
            if personal_memories:
                explanation += f"\n\n## 🔗 Your Connection to {topic}\n\n"
                explanation += f"Found {len(personal_memories)} related memories in your knowledge base:\n\n"
                for i, memory in enumerate(personal_memories[:2], 1):
                    # comprehensive_search returns dictionaries with keys
                    if isinstance(memory, dict):
                        content_full = memory.get('content', '')
                        timestamp = memory.get('timestamp', 'Unknown date')[:10]
                    else:
                        content_full = str(memory)
                        timestamp = 'Unknown date'
                    explanation += f"{i}. *{timestamp}*:\n{content_full}\n\n"
            
            return explanation
            
        except Exception as e:
            # Fallback to basic explanation without web search
            fallback_model = current_model.replace(':online', '')
            try:
                explanation = complete(
                    self.client,
                    fallback_model,
                    [
                        {"role": "system", "content": system_prompt.replace("comprehensive", "focused")},
                        {"role": "user", "content": f"Explain {topic} in the context of {context}.{memory_context}"}
                    ],
                    max_tokens=800,
                    temperature=0.3
                ).strip()
                explanation += f"\n\n*Note: Limited explanation due to research unavailability.*"
                return explanation
                
            except Exception as fallback_error:
                return f"**{topic}**\n\nContext: {context}\nPersonal Context: {personal_context}\n\n*Unable to generate detailed explanation at this time.*"
