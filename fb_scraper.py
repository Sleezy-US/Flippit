import requests
from bs4 import BeautifulSoup
import time
import json
from datetime import datetime
import re
from urllib.parse import urlencode, quote_plus
import random
import os
from fake_useragent import UserAgent

class EnhancedCarSearchMonitor:
    def __init__(self, use_selenium=False, use_mock_data=False):
        self.use_mock_data = use_mock_data
        self.session = requests.Session()
        self.seen_cars = set()
        
        # Initialize user agent rotator
        self.ua = UserAgent()
        
        # Premium user agents that work well with Facebook
        self.user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0'
        ]
        
        self.setup_session()

    def setup_session(self):
        """Setup enhanced session with anti-detection features"""
        # Rotate user agent
        user_agent = random.choice(self.user_agents)
        
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })
        
        # Add realistic session cookies
        self.session.cookies.update({
            'locale': 'en_US',
            'datr': self.generate_datr(),
            'sb': self.generate_sb(),
        })

    def generate_datr(self):
        """Generate realistic datr cookie"""
        import string
        chars = string.ascii_letters + string.digits + '-_'
        return ''.join(random.choice(chars) for _ in range(24))

    def generate_sb(self):
        """Generate realistic sb cookie"""
        import string
        chars = string.ascii_letters + string.digits + '-_'
        return ''.join(random.choice(chars) for _ in range(24))

    def human_delay(self, min_seconds=2, max_seconds=5):
        """Add human-like delays"""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    def monitor_car_search(self, search_config):
        """Enhanced car search monitoring"""
        make = search_config.get('make', '')
        model = search_config.get('model', '')
        
        search_name = f"{make} {model}".strip() or "cars"
        print(f"\n🎯 Enhanced cloud monitoring: {search_name}")
        
        cars = []
        
        # Multi-source approach
        sources = [
            self.facebook_marketplace_search,
            self.craigslist_search,
            self.autotrader_search,
            self.cars_com_search
        ]
        
        for source_func in sources:
            try:
                source_cars = source_func(search_config)
                if source_cars:
                    cars.extend(source_cars)
                    print(f"  ✅ {source_func.__name__}: Found {len(source_cars)} cars")
                else:
                    print(f"  ⚠️ {source_func.__name__}: No results")
                
                # Don't overwhelm servers
                self.human_delay(3, 6)
                
            except Exception as e:
                print(f"  ❌ {source_func.__name__} failed: {e}")
                continue
        
        # Filter duplicates and new cars
        new_cars = self.filter_new_cars(cars)
        
        print(f"   📊 Total: {len(cars)} cars, {len(new_cars)} new")
        return new_cars

    def facebook_marketplace_search(self, search_config):
        """Enhanced Facebook Marketplace search"""
        try:
            make = search_config.get('make', '')
            model = search_config.get('model', '')
            price_min = search_config.get('price_min')
            price_max = search_config.get('price_max')
            location = search_config.get('location', '')
            
            query = f"{make} {model}".strip() or "car"
            
            # Try multiple Facebook URL patterns
            urls = [
                self.build_facebook_url_v1(query, price_min, price_max, location),
                self.build_facebook_url_v2(query, price_min, price_max, location),
                self.build_facebook_url_v3(make, model, price_min, price_max, location)
            ]
            
            for i, url in enumerate(urls):
                try:
                    print(f"    🌐 Facebook attempt {i+1}...")
                    
                    # Refresh session for each attempt
                    if i > 0:
                        self.setup_session()
                    
                    self.human_delay(2, 4)
                    
                    response = self.session.get(url, timeout=15)
                    
                    if response.status_code == 200:
                        cars = self.parse_facebook_response(response.text)
                        if cars:
                            return cars
                    elif response.status_code == 429:
                        print("    ⏳ Rate limited, waiting...")
                        time.sleep(30)
                    else:
                        print(f"    ❌ Status {response.status_code}")
                        
                except requests.RequestException as e:
                    print(f"    ❌ Request failed: {e}")
                    continue
            
            return []
            
        except Exception as e:
            print(f"Facebook search error: {e}")
            return []

    def build_facebook_url_v1(self, query, price_min, price_max, location):
        """Facebook Marketplace URL - Version 1"""
        params = {
            'query': query,
            'sortBy': 'creation_time_descend',
            'category': 'vehicles',
            'exact': 'false'
        }
        
        if price_min:
            params['minPrice'] = price_min
        if price_max:
            params['maxPrice'] = price_max
        if location:
            params['location'] = location
            
        return f"https://www.facebook.com/marketplace/search?{urlencode(params)}"

    def build_facebook_url_v2(self, query, price_min, price_max, location):
        """Facebook Marketplace URL - Version 2"""
        params = {
            'q': query,
            'sortBy': 'best_match',
            'category': 'vehicles'
        }
        
        if price_min:
            params['priceMin'] = price_min
        if price_max:
            params['priceMax'] = price_max
            
        return f"https://www.facebook.com/marketplace/search?{urlencode(params)}"

    def build_facebook_url_v3(self, make, model, price_min, price_max, location):
        """Facebook Marketplace URL - Version 3 (Direct category)"""
        params = {
            'query': f"{make} {model}".strip(),
            'sortBy': 'creation_time_descend'
        }
        
        if price_max:
            params['maxPrice'] = price_max
        if price_min:
            params['minPrice'] = price_min
            
        return f"https://www.facebook.com/marketplace/category/vehicles?{urlencode(params)}"

    def parse_facebook_response(self, html_content):
        """Parse Facebook HTML response"""
        cars = []
        
        # Check for blocking
        if any(block_indicator in html_content.lower() for block_indicator in
               ['log in', 'login', 'security check', 'blocked']):
            print("    🚫 Facebook blocking detected")
            return []
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Multiple selector strategies
        selectors = [
            'a[href*="/marketplace/item/"]',
            '[data-testid*="marketplace"]',
            '[role="article"]',
            '.marketplace-item',
            '[aria-label*="$"]'
        ]
        
        all_elements = []
        for selector in selectors:
            elements = soup.select(selector)
            all_elements.extend(elements)
        
        print(f"    🔍 Found {len(all_elements)} potential elements")
        
        # Extract car data
        for element in all_elements[:25]:  # Process up to 25 elements
            try:
                car_data = self.extract_facebook_car_data(element)
                if car_data and self.is_valid_car(car_data):
                    cars.append(car_data)
            except Exception:
                continue
        
        return self.deduplicate_cars(cars)

    def extract_facebook_car_data(self, element):
        """Extract car data from Facebook element"""
        try:
            text = element.get_text() if element else ""
            
            # Must have price
            price_match = re.search(r'\$[\d,]+', text)
            if not price_match:
                return None
            
            price = price_match.group()
            
            # Extract URL
            url = element.get('href') if element.name == 'a' else None
            if not url:
                link = element.find('a', href=True)
                url = link['href'] if link else None
            
            if url and url.startswith('/'):
                url = f"https://www.facebook.com{url}"
            
            # Clean title
            title = text.replace(price, '').strip()
            title = re.sub(r'\d+\s*miles?', '', title, flags=re.IGNORECASE).strip()
            title = ' '.join(title.split()[:15])  # Limit words
            
            # Extract year
            year_match = re.search(r'\b(19|20)\d{2}\b', text)
            year = year_match.group() if year_match else None
            
            # Extract mileage
            mileage_match = re.search(r'([\d,]+)\s*miles?', text, re.IGNORECASE)
            mileage = mileage_match.group() if mileage_match else None
            
            if len(title) > 5 and price:
                return {
                    'title': title,
                    'price': price,
                    'year': year,
                    'mileage': mileage,
                    'url': url,
                    'source': 'facebook',
                    'scraped_at': datetime.now().isoformat()
                }
                
        except Exception:
            pass
        
        return None

    def craigslist_search(self, search_config):
        """Search Craigslist for cars"""
        try:
            make = search_config.get('make', '')
            model = search_config.get('model', '')
            price_max = search_config.get('price_max', 50000)
            location = search_config.get('location', '')
            
            query = f"{make} {model}".strip()
            if not query:
                return []
            
            # Map location to Craigslist city
            city = self.get_craigslist_city(location)
            
            params = {
                'query': query,
                'sort': 'date',
                'auto_make_model': query
            }
            
            if price_max:
                params['max_price'] = price_max
            
            url = f"https://{city}.craigslist.org/search/cta?{urlencode(params)}"
            
            # Use different headers for Craigslist
            headers = self.session.headers.copy()
            headers['User-Agent'] = random.choice(self.user_agents)
            
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                return self.parse_craigslist_response(response.text)
            
        except Exception as e:
            print(f"Craigslist error: {e}")
        
        return []

    def get_craigslist_city(self, location):
        """Map location to Craigslist subdomain"""
        location_map = {
            'cape coral': 'swfl',
            'fort myers': 'swfl',
            'naples': 'swfl',
            'miami': 'miami',
            'tampa': 'tampa',
            'orlando': 'orlando',
            'jacksonville': 'jacksonville'
        }
        
        if location:
            location_lower = location.lower()
            for city, subdomain in location_map.items():
                if city in location_lower:
                    return subdomain
        
        return 'swfl'  # Default to Southwest Florida

    def parse_craigslist_response(self, html_content):
        """Parse Craigslist response"""
        soup = BeautifulSoup(html_content, 'html.parser')
        cars = []
        
        try:
            listings = soup.find_all('li', class_='result-row')
            
            for listing in listings[:10]:
                try:
                    title_element = listing.find('a', class_='result-title')
                    if not title_element:
                        continue
                    
                    title = title_element.get_text().strip()
                    url = title_element.get('href')
                    
                    if url and url.startswith('/'):
                        url = f"https://swfl.craigslist.org{url}"
                    
                    price_element = listing.find('span', class_='result-price')
                    price = price_element.get_text().strip() if price_element else None
                    
                    year_match = re.search(r'\b(19|20)\d{2}\b', title)
                    year = year_match.group() if year_match else None
                    
                    if title and price:
                        cars.append({
                            'title': title,
                            'price': price,
                            'year': year,
                            'url': url,
                            'source': 'craigslist',
                            'scraped_at': datetime.now().isoformat()
                        })
                        
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"Craigslist parsing error: {e}")
        
        return cars

    def autotrader_search(self, search_config):
        """Search AutoTrader (simplified)"""
        # Placeholder for AutoTrader integration
        # AutoTrader has anti-bot measures, so this would need more work
        return []

    def cars_com_search(self, search_config):
        """Search Cars.com (simplified)"""
        # Placeholder for Cars.com integration
        return []

    def is_valid_car(self, car_data):
        """Validate if listing is actually a car"""
        title = car_data.get('title', '').lower()
        
        car_keywords = [
            'car', 'auto', 'vehicle', 'sedan', 'suv', 'truck', 'coupe',
            'honda', 'toyota', 'ford', 'chevrolet', 'nissan', 'bmw',
            'mercedes', 'audi', 'mazda', 'hyundai', 'kia', 'subaru'
        ]
        
        non_car_keywords = [
            'house', 'apartment', 'phone', 'laptop', 'furniture', 'clothing'
        ]
        
        car_score = sum(1 for keyword in car_keywords if keyword in title)
        non_car_score = sum(1 for keyword in non_car_keywords if keyword in title)
        
        return car_score > 0 and car_score >= non_car_score

    def filter_new_cars(self, cars):
        """Filter out cars we've already seen"""
        new_cars = []
        
        for car in cars:
            car_id = f"{car.get('title', '')}_{car.get('price', '')}"
            if car_id not in self.seen_cars:
                self.seen_cars.add(car_id)
                new_cars.append(car)
        
        return new_cars

    def deduplicate_cars(self, cars):
        """Remove duplicate cars from list"""
        seen = set()
        unique_cars = []
        
        for car in cars:
            car_id = f"{car.get('title', '')}_{car.get('price', '')}"
            if car_id not in seen:
                seen.add(car_id)
                unique_cars.append(car)
        
        return unique_cars

# Test the enhanced scraper
if __name__ == "__main__":
    monitor = EnhancedCarSearchMonitor()
    
    test_search = {
        'make': 'Honda',
        'model': 'Civic',
        'price_max': 25000,
        'location': 'Cape Coral, FL'
    }
    
    print("🧪 Testing cloud-optimized scraper...")
    results = monitor.monitor_car_search(test_search)
    
    print(f"\n📊 Results: {len(results)} cars found")
    for i, car in enumerate(results[:5], 1):
        print(f"  {i}. {car['title']} - {car['price']} ({car['source']})")
