# FastAPI backend for FX + Crypto
# Endpoints:
#   GET /health
#   GET /rates?base=USD
#   GET /fx?base=USD&to=NGN&amount=100
#   GET /crypto?coins=bitcoin,ethereum&vs=usd,ngn

import time
from typing import Dict, Tuple, List
import httpx
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="PyCalc FX+Crypto API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock down later if you want
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TTLCache:
    def __init__(self):
        self.store: Dict[str, Tuple[float, dict]] = {}

    def get(self, key: str, max_age: int):
        if key in self.store:
            ts, data = self.store[key]
            if time.time() - ts < max_age:
                return data
        return None

    def set(self, key: str, data: dict):
        self.store[key] = (time.time(), data)

cache = TTLCache()

async def fetch_json(url: str, timeout=10):
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()

async def get_fiat_rates(base: str):
    base = base.upper()
    key = f"fx:{base}"
    cached = cache.get(key, max_age=60*30)  # 30 mins
    if cached:
        return cached
    url = f"https://api.exchangerate.host/latest?base={base}"
    data = await fetch_json(url)
    rates = data.get("rates")
    if not rates:
        raise HTTPException(status_code=502, detail="No rates")
    payload = {"base": base, "rates": rates, "ts": int(time.time())}
    cache.set(key, payload)
    return payload

async def get_crypto_simple(coins: List[str], vs: List[str]):
    coins = [c.lower() for c in coins]
    vs = [v.lower() for v in vs]
    key = f"cg:{','.join(sorted(coins))}|{','.join(sorted(vs))}"
    cached = cache.get(key, max_age=60)  # 60s
    if cached:
        return cached
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={','.join(coins)}&vs_currencies={','.join(vs)}"
    )
    data = await fetch_json(url)
    if not isinstance(data, dict) or not data:
        raise HTTPException(status_code=502, detail="No crypto data")
    payload = {"data": data, "ts": int(time.time())}
    cache.set(key, payload)
    return payload
@app.get("/")
async def root():
    return {
        "message": "Welcome to FX+Crypto API",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "fx_example": "/fx?base=USD&to=NGN&amount=100",
            "crypto_example": "/crypto?coins=bitcoin,ethereum&vs=usd,ngn",
            "rates_example": "/rates?base=USD"
        }
    }

@app.get("/health")
async def health():
    return {"ok": True, "ts": int(time.time())}

@app.get("/rates")
async def rates(base: str = Query("USD")):
    return await get_fiat_rates(base)

@app.get("/fx")
async def fx(base: str = Query("USD"), to: str = Query("NGN"), amount: float = Query(1.0)):
    data = await get_fiat_rates(base)
    to_up = to.upper()
    if to_up not in data["rates"]:
        raise HTTPException(status_code=400, detail=f"Unsupported target: {to_up}")
    rate = data["rates"][to_up]
    return {
        "base": base.upper(), "to": to_up, "rate": rate,
        "amount": amount, "result": amount * rate, "ts": data["ts"]
    }

@app.get("/crypto")
async def crypto(
    coins: str = Query("bitcoin,ethereum,solana,binancecoin"),
    vs: str = Query("usd,eur,ngn")
):
    coins_list = [c.strip() for c in coins.split(",") if c.strip()]
    vs_list = [v.strip() for v in vs.split(",") if v.strip()]
    return await get_crypto_simple(coins_list, vs_list)
