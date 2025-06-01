from database.db import init_db, drop_db, SessionLocal
from rss.rss_fetcher import RSSFetcher
from llm.chat import RSSChat
import argparse
from config import config
from rss.feeds import get_all_feeds, get_feeds_by_category, get_available_categories, Feed, update_feed_categories
from rss.opml_handler import parse_opml, merge_feeds
from database.models import Feed as DBFeed, FeedEntry
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.markdown import Markdown
from contextlib import contextmanager

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

def display_categories():
    """Display available categories in a table"""
    table = Table(title="Available Feed Categories")
    table.add_column("Category", style="cyan", no_wrap=True)
    table.add_column("Feeds", style="magenta")
    table.add_column("Feed Names", style="green")
    
    for category in get_available_categories():
        feeds = get_feeds_by_category(category)
        feed_names = ", ".join(f"{feed.name}" for feed in feeds)
        table.add_row(
            category.upper(),
            str(len(feeds)),
            feed_names
        )
    
    console.print(table)

def display_feeds():
    """Display all configured feeds in a table"""
    table = Table(title="Configured Feeds")
    table.add_column("Name", style="cyan")
    table.add_column("URL", style="blue")
    table.add_column("Title", style="magenta")
    table.add_column("Category", style="green")
    table.add_column("Last Updated", style="yellow")
    
    with get_db_session() as db:
        # Get all feeds from database
        feeds = db.query(DBFeed).all()
        
        for feed in feeds:
            # Find category for feed
            categories = get_available_categories()
            category = next(
                (cat for cat in categories if any(f.url == feed.url for f in get_feeds_by_category(cat))),
                "Unknown"
            )
            
            # Format last_updated
            last_updated = feed.last_updated.strftime("%Y-%m-%d %H:%M") if feed.last_updated else "Never"
            
            table.add_row(
                feed.title or "No Title",  # Use DB title
                feed.url,
                feed.description[:50] + "..." if feed.description and len(feed.description) > 50 else (feed.description or "No Description"),
                category.upper(),
                last_updated
            )
    
    console.print(table)

def main():
    parser = argparse.ArgumentParser(
        description='RSS CLI with AI-powered feed management and interaction',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all available feed categories
  python main.py --list-categories
  
  # Add feeds from a specific category
  python main.py --add-feeds --category tech
  
  # Update all feeds in a category
  python main.py --update-category tech
  
  # Import feeds from OPML file
  python main.py --import-opml feeds.opml
  
  # Start chat interface
  python main.py --chat
        """
    )
    
    # Database management
    db_group = parser.add_argument_group('Database Management')
    db_group.add_argument('--reset-db', action='store_true', help='Reset the database and recreate all tables')
    
    # Feed management
    feed_group = parser.add_argument_group('Feed Management')
    feed_group.add_argument('--add-feeds', action='store_true', help='Add example RSS feeds to the database')
    feed_group.add_argument('--category', type=str, help='Specify a category when adding or updating feeds')
    feed_group.add_argument('--update-all', action='store_true', help='Update all feeds in the database')
    feed_group.add_argument('--update-category', type=str, help='Update all feeds in a specific category')
    feed_group.add_argument('--import-opml', type=str, metavar='FILE', help='Import feeds from OPML file')
    
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
    
    fetcher = None
    
    if args.add_feeds or args.update_all or args.update_category:
        # Create fetcher instance
        fetcher = RSSFetcher(debug=args.debug)
        
        if args.add_feeds:
            # Get feeds to process
            if args.category:
                if args.category not in get_available_categories():
                    console.print(f"[bold red]Error:[/bold red] Category '{args.category}' not found.")
                    console.print("Available categories:", ", ".join(get_available_categories()))
                    return
                feeds_to_add = get_feeds_by_category(args.category)
                console.print(f"\n[bold cyan]Adding feeds from category:[/bold cyan] {args.category}")
            else:
                feeds_to_add = get_all_feeds()
                console.print("\n[bold cyan]Adding all feeds[/bold cyan]")
            
            # Fetch and store feeds
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                for feed in feeds_to_add:
                    task_id = progress.add_task(f"Fetching: {feed.name}")
                    try:
                        result = fetcher.fetch_feed(feed.url)
                        if result:
                            with get_db_session() as db:
                                # Refresh the feed object within the session
                                db_feed = db.merge(result)
                                console.print(Panel(format_feed_info(db_feed), title=feed.name, border_style="green"))
                        else:
                            console.print(f"[bold red]Failed to fetch feed:[/bold red] {feed.name}")
                    except Exception as e:
                        console.print(f"[bold red]Error fetching {feed.name}:[/bold red] {str(e)}")
                    finally:
                        progress.remove_task(task_id)
        
        if args.update_category:
            if args.update_category not in get_available_categories():
                console.print(f"[bold red]Error:[/bold red] Category '{args.update_category}' not found.")
                console.print("Available categories:", ", ".join(get_available_categories()))
                return
            
            console.print(f"\n[bold cyan]Updating feeds in category:[/bold cyan] {args.update_category}")
            feeds_to_update = get_feeds_by_category(args.update_category)
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                for feed in feeds_to_update:
                    task_id = progress.add_task(f"Updating: {feed.name}")
                    try:
                        result = fetcher.fetch_feed(feed.url)
                        if result:
                            with get_db_session() as db:
                                # Refresh the feed object within the session
                                db_feed = db.merge(result)
                                console.print(Panel(format_feed_info(db_feed), title=feed.name, border_style="green"))
                        else:
                            console.print(f"[bold red]Failed to update feed:[/bold red] {feed.name}")
                    except Exception as e:
                        console.print(f"[bold red]Error updating {feed.name}:[/bold red] {str(e)}")
                    finally:
                        progress.remove_task(task_id)
    
    if args.import_opml:
        try:
            # Create fetcher instance if not exists
            if not fetcher:
                fetcher = RSSFetcher(debug=args.debug)
            
            # Use a single progress display for all operations
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                # Parse and merge OPML
                task_id = progress.add_task("Importing OPML file...")
                new_feeds = parse_opml(args.import_opml)
                merged_feeds = merge_feeds(new_feeds, {cat: get_feeds_by_category(cat) for cat in get_available_categories()})
                update_feed_categories(merged_feeds)
                progress.remove_task(task_id)
                
                # Add all new feeds to database
                console.print("\n[bold cyan]Adding new feeds to database...[/bold cyan]")
                for category, feeds in merged_feeds.items():
                    for feed in feeds:
                        task_id = progress.add_task(f"Processing: {feed.name}")
                        try:
                            # Check if feed already exists in database
                            with get_db_session() as db:
                                existing = db.query(DBFeed).filter(DBFeed.url == feed.url).first()
                                if not existing:
                                    # Fetch and store new feed
                                    result = fetcher.fetch_feed(feed.url)
                                    if result:
                                        with get_db_session() as db:
                                            db_feed = db.merge(result)
                                            console.print(Panel(format_feed_info(db_feed), title=feed.name, border_style="green"))
                                    else:
                                        console.print(f"[yellow]Could not fetch feed:[/yellow] {feed.name}")
                        except Exception as e:
                            console.print(f"[red]Error processing {feed.name}:[/red] {str(e)}")
                        finally:
                            progress.remove_task(task_id)
                
                # Display results
                console.print("\n[bold green]OPML import complete![/bold green]")
                display_categories()
        except Exception as e:
            console.print(f"[bold red]Error importing OPML:[/bold red] {str(e)}")
            return
    
    # Start chat interface if requested or if no other action was specified
    if args.chat or not any([args.reset_db, args.add_feeds, args.list_categories, 
                           args.list_feeds, args.update_all, args.update_category]):
        # Create chat instance
        chat = RSSChat(config=config, debug=args.debug)
        
        welcome_md = """
        # RSS AI Chat Interface
        
        You can:
        1. 🔍 Search feeds by category
           - Example: "show me tech feeds"
        2. 📰 Get feed details
           - Example: "what's new on Hacker News?"
        3. 🎯 Search by topic
           - Example: "find feeds about machine learning"
        4. 🔄 Update feeds
           - Example: "update OpenAI Blog"
        
        Type 'quit' to exit.
        """
        
        console.print(Markdown(welcome_md))
        
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