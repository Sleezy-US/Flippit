import time
import json
from datetime import datetime
import re
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SeleniumFacebookCarScraper:
    def __init__(self, use_selenium=True):
        self.use_selenium = use_selenium
        self.driver = None
        
        # Location coordinates mapping
        self.location_coords = {
            'Miami, FL': {'lat': 25.7617, 'lng': -80.1918},
            'Orlando, FL': {'lat': 28.5383, 'lng': -81.3792},
            'Tampa, FL': {'lat': 27.9506, 'lng': -82.4572},
            'Fort Lauderdale, FL': {'lat': 26.1224, 'lng': -80.1373},
            'Jacksonville, FL': {'lat': 30.3322, 'lng': -81.6557},
        }
        
        if self.use_selenium:
            self.setup_driver()
    
    def setup_driver(self):
        """Setup Chrome driver for Railway/Heroku deployment"""
        try:
            chrome_options = Options()
            
            # Essential options for headless operation
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-web-security')
            chrome_options.add_argument('--disable-features=VizDisplayCompositor')
            
            # Performance options
            chrome_options.add_argument('--memory-pressure-off')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            
            # Set window size to ensure elements are visible
            chrome_options.add_argument('--window-size=1920,1080')
            
            # User agent to look more real
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            # Disable images for faster loading (optional)
            prefs = {"profile.managed_default_content_settings.images": 2}
            chrome_options.add_experimental_option("prefs", prefs)
            
            # Initialize driver
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.set_page_load_timeout(30)
            
            logger.info("✅ Selenium Chrome driver initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to setup Selenium driver: {e}")
            self.use_selenium = False
    
    def search_cars(self, make=None, model=None, year_min=None, year_max=None,
                   price_min=None, price_max=None, mileage_max=None,
                   location="Miami, FL", distance_miles=25):
        """Search Facebook Marketplace for cars using Selenium"""
        
        if not self.use_selenium or not self.driver:
            logger.warning("⚠️ Selenium not available, falling back to basic scraper")
            return []
        
        try:
            # Build Facebook Marketplace URL
            url = self._build_marketplace_url(
                make, model, year_min, year_max,
                price_min, price_max, location, distance_miles
            )
            
            logger.info(f"🚗 Searching for: {make or 'Any'} {model or 'car'}")
            logger.info(f"📍 Location: {location} ({distance_miles} miles)")
            logger.info(f"🔗 URL: {url}")
            
            # Navigate to the page
            self.driver.get(url)
            
            # Wait for page to load
            time.sleep(random.uniform(3, 5))
            
            # Handle login prompt if it appears
            if self._check_login_required():
                logger.warning("🚫 Facebook requires login - using mock data")
                return []
            
            # Scroll to load more results
            self._scroll_page()
            
            # Extract listings
            listings = self._extract_listings()
            
            logger.info(f"✅ Found {len(listings)} car listings")
            return listings
            
        except Exception as e:
            logger.error(f"❌ Selenium search error: {e}")
            return []
    
    def _build_marketplace_url(self, make, model, year_min, year_max,
                              price_min, price_max, location, distance_miles):
        """Build Facebook Marketplace URL with all parameters"""
        
        # Get location coordinates
        coords = self.location_coords.get(location, self.location_coords['Miami, FL'])
        
        # Base URL for vehicles in specific location
        if location == "Miami, FL":
            base_url = "https://www.facebook.com/marketplace/miami/vehicles"
        else:
            base_url = "https://www.facebook.com/marketplace/category/vehicles"
        
        # Build query parameters
        params = []
        
        # Search query
        if make or model:
            query = f"{make or ''} {model or ''}".strip()
            params.append(f"query={query}")
        
        # Price range
        if price_min:
            params.append(f"minPrice={price_min}")
        if price_max:
            params.append(f"maxPrice={price_max}")
        
        # Year range
        if year_min:
            params.append(f"minYear={year_min}")
        if year_max:
            params.append(f"maxYear={year_max}")
        
        # Location parameters
        params.append(f"latitude={coords['lat']}")
        params.append(f"longitude={coords['lng']}")
        params.append(f"radius={int(distance_miles * 1.60934)}")  # Convert to km
        
        # Sort by newest
        params.append("sortBy=creation_time_descend")
        
        # Combine URL
        if params:
            return f"{base_url}?{'&'.join(params)}"
        return base_url
    
    def _check_login_required(self):
        """Check if Facebook is showing login page"""
        try:
            # Check for common login indicators
            login_indicators = [
                "//button[contains(text(), 'Log In')]",
                "//a[contains(@href, '/login')]",
                "//div[contains(text(), 'You must log in')]"
            ]
            
            for indicator in login_indicators:
                elements = self.driver.find_elements(By.XPATH, indicator)
                if elements:
                    return True
            return False
        except:
            return False
    
    def _scroll_page(self):
        """Scroll page to load more results"""
        try:
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            scrolls = 0
            max_scrolls = 5
            
            while scrolls < max_scrolls:
                # Scroll down
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(2, 3))
                
                # Check if more content loaded
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                    
                last_height = new_height
                scrolls += 1
                
            logger.info(f"📜 Scrolled {scrolls} times to load results")
        except Exception as e:
            logger.error(f"Scroll error: {e}")
    
    def _extract_listings(self):
        """Extract car listings from the page"""
        listings = []
        
        try:
            # Wait for listings to be present
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/marketplace/item/')]"))
            )
            
            # Find all listing links
            listing_elements = self.driver.find_elements(
                By.XPATH, "//a[contains(@href, '/marketplace/item/')]"
            )
            
            for element in listing_elements[:20]:  # Limit to 20 results
                try:
                    listing = self._extract_listing_data(element)
                    if listing and self._is_valid_car_listing(listing):
                        listings.append(listing)
                except Exception as e:
                    continue
                    
        except TimeoutException:
            logger.warning("⏱️ Timeout waiting for listings")
        except Exception as e:
            logger.error(f"❌ Error extracting listings: {e}")
            
        return listings
    
    def _extract_listing_data(self, element):
        """Extract data from a single listing element"""
        try:
            # Get the parent container for more data
            container = element.find_element(By.XPATH, "./ancestor::div[contains(@style, 'border-radius')]")
            text = container.text
            
            # Extract price
            price_match = re.search(r'\$[\d,]+', text)
            if not price_match:
                return None
                
            price = price_match.group()
            
            # Extract title (usually first line)
            lines = text.split('\n')
            title = lines[0] if lines else ""
            
            # Extract year
            year_match = re.search(r'\b(19\d{2}|20\d{2})\b', text)
            year = year_match.group() if year_match else None
            
            # Extract mileage
            mileage_match = re.search(r'([\d,]+)\s*(?:miles?|mi\b)', text, re.IGNORECASE)
            mileage = mileage_match.group(1) if mileage_match else None
            
            # Get URL
            url = element.get_attribute('href')
            if url and not url.startswith('http'):
                url = f"https://www.facebook.com{url}"
            
            return {
                'title': title,
                'price': price,
                'year': year,
                'mileage': mileage,
                'url': url,
                'location': text.split('\n')[-1] if '\n' in text else "",
                'raw_text': text[:200],
                'found_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            return None
    
    def _is_valid_car_listing(self, listing):
        """Check if listing is a valid car"""
        text = (listing.get('title', '') + ' ' + listing.get('raw_text', '')).lower()
        
        # Must have price and title
        if not listing.get('price') or not listing.get('title'):
            return False
            
        # Car keywords
        car_indicators = ['car', 'vehicle', 'miles', 'automatic', 'manual',
                         'sedan', 'suv', 'truck', 'van', 'coupe']
        
        # Check if any car indicator is present
        return any(indicator in text for indicator in car_indicators)
    
    def cleanup(self):
        """Close the Selenium driver"""
        if self.driver:
            self.driver.quit()
            logger.info("🧹 Selenium driver closed")

# Wrapper to use either Selenium or basic scraper
class EnhancedFacebookCarScraper:
    def __init__(self, use_selenium=True):
        self.use_selenium = use_selenium and self._check_selenium_available()
        
        if self.use_selenium:
            logger.info("🚀 Using Selenium-enhanced scraper")
            self.scraper = SeleniumFacebookCarScraper(use_selenium=True)
        else:
            logger.info("⚠️ Selenium not available, using basic scraper")
            # Fall back to your existing scraper
            from fb_scraper import FacebookCarScraper
            self.scraper = FacebookCarScraper()
    
    def _check_selenium_available(self):
        """Check if Selenium and Chrome are available"""
        try:
            from selenium import webdriver
            # Try to create a headless Chrome instance
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')
            driver = webdriver.Chrome(options=options)
            driver.quit()
            return True
        except:
            return False
    
    def search_cars(self, **kwargs):
        """Search for cars using the appropriate scraper"""
        return self.scraper.search_cars(**kwargs)
    
    def cleanup(self):
        """Cleanup resources"""
        if hasattr(self.scraper, 'cleanup'):
            self.scraper.cleanup()
