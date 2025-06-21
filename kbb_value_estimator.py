import requests
from bs4 import BeautifulSoup
import re
from typing import Dict, Optional, Tuple
import json
from datetime import datetime

class KBBValueEstimator:
    """
    Estimates car values using KBB-style algorithms and market data.
    NOTE: This provides ESTIMATES ONLY - not official KBB values.
    """
    
    def __init__(self):
        # Base depreciation rates per year (approximate)
        self.depreciation_rates = {
            1: 0.20,   # 20% first year
            2: 0.15,   # 15% second year
            3: 0.10,   # 10% third year
            4: 0.08,   # 8% fourth year
            5: 0.07,   # 7% fifth year and beyond
        }
        
        # Mileage adjustment (per 1000 miles over/under average)
        self.mileage_adjustment_rate = 0.005  # 0.5% per 1000 miles
        self.average_miles_per_year = 12000
        
        # Condition multipliers
        self.condition_multipliers = {
            'excellent': 1.10,
            'very_good': 1.05,
            'good': 1.00,
            'fair': 0.90,
            'poor': 0.75
        }
        
        # Market-based starting prices (2024 models)
        self.base_msrp = {
            # Popular models with approximate MSRP
            'honda': {
                'civic': 25000,
                'accord': 28000,
                'cr-v': 30000,
                'pilot': 40000,
                'odyssey': 38000,
                'hr-v': 25000,
                'ridgeline': 40000
            },
            'toyota': {
                'corolla': 24000,
                'camry': 27000,
                'rav4': 30000,
                'highlander': 38000,
                'tacoma': 32000,
                'tundra': 40000,
                'prius': 28000,
                'sienna': 37000
            },
            'ford': {
                'mustang': 32000,
                'f-150': 38000,
                'explorer': 38000,
                'escape': 30000,
                'edge': 35000,
                'ranger': 30000,
                'expedition': 55000
            },
            'chevrolet': {
                'malibu': 26000,
                'camaro': 28000,
                'silverado': 38000,
                'equinox': 28000,
                'traverse': 35000,
                'tahoe': 55000,
                'colorado': 30000
            },
            'nissan': {
                'altima': 26000,
                'sentra': 21000,
                'rogue': 29000,
                'pathfinder': 36000,
                'frontier': 30000,
                'maxima': 38000,
                'murano': 34000
            }
        }
    
    def estimate_value(self, make: str, model: str, year: int,
                      mileage: Optional[int] = None,
                      condition: str = 'good',
                      zip_code: str = None) -> Dict:
        """
        Estimate car value based on make, model, year, mileage, and condition.
        Returns estimated values and deal scoring information.
        """
        
        make_lower = make.lower()
        model_lower = model.lower()
        current_year = datetime.now().year
        car_age = current_year - year
        
        # Get base MSRP
        base_price = self._get_base_price(make_lower, model_lower, year)
        
        # Apply depreciation
        depreciated_value = self._apply_depreciation(base_price, car_age)
        
        # Apply mileage adjustment
        if mileage:
            expected_mileage = car_age * self.average_miles_per_year
            mileage_diff = mileage - expected_mileage
            mileage_adjustment = (mileage_diff / 1000) * self.mileage_adjustment_rate
            depreciated_value *= (1 - mileage_adjustment)
        
        # Apply condition adjustment
        condition_mult = self.condition_multipliers.get(condition, 1.0)
        
        # Calculate different values (like KBB categories)
        values = {
            'trade_in': int(depreciated_value * condition_mult * 0.85),
            'private_party': int(depreciated_value * condition_mult * 1.00),
            'dealer_retail': int(depreciated_value * condition_mult * 1.15),
            'certified_preowned': int(depreciated_value * condition_mult * 1.20)
        }
        
        # Add market insights
        market_insights = self._get_market_insights(make_lower, model_lower, car_age)
        
        return {
            'values': values,
            'confidence': self._calculate_confidence(make_lower, model_lower),
            'market_insights': market_insights,
            'disclaimer': "These are ESTIMATES based on market analysis, NOT official KBB values. Actual values may vary significantly based on condition, location, and market demand.",
            'factors_considered': {
                'depreciation': f"{car_age} years",
                'mileage': f"{mileage:,} miles" if mileage else "Not specified",
                'condition': condition,
                'base_msrp': f"${base_price:,}"
            }
        }
    
    def _get_base_price(self, make: str, model: str, year: int) -> float:
        """Get base MSRP for the vehicle"""
        # Check if we have the make/model in our database
        if make in self.base_msrp and model in self.base_msrp[make]:
            base = self.base_msrp[make][model]
            
            # Adjust for model year (newer models typically cost more)
            current_year = datetime.now().year
            year_diff = current_year - year
            
            # Assume 2% price increase per year for new models
            if year > 2020:
                inflation_adjustment = 0.02 * (2024 - year)
                base = base * (1 - inflation_adjustment)
            
            return base
        
        # Default estimates based on make reputation
        default_prices = {
            'honda': 28000,
            'toyota': 29000,
            'ford': 32000,
            'chevrolet': 31000,
            'nissan': 27000,
            'mazda': 26000,
            'hyundai': 25000,
            'kia': 24000,
            'subaru': 28000,
            'volkswagen': 30000,
            'bmw': 45000,
            'mercedes': 50000,
            'audi': 45000,
            'lexus': 45000,
            'acura': 38000,
            'infiniti': 40000
        }
        
        return default_prices.get(make, 30000)
    
    def _apply_depreciation(self, base_price: float, age: int) -> float:
        """Apply depreciation based on age"""
        value = base_price
        
        for year in range(1, age + 1):
            if year <= 5:
                rate = self.depreciation_rates[year]
            else:
                rate = self.depreciation_rates[5]  # Use year 5 rate for older cars
            
            value *= (1 - rate)
        
        # Floor at 10% of original value
        return max(value, base_price * 0.10)
    
    def _calculate_confidence(self, make: str, model: str) -> str:
        """Calculate confidence level of the estimate"""
        # High confidence for popular makes/models we have data for
        if make in self.base_msrp and model in self.base_msrp.get(make, {}):
            return "high"
        elif make in self.base_msrp:
            return "medium"
        else:
            return "low"
    
    def _get_market_insights(self, make: str, model: str, age: int) -> Dict:
        """Provide market insights for the vehicle"""
        insights = {
            'demand': 'average',
            'depreciation_rate': 'normal',
            'best_time_to_buy': 'now',
            'notes': []
        }
        
        # Popular reliable brands
        if make in ['honda', 'toyota', 'mazda']:
            insights['demand'] = 'high'
            insights['depreciation_rate'] = 'slower'
            insights['notes'].append("This brand typically holds value well")
        
        # Luxury brands
        elif make in ['bmw', 'mercedes', 'audi']:
            insights['depreciation_rate'] = 'faster'
            insights['notes'].append("Luxury vehicles typically depreciate faster")
            
        # Age-based insights
        if age <= 3:
            insights['notes'].append("Still under typical warranty period")
        elif age >= 7:
            insights['notes'].append("Major depreciation has already occurred")
            insights['best_time_to_buy'] = 'good value range'
        
        return insights
    
    def calculate_deal_score(self, listing_price: float, estimated_value: Dict) -> Dict:
        """
        Calculate how good of a deal this listing is.
        Returns a score from 0-100 and deal rating.
        """
        private_party_value = estimated_value['values']['private_party']
        
        # Calculate percentage difference
        price_diff = private_party_value - listing_price
        price_diff_percent = (price_diff / private_party_value) * 100
        
        # Score calculation (0-100)
        # Below market = good deal
        # Above market = bad deal
        if price_diff_percent >= 20:
            score = 95  # Excellent deal
        elif price_diff_percent >= 10:
            score = 85  # Great deal
        elif price_diff_percent >= 5:
            score = 75  # Good deal
        elif price_diff_percent >= 0:
            score = 65  # Fair deal
        elif price_diff_percent >= -5:
            score = 50  # Market price
        elif price_diff_percent >= -10:
            score = 35  # Slightly overpriced
        else:
            score = 20  # Overpriced
        
        # Determine rating
        if score >= 85:
            rating = "🔥 HOT DEAL"
            color = "#FF4500"  # Red-orange
        elif score >= 75:
            rating = "✨ GREAT DEAL"
            color = "#32CD32"  # Lime green
        elif score >= 65:
            rating = "👍 GOOD DEAL"
            color = "#228B22"  # Forest green
        elif score >= 50:
            rating = "✓ FAIR PRICE"
            color = "#4169E1"  # Royal blue
        else:
            rating = "⚠️ OVERPRICED"
            color = "#DC143C"  # Crimson
        
        return {
            'score': score,
            'rating': rating,
            'color': color,
            'price_difference': int(price_diff),
            'price_difference_percent': round(price_diff_percent, 1),
            'listing_price': listing_price,
            'estimated_value': private_party_value,
            'below_market': price_diff > 0,
            'savings_potential': max(0, int(price_diff)),
            'analysis': self._get_deal_analysis(score, price_diff_percent)
        }
    
    def _get_deal_analysis(self, score: int, price_diff_percent: float) -> str:
        """Provide detailed analysis of the deal"""
        if score >= 85:
            return f"This vehicle is priced {abs(price_diff_percent):.1f}% below market value. Act fast - deals like this don't last long!"
        elif score >= 75:
            return f"Priced {abs(price_diff_percent):.1f}% below typical market value. This is a solid opportunity for a good purchase."
        elif score >= 65:
            return f"This is reasonably priced, about {abs(price_diff_percent):.1f}% below market. Room for some negotiation."
        elif score >= 50:
            return "Priced at fair market value. This is what most similar vehicles sell for."
        else:
            return f"This appears to be {abs(price_diff_percent):.1f}% above market value. Consider negotiating or looking at other options."


# Integration with your existing code
def enhance_car_listing_with_values(listing: Dict, estimator: KBBValueEstimator) -> Dict:
    """
    Enhance a car listing with estimated values and deal scoring.
    """
    # Extract car details from listing
    year = None
    if listing.get('year'):
        try:
            year = int(listing['year'])
        except:
            year = None
    
    mileage = None
    if listing.get('mileage'):
        mileage_str = listing['mileage'].replace(',', '').replace(' miles', '').replace('miles', '')
        try:
            mileage = int(mileage_str)
        except:
            mileage = None
    
    price = None
    if listing.get('price'):
        price_str = listing['price'].replace('$', '').replace(',', '')
        try:
            price = int(price_str)
        except:
            price = None
    
    # Extract make/model from title if not provided
    make = listing.get('make', '')
    model = listing.get('model', '')
    
    if not make and listing.get('title'):
        # Try to extract from title
        title_lower = listing['title'].lower()
        for brand in ['honda', 'toyota', 'ford', 'chevrolet', 'nissan', 'mazda']:
            if brand in title_lower:
                make = brand
                break
    
    # Get value estimate if we have enough info
    if make and year and price:
        try:
            estimate = estimator.estimate_value(
                make=make,
                model=model or 'unknown',
                year=year,
                mileage=mileage,
                condition='good'  # Default assumption
            )
            
            # Calculate deal score
            deal_score = estimator.calculate_deal_score(price, estimate)
            
            # Add to listing
            listing['value_estimate'] = estimate
            listing['deal_score'] = deal_score
            listing['has_analysis'] = True
        except Exception as e:
            print(f"Error calculating value estimate: {e}")
            listing['has_analysis'] = False
    else:
        listing['has_analysis'] = False
    
    return listing
