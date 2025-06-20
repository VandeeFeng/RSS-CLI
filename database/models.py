from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, create_engine, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import ARRAY
from pgvector.sqlalchemy import Vector

Base = declarative_base()

class Feed(Base):
    __tablename__ = 'feeds'
    
    id = Column(Integer, primary_key=True)
    url = Column(String, unique=True, nullable=False)
    name = Column(String)
    description = Column(Text)
    last_updated = Column(DateTime)
    category = Column(String)
    entries = relationship('FeedEntry', back_populates='feed')

class FeedEntry(Base):
    __tablename__ = 'feed_entries'
    
    id = Column(Integer, primary_key=True)
    feed_id = Column(Integer, ForeignKey('feeds.id'))
    title = Column(String)
    content = Column(Text)
    link = Column(String)
    published_date = Column(DateTime)
    embedding = Column(Vector(768))
    
    feed = relationship('Feed', back_populates='entries')
    
    __table_args__ = (
        UniqueConstraint('feed_id', 'link', name='uix_feed_entry_link'),
    ) 