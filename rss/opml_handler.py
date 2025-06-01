import xml.etree.ElementTree as ET
from typing import Dict, List
from .feeds import Feed

def parse_opml(opml_path: str) -> Dict[str, List[Feed]]:
    """
    Parse OPML file into Dict[str, List[Feed]] structure
    """
    tree = ET.parse(opml_path)
    root = tree.getroot()
    body = root.find('body')
    
    result: Dict[str, List[Feed]] = {}
    
    def process_outline(outline: ET.Element, current_category: str = None):
        if outline.get('xmlUrl'):  # This is a feed
            feed = Feed(
                url=outline.get('xmlUrl'),
                name=outline.get('title') or outline.get('text', '')
            )
            
            category = current_category or 'default'
            if category not in result:
                result[category] = []
            result[category].append(feed)
            
        else:  # This is a category
            category = outline.get('title') or outline.get('text', '')
            for child in outline:
                process_outline(child, category)
    
    for outline in body:
        process_outline(outline)
    
    return result

def merge_feeds(opml_feeds: Dict[str, List[Feed]], existing_feeds: Dict[str, List[Feed]]) -> Dict[str, List[Feed]]:
    """Merge new feeds with existing feeds, avoiding duplicates"""
    merged = existing_feeds.copy()
    
    # Create a set of existing URLs for quick lookup
    existing_urls = {
        feed.url
        for feeds in existing_feeds.values()
        for feed in feeds
    }
    
    # Create a map of existing names to avoid duplicates
    existing_names = {
        feed.name: feed
        for feeds in existing_feeds.values()
        for feed in feeds
    }
    
    for category, feeds in opml_feeds.items():
        if category not in merged:
            merged[category] = []
            
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
            
            merged[category].append(feed)
            # Update our tracking sets/maps
            existing_urls.add(feed.url)
            existing_names[feed.name] = feed
    
    return merged 