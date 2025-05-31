import logging
import feedparser
from typing import List, Optional
from datetime import datetime, timedelta
from dateutil.parser import parse
from langchain_community.embeddings import OllamaEmbeddings
from config import config
from database.models import Feed as DBFeed, FeedEntry
from database.db import SessionLocal
from contextlib import contextmanager

logger = logging.getLogger('rss_ai')

@contextmanager
def get_db_session():
    """Create a new database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class RSSFetcher:
    def __init__(self, debug: bool = False):
        self.debug = debug
        if debug:
            logger.setLevel(logging.DEBUG)
        
        # Initialize embeddings model
        self.embeddings = OllamaEmbeddings(
            base_url=config.ollama.base_url,
            model=config.ollama.embedding_model
        )
    
    def fetch_feed(self, url: str) -> Optional[DBFeed]:
        try:
            feed_data = feedparser.parse(url)
            if not feed_data.feed or hasattr(feed_data, 'bozo_exception'):
                logger.error(f"Could not fetch feed from {url}: {getattr(feed_data, 'bozo_exception', 'No feed data')}")
                return None
                
            with get_db_session() as db:
                try:
                    # Check if feed already exists
                    existing_feed = db.query(DBFeed).filter(DBFeed.url == url).first()
                    if existing_feed:
                        if self.debug:
                            logger.debug(f"Feed already exists: {url}")
                        # Update the feed title and last_updated
                        existing_feed.title = feed_data.feed.get('title', '')
                        existing_feed.description = feed_data.feed.get('description', '')
                        existing_feed.last_updated = datetime.now()
                        db.commit()
                        return db.merge(existing_feed)
                    
                    # Create new feed
                    feed = DBFeed(
                        url=url,
                        title=feed_data.feed.get('title', ''),
                        description=feed_data.feed.get('description', ''),
                        last_updated=datetime.now()
                    )
                    
                    db.add(feed)
                    db.flush()

                    # Calculate the cutoff time for entries
                    cutoff_time = datetime.now() - timedelta(hours=config.rss.max_age_hours)
                    entries_added = 0
                    
                    if self.debug:
                        logger.debug(f"Found {len(feed_data.entries)} entries")
                    
                    for entry in feed_data.entries:
                        # Stop if we've reached the maximum number of entries
                        if entries_added >= config.rss.max_entries_per_feed:
                            if self.debug:
                                logger.debug(f"Reached maximum entries limit ({config.rss.max_entries_per_feed})")
                            break
                            
                        content = entry.get('content', [{}])[0].get('value', '') or entry.get('description', '')
                        published = entry.get('published')
                        if published:
                            try:
                                published_date = parse(published)
                                # Skip entries older than the cutoff time
                                if published_date < cutoff_time:
                                    continue
                            except:
                                published_date = datetime.now()
                        else:
                            published_date = datetime.now()
                        
                        title = entry.get('title', '')
                        if not title or not content:
                            if self.debug:
                                logger.debug(f"Skipping entry: missing title or content")
                            continue
                                
                        embedding = self.embeddings.embed_query(f"{title} {content}")
                        
                        feed_entry = FeedEntry(
                            feed_id=feed.id,
                            title=title,
                            content=content,
                            link=entry.get('link', ''),
                            published_date=published_date,
                            embedding=embedding
                        )
                        
                        db.add(feed_entry)
                        entries_added += 1
                        if self.debug:
                            logger.debug(f"Added entry: {title}")
                    
                    if self.debug:
                        logger.debug(f"Successfully added {entries_added} entries")
                    
                    db.commit()
                    return db.merge(feed)
                    
                except Exception as e:
                    db.rollback()
                    logger.error(f"Error processing feed: {str(e)}")
                    raise e
                    
        except Exception as e:
            logger.error(f"Error fetching feed from {url}: {str(e)}")
            return None
        
    def search_similar_entries(self, query: str, limit: int = 5) -> List[FeedEntry]:
        query_embedding = self.embeddings.embed_query(query)
        with get_db_session() as db:
            # Using pgvector's L2 distance search
            results = db.query(FeedEntry).order_by(
                FeedEntry.embedding.l2_distance(query_embedding)
            ).limit(limit).all()
            return results 