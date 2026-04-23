"""
MongoDB connection and queries for Binance ticker data.
Following MongoDB connection best practices for web applications.
"""

import os
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Connection pool configuration (Django synchronous web app context)
# Context: Django WSGI app with typical workload
# - Expected ops/sec: ~1-10 (dashboard queries)
# - Average query duration: 50-200ms
# - Pool size: 5-10 sufficient for small-medium dashboards
MONGO_URI = os.getenv(
    'MONGO_URI',
    'mongodb://admin:pwd@mongo-primary:27017,mongo-secondary-1:27017,mongo-secondary-2:27017/?replicaSet=rs0&authSource=admin'
)

# Connection pool configuration
MONGO_CLIENT_KWARGS = {
    'serverSelectionTimeoutMS': 5000,  # 5s timeout for initial server discovery
    'connectTimeoutMS': 10000,          # 10s timeout for TCP connection
    'socketTimeoutMS': 30000,           # 30s timeout for socket operations
    'maxPoolSize': 10,                  # Max 10 connections (light dashboard workload)
    'minPoolSize': 2,                   # Min 2 idle connections (always ready)
    'maxIdleTimeMS': 60000,             # Prune idle connections after 60s
    'retryWrites': True,                # Automatic retry on transient errors (helps with replica failover)
}

# Global MongoClient instance (created once, reused across requests)
_mongo_client = None


def get_mongo_client():
    """
    Get or create a singleton MongoDB client with optimized connection pool.
    Reusing client instance dramatically reduces connection overhead.
    
    Returns:
        MongoClient: Connected MongoDB client with replica set support
        
    Raises:
        ServerSelectionTimeoutError: If MongoDB is unreachable
    """
    global _mongo_client
    
    if _mongo_client is None:
        try:
            _mongo_client = MongoClient(MONGO_URI, **MONGO_CLIENT_KWARGS)
            # Verify connectivity on first creation
            _mongo_client.admin.command('ping')
            logger.info("✓ MongoDB connection established (replica set rs0)")
        except (ServerSelectionTimeoutError, ConnectionFailure) as e:
            logger.error(f"✗ Failed to connect to MongoDB: {e}")
            raise
    
    return _mongo_client


def get_binance_db():
    """Get the binance_db database instance."""
    client = get_mongo_client()
    return client['binance_db']


def get_realtime_collection():
    """Get the realtime_data collection."""
    db = get_binance_db()
    return db['realtime_data']


def get_all_symbols(limit=1000) -> list:
    """
    Get all available trading symbols with their latest prices.
    
    Args:
        limit: Max number of symbols to return
        
    Returns:
        List of dicts with symbol, lastPrice, priceChange, volume
    """
    try:
        collection = get_realtime_collection()
        
        # Project only needed fields for list view (reduces network transfer)
        symbols = collection.find(
            {'quoteVolume': {'$gt': 0}},  # Filter out zero-volume symbols
            projection={
                'symbol': 1,
                'lastPrice': 1,
                'priceChange': 1,
                'priceMovement': 1,
                'volume': 1,
                'quoteVolume': 1,
                'timestamp': 1,
            }
        ).limit(limit).sort('symbol', 1)
        
        return list(symbols)
    except Exception as e:
        logger.error(f"Error fetching symbols: {e}")
        return []


def get_ticker_by_symbol(symbol: str) -> dict:
    """
    Get latest ticker data for a specific symbol.
    
    Args:
        symbol: Trading pair symbol (e.g., 'BTCUSDT')
        
    Returns:
        Dict with ticker data or empty dict if not found
    """
    try:
        collection = get_realtime_collection()
        ticker = collection.find_one(
            {'symbol': symbol},
            projection={
                'symbol': 1,
                'lastPrice': 1,
                'priceChange': 1,
                'priceMovement': 1,
                'volume': 1,
                'quoteVolume': 1,
                'weightedAvgPrice': 1,
                'timestamp': 1,
                'processingDate': 1,
            }
        )
        return ticker if ticker else {}
    except Exception as e:
        logger.error(f"Error fetching ticker for {symbol}: {e}")
        return {}


def get_ticker_history(symbol: str, days: int = 1) -> list:
    """
    Get historical ticker data for a symbol.
    
    Note: Current implementation stores only latest snapshot.
    For true historical data, archive older snapshots to separate collection.
    
    Args:
        symbol: Trading pair symbol
        days: Number of days of history (not yet implemented in current schema)
        
    Returns:
        List of historical ticker records
    """
    try:
        collection = get_realtime_collection()
        
        # Current limitation: realtime_data is replaced on each Spark run
        # So we only have the latest snapshot
        # TODO: Implement historical collection with periodic snapshots
        
        history = list(collection.find(
            {'symbol': symbol},
            projection={
                'symbol': 1,
                'lastPrice': 1,
                'volume': 1,
                'priceChange': 1,
                'timestamp': 1,
            }
        ).limit(1))
        
        return history
    except Exception as e:
        logger.error(f"Error fetching history for {symbol}: {e}")
        return []


def get_top_gainers(limit: int = 10) -> list:
    """
    Get top gainers by price change percentage.
    
    Args:
        limit: Number of top gainers to return
        
    Returns:
        List of top gainer symbols
    """
    try:
        collection = get_realtime_collection()
        
        gainers = list(collection.find(
            {'quoteVolume': {'$gt': 0}},
            projection={
                'symbol': 1,
                'lastPrice': 1,
                'priceMovement': 1,
                'volume': 1,
            }
        ).sort('priceMovement', -1).limit(limit))
        
        return gainers
    except Exception as e:
        logger.error(f"Error fetching top gainers: {e}")
        return []


def get_top_losers(limit: int = 10) -> list:
    """
    Get top losers by price change percentage.
    
    Args:
        limit: Number of top losers to return
        
    Returns:
        List of top loser symbols
    """
    try:
        collection = get_realtime_collection()
        
        losers = list(collection.find(
            {'quoteVolume': {'$gt': 0}},
            projection={
                'symbol': 1,
                'lastPrice': 1,
                'priceMovement': 1,
                'volume': 1,
            }
        ).sort('priceMovement', 1).limit(limit))
        
        return losers
    except Exception as e:
        logger.error(f"Error fetching top losers: {e}")
        return []


def cleanup_mongo():
    """Close MongoDB connection (call on app shutdown)."""
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        _mongo_client = None
        logger.info("MongoDB connection closed")
