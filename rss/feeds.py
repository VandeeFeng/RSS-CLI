from typing import List, Dict
from dataclasses import dataclass
import json
import os

@dataclass
class Feed:
    url: str
    name: str
    title: str = ""  # RSS feed's actual title (will be fetched)
    update_interval: int = 3600  # Update interval in seconds

# File to store feeds
FEEDS_FILE = "feeds.json"

# Default feed categories
DEFAULT_FEED_CATEGORIES: Dict[str, List[Feed]] = {
    "tech": [
        Feed(
            url="https://news.ycombinator.com/rss",
            name="Hacker News"
        ),
        Feed(
            url="https://techcrunch.com/feed/",
            name="TechCrunch"
        )
    ],
    "programming": [
        Feed(
            url="https://dev.to/feed/",
            name="Dev.to"
        )
    ],
    "ai": [
        Feed(
            url="https://arxiv.org/rss/cs.AI",
            name="ArXiv AI"
        )
    ]
}

# Global feed categories that will be loaded from file or defaults
FEED_CATEGORIES: Dict[str, List[Feed]] = {}

def _load_feeds():
    """Load feeds from file or use defaults"""
    global FEED_CATEGORIES
    try:
        if os.path.exists(FEEDS_FILE):
            with open(FEEDS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                FEED_CATEGORIES = {
                    category: [Feed(**feed) for feed in feeds]
                    for category, feeds in data.items()
                }
        else:
            FEED_CATEGORIES = DEFAULT_FEED_CATEGORIES
    except Exception:
        FEED_CATEGORIES = DEFAULT_FEED_CATEGORIES

def _save_feeds():
    """Save feeds to file"""
    data = {
        category: [{"url": feed.url, "name": feed.name} for feed in feeds]
        for category, feeds in FEED_CATEGORIES.items()
    }
    with open(FEEDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def update_feed_categories(new_categories: Dict[str, List[Feed]]) -> None:
    """Update FEED_CATEGORIES with new categories and feeds"""
    global FEED_CATEGORIES
    FEED_CATEGORIES = new_categories
    _save_feeds()

def get_all_feeds() -> List[Feed]:
    """Get all feeds from all categories"""
    if not FEED_CATEGORIES:
        _load_feeds()
    all_feeds = []
    for feeds in FEED_CATEGORIES.values():
        all_feeds.extend(feeds)
    return all_feeds

def get_feeds_by_category(category: str) -> List[Feed]:
    """Get feeds by category"""
    if not FEED_CATEGORIES:
        _load_feeds()
    # Try exact match first, then case-insensitive match
    return FEED_CATEGORIES.get(category) or FEED_CATEGORIES.get(category.upper()) or FEED_CATEGORIES.get(category.lower(), [])

def get_available_categories() -> List[str]:
    """Get list of available feed categories"""
    if not FEED_CATEGORIES:
        _load_feeds()
    return list(FEED_CATEGORIES.keys())

def get_feed_by_name(name: str) -> Feed:
    """Get feed by name"""
    if not FEED_CATEGORIES:
        _load_feeds()
    for feed in get_all_feeds():
        if feed.name == name:
            return feed
    return None

# Load feeds when module is imported
_load_feeds() 