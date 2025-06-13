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
import uvicorn
from api.rss_cli_mcp import app as mcp_app

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
        title = feed.name or "Untitled Feed"
        url = feed.url
        last_updated = None
    else:
        title = feed.title or feed.name or "Untitled Feed"
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
  python main.py list-categories
  
  # List all configured feeds
  python main.py list-feeds
  
  # Add feeds interactively
  python main.py add-feeds
  
  # Fetch latest content for a single feed
  python main.py fetch-feed "Hacker News"
  
  # Fetch latest content for a single feed with custom limits
  python main.py fetch-feed "Hacker News" -items 5 -hours 12
  
  # Fetch latest content for all feeds in a category
  python main.py fetch-category tech
  
  # Fetch latest content for all feeds
  python main.py fetch-all
  
  # Update feeds configuration from feeds.json
  python main.py update-feedjs
  
  # Import feeds from OPML file
  python main.py import-opml feeds.opml
  
  # Start chat interface
  python main.py chat
  
  # Enable debug mode
  python main.py chat -debug

  # Start MCP server
  python main.py mcp
        """
    )
    
    # Global options that can be used with any command
    parser.add_argument('-debug', action='store_true', help='Enable debug mode for verbose output')
    subparsers = parser.add_subparsers(dest='command', help='Available commands', required=False)
    
    # Common arguments for fetch commands
    fetch_parent_parser = argparse.ArgumentParser(add_help=False)
    fetch_parent_parser.add_argument('-items', type=int, help='Maximum number of items to fetch per feed')
    fetch_parent_parser.add_argument('-hours', type=int, help='Maximum age of entries in hours')
    
    # Help command
    subparsers.add_parser('help', help='Show this help message')
    
    # Database management
    subparsers.add_parser('reset-db', help='Reset the database and recreate all tables')
    
    # Feed management
    add_feeds_parser = subparsers.add_parser('add-feeds', help='Interactively add new RSS feeds')
    add_feeds_parser.add_argument('-category', type=str, help='Specify a category when adding feeds')
    
    subparsers.add_parser('fetch-all', help='Fetch latest content for all feeds', parents=[fetch_parent_parser])
    
    fetch_category = subparsers.add_parser('fetch-category', help='Fetch latest content for all feeds in a specific category', parents=[fetch_parent_parser])
    fetch_category.add_argument('category', type=str, help='Category name')
    
    fetch_feed = subparsers.add_parser('fetch-feed', help='Fetch latest content for a single feed by name', parents=[fetch_parent_parser])
    fetch_feed.add_argument('name', type=str, help='Feed name')
    
    import_opml_parser = subparsers.add_parser('import-opml', help='Import feeds from OPML file')
    import_opml_parser.add_argument('file', type=str, help='OPML file path')
    
    subparsers.add_parser('update-feedjs', help='Update feeds configuration from feeds.json')
    
    # Information display
    subparsers.add_parser('list-categories', help='List all available feed categories')
    subparsers.add_parser('list-feeds', help='List all configured feeds')
    
    # Chat interface
    subparsers.add_parser('chat', help='Start the AI chat interface')
    
    # MCP server
    mcp = subparsers.add_parser('mcp', help='Start the MCP server')
    mcp.add_argument('-port', type=int, default=8000, help='Port for MCP server (default: 8000)')
    mcp.add_argument('-host', type=str, default="127.0.0.1", help='Host for MCP server (default: 127.0.0.1)')

    args = parser.parse_args()
    
    # Override config values if custom limits are provided
    if hasattr(args, 'items') and args.items is not None:
        config.rss.max_entries_per_feed = args.items
    if hasattr(args, 'hours') and args.hours is not None:
        config.rss.max_age_hours = args.hours
    
    # If no command is provided, default to chat mode
    if not args.command:
        args.command = 'chat'
    
    # Handle help command
    if args.command == 'help':
        parser.print_help()
        return
        
    if args.command == 'list-categories':
        display_categories()
        return
    
    if args.command == 'list-feeds':
        display_feeds()
        return
    
    if args.command == 'reset-db':
        with console.status("[bold yellow]Resetting database...[/bold yellow]"):
            drop_db()
            init_db()
            console.print("[bold green]Database reset complete![/bold green]")
    else:
        # Just ensure tables exist
        init_db()
    
    if args.command == 'add-feeds':
        add_feeds(args.category if hasattr(args, 'category') else None, args.debug)
    
    if args.command == 'fetch-category':
        fetch_category_feeds(args.category, args.debug)
    
    if args.command == 'fetch-feed':
        fetch_single_feed(args.name, args.debug)
    
    if args.command == 'fetch-all':
        fetch_all_feeds(args.debug)
    
    if args.command == 'update-feedjs':
        update_feeds_from_json(args.debug)
    
    if args.command == 'import-opml':
        import_opml(args.file, args.debug)
    
    if args.command == 'mcp':
        console.print("[bold green]Starting MCP server...[/bold green]")
        console.print(Panel("""[bold cyan]Configure MCP in Cursor settings:[/bold cyan]

[white]Add the following to your Cursor settings:[/white]

{
  "rss_mcp": {
    "url": "http://127.0.0.1:8000/mcp"
  }
}

[dim]The server is now running at http://127.0.0.1:8000[/dim]""", border_style="green"))
        uvicorn.run(mcp_app, 
                   host=args.host if hasattr(args, 'host') else "127.0.0.1",
                   port=args.port if hasattr(args, 'port') else 8000, 
                   loop="asyncio")
        return

    # Start chat interface if requested or if no other action was specified
    if args.command == 'chat':
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

💡 Tip: Use `-help` to see all available command line options

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