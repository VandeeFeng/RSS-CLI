"""
RSS CLI Package

This package contains all the command-line interface related functionality for the RSS CLI tool.
It provides commands for:
- Managing RSS feeds (add, update, remove)
- Displaying feed information
- Importing feeds from OPML files
- Updating feeds from feeds.json configuration

The main commands are implemented in the commands.py module.
"""

from .commands import (
    display_categories,
    display_feeds,
    update_feeds_from_json,
    add_feeds,
    update_category,
    import_opml
)
