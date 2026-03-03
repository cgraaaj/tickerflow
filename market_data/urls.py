from django.urls import path

from . import views

app_name = "market_data"

urlpatterns = [
    path("stocks/", views.StockListView.as_view(), name="stock-list"),
    path("instruments/", views.InstrumentListView.as_view(), name="instrument-list"),
    path("expiries/", views.ExpiryListView.as_view(), name="expiry-list"),
    path("ticks/", views.TickListView.as_view(), name="tick-list"),
    path("candles/", views.CandleListView.as_view(), name="candle-list"),
]
