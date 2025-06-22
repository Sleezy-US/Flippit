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
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import logging
import os
import subprocess

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
            'Cape Coral, FL': {'lat': 26.5629, 'lng': -81.9495},
            'Fort Myers, FL': {'lat': 26.6406, 'lng': -81.8723},
            'Naples, FL': {'lat': 26.1420, 'lng': -81.7948},
            'Sarasota, FL': {'lat': 27.3364, 'lng': -82.5307},
            'Port Charlotte, FL': {'lat': 26.9762, 'lng': -82.0906},
            'Bonita Springs, FL': {'lat': 26.3398, 'lng': -81.7787}
        }
        
        if self.use_selenium:
            self.setup_driver()
    
    def find_chrome_binary(self):
        """Find Chrome/Chromium binary in Railway environment"""
        possible_paths = [
            '/nix/store/*/bin/chromium',  # Nix store path (Railway uses Nix)
            '/usr/bin/chromium',
            '/usr/bin/chromium-browser',
            '/usr/bin/google-chrome',
            '/usr/local/bin/chromium',
            '/app/.apt/usr/bin/google-chrome',
            'chromium',  # Let system PATH handle it
            'chromium-browser',
            'google-chrome'
        ]
        
        # Check Nix store specifically
        try:
            # Use glob to find chromium in nix store
            import glob
            nix_chromiums = glob.glob('/nix/store/*/bin/chromium')
            if nix_chromiums:
                logger.info(f"Found Chromium in Nix store: {nix_chromiums[0]}")
                return nix_chromiums[0]
        except Exception as e:
            logger.warning(f"Error searching Nix store: {e}")
        
        # Check standard paths
        for path in possible_paths:
            try:
                if os.path.exists(path):
                    logger.info(f"Found Chrome binary at: {path}")
                    return path
                    
                # Try to run it to see if it's in PATH
                result = subprocess.run([path, '--version'],
                                      capture_output=True,
                                      text=True,
                                      timeout=5)
                if result.returncode == 0:
                    logger.info(f"Found Chrome binary via PATH: {path}")
                    return path
            except:
                continue
        
        logger.error("Could not find Chrome/Chromium binary")
        return None
    
    def find_chromedriver(self):
        """Find ChromeDriver in Railway environment"""
        possible_paths = [
            '/nix/store/*/bin/chromedriver',  # Nix store path
            '/usr/bin/chromedriver',
            '/usr/local/bin/chromedriver',
            '/app/.chromedriver/chromedriver',
            'chromedriver'  # Let system PATH handle it
        ]
        
        # Check Nix store specifically
        try:
            import glob
            nix_drivers = glob.glob('/nix/store/*/bin/chromedriver')
            if nix_drivers:
                logger.info(f"Found ChromeDriver in Nix store: {nix_drivers[0]}")
                return nix_drivers[0]
        except Exception as e:
            logger.warning(f"Error searching Nix store for chromedriver: {e}")
        
        # Check standard paths
        for path in possible_paths:
            try:
                if os.path.exists(path):
                    logger.info(f"Found ChromeDriver at: {path}")
                    return path
                    
                # Try to run it
                result = subprocess.run([path, '--version'],
                                      capture_output=True,
                                      text=True,
                                      timeout=5)
                if result.returncode == 0:
                    logger.info(f"Found ChromeDriver via PATH: {path}")
                    return path
            except:
                continue
        
        logger.warning("Could not find ChromeDriver, will try without explicit path")
        return None
    
    def setup_driver(self):
        """Setup Chrome driver for Railway deployment"""
        try:
            chrome_options = Options()
            
            # Essential options for headless operation
            chrome_options.add_argument('--headless=new')  # New headless mode
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-web-security')
            chrome_options.add_argument('--disable-features=VizDisplayCompositor')
            chrome_options.add_argument('--disable-software-rasterizer')
            
            # Performance options
            chrome_options.add_argument('--memory-pressure-off')
            chrome_options.add_argument('--max_old_space_size=4096')
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            
            # Set window size to ensure elements are visible
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--start-maximized')
            
            # User agent to look more real
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            # Disable images for faster loading and less memory
            prefs = {
                "profile.managed_default_content_settings.images": 2,
                "profile.default_content_setting_values": {
                    "cookies": 1,
                    "images": 2,
                    "javascript": 1,
                    "plugins": 2,
                    "popups": 2,
                    "geolocation": 2,
                    "notifications": 2,
                    "media_stream": 2,
                }
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            # Find Chrome binary
            chrome_binary = self.find_chrome_binary()
            if chrome_binary:
                chrome_options.binary_location = chrome_binary
            else:
                logger.warning("Chrome binary not found, trying default...")
            
            # Find ChromeDriver
            chromedriver_path = self.find_chromedriver()
            
            # Initialize driver
            if chromedriver_path:
                service = Service(chromedriver_path)
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                # Try without explicit path
                self.driver = webdriver.Chrome(options=chrome_options)
            
            self.driver.set_page_load_timeout(30)
            
            # Test the driver
            self.driver.get("https://www.google.com")
            logger.info("✅ Selenium Chrome driver initialized and tested successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to setup Selenium driver: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")
            self.use_selenium = False
            self.driver = None
    
    def search_cars(self, make=None, model=None, year_min=None, year_max=None,
                   price_min=None, price_max=None, mileage_max=None,
                   location="Miami, FL", distance_miles=25):
        """Search Facebook Marketplace for cars using Selenium"""
        
        if not self.use_selenium or not self.driver:
            logger.warning("⚠️ Selenium not available, returning empty results")
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
                logger.warning("🚫 Facebook requires login - cannot proceed without authentication")
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
        
        # Base URL for vehicles
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
        
        # Year range - Facebook uses different parameter names
        if year_min:
            params.append(f"minYear={year_min}")
        if year_max:
            params.append(f"maxYear={year_max}")
        
        # Location parameters
        params.append(f"latitude={coords['lat']}")
        params.append(f"longitude={coords['lng']}")
        params.append(f"radius={int(distance_miles * 1.60934)}")  # Convert miles to km
        
        # Sort by newest
        params.append("sortBy=creation_time_descend")
        
        # Vehicle specific parameters
        params.append("vehicleTaxonomy=vehicles")
        
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
                "//button[contains(text(), 'Log in')]",
                "//a[contains(@href, '/login')]",
                "//div[contains(text(), 'You must log in')]",
                "//div[contains(text(), 'You must be logged in')]"
            ]
            
            for indicator in login_indicators:
                elements = self.driver.find_elements(By.XPATH, indicator)
                if elements:
                    logger.info("Login page detected")
                    return True
                    
            # Also check URL
            if '/login' in self.driver.current_url:
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
            
            logger.info(f"Found {len(listing_elements)} potential listings")
            
            for element in listing_elements[:20]:  # Limit to 20 results
                try:
                    listing = self._extract_listing_data(element)
                    if listing and self._is_valid_car_listing(listing):
                        listings.append(listing)
                except Exception as e:
                    logger.debug(f"Error extracting listing: {e}")
                    continue
                    
        except TimeoutException:
            logger.warning("⏱️ Timeout waiting for listings - page might require login")
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
            mileage_match = re.search(r'([\d,]+)\s*(?:miles?|mi\b|k\s*miles?)', text, re.IGNORECASE)
            mileage = mileage_match.group(1) + " miles" if mileage_match else None
            
            # Get URL
            url = element.get_attribute('href')
            if url and not url.startswith('http'):
                url = f"https://www.facebook.com{url}"
            
            # Extract location (usually near the end)
            location = ""
            for line in reversed(lines):
                if any(city in line for city in ['FL', 'Florida', 'miles', 'mi']):
                    location = line
                    break
            
            return {
                'title': title,
                'price': price,
                'year': year,
                'mileage': mileage,
                'url': url,
                'location': location,
                'found_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.debug(f"Error parsing listing: {e}")
            return None
    
    def _is_valid_car_listing(self, listing):
        """Check if listing is a valid car"""
        text = (listing.get('title', '') + ' ' + listing.get('location', '')).lower()
        
        # Must have price and title
        if not listing.get('price') or not listing.get('title'):
            return False
            
        # Car keywords
        car_indicators = ['car', 'vehicle', 'miles', 'automatic', 'manual',
                         'sedan', 'suv', 'truck', 'van', 'coupe', 'convertible',
                         'hatchback', 'wagon', 'minivan', 'pickup']
        
        # Car brands
        car_brands = ['honda', 'toyota', 'ford', 'chevrolet', 'nissan', 'mazda',
                     'hyundai', 'kia', 'subaru', 'volkswagen', 'bmw', 'mercedes',
                     'audi', 'lexus', 'acura', 'infiniti', 'gmc', 'ram', 'jeep']
        
        # Check if any car indicator or brand is present
        has_indicator = any(indicator in text for indicator in car_indicators)
        has_brand = any(brand in text for brand in car_brands)
        
        return has_indicator or has_brand
    
    def cleanup(self):
        """Close the Selenium driver"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("🧹 Selenium driver closed")
            except:
                pass

# Basic Facebook scraper fallback
class FacebookCarScraper:
    """Basic scraper without Selenium - fallback option"""
    def __init__(self):
        self.base_url = "https://www.facebook.com/marketplace"
        logger.info("Initialized basic Facebook scraper (no Selenium)")
        
    def search_cars(self, **kwargs):
        """Basic search that returns empty results"""
        logger.warning("Basic scraper called - no real results available without Selenium")
        return []

# Wrapper to use either Selenium or basic scraper
class EnhancedFacebookCarScraper:
    def __init__(self, use_selenium=True):
        self.use_selenium = use_selenium and self._check_selenium_available()
        
        if self.use_selenium:
            logger.info("🚀 Using Selenium-enhanced scraper")
            self.scraper = SeleniumFacebookCarScraper(use_selenium=True)
        else:
            logger.info("⚠️ Selenium not available, using basic scraper")
            self.scraper = FacebookCarScraper()
    
    def _check_selenium_available(self):
        """Check if Selenium and Chrome are available"""
        try:
            # First check if we can import selenium
            import selenium
            logger.info("✅ Selenium package is installed")
            
            # Check if USE_SELENIUM environment variable is set
            use_selenium_env = os.getenv("USE_SELENIUM", "true").lower() == "true"
            if not use_selenium_env:
                logger.info("USE_SELENIUM is set to false, skipping Selenium")
                return False
            
            # Try to find Chrome/Chromium binary
            test_scraper = SeleniumFacebookCarScraper(use_selenium=False)
            chrome_binary = test_scraper.find_chrome_binary()
            chromedriver = test_scraper.find_chromedriver()
            
            if not chrome_binary:
                logger.error("Chrome/Chromium binary not found")
                return False
                
            if not chromedriver:
                logger.warning("ChromeDriver not found, will try default")
            
            # Try to actually create a driver instance
            logger.info("Testing Selenium with Chrome...")
            options = webdriver.ChromeOptions()
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            
            if chrome_binary:
                options.binary_location = chrome_binary
            
            # Quick test
            if chromedriver:
                service = Service(chromedriver)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                driver = webdriver.Chrome(options=options)
                
            driver.quit()
            
            logger.info("✅ Selenium test successful!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Selenium check failed: {type(e).__name__}: {str(e)}")
            return False
    
    def search_cars(self, **kwargs):
        """Search for cars using the appropriate scraper"""
        return self.scraper.search_cars(**kwargs)
    
    def cleanup(self):
        """Cleanup resources"""
        if hasattr(self.scraper, 'cleanup'):
            self.scraper.cleanup()

# Main monitoring class that the API expects
class CarSearchMonitor:
    """Main monitoring class that uses the enhanced scraper"""
    def __init__(self, use_selenium=True, use_mock_data=False):
        self.use_mock_data = use_mock_data
        self.use_selenium = use_selenium
        
        logger.info(f"Initializing CarSearchMonitor - Selenium: {use_selenium}, Mock: {use_mock_data}")
        
        if not use_mock_data:
            self.scraper = EnhancedFacebookCarScraper(use_selenium=use_selenium)
        else:
            logger.info("Mock data mode - skipping scraper initialization")
            self.scraper = None
    
    def monitor_car_search(self, search_config):
        """Monitor for new car listings"""
        if self.use_mock_data:
            logger.info("Mock data mode - returning empty list for API to generate mock data")
            return []  # Let the API handle mock data
        
        if not self.scraper:
            logger.warning("No scraper available")
            return []
        
        logger.info(f"Starting car search with config: {search_config}")
        
        results = self.scraper.search_cars(
            make=search_config.get('make'),
            model=search_config.get('model'),
            year_min=search_config.get('year_min'),
            year_max=search_config.get('year_max'),
            price_min=search_config.get('price_min'),
            price_max=search_config.get('price_max'),
            mileage_max=search_config.get('mileage_max'),
            location=search_config.get('location', 'Miami, FL'),
            distance_miles=search_config.get('distance_miles', 25)
        )
        
        logger.info(f"Search completed - found {len(results)} results")
        return results
    
    def cleanup(self):
        """Cleanup resources"""
        if self.scraper:
            self.scraper.cleanup()

# For backwards compatibility
FacebookMarketplaceScraper = CarSearchMonitor
