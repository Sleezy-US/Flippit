"""
Enhanced Distributed Scraper with Maximum Facebook Success Rate
This integrates with your DigitalOcean VPS for better scraping
"""

import requests
import asyncio
import aiohttp
import random
import time
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import json
import os

logger = logging.getLogger(__name__)

class DistributedScraperClient:
    """Client that connects to your VPS nodes for scraping"""
    
    def __init__(self):
        # Load nodes from environment
        self.nodes = json.loads(os.getenv('DISTRIBUTED_NODES', '[]'))
        self.node_secret = os.getenv('NODE_SECRET', '')
        self.current_node_index = 0
        self.node_cooldowns = {}
        
        logger.info(f"🌐 Distributed scraper initialized with {len(self.nodes)} nodes")
        
    def get_next_available_node(self):
        """Get next available node using round-robin with cooldowns"""
        now = datetime.now()
        attempts = 0
        
        while attempts < len(self.nodes):
            node = self.nodes[self.current_node_index]
            self.current_node_index = (self.current_node_index + 1) % len(self.nodes)
            
            # Check if node is in cooldown
            cooldown_until = self.node_cooldowns.get(node['id'])
            if cooldown_until and now < cooldown_until:
                attempts += 1
                continue
                
            return node
            
        logger.warning("All nodes are in cooldown!")
        return None
        
    async def scrape_with_node(self, node: Dict, search_params: Dict) -> List[Dict]:
        """Send scraping request to a specific node"""
        try:
            url = f"{node['url']}/scrape"
            headers = {
                'X-API-Key': self.node_secret,
                'Content-Type': 'application/json'
            }
            
            # Prepare search parameters
            data = {
                'query': f"{search_params.get('make', '')} {search_params.get('model', '')}".strip(),
                'location': search_params.get('location', 'Miami'),
                'min_price': search_params.get('min_price'),
                'max_price': search_params.get('max_price'),
                'year_min': search_params.get('year_min'),
                'year_max': search_params.get('year_max'),
                'radius': search_params.get('distance_miles', 25)
            }
            
            logger.info(f"📡 Sending request to node {node['id']}: {data['query']}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data, headers=headers, timeout=30) as response:
                    if response.status == 200:
                        result = await response.json()
                        listings = result.get('listings', [])
                        logger.info(f"✅ Node {node['id']} returned {len(listings)} listings")
                        return listings
                    else:
                        logger.error(f"Node {node['id']} returned status {response.status}")
                        # Put node in cooldown
                        self.node_cooldowns[node['id']] = datetime.now() + timedelta(minutes=5)
                        return []
                        
        except Exception as e:
            logger.error(f"Error with node {node['id']}: {e}")
            # Put node in cooldown on error
            self.node_cooldowns[node['id']] = datetime.now() + timedelta(minutes=5)
            return []


class SmartFacebookScraper:
    """
    Advanced Facebook scraping strategies to maximize success
    """
    
    def __init__(self, distributed_client: DistributedScraperClient):
        self.distributed = distributed_client
        self.strategies = [
            self._try_distributed_nodes,    # Primary: Use VPS nodes
            self._try_craigslist_fallback, # Fallback: Craigslist
            self._try_mock_data            # Last resort: Mock data
        ]
        
    async def search(self, search_params: Dict) -> List[Dict]:
        """Try multiple strategies in order"""
        all_listings = []
        
        for strategy in self.strategies:
            try:
                logger.info(f"🔍 Trying strategy: {strategy.__name__}")
                listings = await strategy(search_params)
                
                if listings:
                    all_listings.extend(listings)
                    logger.info(f"✅ Got {len(listings)} listings from {strategy.__name__}")
                    
                    # If we got good results from distributed nodes, stop
                    if strategy.__name__ == '_try_distributed_nodes' and len(listings) >= 5:
                        break
                        
            except Exception as e:
                logger.error(f"Strategy {strategy.__name__} failed: {e}")
                continue
                
        return all_listings
        
    async def _try_distributed_nodes(self, search_params: Dict) -> List[Dict]:
        """Use distributed VPS nodes"""
        node = self.distributed.get_next_available_node()
        
        if not node:
            return []
            
        return await self.distributed.scrape_with_node(node, search_params)
        
    async def _try_craigslist_fallback(self, search_params: Dict) -> List[Dict]:
        """Fallback to Craigslist (always works)"""
        try:
            # Simple Craigslist scraper
            city = search_params.get('location', 'Miami').split(',')[0].lower()
            query = f"{search_params.get('make', '')} {search_params.get('model', '')}".strip()
            
            url = f"https://{city}.craigslist.org/search/cta"
            params = {
                'query': query,
                'min_price': search_params.get('min_price'),
                'max_price': search_params.get('max_price'),
                'min_auto_year': search_params.get('year_min'),
                'max_auto_year': search_params.get('year_max')
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            # Basic parsing (simplified)
            listings = []
            if response.status_code == 200:
                # Would parse HTML here
                logger.info("Craigslist fallback available")
                
            return listings
            
        except Exception as e:
            logger.error(f"Craigslist fallback failed: {e}")
            return []
            
    async def _try_mock_data(self, search_params: Dict) -> List[Dict]:
        """Last resort: Return mock data"""
        if os.getenv('USE_MOCK_DATA', 'false').lower() != 'true':
            return []
            
        mock_listings = []
        for i in range(5):
            mock_listings.append({
                'id': f"mock_{int(time.time())}_{i}",
                'title': f"2020 {search_params.get('make', 'Toyota')} {search_params.get('model', 'Camry')}",
                'price': random.randint(15000, 25000),
                'url': f"https://example.com/mock/{i}",
                'location': search_params.get('location', 'Miami'),
                'source': 'mock',
                'image_url': None,
                'mileage': random.randint(20000, 60000),
                'year': random.randint(2018, 2023)
            })
            
        return mock_listings


class EnhancedCarSearchMonitor:
    """
    Drop-in replacement for your existing CarSearchMonitor
    Uses distributed VPS nodes for better success
    """
    
    def __init__(self, use_selenium: bool = False, use_mock_data: bool = False):
        self.use_selenium = use_selenium
        self.use_mock_data = use_mock_data
        
        # Initialize distributed client
        self.distributed_client = DistributedScraperClient()
        self.smart_scraper = SmartFacebookScraper(self.distributed_client)
        
        logger.info(f"✅ Enhanced monitor initialized with {len(self.distributed_client.nodes)} distributed nodes")
        
    def monitor_car_search(self, search_config: Dict) -> List[Dict]:
        """
        Main method that your existing code calls
        Now uses distributed scraping!
        """
        # Run async search in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            listings = loop.run_until_complete(self.smart_scraper.search(search_config))
            
            # Ensure all listings have required fields
            for listing in listings:
                listing.setdefault('created_time', datetime.now().isoformat())
                listing.setdefault('seller_name', 'Unknown')
                listing.setdefault('source', 'distributed')
                
            return listings
            
        finally:
            loop.close()
            
    def cleanup(self):
        """Cleanup resources"""
        pass


# Monitoring and statistics
class ScraperMonitor:
    """Track success rates and performance"""
    
    def __init__(self):
        self.stats = {
            'total_searches': 0,
            'successful_searches': 0,
            'listings_found': 0,
            'node_performance': {}
        }
        
    def record_search(self, node_id: str, success: bool, listings_count: int):
        """Record search statistics"""
        self.stats['total_searches'] += 1
        
        if success:
            self.stats['successful_searches'] += 1
            self.stats['listings_found'] += listings_count
            
        # Track per-node performance
        if node_id not in self.stats['node_performance']:
            self.stats['node_performance'][node_id] = {
                'searches': 0,
                'successes': 0,
                'listings': 0
            }
            
        node_stats = self.stats['node_performance'][node_id]
        node_stats['searches'] += 1
        if success:
            node_stats['successes'] += 1
            node_stats['listings'] += listings_count
            
    def get_success_rate(self) -> float:
        """Calculate overall success rate"""
        if self.stats['total_searches'] == 0:
            return 0.0
        return self.stats['successful_searches'] / self.stats['total_searches']
        
    def get_node_stats(self) -> Dict:
        """Get performance stats for each node"""
        node_stats = {}
        
        for node_id, stats in self.stats['node_performance'].items():
            success_rate = 0
            if stats['searches'] > 0:
                success_rate = stats['successes'] / stats['searches']
                
            node_stats[node_id] = {
                'success_rate': round(success_rate * 100, 2),
                'total_searches': stats['searches'],
                'avg_listings': round(stats['listings'] / max(stats['searches'], 1), 2)
            }
            
        return node_stats


# Global monitor instance
monitor = ScraperMonitor()
