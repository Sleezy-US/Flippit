import stripe
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import sqlite3
import hashlib
from jose import jwt
from datetime import datetime, timedelta
import os
import threading
import time

# Import our car scraper
from fb_scraper import CarSearchMonitor

# Stripe configuration
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_your_stripe_key_here")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_your_webhook_secret")

app = FastAPI(title="Flippit - Car Marketplace Monitor API", version="2.0.0")

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

# Subscription Configuration
SUBSCRIPTION_INTERVALS = {
    'free': 1500,      # 25 minutes (1500 seconds)
    'pro': 600,        # 10 minutes (600 seconds) 
    'premium': 300,    # 5 minutes (300 seconds)
}

SUBSCRIPTION_LIMITS = {
    'free': {
        'max_searches': 3,
        'interval': 1500,
        'features': ['basic_search', 'email_notifications']
    },
    'pro': {
        'max_searches': 15,
        'interval': 600,
        'features': ['basic_search', 'email_notifications', 'advanced_filters', 'priority_support']
    },
    'pro_yearly': {
        'max_searches': 15,
        'interval': 600,
        'features': ['basic_search', 'email_notifications', 'advanced_filters', 'priority_support']
    },
    'premium': {
        'max_searches': 25,
        'interval': 300,
        'features': ['basic_search', 'email_notifications', 'advanced_filters', 'priority_support', 'instant_alerts', 'unlimited_locations']
    },
    'premium_yearly': {
        'max_searches': 25,
        'interval': 300,
        'features': ['basic_search', 'email_notifications', 'advanced_filters', 'priority_support', 'instant_alerts', 'unlimited_locations']
    }
}

def init_db():
    """Initialize SQLite database for car searches"""
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
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            stripe_payment_method_id TEXT,
            cancel_at_period_end BOOLEAN DEFAULT FALSE,
            gifted_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Car searches table
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
            FOREIGN KEY (search_id) REFERENCES car_searches (id)
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

class UserRegister(BaseModel):
    email: str
    password: str

class TrialSignup(BaseModel):
    email: str
    password: str
    payment_method_id: str  # From Stripe Elements

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

class GiftSubscription(BaseModel):
    recipient_email: str
    tier: str
    duration_months: int
    message: Optional[str] = None

class SubscriptionManagement(BaseModel):
    action: str  # 'cancel', 'reactivate', 'change_plan'
    new_tier: Optional[str] = None

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
    
    if not result:
        conn.close()
        return 'free'
    
    tier = result[0]
    conn.close()
    
    # Map yearly tiers to their base tier for limits
    if tier == 'pro_yearly':
        return 'pro'
    elif tier == 'premium_yearly':
        return 'premium'
    
    return tier

# Background monitoring with tier-based intervals
def run_continuous_monitoring():
    """Run car monitoring with tier-based intervals"""
    global car_monitor
    if car_monitor is None:
        car_monitor = CarSearchMonitor()
    
    print("🚀 Starting Flippit car monitoring with subscription tiers!")
    
    while True:
        try:
            # Process each subscription tier
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            
            for tier, limits in SUBSCRIPTION_LIMITS.items():
                interval = limits['interval']
                
                # Get searches for this tier (include yearly variants)
                tier_conditions = [tier]
                if tier == 'pro':
                    tier_conditions.append('pro_yearly')
                elif tier == 'premium':
                    tier_conditions.append('premium_yearly')
                
                placeholders = ','.join(['?' for _ in tier_conditions])
                
                cursor.execute(f"""
                    SELECT cs.id, cs.make, cs.model, cs.year_min, cs.year_max, 
                           cs.price_min, cs.price_max, cs.mileage_max, cs.location,
                           u.subscription_tier, u.email
                    FROM car_searches cs
                    JOIN users u ON cs.user_id = u.id 
                    WHERE cs.is_active = TRUE AND u.subscription_tier IN ({placeholders})
                """, tier_conditions)
                
                tier_searches = cursor.fetchall()
                
                if tier_searches:
                    print(f"🔄 Processing {len(tier_searches)} {tier.upper()} searches (every {interval//60} minutes)")
                    
                    for search_row in tier_searches:
                        search_id = search_row[0]
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
                        
                        # Monitor this search
                        try:
                            new_cars = car_monitor.monitor_car_search(search_config)
                            
                            # Save new listings
                            if new_cars:
                                save_new_car_listings(search_id, new_cars)
                                search_name = f"{search_config.get('make', '')} {search_config.get('model', '')}".strip()
                                print(f"🚗 {tier.upper()} user ({user_email}) found {len(new_cars)} new {search_name} cars!")
                        
                        except Exception as e:
                            print(f"❌ Error monitoring search {search_id}: {e}")
                        
                        time.sleep(3)  # Small delay between searches
                
                time.sleep(5)  # Delay between tiers
            
            conn.close()
            
            # Wait before next cycle (use shortest interval for premium users)
            min_interval = min(limits['interval'] for limits in SUBSCRIPTION_LIMITS.values())
            print(f"💤 Next monitoring cycle in {min_interval//60} minutes...")
            time.sleep(min_interval)
            
        except Exception as e:
            print(f"❌ Error in monitoring thread: {e}")
            time.sleep(60)

def save_new_car_listings(search_id: int, cars: list):
    """Save new car listings to database"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    for car in cars:
        cursor.execute("""
            INSERT INTO car_listings (search_id, title, price, year, mileage, url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            search_id,
            car['title'],
            car['price'],
            car.get('year'),
            car.get('mileage'),
            car.get('url')
        ))
    
    conn.commit()
    conn.close()

# API Routes
@app.on_event("startup")
async def startup_event():
    init_db()
    
    # Start background monitoring thread
    global monitor_thread
    if monitor_thread is None:
        monitor_thread = threading.Thread(target=run_continuous_monitoring, daemon=True)
        monitor_thread.start()
        print("🚀 Flippit monitoring started with subscription tiers!")

@app.get("/")
async def root():
    return {
        "message": "🚗 Flippit - Car Marketplace Monitor", 
        "version": "2.0.0",
        "features": "Subscription tiers with smart monitoring",
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
            "message": "Welcome to Flippit! You have 3 free car searches. Start a 7-day Pro trial for 15 searches and faster alerts!"
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
            items=[{'price': 'price_1RbtlsHH6XNAV6XKBbiwpO4K'}],  # You'll need to create this in Stripe
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
            "message": "7-day Pro trial started! You have 15 car searches and 10-minute alerts. Your card will be charged $15/month after the trial unless you cancel."
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
            detail=f"Search limit reached! {tier_display[subscription_tier]} allows {max_searches} searches. Upgrade for more searches."
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
    
    search_name = f"{search.make or ''} {search.model or ''}".strip() or "cars"
    
    # Get interval for display (handle yearly tiers)
    display_tier = subscription_tier
    if subscription_tier in ['pro_yearly']:
        display_tier = 'pro'
    elif subscription_tier in ['premium_yearly']:
        display_tier = 'premium'
    
    interval = SUBSCRIPTION_LIMITS[display_tier]['interval'] // 60
    
    print(f"✅ New {subscription_tier} search created: {search_name} (checks every {interval} minutes)")
    
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

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks for subscription events"""
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
        if event['type'] == 'customer.subscription.updated':
            subscription = event['data']['object']
            customer_id = subscription['customer']
            
            # Find user by Stripe customer ID
            cursor.execute("SELECT id FROM users WHERE stripe_customer_id = ?", (customer_id,))
            user = cursor.fetchone()
            
            if user:
                user_id = user[0]
                
                # Update subscription status based on Stripe
                if subscription['status'] == 'active':
                    # Determine tier from Stripe price
                    price_id = subscription['items']['data'][0]['price']['id']
                    tier_map = {
                        "price_1RbtlsHH6XNAV6XKBbiwpO4K": "pro",
                        "price_1RbtnZHH6XNAV6XKoCvZdKQX": "pro_yearly",
                        "price_1Rbtp7HH6XNAV6XKQPe7ow42": "premium", 
                        "price_1RbtpcHH6XNAV6XKlfmvTpke": "premium_yearly"
                    }
                    
                    new_tier = tier_map.get(price_id, 'pro')
                    
                    cursor.execute("""
                        UPDATE users 
                        SET subscription_tier = ?, is_trial = FALSE, trial_ends = NULL,
                            cancel_at_period_end = ?
                        WHERE id = ?
                    """, (new_tier, subscription.get('cancel_at_period_end', False), user_id))
                    
                elif subscription['status'] in ['canceled', 'unpaid']:
                    # Downgrade to free
                    cursor.execute("""
                        UPDATE users 
                        SET subscription_tier = 'free', is_trial = FALSE,
                            trial_ends = NULL, stripe_subscription_id = NULL
                        WHERE id = ?
                    """, (user_id,))
        
        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            customer_id = subscription['customer']
            
            cursor.execute("SELECT id FROM users WHERE stripe_customer_id = ?", (customer_id,))
            user = cursor.fetchone()
            
            if user:
                # Downgrade to free when subscription is deleted
                cursor.execute("""
                    UPDATE users 
                    SET subscription_tier = 'free', is_trial = FALSE,
                        trial_ends = NULL, stripe_subscription_id = NULL
                    WHERE id = ?
                """, (user[0],))
        
        elif event['type'] == 'invoice.payment_failed':
            invoice = event['data']['object']
            customer_id = invoice['customer']
            
            cursor.execute("SELECT id, email FROM users WHERE stripe_customer_id = ?", (customer_id,))
            user = cursor.fetchone()
            
            if user:
                # You could send email notification about failed payment
                print(f"Payment failed for user {user[1]} (ID: {user[0]})")
        
        conn.commit()
        
    except Exception as e:
        print(f"Webhook error: {e}")
        conn.rollback()
    finally:
        conn.close()
    
    return {"status": "success"}

@app.get("/pricing")
async def get_pricing():
    return {
        "tiers": {
            "free": {
                "name": "Free",
                "price": "$0/month",
                "interval": "25 minutes",
                "max_searches": 3,
                "features": [
                    "3 active car searches",
                    "25-minute refresh rate",
                    "Basic email notifications",
                    "Standard support"
                ]
            },
            "pro": {
                "name": "Pro Monthly", 
                "price": "$15/month",
                "interval": "10 minutes",
                "max_searches": 15,
                "annual_option": {
                    "price": "$153/year",
                    "monthly_equivalent": "$12.75/month",
                    "savings": "15% off",
                    "total_savings": "$27/year"
                },
                "features": [
                    "15 active car searches",
                    "10-minute refresh rate", 
                    "Email & push notifications",
                    "Advanced filters",
                    "Priority support",
                    "Multiple locations"
                ]
            },
            "premium": {
                "name": "Premium Monthly",
                "price": "$50/month", 
                "interval": "5 minutes",
                "max_searches": 25,
                "annual_option": {
                    "price": "$480/year",
                    "monthly_equivalent": "$40/month",
                    "savings": "20% off",
                    "total_savings": "$120/year"
                },
                "features": [
                    "25 active car searches",
                    "5-minute refresh rate",
                    "Instant notifications",
                    "All advanced features",
                    "VIP support",
                    "Unlimited locations",
                    "Custom alerts"
                ]
            }
        },
        "comparison": {
            "swoopa_pricing": "$300-600/month",
            "our_monthly_savings": "92-95% cheaper than Swoopa",
            "our_annual_savings": "Even better with annual plans!",
            "value_proposition": "Professional car flipping tools at fraction of the cost"
        },
        "annual_benefits": [
            "Lock in current pricing",
            "Significant cost savings",
            "No monthly billing hassle",
            "Priority customer support"
        ]
    }

@app.get("/stats")
async def get_stats(user_id: int = Depends(verify_token)):
    """Get user statistics"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Get total cars found for user
    cursor.execute("""
        SELECT COUNT(*) FROM car_listings cl
        JOIN car_searches cs ON cl.search_id = cs.id
        WHERE cs.user_id = ?
    """, (user_id,))
    total_cars = cursor.fetchone()[0]
    
    # Get cars found in last 24 hours
    cursor.execute("""
        SELECT COUNT(*) FROM car_listings cl
        JOIN car_searches cs ON cl.search_id = cs.id
        WHERE cs.user_id = ? AND cl.found_at > datetime('now', '-24 hours')
    """, (user_id,))
    cars_today = cursor.fetchone()[0]
    
    # Get subscription info
    cursor.execute("SELECT subscription_tier FROM users WHERE id = ?", (user_id,))
    tier = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total_cars_found": total_cars,
        "cars_found_today": cars_today,
        "subscription_tier": tier,
        "monitoring_interval": f"{SUBSCRIPTION_LIMITS[tier]['interval'] // 60} minutes"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "timestamp": datetime.utcnow(),
        "service": "Flippit Car Monitor",
        "version": "2.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)