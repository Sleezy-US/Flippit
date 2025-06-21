import requests
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import sqlite3
import hashlib
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
import os
import threading
import time
import json
import statistics
import requests
import random
import base64
import hmac

# Import our car scraper
from fb_scraper import CarSearchMonitor

# Import enhanced scraper (if available)
try:
    from enhanced_fb_scraper import EnhancedCarSearchMonitor
    ENHANCED_SCRAPER_AVAILABLE = True
except ImportError:
    ENHANCED_SCRAPER_AVAILABLE = False
    print("⚠️  Enhanced scraper not available, using basic scraper")

# Import the KBB estimator
from kbb_value_estimator import KBBValueEstimator, enhance_car_listing_with_values

# Initialize the value estimator
value_estimator = KBBValueEstimator()

# Configuration
USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "true").lower() == "true"
USE_SELENIUM = os.getenv("USE_SELENIUM", "false").lower() == "true"

# iOS In-App Purchase Configuration
APPLE_SHARED_SECRET = os.getenv("APPLE_SHARED_SECRET", "your_apple_shared_secret")
APPLE_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"
APPLE_PRODUCTION_URL = "https://buy.itunes.apple.com/verifyReceipt"

app = FastAPI(title="Flippit - Enhanced Car Marketplace Monitor API", version="3.2.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security with more robust secret key handling
security = HTTPBearer()
SECRET_KEY = os.getenv("SECRET_KEY", "flippit-default-secret-key-change-this-in-production")

# Print secret key info for debugging (remove in production)
print(f"🔑 Using SECRET_KEY: {SECRET_KEY[:10]}... (length: {len(SECRET_KEY)})")

# Database
DATABASE = "car_marketplace.db"

# Global monitor instance
car_monitor = None
monitor_thread = None

# Admin emails
ADMIN_EMAILS = ["johnsilva36@live.com"]

# Constants for reasonable defaults
CURRENT_YEAR = datetime.now().year
MIN_CAR_YEAR = 1900  # First mass-produced cars
DEFAULT_MIN_YEAR = CURRENT_YEAR - 20  # Default to last 20 years
DEFAULT_MAX_YEAR = CURRENT_YEAR + 1  # Allow for next year's models
DEFAULT_MIN_PRICE = 500
DEFAULT_MAX_PRICE = 100000

# iOS In-App Purchase Product IDs and Pricing
IAP_PRODUCTS = {
    'com.flippit.pro.monthly': {
        'tier': 'pro',
        'duration': 'monthly',
        'price': 14.99,
        'display_price': '$14.99/month'
    },
    'com.flippit.pro.yearly': {
        'tier': 'pro_yearly',
        'duration': 'yearly',
        'price': 152.99,  # 15% off ($179.88 - $26.89 = $152.99)
        'display_price': '$152.99/year (15% off)',
        'original_price': 179.88,
        'savings': 26.89
    },
    'com.flippit.premium.monthly': {
        'tier': 'premium',
        'duration': 'monthly',
        'price': 49.99,
        'display_price': '$49.99/month'
    },
    'com.flippit.premium.yearly': {
        'tier': 'premium_yearly',
        'duration': 'yearly',
        'price': 479.99,  # 20% off ($599.88 - $119.89 = $479.99)
        'display_price': '$479.99/year (20% off)',
        'original_price': 599.88,
        'savings': 119.89
    }
}

# Enhanced Subscription Configuration with Distance Limits
SUBSCRIPTION_LIMITS = {
    'free': {
        'max_searches': 3,
        'interval': 1500,  # 25 minutes
        'max_distance_miles': 25,
        'features': [
            'basic_search',
            'basic_filtering',
            'value_estimates',
            'limited_favorites',
            '25_mile_radius'
        ]
    },
    'pro': {
        'max_searches': 15,
        'interval': 600,  # 10 minutes
        'max_distance_miles': 50,
        'features': [
            'basic_search',
            'advanced_filtering',
            'value_estimates',
            'push_notifications',
            'price_analytics',
            'unlimited_favorites',
            'car_notes',
            '50_mile_radius',
            'priority_support'
        ]
    },
    'pro_yearly': {
        'max_searches': 15,
        'interval': 600,
        'max_distance_miles': 50,
        'features': [
            'basic_search',
            'advanced_filtering',
            'value_estimates',
            'push_notifications',
            'price_analytics',
            'unlimited_favorites',
            'car_notes',
            '50_mile_radius',
            'priority_support'
        ]
    },
    'premium': {
        'max_searches': 25,
        'interval': 300,  # 5 minutes
        'max_distance_miles': 200,
        'features': [
            'all_features',
            'basic_search',
            'advanced_filtering',
            'value_estimates',
            'push_notifications',
            'price_analytics',
            'unlimited_favorites',
            'car_notes',
            'map_view',
            'ai_insights',
            'export_data',
            '200_mile_radius',
            'instant_alerts',
            'priority_support'
        ]
    },
    'premium_yearly': {
        'max_searches': 25,
        'interval': 300,
        'max_distance_miles': 200,
        'features': [
            'all_features',
            'basic_search',
            'advanced_filtering',
            'value_estimates',
            'push_notifications',
            'price_analytics',
            'unlimited_favorites',
            'car_notes',
            'map_view',
            'ai_insights',
            'export_data',
            '200_mile_radius',
            'instant_alerts',
            'priority_support'
        ]
    }
}

# Location coordinates for Florida cities
FLORIDA_CITIES = {
    "cape coral": {"lat": 26.5629, "lng": -81.9495, "fb_id": "112863195403299"},
    "fort myers": {"lat": 26.6406, "lng": -81.8723, "fb_id": "113744028636146"},
    "naples": {"lat": 26.1420, "lng": -81.7948, "fb_id": "112481458764682"},
    "miami": {"lat": 25.7617, "lng": -80.1918, "fb_id": "110148005670892"},
    "tampa": {"lat": 27.9506, "lng": -82.4572, "fb_id": "109155869101760"},
    "orlando": {"lat": 28.5383, "lng": -81.3792, "fb_id": "106050236084297"},
    "jacksonville": {"lat": 30.3322, "lng": -81.6557, "fb_id": "112548152092705"},
    "sarasota": {"lat": 27.3364, "lng": -82.5307, "fb_id": "106430962718962"},
    "port charlotte": {"lat": 26.9762, "lng": -82.0906, "fb_id": "103136976395671"},
    "bonita springs": {"lat": 26.3398, "lng": -81.7787, "fb_id": "112724155411170"}
}

def init_db():
    """Initialize SQLite database with enhanced features"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            subscription_tier TEXT DEFAULT 'free',
            subscription_expires TIMESTAMP,
            trial_ends TIMESTAMP,
            is_trial BOOLEAN DEFAULT FALSE,
            apple_receipt_data TEXT,
            apple_original_transaction_id TEXT,
            apple_latest_transaction_id TEXT,
            apple_subscription_id TEXT,
            cancel_at_period_end BOOLEAN DEFAULT FALSE,
            gifted_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # iOS In-App Purchase receipts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS apple_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            receipt_data TEXT NOT NULL,
            transaction_id TEXT UNIQUE NOT NULL,
            original_transaction_id TEXT,
            product_id TEXT NOT NULL,
            purchase_date TIMESTAMP,
            expires_date TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Car searches table with distance
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS car_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            make TEXT,
            model TEXT,
            year_min INTEGER,
            year_max INTEGER,
            price_min INTEGER,
            price_max INTEGER,
            mileage_max INTEGER,
            location TEXT,
            distance_miles INTEGER DEFAULT 25,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Car listings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS car_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            price TEXT,
            year TEXT,
            mileage TEXT,
            url TEXT,
            found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notified BOOLEAN DEFAULT FALSE,
            fuel_type TEXT,
            transmission TEXT,
            body_style TEXT,
            color TEXT,
            location_lat REAL,
            location_lng REAL,
            distance_miles REAL,
            deal_score REAL,
            is_featured BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (search_id) REFERENCES car_searches (id)
        )
    ''')
    
    # Push notification tokens
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS push_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT NOT NULL,
            platform TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(user_id, token)
        )
    ''')
    
    # Price history for analytics
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            make TEXT,
            model TEXT,
            year INTEGER,
            location TEXT,
            price INTEGER,
            mileage INTEGER,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Favorites table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            listing_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (listing_id) REFERENCES car_listings (id),
            UNIQUE(user_id, listing_id)
        )
    ''')
    
    # Car notes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS car_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            listing_id INTEGER NOT NULL,
            note TEXT,
            status TEXT DEFAULT 'interested',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (listing_id) REFERENCES car_listings (id)
        )
    ''')
    
    # Search suggestions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            make TEXT,
            model TEXT,
            search_count INTEGER DEFAULT 1,
            last_searched TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(make, model)
        )
    ''')
    
    # Deal scores
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deal_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL,
            market_price_estimate INTEGER,
            deal_score REAL,
            quality_indicators TEXT,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (listing_id) REFERENCES car_listings (id)
        )
    ''')
    
    # Notifications
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            listing_id INTEGER NOT NULL,
            notification_type TEXT DEFAULT 'push',
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (listing_id) REFERENCES car_listings (id)
        )
    ''')
    
    # Add new columns if they don't exist
    columns_to_add = [
        ("car_searches", "distance_miles", "INTEGER DEFAULT 25"),
        ("car_listings", "deal_score", "REAL"),
        ("users", "apple_receipt_data", "TEXT"),
        ("users", "apple_original_transaction_id", "TEXT"),
        ("users", "apple_latest_transaction_id", "TEXT"),
        ("users", "apple_subscription_id", "TEXT")
    ]
    
    for table, column, definition in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            print(f"✅ Added {column} column to {table} table")
        except sqlite3.OperationalError:
            pass
    
    conn.commit()
    conn.close()

# Pydantic Models
class UserRegister(BaseModel):
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class CarSearchCreate(BaseModel):
    make: Optional[str] = None
    model: Optional[str] = None
    year_min: Optional[int] = DEFAULT_MIN_YEAR
    year_max: Optional[int] = DEFAULT_MAX_YEAR
    price_min: Optional[int] = DEFAULT_MIN_PRICE
    price_max: Optional[int] = DEFAULT_MAX_PRICE
    mileage_max: Optional[int] = None
    location: Optional[str] = "Cape Coral, FL"
    distance_miles: Optional[int] = None  # Will be set based on subscription

class CarSearchUpdate(BaseModel):
    make: Optional[str] = None
    model: Optional[str] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    mileage_max: Optional[int] = None
    location: Optional[str] = None
    distance_miles: Optional[int] = None

class CarSearchResponse(BaseModel):
    id: int
    make: Optional[str]
    model: Optional[str]
    year_min: Optional[int]
    year_max: Optional[int]
    price_min: Optional[int]
    price_max: Optional[int]
    mileage_max: Optional[int]
    location: Optional[str]
    distance_miles: int
    is_active: bool
    created_at: str

class SubscriptionResponse(BaseModel):
    tier: str
    max_searches: int
    current_searches: int
    interval_minutes: int
    max_distance_miles: int
    features: List[str]
    price: str
    trial_ends: Optional[str] = None
    gifted_by: Optional[str] = None

class AppleReceiptVerification(BaseModel):
    receipt_data: str
    product_id: str

# Apple IAP Helper Functions
async def verify_apple_receipt(receipt_data: str, use_sandbox: bool = True) -> Dict:
    """
    Verify Apple receipt with App Store
    """
    url = APPLE_SANDBOX_URL if use_sandbox else APPLE_PRODUCTION_URL
    
    payload = {
        'receipt-data': receipt_data,
        'password': APPLE_SHARED_SECRET,
        'exclude-old-transactions': True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        result = response.json()
        
        # If sandbox fails and we get status 21007, try production
        if result.get('status') == 21007 and use_sandbox:
            return await verify_apple_receipt(receipt_data, use_sandbox=False)
        
        return result
    except Exception as e:
        print(f"Apple receipt verification failed: {e}")
        return {'status': 99999, 'error': str(e)}

def parse_apple_receipt(receipt_data: Dict) -> Optional[Dict]:
    """
    Parse Apple receipt data to extract subscription info
    """
    try:
        receipt = receipt_data.get('receipt', {})
        latest_receipt_info = receipt_data.get('latest_receipt_info', [])
        
        if not latest_receipt_info:
            return None
        
        # Get the most recent transaction
        latest_transaction = max(latest_receipt_info,
                               key=lambda x: x.get('purchase_date_ms', '0'))
        
        expires_date_ms = latest_transaction.get('expires_date_ms')
        expires_date = None
        if expires_date_ms:
            expires_date = datetime.fromtimestamp(int(expires_date_ms) / 1000)
        
        purchase_date_ms = latest_transaction.get('purchase_date_ms')
        purchase_date = None
        if purchase_date_ms:
            purchase_date = datetime.fromtimestamp(int(purchase_date_ms) / 1000)
        
        return {
            'product_id': latest_transaction.get('product_id'),
            'transaction_id': latest_transaction.get('transaction_id'),
            'original_transaction_id': latest_transaction.get('original_transaction_id'),
            'purchase_date': purchase_date,
            'expires_date': expires_date,
            'is_active': expires_date > datetime.now() if expires_date else False
        }
    except Exception as e:
        print(f"Error parsing Apple receipt: {e}")
        return None

def get_subscription_tier_from_product_id(product_id: str) -> str:
    """
    Map Apple product ID to subscription tier
    """
    product_info = IAP_PRODUCTS.get(product_id)
    return product_info['tier'] if product_info else 'free'

# Helper functions
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

def create_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    print(f"🔑 Created token for user {user_id} with secret: {SECRET_KEY[:10]}...")
    return token

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        print(f"🔍 Verifying token with secret: {SECRET_KEY[:10]}...")
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        print(f"✅ Token verified successfully for user: {payload['user_id']}")
        return payload["user_id"]
    except jwt.ExpiredSignatureError:
        print("❌ Token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError as e:
        print(f"❌ Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

def get_user_subscription_tier(user_id: int) -> str:
    """Get user's current subscription tier"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT subscription_tier FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else 'free'

def get_subscription_limits(tier: str) -> dict:
    """Get limits for a subscription tier"""
    # Map yearly tiers to base tier
    if tier == 'pro_yearly':
        tier = 'pro'
    elif tier == 'premium_yearly':
        tier = 'premium'
    
    return SUBSCRIPTION_LIMITS.get(tier, SUBSCRIPTION_LIMITS['free'])

def get_location_info(location_str: str) -> dict:
    """Get location coordinates and Facebook ID"""
    if not location_str:
        return FLORIDA_CITIES["cape coral"]
    
    # Clean the location string
    location_lower = location_str.lower().strip()
    
    # Remove state abbreviations
    location_lower = location_lower.replace(", fl", "").replace(", florida", "")
    
    # Check if it's a known city
    for city, info in FLORIDA_CITIES.items():
        if city in location_lower:
            return info
    
    # Default to Cape Coral if not found
    return FLORIDA_CITIES["cape coral"]

def get_mock_cars(search_config):
    """Get mock car data with value estimates for testing"""
    make = search_config.get('make', 'Toyota')
    model = search_config.get('model', 'Camry')
    location = search_config.get('location', 'Cape Coral, FL')
    
    # Create realistic mock cars with varying prices for different deal scores
    mock_cars = [
        {
            "id": f"mock_{int(time.time())}_{random.randint(1000, 9999)}",
            "title": f"2021 {make} {model} LE - Excellent Condition",
            "price": "$19,500",  # Fair price
            "year": "2021",
            "make": make,
            "model": model,
            "mileage": "25,000 miles",
            "url": f"https://facebook.com/marketplace/item/mock1",
            "location": location,
            "source": "mock_data",
            "fuel_type": "Gasoline",
            "transmission": "Automatic",
            "scraped_at": datetime.now().isoformat()
        },
        {
            "id": f"mock_{int(time.time())}_{random.randint(1000, 9999)}",
            "title": f"2019 {make} {model} XLE - Low Miles",
            "price": "$15,900",  # Great deal
            "year": "2019",
            "make": make,
            "model": model,
            "mileage": "38,000 miles",
            "url": f"https://facebook.com/marketplace/item/mock2",
            "location": location,
            "source": "mock_data",
            "fuel_type": "Gasoline",
            "transmission": "Automatic",
            "scraped_at": datetime.now().isoformat()
        },
        {
            "id": f"mock_{int(time.time())}_{random.randint(1000, 9999)}",
            "title": f"2020 {make} {model} SE - One Owner",
            "price": "$14,500",  # Hot deal!
            "year": "2020",
            "make": make,
            "model": model,
            "mileage": "42,000 miles",
            "url": f"https://facebook.com/marketplace/item/mock3",
            "location": location,
            "source": "mock_data",
            "fuel_type": "Hybrid",
            "transmission": "CVT",
            "scraped_at": datetime.now().isoformat()
        }
    ]
    
    # Filter by price if specified
    if search_config.get('price_max'):
        mock_cars = [car for car in mock_cars
                    if int(car['price'].replace('$', '').replace(',', '')) <= search_config['price_max']]
    
    # Filter by year if specified
    if search_config.get('year_min'):
        mock_cars = [car for car in mock_cars
                    if int(car.get('year', '0')) >= search_config['year_min']]
    
    # Enhance each car with value estimates
    enhanced_cars = []
    for car in mock_cars:
        enhanced_car = enhance_car_listing_with_values(car, value_estimator)
        enhanced_cars.append(enhanced_car)
    
    return enhanced_cars

def enhanced_save_car_listings(search_id: int, cars: list):
    """Save car listings with value estimates and deal scoring"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Get search details
    cursor.execute("SELECT make, model, location FROM car_searches WHERE id = ?", (search_id,))
    search_info = cursor.fetchone()
    search_make = search_info[0] if search_info else None
    search_model = search_info[1] if search_info else None
    
    for car in cars:
        # Add make/model from search if not in car data
        if not car.get('make') and search_make:
            car['make'] = search_make
        if not car.get('model') and search_model:
            car['model'] = search_model
            
        # Enhance with value estimates
        car = enhance_car_listing_with_values(car, value_estimator)
        
        # Insert car listing
        cursor.execute("""
            INSERT INTO car_listings 
            (search_id, title, price, year, mileage, url, fuel_type, transmission, 
             body_style, color, deal_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            search_id,
            car['title'],
            car['price'],
            car.get('year'),
            car.get('mileage'),
            car.get('url'),
            car.get('fuel_type'),
            car.get('transmission'),
            car.get('body_style'),
            car.get('color'),
            car.get('deal_score', {}).get('score') if car.get('has_analysis') else None
        ))
        
        listing_id = cursor.lastrowid
        
        # Save value estimate data if available
        if car.get('has_analysis') and car.get('value_estimate'):
            cursor.execute("""
                INSERT INTO deal_scores 
                (listing_id, market_price_estimate, deal_score, quality_indicators, calculated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                listing_id,
                car['value_estimate']['values']['private_party'],
                car['deal_score']['score'],
                json.dumps({
                    'value_estimate': car['value_estimate'],
                    'deal_score': car['deal_score']
                }),
                datetime.now().isoformat()
            ))
        
        # Add to price history
        try:
            price_text = car['price'].replace('$', '').replace(',', '')
            price_num = int(price_text) if price_text.isdigit() else None
            
            year_text = car.get('year', '')
            year_num = int(year_text) if str(year_text).isdigit() else None
            
            mileage_text = str(car.get('mileage', '')).replace(',', '').replace(' miles', '')
            mileage_num = int(mileage_text) if mileage_text.isdigit() else None
            
            if search_info and price_num:
                cursor.execute("""
                    INSERT INTO price_history (make, model, year, location, price, mileage)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (search_make, search_model, year_num, search_info[2], price_num, mileage_num))
        except Exception as e:
            print(f"Error saving price history: {e}")
    
    conn.commit()
    conn.close()

def update_search_suggestions():
    """Update search suggestions based on current searches"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT make, model, COUNT(*) as count
        FROM car_searches 
        WHERE make IS NOT NULL OR model IS NOT NULL
        GROUP BY make, model
    """)
    
    suggestions = cursor.fetchall()
    
    for make, model, count in suggestions:
        if make and model:
            cursor.execute("""
                INSERT OR REPLACE INTO search_suggestions (make, model, search_count)
                VALUES (?, ?, ?)
            """, (make, model, count))
        elif make:
            cursor.execute("""
                INSERT OR REPLACE INTO search_suggestions (make, search_count)
                VALUES (?, ?)
            """, (make, count))
    
    conn.commit()
    conn.close()

# Background monitoring
def run_continuous_monitoring():
    """Run car monitoring with subscription tiers and distance limits"""
    global car_monitor
    
    # Initialize monitor
    if car_monitor is None:
        if ENHANCED_SCRAPER_AVAILABLE:
            car_monitor = EnhancedCarSearchMonitor(use_selenium=False, use_mock_data=USE_MOCK_DATA)
        else:
            car_monitor = CarSearchMonitor()
    
    print("🚀 Starting Enhanced Flippit monitoring!")
    print(f"📊 Mock data: {'Enabled' if USE_MOCK_DATA else 'Disabled'}")
    print(f"🌐 Selenium: {'Enabled' if USE_SELENIUM and ENHANCED_SCRAPER_AVAILABLE else 'Disabled'}")
    
    while True:
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            
            # Process searches by tier
            for tier, limits in SUBSCRIPTION_LIMITS.items():
                tier_conditions = [tier]
                if tier == 'pro':
                    tier_conditions.append('pro_yearly')
                elif tier == 'premium':
                    tier_conditions.append('premium_yearly')
                
                placeholders = ','.join(['?' for _ in tier_conditions])
                
                cursor.execute(f"""
                    SELECT cs.id, cs.make, cs.model, cs.year_min, cs.year_max, 
                           cs.price_min, cs.price_max, cs.mileage_max, cs.location,
                           cs.distance_miles, u.subscription_tier, u.email, u.id
                    FROM car_searches cs
                    JOIN users u ON cs.user_id = u.id 
                    WHERE cs.is_active = TRUE AND u.subscription_tier IN ({placeholders})
                """, tier_conditions)
                
                tier_searches = cursor.fetchall()
                
                if tier_searches:
                    print(f"🔄 Processing {len(tier_searches)} {tier.upper()} searches")
                    
                    for search_row in tier_searches:
                        search_id = search_row[0]
                        user_id = search_row[12]
                        
                        # Get location info
                        location_info = get_location_info(search_row[8])
                        
                        search_config = {
                            'make': search_row[1],
                            'model': search_row[2],
                            'year_min': search_row[3],
                            'year_max': search_row[4],
                            'price_min': search_row[5],
                            'price_max': search_row[6],
                            'mileage_max': search_row[7],
                            'location': search_row[8] or 'Cape Coral, FL',
                            'distance_miles': search_row[9],
                            'lat': location_info['lat'],
                            'lng': location_info['lng'],
                            'fb_location_id': location_info['fb_id']
                        }
                        
                        try:
                            new_cars = car_monitor.monitor_car_search(search_config)
                            
                            # Use mock data if enabled and no real results
                            if not new_cars and USE_MOCK_DATA:
                                print("📊 Using mock data for testing")
                                new_cars = get_mock_cars(search_config)
                            
                            if new_cars:
                                enhanced_save_car_listings(search_id, new_cars)
                                
                                search_name = f"{search_config.get('make', '')} {search_config.get('model', '')}".strip()
                                print(f"🚗 Found {len(new_cars)} new {search_name} cars!")
                                
                                if new_cars and new_cars[0].get('deal_score'):
                                    print(f"   Best deal: {new_cars[0]['deal_score']['rating']}")
                        
                        except Exception as e:
                            print(f"❌ Error monitoring search {search_id}: {e}")
                        
                        time.sleep(3)
                
                time.sleep(5)
            
            conn.close()
            
            update_search_suggestions()
            
            # Wait before next cycle
            min_interval = min(limits['interval'] for limits in SUBSCRIPTION_LIMITS.values())
            print(f"💤 Next monitoring cycle in {min_interval//60} minutes...")
            time.sleep(min_interval)
            
        except Exception as e:
            print(f"❌ Error in monitoring: {e}")
            time.sleep(60)

# API Routes

@app.on_event("startup")
async def startup_event():
    init_db()
    update_search_suggestions()
    
    global monitor_thread
    if monitor_thread is None:
        monitor_thread = threading.Thread(target=run_continuous_monitoring, daemon=True)
        monitor_thread.start()
        print("🚀 Enhanced Flippit monitoring started!")

@app.get("/")
async def root():
    return {
        "message": "🚗 Flippit - Enhanced Car Marketplace Monitor",
        "version": "3.2.0",
        "features": "iOS In-App Purchase, Distance-based search limits, KBB-style values, AI deal scoring",
        "docs": "/docs"
    }

@app.get("/debug-auth")
async def debug_auth():
    """Debug endpoint to check auth configuration"""
    return {
        "secret_key_length": len(SECRET_KEY),
        "secret_key_preview": SECRET_KEY[:10] + "...",
        "message": "Check if this secret key matches between login and verification"
    }

@app.get("/pricing")
async def get_pricing():
    """Get iOS subscription pricing information"""
    return {
        "platform": "ios",
        "products": IAP_PRODUCTS,
        "tiers": {
            "free": {
                "name": "Free",
                "price": "$0/month",
                "searches": 3,
                "refresh_minutes": 25,
                "search_radius": "25 miles",
                "features": [
                    "Basic search",
                    "Basic filtering",
                    "Value estimates",
                    "25 mile search radius"
                ]
            },
            "pro": {
                "name": "Pro",
                "monthly_price": "$14.99/month",
                "yearly_price": "$152.99/year (15% off)",
                "yearly_savings": "$26.89",
                "searches": 15,
                "refresh_minutes": 10,
                "search_radius": "50 miles",
                "features": [
                    "Everything in Free",
                    "50 mile search radius",
                    "Push notifications",
                    "Price analytics",
                    "Unlimited favorites",
                    "Car notes",
                    "Priority support"
                ]
            },
            "premium": {
                "name": "Premium",
                "monthly_price": "$49.99/month",
                "yearly_price": "$479.99/year (20% off)",
                "yearly_savings": "$119.89",
                "searches": 25,
                "refresh_minutes": 5,
                "search_radius": "200 miles",
                "features": [
                    "Everything in Pro",
                    "200 mile search radius",
                    "Map view",
                    "AI insights",
                    "Export data",
                    "Instant alerts",
                    "Premium support"
                ]
            }
        }
    }

@app.post("/register")
async def register(user: UserRegister):
    """Free registration"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO users (email, password_hash, subscription_tier) VALUES (?, ?, ?)",
            (user.email, hash_password(user.password), 'free')
        )
        conn.commit()
        user_id = cursor.lastrowid
        token = create_token(user_id)
        
        return {
            "token": token,
            "user_id": user_id,
            "subscription_tier": "free",
            "message": "Welcome to Flippit! You can search within 25 miles. Upgrade to Pro for 50 miles or Premium for 200 miles!"
        }
    
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Email already registered")
    finally:
        conn.close()

@app.post("/login")
async def login(user: UserLogin):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, password_hash, subscription_tier 
        FROM users WHERE email = ?
    """, (user.email,))
    db_user = cursor.fetchone()
    conn.close()
    
    if not db_user or not verify_password(user.password, db_user[1]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user_id, _, subscription_tier = db_user
    token = create_token(user_id)
    
    return {
        "token": token,
        "user_id": user_id,
        "subscription_tier": subscription_tier
    }

@app.post("/verify-purchase")
async def verify_purchase(receipt: AppleReceiptVerification, user_id: int = Depends(verify_token)):
    """
    Verify iOS In-App Purchase and activate subscription
    """
    try:
        # Verify receipt with Apple
        verification_result = await verify_apple_receipt(receipt.receipt_data)
        
        if verification_result.get('status') != 0:
            raise HTTPException(
                status_code=400,
                detail=f"Receipt verification failed: {verification_result.get('status')}"
            )
        
        # Parse receipt data
        purchase_info = parse_apple_receipt(verification_result)
        
        if not purchase_info:
            raise HTTPException(status_code=400, detail="Invalid receipt data")
        
        # Verify product ID matches
        if purchase_info['product_id'] != receipt.product_id:
            raise HTTPException(status_code=400, detail="Product ID mismatch")
        
        # Check if purchase is active
        if not purchase_info['is_active']:
            raise HTTPException(status_code=400, detail="Subscription has expired")
        
        # Get subscription tier from product ID
        subscription_tier = get_subscription_tier_from_product_id(receipt.product_id)
        
        # Update user subscription
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users SET 
                subscription_tier = ?,
                subscription_expires = ?,
                apple_receipt_data = ?,
                apple_original_transaction_id = ?,
                apple_latest_transaction_id = ?,
                apple_subscription_id = ?
            WHERE id = ?
        """, (
            subscription_tier,
            purchase_info['expires_date'],
            receipt.receipt_data,
            purchase_info['original_transaction_id'],
            purchase_info['transaction_id'],
            receipt.product_id,
            user_id
        ))
        
        # Save receipt record
        cursor.execute("""
            INSERT OR REPLACE INTO apple_receipts 
            (user_id, receipt_data, transaction_id, original_transaction_id, 
             product_id, purchase_date, expires_date, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            receipt.receipt_data,
            purchase_info['transaction_id'],
            purchase_info['original_transaction_id'],
            receipt.product_id,
            purchase_info['purchase_date'],
            purchase_info['expires_date'],
            purchase_info['is_active']
        ))
        
        conn.commit()
        conn.close()
        
        product_info = IAP_PRODUCTS.get(receipt.product_id, {})
        
        return {
            "success": True,
            "subscription_tier": subscription_tier,
            "expires_date": purchase_info['expires_date'].isoformat() if purchase_info['expires_date'] else None,
            "product_info": product_info,
            "message": f"Successfully activated {product_info.get('display_price', 'subscription')}!"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Purchase verification error: {e}")
        raise HTTPException(status_code=500, detail="Purchase verification failed")

@app.post("/restore-purchases")
async def restore_purchases(receipt: AppleReceiptVerification, user_id: int = Depends(verify_token)):
    """
    Restore previous iOS purchases
    """
    try:
        # Verify receipt with Apple
        verification_result = await verify_apple_receipt(receipt.receipt_data)
        
        if verification_result.get('status') != 0:
            raise HTTPException(status_code=400, detail="Receipt verification failed")
        
        # Get all transactions from receipt
        latest_receipt_info = verification_result.get('latest_receipt_info', [])
        
        if not latest_receipt_info:
            return {"restored": False, "message": "No purchases found to restore"}
        
        # Find the most recent active subscription
        active_subscription = None
        for transaction in latest_receipt_info:
            expires_date_ms = transaction.get('expires_date_ms')
            if expires_date_ms:
                expires_date = datetime.fromtimestamp(int(expires_date_ms) / 1000)
                if expires_date > datetime.now():
                    if not active_subscription or expires_date > active_subscription['expires_date']:
                        active_subscription = {
                            'product_id': transaction.get('product_id'),
                            'transaction_id': transaction.get('transaction_id'),
                            'original_transaction_id': transaction.get('original_transaction_id'),
                            'expires_date': expires_date,
                            'purchase_date': datetime.fromtimestamp(int(transaction.get('purchase_date_ms', 0)) / 1000)
                        }
        
        if not active_subscription:
            return {"restored": False, "message": "No active subscriptions found"}
        
        # Restore the subscription
        subscription_tier = get_subscription_tier_from_product_id(active_subscription['product_id'])
        
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users SET 
                subscription_tier = ?,
                subscription_expires = ?,
                apple_receipt_data = ?,
                apple_original_transaction_id = ?,
                apple_latest_transaction_id = ?,
                apple_subscription_id = ?
            WHERE id = ?
        """, (
            subscription_tier,
            active_subscription['expires_date'],
            receipt.receipt_data,
            active_subscription['original_transaction_id'],
            active_subscription['transaction_id'],
            active_subscription['product_id'],
            user_id
        ))
        
        conn.commit()
        conn.close()
        
        product_info = IAP_PRODUCTS.get(active_subscription['product_id'], {})
        
        return {
            "restored": True,
            "subscription_tier": subscription_tier,
            "expires_date": active_subscription['expires_date'].isoformat(),
            "product_info": product_info,
            "message": f"Successfully restored {product_info.get('display_price', 'subscription')}!"
        }
        
    except Exception as e:
        print(f"Restore purchases error: {e}")
        raise HTTPException(status_code=500, detail="Failed to restore purchases")

@app.get("/subscription")
async def get_subscription(request: Request):
    """Get subscription info with better error handling"""
    try:
        # Try to get the authorization header
        auth_header = request.headers.get("authorization")
        
        if not auth_header:
            # Return default free subscription if no auth
            return {
                "tier": "free",
                "max_searches": 3,
                "current_searches": 0,
                "interval_minutes": 25,
                "max_distance_miles": 25,
                "features": ["basic_search", "value_estimates", "25_mile_radius"],
                "price": "$0/month",
                "trial_ends": None,
                "gifted_by": None,
                "platform": "ios"
            }
        
        # Try to verify the token
        try:
            token = auth_header.replace("Bearer ", "")
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user_id = payload["user_id"]
        except Exception as token_error:
            # Return default if token verification fails
            print(f"Token verification failed: {token_error}")
            return {
                "tier": "free",
                "max_searches": 3,
                "current_searches": 0,
                "interval_minutes": 25,
                "max_distance_miles": 25,
                "features": ["basic_search", "value_estimates", "25_mile_radius"],
                "price": "$0/month",
                "trial_ends": None,
                "gifted_by": None,
                "platform": "ios"
            }
        
        # Get user's actual subscription
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT subscription_tier, subscription_expires, trial_ends, gifted_by 
            FROM users WHERE id = ?
        """, (user_id,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            # Return default instead of 404
            return {
                "tier": "free",
                "max_searches": 3,
                "current_searches": 0,
                "interval_minutes": 25,
                "max_distance_miles": 25,
                "features": ["basic_search", "value_estimates", "25_mile_radius"],
                "price": "$0/month",
                "trial_ends": None,
                "gifted_by": None,
                "platform": "ios"
            }
        
        tier, subscription_expires, trial_ends, gifted_by = result
        
        # Check if subscription has expired
        if subscription_expires:
            expires_date = datetime.fromisoformat(subscription_expires.replace('Z', '+00:00'))
            if expires_date < datetime.now(timezone.utc):
                # Subscription expired, downgrade to free
                cursor.execute("UPDATE users SET subscription_tier = 'free' WHERE id = ?", (user_id,))
                conn.commit()
                tier = 'free'
        
        limits = get_subscription_limits(tier)
        
        # Count current searches
        cursor.execute("SELECT COUNT(*) FROM car_searches WHERE user_id = ? AND is_active = TRUE", (user_id,))
        current_searches = cursor.fetchone()[0]
        
        conn.close()
        
        # Get display price for current tier
        display_prices = {
            "free": "$0/month",
            "pro": "$14.99/month",
            "pro_yearly": "$152.99/year (15% off)",
            "premium": "$49.99/month",
            "premium_yearly": "$479.99/year (20% off)"
        }
        
        return {
            "tier": tier,
            "max_searches": limits['max_searches'],
            "current_searches": current_searches,
            "interval_minutes": limits['interval'] // 60,
            "max_distance_miles": limits['max_distance_miles'],
            "features": limits['features'],
            "price": display_prices.get(tier, "$0/month"),
            "trial_ends": trial_ends,
            "gifted_by": gifted_by,
            "platform": "ios",
            "expires_date": subscription_expires
        }
        
    except Exception as e:
        print(f"Subscription endpoint error: {e}")
        # Return default subscription on any error
        return {
            "tier": "free",
            "max_searches": 3,
            "current_searches": 0,
            "interval_minutes": 25,
            "max_distance_miles": 25,
            "features": ["basic_search", "value_estimates", "25_mile_radius"],
            "price": "$0/month",
            "trial_ends": None,
            "gifted_by": None,
            "platform": "ios"
        }

@app.post("/car-searches", response_model=CarSearchResponse)
async def create_car_search(search: CarSearchCreate, user_id: int = Depends(verify_token)):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Get user's subscription
    tier = get_user_subscription_tier(user_id)
    limits = get_subscription_limits(tier)
    
    # Check search count
    cursor.execute("SELECT COUNT(*) FROM car_searches WHERE user_id = ? AND is_active = TRUE", (user_id,))
    current_count = cursor.fetchone()[0]
    
    if current_count >= limits['max_searches']:
        raise HTTPException(
            status_code=403,
            detail=f"Search limit reached! {tier} tier allows {limits['max_searches']} searches."
        )
    
    # Set distance based on subscription or use provided value if within limits
    if search.distance_miles:
        if search.distance_miles > limits['max_distance_miles']:
            raise HTTPException(
                status_code=403,
                detail=f"{tier} tier allows searches up to {limits['max_distance_miles']} miles. Upgrade for wider search!"
            )
        distance = search.distance_miles
    else:
        distance = limits['max_distance_miles']
    
    # Validate year ranges
    if search.year_min and search.year_min < MIN_CAR_YEAR:
        search.year_min = MIN_CAR_YEAR
    if search.year_max and search.year_max > DEFAULT_MAX_YEAR:
        search.year_max = DEFAULT_MAX_YEAR
    
    # Create the search
    cursor.execute(
        """INSERT INTO car_searches 
           (user_id, make, model, year_min, year_max, price_min, price_max, 
            mileage_max, location, distance_miles) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, search.make, search.model, search.year_min, search.year_max,
         search.price_min, search.price_max, search.mileage_max, search.location, distance)
    )
    
    search_id = cursor.lastrowid
    conn.commit()
    
    # Get the created search
    cursor.execute("SELECT * FROM car_searches WHERE id = ?", (search_id,))
    row = cursor.fetchone()
    conn.close()
    
    if search.make or search.model:
        update_search_suggestions()
    
    return CarSearchResponse(
        id=row[0],
        make=row[2],
        model=row[3],
        year_min=row[4],
        year_max=row[5],
        price_min=row[6],
        price_max=row[7],
        mileage_max=row[8],
        location=row[9],
        distance_miles=row[10],
        is_active=row[11],
        created_at=row[12]
    )

@app.get("/car-searches", response_model=List[CarSearchResponse])
async def get_car_searches(user_id: int = Depends(verify_token)):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM car_searches WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    return [
        CarSearchResponse(
            id=row[0],
            make=row[2],
            model=row[3],
            year_min=row[4],
            year_max=row[5],
            price_min=row[6],
            price_max=row[7],
            mileage_max=row[8],
            location=row[9],
            distance_miles=row[10] if len(row) > 10 else 25,
            is_active=row[11] if len(row) > 11 else True,
            created_at=row[12] if len(row) > 12 else ""
        ) for row in rows
    ]

@app.put("/car-searches/{search_id}")
async def update_car_search(search_id: int, search: CarSearchUpdate, user_id: int = Depends(verify_token)):
    """Update existing car search"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Verify ownership
    cursor.execute("SELECT user_id FROM car_searches WHERE id = ?", (search_id,))
    search_owner = cursor.fetchone()
    
    if not search_owner or search_owner[0] != user_id:
        raise HTTPException(status_code=404, detail="Search not found")
    
    # Check distance limits if updating
    if search.distance_miles:
        tier = get_user_subscription_tier(user_id)
        limits = get_subscription_limits(tier)
        
        if search.distance_miles > limits['max_distance_miles']:
            raise HTTPException(
                status_code=403,
                detail=f"{tier} tier allows searches up to {limits['max_distance_miles']} miles."
            )
    
    # Build update query
    update_fields = []
    values = []
    
    for field, value in search.dict(exclude_unset=True).items():
        update_fields.append(f"{field} = ?")
        values.append(value)
    
    if update_fields:
        values.append(search_id)
        cursor.execute(f"""
            UPDATE car_searches 
            SET {', '.join(update_fields)}
            WHERE id = ?
        """, values)
        
        conn.commit()
    
    conn.close()
    return {"message": "Search updated successfully"}

@app.delete("/car-searches/{search_id}")
async def delete_car_search(search_id: int, user_id: int = Depends(verify_token)):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM car_searches WHERE id = ?", (search_id,))
    search = cursor.fetchone()
    
    if not search or search[0] != user_id:
        raise HTTPException(status_code=404, detail="Search not found")
    
    cursor.execute("DELETE FROM car_searches WHERE id = ?", (search_id,))
    conn.commit()
    conn.close()
    
    return {"message": "Car search deleted successfully"}

@app.get("/all-deals")
async def get_all_deals(user_id: int = Depends(verify_token)):
    """Get all found cars with value analysis"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                cl.id, cl.search_id, cl.title, cl.price, cl.year, cl.mileage,
                cl.url, cl.found_at, cl.fuel_type, cl.transmission, cl.deal_score,
                cs.make, cs.model,
                ds.quality_indicators
            FROM car_listings cl
            JOIN car_searches cs ON cl.search_id = cs.id
            LEFT JOIN deal_scores ds ON cl.id = ds.listing_id
            WHERE cs.user_id = ?
            ORDER BY cl.found_at DESC
            LIMIT 100
        """, (user_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        deals = []
        for row in rows:
            deal = {
                "id": row[0],
                "search_id": row[1],
                "title": row[2],
                "price": row[3],
                "year": row[4],
                "mileage": row[5],
                "url": row[6],
                "found_at": row[7],
                "fuel_type": row[8],
                "transmission": row[9],
                "deal_score_value": row[10],
                "search_make": row[11],
                "search_model": row[12],
                "is_mock": "mock_data" in (row[6] or "")
            }
            
            # Add value analysis if available
            if row[13]:  # quality_indicators
                try:
                    analysis_data = json.loads(row[13])
                    deal['value_estimate'] = analysis_data.get('value_estimate')
                    deal['deal_score'] = analysis_data.get('deal_score')
                    deal['has_analysis'] = True
                except:
                    deal['has_analysis'] = False
            else:
                deal['has_analysis'] = False
            
            deals.append(deal)
        
        return {"deals": deals, "total": len(deals)}
        
    except Exception as e:
        print(f"Error in all-deals: {e}")
        conn.close()
        return {"deals": [], "total": 0}

@app.get("/test-search/{search_id}")
async def test_car_search(search_id: int, user_id: int = Depends(verify_token)):
    """Manually trigger a search test with mock data"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM car_searches 
        WHERE id = ? AND user_id = ?
    """, (search_id, user_id))
    
    search = cursor.fetchone()
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    
    search_config = {
        'make': search[2],
        'model': search[3],
        'year_min': search[4],
        'year_max': search[5],
        'price_min': search[6],
        'price_max': search[7],
        'mileage_max': search[8],
        'location': search[9] or 'Cape Coral, FL',
        'distance_miles': search[10] if len(search) > 10 else 25
    }
    
    # Force mock data
    mock_cars = get_mock_cars(search_config)
    
    # Save mock cars
    enhanced_save_car_listings(search_id, mock_cars)
    
    conn.close()
    
    return {
        "message": f"Added {len(mock_cars)} test cars with value analysis",
        "search_config": search_config,
        "sample_car": mock_cars[0] if mock_cars else None
    }

@app.get("/config")
async def get_config():
    """Get current configuration"""
    return {
        "platform": "ios",
        "use_mock_data": USE_MOCK_DATA,
        "use_selenium": USE_SELENIUM,
        "enhanced_scraper": ENHANCED_SCRAPER_AVAILABLE,
        "version": "3.2.0",
        "features": {
            "ios_iap": True,
            "distance_limits": True,
            "kbb_values": True,
            "deal_scoring": True,
            "market_insights": True,
            "mock_data": USE_MOCK_DATA
        },
        "year_limits": {
            "min": MIN_CAR_YEAR,
            "default_min": DEFAULT_MIN_YEAR,
            "default_max": DEFAULT_MAX_YEAR,
            "current_year": CURRENT_YEAR
        },
        "iap_products": IAP_PRODUCTS,
        "secret_key_info": {
            "length": len(SECRET_KEY),
            "preview": SECRET_KEY[:10] + "..."
        }
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print("🍎 Starting Enhanced Flippit API Server v3.2.0 with iOS
