"""Weather plugin — current + forecast queries."""
import json
import urllib.request
import urllib.parse
import time

from .base import AstraPlugin

_wx_cache = {}   # city -> {data, ts}
WEATHER_API_KEY = ""   # injected at load time
DEFAULT_CITY    = "Mumbai"
COUNTRY_CODE    = "IN"


def _fetch_weather(city: str, units: str = "metric") -> str:
    now = time.time()
    cached = _wx_cache.get(city)
    if cached and now - cached["ts"] < 600:
        return cached["data"]
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={urllib.parse.quote(city)},{COUNTRY_CODE}"
            f"&appid={WEATHER_API_KEY}&units={units}"
        )
        with urllib.request.urlopen(url, timeout=6) as r:
            d = json.loads(r.read())
        temp    = round(d["main"]["temp"])
        feels   = round(d["main"]["feels_like"])
        humidity= d["main"]["humidity"]
        desc    = d["weather"][0]["description"].capitalize()
        result  = f"{desc} in {city}. {temp}°C, feels like {feels}. Humidity {humidity}%."
        _wx_cache[city] = {"data": result, "ts": now}
        return result
    except Exception as e:
        print(f"[WeatherPlugin] error: {e}")
        return "Couldn't get weather right now."


def _fetch_forecast(city: str) -> str:
    """Tomorrow's forecast — first 3-hour block after midnight."""
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/forecast"
            f"?q={urllib.parse.quote(city)},{COUNTRY_CODE}"
            f"&appid={WEATHER_API_KEY}&units=metric&cnt=10"
        )
        with urllib.request.urlopen(url, timeout=6) as r:
            d = json.loads(r.read())
        import datetime
        tomorrow = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        for item in d.get("list", []):
            if item["dt_txt"].startswith(tomorrow):
                temp = round(item["main"]["temp"])
                desc = item["weather"][0]["description"].capitalize()
                return f"Tomorrow in {city}: {desc}, around {temp}°C."
        return "Forecast data not available right now."
    except Exception as e:
        print(f"[WeatherPlugin] forecast error: {e}")
        return "Couldn't fetch tomorrow's forecast."


class WeatherPlugin(AstraPlugin):
    name    = "weather"
    intents = ["weather", "weather_forecast"]

    def handle(self, intent: dict, speak_fn, **kwargs):
        i    = intent.get("intent")
        city = intent.get("city", DEFAULT_CITY) or DEFAULT_CITY
        if i == "weather":
            speak_fn(_fetch_weather(city))
            return True
        if i == "weather_forecast":
            speak_fn(_fetch_forecast(city))
            return True
        return False
