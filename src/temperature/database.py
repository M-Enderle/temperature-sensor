import json
from datetime import datetime, timedelta
import pytz
from sqlalchemy import create_engine, Column, Float, DateTime, Integer
from sqlalchemy.orm import declarative_base, sessionmaker
from typing import Optional
import os

# Berlin timezone
BERLIN_TZ = pytz.timezone('Europe/Berlin')

# Database setup
db_path = os.getenv("DATABASE_PATH", "./temperature.db")
DATABASE_URL = f"sqlite:///{db_path}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TemperatureRecord(Base):
    """Store temperature measurements from Redis"""
    __tablename__ = "temperature_records"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(BERLIN_TZ), index=True)
    avg_temp1 = Column(Float)
    avg_temp2 = Column(Float)


def init_db():
    """Create database tables"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def save_temperature(avg_temp1: float, avg_temp2: float) -> TemperatureRecord:
    """Save temperature reading to database"""
    db = SessionLocal()
    try:
        record = TemperatureRecord(avg_temp1=avg_temp1, avg_temp2=avg_temp2)
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    finally:
        db.close()


def get_latest_temperature() -> Optional[TemperatureRecord]:
    """Get the most recent temperature reading"""
    db = SessionLocal()
    try:
        return db.query(TemperatureRecord).order_by(
            TemperatureRecord.timestamp.desc()
        ).first()
    finally:
        db.close()


def get_temperature_history(hours: int = 6) -> list[TemperatureRecord]:
    """Get temperature readings from the last N hours"""
    db = SessionLocal()
    try:
        cutoff_time = datetime.now(BERLIN_TZ) - timedelta(hours=hours)
        return db.query(TemperatureRecord).filter(
            TemperatureRecord.timestamp >= cutoff_time
        ).order_by(TemperatureRecord.timestamp.asc()).all()
    finally:
        db.close()


def clear_database() -> int:
    """Clear all temperature records from database"""
    db = SessionLocal()
    try:
        count = db.query(TemperatureRecord).delete()
        db.commit()
        return count
    finally:
        db.close()
