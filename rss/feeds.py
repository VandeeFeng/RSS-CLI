from typing import List, Dict
from dataclasses import dataclass
import json
import os
from config import config

@dataclass
class Feed:
    url: str
    name: str
    description: str = ""  # RSS feed's actual description (will be fetched)
    update_interval: int = 3600  # Update interval in seconds
    category: str = ""  # Feed category

# Global feed categories that will be loaded from file
FEED_CATEGORIES: Dict[str, List[Feed]] = {}

def _load_feeds():
    """Load feeds from file"""
    global FEED_CATEGORIES
    try:
        # Try loading from the configured path first
        if os.path.exists(config.rss.feeds_file):
            with open(config.rss.feeds_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                FEED_CATEGORIES = {
                    category: [Feed(**feed) for feed in feeds]
                    for category, feeds in data.items()
                }
                return
        
        # If not found, try looking in the package directory
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        package_feeds = os.path.join(package_dir, 'feeds.json')
        if os.path.exists(package_feeds):
            with open(package_feeds, 'r', encoding='utf-8') as f:
                data = json.load(f)
                FEED_CATEGORIES = {
                    category: [Feed(**feed) for feed in feeds]
                    for category, feeds in data.items()
                }
                return
        
        # If still not found, show error message
        from rich.console import Console
        console = Console()
        console.print("[yellow]No feeds file found![/yellow]")
        console.print(f"[yellow]Expected locations:[/yellow]")
        console.print(f"  - {config.rss.feeds_file}")
        console.print(f"  - {package_feeds}")
        console.print("[green]You can add feeds using:[/green]")
        console.print("  rss add-feed")
        FEED_CATEGORIES = {}
    except Exception as e:
        from rich.console import Console
        console = Console()
        console.print(f"[red]Error loading feeds file: {str(e)}[/red]")
        console.print("[green]You can add feeds using:[/green]")
        console.print("  rss add-feed")
        FEED_CATEGORIES = {}

def _save_feeds():
    """Save feeds to file"""
    data = {
        category: [{"url": feed.url, "name": feed.name} for feed in feeds]
        for category, feeds in FEED_CATEGORIES.items()
    }
    with open(config.rss.feeds_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def update_feed_categories(new_categories: Dict[str, List[Feed]]) -> None:
    """Update FEED_CATEGORIES with new categories and feeds"""
    global FEED_CATEGORIES
    
    # Load existing feeds if not loaded
    if not FEED_CATEGORIES:
        _load_feeds()
    
    # Create a set of existing URLs for quick lookup
    existing_urls = {
        feed.url
        for feeds in FEED_CATEGORIES.values()
        for feed in feeds
    }
    
    # Create a map of existing names to avoid duplicates
    existing_names = {
        feed.name: feed
        for feeds in FEED_CATEGORIES.values()
        for feed in feeds
    }
    
    # Merge new categories with existing ones
    for category, feeds in new_categories.items():
        if category not in FEED_CATEGORIES:
            FEED_CATEGORIES[category] = []
            
        for feed in feeds:
            # Skip if URL already exists in any category
            if feed.url in existing_urls:
                continue
                
            # If name exists but URL is different, append a number
            base_name = feed.name
            counter = 1
            while feed.name in existing_names:
                feed.name = f"{base_name} ({counter})"
                counter += 1
            
            FEED_CATEGORIES[category].append(feed)
            # Update our tracking sets/maps
            existing_urls.add(feed.url)
            existing_names[feed.name] = feed
    
    # Save the updated feeds to file
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
    # Strip any quotes from the name
    name = name.strip().strip('"\'')
    for feed in get_all_feeds():
        if feed.name == name:
            return feed
    return None

# Load feeds when module is imported
_load_feeds() 