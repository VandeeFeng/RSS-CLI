from langchain.tools import Tool, StructuredTool
from rss.feeds import get_feeds_by_category, get_available_categories, get_feed_by_name, get_all_feeds
from database.db import SessionLocal
from database.models import Feed as DBFeed, FeedEntry
from datetime import datetime, timedelta
from dateutil.parser import parse
from dateutil.tz import tzutc
from langchain_ollama import OllamaEmbeddings
from config import config
from rss.rss_fetcher import RSSFetcher
from contextlib import contextmanager
import logging
import json
from crawl4ai import AsyncWebCrawler
import asyncio
from pydantic.v1 import BaseModel, Field
from typing import Optional

# Initialize embeddings model
embeddings_model = OllamaEmbeddings(
    base_url=config.ollama.base_url,
    model=config.ollama.embedding_model
)

# Initialize RSS fetcher
rss_fetcher = RSSFetcher()

# Initialize logger
logger = logging.getLogger(__name__)

@contextmanager
def get_db_session():
    """Create a new database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_category_feeds_info(category: str) -> str:
    """Get information about feeds in a specific category"""
    with get_db_session() as db:
        try:
            # Get all feeds from database
            all_feeds = db.query(DBFeed).all()
            
            # Get configured categories
            categories = get_available_categories()
            
            # Try to match category (case-insensitive)
            matched_category = next(
                (cat for cat in categories if cat.lower() == category.lower()),
                None
            )
            
            if not matched_category:
                return json.dumps({
                    "success": False,
                    "error": f"Category '{category}' not found",
                    "available_categories": list(categories)
                })
            
            # Filter feeds by category
            category_feeds = [
                feed for feed in all_feeds
                if any(f.url == feed.url for f in get_feeds_by_category(matched_category))
            ]
            
            feeds_info = []
            for db_feed in category_feeds:
                # Get recent entries
                recent_time = datetime.now() - timedelta(hours=24)  # Last 24 hours
                recent_entries = (
                    db.query(FeedEntry)
                    .filter(FeedEntry.feed_id == db_feed.id)
                    .filter(FeedEntry.published_date >= recent_time)
                    .order_by(FeedEntry.published_date.desc())
                    .limit(5)
                    .all()
                )
                
                feeds_info.append({
                    "name": db_feed.name,
                    "url": db_feed.url,
                    "status": "Active",
                    "description": db_feed.description,
                    "last_updated": db_feed.last_updated.isoformat() if db_feed.last_updated else None,
                    "entries": [
                        {
                            "title": entry.title,  # Entry title
                            "link": entry.link,
                            "published": entry.published_date.isoformat() if entry.published_date else None
                        }
                        for entry in recent_entries
                    ]
                })
            
            return json.dumps({
                "success": True,
                "category": matched_category,
                "feeds_count": len(feeds_info),
                "feeds": feeds_info
            })
            
        except Exception as e:
            logger.error(f"Error getting category feeds info: {str(e)}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

def get_feed_details(feed_name: str) -> str:
    """
    Get detailed information about a specific feed, including all its entries
    
    Args:
        feed_name: Name of the feed (e.g., "Hacker News", "TechCrunch")
    
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - error: error message if any
        - feed: detailed feed information and entries
    """
    with get_db_session() as db:
        # Clean feed name by removing extra whitespace and newlines
        feed_name = feed_name.strip()
        
        # Get feed configuration
        feed_config = get_feed_by_name(feed_name)
        if not feed_config:
            error_response = {
                "success": False,
                "error": f"Feed '{feed_name}' not found in configuration",
                "feed": None
            }
            return json.dumps(error_response)
        
        try:
            # Get feed from database
            db_feed = db.query(DBFeed).filter(DBFeed.url == feed_config.url).first()
            
            if not db_feed:
                response = {
                    "success": True,
                    "feed": {
                        "name": feed_config.name,
                        "url": feed_config.url,
                        "status": "Not fetched yet",
                        "entries_count": 0,
                        "entries": []
                    }
                }
                return json.dumps(response)
            
            # Get all entries, ordered by publication date
            entries = (
                db.query(FeedEntry)
                .filter(FeedEntry.feed_id == db_feed.id)
                .order_by(FeedEntry.published_date.desc())
                .all()
            )
            
            # Group entries by time period
            now = datetime.now(tzutc())  # Use UTC timezone
            entries_by_period = {
                "last_24h": [],
                "last_week": [],
                "last_month": [],
                "older": []
            }
            
            for entry in entries:
                if not entry.published_date:
                    continue
                    
                age = now - entry.published_date
                entry_info = {
                    "title": entry.title,  # Entry title
                    "link": entry.link,
                    "published": entry.published_date.isoformat(),
                    "content_preview": entry.content[:200] + "..." if len(entry.content) > 200 else entry.content
                }
                
                if age < timedelta(hours=24):
                    entries_by_period["last_24h"].append(entry_info)
                elif age < timedelta(days=7):
                    entries_by_period["last_week"].append(entry_info)
                elif age < timedelta(days=30):
                    entries_by_period["last_month"].append(entry_info)
                else:
                    entries_by_period["older"].append(entry_info)
            
            feed_info = {
                "name": feed_config.name,
                "url": feed_config.url,
                "status": "Active",
                "description": db_feed.description,
                "last_updated": db_feed.last_updated.isoformat() if db_feed.last_updated else None,
                "entries_count": len(entries),
                "entries_by_period": {
                    "last_24h": {
                        "count": len(entries_by_period["last_24h"]),
                        "entries": entries_by_period["last_24h"]
                    },
                    "last_week": {
                        "count": len(entries_by_period["last_week"]),
                        "entries": entries_by_period["last_week"]
                    },
                    "last_month": {
                        "count": len(entries_by_period["last_month"]),
                        "entries": entries_by_period["last_month"]
                    },
                    "older": {
                        "count": len(entries_by_period["older"]),
                        "entries": entries_by_period["older"]
                    }
                }
            }
            
            response = {
                "success": True,
                "feed": feed_info
            }
            return json.dumps(response)
            
        except Exception as e:
            error_response = {
                "success": False,
                "error": str(e),
                "feed": None
            }
            return json.dumps(error_response)

class SearchFeedsArgs(BaseModel):
    query: str = Field(description="Search query describing the topic of interest (e.g., 'AI research', 'tech news')")
    time_filter: Optional[str] = Field(None, description='Filter feeds by update time ("24h", "week", "month", None for all)')
    sort_by: Optional[str] = Field("relevance", description='How to sort results ("relevance", "recent", "combined")')
    limit: Optional[int] = Field(5, description="Maximum number of results to return")

def search_related_feeds(query: str, time_filter: str = None, sort_by: str = "relevance", limit: int = 5) -> str:
    """
    Search for feeds and entries related to the given query using semantic search with advanced filtering
    
    Args:
        query: Search query (e.g., "AI news", "programming tutorials")
        time_filter: Filter feeds by update time ("24h", "week", "month", None for all)
        sort_by: How to sort results ("relevance", "recent", "combined")
        limit: Maximum number of results to return
    
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - error: error message if any
        - feeds: list of related feeds with their recent entries
        - entries: list of directly related entries
        - query: original search query
    """
    with get_db_session() as db:
        try:
            # First try to find directly related entries using semantic search
            fetcher = RSSFetcher()
            similar_entries = fetcher.search_similar_entries(query, limit=limit*2)
            
            if not similar_entries:
                return json.dumps({
                    "success": True,
                    "query": query,
                    "time_filter": time_filter,
                    "sort_by": sort_by,
                    "feeds_found": 0,
                    "feeds": [],
                    "entries_found": 0,
                    "entries": [],
                    "message": "No semantically similar entries found"
                })
            
            # Apply time filter if specified
            now = datetime.now(tzutc())
            time_deltas = {
                "24h": timedelta(hours=24),
                "week": timedelta(days=7),
                "month": timedelta(days=30)
            }
            
            # Group entries by feed and calculate feed relevance
            feed_scores = {}
            entries_by_feed = {}
            feed_last_updated = {}
            
            for entry in similar_entries:
                feed_id = entry.feed_id
                
                # Get feed and check time filter if specified
                feed = db.query(DBFeed).filter(DBFeed.id == feed_id).first()
                if not feed or not feed.last_updated:
                    continue
                    
                if time_filter:
                    delta = time_deltas.get(time_filter)
                    if delta and now - feed.last_updated > delta:
                        continue
                
                # Initialize feed data
                if feed_id not in feed_scores:
                    feed_scores[feed_id] = 0
                    entries_by_feed[feed_id] = []
                    feed_last_updated[feed_id] = feed.last_updated
                
                # Calculate entry score based on semantic relevance and recency
                time_score = 1.0
                if entry.published_date:
                    age = now - entry.published_date
                    # Decay score based on age (1.0 to 0.5 over a month)
                    time_score = max(0.5, 1.0 - (age.total_seconds() / (30 * 24 * 3600)) * 0.5)
                
                # Entries are already sorted by semantic similarity
                semantic_position = similar_entries.index(entry)
                semantic_score = 1.0 - (semantic_position / len(similar_entries))
                
                # Combined score weights semantic relevance more heavily
                combined_score = (semantic_score * 0.7) + (time_score * 0.3)
                
                feed_scores[feed_id] += combined_score
                entries_by_feed[feed_id].append((entry, combined_score))
            
            if not feed_scores:
                return json.dumps({
                    "success": True,
                    "query": query,
                    "time_filter": time_filter,
                    "sort_by": sort_by,
                    "feeds_found": 0,
                    "feeds": [],
                    "entries_found": 0,
                    "entries": [],
                    "message": "No feeds match the time filter criteria"
                })
            
            # Sort feeds based on specified criteria
            if sort_by == "recent":
                sorted_feeds = sorted(feed_scores.keys(), 
                                   key=lambda x: feed_last_updated[x],
                                   reverse=True)
            elif sort_by == "combined":
                # Combine relevance score with recency
                sorted_feeds = sorted(feed_scores.keys(),
                                   key=lambda x: (feed_scores[x] * 0.7 + 
                                                (1.0 - (now - feed_last_updated[x]).total_seconds() / 
                                                (30 * 24 * 3600)) * 0.3),
                                   reverse=True)
            else:  # default to relevance
                sorted_feeds = sorted(feed_scores.keys(),
                                   key=lambda x: feed_scores[x],
                                   reverse=True)
            
            # Get feed information
            feeds_info = []
            entries_info = []
            seen_entries = set()
            
            # Process feeds in sorted order
            for feed_id in sorted_feeds[:limit]:
                feed = db.query(DBFeed).filter(DBFeed.id == feed_id).first()
                if not feed:
                    continue
                
                # Sort feed entries by score
                sorted_entries = sorted(entries_by_feed[feed_id],
                                     key=lambda x: x[1],  # Sort by combined score
                                     reverse=True)
                
                # Format feed info
                feeds_info.append({
                    "name": feed.name,
                    "url": feed.url,
                    "description": feed.description,
                    "relevance_score": round(feed_scores[feed_id] / len(similar_entries), 3),
                    "last_updated": feed.last_updated.isoformat() if feed.last_updated else None,
                    "matching_entries": [
                        {
                            "title": entry.title,
                            "link": entry.link,
                            "published": entry.published_date.isoformat() if entry.published_date else None,
                            "content_preview": entry.content[:200] + "..." if len(entry.content) > 200 else entry.content,
                            "relevance_score": round(score, 3)
                        }
                        for entry, score in sorted_entries[:3]  # Top 3 entries per feed
                    ]
                })
                
                # Add entries to the separate entries list
                for entry, score in sorted_entries:
                    if entry.id not in seen_entries and len(entries_info) < limit:
                        entries_info.append({
                            "title": entry.title,
                            "link": entry.link,
                            "content_preview": entry.content[:200] + "..." if len(entry.content) > 200 else entry.content,
                            "published": entry.published_date.isoformat() if entry.published_date else None,
                            "relevance_score": round(score, 3),
                            "feed": {
                                "id": feed.id,
                                "title": feed.name,
                                "url": feed.url
                            }
                        })
                        seen_entries.add(entry.id)
            
            response = {
                "success": True,
                "query": query,
                "time_filter": time_filter,
                "sort_by": sort_by,
                "feeds_found": len(feeds_info),
                "feeds": feeds_info,
                "entries_found": len(entries_info),
                "entries": entries_info
            }
            return json.dumps(response)
            
        except Exception as e:
            logger.error(f"Error in search_related_feeds: {str(e)}")
            error_response = {
                "success": False,
                "error": str(e),
                "query": query,
                "feeds": [],
                "entries": []
            }
            return json.dumps(error_response)

def fetch_feed_content(feed_name: str) -> str:
    """
    Fetch latest content for a specific RSS feed
    
    Args:
        feed_name: Name of the feed to fetch
        
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - error: error message if any
        - feed: feed information if successful
    """
    try:
        # Clean feed name by removing extra whitespace and newlines
        feed_name = feed_name.strip()
        
        feed_config = get_feed_by_name(feed_name)
        if not feed_config:
            error_response = {
                "success": False,
                "error": f"Feed '{feed_name}' not found in configuration",
                "feed": None
            }
            return json.dumps(error_response)
        
        with get_db_session() as db:
            try:
                # First try to fetch the feed
                result = rss_fetcher.fetch_feed(feed_config.url)
                if not result:
                    error_response = {
                        "success": False,
                        "error": f"Failed to fetch feed: {feed_name}",
                        "feed": None
                    }
                    return json.dumps(error_response)
                
                # Make sure the result is bound to our session
                result = db.merge(result)
                
                # Return feed info from the committed object
                response = {
                    "success": True,
                    "feed": {
                        "name": feed_config.name,
                        "url": feed_config.url,
                        "description": result.description,
                        "last_updated": result.last_updated.isoformat() if result.last_updated else None
                    }
                }
                return json.dumps(response)
            except Exception as e:
                logger.error(f"Error in fetch_feed_content: {str(e)}")
                error_response = {
                    "success": False,
                    "error": str(e),
                    "feed": None
                }
                return json.dumps(error_response)
            
    except Exception as e:
        logger.error(f"Error in fetch_feed_content: {str(e)}")
        error_response = {
            "success": False,
            "error": str(e),
            "feed": None
        }
        return json.dumps(error_response)

def get_all_categories() -> str:
    """
    Get a list of all available feed categories
    
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - categories: list of category names and their feed counts
    """
    try:
        categories = get_available_categories()
        category_info = []
        
        for category in categories:
            feeds = get_feeds_by_category(category)
            category_info.append({
                "name": category,
                "feed_count": len(feeds)
            })
        
        response = {
            "success": True,
            "categories": category_info,
            "total_categories": len(categories)
        }
        return json.dumps(response)
        
    except Exception as e:
        error_response = {
            "success": False,
            "error": str(e),
            "categories": []
        }
        return json.dumps(error_response)

# Create the LangChain tools
get_all_categories_tool = Tool(
    name="get_all_categories",
    description="""
    Get a list of all available RSS feed categories.
    This tool returns all category names and the number of feeds in each category.
    
    Returns:
        List of all categories with:
        - Category names
        - Number of feeds in each category
        - Total number of categories
    
    Use this tool first to discover available categories before using get_category_feeds.
    """,
    func=get_all_categories
)

get_category_feeds_tool = Tool(
    name="get_category_feeds",
    description="""
    Get information about all RSS feeds in a specific category.
    This tool returns details about the feeds and their recent entries.
    
    Args:
        category (str): The category to get feeds for (e.g., 'tech', 'programming', 'ai')
        
    Returns:
        Information about all feeds in the category, including:
        - Feed names and URLs
        - Feed status (Active/Not fetched)
        - Recent entries (last 24 hours)
        - Last update time
        
    First use get_all_categories to see available categories, then use this tool to get details for a specific category.
    """,
    func=get_category_feeds_info
)

get_feed_details_tool = Tool(
    name="get_feed_details",
    description="""
    Get detailed information about a specific RSS feed by its name.
    This tool returns comprehensive information about the feed and all its entries.
    
    Args:
        feed_name (str): Name of the feed (e.g., "Hacker News", "TechCrunch")
        
    Returns:
        Detailed feed information, including:
        - Feed metadata (name, URL, title, description)
        - Last update time
        - All entries, grouped by time period (24h, week, month, older)
        - Entry counts for each time period
        - Content previews and links
    """,
    func=get_feed_details
)

search_related_feeds_tool = StructuredTool.from_function(
    func=search_related_feeds,
    name="search_related_feeds",
    description="""
    Search for feeds and entries related to a given topic or query using semantic search with advanced filtering.
    This tool uses HNSW index for efficient vector similarity search and supports time-based filtering.
    
    Args:
        query (str): Search query describing the topic of interest (e.g., "AI research", "tech news")
        time_filter (str, optional): Filter feeds by update time ("24h", "week", "month", None for all)
        sort_by (str, optional): How to sort results ("relevance", "recent", "combined")
        limit (int, optional): Maximum number of results to return (default: 5)
        
    Returns:
        Information about related content, including:
        - Related feeds sorted by chosen criteria (relevance/recency/combined)
        - Matching entries from these feeds with relevance scores
        - Content previews and links
        - Publication dates
        Results can be filtered by time and sorted by different criteria.
    """,
    args_schema=SearchFeedsArgs,
)

fetch_feed_tool = Tool(
    name="fetch_feed",
    description="""
    Fetch latest content for an RSS feed by its name.
    This tool will fetch new entries from the feed and store them in the database.
    
    Args:
        feed_name (str): Name of the feed to fetch (e.g., "Hacker News", "TechCrunch")
        
    Returns:
        Information about the fetched feed, including:
        - Feed metadata
        - Last update time
        - Success/failure status
    """,
    func=fetch_feed_content
)

# New function and tool for crawling URL content
async def crawl_url_content_async(url: str) -> str:
    """
    Crawl the content of a given URL using Crawl4ai asynchronously.
    
    Args:
        url: The URL to crawl
        
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - error: error message if any
        - url: the crawled URL
        - content: the crawled content (Markdown format)
        - summary: a brief summary of the content
        - next_steps: suggested next steps for processing this content
    """
    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=None)
        
            if result and result.markdown:
                content = result.markdown
                
                # Extract meaningful summary
                # First try to get the first paragraph that's not too short
                paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
                summary = ""
                
                # Look for a good first paragraph (at least 50 chars but not too long)
                for para in paragraphs:
                    if len(para) >= 50 and len(para) <= 300:
                        summary = para
                        break
                
                # If no good paragraph found, use smart truncation
                if not summary:
                    # Take first paragraph but ensure we don't cut mid-sentence
                    first_para = paragraphs[0] if paragraphs else content
                    if len(first_para) > 300:
                        # Find the last complete sentence within 300 chars
                        truncated = first_para[:300]
                        last_period = max(
                            truncated.rfind('.'),
                            truncated.rfind('!'),
                            truncated.rfind('?')
                        )
                        if last_period > 50:  # Ensure we have a decent length
                            summary = first_para[:last_period + 1]
                        else:
                            # If no good sentence break, use the first 300 chars
                            summary = truncated + "..."
                    else:
                        summary = first_para
                
                # Add content length info to summary
                summary = f"{summary}\n\nArticle length: {len(content)} characters."
                
                response = {
                    "success": True,
                    "url": url,
                    "content": content,  # Keep the full content
                    "summary": summary,
                    "next_steps": [
                        "Review the summary for relevance",
                        "Use process_long_content tool if you need to focus on specific parts",
                        "Extract key information based on the user's query"
                    ]
                }
            else:
                response = {
                    "success": False,
                    "error": "Failed to crawl content or content is empty.",
                    "url": url,
                    "content": None,
                    "summary": None,
                    "next_steps": ["Try an alternative URL", "Report the crawling failure"]
                }
            return json.dumps(response)
        
    except Exception as e:
        logger.error(f"Error in crawl_url_content_async for url {url}: {str(e)}")
        error_response = {
            "success": False,
            "error": str(e),
            "url": url,
            "content": None,
            "summary": None,
            "next_steps": ["Handle the error", "Try an alternative URL"]
        }
        return json.dumps(error_response)

def crawl_url_content(url: str) -> str:
    """Synchronous wrapper for crawl_url_content_async."""
    try:
        return asyncio.run(crawl_url_content_async(url))
    except Exception as e:
        logger.error(f"Error running async crawl_url_content for {url}: {str(e)}")
        error_response = {
            "success": False,
            "error": f"Asyncio execution error: {str(e)}",
            "url": url,
            "content": None,
            "summary": None,
            "next_steps": ["Handle the error", "Try an alternative URL"]
        }
        return json.dumps(error_response)

crawl_url_tool = Tool(
    name="crawl_url_content",
    description="""
    Crawl the main content of a web page given its URL.
    This tool uses Crawl4ai to extract the article or main content from a URL and returns it in Markdown format.
    
    IMPORTANT: Input should be a direct URL string, NOT a JSON object.
    Example: "https://example.com/article" (correct)
    NOT: {"url": "https://example.com/article"} (wrong)
    
    The response includes:
    - The main content
    - A brief summary
    - Suggested next steps for processing
    - The original URL for reference
    
    After getting the content, you should:
    1. Summarize the main points in a few sentences
    2. Extract relevant information based on the user's query
    3. Always provide the source URL
    
    Args:
        url (str): The direct URL string of the web page to crawl.
        
    Returns:
        A JSON string containing the content, summary, and next steps.
    """,
    func=crawl_url_content
)

class ProcessContentArgs(BaseModel):
    content: str = Field(description="The content to process")
    query: Optional[str] = Field(None, description="Optional query to focus the extraction")
    max_length: int = Field(1000, description="Maximum length of processed content")

def process_long_content(content: str, query: str = None, max_length: int = 1000) -> str:
    """
    Process long content and extract relevant information.
    
    Args:
        content: The content to process
        query: Optional query to focus the extraction
        max_length: Maximum length of processed content
        
    Returns:
        JSON string containing processed information
    """
    try:
        # If content is not too long, return as is
        if len(content) <= max_length:
            return json.dumps({
                "success": True,
                "content": content,
                "is_truncated": False
            })
            
        # If we have a query, try to extract relevant sections
        if query:
            # Split content into paragraphs
            paragraphs = content.split('\n\n')
            
            # Score paragraphs based on relevance to query
            relevant_paragraphs = []
            for para in paragraphs:
                # Simple relevance check - can be improved with embeddings
                if any(term.lower() in para.lower() for term in query.split()):
                    relevant_paragraphs.append(para)
            
            # Combine relevant paragraphs up to max_length
            processed_content = ""
            for para in relevant_paragraphs:
                if len(processed_content) + len(para) + 2 <= max_length:
                    processed_content += para + "\n\n"
                else:
                    break
                    
            return json.dumps({
                "success": True,
                "content": processed_content.strip(),
                "is_truncated": True,
                "original_length": len(content),
                "processed_length": len(processed_content)
            })
            
        # If no query, take the first and last parts
        start = content[:max_length//2]
        end = content[-max_length//2:]
        
        return json.dumps({
            "success": True,
            "content": f"{start}\n\n[...content truncated...]\n\n{end}",
            "is_truncated": True,
            "original_length": len(content),
            "processed_length": max_length
        })
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "content": None
        })

process_content_tool = StructuredTool.from_function(
    func=process_long_content,
    name="process_long_content",
    description="""
    Process and extract relevant information from long content.
    Useful when dealing with large articles or documents.
    Can focus extraction based on a specific query.
    
    Args:
        content: The content to process
        query: Optional query to focus the extraction
        max_length: Maximum length of processed content
        
    Returns:
        Processed and potentially shortened content, focusing on relevant parts.
    """,
    args_schema=ProcessContentArgs,
)

def find_feeds(query: str) -> str:
    """
    Find feeds by partial name match in database
    
    Args:
        query: Search term to find in feed names (case-insensitive partial match)
        
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - feeds: list of matching feeds with their details
        - total_feeds: number of feeds found
    """
    with get_db_session() as db:
        try:
            # Use LIKE for partial name matching (case-insensitive)
            feeds = db.query(DBFeed).filter(DBFeed.name.ilike(f"%{query}%")).all()
            
            if not feeds:
                return json.dumps({
                    "success": True,
                    "feeds": [],
                    "total_feeds": 0
                })
            
            # Format feed information
            feeds_info = []
            for feed in feeds:
                feeds_info.append({
                    "id": feed.id,
                    "name": feed.name,
                    "url": feed.url
                })
            
            return json.dumps({
                "success": True,
                "feeds": feeds_info,
                "total_feeds": len(feeds_info)
            })
            
        except Exception as e:
            logger.error(f"Error in find_feeds: {str(e)}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "feeds": [],
                "total_feeds": 0
            })

# Create the find_feeds tool
find_feeds_tool = Tool(
    name="find_feeds",
    description="""
    Find RSS feeds by searching for partial matches in their names.
    The search is case-insensitive and will find any feed names that contain the search term.
    
    Args:
        query: Search term to find in feed names (case-insensitive partial match)
        
    Returns:
        Matching feeds with their basic details (id, name, url)
    """,
    func=find_feeds
)

# Update the tools list
tools = [
    get_feed_details_tool,
    get_category_feeds_tool,
    fetch_feed_tool,
    search_related_feeds_tool,
    find_feeds_tool,  
    crawl_url_tool,
    process_content_tool
]

# MCP tools
def list_feeds() -> str:
    """
    List all available feeds grouped by category
    
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - categories: list of categories with their feeds
    """
    # Reuse get_all_categories and get_category_feeds_info
    try:
        # Get all categories first
        categories_data = json.loads(get_all_categories())
        if not categories_data["success"]:
            return json.dumps(categories_data)
            
        # Get feeds for each category
        result = {
            "success": True,
            "categories": []
        }
        
        total_feeds = 0
        for cat_info in categories_data["categories"]:
            category_name = cat_info["name"]
            # Get detailed feed info for this category
            feeds_data = json.loads(get_category_feeds_info(category_name))
            if feeds_data["success"]:
                result["categories"].append({
                    "name": category_name,
                    "feeds": [
                        {
                            "name": feed["name"],
                            "url": feed["url"],
                            "description": feed.get("description", "")
                        }
                        for feed in feeds_data["feeds"]
                    ],
                    "feed_count": feeds_data["feeds_count"]
                })
                total_feeds += feeds_data["feeds_count"]
        
        result["total_categories"] = len(result["categories"])
        result["total_feeds"] = total_feeds
        return json.dumps(result)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "categories": []
        })

def search_feeds(query: str) -> str:
    """
    Search for RSS feeds by title or URL
    
    Args:
        query: Search term to find in feed titles or URLs
        
    Returns:
        JSON string containing matching feeds
    """
    # Reuse search_related_feeds
    try:
        search_results = json.loads(search_related_feeds(query))
        if not search_results["success"]:
            return json.dumps(search_results)
            
        # Convert to MCP format
        return json.dumps({
            "success": True,
            "results": [
                {
                    "name": feed["name"],
                    "url": feed["url"],
                    "title": feed["title"],
                    "description": feed.get("description", ""),
                    "relevance_score": feed.get("relevance_score", 0)
                }
                for feed in search_results["feeds"]
            ],
            "total_results": search_results["feeds_found"]
        })
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "results": []
        })

def get_feed_summary(feed_id: int) -> str:
    """
    Get a summary of a feed including its latest entries
    
    Args:
        feed_id: ID of the feed to get summary for
        
    Returns:
        JSON string containing feed summary and latest entries
    """
    with get_db_session() as db:
        try:
            # Get feed from database
            db_feed = db.query(DBFeed).filter(DBFeed.id == feed_id).first()
            if not db_feed:
                return json.dumps({
                    "success": False,
                    "error": f"Feed with ID {feed_id} not found",
                    "feed": None
                })
            
            # Reuse get_feed_details logic
            feed_details = json.loads(get_feed_details(db_feed.name))
            if not feed_details["success"]:
                return json.dumps(feed_details)
            
            # Convert to MCP format
            return json.dumps({
                "success": True,
                "feed": {
                    "id": feed_id,
                    "title": db_feed.name,
                    "url": db_feed.url,
                    "description": db_feed.description,
                    "last_updated": db_feed.last_updated.isoformat() if db_feed.last_updated else None
                },
                "latest_entries": feed_details["feed"]["entries_by_period"]["last_24h"]["entries"]
            })
            
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "feed": None,
                "latest_entries": []
            })

# Define MCP tools
list_feeds_tool = Tool(
    name="list_feeds_feeds_get",
    description="List all RSS feeds in the database.",
    func=list_feeds
)

search_feeds_tool = Tool(
    name="search_feeds_feeds_search_post",
    description="Search for RSS feeds by title or URL.",
    func=search_feeds
)

get_feed_summary_tool = Tool(
    name="get_feed_summary_feeds_feed_id_summary_get",
    description="Get a summary of a feed including its latest entries.",
    func=get_feed_summary
)