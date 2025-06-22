import requests
from bs4 import BeautifulSoup
import time
import json
from datetime import datetime
import re
from urllib.parse import urlencode, quote_plus
import random

class FacebookCarScraper:
    def __init__(self):
        self.session = requests.Session()
        
        # Car-specific user agents (people browsing for cars)
        self.user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]
        
        # Location coordinates mapping
        self.location_coords = {
            'Miami, FL': {'lat': 25.7617, 'lng': -80.1918, 'radius': 40233},  # 25 miles in meters
            'Orlando, FL': {'lat': 28.5383, 'lng': -81.3792, 'radius': 40233},
            'Tampa, FL': {'lat': 27.9506, 'lng': -82.4572, 'radius': 40233},
            'Fort Lauderdale, FL': {'lat': 26.1224, 'lng': -80.1373, 'radius': 40233},
            'Jacksonville, FL': {'lat': 30.3322, 'lng': -81.6557, 'radius': 40233},
        }
        
        self.update_headers()
        
    def update_headers(self):
        """Update headers with random user agent"""
        self.session.headers.update({
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        })
        
    def get_location_params(self, location_str, distance_miles=25):
        """Convert location string to Facebook location parameters"""
        # Check if we have coordinates for this location
        if location_str in self.location_coords:
            coords = self.location_coords[location_str]
            return {
                'latitude': coords['lat'],
                'longitude': coords['lng'],
                'radius': int(distance_miles * 1609.34)  # Convert miles to meters
            }
        
        # Try to extract city name for partial matches
        for known_loc, coords in self.location_coords.items():
            if location_str.lower() in known_loc.lower():
                return {
                    'latitude': coords['lat'],
                    'longitude': coords['lng'],
                    'radius': int(distance_miles * 1609.34)
                }
        
        # Default to Miami if location not found
        miami_coords = self.location_coords['Miami, FL']
        return {
            'latitude': miami_coords['lat'],
            'longitude': miami_coords['lng'],
            'radius': int(distance_miles * 1609.34)
        }
        
    def search_cars(self, make=None, model=None, year_min=None, year_max=None,
                   price_min=None, price_max=None, mileage_max=None, location="", distance_miles=25):
        """
        Search Facebook Marketplace specifically for cars
        """
        # Build search query for cars
        query_parts = []
        if make:
            query_parts.append(make)
        if model:
            query_parts.append(model)
        
        query = " ".join(query_parts) if query_parts else "car"
        
        print(f"🚗 Searching for cars: {query}")
        if year_min or year_max:
            print(f"   📅 Year range: {year_min or 'any'} - {year_max or 'current'}")
        if price_min or price_max:
            print(f"   💰 Price range: ${price_min or 0:,} - ${price_max or 999999:,}")
        if mileage_max:
            print(f"   🛣️  Max mileage: {mileage_max:,} miles")
        if location:
            print(f"   📍 Location: {location} (within {distance_miles} miles)")
        
        # Try different car-specific URL approaches with location
        urls_to_try = [
            self.build_car_search_url_v1(query, year_min, year_max, price_min, price_max, location, distance_miles),
            self.build_car_search_url_v2(make, model, year_min, year_max, price_min, price_max, location, distance_miles),
            self.build_vehicle_category_url(query, price_min, price_max, location, distance_miles)
        ]
        
        for i, search_url in enumerate(urls_to_try):
            try:
                print(f"  📡 Trying car search approach {i+1}...")
                print(f"     {search_url[:150]}...")
                
                # Add random delay to look more human
                time.sleep(random.uniform(2, 5))
                
                response = self.session.get(search_url, timeout=15)
                print(f"  📊 Response status: {response.status_code}")
                
                if response.status_code == 200:
                    cars = self.parse_car_listings(response.text)
                    print(f"  ✅ Successfully parsed {len(cars)} car listings")
                    return cars
                elif response.status_code == 429:
                    print("  ⚠️  Rate limited - waiting longer...")
                    time.sleep(60)
                else:
                    print(f"  ❌ Status {response.status_code}: {response.reason}")
                    
            except requests.RequestException as e:
                print(f"  ❌ Request error: {e}")
                continue
                
        print("  🚫 All car search approaches failed")
        return []
    
    def build_car_search_url_v1(self, query, year_min, year_max, price_min, price_max, location, distance_miles):
        """Car-specific search URL with vehicle category and location"""
        search_params = {
            'query': query,
            'category_id': '807311116002614',  # Facebook's vehicle category ID
            'sortBy': 'creation_time_descend',
        }
        
        # Add location parameters
        if location:
            loc_params = self.get_location_params(location, distance_miles)
            search_params.update(loc_params)
        
        if price_max:
            search_params['maxPrice'] = price_max
        if price_min:
            search_params['minPrice'] = price_min
        if year_min:
            search_params['minYear'] = year_min
        if year_max:
            search_params['maxYear'] = year_max
            
        base_url = "https://www.facebook.com/marketplace/search/?"
        return base_url + urlencode(search_params)
    
    def build_car_search_url_v2(self, make, model, year_min, year_max, price_min, price_max, location, distance_miles):
        """Alternative car search URL with location"""
        query = f"{make or ''} {model or ''}".strip() or "vehicle"
        
        search_params = {
            'q': query,
            'category_id': '807311116002614',
            'sortBy': 'best_match',
        }
        
        # Add location parameters
        if location:
            loc_params = self.get_location_params(location, distance_miles)
            search_params.update(loc_params)
        
        if price_max:
            search_params['priceMax'] = price_max
        if price_min:
            search_params['priceMin'] = price_min
            
        base_url = "https://www.facebook.com/marketplace/search/?"
        return base_url + urlencode(search_params)
    
    def build_vehicle_category_url(self, query, price_min, price_max, location, distance_miles):
        """Direct vehicle category browse with location"""
        search_params = {
            'query': query,
            'sortBy': 'creation_time_descend',
        }
        
        # Add location parameters
        if location:
            loc_params = self.get_location_params(location, distance_miles)
            search_params.update(loc_params)
        
        if price_max:
            search_params['maxPrice'] = price_max
        if price_min:
            search_params['minPrice'] = price_min
            
        # Try Miami-specific marketplace URL
        if "Miami" in location:
            base_url = "https://www.facebook.com/marketplace/miami/vehicles/?"
        else:
            base_url = "https://www.facebook.com/marketplace/category/vehicles/?"
            
        return base_url + urlencode(search_params)
    
    def parse_car_listings(self, html_content):
        """
        Parse HTML content specifically for car listings
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        cars = []
        
        print("  🔎 Analyzing car listings...")
        
        # Check if we got blocked
        if "log in" in html_content.lower() or "login" in html_content.lower():
            print("  🚫 Got login page - Facebook is blocking us")
            return []
        
        if "marketplace" not in html_content.lower() and "vehicle" not in html_content.lower():
            print("  🚫 Page doesn't contain marketplace/vehicle content")
            return []
        
        # Car-specific selectors
        car_selectors = [
            'div[data-testid*="marketplace"]',
            'div[data-testid*="vehicle"]',
            'a[href*="/marketplace/item/"]',
            'div[aria-label*="vehicle"]',
            'div[aria-label*="car"]',
        ]
        
        for selector in car_selectors:
            try:
                elements = soup.select(selector)
                print(f"     Found {len(elements)} elements with car selector: {selector}")
                
                if elements:
                    cars.extend(self.extract_car_data_from_elements(elements))
                    
            except Exception as e:
                print(f"     Error with selector {selector}: {e}")
                continue
        
        # Remove duplicates and filter for car-like listings
        unique_cars = []
        seen_listings = set()
        
        for car in cars:
            car_id = f"{car['title']}_{car['price']}"
            if car_id not in seen_listings and self.is_likely_car(car):
                unique_cars.append(car)
                seen_listings.add(car_id)
        
        return unique_cars[:15]  # Limit to 15 results
    
    def extract_car_data_from_elements(self, elements):
        """Extract car-specific data from HTML elements"""
        cars = []
        
        for element in elements[:30]:  # Process more elements for cars
            try:
                text_content = element.get_text() if element else ""
                
                # Look for car price patterns
                price_patterns = [r'\$[\d,]+', r'\$\d+']
                prices = []
                for pattern in price_patterns:
                    prices.extend(re.findall(pattern, text_content))
                
                if prices and len(text_content) > 10:
                    # Extract car details
                    car_data = self.extract_car_details(text_content)
                    
                    if car_data['title'] and len(car_data['title']) > 3:
                        car_data.update({
                            'price': prices[0],
                            'timestamp': datetime.now().isoformat(),
                            'url': self.extract_listing_url(element),
                        })
                        cars.append(car_data)
                        
            except Exception as e:
                continue
                
        return cars
    
    def extract_car_details(self, text):
        """Extract car-specific details from text"""
        # Clean the text
        text = ' '.join(text.split())
        
        # Common car-related patterns
        year_pattern = r'\b(19|20)\d{2}\b'
        mileage_pattern = r'([\d,]+)\s*(miles?|mi|k\s*miles?)'
        
        # Extract year
        year_matches = re.findall(year_pattern, text)
        year = year_matches[0] if year_matches else None
        
        # Extract mileage
        mileage_matches = re.findall(mileage_pattern, text, re.IGNORECASE)
        mileage = mileage_matches[0][0] if mileage_matches else None
        
        # Extract title (remove price and common car terms)
        title = text
        title = re.sub(r'\$[\d,]+', '', title)  # Remove prices
        title = re.sub(r'\b\d+\s*miles?\b', '', title, flags=re.IGNORECASE)  # Remove mileage
        
        # Take relevant words for title
        words = title.split()
        if len(words) > 2:
            # Try to find make/model in first part
            title = ' '.join(words[:10])  # First 10 words
        
        return {
            'title': title.strip(),
            'year': year,
            'mileage': mileage,
            'raw_text': text[:200]  # Keep sample of original text
        }
    
    def is_likely_car(self, listing):
        """Check if listing is likely a car"""
        text = (listing.get('title', '') + ' ' + listing.get('raw_text', '')).lower()
        
        # Car indicators
        car_keywords = [
            'car', 'auto', 'vehicle', 'sedan', 'suv', 'truck', 'coupe', 'wagon',
            'honda', 'toyota', 'ford', 'chevrolet', 'nissan', 'bmw', 'mercedes',
            'audi', 'volkswagen', 'hyundai', 'kia', 'mazda', 'subaru', 'jeep',
            'miles', 'mileage', 'engine', 'transmission', 'automatic', 'manual'
        ]
        
        # Non-car indicators (to filter out)
        non_car_keywords = [
            'house', 'apartment', 'furniture', 'phone', 'computer', 'laptop',
            'clothing', 'shoes', 'toy', 'book', 'game', 'electronics'
        ]
        
        car_score = sum(1 for keyword in car_keywords if keyword in text)
        non_car_score = sum(1 for keyword in non_car_keywords if keyword in text)
        
        return car_score > 0 and car_score > non_car_score
    
    def extract_listing_url(self, element):
        """Extract the URL for a car listing"""
        link = element.find('a', href=True)
        if not link and element.parent:
            link = element.parent.find('a', href=True)
        
        if link:
            href = link['href']
            if '/marketplace/' in href:
                if href.startswith('/'):
                    return f"https://www.facebook.com{href}"
                return href
        return None

class CarSearchMonitor:
    def __init__(self):
        self.scraper = FacebookCarScraper()
        self.seen_cars = set()
        
    def monitor_car_search(self, search_config):
        """
        Monitor a car search and return new listings
        """
        make = search_config.get('make', '')
        model = search_config.get('model', '')
        year_min = search_config.get('year_min')
        year_max = search_config.get('year_max')
        price_min = search_config.get('price_min')
        price_max = search_config.get('price_max')
        mileage_max = search_config.get('mileage_max')
        location = search_config.get('location', '')
        distance_miles = search_config.get('distance_miles', 25)
        
        search_name = f"{make} {model}".strip() or "cars"
        print(f"\n🎯 Monitoring car search: {search_name}")
        
        # Get current car listings
        current_cars = self.scraper.search_cars(
            make=make,
            model=model,
            year_min=year_min,
            year_max=year_max,
            price_min=price_min,
            price_max=price_max,
            mileage_max=mileage_max,
            location=location,
            distance_miles=distance_miles
        )
        
        # Filter out cars we've already seen
        new_cars = []
        for car in current_cars:
            car_id = f"{car['title']}_{car['price']}"
            if car_id not in self.seen_cars:
                self.seen_cars.add(car_id)
                new_cars.append(car)
        
        print(f"   📊 Found {len(current_cars)} total cars, {len(new_cars)} new")
        return new_cars
    
    def continuous_car_monitor(self, search_configs, check_interval=600):
        """
        Continuously monitor car searches (longer intervals for cars)
        """
        print(f"🚀 Starting continuous car monitoring (checking every {check_interval//60} minutes)")
        
        while True:
            for config in search_configs:
                try:
                    new_cars = self.monitor_car_search(config)
                    
                    if new_cars:
                        search_name = f"{config.get('make', '')} {config.get('model', '')}".strip()
                        print(f"\n🚨 Found {len(new_cars)} new cars for '{search_name}':")
                        
                        for car in new_cars:
                            print(f"  🚗 {car['title']} - {car['price']}")
                            if car.get('year'):
                                print(f"     📅 Year: {car['year']}")
                            if car.get('mileage'):
                                print(f"     🛣️  Mileage: {car['mileage']}")
                            if car['url']:
                                print(f"     🔗 {car['url']}")
                        
                        self.send_car_notifications(new_cars, config)
                    else:
                        search_name = f"{config.get('make', '')} {config.get('model', '')}".strip()
                        print(f"   😴 No new cars for '{search_name}'")
                        
                except Exception as e:
                    print(f"❌ Error monitoring car search: {e}")
                
                # Longer delay between car searches
                time.sleep(random.uniform(10, 20))
            
            print(f"\n💤 Waiting {check_interval//60} minutes before next car check...")
            time.sleep(check_interval)
    
    def send_car_notifications(self, cars, search_config):
        """
        Send notifications for new car listings
        """
        print(f"📱 Would send car notifications for {len(cars)} listings")
