-- Enable the vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create feeds table
CREATE TABLE IF NOT EXISTS feeds (
    id SERIAL PRIMARY KEY,
    url VARCHAR NOT NULL UNIQUE,
    name VARCHAR,
    title VARCHAR,
    description TEXT,
    last_updated TIMESTAMP WITH TIME ZONE,
    category VARCHAR
);

-- Create feed_entries table with vector support
CREATE TABLE IF NOT EXISTS feed_entries (
    id SERIAL PRIMARY KEY,
    feed_id INTEGER REFERENCES feeds(id),
    title VARCHAR,
    content TEXT,
    link VARCHAR,
    published_date TIMESTAMP WITH TIME ZONE,
    embedding vector(768),
    CONSTRAINT uix_feed_entry_link UNIQUE (feed_id, link)
);

-- Create HNSW index for vector similarity search
CREATE INDEX IF NOT EXISTS feed_entries_embedding_hnsw_idx ON feed_entries 
USING hnsw (embedding vector_l2_ops);

-- Set default HNSW search parameters
ALTER DATABASE rss_db SET hnsw.ef_search = 100;

-- Create additional indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_feed_entries_published_date 
ON feed_entries (published_date DESC);

CREATE INDEX IF NOT EXISTS idx_feeds_category 
ON feeds (category); 