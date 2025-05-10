import requests

import os

# Folder where logos are saved
FOLDER = "crypto_logos"


def fetch_top_50_coins():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 50,
        "page": 1,
        "sparkline": False
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

coins = fetch_top_50_coins()

# Create mapping: coingecko_id -> TICKERUSDT
ticker_map = {coin["id"]: coin["symbol"].upper() + "USDT" for coin in coins}

def rename_files():
    for old_name in os.listdir(FOLDER):
        if not old_name.endswith(".png"):
            continue
        coin_id = old_name.replace(".png", "")
        new_name = ticker_map.get(coin_id)
        if new_name:
            src = os.path.join(FOLDER, old_name)
            dst = os.path.join(FOLDER, f"{new_name}.png")
            os.rename(src, dst)
            print(f"Renamed {old_name} -> {new_name}.png")
        else:
            print(f"Skipping {old_name} (no mapping found)")

if __name__ == "__main__":
    rename_files()