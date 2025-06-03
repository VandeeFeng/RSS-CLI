from dataclasses import dataclass
from dotenv import load_dotenv
import os

load_dotenv()

@dataclass
class DatabaseConfig:
    url: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rss_db")

@dataclass
class OllamaConfig:
    base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    chat_model: str = os.getenv("CHAT_MODEL_NAME", "qwen3:14b")
    embedding_model: str = os.getenv("EMBEDDING_MODEL_NAME", "nomic-embed-text")

@dataclass
class RSSConfig:
    # Maximum age of entries to fetch (in hours)
    max_age_hours: int = int(os.getenv("RSS_MAX_AGE_HOURS", "24"))
    # Maximum number of entries to fetch per feed
    max_entries_per_feed: int = int(os.getenv("RSS_MAX_ENTRIES_PER_FEED", "10"))
    # Path to feeds configuration file
    feeds_file: str = os.getenv("RSS_FEEDS_FILE", "feeds.json")

    def update_limits(self, max_entries: int = None, max_age: int = None):
        """Update the RSS feed limits"""
        if max_entries is not None:
            self.max_entries_per_feed = max_entries
        if max_age is not None:
            self.max_age_hours = max_age

class Config:
    def __init__(self):
        self.db = DatabaseConfig()
        self.ollama = OllamaConfig()
        self.rss = RSSConfig()
        self.debug: bool = False  # Will be set by main.py

# Global config instance
config = Config() 