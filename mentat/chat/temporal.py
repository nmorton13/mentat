"""
Temporal processing utilities for MENTAT

Handles natural language time expressions and converts them to searchable date ranges.
This module provides deterministic date calculations for common temporal patterns,
falling back to AI processing for complex cases.
"""

from datetime import datetime, timedelta
import calendar
import re
from typing import Optional, Dict, Any, Tuple


def extract_temporal_intent(
    query: str, 
    model: Optional[str] = None, 
    client: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """
    Extract temporal intent from natural language query.
    
    Processes natural language time expressions and converts them to searchable 
    date ranges. Uses deterministic pattern matching for common temporal expressions
    (e.g., "last week", "last January", "last spring") with AI fallback for complex cases.
    
    Parameters:
        query (str): Natural language query containing temporal expressions
        model (Optional[str]): AI model name for complex pattern processing.
            Used only for AI fallback cases.
        client (Optional[Any]): AI client for complex temporal pattern processing.
            If None, returns None without processing.
    
    Returns:
        Optional[Dict[str, Any]]: Dictionary containing temporal information:
            - 'start_date': Start of the date range (datetime)
            - 'end_date': End of the date range (datetime)  
            - 'context': Human-readable description of the time period
            - 'cleaned_query': Query with temporal expressions removed
            - 'is_generic': Whether query was generic (e.g., "what did I do")
            Returns None if no temporal intent found or client unavailable.
    """
    if not client:
        return None
    
    # First, check for common temporal patterns and calculate dates ourselves
    query_lower = query.lower().strip()
    current_datetime = datetime.now()
    
    # Clean up generic query patterns
    def clean_remaining_query(original_query: str, temporal_phrase: str) -> str:
        """
        Remove temporal phrase and clean up generic questions.
        
        Processes the original query by removing the identified temporal phrase
        and determines if the remaining query is generic (should return all memories
        in the timeframe) or specific (should filter within the timeframe).
        
        Parameters:
            original_query (str): The original user query containing temporal expressions
            temporal_phrase (str): The specific temporal phrase to remove (e.g., "last week")
        
        Returns:
            str: Cleaned query text, or empty string if query is generic and should
                return all memories from the specified timeframe without filtering.
        """
        remaining = original_query.replace(temporal_phrase, "").strip()
        remaining = remaining.replace("?", "").strip()
        
        # Generic patterns that should return all memories in timeframe
        generic_patterns = [
            "what did i do", "what did i work on", "what happened", 
            "what was i doing", "what was i thinking", "what was i thinking about",
            "show me", "tell me about"
        ]
        
        if any(pattern in remaining for pattern in generic_patterns):
            return ""
        return remaining
    
    # === RELATIVE TIME PERIODS ===
    
    # Last week
    if "last week" in query_lower:
        start = (current_datetime - timedelta(days=current_datetime.weekday() + 7)).strftime('%Y-%m-%d')
        end = (current_datetime - timedelta(days=current_datetime.weekday() + 1)).strftime('%Y-%m-%d')
        return {
            "has_temporal_intent": True,
            "start_date": start,
            "end_date": end,
            "temporal_context": f"last week ({start} to {end})",
            "query_without_temporal": clean_remaining_query(query_lower, "last week"),
            "confidence": 0.95
        }
    
    # Last month
    if "last month" in query_lower:
        start = (current_datetime.replace(day=1) - timedelta(days=1)).replace(day=1).strftime('%Y-%m-%d')
        end = (current_datetime.replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
        return {
            "has_temporal_intent": True,
            "start_date": start,
            "end_date": end,
            "temporal_context": f"last month ({start} to {end})",
            "query_without_temporal": clean_remaining_query(query_lower, "last month"),
            "confidence": 0.95
        }
    
    # Yesterday
    if "yesterday" in query_lower:
        yesterday = (current_datetime - timedelta(days=1)).strftime('%Y-%m-%d')
        return {
            "has_temporal_intent": True,
            "start_date": yesterday,
            "end_date": yesterday,
            "temporal_context": f"yesterday ({yesterday})",
            "query_without_temporal": clean_remaining_query(query_lower, "yesterday"),
            "confidence": 0.95
        }
    
    # Last year / This time last year
    if "last year" in query_lower or "this time last year" in query_lower:
        # Use a 2-month window around this time last year
        last_year_center = current_datetime.replace(year=current_datetime.year - 1)
        start = (last_year_center - timedelta(days=30)).strftime('%Y-%m-%d')
        end = (last_year_center + timedelta(days=30)).strftime('%Y-%m-%d')
        temporal_phrase = "this time last year" if "this time last year" in query_lower else "last year"
        return {
            "has_temporal_intent": True,
            "start_date": start,
            "end_date": end,
            "temporal_context": f"{temporal_phrase} ({start} to {end})",
            "query_without_temporal": clean_remaining_query(query_lower, temporal_phrase),
            "confidence": 0.90
        }
    
    # === SPECIFIC MONTHS ===
    
    # Month patterns: "last January", "in March", "during June", "January 2024"
    month_patterns = [
        (r"last (january|february|march|april|may|june|july|august|september|october|november|december)", "last"),
        (r"in (january|february|march|april|may|june|july|august|september|october|november|december)", "in"),
        (r"during (january|february|march|april|may|june|july|august|september|october|november|december)", "during"),
        (r"(january|february|march|april|may|june|july|august|september|october|november|december) (\d{4})", "specific_year"),
    ]
    
    for pattern, pattern_type in month_patterns:
        match = re.search(pattern, query_lower)
        if match:
            month_name = match.group(1)
            month_num = list(calendar.month_name).index(month_name.capitalize())
            
            if pattern_type == "specific_year":
                year = int(match.group(2))
            elif pattern_type == "last":
                # Last [month] means the most recent occurrence of that month
                if month_num <= current_datetime.month:
                    year = current_datetime.year
                else:
                    year = current_datetime.year - 1
            else:  # "in" or "during"
                # Default to current year if month hasn't passed, else last year
                if month_num <= current_datetime.month:
                    year = current_datetime.year
                else:
                    year = current_datetime.year - 1
            
            # Get first and last day of that month
            _, last_day = calendar.monthrange(year, month_num)
            start = f"{year:04d}-{month_num:02d}-01"
            end = f"{year:04d}-{month_num:02d}-{last_day:02d}"
            
            temporal_phrase = match.group(0)
            return {
                "has_temporal_intent": True,
                "start_date": start,
                "end_date": end,
                "temporal_context": f"{temporal_phrase} ({start} to {end})",
                "query_without_temporal": clean_remaining_query(query_lower, temporal_phrase),
                "confidence": 0.90
            }
    
    # === SEASONS ===
    
    # Season definitions (approximate)
    seasons = {
        "spring": (3, 5),   # March-May
        "summer": (6, 8),   # June-August
        "fall": (9, 11),    # September-November
        "autumn": (9, 11),  # September-November
        "winter": (12, 2),  # December-February (spans years)
    }
    
    season_patterns = [
        (r"last (spring|summer|fall|autumn|winter)", "last"),
        (r"this (spring|summer|fall|autumn|winter)", "this"),
    ]
    
    for pattern, pattern_type in season_patterns:
        match = re.search(pattern, query_lower)
        if match:
            season_name = match.group(1)
            start_month, end_month = seasons[season_name]
            
            if pattern_type == "last":
                if season_name == "winter":
                    # Last winter: most recent completed winter (Dec-Feb) before today.
                    if current_datetime.month in [1, 2]:
                        start_year = current_datetime.year - 2
                        end_year = current_datetime.year - 1
                    else:
                        start_year = current_datetime.year - 1
                        end_year = current_datetime.year
                    start = f"{start_year}-12-01"
                    end = f"{end_year}-02-28"  # Simplified, not handling leap years
                else:
                    # Last season: most recent occurrence before today.
                    if current_datetime.month > end_month:
                        year = current_datetime.year
                    else:
                        year = current_datetime.year - 1
                    start = f"{year}-{start_month:02d}-01"
                    end = f"{year}-{end_month:02d}-{calendar.monthrange(year, end_month)[1]:02d}"
            else:  # "this"
                year = current_datetime.year
                if season_name == "winter":
                    # This winter: Dec of current year to Feb of next year
                    start = f"{year}-12-01"
                    end = f"{year+1}-02-28"
                else:
                    start = f"{year}-{start_month:02d}-01"
                    end = f"{year}-{end_month:02d}-{calendar.monthrange(year, end_month)[1]:02d}"
            
            temporal_phrase = match.group(0)
            return {
                "has_temporal_intent": True,
                "start_date": start,
                "end_date": end,
                "temporal_context": f"{temporal_phrase} ({start} to {end})",
                "query_without_temporal": clean_remaining_query(query_lower, temporal_phrase),
                "confidence": 0.85
            }
    
    # === HOLIDAYS ===
    
    # Christmas patterns
    if "last christmas" in query_lower:
        last_dec = current_datetime.replace(year=current_datetime.year-1, month=12, day=25)
        start = (last_dec - timedelta(days=7)).strftime('%Y-%m-%d')
        end = (last_dec + timedelta(days=7)).strftime('%Y-%m-%d')
        return {
            "has_temporal_intent": True,
            "start_date": start,
            "end_date": end,
            "temporal_context": f"last Christmas ({start} to {end})",
            "query_without_temporal": clean_remaining_query(query_lower, "last christmas"),
            "confidence": 0.90
        }
    
    if "this christmas" in query_lower or "christmas" in query_lower:
        this_dec = current_datetime.replace(month=12, day=25)
        # If it's past Christmas, refer to this year's Christmas, otherwise next year's
        if current_datetime.month == 12 and current_datetime.day > 25:
            this_dec = this_dec.replace(year=current_datetime.year + 1)
        start = (this_dec - timedelta(days=7)).strftime('%Y-%m-%d')
        end = (this_dec + timedelta(days=7)).strftime('%Y-%m-%d')
        temporal_phrase = "this christmas" if "this christmas" in query_lower else "christmas"
        return {
            "has_temporal_intent": True,
            "start_date": start,
            "end_date": end,
            "temporal_context": f"{temporal_phrase} ({start} to {end})",
            "query_without_temporal": clean_remaining_query(query_lower, temporal_phrase),
            "confidence": 0.90
        }
    
    # If no patterns match, fall back to AI processing
    # Import here to avoid circular imports
    from ..core.ai import extract_temporal_intent_ai
    return extract_temporal_intent_ai(query, model=model, client=client)


def get_season_for_date(date):
    """Get the season name for a given date"""
    month = date.month
    if month in [12, 1, 2]:
        return "winter"
    elif month in [3, 4, 5]:
        return "spring"
    elif month in [6, 7, 8]:
        return "summer"
    else:  # 9, 10, 11
        return "fall"


def get_month_name(month_num):
    """Get month name from number"""
    return calendar.month_name[month_num]
