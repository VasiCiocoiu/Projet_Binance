"""
MongoDB connection and queries for Binance ticker data.
Following MongoDB connection best practices for web applications.
"""

import os
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure, OperationFailure, AutoReconnect
from datetime import datetime, timedelta
import logging
import time

logger = logging.getLogger(__name__)

# Connection pool configuration (Django synchronous web app context)
# Context: Django WSGI app with typical workload
# - Expected ops/sec: ~1-10 (dashboard queries)
# - Average query duration: 50-200ms
# - Pool size: 5-10 sufficient for small-medium dashboards
MONGO_URI = os.getenv(
    'MONGO_URI',
    'mongodb://mongo-primary:27017,mongo-secondary-1:27017,mongo-secondary-2:27017/?replicaSet=rs0'
)

# Connection pool configuration (optimized for Django web app)
MONGO_CLIENT_KWARGS = {
    'serverSelectionTimeoutMS': 10000,  # 10s timeout for initial server discovery (increased for replica set init)
    'connectTimeoutMS': 15000,          # 15s timeout for TCP connection (increased for initialization phase)
    'socketTimeoutMS': 30000,           # 30s timeout for socket operations
    'maxPoolSize': 10,                  # Max 10 connections (light dashboard workload)
    'minPoolSize': 2,                   # Min 2 idle connections (always ready)
    'maxIdleTimeMS': 60000,             # Prune idle connections after 60s
    'retryWrites': True,                # Automatic retry on transient errors (helps with replica failover)
    'retryReads': True,                 # Automatic retry on read errors
}

# Global MongoClient instance (created once, reused across requests)
_mongo_client = None
_connection_error_logged = False


def get_mongo_client(max_retries=3, retry_delay=2):
    """
    Get or create a singleton MongoDB client with optimized connection pool.
    Reusing client instance dramatically reduces connection overhead.
    
    Implements retry logic to handle transient connection failures during
    replica set initialization and network issues.
    
    Args:
        max_retries: Number of times to retry connection before giving up
        retry_delay: Seconds to wait between retry attempts
    
    Returns:
        MongoClient: Connected MongoDB client with replica set support
        
    Raises:
        ServerSelectionTimeoutError: If MongoDB is unreachable after retries
        OperationFailure: If authentication fails (credentials incorrect)
    """
    global _mongo_client, _connection_error_logged
    
    if _mongo_client is not None:
        try:
            # Verify existing connection is still valid
            _mongo_client.admin.command('ping')
            return _mongo_client
        except (ServerSelectionTimeoutError, ConnectionFailure, AutoReconnect, OperationFailure):
            logger.warning("MongoDB connection lost, attempting to reconnect...")
            _mongo_client = None
    
    # Retry logic for initial connection
    last_error = None
    for attempt in range(max_retries):
        try:
            logger.info(f"Connecting to MongoDB (attempt {attempt + 1}/{max_retries})...")
            client = MongoClient(MONGO_URI, **MONGO_CLIENT_KWARGS)
            
            # Verify connectivity on first creation
            client.admin.command('ping')
            _mongo_client = client
            logger.info("✓ MongoDB connection established (replica set rs0)")
            _connection_error_logged = False
            return _mongo_client
            
        except OperationFailure as e:
            # Authentication failed - this is a permanent error, don't retry
            logger.error(f"✗ MongoDB authentication failed: {e}")
            logger.error(f"  Check MONGO_URI and credentials in .env file")
            logger.error(f"  Expected credentials: MONGO_USERNAME={os.getenv('MONGO_USERNAME')} (from .env)")
            _connection_error_logged = True
            raise
            
        except (ServerSelectionTimeoutError, ConnectionFailure, AutoReconnect) as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)  # Exponential backoff
                logger.warning(f"✗ Connection attempt {attempt + 1} failed: {e}")
                logger.info(f"  Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"✗ Failed to connect to MongoDB after {max_retries} attempts: {e}")
                _connection_error_logged = True
                raise
    
    # Should not reach here, but handle just in case
    raise ServerSelectionTimeoutError(f"Failed to connect to MongoDB: {last_error}")


def get_binance_db():
    """Get the binance_db database instance."""
    client = get_mongo_client()
    return client['binance_db']


def get_realtime_collection():
    """Get the append-only price_history time-series collection."""
    db = get_binance_db()
    return db['price_history']


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

        pipeline = [
            {'$match': {'quoteVolume': {'$gt': 0}}},
            {'$sort': {'timestamp': -1}},
            {
                '$group': {
                    '_id': '$metadata.symbol',
                    'doc': {'$first': '$$ROOT'}
                }
            },
            {'$replaceRoot': {'newRoot': '$doc'}},
            {'$sort': {'metadata.symbol': 1}},
            {'$limit': int(limit)},
            {
                '$project': {
                    '_id': 1,
                    'symbol': '$metadata.symbol',
                    'lastPrice': 1,
                    'priceChange': 1,
                    'priceMovement': 1,
                    'volume': 1,
                    'quoteVolume': 1,
                    'weightedAvgPrice': 1,
                    'timestamp': 1,
                    'processingDate': 1,
                }
            },
        ]

        return list(collection.aggregate(pipeline))
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
            {'metadata.symbol': symbol.upper()},
            projection={
                'metadata.symbol': 1,
                'lastPrice': 1,
                'priceChange': 1,
                'priceMovement': 1,
                'volume': 1,
                'quoteVolume': 1,
                'weightedAvgPrice': 1,
                'timestamp': 1,
                'processingDate': 1,
            },
            sort=[('timestamp', -1)],
        )
        if ticker:
            ticker['symbol'] = ticker.get('metadata', {}).get('symbol', symbol.upper())
            ticker.pop('metadata', None)
        return ticker if ticker else {}
    except Exception as e:
        logger.error(f"Error fetching ticker for {symbol}: {e}")
        return {}


def get_ticker_history(symbol: str, days: int = 1) -> list:
    """
    Get historical ticker data for a symbol.
    
    Returns true time-series history from append-only price_history collection.
    
    Args:
        symbol: Trading pair symbol
        days: Number of days of history (not yet implemented in current schema)
        
    Returns:
        List of historical ticker records
    """
    try:
        collection = get_realtime_collection()
        since = datetime.utcnow() - timedelta(days=max(days, 1))

        pipeline = [
            {
                '$match': {
                    'metadata.symbol': symbol.upper(),
                    'timestamp': {'$gte': since}
                }
            },
            {'$sort': {'timestamp': 1}},
            {
                '$project': {
                    '_id': 1,
                    'symbol': '$metadata.symbol',
                    'lastPrice': 1,
                    'volume': 1,
                    'quoteVolume': 1,
                    'priceChange': 1,
                    'priceMovement': 1,
                    'weightedAvgPrice': 1,
                    'timestamp': 1,
                }
            },
        ]

        return list(collection.aggregate(pipeline))
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

        pipeline = [
            {'$match': {'quoteVolume': {'$gt': 0}}},
            {'$sort': {'timestamp': -1}},
            {
                '$group': {
                    '_id': '$metadata.symbol',
                    'doc': {'$first': '$$ROOT'}
                }
            },
            {'$replaceRoot': {'newRoot': '$doc'}},
            {'$sort': {'priceMovement': -1}},
            {'$limit': int(limit)},
            {
                '$project': {
                    '_id': 1,
                    'symbol': '$metadata.symbol',
                    'lastPrice': 1,
                    'priceMovement': 1,
                    'volume': 1,
                }
            },
        ]

        return list(collection.aggregate(pipeline))
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

        pipeline = [
            {'$match': {'quoteVolume': {'$gt': 0}}},
            {'$sort': {'timestamp': -1}},
            {
                '$group': {
                    '_id': '$metadata.symbol',
                    'doc': {'$first': '$$ROOT'}
                }
            },
            {'$replaceRoot': {'newRoot': '$doc'}},
            {'$sort': {'priceMovement': 1}},
            {'$limit': int(limit)},
            {
                '$project': {
                    '_id': 1,
                    'symbol': '$metadata.symbol',
                    'lastPrice': 1,
                    'priceMovement': 1,
                    'volume': 1,
                }
            },
        ]

        return list(collection.aggregate(pipeline))
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
