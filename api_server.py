from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import sqlite3
import hashlib
import jwt
from datetime import datetime, timedelta
import os
import threading
import time

# Import our car scraper
from fb_scraper import CarSearchMonitor

app = FastAPI(title="Car Marketplace Monitor API", version="1.0.0")

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subscription_tier TEXT DEFAULT 'free'
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

# Pydantic models
class UserRegister(BaseModel):
    email: str
    password: str

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

# Background monitoring
def run_continuous_monitoring():
    """Run car monitoring in background"""
    global car_monitor
    if car_monitor is None:
        car_monitor = CarSearchMonitor()
    
    while True:
        try:
            # Get all active searches from database
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, make, model, year_min, year_max, price_min, price_max, 
                       mileage_max, location 
                FROM car_searches WHERE is_active = TRUE
            """)
            
            active_searches = cursor.fetchall()
            conn.close()
            
            if active_searches:
                print(f"🔄 Monitoring {len(active_searches)} active car searches...")
                
                for search_row in active_searches:
                    search_id = search_row[0]
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
                    new_cars = car_monitor.monitor_car_search(search_config)
                    
                    # Save new listings to database
                    if new_cars:
                        save_new_car_listings(search_id, new_cars)
                    
                    time.sleep(10)  # Delay between searches
            
            # Wait 10 minutes before next full cycle
            time.sleep(600)
            
        except Exception as e:
            print(f"❌ Error in monitoring thread: {e}")
            time.sleep(60)  # Wait 1 minute on error

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
    print(f"💾 Saved {len(cars)} new car listings for search {search_id}")

# API Routes
@app.on_event("startup")
async def startup_event():
    init_db()
    
    # Start background monitoring thread
    global monitor_thread
    if monitor_thread is None:
        monitor_thread = threading.Thread(target=run_continuous_monitoring, daemon=True)
        monitor_thread.start()
        print("🚀 Started background car monitoring")

@app.post("/register")
async def register(user: UserRegister):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (user.email, hash_password(user.password))
        )
        conn.commit()
        user_id = cursor.lastrowid
        token = create_token(user_id)
        
        return {"token": token, "user_id": user_id}
    
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Email already registered")
    finally:
        conn.close()

@app.post("/login")
async def login(user: UserLogin):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, password_hash FROM users WHERE email = ?", (user.email,))
    db_user = cursor.fetchone()
    
    if not db_user or not verify_password(user.password, db_user[1]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(db_user[0])
    conn.close()
    
    return {"token": token, "user_id": db_user[0]}

@app.post("/car-searches", response_model=CarSearchResponse)
async def create_car_search(search: CarSearchCreate, user_id: int = Depends(verify_token)):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
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
        "SELECT * FROM car_listings WHERE search_id = ? ORDER BY found_at DESC",
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
    
    return {"message": "Car search deleted"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}

@app.get("/")
async def root():
    return {"message": "Car Marketplace Monitor API", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
