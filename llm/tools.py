from typing import List, Dict, Optional, Any
from langchain.tools import Tool
from rss.feeds import get_feeds_by_category, get_available_categories, get_feed_by_name, get_all_feeds
from database.db import SessionLocal
from database.models import Feed as DBFeed, FeedEntry
from datetime import datetime, timedelta
from langchain_community.embeddings import OllamaEmbeddings
from config import config
from rss.rss_fetcher import RSSFetcher
from contextlib import contextmanager
import logging
import json
from crawl4ai import AsyncWebCrawler
import asyncio

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
    """
    Get information about all feeds in a specific category, including their latest entries
    
    Args:
        category: The category to get feeds for
    
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - error: error message if any
        - category: the requested category
        - feeds: list of feeds with their latest entries
    """
    with get_db_session() as db:
        # Validate category
        available_categories = get_available_categories()
        if category not in available_categories:
            error_response = {
                "success": False,
                "error": f"Category '{category}' not found. Available categories: {', '.join(available_categories)}",
                "category": category,
                "feeds": []
            }
            return json.dumps(error_response)
        
        try:
            feeds_info = []
            
            # Get configured feeds for this category
            configured_feeds = get_feeds_by_category(category)
            
            for feed_config in configured_feeds:
                # Get feed from database
                db_feed = db.query(DBFeed).filter(DBFeed.url == feed_config.url).first()
                
                if not db_feed:
                    feeds_info.append({
                        "name": feed_config.name,
                        "url": feed_config.url,
                        "status": "Not fetched yet",
                        "entries": []
                    })
                    continue
                
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
                    "name": feed_config.name,
                    "url": feed_config.url,
                    "status": "Active",
                    "title": db_feed.title,
                    "last_updated": db_feed.last_updated.isoformat() if db_feed.last_updated else None,
                    "entries": [
                        {
                            "title": entry.title,
                            "link": entry.link,
                            "published": entry.published_date.isoformat() if entry.published_date else None
                        }
                        for entry in recent_entries
                    ]
                })
            
            response = {
                "success": True,
                "category": category,
                "feeds": feeds_info,
                "total_feeds": len(feeds_info)
            }
            return json.dumps(response)
            
        except Exception as e:
            error_response = {
                "success": False,
                "error": str(e),
                "category": category,
                "feeds": []
            }
            return json.dumps(error_response)

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
            now = datetime.now()
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
                    "title": entry.title,
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
                "title": db_feed.title,
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

def search_related_feeds(query: str) -> str:
    """
    Search for feeds related to the given query using semantic search
    
    Args:
        query: Search query (e.g., "AI news", "programming tutorials")
    
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - error: error message if any
        - feeds: list of related feeds with their recent entries
        - query: original search query
    """
    with get_db_session() as db:
        try:
            all_feeds = get_all_feeds()
            
            # Create search context for each feed
            feed_contexts = []
            for feed_config in all_feeds:
                db_feed = db.query(DBFeed).filter(DBFeed.url == feed_config.url).first()
                if not db_feed:
                    continue
                    
                # Get recent entries for context
                recent_entries = (
                    db.query(FeedEntry)
                    .filter(FeedEntry.feed_id == db_feed.id)
                    .order_by(FeedEntry.published_date.desc())
                    .limit(5)
                    .all()
                )
                
                # Create context from feed metadata and recent entries
                context = f"{db_feed.title}\n{db_feed.description}\n"
                for entry in recent_entries:
                    context += f"{entry.title}\n{entry.content[:200]}\n"
                
                feed_contexts.append({
                    "feed": feed_config,
                    "db_feed": db_feed,
                    "context": context
                })
            
            # Get embeddings for the query and all feed contexts
            query_embedding = embeddings_model.embed_query(query)
            
            # Calculate similarity scores
            results = []
            for feed_context in feed_contexts:
                context_embedding = embeddings_model.embed_query(feed_context["context"])
                similarity = sum(q * c for q, c in zip(query_embedding, context_embedding))
                results.append({
                    "feed": feed_context["feed"],
                    "db_feed": feed_context["db_feed"],
                    "similarity": similarity
                })
            
            # Sort by similarity score
            results.sort(key=lambda x: x["similarity"], reverse=True)
            
            # Format results
            feeds_info = []
            for result in results[:5]:  # Top 5 most relevant feeds
                db_feed = result["db_feed"]
                
                # Get recent entries
                recent_entries = (
                    db.query(FeedEntry)
                    .filter(FeedEntry.feed_id == db_feed.id)
                    .order_by(FeedEntry.published_date.desc())
                    .limit(3)
                    .all()
                )
                
                feeds_info.append({
                    "name": result["feed"].name,
                    "url": result["feed"].url,
                    "title": db_feed.title,
                    "description": db_feed.description,
                    "relevance_score": round(result["similarity"], 3),
                    "last_updated": db_feed.last_updated.isoformat() if db_feed.last_updated else None,
                    "recent_entries": [
                        {
                            "title": entry.title,
                            "link": entry.link,
                            "published": entry.published_date.isoformat() if entry.published_date else None,
                            "content_preview": entry.content[:200] + "..." if len(entry.content) > 200 else entry.content
                        }
                        for entry in recent_entries
                    ]
                })
            
            response = {
                "success": True,
                "query": query,
                "feeds_found": len(feeds_info),
                "feeds": feeds_info
            }
            return json.dumps(response)
            
        except Exception as e:
            error_response = {
                "success": False,
                "error": str(e),
                "query": query,
                "feeds": []
            }
            return json.dumps(error_response)

def fetch_and_update_feed(feed_name: str) -> str:
    """
    Fetch or update a specific RSS feed
    
    Args:
        feed_name: Name of the feed to fetch/update
        
    Returns:
        JSON string containing:
        - success: bool indicating if the operation was successful
        - error: error message if any
        - feed: feed information if successful
    """
    try:
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
                        "title": result.title,
                        "description": result.description,
                        "last_updated": result.last_updated.isoformat() if result.last_updated else None
                    }
                }
                return json.dumps(response)
            except Exception as e:
                logger.error(f"Error in fetch_and_update_feed: {str(e)}")
                error_response = {
                    "success": False,
                    "error": str(e),
                    "feed": None
                }
                return json.dumps(error_response)
            
    except Exception as e:
        logger.error(f"Error in fetch_and_update_feed: {str(e)}")
        error_response = {
            "success": False,
            "error": str(e),
            "feed": None
        }
        return json.dumps(error_response)

# Create the LangChain tools
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

search_related_feeds_tool = Tool(
    name="search_related_feeds",
    description="""
    Search for RSS feeds related to a given topic or query using semantic search.
    This tool helps find feeds that are semantically related to the user's interests.
    
    Args:
        query (str): Search query describing the topic of interest (e.g., "AI research", "tech news")
        
    Returns:
        Information about related feeds, including:
        - Feed metadata and relevance scores
        - Recent entries from each feed
        - Content previews and links
        Feeds are sorted by relevance to the query.
    """,
    func=search_related_feeds
)

fetch_feed_tool = Tool(
    name="fetch_feed",
    description="""
    Fetch or update an RSS feed by its name.
    This tool will fetch new entries from the feed and store them in the database.
    
    Args:
        feed_name (str): Name of the feed to fetch (e.g., "Hacker News", "TechCrunch")
        
    Returns:
        Information about the fetched feed, including:
        - Feed metadata
        - Last update time
        - Success/failure status
    """,
    func=fetch_and_update_feed
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
    """
    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=None)
        
            if result and result.markdown:
                response = {
                    "success": True,
                    "url": url,
                    "content": result.markdown
                }
            else:
                response = {
                    "success": False,
                    "error": "Failed to crawl content or content is empty.",
                    "url": url,
                    "content": None
                }
            return json.dumps(response)
        
    except Exception as e:
        logger.error(f"Error in crawl_url_content_async for url {url}: {str(e)}")
        error_response = {
            "success": False,
            "error": str(e),
            "url": url,
            "content": None
        }
        return json.dumps(error_response)

def crawl_url_content(url: str) -> str:
    """Synchronous wrapper for crawl_url_content_async."""
    try:
        return asyncio.run(crawl_url_content_async(url))
    except Exception as e:
        # Log the exception or handle it as needed
        logger.error(f"Error running async crawl_url_content for {url}: {str(e)}")
        # Potentially re-raise or return an error JSON if asyncio.run itself fails
        error_response = {
            "success": False,
            "error": f"Asyncio execution error: {str(e)}",
            "url": url,
            "content": None
        }
        return json.dumps(error_response)

crawl_url_tool = Tool(
    name="crawl_url_content",
    description="""
    Crawl the main content of a web page given its URL.
    This tool uses Crawl4ai to extract the article or main content from a URL and returns it in Markdown format.
    
    Args:
        url (str): The URL of the web page to crawl.
        
    Returns:
        The main content of the web page in Markdown format.
        Includes success status and error messages if any.
    """,
    func=crawl_url_content
) 