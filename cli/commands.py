from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.markdown import Markdown
from database.db import SessionLocal
from database.models import Feed as DBFeed, FeedEntry
from rss.feeds import get_all_feeds, get_feeds_by_category, get_available_categories, Feed, update_feed_categories, _load_feeds
from rss.rss_fetcher import RSSFetcher
from rss.opml_handler import parse_opml, merge_feeds
from datetime import datetime
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
        feeds = db.query(DBFeed).all()
        
        for feed in feeds:
            categories = get_available_categories()
            category = next(
                (cat for cat in categories if any(f.url == feed.url for f in get_feeds_by_category(cat))),
                "Unknown"
            )
            
            last_updated = feed.last_updated.strftime("%Y-%m-%d %H:%M") if feed.last_updated else "Never"
            
            table.add_row(
                feed.title or "No Title",
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
                console.print(f"[yellow]Removing feed not in feeds.json:[/yellow] {db_feed.title or db_feed.url}")
                db.delete(db_feed)
                changes_made = True
        
        # Update or add feeds from feeds.json
        for feed in all_feeds:
            existing_feed = db.query(DBFeed).filter(DBFeed.url == feed.url).first()
            if existing_feed:
                if existing_feed.title != feed.name:
                    console.print(f"[cyan]Updating feed name:[/cyan] {existing_feed.title} -> {feed.name}")
                    existing_feed.title = feed.name
                    changes_made = True
            else:
                console.print(f"[green]Adding new feed:[/green] {feed.name}")
                new_feed = DBFeed(
                    url=feed.url,
                    title=feed.name,
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
    """Add feeds to the database"""
    fetcher = RSSFetcher(debug=debug)
    
    if category:
        if category not in get_available_categories():
            console.print(f"[bold red]Error:[/bold red] Category '{category}' not found.")
            console.print("Available categories:", ", ".join(get_available_categories()))
            return
        feeds_to_add = get_feeds_by_category(category)
        console.print(f"\n[bold cyan]Adding feeds from category:[/bold cyan] {category}")
    else:
        feeds_to_add = get_all_feeds()
        console.print("\n[bold cyan]Adding all feeds[/bold cyan]")
    
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
                        db_feed = db.merge(result)
                        console.print(Panel(format_feed_info(db_feed), title=feed.name, border_style="green"))
                else:
                    console.print(f"[bold red]Failed to fetch feed:[/bold red] {feed.name}")
            except Exception as e:
                console.print(f"[bold red]Error fetching {feed.name}:[/bold red] {str(e)}")
            finally:
                progress.remove_task(task_id)

def update_category(category: str, debug: bool = False):
    """Update all feeds in a specific category"""
    if category not in get_available_categories():
        console.print(f"[bold red]Error:[/bold red] Category '{category}' not found.")
        console.print("Available categories:", ", ".join(get_available_categories()))
        return
    
    fetcher = RSSFetcher(debug=debug)
    console.print(f"\n[bold cyan]Updating feeds in category:[/bold cyan] {category}")
    feeds_to_update = get_feeds_by_category(category)
    
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
                        db_feed = db.merge(result)
                        console.print(Panel(format_feed_info(db_feed), title=feed.name, border_style="green"))
                else:
                    console.print(f"[bold red]Failed to update feed:[/bold red] {feed.name}")
            except Exception as e:
                console.print(f"[bold red]Error updating {feed.name}:[/bold red] {str(e)}")
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