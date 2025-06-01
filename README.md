# RSS CLI

A modern CLI tool that combines RSS feed management with AI capabilities. Built with Ollama for local LLM chat and pgvector for semantic search, it transforms how you interact with and discover content from your RSS feeds. Powered by LangChain's Agent framework, it enables natural language interactions with your RSS feeds through a sophisticated function-calling system.

## Why This Project?

Information shapes your habits, cognition, and way of thinking.

While RSS may not solve all problems related to information consumption, it can help avoid many of them.

But many RSS readers are bloated with unnecessary features and complex interfaces, when all you need is quick access to specific information. 

And I really don't need a fancy GUI. I've been searching for a simple yet effective way to read RSS feeds that lets me focus on what matters: the content.

Traditional RSS readers often lack intelligent search and content discovery features. This CLI tool addresses these challenges by:

- Providing a fast, distraction-free reading experience right in your terminal
- Focusing on core functionality without unnecessary bloat
- Leveraging AI to enable natural language search and content discovery
- Offering semantic search to find related articles across all your feeds
- Running entirely locally with privacy-preserving LLMs
- Saving time by allowing you to chat with your RSS feeds and get smart summaries

## Project Structure
```
.
├── api/                  # API and MCP integration
│   ├── __init__.py      # API package initialization
│   └── rss_cli_mcp.py   # MCP endpoints and FastAPI setup
├── database/               # Database related code
│   ├── db.py              # Database connection and session management
│   ├── models.py          # SQLAlchemy models
│   ├── docker-compose.yml # PostgreSQL container configuration
│   └── init.sql           # Database initialization script
├── llm/                   # LLM integration
│   ├── chat.py           # Chat interface implementation
│   └── tools.py          # LangChain tools and functions
├── rss/                   # RSS handling
│   ├── feeds.py          # Feed configuration and management
│   └── rss_fetcher.py    # RSS feed fetching and processing
├── main.py               # CLI entry point
├── config.py             # Configuration management
├── requirements.txt      # Python dependencies
└── .env                  # Environment variables
```

## Key Features

- 🔄 **Smart RSS Feed Management**
  - Fetch and store RSS feeds in PostgreSQL
  - Automatic feed updates with configurable intervals
  - Category-based feed organization (tech, programming, AI, etc.)
  - Configurable entry age and count limits

- 🔍 **Advanced Search Capabilities**
  - Vector search using pgvector
  - Semantic similarity search across all feed content
  - Category-based feed filtering
  - Real-time content crawling for linked articles

- 🤖 **Intelligent Chat Interface**
  - Chat with your RSS feeds using local LLM (Ollama)
  - Natural language queries for feed content
  - Smart feed recommendations
  - Contextual article summaries

- 🌐 **MCP Integration**
  - Standardized API endpoints for feed management
  - Seamless function calling between components
  - Real-time feed updates and synchronization
  - Extensible API layer for third-party integrations
  - Built on FastAPI for high performance

- 🛠️ **Extensible Function System**
  - Built on LangChain's Tool framework for easy extension
  - Core tools available:
    - `get_category_feeds`: Get feeds by category with recent entries
    - `get_feed_details`: Get comprehensive feed information
    - `search_related_feeds`: Semantic search across feeds
    - `fetch_feed`: Update specific feed content
    - `crawl_url`: Extract article content from URLs
  - Each tool returns structured JSON responses
  - Easy to add new tools by implementing the Tool interface

- ⌨️ **Command Line Interface**
  - Basic Operations:
    - `--add-feeds`: Add example RSS feeds
    - `--update-all`: Update all feeds
    - `--chat`: Start chat interface (default if no arguments provided)
  - Feed Management:
    - `--category CATEGORY`: Add feeds from specific category
    - `--update-category CATEGORY`: Update feeds in specific category
    - `--list-categories`: Show available categories
    - `--list-feeds`: Display all feeds
  - System:
    - `--reset-db`: Reset the database
    - `--debug`: Enable debug mode

## Prerequisites

- Python 3.8+
- PostgreSQL with pgvector extension
- Ollama running locally
- UV package manager (recommended)

## Quick Start

1. **Clone and Setup Environment**
```bash
# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt
```

2. **Configure RSS Feeds**
The project supports two ways to configure RSS feeds:

a) **Import from OPML** (Recommended)
```bash
# Import feeds from your OPML file
python main.py --import-opml feeds.opml
```
The OPML import will:
- Preserve your feed categories from the OPML file
- Skip duplicate feeds (based on URL)
- Automatically rename feeds with duplicate names
- Fetch initial content for new feeds

b) **Manual Configuration** (Optional)
You can customize feeds by editing `rss/feeds.py`:

```python
# Edit rss/feeds.py to customize your RSS sources
FEED_CATEGORIES = {
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
        )
    ]
}
```

Feed Configuration Options:
- `url`: RSS feed URL (required)
- `name`: Display name for the feed (required)
- `update_interval`: Update frequency in seconds (optional, default: 3600)

You can:
- Add new categories
- Add/remove feeds in existing categories
- Customize update intervals per feed
- Group feeds by your own categories

3. **Setup PostgreSQL with Docker** (recommended)
```bash
# Start PostgreSQL with pgvector
cd database && docker-compose up -d

# Or manually setup PostgreSQL and run:
CREATE EXTENSION vector;
```

4. **Configure Environment**
Copy `env.example` to `.env` and adjust the values:
```env
# Database settings
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rss_db

# Ollama settings
OLLAMA_BASE_URL=http://127.0.0.1:11434
CHAT_MODEL_NAME=qwen3:14b
EMBEDDING_MODEL_NAME=nomic-embed-text

# RSS settings
RSS_MAX_AGE_HOURS=24           # Maximum age of entries to fetch
RSS_MAX_ENTRIES_PER_FEED=10    # Maximum entries per feed
```

5. **Install Required Ollama Models**
```bash
ollama pull qwen3:14b
ollama pull nomic-embed-text
```

6. **Initialize and Run**
```bash
# Reset database and add initial feeds
python main.py --reset-db --add-feeds

# Or start with specific category
python main.py --add-feeds --category tech

# Start chat interface
python main.py
```

## Usage Guide

### Function Calling System

The project implements a function calling system that allows the LLM to interact with RSS feeds and content through specialized tools:

#### Feed Management Functions
- **get_category_feeds**
  - Purpose: Retrieve and manage feeds by category
  - Input: Category name (e.g., "tech", "ai")
  - Output: Feed information including status and recent entries
  - Use case: "Show me all tech feeds"

#### Search Functions
- **search_related_feeds**
  - Purpose: Semantic search across all feeds
  - Input: Search query or topic
  - Output: Ranked list of relevant feeds with similarity scores
  - Use case: "Find feeds about machine learning"

- **get_feed_details**
  - Purpose: Detailed feed information retrieval
  - Input: Feed name
  - Output: Comprehensive feed metadata and entries
  - Use case: "What's new in Hacker News?"

#### Content Management Functions
- **fetch_feed**
  - Purpose: Update feed content
  - Input: Feed name
  - Output: Feed update status and new entries
  - Use case: "Update the OpenAI blog feed"

- **crawl_url**
  - Purpose: Extract and process article content
  - Input: Article URL
  - Output: Processed article content in markdown format
  - Use case: "Get the full content of this article"

The LLM agent automatically:
- Selects appropriate functions based on user queries
- Handles parameter validation and error cases
- Processes and formats function outputs
- Combines multiple function calls when needed

### MCP

To start the MCP server:
```bash
# Start the MCP server on default port 8000
python -m api.rss_cli_mcp

# Or specify a custom port
PORT=8080 python -m api.rss_cli_mcp
```

Configure MCP in Cursor settings:
```json
{
  "rss_mcp": {
    "url": "http://127.0.0.1:8000/mcp"
  }
}
```
Add this to your Cursor settings to enable MCP integration. The URL should match your MCP server address.

The MCP server provides the following endpoints:
- `/mcp/list_feeds` - Get all RSS feeds
- `/mcp/feeds/search` - Search feeds by title/URL
- `/mcp/feeds/{feed_id}/summary` - Get feed summary with latest entries
- `/mcp/feeds/categories` - List all feed categories
- `/mcp/feeds/update/{feed_id}` - Update specific feed

## Tech Stack

### Core Technologies
- **Python 3.8+**: Main development language
- **PostgreSQL + pgvector**: Vector database for semantic search
  - Stores RSS feeds and entries
  - Handles vector similarity searches
  - Manages feed metadata and content

### AI & Language Models
- **Ollama**: Local LLM server
  - `qwen3:14b`: Main chat model
  - `nomic-embed-text`: Text embedding model
- **LangChain**: LLM framework
  - Manages chat interactions
  - Handles tool integrations
  - Provides agent capabilities

### Key Libraries
- **SQLAlchemy**: Database ORM and management
- **feedparser**: RSS feed parsing and handling
- **Rich**: Terminal UI and formatting
- **UV**: Modern Python package manager
- **python-dotenv**: Environment configuration


