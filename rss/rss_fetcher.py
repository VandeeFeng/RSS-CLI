import logging
import feedparser
from typing import List, Optional
from datetime import datetime, timedelta
from dateutil.parser import parse
from dateutil.tz import tzlocal, tzutc
from langchain_ollama import OllamaEmbeddings
from config import config
from database.models import Feed as DBFeed, FeedEntry
from database.db import SessionLocal
from contextlib import contextmanager
import requests
from sqlalchemy.exc import IntegrityError
from . import FEED_CATEGORIES, _load_feeds
from sqlalchemy import text

logger = logging.getLogger('rss_ai')

# Define timezone info for common timezones
TZINFOS = {
    'EST': -18000,  # UTC-5 hours in seconds
    'EDT': -14400,  # UTC-4 hours in seconds
    'CST': -21600,  # UTC-6 hours
    'CDT': -18000,  # UTC-5 hours
    'MST': -25200,  # UTC-7 hours
    'MDT': -21600,  # UTC-6 hours
    'PST': -28800,  # UTC-8 hours
    'PDT': -25200,  # UTC-7 hours
    'GMT': 0,       # UTC
    'UTC': 0,
}

@contextmanager
def get_db_session():
    """Create a new database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class RSSFetcher:
    def __init__(self, debug: bool = False, max_entries: int = None, max_age_hours: int = None):
        self.debug = debug
        if debug:
            logger.setLevel(logging.DEBUG)
        
        # Initialize embeddings model
        self.embeddings = OllamaEmbeddings(
            base_url=config.ollama.base_url,
            model=config.ollama.embedding_model
        )
        
        # Set custom limits if provided
        self.max_entries = max_entries if max_entries is not None else config.rss.max_entries_per_feed
        self.max_age_hours = max_age_hours if max_age_hours is not None else config.rss.max_age_hours
        
        if debug:
            logger.debug(f"Initialized RSSFetcher with max_entries={self.max_entries}, max_age_hours={self.max_age_hours}")
    
    def fetch_feed(self, url: str) -> Optional[DBFeed]:
        # Reset counters at the start of each fetch
        self.entries_added = 0
        self.entries_skipped = 0
        
        try:
            # First try to fetch the raw content with requests
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            # Force UTF-8 encoding
            content = response.content.decode('utf-8', errors='replace')
            
            # Parse the content with feedparser
            feed_data = feedparser.parse(content)
            
            if not feed_data.feed or hasattr(feed_data, 'bozo_exception'):
                # If failed with direct content, try URL-based parsing as fallback
                feed_data = feedparser.parse(url)
                if not feed_data.feed or hasattr(feed_data, 'bozo_exception'):
                    logger.error(f"Could not fetch feed from {url}: {getattr(feed_data, 'bozo_exception', 'No feed data')}")
                    return None
                
            # Get feed description from multiple possible fields
            description = (
                feed_data.feed.get('description') or 
                feed_data.feed.get('subtitle') or 
                feed_data.feed.get('summary') or 
                feed_data.feed.get('tagline') or
                ''
            )
            
            if self.debug:
                logger.debug(f"Feed description: {description}")
                
            with get_db_session() as db:
                try:
                    # Check if feed already exists
                    existing_feed = db.query(DBFeed).filter(DBFeed.url == url).first()
                    current_time = datetime.now(tzutc())
                    
                    if existing_feed:
                        if self.debug:
                            logger.debug(f"Feed already exists: {url}")
                        # Update the feed name, description and last_updated
                        existing_feed.name = feed_data.feed.get('title', '')  # RSS feed title as name
                        existing_feed.description = description
                        existing_feed.last_updated = current_time
                        # Get category from feeds.json
                        if not FEED_CATEGORIES:
                            _load_feeds()
                        for cat, feeds in FEED_CATEGORIES.items():
                            if any(f.url == url for f in feeds):
                                existing_feed.category = cat
                                break
                        db.commit()
                        feed = db.merge(existing_feed)
                    else:
                        # Create new feed
                        if not FEED_CATEGORIES:
                            _load_feeds()
                        category = next((cat for cat, feeds in FEED_CATEGORIES.items() 
                                      if any(f.url == url for f in feeds)), None)
                        feed = DBFeed(
                            url=url,
                            name=feed_data.feed.get('title', ''),  # RSS feed title as name
                            description=description,
                            last_updated=current_time,
                            category=category
                        )
                        db.add(feed)
                        db.flush()

                    cutoff_time = current_time - timedelta(hours=self.max_age_hours)
                    
                    if self.debug:
                        logger.debug(f"Found {len(feed_data.entries)} entries")
                        logger.debug(f"Cutoff time: {cutoff_time}")
                        logger.debug(f"Max entries: {self.max_entries}")
                        logger.debug(f"Max age hours: {self.max_age_hours}")
                    
                    # Process entries in order (feedparser usually returns newest first)
                    for entry in feed_data.entries:
                        # Stop if we've reached the maximum number of entries
                        if self.entries_added >= self.max_entries:
                            if self.debug:
                                logger.debug(f"Reached maximum entries limit ({self.max_entries}), stopping")
                            break
                            
                        try:
                            # Parse published date first to check time limit
                            published = entry.get('published', entry.get('updated', entry.get('created')))
                            if published:
                                try:
                                    # First try to parse with timezone info
                                    published_date = parse(published, tzinfos=TZINFOS)
                                    # If no timezone info was found, assume UTC
                                    if published_date.tzinfo is None:
                                        published_date = published_date.replace(tzinfo=tzutc())
                                    # Convert to UTC for consistent comparison
                                    published_date = published_date.astimezone(tzutc())
                                except Exception as e:
                                    if self.debug:
                                        logger.warning(f"Error parsing date '{published}': {str(e)}")
                                    published_date = current_time
                            else:
                                if self.debug:
                                    logger.debug("No published date found, using current time")
                                published_date = current_time
                            
                            # Skip entries older than cutoff time
                            if published_date < cutoff_time:
                                if self.debug:
                                    logger.debug(f"Skipping entry: older than {self.max_age_hours} hours (published: {published_date}, cutoff: {cutoff_time})")
                                self.entries_skipped += 1
                                continue
                            
                            content = entry.get('content', [{}])[0].get('value', '') or entry.get('description', '')
                            title = entry.get('title', '')
                            link = entry.get('link', '')
                            
                            if not title or not content or not link:
                                if self.debug:
                                    logger.debug(f"Skipping entry: missing title, content, or link")
                                self.entries_skipped += 1
                                continue
                            
                            # Check if entry already exists
                            existing_entry = db.query(FeedEntry).filter(
                                FeedEntry.feed_id == feed.id,
                                FeedEntry.link == link
                            ).first()
                            
                            if existing_entry:
                                if self.debug:
                                    logger.debug(f"Skipping duplicate entry: {title}")
                                self.entries_skipped += 1
                                continue
                                    
                            try:
                                embedding = self.embeddings.embed_query(f"{title} {content}")
                            except Exception as e:
                                logger.error(f"Error generating embedding for entry {title}: {str(e)}")
                                self.entries_skipped += 1
                                continue
                            
                            feed_entry = FeedEntry(
                                feed_id=feed.id,
                                title=title,
                                content=content,
                                link=link,
                                published_date=published_date,
                                embedding=embedding
                            )
                            
                            db.add(feed_entry)
                            self.entries_added += 1
                            
                            if self.debug:
                                logger.debug(f"Added entry: {title} (published: {published_date})")
                                
                        except Exception as e:
                            logger.error(f"Error processing entry: {str(e)}")
                            self.entries_skipped += 1
                            continue
                    
                    db.commit()
                    
                    if self.debug:
                        logger.debug(f"Added {self.entries_added} entries, skipped {self.entries_skipped} entries")
                    
                    return feed
                    
                except Exception as e:
                    logger.error(f"Database error: {str(e)}")
                    db.rollback()
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching feed: {str(e)}")
            return None
        
    def search_similar_entries(self, query: str, limit: int = 5, ef_search: int = 40) -> List[FeedEntry]:
        """
        Search for similar entries using semantic search with HNSW index
        
        Args:
            query: The search query
            limit: Maximum number of results to return
            ef_search: HNSW ef_search parameter (higher values = more accurate but slower)
            
        Returns:
            List of similar FeedEntry objects
        """
        try:
            # Generate embedding for the query
            query_embedding = self.embeddings.embed_query(query)
            
            with get_db_session() as db:
                try:
                    # Set ef_search parameter for this query
                    db.execute(text("SET LOCAL hnsw.ef_search = :ef_search"), {"ef_search": ef_search})
                    
                    # Using HNSW index for approximate nearest neighbor search
                    # We get more results initially to allow for post-filtering
                    initial_limit = limit * 3
                    results = db.query(FeedEntry).order_by(
                        FeedEntry.embedding.l2_distance(query_embedding)
                    ).limit(initial_limit).all()
                    
                    if not results:
                        logger.debug(f"No results found for query: {query}")
                        return []
                    
                    # Post-process results to improve relevance
                    processed_results = []
                    for entry in results:
                        # Calculate semantic similarity score
                        title_embedding = self.embeddings.embed_query(entry.title)
                        similarity = 1.0 / (1.0 + sum((a - b) ** 2 for a, b in zip(query_embedding, title_embedding)) ** 0.5)
                        
                        processed_results.append((entry, similarity))
                    
                    # Sort by similarity score and take top results
                    processed_results.sort(key=lambda x: x[1], reverse=True)
                    
                    # Return only the entries, discarding scores
                    return [entry for entry, _ in processed_results[:limit]]
                    
                except Exception as e:
                    logger.error(f"Database error in search_similar_entries: {str(e)}")
                    return []
                
        except Exception as e:
            logger.error(f"Error in search_similar_entries: {str(e)}")
            return [] 