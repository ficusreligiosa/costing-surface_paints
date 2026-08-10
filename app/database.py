import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Load environment variables from .env file
load_dotenv()

# Set DATABASE_URL in your .env file, e.g.:
# postgresql://surface_user:yourpassword@localhost:5432/surface_paints
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://surface_user:changeme@localhost:5432/surface_paints",
)

# Render and other cloud hosts often set postgres://, which SQLAlchemy requires to be postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
