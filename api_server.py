import requests
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import psycopg2
from psycopg2.extras import RealDictCursor
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

# Import our database module
from database import init_db, get_db_cursor, execute_query, execute_insert

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

# Global monitor instance
car_monitor = None
monitor_thread = None

# Admin emails
ADMIN_EMAILS = ["johnsilva36@live.com"]

# Constants for reasonable defaults
CURRENT_YEAR = datetime.now().year
MIN_CAR_YEAR = 1900  # First mass-produced cars
DEFAULT_MIN_YEAR = 1990  # Changed from CURRENT_YEAR - 20
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
    location: Optional[str] = "Miami, FL"
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
    result = execute_query(
        "SELECT subscription_tier FROM users WHERE id = %s",
        (user_id,),
        fetch_one=True
    )
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
    
    # Default to Miami if not found
    return FLORIDA_CITIES["miami"]

def get_mock_cars(search_config):
    """Get mock car data with value estimates for testing"""
    make = search_config.get('make', 'Toyota')
    model = search_config.get('model', 'Camry')
    location = search_config.get('location', 'Miami, FL')
    
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
    with get_db_cursor() as cursor:
        # Get search details
        cursor.execute("SELECT make, model, location FROM car_searches WHERE id = %s", (search_id,))
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
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
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
            
            listing_id = cursor.fetchone()[0]
            
            # Save value estimate data if available
            if car.get('has_analysis') and car.get('value_estimate'):
                cursor.execute("""
                    INSERT INTO deal_scores 
                    (listing_id, market_price_estimate, deal_score, quality_indicators, calculated_at)
                    VALUES (%s, %s, %s, %s, %s)
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
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (search_make, search_model, year_num, search_info[2], price_num, mileage_num))
            except Exception as e:
                print(f"Error saving price history: {e}")

def update_search_suggestions():
    """Update search suggestions based on current searches"""
    with get_db_cursor() as cursor:
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
                    INSERT INTO search_suggestions (make, model, search_count)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (make, model) DO UPDATE SET search_count = %s
                """, (make, model, count, count))
            elif make:
                cursor.execute("""
                    INSERT INTO search_suggestions (make, search_count)
                    VALUES (%s, %s)
                    ON CONFLICT (make) DO UPDATE SET search_count = %s
                    WHERE model IS NULL
                """, (make, count, count))

# Background monitoring
def run_continuous_monitoring():
    """Run car monitoring with subscription tiers and distance limits"""
    global car_monitor
    
    # Initialize monitor
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
            with get_db_cursor() as cursor:
                # Check total searches first
                cursor.execute("SELECT COUNT(*) FROM car_searches WHERE is_active = TRUE")
                total_searches = cursor.fetchone()[0]
                print(f"📊 Total active searches in database: {total_searches}")
                
                if total_searches == 0:
                    print("⚠️  No active searches found - users need to create searches first!")
                
                # Process searches by tier
                for tier, limits in SUBSCRIPTION_LIMITS.items():
                    tier_conditions = [tier]
                    if tier == 'pro':
                        tier_conditions.append('pro_yearly')
                    elif tier == 'premium':
                        tier_conditions.append('premium_yearly')
                    
                    placeholders = ','.join(['%s' for _ in tier_conditions])
                    
                    cursor.execute(f"""
                        SELECT cs.id, cs.make, cs.model, cs.year_min, cs.year_max, 
                               cs.price_min, cs.price_max, cs.mileage_max, cs.location,
                               cs.distance_miles, u.subscription_tier, u.email, u.id
                        FROM car_searches cs
                        JOIN users u ON cs.user_id = u.id 
                        WHERE cs.is_active = TRUE AND u.subscription_tier IN ({placeholders})
                    """, tier_conditions)
                    
                    tier_searches = cursor.fetchall()
                    print(f"🔍 Found {len(tier_searches)} searches for tier: {tier}")
                    
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
                                'location': search_row[8] or 'Miami, FL',
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
    try:
        user_id = execute_insert(
            "INSERT INTO users (email, password_hash, subscription_tier) VALUES (%s, %s, %s)",
            (user.email, hash_password(user.password), 'free'),
            returning_id=True
        )
        
        token = create_token(user_id)
        
        return {
            "token": token,
            "user_id": user_id,
            "subscription_tier": "free",
            "message": "Welcome to Flippit! You can search within 25 miles. Upgrade to Pro for 50 miles or Premium for 200 miles!"
        }
    
    except psycopg2.IntegrityError:
        raise HTTPException(status_code=400, detail="Email already registered")

@app.post("/login")
async def login(user: UserLogin):
    with get_db_cursor() as cursor:
        cursor.execute("""
            SELECT id, password_hash, subscription_tier 
            FROM users WHERE email = %s
        """, (user.email,))
        db_user = cursor.fetchone()
    
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
        with get_db_cursor() as cursor:
            cursor.execute("""
                UPDATE users SET 
                    subscription_tier = %s,
                    subscription_expires = %s,
                    apple_receipt_data = %s,
                    apple_original_transaction_id = %s,
                    apple_latest_transaction_id = %s,
                    apple_subscription_id = %s
                WHERE id = %s
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
                INSERT INTO apple_receipts 
                (user_id, receipt_data, transaction_id, original_transaction_id, 
                 product_id, purchase_date, expires_date, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (transaction_id) DO UPDATE SET
                    expires_date = EXCLUDED.expires_date,
                    is_active = EXCLUDED.is_active
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
        
        with get_db_cursor() as cursor:
            cursor.execute("""
                UPDATE users SET 
                    subscription_tier = %s,
                    subscription_expires = %s,
                    apple_receipt_data = %s,
                    apple_original_transaction_id = %s,
                    apple_latest_transaction_id = %s,
                    apple_subscription_id = %s
                WHERE id = %s
            """, (
                subscription_tier,
                active_subscription['expires_date'],
                receipt.receipt_data,
                active_subscription['original_transaction_id'],
                active_subscription['transaction_id'],
                active_subscription['product_id'],
                user_id
            ))
        
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
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT subscription_tier, subscription_expires, trial_ends, gifted_by 
                FROM users WHERE id = %s
            """, (user_id,))
            result = cursor.fetchone()
            
            if not result:
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
                    cursor.execute("UPDATE users SET subscription_tier = 'free' WHERE id = %s", (user_id,))
                    tier = 'free'
            
            limits = get_subscription_limits(tier)
            
            # Count current searches
            cursor.execute("SELECT COUNT(*) FROM car_searches WHERE user_id = %s AND is_active = TRUE", (user_id,))
            current_searches = cursor.fetchone()[0]
        
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
    print(f"🎯 Creating new search for user {user_id}")
    print(f"   Search details: {search.model_dump()}")
    
    with get_db_cursor() as cursor:
        # Get user's subscription
        tier = get_user_subscription_tier(user_id)
        limits = get_subscription_limits(tier)
        
        print(f"   User tier: {tier}, Max searches: {limits['max_searches']}")
        
        # Check search count
        cursor.execute("SELECT COUNT(*) FROM car_searches WHERE user_id = %s AND is_active = TRUE", (user_id,))
        current_count = cursor.fetchone()[0]
        
        print(f"   Current search count: {current_count}")
        
        if current_count >= limits['max_searches']:
            print(f"❌ Search limit reached for user {user_id}")
            raise HTTPException(
                status_code=403,
                detail=f"Search limit reached! {tier} tier allows {limits['max_searches']} searches."
            )
        
        # Set distance based on subscription or use provided value if within limits
        if search.distance_miles:
            if search.distance_miles > limits['max_distance_miles']:
                print(f"❌ Distance limit exceeded: {search.distance_miles} > {limits['max_distance_miles']}")
                raise HTTPException(
                    status_code=403,
                    detail=f"{tier} tier allows searches up to {limits['max_distance_miles']} miles. Upgrade for wider search!"
                )
            distance = search.distance_miles
        else:
            distance = limits['max_distance_miles']
        
        print(f"   Using distance: {distance} miles")
        
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
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, created_at, is_active""",
            (user_id, search.make, search.model, search.year_min, search.year_max,
             search.price_min, search.price_max, search.mileage_max, search.location, distance)
        )
        
        result = cursor.fetchone()
        search_id = result[0]
        created_at = result[1]
        is_active = result[2]
        
        print(f"✅ Created search with ID: {search_id}")
    
    if search.make or search.model:
        update_search_suggestions()
    
    return CarSearchResponse(
        id=search_id,
        make=search.make,
        model=search.model,
        year_min=search.year_min,
        year_max=search.year_max,
        price_min=search.price_min,
        price_max=search.price_max,
        mileage_max=search.mileage_max,
        location=search.location,
        distance_miles=distance,
        is_active=is_active,
        created_at=created_at.isoformat()
    )

@app.get("/search-defaults")
async def get_search_defaults(user_id: int = Depends(verify_token)):
    """Get default search values based on user's subscription tier"""
    tier = get_user_subscription_tier(user_id)
    limits = get_subscription_limits(tier)
    
    return {
        "defaults": {
            "make": None,
            "model": None,
            "year_min": DEFAULT_MIN_YEAR,
            "year_max": DEFAULT_MAX_YEAR,
            "price_min": DEFAULT_MIN_PRICE,
            "price_max": DEFAULT_MAX_PRICE,
            "mileage_max": None,
            "location": "Miami, FL",
            "distance_miles": limits['max_distance_miles']
        },
        "limits": {
            "max_distance_miles": limits['max_distance_miles'],
            "max_searches": limits['max_searches'],
            "tier": tier
        },
        "distance_options": [
            {"value": 10, "label": "10 miles", "available": 10 <= limits['max_distance_miles']},
            {"value": 25, "label": "25 miles", "available": 25 <= limits['max_distance_miles']},
            {"value": 50, "label": "50 miles", "available": 50 <= limits['max_distance_miles']},
            {"value": 100, "label": "100 miles", "available": 100 <= limits['max_distance_miles']},
            {"value": 200, "label": "200 miles", "available": 200 <= limits['max_distance_miles']}
        ],
        "year_range": {
            "min_allowed": MIN_CAR_YEAR,
            "max_allowed": DEFAULT_MAX_YEAR,
            "default_min": DEFAULT_MIN_YEAR,
            "default_max": DEFAULT_MAX_YEAR
        },
        "price_range": {
            "default_min": DEFAULT_MIN_PRICE,
            "default_max": DEFAULT_MAX_PRICE
        }
    }

@app.get("/debug-searches")
async def debug_searches(request: Request):
    """Debug endpoint to check all searches and user info"""
    try:
        # Try to get user from token
        auth_header = request.headers.get("authorization")
        user_id = None
        
        if auth_header:
            try:
                token = auth_header.replace("Bearer ", "")
                payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
                user_id = payload["user_id"]
            except Exception as e:
                print(f"Token error in debug: {e}")
        
        with get_db_cursor() as cursor:
            # Get all users
            cursor.execute("SELECT id, email, subscription_tier FROM users")
            all_users = cursor.fetchall()
            
            # Get all searches
            cursor.execute("""
                SELECT cs.id, cs.user_id, cs.make, cs.model, cs.is_active, cs.created_at, u.email
                FROM car_searches cs
                LEFT JOIN users u ON cs.user_id = u.id
                ORDER BY cs.created_at DESC
            """)
            all_searches = cursor.fetchall()
            
            # Get searches for current user if authenticated
            user_searches = []
            if user_id:
                cursor.execute("""
                    SELECT * FROM car_searches 
                    WHERE user_id = %s 
                    ORDER BY created_at DESC
                """, (user_id,))
                user_searches = cursor.fetchall()
        
        return {
            "authenticated_user_id": user_id,
            "total_users": len(all_users),
            "total_searches": len(all_searches),
            "current_user_searches": len(user_searches),
            "users": [{"id": u[0], "email": u[1], "tier": u[2]} for u in all_users],
            "all_searches": [
                {
                    "id": s[0],
                    "user_id": s[1],
                    "make": s[2],
                    "model": s[3],
                    "is_active": s[4],
                    "created_at": s[5].isoformat() if s[5] else None,
                    "user_email": s[6]
                } for s in all_searches
            ],
            "current_user_searches_detail": [
                {
                    "id": s[0],
                    "make": s[2],
                    "model": s[3],
                    "is_active": s[11] if len(s) > 11 else "unknown"
                } for s in user_searches
            ]
        }
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/car-searches", response_model=List[CarSearchResponse])
async def get_car_searches(user_id: int = Depends(verify_token)):
    print(f"🔍 Getting car searches for user {user_id}")
    
    with get_db_cursor() as cursor:
        cursor.execute("SELECT * FROM car_searches WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        rows = cursor.fetchall()
        
        print(f"📊 Found {len(rows)} searches for user {user_id}")
        for i, row in enumerate(rows):
            print(f"   Search {i+1}: ID={row[0]}, Make={row[2]}, Model={row[3]}, Active={row[11] if len(row) > 11 else 'unknown'}")
    
    searches = []
    for row in rows:
        try:
            search = CarSearchResponse(
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
                created_at=row[12].isoformat() if len(row) > 12 else ""
            )
            searches.append(search)
        except Exception as e:
            print(f"❌ Error processing search row {row[0]}: {e}")
    
    print(f"✅ Returning {len(searches)} valid searches")
    return searches

@app.put("/car-searches/{search_id}")
async def update_car_search(search_id: int, search: CarSearchUpdate, user_id: int = Depends(verify_token)):
    """Update existing car search"""
    with get_db_cursor() as cursor:
        # Verify ownership
        cursor.execute("SELECT user_id FROM car_searches WHERE id = %s", (search_id,))
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
        
        for field, value in search.model_dump(exclude_unset=True).items():
            update_fields.append(f"{field} = %s")
            values.append(value)
        
        if update_fields:
            values.append(search_id)
            cursor.execute(f"""
                UPDATE car_searches 
                SET {', '.join(update_fields)}
                WHERE id = %s
            """, values)
    
    return {"message": "Search updated successfully"}

@app.delete("/car-searches/{search_id}")
async def delete_car_search(search_id: int, user_id: int = Depends(verify_token)):
    with get_db_cursor() as cursor:
        cursor.execute("SELECT user_id FROM car_searches WHERE id = %s", (search_id,))
        search = cursor.fetchone()
        
        if not search or search[0] != user_id:
            raise HTTPException(status_code=404, detail="Search not found")
        
        cursor.execute("DELETE FROM car_searches WHERE id = %s", (search_id,))
    
    return {"message": "Car search deleted successfully"}

@app.get("/all-deals")
async def get_all_deals(user_id: int = Depends(verify_token)):
    """Get all found cars with value analysis"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    cl.id, cl.search_id, cl.title, cl.price, cl.year, cl.mileage,
                    cl.url, cl.found_at, cl.fuel_type, cl.transmission, cl.deal_score,
                    cs.make, cs.model,
                    ds.quality_indicators
                FROM car_listings cl
                JOIN car_searches cs ON cl.search_id = cs.id
                LEFT JOIN deal_scores ds ON cl.id = ds.listing_id
                WHERE cs.user_id = %s
                ORDER BY cl.found_at DESC
                LIMIT 100
            """, (user_id,))
            
            rows = cursor.fetchall()
        
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
                "found_at": row[7].isoformat() if row[7] else None,
                "fuel_type": row[8],
                "transmission": row[9],
                "deal_score_value": row[10],
                "search_make": row[11],
                "search_model": row[12],
                "is_mock": "mock" in (row[6] or "") or "test" in (row[6] or ""),
                "is_test_car": "mock" in (row[6] or "") or "test" in (row[6] or ""),
                "car_type": "Test Car" if ("mock" in (row[6] or "") or "test" in (row[6] or "")) else "Real Listing"
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
        return {"deals": [], "total": 0}

@app.get("/force-search-cycle")
async def force_search_cycle():
    """Manually trigger a search cycle for debugging"""
    try:
        with get_db_cursor() as cursor:
            # Check total searches
            cursor.execute("SELECT COUNT(*) FROM car_searches WHERE is_active = TRUE")
            total_searches = cursor.fetchone()[0]
            
            if total_searches == 0:
                return {"message": "No active searches found. Create a search first!", "total_searches": 0}
            
            # Get a sample search to test
            cursor.execute("""
                SELECT cs.id, cs.make, cs.model, cs.location, u.subscription_tier
                FROM car_searches cs
                JOIN users u ON cs.user_id = u.id 
                WHERE cs.is_active = TRUE
                LIMIT 1
            """)
            
            search = cursor.fetchone()
            if not search:
                return {"message": "No valid search found", "total_searches": total_searches}
            
            search_id, make, model, location, tier = search
            
            # Force mock data for this search
            search_config = {
                'make': make or 'Toyota',
                'model': model or 'Camry',
                'location': location or 'Miami, FL'
            }
            
            mock_cars = get_mock_cars(search_config)
            enhanced_save_car_listings(search_id, mock_cars)
        
        return {
            "message": f"Successfully added {len(mock_cars)} mock cars to search {search_id}",
            "search_info": {
                "id": search_id,
                "make": make,
                "model": model,
                "tier": tier
            },
            "cars_added": len(mock_cars)
        }
        
    except Exception as e:
        return {"error": str(e), "message": "Failed to force search cycle"}

@app.delete("/clear-test-cars/{search_id}")
async def clear_test_cars(search_id: int, user_id: int = Depends(verify_token)):
    """Clear all test/mock cars for a specific search"""
    with get_db_cursor() as cursor:
        # Verify ownership
        cursor.execute("SELECT user_id FROM car_searches WHERE id = %s", (search_id,))
        search_owner = cursor.fetchone()
        
        if not search_owner or search_owner[0] != user_id:
            raise HTTPException(status_code=404, detail="Search not found")
        
        # Delete mock cars (ones with mock URLs)
        cursor.execute("""
            DELETE FROM car_listings 
            WHERE search_id = %s AND (url LIKE '%mock%' OR url LIKE '%test%')
        """, (search_id,))
        
        deleted_count = cursor.rowcount
    
    return {
        "message": f"Cleared {deleted_count} test cars from search {search_id}",
        "deleted_count": deleted_count
    }

@app.delete("/clear-all-test-cars")
async def clear_all_test_cars(user_id: int = Depends(verify_token)):
    """Clear ALL test/mock cars for the current user - ONE CLICK CLEANUP"""
    with get_db_cursor() as cursor:
        # Delete mock cars for all user's searches
        cursor.execute("""
            DELETE FROM car_listings 
            WHERE search_id IN (
                SELECT id FROM car_searches WHERE user_id = %s
            ) AND (url LIKE '%mock%' OR url LIKE '%test%')
        """, (user_id,))
        
        deleted_count = cursor.rowcount
        
        # Also clear associated deal scores for deleted listings
        cursor.execute("""
            DELETE FROM deal_scores 
            WHERE listing_id NOT IN (SELECT id FROM car_listings)
        """)
    
    return {
        "success": True,
        "message": f"✅ Cleaned up! Removed {deleted_count} test cars from all searches",
        "deleted_count": deleted_count,
        "action": "All test cars have been removed. You now see only real listings."
    }

@app.get("/search-stats/{search_id}")
async def get_search_stats(search_id: int, user_id: int = Depends(verify_token)):
    """Get statistics about a search including test vs real cars"""
    with get_db_cursor() as cursor:
        # Verify ownership
        cursor.execute("SELECT user_id, make, model FROM car_searches WHERE id = %s", (search_id,))
        search_info = cursor.fetchone()
        
        if not search_info or search_info[0] != user_id:
            raise HTTPException(status_code=404, detail="Search not found")
        
        # Count total cars
        cursor.execute("SELECT COUNT(*) FROM car_listings WHERE search_id = %s", (search_id,))
        total_cars = cursor.fetchone()[0]
        
        # Count test cars
        cursor.execute("""
            SELECT COUNT(*) FROM car_listings 
            WHERE search_id = %s AND (url LIKE '%mock%' OR url LIKE '%test%')
        """, (search_id,))
        test_cars = cursor.fetchone()[0]
        
        # Count real cars
        real_cars = total_cars - test_cars
        
        # Get latest cars
        cursor.execute("""
            SELECT title, price, url, found_at 
            FROM car_listings 
            WHERE search_id = %s 
            ORDER BY found_at DESC 
            LIMIT 5
        """, (search_id,))
        latest_cars = cursor.fetchall()
    
    return {
        "search_id": search_id,
        "search_name": f"{search_info[1] or ''} {search_info[2] or ''}".strip() or "All Cars",
        "total_cars": total_cars,
        "real_cars": real_cars,
        "test_cars": test_cars,
        "has_test_cars": test_cars > 0,
        "latest_cars": [
            {
                "title": car[0],
                "price": car[1],
                "is_test": "mock" in (car[2] or ""),
                "found_at": car[3].isoformat() if car[3] else None
            } for car in latest_cars
        ]
    }

@app.get("/test-search/{search_id}")
async def test_car_search(search_id: int, user_id: int = Depends(verify_token)):
    """Manually trigger a search test with mock data (auto-clears old test cars)"""
    with get_db_cursor() as cursor:
        cursor.execute("""
            SELECT * FROM car_searches 
            WHERE id = %s AND user_id = %s
        """, (search_id, user_id))
        
        search = cursor.fetchone()
        if not search:
            raise HTTPException(status_code=404, detail="Search not found")
        
        # AUTO-CLEAR: Remove old test cars first
        cursor.execute("""
            DELETE FROM car_listings 
            WHERE search_id = %s AND (url LIKE '%mock%' OR url LIKE '%test%')
        """, (search_id,))
        old_test_cars = cursor.rowcount
        
        search_config = {
            'make': search[2],
            'model': search[3],
            'year_min': search[4],
            'year_max': search[5],
            'price_min': search[6],
            'price_max': search[7],
            'mileage_max': search[8],
            'location': search[9] or 'Miami, FL',
            'distance_miles': search[10] if len(search) > 10 else 25
        }
        
        # Add fresh mock cars
        mock_cars = get_mock_cars(search_config)
        enhanced_save_car_listings(search_id, mock_cars)
    
    return {
        "message": f"Replaced {old_test_cars} old test cars with {len(mock_cars)} fresh test cars",
        "old_test_cars_removed": old_test_cars,
        "new_test_cars_added": len(mock_cars),
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
    print("🍎 Starting Enhanced Flippit API Server v3.2.0 with iOS In-App Purchase")
    print("✨ Features: iOS IAP, Distance-based search limits, KBB values, Deal scoring")
    print(f"📍 Free: 25 miles | Pro: 50 miles | Premium: 200 miles")
    print(f"💰 Pricing: Pro $14.99/mo or $152.99/yr (15% off) | Premium $49.99/mo or $479.99/yr (20% off)")
    print(f"🔑 Secret key configured: {SECRET_KEY[:10]}... (length: {len(SECRET_KEY)})")
    print("🐘 Using PostgreSQL database for persistent storage")
    uvicorn.run(app, host="0.0.0.0", port=port)
