from typing import List, Dict
from dataclasses import dataclass

@dataclass
class Feed:
    url: str
    name: str
    title: str = ""  # RSS feed's actual title (will be fetched)
    update_interval: int = 3600  # Update interval in seconds

# Feed categories
FEED_CATEGORIES: Dict[str, List[Feed]] = {
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
            url="https://www.reddit.com/r/programming/.rss",
            name="Reddit Programming"
        ),
        Feed(
            url="https://dev.to/feed/",
            name="Dev.to"
        )
    ],
    "ai": [
        Feed(
            url="https://arxiv.org/rss/cs.AI",
            name="ArXiv AI"
        ),
        Feed(
            url="https://openai.com/blog/rss/",
            name="OpenAI Blog"
        )
    ]
}

def get_all_feeds() -> List[Feed]:
    """Get all feeds from all categories"""
    all_feeds = []
    for feeds in FEED_CATEGORIES.values():
        all_feeds.extend(feeds)
    return all_feeds

def get_feeds_by_category(category: str) -> List[Feed]:
    """Get feeds by category"""
    return FEED_CATEGORIES.get(category, [])

def get_feed_by_name(name: str) -> Feed:
    """Get feed by name"""
    for feed in get_all_feeds():
        if feed.name == name:
            return feed
    return None

def get_available_categories() -> List[str]:
    """Get list of available feed categories"""
    return list(FEED_CATEGORIES.keys()) 