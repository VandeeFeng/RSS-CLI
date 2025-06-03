import argparse
from database.db import init_db, drop_db, SessionLocal
from llm.chat import RSSChat
from config import config
from cli import (
    display_categories,
    display_feeds,
    update_feeds_from_json,
    add_feeds,
    fetch_category_feeds,
    import_opml,
    fetch_single_feed,
    fetch_all_feeds
)
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from contextlib import contextmanager
from database.models import Feed

# Initialize rich console
console = Console()

@contextmanager
def get_db_session():
    """Create a new database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def format_feed_info(feed, entries=None):
    """Format feed information for display"""
    # Handle both Feed and DBFeed objects
    if isinstance(feed, Feed):
        title = feed.name
        url = feed.url
        last_updated = None
    else:
        title = feed.title or feed.name
        url = feed.url
        last_updated = feed.last_updated
    
    info = [
        f"[bold cyan]Feed:[/bold cyan] {title}",
        f"[bold blue]URL:[/bold blue] {url}",
        f"[bold green]Last Updated:[/bold green] {last_updated.strftime('%Y-%m-%d %H:%M:%S') if last_updated else 'Never'}"
    ]
    
    if entries:
        info.append(f"\n[bold yellow]Latest entries[/bold yellow] ({len(entries)}):")
        for entry in entries:
            info.append(f"[bold]- {entry.title}[/bold]")
            info.append(f"  [dim]Published: {entry.published_date.strftime('%Y-%m-%d %H:%M:%S') if entry.published_date else 'Unknown'}[/dim]")
            info.append(f"  [blue link={entry.link}]Link[/blue]\n")
    
    return "\n".join(info)

def main():
    parser = argparse.ArgumentParser(
        description='RSS CLI with AI-powered feed management and interaction',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all available feed categories
  python main.py --list-categories
  
  # List all configured feeds
  python main.py --list-feeds
  
  # Add feeds interactively
  python main.py --add-feeds
  
  # Fetch latest content for a single feed
  python main.py --fetch-feed "Hacker News"
  
  # Fetch latest content for a single feed with custom limits
  python main.py --fetch-feed "Hacker News" -items 5 -hours 12
  
  # Fetch latest content for all feeds in a category
  python main.py --fetch-category tech
  
  # Fetch latest content for all feeds
  python main.py --fetch-all
  
  # Update feeds configuration from feeds.json
  python main.py --update-feedjs
  
  # Import feeds from OPML file
  python main.py --import-opml feeds.opml
  
  # Start chat interface
  python main.py --chat
  
  # Enable debug mode
  python main.py --chat --debug
        """
    )
    
    # Database management
    db_group = parser.add_argument_group('Database Management')
    db_group.add_argument('--reset-db', action='store_true', help='Reset the database and recreate all tables')
    
    # Feed management
    feed_group = parser.add_argument_group('Feed Management')
    feed_group.add_argument('--add-feeds', action='store_true', 
        help='Interactively add new RSS feeds. You will be prompted to enter category, URL, and name for each feed. '
             'Feeds will be saved to both feeds.json and database.')
    feed_group.add_argument('--category', type=str, help='Specify a category when fetching feeds')
    feed_group.add_argument('--fetch-all', action='store_true', help='Fetch latest content for all feeds')
    feed_group.add_argument('--fetch-category', type=str, help='Fetch latest content for all feeds in a specific category')
    feed_group.add_argument('--fetch-feed', type=str, metavar='NAME', help='Fetch latest content for a single feed by name')
    feed_group.add_argument('--import-opml', type=str, metavar='FILE', help='Import feeds from OPML file')
    feed_group.add_argument(
        '--update-feedjs',
        action='store_true',
        help='Update feeds configuration from feeds.json'
    )
    
    # Feed fetch options
    fetch_group = parser.add_argument_group('Feed Fetch Options')
    fetch_group.add_argument('-items', type=int, help='Maximum number of items to fetch per feed (overrides RSS_MAX_ENTRIES_PER_FEED)')
    fetch_group.add_argument('-hours', type=int, help='Maximum age of entries in hours (overrides RSS_MAX_AGE_HOURS)')
    
    # Information display
    info_group = parser.add_argument_group('Information Display')
    info_group.add_argument('--list-categories', action='store_true', help='List all available feed categories')
    info_group.add_argument('--list-feeds', action='store_true', help='List all configured feeds')
    
    # Chat interface
    chat_group = parser.add_argument_group('Chat Interface')
    chat_group.add_argument('--chat', action='store_true', help='Start the AI chat interface')
    
    # Debug options
    debug_group = parser.add_argument_group('Debug Options')
    debug_group.add_argument('--debug', action='store_true', help='Enable debug mode for verbose output')

    args = parser.parse_args()
    
    # Override config values if custom limits are provided
    if args.items is not None:
        config.rss.max_entries_per_feed = args.items
    if args.hours is not None:
        config.rss.max_age_hours = args.hours
    
    if args.list_categories:
        display_categories()
        return
    
    if args.list_feeds:
        display_feeds()
        return
    
    if args.reset_db:
        with console.status("[bold yellow]Resetting database...[/bold yellow]"):
            drop_db()
            init_db()
            console.print("[bold green]Database reset complete![/bold green]")
    else:
        # Just ensure tables exist
        init_db()
    
    if args.add_feeds:
        add_feeds(args.category, args.debug)
    
    if args.fetch_category:
        fetch_category_feeds(args.fetch_category, args.debug)
    
    if args.fetch_feed:
        fetch_single_feed(args.fetch_feed, args.debug)
    
    if args.fetch_all:
        fetch_all_feeds(args.debug)
    
    if args.update_feedjs:
        update_feeds_from_json(args.debug)
    
    if args.import_opml:
        import_opml(args.import_opml, args.debug)
    
    # Start chat interface if requested or if no other action was specified
    if args.chat or not any([args.reset_db, args.add_feeds, args.list_categories, 
                           args.list_feeds, args.fetch_all, args.fetch_category,
                           args.fetch_feed, args.update_feedjs, args.import_opml]):
        # Create chat instance
        chat = RSSChat(config=config, debug=args.debug)
        
        welcome_md = """# RSS CLI AI Chat Interface

You can:
1. 🔍 Search feeds by category
   - Example: "show me tech feeds"
2. 📰 Get feed details
   - Example: "what's new on Hacker News?"
3. 🎯 Search by topic
   - Example: "find feeds about machine learning"
4. 🔄 Update feeds
   - Example: "update OpenAI Blog"

💡 Tip: Use `--help` to see all available command line options

Type 'quit' to exit."""
        
        console.print(Panel(Markdown(welcome_md), border_style="green"))
        
        while True:
            query = console.input("\n[bold cyan]Enter your question[/bold cyan] (or 'quit' to exit): ")
            if query.lower() == 'quit':
                break
                
            try:
                console.print("\n[bold green]Response:[/bold green]")
                # Use streaming output
                for chunk in chat.chat_stream(query):
                    if chunk:
                        console.print(chunk, end="")
                console.print()  # New line after response
            except Exception as e:
                console.print(f"\n[bold red]Error:[/bold red] {str(e)}")
                console.print("[yellow]Please try again with a different question.[/yellow]")

if __name__ == '__main__':
    main() 