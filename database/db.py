from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from config import config

engine = create_engine(config.db.url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    from database.models import Base
    Base.metadata.create_all(bind=engine)

def drop_db():
    from database.models import Base
    Base.metadata.drop_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 