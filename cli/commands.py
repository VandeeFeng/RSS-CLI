from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.markdown import Markdown
from database.db import SessionLocal
from database.models import Feed as DBFeed, FeedEntry
from rss.feeds import get_all_feeds, get_feeds_by_category, get_available_categories, Feed, update_feed_categories, _load_feeds, get_feed_by_name
from rss.rss_fetcher import RSSFetcher
from rss.opml_handler import parse_opml, merge_feeds
from datetime import datetime
from contextlib import contextmanager
from config import config

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
        name = feed.name
        url = feed.url
        description = ""
        last_updated = None
    else:
        name = feed.name
        url = feed.url
        description = feed.description or "No description"
        last_updated = feed.last_updated
    
    info = [
        f"[bold cyan]Feed:[/bold cyan] {name}",
        f"[bold blue]URL:[/bold blue] {url}",
        f"[bold magenta]Description:[/bold magenta] {description}",
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
    table.add_column("Description", style="magenta")
    table.add_column("Category", style="green")
    table.add_column("Last Updated", style="yellow")
    
    with get_db_session() as db:
        feeds = db.query(DBFeed).all()
        
        for feed in feeds:
            categories = get_available_categories()
            category = next(
                (cat for cat in categories if any(f.url == feed.url for f in get_feeds_by_category(cat))),
                "Unknown"
            )
            
            last_updated = feed.last_updated.strftime("%Y-%m-%d %H:%M") if feed.last_updated else "Never"
            
            table.add_row(
                feed.name or "No Name",
                feed.url,
                feed.description[:50] + "..." if feed.description and len(feed.description) > 50 else (feed.description or "No Description"),
                category.upper(),
                last_updated
            )
    
    console.print(table)

def update_feeds_from_json(debug: bool = False):
    """Update feeds configuration from feeds.json"""
    console.print("\n[bold cyan]Updating feeds configuration from feeds.json[/bold cyan]")
    _load_feeds()
    all_feeds = get_all_feeds()
    
    json_feed_urls = {feed.url for feed in all_feeds}
    json_feed_map = {feed.url: feed for feed in all_feeds}
    
    changes_made = False
    with get_db_session() as db:
        # Remove feeds not in feeds.json
        db_feeds = db.query(DBFeed).all()
        for db_feed in db_feeds:
            if db_feed.url not in json_feed_urls:
                console.print(f"[yellow]Removing feed not in feeds.json:[/yellow] {db_feed.name or db_feed.url}")
                db.delete(db_feed)
                changes_made = True
        
        # Update or add feeds from feeds.json
        for feed in all_feeds:
            existing_feed = db.query(DBFeed).filter(DBFeed.url == feed.url).first()
            if existing_feed:
                if existing_feed.name != feed.name:
                    console.print(f"[cyan]Updating feed name:[/cyan] {existing_feed.name} -> {feed.name}")
                    existing_feed.name = feed.name
                    changes_made = True
            else:
                console.print(f"[green]Adding new feed:[/green] {feed.name}")
                new_feed = DBFeed(
                    url=feed.url,
                    name=feed.name,
                    last_updated=datetime.now()
                )
                db.add(new_feed)
                changes_made = True
        
        if changes_made:
            db.commit()
            console.print("\n[bold green]Feeds configuration updated successfully![/bold green]")
        else:
            console.print("\n[bold blue]No changes needed, feeds configuration is up to date.[/bold blue]")

def add_feeds(category: str = None, debug: bool = False):
    """Interactive function to add feeds to feeds.json and database"""
    fetcher = RSSFetcher(debug=debug)
    console = Console()
    
    # Load existing feeds
    _load_feeds()
    categories = get_available_categories()
    
    while True:
        # Get category
        if not categories:
            category = console.input("\n[bold cyan]Enter new category name[/bold cyan]: ").strip().lower()
        else:
            console.print("\nAvailable categories:", ", ".join(categories))
            category = console.input("[bold cyan]Enter category name (new or existing)[/bold cyan]: ").strip().lower()
        
        if not category:
            break
            
        # Get feed URL
        url = console.input("[bold cyan]Enter feed URL[/bold cyan] (or press Enter to finish): ").strip()
        if not url:
            break
            
        # Get feed name
        name = console.input("[bold cyan]Enter feed name[/bold cyan] (or press Enter to use default): ").strip()
        
        # Validate feed URL and add to both feeds.json and database
        try:
            with console.status("[bold yellow]Validating and adding feed...[/bold yellow]"):
                # First try to fetch and add to database
                result = fetcher.fetch_feed(url)
                if not result:
                    console.print("[bold red]Error:[/bold red] Invalid feed URL")
                    continue
                
                # Use fetched title if name not provided
                if not name:
                    name = result.name or url
                
                # Add to feeds.json
                feed = Feed(url=url, name=name)
                update_feed_categories({category: [feed]})
                console.print("[bold green]✓[/bold green] Saved to feeds.json")
                
                # Add to database
                with get_db_session() as db:
                    db_feed = db.merge(result)
                    db.commit()
                    console.print("[bold green]✓[/bold green] Saved to database")
                    console.print(Panel(format_feed_info(db_feed), title=name, border_style="green"))
                
                console.print(f"[bold green]Successfully added feed:[/bold green] {name}")
                console.print(f"[bold green]Category:[/bold green] {category}")
                
                # Update categories list
                categories = get_available_categories()
                
                # Ask if want to add another feed
                if not console.input("\n[bold cyan]Add another feed? (y/N):[/bold cyan] ").lower().startswith('y'):
                    break
                    
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {str(e)}")
            if not console.input("\n[bold cyan]Try again? (Y/n):[/bold cyan] ").lower().startswith('n'):
                continue
            break
    
    console.print("\n[bold green]Feed addition completed![/bold green]")
    display_categories()

def fetch_category_feeds(category: str, debug: bool = False):
    """Fetch latest content for all feeds in a specific category"""
    if category not in get_available_categories():
        console.print(f"[bold red]Error:[/bold red] Category '{category}' not found.")
        console.print("Available categories:", ", ".join(get_available_categories()))
        return
    
    fetcher = RSSFetcher(
        debug=debug,
        max_entries=config.rss.max_entries_per_feed,
        max_age_hours=config.rss.max_age_hours
    )
    console.print(f"\n[bold cyan]Fetching latest content for feeds in category:[/bold cyan] {category}")
    feeds_to_update = get_feeds_by_category(category)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        for feed in feeds_to_update:
            task_id = progress.add_task(f"Fetching: {feed.name}")
            try:
                result = fetcher.fetch_feed(feed.url)
                if result:
                    with get_db_session() as db:
                        db_feed = db.merge(result)
                        console.print(Panel(format_feed_info(db_feed), title=feed.name, border_style="green"))
                else:
                    console.print(f"[bold red]Failed to fetch feed:[/bold red] {feed.name}")
            except Exception as e:
                console.print(f"[bold red]Error fetching {feed.name}:[/bold red] {str(e)}")
            finally:
                progress.remove_task(task_id)

def import_opml(file_path: str, debug: bool = False):
    """Import feeds from OPML file"""
    try:
        fetcher = RSSFetcher(debug=debug)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task_id = progress.add_task("Importing OPML file...")
            new_feeds = parse_opml(file_path)
            merged_feeds = merge_feeds(new_feeds, {cat: get_feeds_by_category(cat) for cat in get_available_categories()})
            update_feed_categories(merged_feeds)
            progress.remove_task(task_id)
            
            console.print("\n[bold cyan]Adding new feeds to database...[/bold cyan]")
            for category, feeds in merged_feeds.items():
                for feed in feeds:
                    task_id = progress.add_task(f"Processing: {feed.name}")
                    try:
                        with get_db_session() as db:
                            existing = db.query(DBFeed).filter(DBFeed.url == feed.url).first()
                            if not existing:
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
            
            console.print("\n[bold green]OPML import complete![/bold green]")
            display_categories()
    except Exception as e:
        console.print(f"[bold red]Error importing OPML:[/bold red] {str(e)}")

def fetch_single_feed(feed_name: str, debug: bool = False):
    """Fetch latest content for a specific feed by name"""
    fetcher = RSSFetcher(
        debug=debug,
        max_entries=config.rss.max_entries_per_feed,
        max_age_hours=config.rss.max_age_hours
    )
    
    try:
        feed_config = get_feed_by_name(feed_name)
        if not feed_config:
            console.print(f"[bold red]Error:[/bold red] Feed '{feed_name}' not found.")
            return
        
        console.print(f"\n[bold cyan]Fetching latest content for feed:[/bold cyan] {feed_name}")
        
        with get_db_session() as db:
            result = fetcher.fetch_feed(feed_config.url)
            if result:
                db_feed = db.merge(result)
                console.print(Panel(format_feed_info(db_feed), title=feed_name, border_style="green"))
            else:
                console.print(f"[bold red]Failed to fetch feed:[/bold red] {feed_name}")
                
    except Exception as e:
        console.print(f"[bold red]Error fetching {feed_name}:[/bold red] {str(e)}")

def fetch_all_feeds(debug: bool = False):
    """Fetch latest content for all feeds in the system"""
    fetcher = RSSFetcher(
        debug=debug,
        max_entries=config.rss.max_entries_per_feed,
        max_age_hours=config.rss.max_age_hours
    )
    console.print("\n[bold cyan]Fetching latest content for all feeds[/bold cyan]")
    feeds_to_update = get_all_feeds()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        for feed in feeds_to_update:
            task_id = progress.add_task(f"Fetching: {feed.name}")
            try:
                result = fetcher.fetch_feed(feed.url)
                if result:
                    with get_db_session() as db:
                        db_feed = db.merge(result)
                        console.print(Panel(format_feed_info(db_feed), title=feed.name, border_style="green"))
                else:
                    console.print(f"[bold red]Failed to fetch feed:[/bold red] {feed.name}")
            except Exception as e:
                console.print(f"[bold red]Error fetching {feed.name}:[/bold red] {str(e)}")
            finally:
                progress.remove_task(task_id) 