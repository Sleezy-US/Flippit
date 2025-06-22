import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")

# Create a connection pool
connection_pool = None

def init_db():
    """Initialize the database connection pool and create tables"""
    global connection_pool
    
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set!")
    
    # Create connection pool
    connection_pool = SimpleConnectionPool(1, 20, DATABASE_URL)
    
    # Create tables
    with get_db_cursor() as cursor:
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                subscription_tier VARCHAR(50) DEFAULT 'free',
                subscription_expires TIMESTAMP,
                trial_ends TIMESTAMP,
                gifted_by VARCHAR(255),
                apple_receipt_data TEXT,
                apple_original_transaction_id VARCHAR(255),
                apple_latest_transaction_id VARCHAR(255),
                apple_subscription_id VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Car searches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS car_searches (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                make VARCHAR(100),
                model VARCHAR(100),
                year_min INTEGER,
                year_max INTEGER,
                price_min INTEGER,
                price_max INTEGER,
                mileage_max INTEGER,
                location VARCHAR(255),
                distance_miles INTEGER DEFAULT 25,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Car listings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS car_listings (
                id SERIAL PRIMARY KEY,
                search_id INTEGER REFERENCES car_searches(id) ON DELETE CASCADE,
                title VARCHAR(500),
                price VARCHAR(50),
                year VARCHAR(10),
                mileage VARCHAR(50),
                url TEXT,
                fuel_type VARCHAR(50),
                transmission VARCHAR(50),
                body_style VARCHAR(50),
                color VARCHAR(50),
                deal_score FLOAT,
                found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Deal scores table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deal_scores (
                id SERIAL PRIMARY KEY,
                listing_id INTEGER REFERENCES car_listings(id) ON DELETE CASCADE,
                market_price_estimate FLOAT,
                deal_score FLOAT,
                quality_indicators JSONB,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Price history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id SERIAL PRIMARY KEY,
                make VARCHAR(100),
                model VARCHAR(100),
                year INTEGER,
                location VARCHAR(255),
                price INTEGER,
                mileage INTEGER,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Search suggestions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_suggestions (
                id SERIAL PRIMARY KEY,
                make VARCHAR(100),
                model VARCHAR(100),
                search_count INTEGER DEFAULT 1,
                UNIQUE(make, model)
            )
        """)
        
        # Apple receipts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS apple_receipts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                receipt_data TEXT,
                transaction_id VARCHAR(255) UNIQUE,
                original_transaction_id VARCHAR(255),
                product_id VARCHAR(255),
                purchase_date TIMESTAMP,
                expires_date TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_searches_user ON car_searches(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_search ON car_listings(search_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_deal_score ON car_listings(deal_score)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        
        logger.info("Database tables created successfully")

@contextmanager
def get_db_cursor():
    """Get a database cursor from the connection pool"""
    connection = None
    cursor = None
    try:
        connection = connection_pool.getconn()
        cursor = connection.cursor()
        yield cursor
        connection.commit()
    except Exception as e:
        if connection:
            connection.rollback()
        raise e
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection_pool.putconn(connection)

def execute_query(query, params=None, fetch_one=False, fetch_all=False):
    """Execute a query and optionally fetch results"""
    with get_db_cursor() as cursor:
        cursor.execute(query, params)
        if fetch_one:
            return cursor.fetchone()
        elif fetch_all:
            return cursor.fetchall()
        return None

def execute_insert(query, params=None, returning_id=False):
    """Execute an insert query and optionally return the inserted ID"""
    with get_db_cursor() as cursor:
        if returning_id:
            query += " RETURNING id"
        cursor.execute(query, params)
        if returning_id:
            return cursor.fetchone()[0]
        return None
