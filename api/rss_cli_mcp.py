from fastapi import FastAPI, Depends, HTTPException, Body
from fastapi_mcp import FastApiMCP
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import datetime
from pydantic import BaseModel
import logging
from contextlib import asynccontextmanager
import asyncio

from database.db import SessionLocal
from database.models import Feed, FeedEntry
from rss.rss_fetcher import RSSFetcher
from rss.feeds import get_all_feeds, get_feeds_by_category, get_available_categories

# Initialize logger
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize MCP before the application starts
    global mcp
    mcp = FastApiMCP(app)
    mcp.mount()
    await asyncio.sleep(1)  # Give MCP time to fully initialize
    logger.info("MCP server initialization complete")
    yield
    # Cleanup (if needed)
    logger.info("Shutting down MCP server")

app = FastAPI(
    title="RSS CLI API",
    description="API for RSS feed management with MCP support",
    lifespan=lifespan
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class FeedResponse(BaseModel):
    id: int
    title: str
    url: Optional[str]
    last_updated: Optional[datetime]

class SearchQuery(BaseModel):
    query: str

@app.get("/mcp/list_feeds", response_model=List[FeedResponse], operation_id="list_feeds_feeds_get")
async def list_feeds(db: Session = Depends(get_db)):
    """List all RSS feeds in the database"""
    try:
        feeds = db.query(Feed).all()
        return [FeedResponse(
            id=f.id,
            title=(f.name or "Untitled Feed"),
            url=f.url,
            last_updated=f.last_updated
        ) for f in feeds]
    except Exception as e:
        logger.error(f"Error in list_feeds: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/feeds/categories")
async def list_categories():
    """List all available RSS feed categories"""
    return get_available_categories()

@app.get("/feeds/category/{category}")
async def get_category_feeds(category: str):
    """Get all RSS feeds in a specific category"""
    if category not in get_available_categories():
        raise HTTPException(status_code=404, detail=f"Category '{category}' not found")
    feeds = get_feeds_by_category(category)
    return [{"name": f.name, "url": f.url} for f in feeds]

@app.post("/feeds/update/{feed_id}")
async def update_feed(feed_id: int, db: Session = Depends(get_db)):
    """Update a specific RSS feed by its ID"""
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    
    fetcher = RSSFetcher()
    try:
        updated_feed = fetcher.fetch_feed(feed.url)
        if updated_feed:
            db.merge(updated_feed)
            db.commit()
            return {"message": f"Feed '{feed.name}' updated successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to fetch feed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/feeds/{feed_id}/entries")
async def get_feed_entries(
    feed_id: int,
    limit: Optional[int] = 10,
    db: Session = Depends(get_db)
):
    """Get entries for a specific RSS feed"""
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    
    entries = db.query(FeedEntry).filter(
        FeedEntry.feed_id == feed_id
    ).order_by(FeedEntry.published_date.desc()).limit(limit).all()
    
    return [{"title": e.title, "link": e.link, "published_date": e.published_date} for e in entries]

@app.post("/feeds/search")
async def search_feeds(query: SearchQuery, db: Session = Depends(get_db)):
    """Search for RSS feeds by title or URL"""
    try:
        results = [
            {"id": f.id, "title": f.name, "url": f.url}
            for f in db.query(Feed).filter(
                (Feed.name.ilike(f"%{query.query}%")) | 
                (Feed.url.ilike(f"%{query.query}%"))
            ).all()
        ]
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/feeds/{feed_id}/summary")
async def get_feed_summary(feed_id: int, db: Session = Depends(get_db)):
    """Get a summary of a feed including its latest entries"""
    try:
        feed = db.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            raise HTTPException(status_code=404, detail="Feed not found")
        
        entries = db.query(FeedEntry).filter(
            FeedEntry.feed_id == feed_id
        ).order_by(FeedEntry.published_date.desc()).limit(5).all()
        
        return {
            "feed": {
                "id": feed.id,
                "title": feed.name,
                "url": feed.url,
                "last_updated": feed.last_updated
            },
            "latest_entries": [
                {
                    "title": e.title,
                    "link": e.link,
                    "published_date": e.published_date
                } for e in entries
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    
    # Use localhost instead of 0.0.0.0 for better stability
    uvicorn.run(app, host="127.0.0.1", port=8000, loop="asyncio") 