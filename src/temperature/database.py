import json
from datetime import datetime, timedelta
import pytz
from sqlalchemy import create_engine, Column, Float, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from typing import Optional
import os
from .logging_config import get_logger, log_database_operation, log_performance

# Berlin timezone
BERLIN_TZ = pytz.timezone('Europe/Berlin')

# Setup logging
logger = get_logger(__name__, "database")

# Database setup
db_path = os.getenv("DATABASE_PATH", "./temperature.db")
DATABASE_URL = f"sqlite:///{db_path}"
logger.info(
    "Initializing database connection",
    extra={
        "operation": "database_initialization",
        "database_url": DATABASE_URL,
        "database_path": db_path
    }
)
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


class ErrorLog(Base):
    """Store error messages"""
    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(BERLIN_TZ), index=True)
    message = Column(Text, nullable=False)


@log_performance
def init_db():
    """Create database tables"""
    logger.info(
        "Creating database tables", 
        extra={
            "operation": "table_creation",
            "database_operation": "create_tables"
        }
    )
    try:
        Base.metadata.create_all(bind=engine)
        log_database_operation("create_tables", success=True)
    except Exception as e:
        log_database_operation("create_tables", success=False, error=str(e))
        raise


def get_db():
    """Dependency for FastAPI to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_valid_reading(new_value: float, prev_value: float, prev_prev_value: float = None, threshold_percent: float = 0.25, min_temp: float = 10.0) -> bool:
    """
    Check if a new temperature reading is valid based on the previous reading.
    Returns False if:
    - The new value differs by more than threshold_percent (default 25%) from previous
    - The new value is below min_temp (default 10°C)
    Exception: If the change continues in the same direction as the previous change (e.g., consecutive drops),
    allow it even if it exceeds the threshold.
    """
    if prev_value is None or prev_value == -999.0:
        return True  # No previous reading to compare against

    if new_value == -999.0:
        return True  # Failed sensor reading, pass through

    # Check minimum temperature threshold
    if new_value < min_temp:
        return False

    # Calculate the acceptable range
    lower_bound = prev_value * (1 - threshold_percent)
    upper_bound = prev_value * (1 + threshold_percent)

    # If within normal range, accept it
    if lower_bound <= new_value <= upper_bound:
        return True

    # If outside normal range, check if it continues in the same direction
    if prev_prev_value is not None and prev_prev_value != -999.0:
        # Calculate the previous trend
        prev_trend = prev_value - prev_prev_value
        # Calculate the current trend
        current_trend = new_value - prev_value

        # If both trends have the same sign (both positive or both negative), allow it
        if (prev_trend > 0 and current_trend > 0) or (prev_trend < 0 and current_trend < 0):
            return True

    return False


@log_performance
def save_temperature(avg_temp1: float, avg_temp2: float, apply_outlier_filter: bool = True) -> TemperatureRecord:
    """
    Save temperature reading to database with optional outlier filtering.
    If apply_outlier_filter is True, discard values that differ by more than 25%
    from the previous reading for each sensor individually, unless the change
    continues in the same direction (e.g., consecutive drops).
    """
    db = SessionLocal()
    try:
        final_temp1 = avg_temp1
        final_temp2 = avg_temp2
        outlier_filtered = False

        if apply_outlier_filter:
            # Get the two most recent readings
            recent_records = db.query(TemperatureRecord).order_by(
                TemperatureRecord.timestamp.desc()
            ).limit(2).all()

            if recent_records:
                prev_record = recent_records[0]
                prev_prev_record = recent_records[1] if len(recent_records) > 1 else None

                # Check each sensor independently
                prev_prev_temp1 = prev_prev_record.avg_temp1 if prev_prev_record else None
                if not is_valid_reading(avg_temp1, prev_record.avg_temp1, prev_prev_temp1):
                    final_temp1 = prev_record.avg_temp1  # Keep previous value
                    outlier_filtered = True
                    logger.warning(
                        "Outlier filtered for sensor 1",
                        extra={
                            "operation": "outlier_filtering",
                            "sensor": 1,
                            "original_value": avg_temp1,
                            "filtered_value": final_temp1,
                            "previous_value": prev_record.avg_temp1
                        }
                    )

                prev_prev_temp2 = prev_prev_record.avg_temp2 if prev_prev_record else None
                if not is_valid_reading(avg_temp2, prev_record.avg_temp2, prev_prev_temp2):
                    final_temp2 = prev_record.avg_temp2  # Keep previous value
                    outlier_filtered = True
                    logger.warning(
                        "Outlier filtered for sensor 2",
                        extra={
                            "operation": "outlier_filtering",
                            "sensor": 2,
                            "original_value": avg_temp2,
                            "filtered_value": final_temp2,
                            "previous_value": prev_record.avg_temp2
                        }
                    )

        record = TemperatureRecord(avg_temp1=final_temp1, avg_temp2=final_temp2)
        db.add(record)
        db.commit()
        db.refresh(record)
        
        log_temperature_reading(final_temp1, final_temp2, outlier_filtered)
        log_database_operation("insert_temperature", success=True, record_count=1)
        
        return record
    except Exception as e:
        logger.error(
            "Error saving temperature to database",
            extra={
                "operation": "save_temperature",
                "database_operation": "insert_temperature",
                "error": str(e),
                "error_type": type(e).__name__,
                "temperature_sensor1": avg_temp1,
                "temperature_sensor2": avg_temp2
            }
        )
        log_database_operation("insert_temperature", success=False, error=str(e))
        db.rollback()
        raise
    finally:
        db.close()


@log_performance
def get_latest_temperature() -> Optional[TemperatureRecord]:
    """Get the most recent temperature reading"""
    db = SessionLocal()
    try:
        result = db.query(TemperatureRecord).order_by(
            TemperatureRecord.timestamp.desc()
        ).first()
        log_database_operation("select_latest_temperature", success=True, record_count=1 if result else 0)
        return result
    except Exception as e:
        log_database_operation("select_latest_temperature", success=False, error=str(e))
        raise
    finally:
        db.close()


@log_performance
def get_temperature_history(hours: int = 6) -> list[TemperatureRecord]:
    """Get temperature readings from the last N hours"""
    db = SessionLocal()
    try:
        cutoff_time = datetime.now(BERLIN_TZ) - timedelta(hours=hours)
        results = db.query(TemperatureRecord).filter(
            TemperatureRecord.timestamp >= cutoff_time
        ).order_by(TemperatureRecord.timestamp.asc()).all()
        
        logger.info(
            f"Retrieved temperature history for {hours} hours",
            extra={
                "operation": "get_temperature_history",
                "database_operation": "select_temperature_history",
                "hours": hours,
                "record_count": len(results),
                "cutoff_time": cutoff_time.isoformat()
            }
        )
        log_database_operation("select_temperature_history", success=True, record_count=len(results))
        return results
    except Exception as e:
        log_database_operation("select_temperature_history", success=False, error=str(e))
        raise
    finally:
        db.close()


@log_performance
def clear_database() -> int:
    """Clear all temperature records from database"""
    db = SessionLocal()
    try:
        logger.info(
            "Clearing all temperature records from database",
            extra={
                "operation": "clear_database",
                "database_operation": "delete_all_temperatures"
            }
        )
        count = db.query(TemperatureRecord).delete()
        db.commit()
        logger.info(
            "Successfully deleted temperature records",
            extra={
                "operation": "clear_database",
                "database_operation": "delete_all_temperatures",
                "record_count": count,
                "success": True
            }
        )
        log_database_operation("delete_all_temperatures", success=True, record_count=count)
        return count
    except Exception as e:
        logger.error(
            "Error clearing temperature records",
            extra={
                "operation": "clear_database",
                "database_operation": "delete_all_temperatures",
                "error": str(e),
                "error_type": type(e).__name__,
                "success": False
            }
        )
        log_database_operation("delete_all_temperatures", success=False, error=str(e))
        db.rollback()
        raise
    finally:
        db.close()


@log_performance
def save_error_log(message: str) -> ErrorLog:
    """Save error log message to database"""
    db = SessionLocal()
    try:
        error_log = ErrorLog(message=message)
        db.add(error_log)
        db.commit()
        db.refresh(error_log)
        
        logger.info(
            "Error log saved to database",
            extra={
                "operation": "save_error_log",
                "database_operation": "insert_error_log",
                "error_message": message[:100] + "..." if len(message) > 100 else message
            }
        )
        log_database_operation("insert_error_log", success=True, record_count=1)
        return error_log
    except Exception as e:
        log_database_operation("insert_error_log", success=False, error=str(e))
        raise
    finally:
        db.close()


@log_performance
def get_error_logs(hours: int = 24) -> list[ErrorLog]:
    """Get error logs from the last N hours"""
    db = SessionLocal()
    try:
        cutoff_time = datetime.now(BERLIN_TZ) - timedelta(hours=hours)
        results = db.query(ErrorLog).filter(
            ErrorLog.timestamp >= cutoff_time
        ).order_by(ErrorLog.timestamp.desc()).all()
        
        logger.info(
            f"Retrieved error logs for {hours} hours",
            extra={
                "operation": "get_error_logs",
                "database_operation": "select_error_logs",
                "hours": hours,
                "record_count": len(results)
            }
        )
        log_database_operation("select_error_logs", success=True, record_count=len(results))
        return results
    except Exception as e:
        log_database_operation("select_error_logs", success=False, error=str(e))
        raise
    finally:
        db.close()


@log_performance
def clear_error_logs() -> int:
    """Clear all error logs from database"""
    db = SessionLocal()
    try:
        logger.info(
            "Clearing all error logs from database",
            extra={
                "operation": "clear_error_logs",
                "database_operation": "delete_all_error_logs"
            }
        )
        count = db.query(ErrorLog).delete()
        db.commit()
        logger.info(
            "Successfully deleted error logs",
            extra={
                "operation": "clear_error_logs",
                "database_operation": "delete_all_error_logs",
                "record_count": count,
                "success": True
            }
        )
        log_database_operation("delete_all_error_logs", success=True, record_count=count)
        return count
    except Exception as e:
        logger.error(
            "Error clearing error logs",
            extra={
                "operation": "clear_error_logs",
                "database_operation": "delete_all_error_logs",
                "error": str(e),
                "error_type": type(e).__name__,
                "success": False
            }
        )
        log_database_operation("delete_all_error_logs", success=False, error=str(e))
        db.rollback()
        raise
    finally:
        db.close()
