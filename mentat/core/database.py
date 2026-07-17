import os
import re
import sqlite3
import json
import threading
import uuid
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple, Union, Callable, Generator
from datetime import datetime

# Import centralized configuration
from .config import (
    DATABASE_PATH, DATABASE_MAX_CONNECTIONS,
    DATABASE_TIMEOUT, DATABASE_CHECK_SAME_THREAD,
    PROJECT_SEARCH_K, GENERAL_SEARCH_K, PROJECT_PREVIEW_LENGTH,
    PROJECT_SEARCH_MIN_SIMILARITY, DEFAULT_WEEKLY_DAYS, DEFAULT_TODO_LIMIT
)

# Import shared utilities
from .utils import standardize_truncation
from .llm import complete
from .prompts import PROJECT_DASHBOARD_PROMPT

# Database connection pool
class DatabasePool:
    def __init__(self, db_path=None, max_connections=None):
        self.db_path = db_path or DATABASE_PATH
        self.max_connections = max_connections or DATABASE_MAX_CONNECTIONS
        self._connections = []
        self._lock = threading.Lock()
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        
    @contextmanager
    def get_connection(self):
        """Get a database connection from the pool"""
        conn = None
        try:
            with self._lock:
                if self._connections:
                    conn = self._connections.pop()
                else:
                    conn = sqlite3.connect(
                        self.db_path, 
                        check_same_thread=DATABASE_CHECK_SAME_THREAD,
                        timeout=DATABASE_TIMEOUT
                    )
                    conn.row_factory = sqlite3.Row  # Enable row factory for better access
            
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                try:
                    conn.commit()  # Commit any pending changes
                    with self._lock:
                        if len(self._connections) < self.max_connections:
                            self._connections.append(conn)
                        else:
                            conn.close()
                except:
                    conn.close()
    
    def close_all(self):
        """Close all connections in the pool"""
        with self._lock:
            for conn in self._connections:
                try:
                    conn.close()
                except:
                    pass
            self._connections.clear()

class MemoryDatabase:
    def __init__(self, db_path=None):
        self.db_pool = DatabasePool(db_path)
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables"""
        with self.db_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create memories table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    command_type TEXT NOT NULL,
                    tags TEXT,
                    metadata TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, content, command_type)
                )
            ''')
            
            # Create full-text search index
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts 
                USING fts5(content, tags, user_id)
            ''')
            
            # Create mem_embeddings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS mem_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER NOT NULL,
                    embedding TEXT NOT NULL
                )
            ''')
            
            # Add indexes for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_memories_command_type ON memories(command_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp)')

    
    def save_memory(
        self, 
        content: str, 
        user_id: str, 
        command_type: str, 
        tags: Optional[List[str]] = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """
        Save a memory to the database with tags and metadata.
        
        Stores a new memory record in the SQLite database, handling duplicate content
        gracefully by returning the existing memory ID if the same content already exists.
        
        Parameters:
            content (str): The text content of the memory to store
            user_id (str): Identifier for the user saving the memory
            command_type (str): Type classification (e.g., 'idea', 'task', 'link', 'reflection')
            tags (Optional[List[str]]): List of tags/themes associated with the content.
                Defaults to None if no tags provided.
            metadata (Optional[Dict[str, Any]]): Additional structured data like entities,
                actionable items, confidence scores, etc. Defaults to None.
        
        Returns:
            Optional[int]: Database ID of the saved memory, or None if save operation failed
        """
        memory_id = None
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                inserted = False
                try:
                    cursor.execute('''
                        INSERT INTO memories (user_id, content, command_type, tags, metadata)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (user_id, content, command_type, json.dumps(tags) if tags else None, json.dumps(metadata) if metadata else None))
                    memory_id = cursor.lastrowid
                    inserted = True
                except sqlite3.IntegrityError as e:
                    # Duplicate entry, fetch existing id
                    cursor.execute('''
                        SELECT id FROM memories WHERE user_id = ? AND content = ? AND command_type = ?
                    ''', (user_id, content, command_type))
                    row = cursor.fetchone()
                    if row:
                        memory_id = row[0]
                    else:
                        raise Exception(f"Integrity error but no duplicate found: {e}")
                if inserted:
                    cursor.execute('''
                        INSERT INTO memories_fts (content, tags, user_id)
                        VALUES (?, ?, ?)
                    ''', (content, ' '.join(tags) if tags else '', user_id))
            return memory_id
        except Exception as e:
            raise Exception(f"Error saving to database: {e}")
    
    def save_embedding(self, memory_id, embedding):
        """Save an embedding for a memory"""
        try:
            embedding_json = json.dumps(embedding)
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO mem_embeddings (memory_id, embedding)
                    VALUES (?, ?)
                ''', (memory_id, embedding_json))
        except Exception as e:
            raise Exception(f"Could not save embedding: {e}")
    
    def search_by_tags(
        self, 
        user_id: str, 
        tags: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Search for memories containing any of the specified tags (case-insensitive).
        
        Performs tag-based search across stored memories, looking for any memory that
        contains at least one of the specified tags. Search is case-insensitive and
        uses partial matching.
        
        Parameters:
            user_id (str): Identifier for the user whose memories to search
            tags (List[str]): List of tag strings to search for
        
        Returns:
            List[Dict[str, Any]]: List of memory dictionaries containing content,
                command_type, tags, timestamp, and 'why_matched' explanations showing
                which specific tag caused the match. Ordered by timestamp (newest first).
        """
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                # Search for memories containing any of the tags (case-insensitive)
                tag_conditions = ' OR '.join(['LOWER(tags) LIKE LOWER(?)' for _ in tags])
                tag_params = [f'%{tag}%' for tag in tags]
                cursor.execute(f'''
                    SELECT id, content, command_type, tags, timestamp, metadata FROM memories
                    WHERE user_id = ? AND ({tag_conditions})
                    ORDER BY timestamp DESC
                ''', [user_id] + tag_params)
                results = cursor.fetchall()
                structured_results = []
                for memory_id, content, command_type, tags_json, timestamp, metadata in results:
                    try:
                        tags_list = json.loads(tags_json) if tags_json else []
                    except:
                        tags_list = []
                    matched_tag = next((tag for tag in tags_list if any(q.lower() in tag.lower() for q in tags)), None)
                    why_matched = f"Tag match: {matched_tag}" if matched_tag else "Tag match"
                    structured_results.append({
                        'id': memory_id,
                        'content': content,
                        'command_type': command_type,
                        'tags': tags_list,
                        'timestamp': timestamp,
                        'metadata': metadata,
                        'why_matched': why_matched
                    })
                return structured_results
        except Exception as e:
            raise Exception(f"Tag search failed: {e}")
    
    def search_for_links(self, user_id, search_term=None):
        """Search for saved links, optionally filtered by search term"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                if search_term:
                    # Search for links containing the search term
                    clean_search = search_term.replace('%', '').replace('_', '')
                    cursor.execute('''
                        SELECT id, content, metadata FROM memories
                        WHERE user_id = ? AND (
                            command_type = 'link' OR 
                            (metadata IS NOT NULL AND (
                                json_extract(metadata, '$.url') IS NOT NULL OR
                                json_extract(metadata, '$.urls') IS NOT NULL
                            ))
                        ) AND (
                            content LIKE ? OR content LIKE ?
                        )
                        ORDER BY timestamp DESC
                    ''', (user_id, f'%{clean_search}%', f'%{clean_search.lower()}%'))
                else:
                    # Get all links (both command_type='link' and any content with URLs in metadata)
                    cursor.execute('''
                        SELECT id, content, metadata FROM memories
                        WHERE user_id = ? AND (
                            command_type = 'link' OR 
                            (metadata IS NOT NULL AND (
                                json_extract(metadata, '$.url') IS NOT NULL OR
                                json_extract(metadata, '$.urls') IS NOT NULL
                            ))
                        )
                        ORDER BY timestamp DESC
                    ''', (user_id,))
                
                results = cursor.fetchall()

                link_memories = []
                for memory_id, content, metadata in results:
                    # Return both content and metadata as a tuple so parser can fallback
                    link_memories.append((content, metadata, memory_id))

                return link_memories
        except Exception as e:
            raise Exception(f"Link search failed: {e}")
    
    def safe_memory_search(self, query, user_id):
        """Safe memory search function with FTS5 syntax handling, now joins FTS results to main table for full metadata. Annotates 'why_matched'."""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                # Sanitize query for FTS5 - remove special characters that cause syntax errors
                sanitized_query = query.replace('?', '').replace('!', '').replace(':', '').replace(';', '')
                sanitized_query = sanitized_query.replace('"', '').replace("'", '').replace('(', '').replace(')', '')
                sanitized_query = sanitized_query.replace('[', '').replace(']', '').replace('{', '').replace('}', '')
                sanitized_query = sanitized_query.replace('*', '').replace('+', '').replace('-', ' ').replace('=', ' ')
                sanitized_query = sanitized_query.replace('.', '')
                # Remove common words that might cause FTS issues
                common_words = ['what', 'is', 'are', 'my', 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by']
                query_words = sanitized_query.split()
                filtered_words = [word for word in query_words if word.lower() not in common_words and len(word) > 2]
                sanitized_query = ' '.join(filtered_words)
                if not sanitized_query.strip():
                    # If no meaningful query left, fall back to regular search
                    return self.comprehensive_search(user_id, query)
                # Use FTS for full-text search - EXCLUDE AI responses
                # Join FTS results to main table to get command_type, tags, timestamp
                cursor.execute('''
                    SELECT m.id, m.content, m.command_type, m.tags, m.timestamp, m.metadata
                    FROM memories_fts f
                    JOIN memories m ON m.content = f.content AND m.user_id = f.user_id
                    WHERE f.user_id = ? AND f.memories_fts MATCH ? AND m.command_type != 'ai_response'
                    ORDER BY m.timestamp DESC
                    LIMIT 5
                ''', (user_id, sanitized_query))
                results = cursor.fetchall()
                if not results:
                    return self.comprehensive_search(user_id, query)
                structured_results = []
                for memory_id, content, command_type, tags, timestamp, metadata in results:
                    try:
                        tags_list = json.loads(tags) if tags else []
                    except:
                        tags_list = []
                    why_matched = "Keyword match in content"
                    # Also check if query matches any tag
                    for tag in tags_list:
                        if query.lower() in tag.lower():
                            why_matched = f"Tag match: {tag}"
                            break
                    structured_results.append({
                        'id': memory_id,
                        'content': content,
                        'command_type': command_type,
                        'tags': tags_list,
                        'timestamp': timestamp,
                        'metadata': metadata,
                        'why_matched': why_matched
                    })
                return structured_results
        except Exception as e:
            # Fall back to regular search
            return self.comprehensive_search(user_id, query)
    
    def comprehensive_search(self, user_id, query):
        """Enhanced comprehensive search function with better cross-content connections"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # Clean the query for LIKE searches
                clean_query = query.replace('%', '').replace('_', '')
                
                # Enhanced search with multiple strategies - including recent content prioritization
                # EXCLUDE AI responses to prevent pollution
                cursor.execute(f'''
                    SELECT id, content, command_type, tags, timestamp, metadata
                    FROM memories
                    WHERE user_id = ? AND command_type != 'ai_response' AND (
                        content LIKE ? OR 
                        content LIKE ? OR
                        tags LIKE ? OR
                        tags LIKE ?
                    )
                    ORDER BY timestamp DESC
                    LIMIT {GENERAL_SEARCH_K}
                ''', (user_id, 
                      f'%{clean_query}%', 
                      f'%{clean_query.lower()}%',
                      f'%{clean_query}%',
                      f'%{clean_query.lower()}%'))
                
                results = cursor.fetchall()
                
                # If no results found, try searching for recent content (especially links)
                if not results:
                    cursor.execute('''
                        SELECT id, content, command_type, tags, timestamp, metadata
                        FROM memories
                        WHERE user_id = ? AND command_type != 'ai_response'
                        ORDER BY timestamp DESC
                        LIMIT 10
                    ''', (user_id,))
                    results = cursor.fetchall()
                
                # Return structured results with metadata
                structured_results = []
                for memory_id, content, command_type, tags, timestamp, metadata in results:
                    try:
                        tags_list = json.loads(tags) if tags else []
                    except:
                        tags_list = []
                    
                    structured_results.append({
                        'id': memory_id,
                        'content': content,
                        'command_type': command_type,
                        'tags': tags_list,
                        'timestamp': timestamp,
                        'metadata': metadata
                    })
                
                return structured_results
        except Exception as e:
            raise Exception(f"Comprehensive search failed: {e}")
    
    def get_all_memories(self, user_id, limit=GENERAL_SEARCH_K):
        """Get all memories for a user, excluding AI responses"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # EXCLUDE AI responses to prevent pollution in memory views
                cursor.execute('''
                    SELECT id, content, command_type, tags, timestamp, metadata 
                    FROM memories 
                    WHERE user_id = ? AND command_type != 'ai_response'
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (user_id, limit))
                
                results = cursor.fetchall()
                
                memories = []
                for id, content, command_type, tags, timestamp, metadata in results:
                    try:
                        tags_list = json.loads(tags) if tags else []
                    except:
                        tags_list = []
                    
                    memories.append({
                        'id': id,
                        'content': content,
                        'command_type': command_type,
                        'tags': tags_list,
                        'timestamp': timestamp,
                        'metadata': metadata
                    })
                
                return memories
        except Exception as e:
            raise Exception(f"Failed to get memories: {e}")
    
    def cleanup_ai_responses(self, user_id):
        """Remove low-quality AI responses from the database"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # Define patterns for low-quality AI responses
                low_quality_patterns = [
                    "no relevant information found",
                    "no specific information",
                    "no saved",
                    "it looks like",
                    "it seems",
                    "i don't have any",
                    "i don't see any",
                    "no content found",
                    "no memories found",
                    "no thoughts found",
                    "no ideas found",
                    "no links found",
                    "you haven't shared",
                    "you haven't saved",
                    "no information available",
                    "no data found",
                    "try using",
                    "you can use",
                    "suggest using"
                ]
                
                # Count how many will be deleted using a safer approach
                count_query = '''
                    SELECT COUNT(*) FROM memories 
                    WHERE user_id = ? AND command_type = 'ai_response' AND (
                '''
                
                # Build the conditions with proper parameterization
                conditions = []
                params = [user_id]
                
                for pattern in low_quality_patterns:
                    conditions.append("content LIKE ?")
                    params.append(f'%{pattern}%')
                
                count_query += " OR ".join(conditions) + ")"
                
                cursor.execute(count_query, params)
                count_to_delete = cursor.fetchone()[0]
                
                if count_to_delete > 0:
                    # Delete from main table using the same approach
                    delete_query = '''
                        DELETE FROM memories 
                        WHERE user_id = ? AND command_type = 'ai_response' AND (
                    '''
                    delete_query += " OR ".join(conditions) + ")"
                    
                    cursor.execute(delete_query, params)
                    
                    # Delete from FTS table (we'll need to rebuild this)
                    cursor.execute('DELETE FROM memories_fts WHERE user_id = ?', (user_id,))
                    
                    # Rebuild FTS table
                    cursor.execute('''
                        INSERT INTO memories_fts (content, tags, user_id)
                        SELECT content, tags, user_id FROM memories WHERE user_id = ?
                    ''', (user_id,))
                    
                    return count_to_delete
                else:
                    return 0
                    
        except Exception as e:
            raise Exception(f"Error during cleanup: {e}")
    
    def semantic_search(
        self, 
        user_id: str, 
        query: str, 
        k: int = 8, 
        min_similarity: float = 0.3, 
        get_embedding_func: Optional[Callable[[str], Optional[Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic search function with fallback to text search.
        
        Performs semantic similarity search using embeddings to find memories that are
        conceptually related to the query. Falls back to comprehensive text search if
        embedding generation fails or insufficient semantic matches are found.
        
        Parameters:
            user_id (str): Identifier for the user whose memories to search
            query (str): The search query text to find similar content  
            k (int): Maximum number of results to return. Defaults to 8.
            min_similarity (float): Minimum similarity threshold (0.0-1.0) for semantic matches.
                Defaults to 0.3.
            get_embedding_func (Optional[Callable[[str], Optional[Any]]]): Function that takes
                a string and returns an embedding vector. Must be provided for semantic search.
        
        Returns:
            List[Dict[str, Any]]: List of memory dictionaries containing content, metadata,
                and 'why_matched' explanations with similarity scores. Falls back to text
                search results if semantic search fails or returns insufficient matches.
        
        Raises:
            ValueError: If get_embedding_func is None
        """
        if get_embedding_func is None:
            raise ValueError("get_embedding_func must be provided")
        
        q_emb = get_embedding_func(query)
        if q_emb is None:
            return self.comprehensive_search(user_id, query)
        
        mem_sim_pairs = self.brute_sem_search(q_emb, k, min_similarity=min_similarity)
        mem_ids = [mid for mid, sim in mem_sim_pairs]
        sim_map = {mid: sim for mid, sim in mem_sim_pairs}
        
        # If semantic search returns too few results, fall back to text search
        if len(mem_ids) < 2:
            return self.comprehensive_search(user_id, query)
        
        if not mem_ids:
            return []
        
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                format_strings = ','.join(['?'] * len(mem_ids))
                cursor.execute(f'''
                    SELECT id, content, command_type, tags, timestamp FROM memories
                    WHERE id IN ({format_strings}) AND user_id = ?
                ''', (*mem_ids, user_id))
                results = cursor.fetchall()
                structured_results = []
                for mem_id, content, command_type, tags, timestamp in results:
                    try:
                        tags_list = json.loads(tags) if tags else []
                    except:
                        tags_list = []
                    similarity = sim_map.get(mem_id, None)
                    why_matched = f"Semantic similarity (score: {similarity:.2f})" if similarity is not None else "Semantic match"
                    structured_results.append({
                        'content': content,
                        'command_type': command_type,
                        'tags': tags_list,
                        'timestamp': timestamp,
                        'why_matched': why_matched
                    })
                return structured_results
        except Exception as e:
            return self.comprehensive_search(user_id, query)
    
    def brute_sem_search(self, q_emb, k=8, min_similarity=PROJECT_SEARCH_MIN_SIMILARITY):
        """Brute force semantic search with minimum similarity threshold. Returns list of (memory_id, similarity) tuples."""
        try:
            import numpy as np
            import pandas as pd
            from scipy.spatial.distance import cdist

            with self.db_pool.get_connection() as conn:
                df = pd.read_sql("SELECT memory_id, embedding FROM mem_embeddings", conn)
            if df.empty:
                return []
            M = np.vstack(df.embedding.apply(lambda x: np.array(json.loads(x))))
            d = cdist([q_emb], M, metric="cosine")[0]
            similarities = 1 - d  # Convert distance to similarity
            
            # Filter by minimum similarity
            valid_indices = similarities >= min_similarity
            if not any(valid_indices):
                return []  # No results meet the threshold
            
            # Get top k results that meet the threshold
            top_indices = np.where(valid_indices)[0]
            top_similarities = similarities[top_indices]
            top_k_indices = top_indices[np.argsort(top_similarities)[::-1][:k]]
            
            # Return list of (memory_id, similarity)
            return list(zip(df.iloc[top_k_indices].memory_id.tolist(), top_similarities[np.argsort(top_similarities)[::-1][:k]].tolist()))
        except Exception as e:
            raise Exception(f"Semantic search failed: {e}")
    
    def get_memories_by_ids(
        self, 
        memory_ids: List[int], 
        user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get memories by their database IDs.
        
        Retrieves multiple memory records from the database using their integer IDs.
        This is commonly used to fetch memories found through semantic search or
        other operations that return memory IDs.
        
        Parameters:
            memory_ids (List[int]): List of database IDs of memories to retrieve
            user_id (str): Identifier for the user to ensure access control
        
        Returns:
            List[Dict[str, Any]]: List of memory dictionaries containing content,
                command_type, tags, and timestamp. Returns empty list if no memories found.
        """
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                format_strings = ','.join(['?'] * len(memory_ids))
                cursor.execute(f'''
                    SELECT content, command_type, tags, timestamp FROM memories
                    WHERE id IN ({format_strings}) AND user_id = ?
                ''', list(memory_ids) + [user_id])
                results = cursor.fetchall()
                structured_results = []
                for content, command_type, tags, timestamp in results:
                    try:
                        tags_list = json.loads(tags) if tags else []
                    except:
                        tags_list = []
                    structured_results.append({
                        'content': content,
                        'command_type': command_type,
                        'tags': tags_list,
                        'timestamp': timestamp
                    })
                return structured_results
        except Exception as e:
            raise Exception(f"Failed to get memories by IDs: {e}")
    
    def delete_memory(self, memory_id, user_id):
        """Delete a specific memory by ID (with user verification)"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # First verify the memory exists and belongs to the user
                cursor.execute('''
                    SELECT id, content, command_type FROM memories 
                    WHERE id = ? AND user_id = ?
                ''', (memory_id, user_id))
                
                memory = cursor.fetchone()
                if not memory:
                    raise Exception(f"Memory {memory_id} not found or doesn't belong to user {user_id}")
                
                # Delete from main memories table
                cursor.execute('DELETE FROM memories WHERE id = ? AND user_id = ?', (memory_id, user_id))
                
                # Delete from FTS table (rebuild will handle this, but explicit delete is cleaner)
                cursor.execute('DELETE FROM memories_fts WHERE rowid = ?', (memory_id,))
                
                # Delete associated embeddings
                cursor.execute('DELETE FROM mem_embeddings WHERE memory_id = ?', (memory_id,))
                
                # Rebuild FTS table to ensure consistency
                cursor.execute('DELETE FROM memories_fts WHERE user_id = ?', (user_id,))
                cursor.execute('''
                    INSERT INTO memories_fts (content, tags, user_id)
                    SELECT content, tags, user_id FROM memories WHERE user_id = ?
                ''', (user_id,))
                
                return {
                    'id': memory[0],
                    'content': memory[1],
                    'command_type': memory[2]
                }
        except Exception as e:
            raise Exception(f"Failed to delete memory: {e}")
    
    def get_memory_by_id(self, memory_id, user_id):
        """Get a specific memory by ID with full details"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, content, command_type, tags, metadata, timestamp 
                    FROM memories 
                    WHERE id = ? AND user_id = ?
                ''', (memory_id, user_id))
                
                result = cursor.fetchone()
                if not result:
                    return None
                
                memory_id, content, command_type, tags, metadata, timestamp = result
                
                try:
                    tags_list = json.loads(tags) if tags else []
                except:
                    tags_list = []
                
                return {
                    'id': memory_id,
                    'content': content,
                    'command_type': command_type,
                    'tags': tags_list,
                    'metadata': metadata,
                    'timestamp': timestamp
                }
        except Exception as e:
            raise Exception(f"Failed to get memory by ID: {e}")
    
    def get_weekly_content(self, user_id, days_back=DEFAULT_WEEKLY_DAYS):
        """Get all content from the last N days"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # Query content from last N days
                cursor.execute('''
                    SELECT content, command_type, tags, timestamp 
                    FROM memories 
                    WHERE user_id = ? AND command_type != 'ai_response' 
                    AND timestamp >= datetime('now', '-{} days')
                    ORDER BY timestamp DESC
                '''.format(days_back), (user_id,))
                
                results = cursor.fetchall()
                
                # Group by content type
                weekly_data = {
                    'links': [],
                    'ideas': [],
                    'questions': [],
                    'thoughts': [],
                    'insights': [],
                    'notes': [],
                    'goals': [],
                    'all_content': []
                }
                
                for content, command_type, tags, timestamp in results:
                    try:
                        tags_list = json.loads(tags) if tags else []
                    except:
                        tags_list = []
                    
                    item = {
                        'content': content,
                        'command_type': command_type,
                        'tags': tags_list,
                        'timestamp': timestamp
                    }
                    
                    weekly_data['all_content'].append(item)
                    
                    if command_type == 'link':
                        weekly_data['links'].append(item)
                    elif command_type == 'idea':
                        weekly_data['ideas'].append(item)
                    elif command_type == 'ask':
                        weekly_data['questions'].append(item)
                    elif command_type == 'dump':
                        weekly_data['thoughts'].append(item)
                    elif command_type == 'insight':
                        weekly_data['insights'].append(item)
                    elif command_type == 'note':
                        weekly_data['notes'].append(item)
                    elif command_type == 'goal':
                        weekly_data['goals'].append(item)
                
                return weekly_data
        except Exception as e:
            raise Exception(f"Weekly content retrieval failed: {e}")
    
    def get_database_stats(self, user_id):
        """Get database statistics for a user"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get total memories for user
                cursor.execute('SELECT COUNT(*) FROM memories WHERE user_id = ?', (user_id,))
                total_memories = cursor.fetchone()[0]
                
                # Get memories by type
                cursor.execute('''
                    SELECT command_type, COUNT(*) 
                    FROM memories 
                    WHERE user_id = ? 
                    GROUP BY command_type
                ''', (user_id,))
                type_counts = cursor.fetchall()
                
                return {
                    'total_memories': total_memories,
                    'type_counts': type_counts
                }
        except Exception as e:
            raise Exception(f"Error getting stats: {e}")
    
    def check_entity_frequency_with_freshness(self, user_id, entities, entity_categories, threshold=3):
        """
        Check entity frequency with category-based freshness decay.
        Returns dict mapping entity names to their frequency counts and 
        list of entities that need web search (either novel or stale).
        
        Args:
            user_id: User identifier
            entities: List of entity names to check
            entity_categories: Dict mapping category -> list of entities (from extract_structured_entities)
            threshold: Frequency threshold for considering entities "known"
        
        Returns:
            Tuple of (entity_frequencies dict, novel_entities list)
        """
        from datetime import datetime, timedelta
        from .config import ENTITY_FRESHNESS_DAYS
        
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                entity_frequencies = {}
                novel_entities = []
                
                # Create reverse mapping: entity -> category
                entity_to_category = {}
                for category, entity_list in entity_categories.items():
                    for entity in entity_list:
                        entity_to_category[entity] = category
                
                for entity in entities:
                    # Get total frequency
                    cursor.execute('''
                        SELECT COUNT(*) FROM memories 
                        WHERE user_id = ? AND (
                            LOWER(content) LIKE LOWER(?) 
                            OR metadata LIKE ?
                        )
                    ''', (user_id, f'%{entity}%', f'%{entity}%'))
                    
                    count = cursor.fetchone()[0]
                    entity_frequencies[entity] = count
                    
                    # If under threshold, it's novel
                    if count < threshold:
                        novel_entities.append(entity)
                    else:
                        # Check freshness - when was this entity last web-searched?
                        cursor.execute('''
                            SELECT MAX(timestamp) FROM memories 
                            WHERE user_id = ? AND (
                                LOWER(content) LIKE LOWER(?) 
                                OR metadata LIKE ?
                            ) AND metadata LIKE '%"web_enriched": true%'
                        ''', (user_id, f'%{entity}%', f'%{entity}%'))
                        
                        result = cursor.fetchone()
                        last_searched = result[0] if result else None
                        
                        if not last_searched:
                            # Never web-searched, should search
                            novel_entities.append(entity)
                        else:
                            # Check if stale based on entity category
                            try:
                                # Parse ISO timestamp 
                                if last_searched.endswith('Z'):
                                    last_searched = last_searched[:-1] + '+00:00'
                                last_date = datetime.fromisoformat(last_searched.replace('Z', '+00:00'))
                                
                                # Get freshness window for this entity's category
                                category = entity_to_category.get(entity, 'default')
                                freshness_days = ENTITY_FRESHNESS_DAYS.get(category, ENTITY_FRESHNESS_DAYS['default'])
                                
                                # Check if stale
                                cutoff = datetime.now() - timedelta(days=freshness_days)
                                if last_date < cutoff:
                                    novel_entities.append(entity)  # Stale, needs refresh
                                    
                            except (ValueError, AttributeError) as e:
                                # If timestamp parsing fails, assume stale
                                novel_entities.append(entity)
                
                return entity_frequencies, novel_entities
                
        except Exception as e:
            print(f"Warning: Error checking entity frequency with freshness: {e}")
            # Return empty dict if error - assume all entities are novel
            return {entity: 0 for entity in entities}, entities

    def check_entity_frequency(self, user_id, entities, threshold=3):
        """
        Legacy method for backward compatibility.
        Check how frequently entities appear in the database.
        Returns dict mapping entity names to their frequency counts.
        Only entities with frequency < threshold are considered 'novel'.
        """
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                entity_frequencies = {}
                
                for entity in entities:
                    # Search for the entity in both content and metadata
                    # First check in content (case-insensitive)
                    cursor.execute('''
                        SELECT COUNT(*) FROM memories 
                        WHERE user_id = ? AND (
                            LOWER(content) LIKE LOWER(?) 
                            OR metadata LIKE ?
                        )
                    ''', (user_id, f'%{entity}%', f'%{entity}%'))
                    
                    count = cursor.fetchone()[0]
                    entity_frequencies[entity] = count
                
                return entity_frequencies
                
        except Exception as e:
            print(f"Warning: Error checking entity frequency: {e}")
            # Return empty dict if error - assume all entities are novel
            return {entity: 0 for entity in entities}
    
    def search_by_content_type(self, user_id, content_type, query=None):
        """Search for specific types of content (idea, dump, ask, etc.)"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                if query:
                    # Search within specific content type
                    cursor.execute('''
                        SELECT content FROM memories 
                        WHERE user_id = ? AND command_type = ? AND content LIKE ?
                        ORDER BY timestamp DESC
                        LIMIT 20
                    ''', (user_id, content_type, f'%{query}%'))
                else:
                    # Get all content of specific type
                    cursor.execute('''
                        SELECT content FROM memories 
                        WHERE user_id = ? AND command_type = ?
                        ORDER BY timestamp DESC
                        LIMIT 20
                    ''', (user_id, content_type))
                
                results = [row[0] for row in cursor.fetchall()]
                return results
        except Exception as e:
            raise Exception(f"Content type search failed: {e}")
    
    def backfill_embeddings(self, embedding_generator_func):
        """Backfill embeddings for existing memories"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                # Find all memory IDs and content
                cursor.execute('SELECT id, content FROM memories')
                all_memories = cursor.fetchall()
                # Find all memory_ids that already have embeddings
                cursor.execute('SELECT memory_id FROM mem_embeddings')
                embedded_ids = set(row[0] for row in cursor.fetchall())
            
            to_embed = [(mem[0], mem[1]) for mem in all_memories if mem[0] not in embedded_ids]
            if not to_embed:
                return 0, "All memories already have embeddings!"
            
            # Generate embeddings for memories that don't have them
            for mem_id, content in to_embed:
                embedding = embedding_generator_func(content)
                if embedding:
                    self.save_embedding(mem_id, embedding)
            
            return len(to_embed), f"Backfilled {len(to_embed)} embeddings!"
        except Exception as e:
            raise Exception(f'Backfill failed: {e}')

    def get_all_memories_for_migration(self):
        """Get all memories across all users for embedding migration (no AI responses)"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, content, command_type, tags, timestamp, metadata 
                    FROM memories 
                    WHERE command_type != 'ai_response'
                    ORDER BY timestamp DESC
                ''')
                results = cursor.fetchall()
                
                memories = []
                for row in results:
                    memories.append({
                        'id': row[0],
                        'content': row[1],
                        'command_type': row[2],
                        'tags': json.loads(row[3]) if row[3] else [],
                        'timestamp': row[4],
                        'metadata': json.loads(row[5]) if row[5] else {}
                    })
                return memories
        except Exception as e:
            raise Exception(f"Failed to get all memories: {e}")

    def clear_all_embeddings(self):
        """Clear all existing embeddings from the database"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM mem_embeddings')
                conn.commit()
                return True
        except Exception as e:
            raise Exception(f"Failed to clear embeddings: {e}")
    
    def get_user_todos(self, user_id, status_filter=None, limit=DEFAULT_TODO_LIMIT):
        """Get todos for a user with optional status filtering. Searches all memories for actionable items in metadata.
        
        Args:
            user_id: User identifier  
            status_filter: Filter by status ('pending', 'done', 'skip', 'blocked') or None for all
            limit: Maximum number of todos to return
        """
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                # Search all memories for actionable items in metadata, ordered by timestamp DESC for chronological view
                cursor.execute('''
                    SELECT id, content, metadata, tags, timestamp, command_type FROM memories 
                    WHERE user_id = ? 
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (user_id, limit * 10))  # Fetch more to ensure enough todos after filtering
                results = cursor.fetchall()
                todos = []
                todo_counter = 0
                
                for memory_id, content, metadata, tags, timestamp, command_type in results:
                    try:
                        metadata_dict = json.loads(metadata) if metadata else {}
                        tags_list = json.loads(tags) if tags else []
                    except:
                        metadata_dict = {}
                        tags_list = []
                    
                    # Extract actionable items from metadata
                    actionable_items = metadata_dict.get('actionable_items', [])
                    if actionable_items:
                        metadata_changed = False
                        for item_index, item in enumerate(actionable_items):
                            if isinstance(item, dict):
                                if not item.get('todo_id'):
                                    item['todo_id'] = f"todo_{uuid.uuid4().hex}"
                                    metadata_changed = True
                                # Handle new structure with status
                                todo = {
                                    'todo_id': item.get('todo_id'),
                                    'memory_id': memory_id,
                                    'item_index': item_index,
                                    'action': item.get('action', str(item)),
                                    'context': item.get('context', ''),
                                    'priority': item.get('priority', 'medium'),
                                    'status': item.get('status', 'pending'),  # Default to pending for existing todos
                                    'marked_date': item.get('marked_date', ''),
                                    'time_sensitive': item.get('time_sensitive', False),
                                    'project': item.get('project', ''),
                                    'due_date': item.get('due_date', ''),
                                    'dependencies': item.get('dependencies', []),
                                    'source_content': content,
                                    'timestamp': timestamp,
                                    'tags': tags_list,
                                    'command_type': command_type
                                }
                            else:
                                todo_id = f"todo_{uuid.uuid4().hex}"
                                actionable_items[item_index] = {
                                    'todo_id': todo_id,
                                    'action': str(item),
                                    'priority': 'medium',
                                    'status': 'pending',
                                    'marked_date': '',
                                    'context': '',
                                    'time_sensitive': False,
                                    'project': '',
                                    'due_date': '',
                                    'dependencies': []
                                }
                                metadata_changed = True
                                # Handle legacy structure (plain strings)
                                todo = {
                                    'todo_id': todo_id,
                                    'memory_id': memory_id,
                                    'item_index': item_index,
                                    'action': str(item),
                                    'context': '',
                                    'priority': 'medium',
                                    'status': 'pending',  # Default status for legacy todos
                                    'marked_date': '',
                                    'time_sensitive': False,
                                    'project': '',
                                    'due_date': '',
                                    'dependencies': [],
                                    'source_content': content,
                                    'timestamp': timestamp,
                                    'tags': tags_list,
                                    'command_type': command_type
                                }

                            # IMPORTANT: Assign global display number BEFORE filtering
                            # This ensures todo #18 is always todo #18 regardless of filter
                            todo_counter += 1
                            todo['display_number'] = todo_counter

                            # Now apply status filter
                            if status_filter is None or todo['status'] == status_filter:
                                todos.append(todo)

                                # Stop if we've reached the limit of FILTERED results
                                if len(todos) >= limit:
                                    if metadata_changed:
                                        metadata_dict['actionable_items'] = actionable_items
                                        cursor.execute(
                                            'UPDATE memories SET metadata = ? WHERE id = ?',
                                            (json.dumps(metadata_dict), memory_id)
                                        )
                                    return todos

                        if metadata_changed:
                            metadata_dict['actionable_items'] = actionable_items
                            cursor.execute(
                                'UPDATE memories SET metadata = ? WHERE id = ?',
                                (json.dumps(metadata_dict), memory_id)
                            )
                
                return todos
        except Exception as e:
            raise Exception(f"Todo retrieval failed: {e}")
    
    def update_todo_status(self, memory_id, item_index, new_status):
        """Update the status of a specific todo item in memory metadata.
        
        Args:
            memory_id: ID of the memory containing the todo
            item_index: Index of the todo item in the actionable_items array
            new_status: New status ('pending', 'done', 'skip', 'blocked')
        """
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get the current memory metadata
                cursor.execute('SELECT metadata FROM memories WHERE id = ?', (memory_id,))
                result = cursor.fetchone()
                
                if not result:
                    raise Exception(f"Memory with ID {memory_id} not found")
                
                metadata = result[0]
                try:
                    metadata_dict = json.loads(metadata) if metadata else {}
                except:
                    metadata_dict = {}
                
                # Get actionable items
                actionable_items = metadata_dict.get('actionable_items', [])
                
                if item_index >= len(actionable_items):
                    raise Exception(f"Todo item index {item_index} not found")
                
                # Update the specific todo item
                item = actionable_items[item_index]
                if isinstance(item, dict):
                    if not item.get('todo_id'):
                        item['todo_id'] = f"todo_{uuid.uuid4().hex}"
                    item['status'] = new_status
                    item['marked_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                else:
                    # Convert legacy string todo to dict format
                    actionable_items[item_index] = {
                        'todo_id': f"todo_{uuid.uuid4().hex}",
                        'action': str(item),
                        'priority': 'medium',
                        'status': new_status,
                        'marked_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'context': '',
                        'time_sensitive': False,
                        'project': '',
                        'due_date': '',
                        'dependencies': []
                    }
                
                # Update metadata in database
                metadata_dict['actionable_items'] = actionable_items
                updated_metadata = json.dumps(metadata_dict)
                
                cursor.execute('UPDATE memories SET metadata = ? WHERE id = ?', 
                             (updated_metadata, memory_id))
                
                return True
                
        except Exception as e:
            raise Exception(f"Todo status update failed: {e}")

    def update_todo_status_by_id(self, user_id, todo_id, new_status):
        """Update a todo item by its persisted opaque todo ID."""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id, metadata FROM memories WHERE user_id = ?',
                    (user_id,)
                )

                for memory_id, metadata in cursor.fetchall():
                    try:
                        metadata_dict = json.loads(metadata) if metadata else {}
                    except:
                        metadata_dict = {}

                    actionable_items = metadata_dict.get('actionable_items', [])
                    for item_index, item in enumerate(actionable_items):
                        if isinstance(item, dict) and item.get('todo_id') == todo_id:
                            item['status'] = new_status
                            item['marked_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            metadata_dict['actionable_items'] = actionable_items
                            cursor.execute(
                                'UPDATE memories SET metadata = ? WHERE id = ?',
                                (json.dumps(metadata_dict), memory_id)
                            )
                            return {
                                'memory_id': memory_id,
                                'item_index': item_index,
                                'todo_id': todo_id,
                                'status': new_status,
                                'action': item.get('action', ''),
                            }

                return None
        except Exception as e:
            raise Exception(f"Todo status update by ID failed: {e}")

    def close(self):
        """Close all database connections"""
        self.db_pool.close_all()

    def semantic_project_content(self, user_id, project_name, k=PROJECT_SEARCH_K, get_embedding_for_query=None, brute_sem_search=None, fallback_project_search=None):
        """Semantic search for all content related to a project, grouped by type. Requires get_embedding_for_query and brute_sem_search functions."""
        if get_embedding_for_query is None or brute_sem_search is None:
            raise ValueError("get_embedding_for_query and brute_sem_search functions must be provided.")
        q_emb = get_embedding_for_query(project_name)
        if q_emb is None:
            if fallback_project_search:
                return fallback_project_search(user_id, project_name)
            return {'links': [], 'ideas': [], 'questions': [], 'thoughts': [], 'insights': [], 'notes': [], 'goals': [], 'all_content': []}
        # Get semantic results
        semantic_mem_ids = brute_sem_search(q_emb, k, min_similarity=PROJECT_SEARCH_MIN_SIMILARITY)
        
        # Always get keyword/fallback results too
        fallback_data = fallback_project_search(user_id, project_name) if fallback_project_search else None
        
        # If no semantic results, just return fallback
        if not semantic_mem_ids and fallback_data:
            return fallback_data
        elif not semantic_mem_ids:
            return {'links': [], 'ideas': [], 'questions': [], 'thoughts': [], 'insights': [], 'notes': [], 'goals': [], 'all_content': []}
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                # Extract just the memory IDs from (memory_id, similarity) tuples
                memory_ids_only = [mem_id for mem_id, similarity in semantic_mem_ids]
                format_strings = ','.join(['?'] * len(memory_ids_only))
                cursor.execute(f'''
                    SELECT id, content, command_type, tags, timestamp, metadata FROM memories
                    WHERE id IN ({format_strings}) AND user_id = ?
                ''', list(memory_ids_only) + [user_id])
                results = cursor.fetchall()
                project_data = {
                    'links': [],
                    'ideas': [],
                    'questions': [],
                    'thoughts': [],
                    'insights': [],
                    'notes': [],
                    'goals': [],
                    'all_content': []
                }
                for id, content, command_type, tags, timestamp, metadata in results:
                    try:
                        tags_list = json.loads(tags) if tags else []
                    except:
                        tags_list = []
                    item = {
                        'id': id,
                        'content': content,
                        'command_type': command_type,
                        'tags': tags_list,
                        'timestamp': timestamp,
                        'metadata': metadata
                    }
                    project_data['all_content'].append(item)
                    if command_type == 'link':
                        project_data['links'].append(item)
                    elif command_type == 'idea':
                        project_data['ideas'].append(item)
                    elif command_type == 'ask':
                        project_data['questions'].append(item)
                    elif command_type == 'dump':
                        project_data['thoughts'].append(item)
                    elif command_type == 'insight':
                        project_data['insights'].append(item)
                    elif command_type == 'note':
                        project_data['notes'].append(item)
                    elif command_type == 'goal':
                        project_data['goals'].append(item)
                
                # Merge with fallback results (keyword matches first priority)
                if fallback_data:
                    semantic_ids = set(item['id'] for item in project_data['all_content'])
                    for fallback_item in fallback_data['all_content']:
                        # Add fallback items that weren't found semantically (keyword matches first)
                        if fallback_item['id'] not in semantic_ids:
                            project_data['all_content'].insert(0, fallback_item)  # Insert at beginning for priority
                            cmd_type = fallback_item['command_type']
                            if cmd_type == 'link':
                                project_data['links'].insert(0, fallback_item)
                            elif cmd_type == 'idea':
                                project_data['ideas'].insert(0, fallback_item)
                            elif cmd_type == 'ask':
                                project_data['questions'].insert(0, fallback_item)
                            elif cmd_type == 'dump':
                                project_data['thoughts'].insert(0, fallback_item)
                            elif cmd_type == 'insight':
                                project_data['insights'].insert(0, fallback_item)
                            elif cmd_type == 'note':
                                project_data['notes'].insert(0, fallback_item)
                            elif cmd_type == 'goal':
                                project_data['goals'].insert(0, fallback_item)
                
                return project_data
        except Exception:
            return {'links': [], 'ideas': [], 'questions': [], 'thoughts': [], 'insights': [], 'notes': [], 'goals': [], 'all_content': []}

    def analyze_project_progress(self, project_data, project_name, openai_client=None, model="openai/gpt-4o-mini"):
        """Analyze project progress and provide insights, clusters, themes, and actionable items. Requires openai_client."""
        if openai_client is None:
            raise ValueError("openai_client must be provided.")
        try:
            analysis_content = []
            analysis_content.append(f"Project: {project_name}")
            analysis_content.append(f"Total items found: {len(project_data['all_content'])}")
            analysis_content.append(f"Links: {len(project_data['links'])}")
            analysis_content.append(f"Ideas: {len(project_data['ideas'])}")
            analysis_content.append(f"Questions: {len(project_data['questions'])}")
            analysis_content.append(f"Thoughts: {len(project_data['thoughts'])}")
            analysis_content.append("---")
            for item in project_data['all_content'][:20]:  # Increased from 10 to 20
                content_type = item['command_type'].upper()
                content_preview = standardize_truncation(item['content'], PROJECT_PREVIEW_LENGTH)
                timestamp = item['timestamp'] if item['timestamp'] else 'Unknown date'
                tags_str = f"Tags: {', '.join(item['tags'])}" if item['tags'] else ""
                analysis_content.append(f"[{content_type}] {timestamp}: {content_preview}")
                if tags_str:
                    analysis_content.append(f"{tags_str} (related by: {', '.join(item['tags'][:3])})")
                analysis_content.append("---")
            combined_content = "\n".join(analysis_content)
            system_prompt = PROJECT_DASHBOARD_PROMPT
            return complete(
                openai_client,
                model,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Project: {project_name}\n\nContent:\n{combined_content}"}
                ]
            )
        except Exception as e:
            return f"Could not analyze project: {e}"

    def _fallback_project_search(self, user_id, project_name):
        """Fallback text-based search for project content"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                clean_query = project_name.replace('%', '').replace('_', '')
                cursor.execute('''
                    SELECT id, content, command_type, tags, timestamp, metadata
                    FROM memories 
                    WHERE user_id = ? AND command_type != 'ai_response' AND (
                        content LIKE ? OR 
                        content LIKE ? OR
                        tags LIKE ? OR
                        tags LIKE ?
                    )
                    ORDER BY timestamp DESC
                ''', (user_id, 
                      f'%{clean_query}%', 
                      f'%{clean_query.lower()}%',
                      f'%{clean_query}%',
                      f'%{clean_query.lower()}%'))
                results = cursor.fetchall()
                project_data = {
                    'links': [],
                    'ideas': [],
                    'questions': [],
                    'thoughts': [],
                    'insights': [],
                    'notes': [],
                    'goals': [],
                    'all_content': []
                }
                project_name_lower = project_name.lower()
                for id, content, command_type, tags, timestamp, metadata in results:
                    try:
                        tags_list = json.loads(tags) if tags else []
                    except:
                        tags_list = []
                    # Robust tag match: case-insensitive, partial match for multi-word queries
                    project_words = project_name_lower.split()
                    tag_string = ' '.join(tags_list).lower()
                    tag_match = all(word in tag_string for word in project_words) or any(project_name_lower in tag.lower() for tag in tags_list)
                    # Content match: case-insensitive, partial match
                    content_match = project_name_lower in content.lower()
                    if tag_match or content_match:
                        item = {
                            'id': id,
                            'content': content,
                            'command_type': command_type,
                            'tags': tags_list,
                            'timestamp': timestamp,
                            'metadata': metadata
                        }
                        project_data['all_content'].append(item)
                        if command_type == 'link':
                            project_data['links'].append(item)
                        elif command_type == 'idea':
                            project_data['ideas'].append(item)
                        elif command_type == 'ask':
                            project_data['questions'].append(item)
                        elif command_type == 'dump':
                            project_data['thoughts'].append(item)
                return project_data
        except Exception:
            return {'links': [], 'ideas': [], 'questions': [], 'thoughts': [], 'insights': [], 'notes': [], 'goals': [], 'all_content': []}

    def search_by_timeframe(self, user_id, query=None, start_date=None, end_date=None, k=GENERAL_SEARCH_K):
        """Search memories within a specific date range, with optional query"""
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # Build query based on what's provided
                if query:
                    # Combined search with date range if both provided
                    if start_date and end_date:
                        # Get all memories in date range first
                        cursor.execute('''
                            SELECT id, content, command_type, tags, timestamp
                            FROM memories 
                            WHERE user_id = ? AND command_type != 'ai_response'
                            AND date(timestamp) BETWEEN date(?) AND date(?)
                            ORDER BY timestamp DESC
                            LIMIT ?
                        ''', (user_id, start_date, end_date, k * 2))  # Get more for filtering
                        
                        results = cursor.fetchall()
                        
                        # If we have query, do intelligent keyword filtering on the results
                        clean_query = query.replace('%', '').replace('_', '')
                        
                        # Extract meaningful keywords from query by removing stopwords
                        stopwords = {'what', 'was', 'were', 'did', 'do', 'i', 'me', 'my', 'am', 'is', 'are', 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
                        query_words = [word.lower() for word in clean_query.split() if word.lower() not in stopwords and len(word) > 1]
                        
                        filtered_results = []
                        for id, content, command_type, tags, timestamp in results:
                            content_lower = content.lower()
                            tags_lower = tags.lower() if tags else ""
                            
                            # Check if any meaningful keyword appears in content or tags
                            if query_words:
                                matches = False
                                for word in query_words:
                                    # Use root word matching for better results (e.g., 'working' matches 'worked', 'work')
                                    if len(word) > 4:
                                        root_word = word[:4]  # Simple root matching for words > 4 chars
                                        matches = any(root_word in content_word for content_word in content_lower.split()) or \
                                                 any(root_word in tag_word for tag_word in tags_lower.split())
                                    else:
                                        matches = word in content_lower or word in tags_lower
                                    
                                    if matches:
                                        break
                            else:
                                # If no meaningful keywords, fall back to original phrase matching
                                matches = (clean_query.lower() in content_lower or clean_query.lower() in tags_lower)
                            
                            if matches:
                                filtered_results.append((id, content, command_type, tags, timestamp))
                        
                        results = filtered_results[:k]
                    else:
                        # Just query without date filtering
                        return self.comprehensive_search(user_id, query)
                else:
                    # Just date range without query
                    cursor.execute('''
                        SELECT id, content, command_type, tags, timestamp
                        FROM memories 
                        WHERE user_id = ? AND command_type != 'ai_response'
                        AND date(timestamp) BETWEEN date(?) AND date(?)
                        ORDER BY timestamp DESC
                        LIMIT ?
                    ''', (user_id, start_date, end_date, k))
                    
                    results = cursor.fetchall()
                
                # Convert to structured format
                structured_results = []
                for row in results:
                    if len(row) == 5:  # id, content, command_type, tags, timestamp
                        memory_id, content, command_type, tags, timestamp = row
                    else:  # content, command_type, tags, timestamp (no id)
                        memory_id = None
                        content, command_type, tags, timestamp = row
                    
                    try:
                        tags_list = json.loads(tags) if tags else []
                    except:
                        tags_list = []
                    
                    result = {
                        'content': content,
                        'command_type': command_type,
                        'tags': tags_list,
                        'timestamp': timestamp
                    }
                    if memory_id is not None:
                        result['id'] = memory_id
                    structured_results.append(result)
                
                return structured_results
                
        except Exception as e:
            raise Exception(f"Timeframe search failed: {e}")

    def find_entity_connections(
        self, 
        memory_entities: Dict[str, List[str]], 
        user_id: str, 
        k: int = 5, 
        exclude_id: Optional[int] = None
    ) -> List[Tuple[Dict[str, Any], List[str]]]:
        """
        Find memories sharing entities with the provided entities.
        
        Searches for memories that share structured entities (people, organizations,
        technologies, etc.) with a given set of entities. Used for discovering
        connections between related content based on common entities.
        
        Parameters:
            memory_entities (Dict[str, List[str]]): Dictionary of entities organized by
                category, like {'technologies': ['Python', 'SQLite'], 'people': ['John']}.
            user_id (str): User ID to search within for access control
            k (int): Maximum number of results to return. Defaults to 5.
            exclude_id (Optional[int]): Memory ID to exclude from results (useful when
                finding connections to a specific memory). Defaults to None.
        
        Returns:
            List[Tuple[Dict[str, Any], List[str]]]: List of tuples where each tuple
                contains (memory_dict, shared_entities). The memory_dict contains the
                standard memory fields, and shared_entities is a list of entity names
                that caused the connection match.
        """
        # Flatten all entities into a set for fast comparison
        entity_set = set()
        for entity_list in memory_entities.values():
            if isinstance(entity_list, list):
                entity_set.update([e.lower().strip() for e in entity_list if e])  # Normalize case
        
        if not entity_set:
            return []
        
        try:
            with self.db_pool.get_connection() as conn:
                cursor = conn.cursor()
                
                # Fetch memories with metadata (exclude AI responses and optionally specific memory)
                if exclude_id:
                    cursor.execute('''
                        SELECT id, content, metadata, tags, timestamp, command_type 
                        FROM memories 
                        WHERE user_id = ? AND command_type != 'ai_response' AND id != ?
                        ORDER BY timestamp DESC
                    ''', (user_id, exclude_id))
                else:
                    cursor.execute('''
                        SELECT id, content, metadata, tags, timestamp, command_type 
                        FROM memories 
                        WHERE user_id = ? AND command_type != 'ai_response'
                        ORDER BY timestamp DESC
                    ''', (user_id,))
                
                results = cursor.fetchall()
                
                scored = []
                for row in results:
                    mem_id, content, metadata, tags, timestamp, command_type = row
                    
                    try:
                        meta = json.loads(metadata) if metadata else {}
                        mem_entities = meta.get('entities', {})
                    except:
                        mem_entities = {}
                    
                    # Flatten memory entities
                    mem_entity_set = set()
                    for entity_list in mem_entities.values():
                        if isinstance(entity_list, list):
                            mem_entity_set.update([e.lower().strip() for e in entity_list if e])
                    
                    # Find shared entities (case-insensitive)
                    shared = entity_set & mem_entity_set
                    
                    if shared:
                        # Parse tags for display
                        try:
                            tags_list = json.loads(tags) if tags else []
                        except:
                            tags_list = []
                        
                        scored.append((
                            {
                                'id': mem_id,
                                'content': content,
                                'tags': tags_list,
                                'timestamp': timestamp,
                                'command_type': command_type
                            },
                            list(shared)
                        ))
                
                # Sort by number of shared entities (descending), then by recency
                scored.sort(key=lambda x: (len(x[1]), x[0]['timestamp']), reverse=True)
                return scored[:k]
                
        except Exception as e:
            raise Exception(f"Entity connections search failed: {e}")
    
# Global database instance
db = MemoryDatabase()  # Uses centralized DATABASE_PATH from config

# Cleanup function for atexit
import atexit
atexit.register(db.close)
