import stripe
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import sqlite3
import hashlib
from jose import jwt
from datetime import datetime, timedelta
import os
import threading
import time
import json
import statistics
import requests
import random

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

# Stripe configuration
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_your_stripe_key_here")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_your_webhook_secret")

app = FastAPI(title="Flippit - Enhanced Car Marketplace Monitor API", version="3.1.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")

# Database
DATABASE = "car_marketplace.db"

# Global monitor instance
car_monitor = None
monitor_thread = None

# Admin emails - UPDATE THIS WITH YOUR ACTUAL EMAIL
ADMIN_EMAILS = ["johnsilva36@live.com"]  # Replace with your actual email

# Enhanced Subscription Configuration with Feature Gating
SUBSCRIPTION_INTERVALS = {
    'free': 1500,      # 25 minutes
    'pro': 600,        # 10 minutes
    'premium': 300,    # 5 minutes
}

SUBSCRIPTION_LIMITS = {
    'free': {
        'max_searches': 3,
        'interval': 1500,
        'features': [
            'basic_search',
            'basic_filtering',
            'basic_deal_scoring',
            'limited_favorites'
        ]
    },
    'pro': {
        'max_searches': 15,
        'interval': 600,
        'features': [
            'basic_search',
            'advanced_filtering',
            'push_notifications',
            'price_analytics',
            'unlimited_favorites',
            'car_notes',
            'priority_support'
        ]
    },
    'pro_yearly': {
        'max_searches': 15,
        'interval': 600,
        'features': [
            'basic_search',
            'advanced_filtering',
            'push_notifications',
            'price_analytics',
            'unlimited_favorites',
            'car_notes',
            'priority_support'
        ]
    },
    'premium': {
        'max_searches': 25,
        'interval': 300,
        'features': [
            'basic_search',
            'advanced_filtering',
            'push_notifications',
            'price_analytics',
            'unlimited_favorites',
            'car_notes',
            'map_view',
            'ai_insights',
            'export_data',
            'social_features',
            'instant_alerts',
            'priority_support'
        ]
    },
    'premium_yearly': {
        'max_searches': 25,
        'interval': 300,
        'features': [
            'basic_search',
            'advanced_filtering',
            'push_notifications',
            'price_analytics',
            'unlimited_favorites',
            'car_notes',
            'map_view',
            'ai_insights',
            'export_data',
            'social_features',
            'instant_alerts',
            'priority_support'
        ]
    }
}

def init_db():
    """Initialize SQLite database with enhanced features"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Existing tables (users, car_searches, car_listings, notifications)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            subscription_tier TEXT DEFAULT 'free',
            subscription_expires TIMESTAMP,
            trial_ends TIMESTAMP,
            is_trial BOOLEAN DEFAULT FALSE,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            stripe_payment_method_id TEXT,
            cancel_at_period_end BOOLEAN DEFAULT FALSE,
            gifted_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
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
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
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
    
    # NEW ENHANCED TABLES
    
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
    
    # Car notes and status tracking
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
    
    # Search suggestions and auto-complete data
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
    
    # Deal quality scores
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
    
    # Notifications table
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
     # Add deal_score column to existing car_listings table
    try:
        cursor.execute("ALTER TABLE car_listings ADD COLUMN deal_score REAL")
        print("✅ Added deal_score column to car_listings table")
    except sqlite3.OperationalError:
        # Column already exists, that's fine
        pass
    conn.commit()
    conn.close()

# Enhanced Pydantic Models
class UserRegister(BaseModel):
    email: str
    password: str

class TrialSignup(BaseModel):
    email: str
    password: str
    payment_method_id: str

class UserLogin(BaseModel):
    email: str
    password: str

class CarSearchCreate(BaseModel):
    make: Optional[str] = None
    model: Optional[str] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    mileage_max: Optional[int] = None
    location: Optional[str] = None

class CarSearchUpdate(BaseModel):
    make: Optional[str] = None
    model: Optional[str] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    mileage_max: Optional[int] = None
    location: Optional[str] = None

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
    is_active: bool
    created_at: str

class CarListingResponse(BaseModel):
    id: int
    title: str
    price: str
    year: Optional[str]
    mileage: Optional[str]
    url: Optional[str]
    found_at: str

class SubscriptionResponse(BaseModel):
    tier: str
    max_searches: int
    current_searches: int
    interval_minutes: int
    features: List[str]
    price: str
    trial_ends: Optional[str] = None
    gifted_by: Optional[str] = None
    cancel_at_period_end: Optional[bool] = None
    next_billing_date: Optional[str] = None

class SubscriptionManagement(BaseModel):
    action: str  # 'cancel', 'reactivate', 'change_plan'
    new_tier: Optional[str] = None

class GiftSubscription(BaseModel):
    recipient_email: str
    tier: str
    duration_months: int
    message: Optional[str] = None

# Helper functions
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

def create_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload["user_id"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def verify_admin(user_id: int = Depends(verify_token)):
    """Verify user is admin"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if not user or user[0] not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id

def get_user_subscription(user_id: int):
    """Get user's current subscription tier and limits"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT subscription_tier FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return 'free'
    
    tier = result[0]
    
    # Map yearly tiers to their base tier for limits
    if tier == 'pro_yearly':
        return 'pro'
    elif tier == 'premium_yearly':
        return 'premium'
    
    return tier

def check_feature_access(user_id: int, feature: str) -> bool:
    """Check if user has access to a specific feature"""
    tier = get_user_subscription(user_id)
    base_tier = tier
    
    if tier == 'pro_yearly':
        base_tier = 'pro'
    elif tier == 'premium_yearly':
        base_tier = 'premium'
    
    return feature in SUBSCRIPTION_LIMITS.get(base_tier, {}).get('features', [])

def get_tier_from_price_id(price_id: str) -> str:
    """Map Stripe price ID to subscription tier"""
    tier_map = {
        "price_1RbtlsHH6XNAV6XKBbiwpO4K": "pro",           # Pro Monthly
        "price_1RbtnZHH6XNAV6XKoCvZdKQX": "pro_yearly",    # Pro Yearly
        "price_1Rbtp7HH6XNAV6XKQPe7ow42": "premium",       # Premium Monthly
        "price_1RbtpcHH6XNAV6XKlfmvTpke": "premium_yearly" # Premium Yearly
    }
    return tier_map.get(price_id, 'free')

def enhanced_save_car_listings(search_id: int, cars: list):
    """Enhanced car listing save with analytics, scoring, and value estimates"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Get search details for make/model info
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
        
        # Insert car listing with enhanced fields
        cursor.execute("""
            INSERT INTO car_listings 
            (search_id, title, price, year, mileage, url, fuel_type, transmission, body_style, color, deal_score)
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
        
        # Add to price history for analytics
        try:
            price_text = car['price'].replace('$', '').replace(',', '')
            price_num = int(price_text) if price_text.isdigit() else None
            
            year_text = car.get('year', '')
            year_num = int(year_text) if year_text.isdigit() else None
            
            mileage_text = car.get('mileage', '').replace(',', '').replace(' miles', '').replace('miles', '')
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

def save_new_car_listings(search_id: int, cars: list):
    """Legacy function - redirect to enhanced version"""
    enhanced_save_car_listings(search_id, cars)

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

def get_mock_cars(search_config):
    """Get mock car data with value estimates for testing"""
    make = search_config.get('make', 'Toyota')
    model = search_config.get('model', 'Camry')
    location = search_config.get('location', 'Cape Coral, FL')
    
    mock_cars = [
        {
            "id": f"mock_{int(time.time())}_{random.randint(1000, 9999)}",
            "title": f"2021 {make} {model} LE - Excellent Condition",
            "price": "$19,500",
            "year": "2021",
            "make": make,
            "model": model,
            "mileage": "25,000 miles",
            "url": f"https://facebook.com/marketplace/item/mock1",
            "image_url": "https://images.unsplash.com/photo-1550355291-bbee04a92027?w=400",
            "location": location,
            "source": "mock_data",
            "fuel_type": "Gasoline",
            "transmission": "Automatic",
            "scraped_at": datetime.now().isoformat()
        },
        {
            "id": f"mock_{int(time.time())}_{random.randint(1000, 9999)}",
            "title": f"2019 {make} {model} XLE - Low Miles",
            "price": "$17,900",
            "year": "2019",
            "make": make,
            "model": model,
            "mileage": "38,000 miles",
            "url": f"https://facebook.com/marketplace/item/mock2",
            "image_url": "https://images.unsplash.com/photo-1549399542-7e3f8b79c341?w=400",
            "location": location,
            "source": "mock_data",
            "fuel_type": "Gasoline",
            "transmission": "Automatic",
            "scraped_at": datetime.now().isoformat()
        },
        {
            "id": f"mock_{int(time.time())}_{random.randint(1000, 9999)}",
            "title": f"2020 {make} {model} SE - One Owner",
            "price": "$16,500",  # Priced below market for a "hot deal"
            "year": "2020",
            "make": make,
            "model": model,
            "mileage": "42,000 miles",
            "url": f"https://facebook.com/marketplace/item/mock3",
            "image_url": "https://images.unsplash.com/photo-1503376780353-7e6692767b70?w=400",
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
    
    # Enhance each car with value estimates
    enhanced_cars = []
    for car in mock_cars:
        enhanced_car = enhance_car_listing_with_values(car, value_estimator)
        enhanced_cars.append(enhanced_car)
    
    return enhanced_cars

def _get_market_advice(make: str, model: str, price_data: list) -> str:
    """Generate market advice based on data"""
    if not price_data:
        return "Limited market data available for this vehicle."
    
    # Simple trend analysis
    if len(price_data) >= 2:
        recent_avg = price_data[0][1]
        older_avg = price_data[1][1]
        
        if recent_avg > older_avg * 1.05:
            return "Prices are trending up. This model is holding value well."
        elif recent_avg < older_avg * 0.95:
            return "Prices are trending down. Good time to buy, but expect continued depreciation."
        else:
            return "Prices are stable. Market is balanced for this model."
    
    return "Monitor market trends before making a decision."

# Background monitoring with enhanced features
def run_continuous_monitoring():
    """Run enhanced car monitoring with subscription tiers"""
    global car_monitor
    
    # Initialize appropriate monitor
    if car_monitor is None:
        if ENHANCED_SCRAPER_AVAILABLE:
            car_monitor = EnhancedCarSearchMonitor(use_selenium=USE_SELENIUM, use_mock_data=USE_MOCK_DATA)
        else:
            car_monitor = CarSearchMonitor()
    
    print("🚀 Starting Enhanced Flippit monitoring!")
    print(f"📊 Mock data: {'Enabled' if USE_MOCK_DATA else 'Disabled'}")
    print(f"🌐 Selenium: {'Enabled' if USE_SELENIUM and ENHANCED_SCRAPER_AVAILABLE else 'Disabled'}")
    
    while True:
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            
            for tier, limits in SUBSCRIPTION_LIMITS.items():
                interval = limits['interval']
                
                tier_conditions = [tier]
                if tier == 'pro':
                    tier_conditions.append('pro_yearly')
                elif tier == 'premium':
                    tier_conditions.append('premium_yearly')
                
                placeholders = ','.join(['?' for _ in tier_conditions])
                
                cursor.execute(f"""
                    SELECT cs.id, cs.make, cs.model, cs.year_min, cs.year_max, 
                           cs.price_min, cs.price_max, cs.mileage_max, cs.location,
                           u.subscription_tier, u.email, u.id
                    FROM car_searches cs
                    JOIN users u ON cs.user_id = u.id 
                    WHERE cs.is_active = TRUE AND u.subscription_tier IN ({placeholders})
                """, tier_conditions)
                
                tier_searches = cursor.fetchall()
                
                if tier_searches:
                    print(f"🔄 Processing {len(tier_searches)} {tier.upper()} searches")
                    
                    for search_row in tier_searches:
                        search_id = search_row[0]
                        user_id = search_row[11]
                        
                        search_config = {
                            'make': search_row[1],
                            'model': search_row[2],
                            'year_min': search_row[3],
                            'year_max': search_row[4],
                            'price_min': search_row[5],
                            'price_max': search_row[6],
                            'mileage_max': search_row[7],
                            'location': search_row[8] or 'Cape Coral, FL',
                        }
                        
                        try:
                            new_cars = car_monitor.monitor_car_search(search_config)
                            
                            # If no real results and mock data is enabled, use mock data
                            if not new_cars and USE_MOCK_DATA:
                                print("📊 No real results, using mock data for testing")
                                new_cars = get_mock_cars(search_config)
                            
                            if new_cars:
                                enhanced_save_car_listings(search_id, new_cars)
                                
                                search_name = f"{search_config.get('make', '')} {search_config.get('model', '')}".strip()
                                print(f"🚗 Found {len(new_cars)} new {search_name} cars!")
                                
                                # Log the first car for debugging
                                if new_cars:
                                    first_car = new_cars[0]
                                    print(f"   Example: {first_car['title']} - {first_car['price']}")
                                    if first_car.get('deal_score'):
                                        print(f"   Deal Score: {first_car['deal_score']['rating']}")
                        
                        except Exception as e:
                            print(f"❌ Error monitoring search {search_id}: {e}")
                        
                        time.sleep(3)
                
                time.sleep(5)
            
            conn.close()
            
            update_search_suggestions()
            
            min_interval = min(limits['interval'] for limits in SUBSCRIPTION_LIMITS.values())
            print(f"💤 Next monitoring cycle in {min_interval//60} minutes...")
            time.sleep(min_interval)
            
        except Exception as e:
            print(f"❌ Error in monitoring: {e}")
            time.sleep(60)

# API Routes - Starting with existing ones, then enhanced

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
        "version": "3.1.0",
        "features": "KBB-style values, AI-powered deal scoring, push notifications, advanced analytics",
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "service": "Enhanced Flippit Car Monitor",
        "version": "3.1.0"
    }

@app.get("/pricing")
async def get_pricing():
    """Get subscription pricing information"""
    return {
        "tiers": {
            "free": {
                "name": "Free",
                "price": "$0/month",
                "searches": 3,
                "refresh_minutes": 25,
                "features": ["Basic search", "Basic filtering", "Basic notifications", "Value estimates"]
            },
            "pro": {
                "name": "Pro",
                "monthly_price": "$15/month",
                "yearly_price": "$153/year (15% off)",
                "yearly_savings": "$27/year",
                "searches": 15,
                "refresh_minutes": 10,
                "features": [
                    "Advanced filtering", "Push notifications", "Price analytics",
                    "Unlimited favorites", "Car notes", "Priority support", "Hot deal alerts"
                ]
            },
            "premium": {
                "name": "Premium",
                "monthly_price": "$50/month",
                "yearly_price": "$480/year (20% off)",
                "yearly_savings": "$120/year",
                "searches": 25,
                "refresh_minutes": 5,
                "features": [
                    "All Pro features", "Map view", "AI insights", "Export data",
                    "Social features", "Instant alerts", "Premium support", "Market analytics"
                ]
            }
        },
        "trial": {
            "duration": "7 days",
            "tier": "pro",
            "requires_payment": True,
            "auto_charges": True
        }
    }

@app.post("/register")
async def register(user: UserRegister):
    """Free registration - no trial, just basic free account"""
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
            "message": "Welcome to Enhanced Flippit! You have 3 free searches with KBB-style value estimates. Upgrade to Pro for hot deal alerts!"
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
        SELECT id, password_hash, subscription_tier, is_trial, trial_ends, 
               cancel_at_period_end, stripe_subscription_id 
        FROM users WHERE email = ?
    """, (user.email,))
    db_user = cursor.fetchone()
    
    if not db_user or not verify_password(user.password, db_user[1]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    user_id, _, current_tier, is_trial, trial_ends, cancel_at_period_end, stripe_sub_id = db_user
    
    # Check if trial has expired
    if is_trial and trial_ends:
        trial_end_dt = datetime.fromisoformat(trial_ends.replace('Z', '+00:00'))
        if datetime.utcnow() > trial_end_dt:
            # Trial expired - downgrade to free
            cursor.execute("""
                UPDATE users SET subscription_tier = 'free', is_trial = FALSE,
                               trial_ends = NULL 
                WHERE id = ?
            """, (user_id,))
            current_tier = 'free'
            is_trial = False
            conn.commit()
    
    token = create_token(user_id)
    conn.close()
    
    response = {
        "token": token,
        "user_id": user_id,
        "subscription_tier": current_tier
    }
    
    if is_trial and trial_ends:
        response["is_trial"] = True
        response["trial_ends"] = trial_ends
    
    if cancel_at_period_end:
        response["cancel_at_period_end"] = True
    
    return response

@app.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(user_id: int = Depends(verify_token)):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Get user subscription with trial info
    cursor.execute("""
        SELECT subscription_tier, is_trial, trial_ends, gifted_by 
        FROM users WHERE id = ?
    """, (user_id,))
    result = cursor.fetchone()
    
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    
    tier, is_trial, trial_ends, gifted_by = result
    
    # Check if trial expired
    if is_trial and trial_ends:
        trial_end_dt = datetime.fromisoformat(trial_ends.replace('Z', '+00:00'))
        if datetime.utcnow() > trial_end_dt:
            cursor.execute("""
                UPDATE users SET subscription_tier = 'free', is_trial = FALSE 
                WHERE id = ?
            """, (user_id,))
            conn.commit()
            tier = 'free'
            is_trial = False
    
    # Map yearly tiers to base tier for limit calculations
    base_tier = tier
    if tier == 'pro_yearly':
        base_tier = 'pro'
    elif tier == 'premium_yearly':
        base_tier = 'premium'
    
    limits = SUBSCRIPTION_LIMITS[base_tier]
    
    # Count current searches
    cursor.execute("SELECT COUNT(*) FROM car_searches WHERE user_id = ? AND is_active = TRUE", (user_id,))
    current_searches = cursor.fetchone()[0]
    
    conn.close()
    
    pricing = {
        "free": "$0/month",
        "pro": "$15/month",
        "pro_yearly": "$153/year (15% off)",
        "premium": "$50/month",
        "premium_yearly": "$480/year (20% off)"
    }
    
    response = SubscriptionResponse(
        tier=tier,
        max_searches=limits['max_searches'],
        current_searches=current_searches,
        interval_minutes=limits['interval'] // 60,
        features=limits['features'],
        price=pricing[tier]
    )
    
    # Add trial/gift info to response
    if is_trial:
        response.trial_ends = trial_ends
    if gifted_by:
        response.gifted_by = gifted_by
    
    return response

@app.post("/car-searches", response_model=CarSearchResponse)
async def create_car_search(search: CarSearchCreate, user_id: int = Depends(verify_token)):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Get user's subscription tier
    cursor.execute("SELECT subscription_tier FROM users WHERE id = ?", (user_id,))
    user_result = cursor.fetchone()
    if not user_result:
        raise HTTPException(status_code=404, detail="User not found")
    
    subscription_tier = user_result[0]
    
    # Map yearly tiers to base tier for limit checks
    base_tier = subscription_tier
    if subscription_tier == 'pro_yearly':
        base_tier = 'pro'
    elif subscription_tier == 'premium_yearly':
        base_tier = 'premium'
    
    max_searches = SUBSCRIPTION_LIMITS[base_tier]['max_searches']
    
    # Check current search count
    cursor.execute("SELECT COUNT(*) FROM car_searches WHERE user_id = ? AND is_active = TRUE", (user_id,))
    current_count = cursor.fetchone()[0]
    
    if current_count >= max_searches:
        tier_display = {
            "free": "Free (3 searches)",
            "pro": "Pro (15 searches)",
            "pro_yearly": "Pro Annual (15 searches)",
            "premium": "Premium (25 searches)",
            "premium_yearly": "Premium Annual (25 searches)"
        }
        raise HTTPException(
            status_code=403,
            detail=f"Search limit reached! {tier_display[subscription_tier]} allows {max_searches} searches. Upgrade for more searches and advanced features!"
        )
    
    # Create the search
    cursor.execute(
        """INSERT INTO car_searches 
           (user_id, make, model, year_min, year_max, price_min, price_max, mileage_max, location) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, search.make, search.model, search.year_min, search.year_max,
         search.price_min, search.price_max, search.mileage_max, search.location)
    )
    
    search_id = cursor.lastrowid
    conn.commit()
    
    # Get the created search
    cursor.execute("SELECT * FROM car_searches WHERE id = ?", (search_id,))
    row = cursor.fetchone()
    conn.close()
    
    # Update search suggestions
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
        is_active=row[10],
        created_at=row[11]
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
            is_active=row[10],
            created_at=row[11]
        ) for row in rows
    ]

@app.put("/car-searches/{search_id}")
async def update_car_search(search_id: int, search: CarSearchUpdate, user_id: int = Depends(verify_token)):
    """Update existing car search - EDIT FUNCTIONALITY"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Verify ownership
    cursor.execute("SELECT user_id FROM car_searches WHERE id = ?", (search_id,))
    search_owner = cursor.fetchone()
    
    if not search_owner or search_owner[0] != user_id:
        raise HTTPException(status_code=404, detail="Search not found")
    
    # Build update query dynamically
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

@app.get("/car-searches/{search_id}/listings", response_model=List[CarListingResponse])
async def get_car_listings(search_id: int, user_id: int = Depends(verify_token)):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Verify ownership
    cursor.execute("SELECT user_id FROM car_searches WHERE id = ?", (search_id,))
    search = cursor.fetchone()
    
    if not search or search[0] != user_id:
        raise HTTPException(status_code=404, detail="Search not found")
    
    cursor.execute(
        "SELECT * FROM car_listings WHERE search_id = ? ORDER BY found_at DESC LIMIT 50",
        (search_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    return [
        CarListingResponse(
            id=row[0],
            title=row[2],
            price=row[3],
            year=row[4],
            mileage=row[5],
            url=row[6],
            found_at=row[7]
        ) for row in rows
    ]

@app.delete("/car-searches/{search_id}")
async def delete_car_search(search_id: int, user_id: int = Depends(verify_token)):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Verify ownership
    cursor.execute("SELECT user_id FROM car_searches WHERE id = ?", (search_id,))
    search = cursor.fetchone()
    
    if not search or search[0] != user_id:
        raise HTTPException(status_code=404, detail="Search not found")
    
    cursor.execute("DELETE FROM car_searches WHERE id = ?", (search_id,))
    conn.commit()
    conn.close()
    
    return {"message": "Car search deleted successfully"}

@app.post("/favorites/{listing_id}")
async def add_favorite(listing_id: int, user_id: int = Depends(verify_token)):
    """Add car to favorites"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO favorites (user_id, listing_id)
            VALUES (?, ?)
        """, (user_id, listing_id))
        conn.commit()
        return {"message": "Added to favorites"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Already in favorites")
    finally:
        conn.close()

@app.delete("/favorites/{listing_id}")
async def remove_favorite(listing_id: int, user_id: int = Depends(verify_token)):
    """Remove car from favorites"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM favorites 
        WHERE user_id = ? AND listing_id = ?
    """, (user_id, listing_id))
    
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Not in favorites")
    
    conn.commit()
    conn.close()
    return {"message": "Removed from favorites"}

@app.get("/favorites")
async def get_favorites(user_id: int = Depends(verify_token)):
    """Get user's favorite cars"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT cl.*
        FROM car_listings cl
        JOIN favorites f ON cl.id = f.listing_id
        WHERE f.user_id = ?
        ORDER BY f.created_at DESC
    """, (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    favorites = []
    for row in rows:
        favorite = {
            "id": row[0],
            "title": row[2],
            "price": row[3],
            "year": row[4],
            "mileage": row[5],
            "url": row[6],
            "found_at": row[7],
            "is_favorite": True
        }
        favorites.append(favorite)
    
    return {"favorites": favorites}

# NEW ENDPOINTS FOR KBB VALUES AND ENHANCED FEATURES

@app.get("/all-deals")
async def get_all_deals(user_id: int = Depends(verify_token)):
    """Get all found cars from all user's searches with value analysis"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT cl.*, cs.make, cs.model, ds.quality_indicators
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
            "fuel_type": row[9],
            "transmission": row[10],
            "body_style": row[11],
            "color": row[12],
            "search_make": row[19],
            "search_model": row[20],
            "is_mock": "mock_data" in (row[6] or "")
        }
        
        # Add value analysis if available
        if row[21]:  # quality_indicators JSON
            try:
                analysis_data = json.loads(row[21])
                deal['value_estimate'] = analysis_data.get('value_estimate')
                deal['deal_score'] = analysis_data.get('deal_score')
                deal['has_analysis'] = True
            except:
                deal['has_analysis'] = False
        else:
            deal['has_analysis'] = False
        
        deals.append(deal)
    
    return {"deals": deals, "total": len(deals)}

@app.get("/test-search/{search_id}")
async def test_car_search(search_id: int, user_id: int = Depends(verify_token)):
    """Manually trigger a search test with mock data"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Get search details
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
    }
    
    # Force mock data for testing
    mock_cars = get_mock_cars(search_config)
    
    # Save mock cars
    enhanced_save_car_listings(search_id, mock_cars)
    
    conn.close()
    
    return {
        "message": f"Added {len(mock_cars)} test cars with value analysis",
        "cars": mock_cars[:1]  # Return first car as example
    }

@app.get("/value-estimate")
async def get_value_estimate(
    make: str,
    model: str,
    year: int,
    mileage: Optional[int] = None,
    price: Optional[int] = None,
    condition: str = "good",
    user_id: int = Depends(verify_token)
):
    """Get KBB-style value estimate for a car"""
    try:
        estimate = value_estimator.estimate_value(
            make=make,
            model=model,
            year=year,
            mileage=mileage,
            condition=condition
        )
        
        # Calculate deal score if price provided
        deal_score = None
        if price:
            deal_score = value_estimator.calculate_deal_score(price, estimate)
        
        return {
            "value_estimate": estimate,
            "deal_score": deal_score,
            "disclaimer": estimate['disclaimer']
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/market-insights/{make}/{model}")
async def get_market_insights(
    make: str,
    model: str,
    user_id: int = Depends(verify_token)
):
    """Get market insights for a specific make/model"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Get price history data
    cursor.execute("""
        SELECT year, AVG(price) as avg_price, COUNT(*) as count,
               MIN(price) as min_price, MAX(price) as max_price
        FROM price_history
        WHERE make = ? AND model = ?
        GROUP BY year
        ORDER BY year DESC
        LIMIT 10
    """, (make, model))
    
    price_data = cursor.fetchall()
    
    # Get recent listings
    cursor.execute("""
        SELECT COUNT(*) as total_listings,
               AVG(CAST(REPLACE(REPLACE(price, '$', ''), ',', '') AS INTEGER)) as avg_listing_price
        FROM car_listings cl
        JOIN car_searches cs ON cl.search_id = cs.id
        WHERE cs.make = ? AND cs.model = ?
        AND cl.found_at > datetime('now', '-30 days')
    """, (make, model))
    
    recent_stats = cursor.fetchone()
    conn.close()
    
    insights = {
        "make": make,
        "model": model,
        "price_trends": [
            {
                "year": row[0],
                "avg_price": row[1],
                "listing_count": row[2],
                "price_range": f"${row[3]:,} - ${row[4]:,}"
            } for row in price_data
        ],
        "recent_activity": {
            "listings_last_30_days": recent_stats[0] if recent_stats else 0,
            "avg_listing_price": f"${int(recent_stats[1]):,}" if recent_stats and recent_stats[1] else "N/A"
        },
        "market_advice": _get_market_advice(make, model, price_data)
    }
    
    return insights

@app.get("/hot-deals")
async def get_hot_deals(user_id: int = Depends(verify_token)):
    """Get only the hottest deals (score > 85)"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT cl.*, cs.make, cs.model, ds.quality_indicators
        FROM car_listings cl
        JOIN car_searches cs ON cl.search_id = cs.id
        LEFT JOIN deal_scores ds ON cl.id = ds.listing_id
        WHERE cs.user_id = ? AND cl.deal_score >= 85
        ORDER BY cl.deal_score DESC, cl.found_at DESC
        LIMIT 20
    """, (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    hot_deals = []
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
            "deal_score": row[15],
            "search_make": row[19],
            "search_model": row[20],
            "is_mock": "mock_data" in (row[6] or "")
        }
        
        if row[21]:  # quality_indicators JSON
            try:
                analysis_data = json.loads(row[21])
                deal['value_estimate'] = analysis_data.get('value_estimate')
                deal['deal_analysis'] = analysis_data.get('deal_score')
            except:
                pass
        
        hot_deals.append(deal)
    
    return {"hot_deals": hot_deals, "total": len(hot_deals)}

@app.get("/search-analytics/{search_id}")
async def get_search_analytics(search_id: int, user_id: int = Depends(verify_token)):
    """Get analytics for a specific search"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Verify ownership
    cursor.execute("SELECT * FROM car_searches WHERE id = ? AND user_id = ?", (search_id, user_id))
    search = cursor.fetchone()
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    
    # Get stats
    cursor.execute("""
        SELECT 
            COUNT(*) as total_found,
            AVG(CAST(REPLACE(REPLACE(price, '$', ''), ',', '') AS REAL)) as avg_price,
            MIN(CAST(REPLACE(REPLACE(price, '$', ''), ',', '') AS INTEGER)) as min_price,
            MAX(CAST(REPLACE(REPLACE(price, '$', ''), ',', '') AS INTEGER)) as max_price,
            AVG(deal_score) as avg_deal_score,
            SUM(CASE WHEN deal_score >= 85 THEN 1 ELSE 0 END) as hot_deals_count
        FROM car_listings
        WHERE search_id = ?
    """, (search_id,))
    
    stats = cursor.fetchone()
    conn.close()
    
    return {
        "search_id": search_id,
        "make": search[2],
        "model": search[3],
        "analytics": {
            "total_cars_found": stats[0] or 0,
            "average_price": f"${int(stats[1]):,}" if stats[1] else "N/A",
            "price_range": f"${stats[2]:,} - ${stats[3]:,}" if stats[2] and stats[3] else "N/A",
            "average_deal_score": round(stats[4], 1) if stats[4] else 0,
            "hot_deals_found": stats[5] or 0
        }
    }

@app.get("/config")
async def get_config():
    """Get current configuration"""
    return {
        "use_mock_data": USE_MOCK_DATA,
        "use_selenium": USE_SELENIUM,
        "enhanced_scraper": ENHANCED_SCRAPER_AVAILABLE,
        "version": "3.1.0",
        "features": {
            "kbb_values": True,
            "deal_scoring": True,
            "market_insights": True,
            "mock_data": USE_MOCK_DATA,
            "hot_deals": True
        }
    }

# STRIPE WEBHOOK ENDPOINTS

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        # Handle the event
        if event['type'] == 'customer.subscription.updated':
            subscription = event['data']['object']
            stripe_sub_id = subscription['id']
            status = subscription['status']
            
            # Update user subscription status
            cursor.execute("""
                UPDATE users 
                SET subscription_tier = ?, cancel_at_period_end = ?
                WHERE stripe_subscription_id = ?
            """, (
                get_tier_from_price_id(subscription['items']['data'][0]['price']['id']),
                subscription.get('cancel_at_period_end', False),
                stripe_sub_id
            ))
            
            print(f"🔄 Updated subscription {stripe_sub_id} to status: {status}")
            
        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            stripe_sub_id = subscription['id']
            
            # Downgrade to free tier
            cursor.execute("""
                UPDATE users 
                SET subscription_tier = 'free', is_trial = FALSE, 
                    trial_ends = NULL, stripe_subscription_id = NULL
                WHERE stripe_subscription_id = ?
            """, (stripe_sub_id,))
            
            print(f"❌ Subscription {stripe_sub_id} canceled - downgraded to free")
            
        elif event['type'] == 'invoice.payment_failed':
            invoice = event['data']['object']
            customer_id = invoice['customer']
            
            # Handle failed payment - could suspend service or notify user
            cursor.execute("""
                SELECT email FROM users WHERE stripe_customer_id = ?
            """, (customer_id,))
            user = cursor.fetchone()
            
            if user:
                print(f"💳 Payment failed for user: {user[0]}")
                # Could implement email notification here
                
        elif event['type'] == 'invoice.payment_succeeded':
            invoice = event['data']['object']
            subscription_id = invoice.get('subscription')
            
            if subscription_id:
                # Payment succeeded - ensure user has active subscription
                subscription = stripe.Subscription.retrieve(subscription_id)
                tier = get_tier_from_price_id(subscription['items']['data'][0]['price']['id'])
                
                cursor.execute("""
                    UPDATE users 
                    SET subscription_tier = ?, is_trial = FALSE, trial_ends = NULL
                    WHERE stripe_subscription_id = ?
                """, (tier, subscription_id))
                
                print(f"💰 Payment succeeded for subscription: {subscription_id}")
        
        conn.commit()
        
    except Exception as e:
        print(f"❌ Error processing webhook: {e}")
        conn.rollback()
    finally:
        conn.close()
    
    return {"status": "success"}

# ADMIN ENDPOINTS FOR GIFTING

@app.post("/gift-subscription")
async def gift_subscription(gift: GiftSubscription, admin_id: int = Depends(verify_admin)):
    """Gift a subscription to a user - Admin only"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        # Check if recipient exists
        cursor.execute("SELECT id FROM users WHERE email = ?", (gift.recipient_email,))
        recipient = cursor.fetchone()
        
        if not recipient:
            # Create account for recipient
            temp_password = hashlib.sha256(f"{gift.recipient_email}{datetime.now()}".encode()).hexdigest()[:12]
            cursor.execute(
                "INSERT INTO users (email, password_hash, subscription_tier) VALUES (?, ?, ?)",
                (gift.recipient_email, hash_password(temp_password), gift.tier)
            )
            recipient_id = cursor.lastrowid
            print(f"🎁 Created new account for {gift.recipient_email}")
        else:
            recipient_id = recipient[0]
            # Update existing user
            cursor.execute(
                "UPDATE users SET subscription_tier = ?, gifted_by = ? WHERE id = ?",
                (gift.tier, ADMIN_EMAILS[0], recipient_id)
            )
        
        # Calculate expiration date
        expires = datetime.utcnow() + timedelta(days=gift.duration_months * 30)
        cursor.execute(
            "UPDATE users SET subscription_expires = ? WHERE id = ?",
            (expires, recipient_id)
        )
        
        conn.commit()
        
        return {
            "message": f"Successfully gifted {gift.tier} subscription to {gift.recipient_email}",
            "expires": expires.isoformat(),
            "created_account": not bool(recipient)
        }
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.post("/admin/bulk-gift")
async def bulk_gift_subscriptions(
    emails: List[str],
    tier: str,
    duration_months: int = 1,
    admin_id: int = Depends(verify_admin)
):
    """Bulk gift subscriptions - Admin only"""
    results = []
    
    for email in emails:
        try:
            gift = GiftSubscription(
                recipient_email=email,
                tier=tier,
                duration_months=duration_months
            )
            result = await gift_subscription(gift, admin_id)
            results.append({"email": email, "status": "success", "result": result})
        except Exception as e:
            results.append({"email": email, "status": "error", "error": str(e)})
    
    successful = len([r for r in results if r["status"] == "success"])
    return {
        "total": len(emails),
        "successful": successful,
        "failed": len(emails) - successful,
        "results": results
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print("🚀 Starting Enhanced Flippit API Server v3.1.0")
    print("✨ New Features: KBB-style Value Estimates, AI Deal Scoring, Market Analytics")
    uvicorn.run(app, host="0.0.0.0", port=port)
