"""
URL configuration for dashboard_config project.
"""

from django.contrib import admin
from django.urls import path
from tickers.views import (
    home,
    api_symbols,
    api_ticker,
    api_gainers,
    api_losers,
)

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),
    
    # Frontend
    path("", home, name="home"),
    
    # API Endpoints
    path("api/symbols/", api_symbols, name="api_symbols"),
    path("api/ticker/<str:symbol>/", api_ticker, name="api_ticker"),
    path("api/ticker/", api_ticker, name="api_ticker_query"),
    path("api/gainers/", api_gainers, name="api_gainers"),
    path("api/losers/", api_losers, name="api_losers"),
]
