"""
Django views for Binance ticker dashboard API.
Provides JSON endpoints for fetching ticker data from MongoDB.
"""

import json
import logging
from datetime import datetime
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import cache_page
from .db_queries import (
    get_all_symbols,
    get_ticker_by_symbol,
    get_top_gainers,
    get_top_losers,
)

logger = logging.getLogger(__name__)


def home(request):
    """
    Render home page (SPA dashboard) - Only BTCUSDT & ETHUSDT with REAL MongoDB data charts.
    """
    return HttpResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Binance Trading Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #0a0e27 0%, #16213e 100%);
                color: #e0e0e0;
                min-height: 100vh;
                padding: 20px;
            }
            
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            
            header {
                text-align: center;
                margin-bottom: 40px;
                padding: 20px 0;
                border-bottom: 1px solid rgba(255, 193, 7, 0.3);
            }
            
            header h1 {
                font-size: 2em;
                color: #ffc107;
                margin-bottom: 10px;
            }
            
            header p {
                color: #999;
                font-size: 0.9em;
            }
            
            .controls {
                display: flex;
                gap: 20px;
                margin-bottom: 30px;
                align-items: center;
            }
            
            .control-group {
                display: flex;
                flex-direction: column;
                gap: 5px;
            }
            
            .control-group label {
                font-size: 0.85em;
                color: #aaa;
                font-weight: 600;
            }
            
            select {
                padding: 10px 15px;
                border: 1px solid rgba(255, 193, 7, 0.5);
                background: rgba(10, 14, 39, 0.8);
                color: #ffc107;
                border-radius: 4px;
                font-size: 1em;
                cursor: pointer;
            }
            
            select:hover {
                border-color: #ffc107;
            }
            
            select:focus {
                outline: none;
                border-color: #ffc107;
                box-shadow: 0 0 5px rgba(255, 193, 7, 0.3);
            }
            
            .dashboard {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 40px;
            }
            
            .card {
                background: rgba(22, 33, 62, 0.8);
                border: 1px solid rgba(255, 193, 7, 0.2);
                border-radius: 8px;
                padding: 20px;
                backdrop-filter: blur(10px);
            }
            
            .card.ticker {
                grid-column: 1 / -1;
            }
            
            .card h2 {
                color: #ffc107;
                margin-bottom: 15px;
            }
            
            .ticker-info {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
            }
            
            .chart-container {
                background: rgba(10, 14, 39, 0.5);
                border-radius: 4px;
                padding: 15px;
                position: relative;
                height: 300px;
                grid-column: 1 / -1;
            }
            
            .chart-container h3 {
                margin: 0 0 10px 0;
                color: #ffc107;
                font-size: 0.9em;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            .ticker-stat {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 0;
                border-bottom: 1px solid rgba(255, 193, 7, 0.1);
            }
            
            .ticker-stat:last-child {
                border-bottom: none;
            }
            
            .ticker-stat label {
                color: #aaa;
                font-size: 0.9em;
            }
            
            .ticker-stat .value {
                font-size: 1.1em;
                font-weight: 600;
                color: #ffc107;
            }
            
            .positive { color: #4caf50; }
            .negative { color: #f44336; }
            
            .loading {
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 200px;
                color: #ffc107;
            }
            
            .spinner {
                border: 3px solid rgba(255, 193, 7, 0.2);
                border-top: 3px solid #ffc107;
                border-radius: 50%;
                width: 30px;
                height: 30px;
                animation: spin 1s linear infinite;
                margin-right: 10px;
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            @media (max-width: 768px) {
                .dashboard {
                    grid-template-columns: 1fr;
                }
                .ticker-info {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>📊 Binance Trading Dashboard</h1>
                <p>Real-time BTC & ETH data from MongoDB Replica Set</p>
            </header>
            
            <div class="controls">
                <div class="control-group">
                    <label for="symbolSelect">Select Trading Pair</label>
                    <select id="symbolSelect" onchange="switchSymbol()">
                        <option value="BTCUSDT">BTCUSDT - Bitcoin</option>
                        <option value="ETHUSDT">ETHUSDT - Ethereum</option>
                    </select>
                </div>
            </div>
            
            <div class="dashboard">
                <!-- BTCUSDT Card -->
                <div class="card" id="btcCard">
                    <h2>₿ BTCUSDT</h2>
                    <div class="ticker-info" id="btcInfo">
                        <div class="loading"><div class="spinner"></div></div>
                    </div>
                </div>
                
                <!-- ETHUSDT Card -->
                <div class="card" id="ethCard">
                    <h2>Ξ ETHUSDT</h2>
                    <div class="ticker-info" id="ethInfo">
                        <div class="loading"><div class="spinner"></div></div>
                    </div>
                </div>
                
                <!-- Comparison Chart -->
                <div class="card">
                    <div class="chart-container">
                        <h3>💰 Price Comparison (BTC vs ETH)</h3>
                        <canvas id="comparisonChart"></canvas>
                    </div>
                </div>
                
                <!-- Volume Comparison -->
                <div class="card">
                    <div class="chart-container">
                        <h3>📊 Volume Comparison (BTC vs ETH)</h3>
                        <canvas id="volumeChart"></canvas>
                    </div>
                </div>
                
                <!-- 24h Movement Chart -->
                <div class="card" style="grid-column: 1 / -1;">
                    <div class="chart-container">
                        <h3>📈 24h Price Movement %</h3>
                        <canvas id="movementChart"></canvas>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            let btcData = null;
            let ethData = null;
            let comparisonChart = null;
            let volumeChart = null;
            let movementChart = null;
            
            document.addEventListener('DOMContentLoaded', function() {
                loadAllData();
                // Refresh every 30 seconds
                setInterval(loadAllData, 30000);
            });
            
            function loadAllData() {
                Promise.all([
                    fetch('/api/ticker/BTCUSDT/').then(r => r.json()),
                    fetch('/api/ticker/ETHUSDT/').then(r => r.json())
                ]).then(([btc, eth]) => {
                    btcData = btc;
                    ethData = eth;
                    
                    // Render ticker cards
                    renderTickerCard('btc', btcData);
                    renderTickerCard('eth', ethData);
                    
                    // Draw comparison charts with REAL data
                    drawComparisonChart();
                    drawVolumeChart();
                    drawMovementChart();
                }).catch(error => console.error('Error loading data:', error));
            }
            
            function renderTickerCard(symbol, data) {
                const containerId = symbol + 'Info';
                const change = data.priceMovement;
                const changeClass = change >= 0 ? 'positive' : 'negative';
                const priceChangeAbs = Math.abs(data.priceChange);
                
                document.getElementById(containerId).innerHTML = `
                    <div>
                        <div class="ticker-stat">
                            <label>Price (USDT)</label>
                            <div class="value">${data.lastPrice.toFixed(2)}</div>
                        </div>
                        <div class="ticker-stat">
                            <label>24h Change %</label>
                            <div class="value ${changeClass}">
                                ${change >= 0 ? '+' : ''}${change.toFixed(2)}%
                            </div>
                        </div>
                        <div class="ticker-stat">
                            <label>24h Price Change ($)</label>
                            <div class="value ${data.priceChange >= 0 ? 'positive' : 'negative'}">
                                ${data.priceChange >= 0 ? '+' : ''}${data.priceChange.toFixed(2)}
                            </div>
                        </div>
                    </div>
                    <div>
                        <div class="ticker-stat">
                            <label>Volume (M)</label>
                            <div class="value">${(data.volume / 1e6).toFixed(2)}</div>
                        </div>
                        <div class="ticker-stat">
                            <label>Quote Volume (B)</label>
                            <div class="value">$${(data.quoteVolume / 1e9).toFixed(2)}</div>
                        </div>
                        <div class="ticker-stat">
                            <label>Weighted Avg Price</label>
                            <div class="value">${data.weightedAvgPrice.toFixed(2)}</div>
                        </div>
                    </div>
                `;
            }
            
            function drawComparisonChart() {
                const canvas = document.getElementById('comparisonChart');
                if (!canvas) return;
                
                if (comparisonChart) {
                    comparisonChart.destroy();
                    comparisonChart = null;
                }
                
                const ctx = canvas.getContext('2d');
                comparisonChart = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: ['Current Price', 'Weighted Avg Price'],
                        datasets: [
                            {
                                label: 'BTCUSDT ($)',
                                data: [btcData.lastPrice, btcData.weightedAvgPrice],
                                backgroundColor: '#f7931a',
                                borderColor: '#f7931a',
                                borderRadius: 4,
                            },
                            {
                                label: 'ETHUSDT ($)',
                                data: [ethData.lastPrice, ethData.weightedAvgPrice],
                                backgroundColor: '#627eea',
                                borderColor: '#627eea',
                                borderRadius: 4,
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                labels: { color: '#aaa' }
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: false,
                                ticks: { color: '#aaa' },
                                grid: { color: 'rgba(255, 193, 7, 0.1)' }
                            },
                            x: {
                                ticks: { color: '#aaa' },
                                grid: { display: false }
                            }
                        }
                    }
                });
            }
            
            function drawVolumeChart() {
                const canvas = document.getElementById('volumeChart');
                if (!canvas) return;
                
                if (volumeChart) {
                    volumeChart.destroy();
                    volumeChart = null;
                }
                
                const ctx = canvas.getContext('2d');
                volumeChart = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: ['Volume (M)', 'Quote Volume (B)'],
                        datasets: [
                            {
                                label: 'BTCUSDT',
                                data: [btcData.volume / 1e6, btcData.quoteVolume / 1e9],
                                backgroundColor: '#f7931a',
                                borderColor: '#f7931a',
                                borderRadius: 4,
                            },
                            {
                                label: 'ETHUSDT',
                                data: [ethData.volume / 1e6, ethData.quoteVolume / 1e9],
                                backgroundColor: '#627eea',
                                borderColor: '#627eea',
                                borderRadius: 4,
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                labels: { color: '#aaa' }
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: false,
                                ticks: { color: '#aaa' },
                                grid: { color: 'rgba(255, 193, 7, 0.1)' }
                            },
                            x: {
                                ticks: { color: '#aaa' },
                                grid: { display: false }
                            }
                        }
                    }
                });
            }
            
            function drawMovementChart() {
                const canvas = document.getElementById('movementChart');
                if (!canvas) return;
                
                if (movementChart) {
                    movementChart.destroy();
                    movementChart = null;
                }
                
                const btcChange = btcData.priceMovement;
                const ethChange = ethData.priceMovement;
                
                const ctx = canvas.getContext('2d');
                movementChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: ['BTC Movement', 'ETH Movement'],
                        datasets: [{
                            label: '24h Price Movement %',
                            data: [btcChange, ethChange],
                            borderColor: ['#f7931a', '#627eea'],
                            backgroundColor: [
                                btcChange >= 0 ? 'rgba(247, 147, 26, 0.1)' : 'rgba(244, 67, 54, 0.1)',
                                ethChange >= 0 ? 'rgba(98, 126, 234, 0.1)' : 'rgba(244, 67, 54, 0.1)'
                            ],
                            borderWidth: 3,
                            fill: true,
                            tension: 0.4,
                            pointRadius: 8,
                            pointBackgroundColor: ['#f7931a', '#627eea'],
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                labels: { color: '#aaa' }
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: false,
                                ticks: { color: '#aaa' },
                                grid: { color: 'rgba(255, 193, 7, 0.1)' }
                            },
                            x: {
                                ticks: { color: '#aaa' },
                                grid: { display: false }
                            }
                        }
                    }
                });
            }
            
            function switchSymbol() {
                // This is kept for possible future expansion
                loadAllData();
            }
        </script>
    </body>
    </html>
    """)


@require_http_methods(["GET"])
def api_symbols(request):
    """
    GET /api/symbols/ - Get all trading pairs with latest prices.
    """
    try:
        symbols = get_all_symbols(limit=200)
        # Filter only symbols with liquidity (quoteVolume > 0)
        filtered = [s for s in symbols if s.get('quoteVolume', 0) > 0]
        
        # Convert ObjectIds to strings for JSON serialization
        for s in filtered:
            if '_id' in s:
                s['_id'] = str(s['_id'])
            s['lastPrice'] = float(s.get('lastPrice', 0))
            s['volume'] = float(s.get('volume', 0))
            s['quoteVolume'] = float(s.get('quoteVolume', 0))
        
        return JsonResponse({
            'symbols': filtered[:50],  # Limit to top 50 for frontend performance
            'count': len(filtered),
            'timestamp': datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"API error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def api_ticker(request, symbol=None):
    """
    GET /api/ticker/BTCUSDT/ - Get latest ticker for a symbol.
    """
    symbol = symbol or request.GET.get('symbol')
    
    if not symbol:
        return JsonResponse({'error': 'Symbol required'}, status=400)
    
    try:
        ticker = get_ticker_by_symbol(symbol)
        
        if not ticker:
            return JsonResponse({'error': f'Symbol {symbol} not found'}, status=404)
        
        # Convert ObjectId to string for JSON serialization
        if '_id' in ticker:
            ticker['_id'] = str(ticker['_id'])
        
        # Ensure numeric fields are JSON serializable
        ticker['lastPrice'] = float(ticker.get('lastPrice', 0))
        ticker['priceChange'] = float(ticker.get('priceChange', 0))
        ticker['priceMovement'] = float(ticker.get('priceMovement', 0))
        ticker['volume'] = float(ticker.get('volume', 0))
        ticker['quoteVolume'] = float(ticker.get('quoteVolume', 0))
        ticker['weightedAvgPrice'] = float(ticker.get('weightedAvgPrice', 0))
        
        return JsonResponse(ticker)
    except Exception as e:
        logger.error(f"API error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def api_gainers(request):
    """
    GET /api/gainers/ - Get top 10 gainers by price movement %.
    """
    try:
        limit = int(request.GET.get('limit', 10))
        gainers = get_top_gainers(limit=min(limit, 50))
        
        # Convert ObjectIds
        for g in gainers:
            if '_id' in g:
                g['_id'] = str(g['_id'])
            g['lastPrice'] = float(g.get('lastPrice', 0))
            g['priceMovement'] = float(g.get('priceMovement', 0))
            g['volume'] = float(g.get('volume', 0))
        
        return JsonResponse({
            'gainers': gainers,
            'count': len(gainers),
        })
    except Exception as e:
        logger.error(f"API error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def api_losers(request):
    """
    GET /api/losers/ - Get top 10 losers by price movement %.
    """
    try:
        limit = int(request.GET.get('limit', 10))
        losers = get_top_losers(limit=min(limit, 50))
        
        # Convert ObjectIds
        for l in losers:
            if '_id' in l:
                l['_id'] = str(l['_id'])
            l['lastPrice'] = float(l.get('lastPrice', 0))
            l['priceMovement'] = float(l.get('priceMovement', 0))
            l['volume'] = float(l.get('volume', 0))
        
        return JsonResponse({
            'losers': losers,
            'count': len(losers),
        })
    except Exception as e:
        logger.error(f"API error: {e}")
        return JsonResponse({'error': str(e)}, status=500)
