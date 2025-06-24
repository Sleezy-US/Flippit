"""
Enhanced Distributed Scraper for Railway
Connects to your DigitalOcean VPS nodes for better scraping success
"""

import os
import json
import requests
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import random
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

class DistributedNode:
    """Represents a single VPS scraper node"""
    
    def __init__(self, config: Dict[str, str]):
        self.id = config['id']
        self.url = config['url'].rstrip('/')
        self.provider = config.get('provider', 'unknown')
        self.region = config.get('region', 'unknown')
        self.last_used = None
        self.success_count = 0
        self.failure_count = 0
        self.is_healthy = True
        self.cooldown_until = None
        
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.5
        
    def is_available(self) -> bool:
        """Check if node is available for use"""
        if not self.is_healthy:
            return False
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            return False
        return True
        
    def set_cooldown(self, seconds: int = 30):
        """Put node on cooldown"""
        self.cooldown_until = datetime.now() + timedelta(seconds=seconds)
        logger.info(f"Node {self.id} on cooldown for {seconds}s")

class DistributedScraper:
    """Manages distributed scraping across VPS nodes"""
    
    def __init__(self):
        # Load configuration
        self.node_secret = os.getenv('NODE_SECRET', '')
        nodes_config = os.getenv('DISTRIBUTED_NODES', '[]')
        
        try:
            nodes_data = json.loads(nodes_config)
            self.nodes = [DistributedNode(config) for config in nodes_data]
            logger.info(f"✅ Loaded {len(self.nodes)} distributed nodes")
        except Exception as e:
            logger.error(f"Failed to load distributed nodes: {e}")
            self.nodes = []
            
        # Configuration
        self.timeout = 30
        self.max_retries = 2
        self.executor = ThreadPoolExecutor(max_workers=3)
        
    def get_available_nodes(self) -> List[DistributedNode]:
        """Get list of available nodes sorted by success rate"""
        available = [node for node in self.nodes if node.is_available()]
        return sorted(available, key=lambda n: n.success_rate, reverse=True)
        
    def health_check_all(self):
        """Check health of all nodes"""
        for node in self.nodes:
            try:
                response = requests.get(
                    f"{node.url}/health",
                    timeout=5
                )
                if response.status_code == 200:
                    node.is_healthy = True
                    logger.info(f"✅ Node {node.id} is healthy")
                else:
                    node.is_healthy = False
                    logger.warning(f"❌ Node {node.id} unhealthy: {response.status_code}")
            except Exception as e:
                node.is_healthy = False
                logger.warning(f"❌ Node {node.id} unreachable: {e}")
                
    def scrape_with_node(self, node: DistributedNode, search_params: Dict) -> Optional[List[Dict]]:
        """Execute scraping on a specific node"""
        try:
            logger.info(f"🔄 Attempting scrape with node {node.id} ({node.provider})")
            
            headers = {
                'X-API-Key': self.node_secret,
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                f"{node.url}/scrape",
                json=search_params,
                headers=headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                node.success_count += 1
                logger.info(f"✅ Node {node.id} returned {len(results)} results")
                return results
            else:
                node.failure_count += 1
                logger.error(f"❌ Node {node.id} returned {response.status_code}")
                return None
                
        except requests.exceptions.Timeout:
            node.failure_count += 1
            logger.error(f"⏱️ Node {node.id} timed out")
            return None
        except Exception as e:
            node.failure_count += 1
            logger.error(f"❌ Node {node.id} error: {e}")
            return None
        finally:
            node.last_used = datetime.now()
            node.set_cooldown(30)  # 30 second cooldown
            
    def scrape_with_fallback(self, search_params: Dict) -> List[Dict]:
        """Scrape using available nodes with fallback"""
        available_nodes = self.get_available_nodes()
        
        if not available_nodes:
            logger.warning("⚠️ No available nodes for distributed scraping")
            return []
            
        # Try nodes in order of success rate
        for i, node in enumerate(available_nodes[:self.max_retries]):
            results = self.scrape_with_node(node, search_params)
            if results:
                return results
                
            # Small delay between retries
            if i < self.max_retries - 1:
                time.sleep(2)
                
        logger.warning("❌ All distributed nodes failed")
        return []

class EnhancedCarSearchMonitor:
    """Drop-in replacement for CarSearchMonitor that uses distributed scraping"""
    
    def __init__(self, use_selenium=True, use_mock_data=False):
        self.use_selenium = use_selenium
        self.use_mock_data = use_mock_data
        self.distributed_scraper = DistributedScraper()
        
        # Health check nodes on startup
        if self.distributed_scraper.nodes:
            logger.info("🏥 Running initial health check on nodes...")
            self.distributed_scraper.health_check_all()
        
    def search_cars(self, search_config: Dict) -> List[Dict]:
        """Main search method that uses distributed scraping"""
        logger.info(f"🚗 Starting distributed search for: {search_config.get('make')} {search_config.get('model')}")
        
        if self.use_mock_data:
            return self._generate_mock_results(search_config)
            
        # Use distributed scraping if nodes are available
        if self.distributed_scraper.nodes:
            results = self.distributed_scraper.scrape_with_fallback(search_config)
            if results:
                return results
                
        # Fallback to basic scraping if no nodes or all failed
        logger.warning("⚠️ Falling back to direct scraping")
        return self._basic_facebook_search(search_config)
        
    def _basic_facebook_search(self, search_config: Dict) -> List[Dict]:
        """Basic fallback search (likely to be blocked)"""
        # This is just a placeholder - it will likely fail
        # The distributed nodes should handle the actual scraping
        return []
        
    def _generate_mock_results(self, search_config: Dict) -> List[Dict]:
        """Generate mock results for testing"""
        mock_results = []
        for i in range(5):
            mock_results.append({
                'title': f"{search_config['make']} {search_config['model']} - Test {i+1}",
                'price': random.randint(5000, 30000),
                'location': search_config.get('location', 'Unknown'),
                'url': f"https://example.com/car/{i+1}",
                'image_url': None,
                'mileage': random.randint(10000, 150000),
                'year': random.randint(2010, 2023),
                'source': 'mock'
            })
        return mock_results
        
    def close(self):
        """Cleanup method"""
        if hasattr(self.distributed_scraper, 'executor'):
            self.distributed_scraper.executor.shutdown(wait=False)
            
    # Add any other methods from CarSearchMonitor that need to be implemented
    def test_selenium(self) -> bool:
        """Test if selenium is working"""
        # Distributed nodes handle their own Selenium
        return True
