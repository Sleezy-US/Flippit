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

# Import our car scraper
from fb_scraper import CarSearchMonitor

# Stripe configuration
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_your_stripe_key_here")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_your_webhook_secret")

app = FastAPI(title="Flippit - Enhanced Car Marketplace Monitor API", version="3.0.0")

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
    
    # Filter presets
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS filter_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            filters TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
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
    
    # Price alerts
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            listing_id INTEGER NOT NULL,
            target_price INTEGER NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

class PushNotificationToken(BaseModel):
    token: str
    platform: str

class CarNote(BaseModel):
    note: str

class FilterPreset(BaseModel):
    name: str
    filters: Dict[str, Any]

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

def calculate_deal_score(car: dict, search_id: int) -> dict:
    """Calculate AI-powered deal quality score"""
    try:
        # Extract numeric values
        price_text = car.get('price', '').replace('$', '').replace(',', '')
        price = int(price_text) if price_text.isdigit() else None
        
        year_text = car.get('year', '')
        year = int(year_text) if year_text.isdigit() else None
        
        mileage_text = car.get('mileage', '').replace(',', '').replace(' miles', '').replace('miles', '')
        mileage = int(mileage_text) if mileage_text.isdigit() else None
        
        # Base scoring factors
        score = 5.0  # Start with middle score
        indicators = {}
        
        # Age factor
        if year:
            current_year = datetime.now().year
            age = current_year - year
            if age <= 3:
                score += 2.0
                indicators['age'] = 'Very New'
            elif age <= 7:
                score += 1.0
                indicators['age'] = 'Recent'
            elif age <= 15:
                indicators['age'] = 'Moderate'
            else:
                score -= 0.5
                indicators['age'] = 'Older'
        
        # Mileage factor
        if mileage and year:
            current_year = datetime.now().year
            age = current_year - year
            expected_mileage = age * 12000  # 12k miles per year average
            
            if mileage < expected_mileage * 0.7:  # Low mileage
                score += 1.5
                indicators['mileage'] = 'Very Low'
            elif mileage < expected_mileage:
                score += 0.5
                indicators['mileage'] = 'Below Average'
            elif mileage > expected_mileage * 1.5:  # High mileage
                score -= 1.0
                indicators['mileage'] = 'High'
            else:
                indicators['mileage'] = 'Average'
        
        # Price factor (compared to user's search range)
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT price_min, price_max FROM car_searches WHERE id = ?", (search_id,))
        search_range = cursor.fetchone()
        conn.close()
        
        if search_range and search_range[1] and price:  # Has max price
            max_price = search_range[1]
            if price <= max_price * 0.8:  # 20% below max
                score += 1.0
                indicators['price'] = 'Great Value'
            elif price <= max_price * 0.9:  # 10% below max
                score += 0.5
                indicators['price'] = 'Good Value'
            elif price >= max_price * 1.1:  # 10% above max
                score -= 0.5
                indicators['price'] = 'Above Budget'
        
        # Title analysis for quality indicators
        title_lower = car.get('title', '').lower()
        
        # Positive indicators
        if any(word in title_lower for word in ['certified', 'warranty', 'carfax', 'clean title']):
            score += 0.5
            indicators['quality'] = 'Certified/Documented'
        
        if any(word in title_lower for word in ['leather', 'navigation', 'sunroof', 'premium']):
            score += 0.3
            indicators['features'] = 'Well-Equipped'
        
        # Negative indicators
        if any(word in title_lower for word in ['accident', 'damage', 'salvage', 'flood']):
            score -= 2.0
            indicators['condition'] = 'Damage History'
        
        if any(word in title_lower for word in ['repair', 'needs work', 'project']):
            score -= 1.0
            indicators['condition'] = 'Needs Repair'
        
        # Cap score between 0-10
        score = max(0, min(10, round(score, 1)))
        
        return {
            'score': score,
            'indicators': indicators
        }
        
    except Exception as e:
        print(f"Error calculating deal score: {e}")
        return {
            'score': 5.0,
            'indicators': {}
        }

def enhanced_save_car_listings(search_id: int, cars: list):
    """Enhanced car listing save with analytics and scoring"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    for car in cars:
        # Insert car listing with enhanced fields
        cursor.execute("""
            INSERT INTO car_listings 
            (search_id, title, price, year, mileage, url, fuel_type, transmission, body_style, color)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            car.get('color')
        ))
        
        listing_id = cursor.lastrowid
        
        # Add to price history for analytics
        try:
            price_text = car['price'].replace('$', '').replace(',', '')
            price_num = int(price_text) if price_text.isdigit() else None
            
            year_text = car.get('year', '')
            year_num = int(year_text) if year_text.isdigit() else None
            
            mileage_text = car.get('mileage', '').replace(',', '').replace(' miles', '').replace('miles', '')
            mileage_num = int(mileage_text) if mileage_text.isdigit() else None
            
            # Extract make/model from search
            cursor.execute("SELECT make, model, location FROM car_searches WHERE id = ?", (search_id,))
            search_info = cursor.fetchone()
            
            if search_info and price_num:
                cursor.execute("""
                    INSERT INTO price_history (make, model, year, location, price, mileage)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (search_info[0], search_info[1], year_num, search_info[2], price_num, mileage_num))
        except Exception as e:
            print(f"Error saving price history: {e}")
        
        # Calculate and save deal score
        deal_data = calculate_deal_score(car, search_id)
        
        if deal_data:
            cursor.execute("""
                UPDATE car_listings 
                SET deal_score = ?
                WHERE id = ?
            """, (deal_data['score'], listing_id))
            
            cursor.execute("""
                INSERT INTO deal_scores (listing_id, deal_score, quality_indicators)
                VALUES (?, ?, ?)
            """, (listing_id, deal_data['score'], json.dumps(deal_data['indicators'])))
    
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

def send_push_notification(user_id: int, title: str, body: str, data: dict = None):
    """Send push notification to user (placeholder for Firebase integration)"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT token, platform FROM push_tokens 
        WHERE user_id = ? AND is_active = TRUE
    """, (user_id,))
    
    tokens = cursor.fetchall()
    conn.close()
    
    if tokens:
        print(f"📱 Would send push notification to {len(tokens)} devices: {title}")
        # TODO: Implement actual Firebase push notification
        # This is where you'd integrate with Firebase Admin SDK
    
    return len(tokens)

# Background monitoring with enhanced features
def run_continuous_monitoring():
    """Run enhanced car monitoring with subscription tiers"""
    global car_monitor
    if car_monitor is None:
        car_monitor = CarSearchMonitor()
    
    print("🚀 Starting Enhanced Flippit monitoring with AI insights!")
    
    while True:
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            
            for tier, limits in SUBSCRIPTION_LIMITS.items():
                interval = limits['interval']
                
                # Get searches for this tier
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
                        user_email = search_row[10]
                        
                        search_config = {
                            'make': search_row[1],
                            'model': search_row[2],
                            'year_min': search_row[3],
                            'year_max': search_row[4],
                            'price_min': search_row[5],
                            'price_max': search_row[6],
                            'mileage_max': search_row[7],
                            'location': search_row[8],
                        }
                        
                        try:
                            new_cars = car_monitor.monitor_car_search(search_config)
                            
                            if new_cars:
                                # Save with enhanced features
                                enhanced_save_car_listings(search_id, new_cars)
                                
                                search_name = f"{search_config.get('make', '')} {search_config.get('model', '')}".strip()
                                print(f"🚗 {tier.upper()} user found {len(new_cars)} new {search_name} cars!")
                                
                                # Send notifications if user has access
                                if check_feature_access(user_id, 'push_notifications'):
                                    send_push_notification(
                                        user_id,
                                        f"🚗 {len(new_cars)} New Cars Found!",
                                        f"Found {len(new_cars)} new {search_name} listings",
                                        {"search_id": str(search_id), "type": "new_cars"}
                                    )
                        
                        except Exception as e:
                            print(f"❌ Error monitoring search {search_id}: {e}")
                        
                        time.sleep(3)
                
                time.sleep(5)
            
            conn.close()
            
            # Update search suggestions periodically
            update_search_suggestions()
            
            # Wait before next cycle
            min_interval = min(limits['interval'] for limits in SUBSCRIPTION_LIMITS.values())
            print(f"💤 Next enhanced monitoring cycle in {min_interval//60} minutes...")
            time.sleep(min_interval)
            
        except Exception as e:
            print(f"❌ Error in enhanced monitoring: {e}")
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
        "version": "3.0.0",
        "features": "AI-powered deal scoring, push notifications, advanced analytics",
        "docs": "/docs"
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
            "message": "Welcome to Enhanced Flippit! You have 3 free searches with basic features. Upgrade to Pro for push notifications and advanced analytics!"
        }
    
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Email already registered")
    finally:
        conn.close()

@app.post("/start-trial")
async def start_trial(trial_signup: TrialSignup):
    """Start 7-day Pro trial with payment method required"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        # Check if user already exists
        cursor.execute("SELECT id, stripe_customer_id FROM users WHERE email = ?", (trial_signup.email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            user_id, customer_id = existing_user
            
            # Check if they already had a trial
            cursor.execute("SELECT trial_ends FROM users WHERE id = ?", (user_id,))
            trial_check = cursor.fetchone()
            if trial_check[0]:  # Already had a trial
                raise HTTPException(status_code=400, detail="Trial already used for this email")
        else:
            # Create new user
            cursor.execute(
                "INSERT INTO users (email, password_hash, subscription_tier) VALUES (?, ?, ?)",
                (trial_signup.email, hash_password(trial_signup.password), 'free')
            )
            conn.commit()
            user_id = cursor.lastrowid
            customer_id = None
        
        # Create Stripe customer if doesn't exist
        if not customer_id:
            stripe_customer = stripe.Customer.create(
                email=trial_signup.email,
                payment_method=trial_signup.payment_method_id
            )
            customer_id = stripe_customer.id
            
            # Update user with Stripe customer ID
            cursor.execute(
                "UPDATE users SET stripe_customer_id = ? WHERE id = ?",
                (customer_id, user_id)
            )
        
        # Attach payment method to customer
        stripe.PaymentMethod.attach(
            trial_signup.payment_method_id,
            customer=customer_id
        )
        
        # Set as default payment method
        stripe.Customer.modify(
            customer_id,
            invoice_settings={'default_payment_method': trial_signup.payment_method_id}
        )
        
        # Create Stripe subscription with 7-day trial
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': 'price_1RbtlsHH6XNAV6XKBbiwpO4K'}],  # Your Pro price ID
            trial_period_days=7,
            payment_behavior='default_incomplete',
            payment_settings={'save_default_payment_method': 'on_subscription'},
            expand=['latest_invoice.payment_intent']
        )
        
        # Calculate trial end date
        trial_ends = datetime.utcnow() + timedelta(days=7)
        
        # Update user with trial info
        cursor.execute("""
            UPDATE users 
            SET subscription_tier = 'pro', is_trial = TRUE, trial_ends = ?,
                stripe_subscription_id = ?, stripe_payment_method_id = ?
            WHERE id = ?
        """, (trial_ends, subscription.id, trial_signup.payment_method_id, user_id))
        
        conn.commit()
        token = create_token(user_id)
        
        return {
            "token": token,
            "user_id": user_id,
            "subscription_tier": "pro",
            "is_trial": True,
            "trial_ends": trial_ends.isoformat(),
            "stripe_subscription_id": subscription.id,
            "message": "🎉 7-day Pro trial started! You now have access to push notifications, price analytics, advanced filtering, and 15 car searches!"
        }
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Payment error: {str(e)}")
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
            # Trial expired - subscription should have auto-converted or been canceled
            if stripe_sub_id:
                try:
                    subscription = stripe.Subscription.retrieve(stripe_sub_id)
                    if subscription.status == 'active':
                        # Trial converted to paid subscription
                        cursor.execute("""
                            UPDATE users SET is_trial = FALSE, trial_ends = NULL 
                            WHERE id = ?
                        """, (user_id,))
                        is_trial = False
                    else:
                        # Subscription failed/canceled, downgrade to free
                        cursor.execute("""
                            UPDATE users SET subscription_tier = 'free', is_trial = FALSE,
                                           trial_ends = NULL, stripe_subscription_id = NULL
                            WHERE id = ?
                        """, (user_id,))
                        current_tier = 'free'
                        is_trial = False
                except stripe.error.StripeError:
                    # Error checking Stripe, assume downgrade to free
                    cursor.execute("""
                        UPDATE users SET subscription_tier = 'free', is_trial = FALSE,
                                       trial_ends = NULL 
                        WHERE id = ?
                    """, (user_id,))
                    current_tier = 'free'
                    is_trial = False
            else:
                # No Stripe subscription, downgrade to free
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

@app.post("/manage-subscription")
async def manage_subscription(management: SubscriptionManagement, user_id: int = Depends(verify_token)):
    """Cancel, reactivate, or change subscription plan"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT stripe_subscription_id, subscription_tier, cancel_at_period_end 
        FROM users WHERE id = ?
    """, (user_id,))
    result = cursor.fetchone()
    
    if not result or not result[0]:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    stripe_sub_id, current_tier, cancel_at_period_end = result
    
    try:
        if management.action == "cancel":
            # Cancel at end of billing period
            stripe.Subscription.modify(
                stripe_sub_id,
                cancel_at_period_end=True
            )
            
            cursor.execute("""
                UPDATE users SET cancel_at_period_end = TRUE WHERE id = ?
            """, (user_id,))
            
            message = "Subscription will cancel at the end of your current billing period"
            
        elif management.action == "reactivate":
            # Reactivate canceled subscription
            stripe.Subscription.modify(
                stripe_sub_id,
                cancel_at_period_end=False
            )
            
            cursor.execute("""
                UPDATE users SET cancel_at_period_end = FALSE WHERE id = ?
            """, (user_id,))
            
            message = "Subscription reactivated - you will continue to be billed"
            
        elif management.action == "change_plan":
            if not management.new_tier:
                raise HTTPException(status_code=400, detail="new_tier required for plan change")
            
            # Get new Stripe price ID based on tier
            price_map = {
                "pro": "price_1RbtlsHH6XNAV6XKBbiwpO4K",
                "pro_yearly": "price_1RbtnZHH6XNAV6XKoCvZdKQX", 
                "premium": "price_1Rbtp7HH6XNAV6XKQPe7ow42",
                "premium_yearly": "price_1RbtpcHH6XNAV6XKlfmvTpke"
            }
            
            if management.new_tier not in price_map:
                raise HTTPException(status_code=400, detail="Invalid subscription tier")
            
            # Update Stripe subscription
            subscription = stripe.Subscription.retrieve(stripe_sub_id)
            stripe.Subscription.modify(
                stripe_sub_id,
                items=[{
                    'id': subscription['items']['data'][0]['id'],
                    'price': price_map[management.new_tier]
                }],
                proration_behavior='immediate_with_unused_time'
            )
            
            cursor.execute("""
                UPDATE users SET subscription_tier = ? WHERE id = ?
            """, (management.new_tier, user_id))
            
            message = f"Subscription changed to {management.new_tier}"
            
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
        
        conn.commit()
        conn.close()
        
        return {"message": message, "action": management.action}
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Stripe error: {str(e)}")

# NEW ENHANCED ENDPOINTS

@app.post("/push-token")
async def register_push_token(token_data: PushNotificationToken, user_id: int = Depends(verify_token)):
    """Register push notification token - Pro feature"""
    if not check_feature_access(user_id, 'push_notifications'):
        raise HTTPException(
            status_code=403, 
            detail="Push notifications require Pro subscription. Upgrade to get instant alerts!"
        )
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Deactivate old tokens for this user/platform
    cursor.execute("""
        UPDATE push_tokens SET is_active = FALSE 
        WHERE user_id = ? AND platform = ?
    """, (user_id, token_data.platform))
    
    # Insert new token
    cursor.execute("""
        INSERT OR REPLACE INTO push_tokens (user_id, token, platform, is_active)
        VALUES (?, ?, ?, TRUE)
    """, (user_id, token_data.token, token_data.platform))
    
    conn.commit()
    conn.close()
    
    return {"message": "Push token registered successfully"}

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

@app.get("/car-listings")
async def get_all_car_listings(
    user_id: int = Depends(verify_token),
    sort_by: str = "found_at",
    order: str = "desc",
    make: Optional[str] = None,
    model: Optional[str] = None,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    max_distance: Optional[float] = None,
    limit: int = 50
):
    """Get all car listings with advanced filtering and sorting"""
    # Check if user has advanced filtering access
    if sort_by != "found_at" or make or model or min_year or max_year or min_price or max_price:
        if not check_feature_access(user_id, 'advanced_filtering'):
            raise HTTPException(
                status_code=403,
                detail="Advanced filtering requires Pro subscription. Upgrade for powerful search tools!"
            )
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Base query
    query = """
        SELECT cl.*, ds.deal_score, ds.quality_indicators,
               CASE WHEN f.id IS NOT NULL THEN 1 ELSE 0 END as is_favorite
        FROM car_listings cl
        JOIN car_searches cs ON cl.search_id = cs.id
        LEFT JOIN deal_scores ds ON cl.id = ds.listing_id
        LEFT JOIN favorites f ON cl.id = f.listing_id AND f.user_id = ?
        WHERE cs.user_id = ?
    """
    
    params = [user_id, user_id]
    
    # Add filters
    if make:
        query += " AND (cl.title LIKE ? OR cs.make LIKE ?)"
        params.extend([f"%{make}%", f"%{make}%"])
    
    if model:
        query += " AND (cl.title LIKE ? OR cs.model LIKE ?)"
        params.extend([f"%{model}%", f"%{model}%"])
    
    if min_year:
        query += " AND CAST(cl.year as INTEGER) >= ?"
        params.append(min_year)
    
    if max_year:
        query += " AND CAST(cl.year as INTEGER) <= ?"
        params.append(max_year)
    
    if min_price:
        query += " AND CAST(REPLACE(REPLACE(cl.price, ', ''), ',', '') as INTEGER) >= ?"
        params.append(min_price)
    
    if max_price:
        query += " AND CAST(REPLACE(REPLACE(cl.price, ', ''), ',', '') as INTEGER) <= ?"
        params.append(max_price)
    
    if max_distance:
        query += " AND cl.distance_miles <= ?"
        params.append(max_distance)
    
    # Add sorting
    valid_sort_fields = ["found_at", "price", "year", "mileage", "distance_miles", "deal_score"]
    if sort_by in valid_sort_fields:
        order_dir = "DESC" if order.lower() == "desc" else "ASC"
        
        if sort_by == "price":
            query += f" ORDER BY CAST(REPLACE(REPLACE(cl.price, ', ''), ',', '') as INTEGER) {order_dir}"
        elif sort_by == "year":
            query += f" ORDER BY CAST(cl.year as INTEGER) {order_dir}"
        elif sort_by == "mileage":
            query += f" ORDER BY CAST(REPLACE(REPLACE(cl.mileage, ',', ''), ' miles', '') as INTEGER) {order_dir}"
        else:
            query += f" ORDER BY cl.{sort_by} {order_dir}"
    else:
        query += " ORDER BY cl.found_at DESC"
    
    query += f" LIMIT {limit}"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    # Convert to enhanced response format
    listings = []
    for row in rows:
        quality_indicators = {}
        if len(row) > 17 and row[17]:  # quality_indicators column
            try:
                quality_indicators = json.loads(row[17])
            except:
                quality_indicators = {}
        
        listing = {
            "id": row[0],
            "title": row[2],
            "price": row[3],
            "year": row[4],
            "mileage": row[5],
            "url": row[6],
            "found_at": row[7],
            "fuel_type": row[9] if len(row) > 9 else None,
            "transmission": row[10] if len(row) > 10 else None,
            "body_style": row[11] if len(row) > 11 else None,
            "color": row[12] if len(row) > 12 else None,
            "distance_miles": row[15] if len(row) > 15 else None,
            "deal_score": row[16] if len(row) > 16 else None,
            "quality_indicators": quality_indicators,
            "is_favorite": bool(row[18]) if len(row) > 18 else False
        }
        listings.append(listing)
    
    return {"listings": listings, "total": len(listings)}

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
        SELECT cl.*, ds.deal_score, ds.quality_indicators
        FROM car_listings cl
        JOIN favorites f ON cl.id = f.listing_id
        LEFT JOIN deal_scores ds ON cl.id = ds.listing_id
        WHERE f.user_id = ?
        ORDER BY f.created_at DESC
    """, (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    favorites = []
    for row in rows:
        quality_indicators = {}
        if len(row) > 17 and row[17]:
            try:
                quality_indicators = json.loads(row[17])
            except:
                quality_indicators = {}
        
        favorite = {
            "id": row[0],
            "title": row[2],
            "price": row[3],
            "year": row[4],
            "mileage": row[5],
            "url": row[6],
            "found_at": row[7],
            "deal_score": row[16] if len(row) > 16 else None,
            "quality_indicators": quality_indicators,
            "is_favorite": True
        }
        favorites.append(favorite)
    
    return {"favorites": favorites}

@app.post("/car-notes/{listing_id}")
async def add_car_note(listing_id: int, note_data: CarNote, user_id: int = Depends(verify_token)):
    """Add note to a car listing - Pro feature"""
    if not check_feature_access(user_id, 'car_notes'):
        raise HTTPException(
            status_code=403,
            detail="Car notes require Pro subscription. Upgrade to organize your car search!"
        )
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO car_notes (user_id, listing_id, note, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (user_id, listing_id, note_data.note))
    
    conn.commit()
    conn.close()
    return {"message": "Note added successfully"}

@app.get("/car-notes/{listing_id}")
async def get_car_note(listing_id: int, user_id: int = Depends(verify_token)):
    """Get note for a car listing"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT note, status, updated_at 
        FROM car_notes 
        WHERE user_id = ? AND listing_id = ?
    """, (user_id, listing_id))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            "note": result[0],
            "status": result[1],
            "updated_at": result[2]
        }
    else:
        return {"note": None, "status": None, "updated_at": None}

@app.get("/search-suggestions")
async def get_search_suggestions(query: str = ""):
    """Get search suggestions for make/model autocomplete"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    if query:
        cursor.execute("""
            SELECT make, model, search_count 
            FROM search_suggestions 
            WHERE make LIKE ? OR model LIKE ?
            ORDER BY search_count DESC 
            LIMIT 10
        """, (f"%{query}%", f"%{query}%"))
    else:
        cursor.execute("""
            SELECT make, model, search_count 
            FROM search_suggestions 
            ORDER BY search_count DESC 
            LIMIT 20
        """)
    
    rows = cursor.fetchall()
    conn.close()
    
    suggestions = []
    for row in rows:
        if row[0]:  # make
            suggestions.append({"type": "make", "value": row[0], "popularity": row[2]})
        if row[1]:  # model
            suggestions.append({"type": "model", "value": row[1], "popularity": row[2]})
    
    return {"suggestions": suggestions}

@app.get("/price-analytics")
async def get_price_analytics(
    make: str,
    model: Optional[str] = None,
    year: Optional[int] = None,
    user_id: int = Depends(verify_token)
):
    """Get price analytics for a specific make/model - Pro feature"""
    if not check_feature_access(user_id, 'price_analytics'):
        raise HTTPException(
            status_code=403,
            detail="Price analytics require Pro subscription. Upgrade for market insights!"
        )
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Build query for historical data
    query = """
        SELECT price, mileage, recorded_at 
        FROM price_history 
        WHERE make LIKE ?
    """
    params = [f"%{make}%"]
    
    if model:
        query += " AND model LIKE ?"
        params.append(f"%{model}%")
    
    if year:
        query += " AND year = ?"
        params.append(year)
    
    query += " ORDER BY recorded_at DESC LIMIT 100"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return {
            "message": "Not enough data for analysis",
            "average_price": None,
            "price_trend": None,
            "market_analysis": None
        }
    
    # Calculate analytics
    prices = [row[0] for row in rows if row[0]]
    
    if not prices:
        return {
            "message": "No price data available",
            "average_price": None
        }
    
    analytics = {
        "average_price": round(statistics.mean(prices)),
        "median_price": round(statistics.median(prices)),
        "price_range": {
            "min": min(prices),
            "max": max(prices)
        },
        "total_listings": len(rows),
        "price_distribution": {
            "below_20k": len([p for p in prices if p < 20000]),
            "20k_to_35k": len([p for p in prices if 20000 <= p < 35000]),
            "35k_to_50k": len([p for p in prices if 35000 <= p < 50000]),
            "above_50k": len([p for p in prices if p >= 50000])
        }
    }
    
    return analytics

@app.get("/map-data")
async def get_map_data(
    user_id: int = Depends(verify_token),
    search_id: Optional[int] = None
):
    """Get car listings with location data for map view - Premium feature"""
    if not check_feature_access(user_id, 'map_view'):
        raise HTTPException(
            status_code=403,
            detail="Map view requires Premium subscription. Upgrade for location features!"
        )
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    query = """
        SELECT cl.id, cl.title, cl.price, cl.location_lat, cl.location_lng, 
               cl.url, ds.deal_score
        FROM car_listings cl
        JOIN car_searches cs ON cl.search_id = cs.id
        LEFT JOIN deal_scores ds ON cl.id = ds.listing_id
        WHERE cs.user_id = ? AND cl.location_lat IS NOT NULL AND cl.location_lng IS NOT NULL
    """
    
    params = [user_id]
    
    if search_id:
        query += " AND cs.id = ?"
        params.append(search_id)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    map_points = []
    for row in rows:
        map_points.append({
            "id": row[0],
            "title": row[1],
            "price": row[2],
            "latitude": row[3],
            "longitude": row[4],
            "url": row[5],
            "deal_score": row[6]
        })
    
    return {"map_points": map_points}

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

@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "timestamp": datetime.utcnow(),
        "service": "Enhanced Flippit Car Monitor",
        "version": "3.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print("🚀 Starting Enhanced Flippit API Server v3.0.0")
    print("✨ New Features: AI Deal Scoring, Push Notifications, Price Analytics")
    uvicorn.run(app, host="0.0.0.0", port=port)