import re, asyncio, time, logging
import requests
import json
import discord
from discord import Embed
from discord.ext import tasks
from openai import OpenAI
from norm import normalize_symbol
from db import init_db, insert_alert, get_active_alerts, mark_triggered
from dotenv import load_dotenv
import os, certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

logging.basicConfig(level=logging.DEBUG)

init_db()
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CRYPTO_INTERVAL = 5      # seconds
OTHER_INTERVAL  = 30     # seconds
BINANCE_BATCH   = "https://api.binance.com/api/v3/ticker/price"

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents= intents)

ai = OpenAI(api_key=OPENAI_API_KEY)

last_other_fetch = 0.0
price_cache = {}

def fetch_crypto_batch(symbols):
    if not symbols:
        return {}
    # compact JSON (no spaces after commas)
    payload = json.dumps(symbols, separators=(",", ""))
    resp = requests.get(
        "https://api.binance.com/api/v3/ticker/price",
        params={"symbols": payload},
        timeout=5
    )
    resp.raise_for_status()
    return {item["symbol"]: float(item["price"]) for item in resp.json()}

def fetch_other_price(symbol):
    return                                      #incomplete



async def gpt_extract(prompt):
    sys = (
        "You are a price-alert parser. From the user’s text, extract exactly one alert "
        "and return ONLY valid JSON with these keys:\n"
        "  • asset     – the ticker or name (e.g. BTCUSDT, AAPL, GOLD)\n"
        "  • price     – the target price as a number\n"
        "  • direction – either \"above\" (price rising to the target), "
        "or \"below\" (price falling to the target), or null if unspecified\n"
        "Example outputs:\n"
        "{\"asset\":\"AAPL\",\"price\":150.0,\"direction\":\"below\"}\n"
        "{\"asset\":\"BTCUSDT\",\"price\":30000,\"direction\":null}"
    )
    try:
        r = ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":sys},
                      {"role":"user","content":prompt}],
            max_tokens=100,
        )
        data = json.loads(r.choices[0].message.content.strip())
        return data.get("asset"), float(data.get("price")), data.get("direction")
    except Exception as e:
        logging.warning("GPT parse error: %s", e)
        return None, None, None



@tasks.loop(seconds=CRYPTO_INTERVAL)
async def price_loop():
    global last_other_fetch
    alerts = get_active_alerts()  
    if not alerts:
        logging.info("No active alerts to check.")
        return

    crypto, other = set(), set()
    for _, _, asset, _, _ in alerts:
        (crypto if asset.endswith("USDT") else other).add(asset)

    # DEBUG
    logging.info(f"Running price_loop — {len(crypto)} crypto, {len(other)} other symbols")

    # --- Crypto refresh ---
    if crypto:
        prices = fetch_crypto_batch(list(crypto))
        ts = time.time()
        for k, v in prices.items():
            price_cache[k] = (v, ts)
            logging.debug(f"Cached crypto {k} @ {v}")

    # --- Stocks/commodities every OTHER_INTERVAL ---
    if time.time() - last_other_fetch >= OTHER_INTERVAL:
        for sym in other:
            try:
                p = fetch_other_price(sym)
                price_cache[sym] = (p, time.time())
                logging.debug(f"Cached other {sym} @ {p}")
            except Exception as e:
                logging.warning("yfinance fail %s: %s", sym, e)
        last_other_fetch = time.time()

    # --- Evaluate all alerts ---
    for aid, uid, asset, target, direction in alerts:
        price, ts = price_cache.get(asset, (None, None))
        logging.debug(f"[Eval] Alert {aid} → {asset} @ {price}, target={target}, dir={direction}")
        if price is None:
            logging.debug(f"[Eval] Skipping {asset}: no price yet")
            continue

        hit = (direction == "above" and price >= target) or (direction == "below" and price <= target)
        logging.debug(f"[Eval] Hit? {hit}")
        if hit:
            logging.info(f"[Trigger] Alert {aid} for user {uid} fired: {asset} {price} >=? {target}")
            try:
                user = await bot.fetch_user(int(uid))
                em = Embed(title="🚨 Price Alert", color=discord.Color.gold())
                em.add_field(name="Asset",   value=asset)
                em.add_field(name="Target",  value=str(target))
                em.add_field(name="Current", value=str(price))
                await user.send(embed=em)
                logging.info(f"Sent DM to {uid} for alert {aid}")
            except Exception as e:
                logging.warning("DM fail %s: %s", uid, e)
            mark_triggered(aid)




class ConfirmView(discord.ui.View):
    def __init__(self, asset, price, direction):
        super().__init__(timeout=60)
        self.asset, self.price, self.direction = asset, price, direction
    @discord.ui.button(label="Confirm", style = discord.ButtonStyle.success)
    async def confirm(self, i: discord.Interaction, _):
        insert_alert(i.user.id, self.asset, self.price, self.direction)
        await i.response.edit_message(content="✅ Alert set!", embed=None, view=None)
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, i: discord.Interaction, _):
        await i.response.edit_message(content="❌ Cancelled", embed=None, view=None)

@bot.event
async def on_ready():
    print("Bot ready as", bot.user)
    price_loop.start()

@bot.event
async def on_message(msg):
    if msg.author == bot.user:
        return

    if bot.user in msg.mentions:
        pattern = rf"<@!?{bot.user.id}>"
        clean_text = re.sub(pattern, "", msg.content).strip()

        if not clean_text:
            user_alerts = [row for row in get_active_alerts() if row[1] == str(msg.author.id)]
            em = Embed(title="📋 Your Active Alerts", color=discord.Color.purple())
            if not user_alerts:
                em.description = "You have no active alerts."
            else:
                lines = []
                for _, _, asset, target, direction in user_alerts:
                    lines.append(f"**{asset}**: {direction} {target}")
                em.description = "\n".join(lines)

            return await msg.channel.send(embed=em)        

        asset_raw, price, direction = await gpt_extract(clean_text)
        if not asset_raw or not price:
            return await msg.channel.send("❌ Could not parse that ticker. Try again.")
        ticker = normalize_symbol(asset_raw)
        current = fetch_other_price(ticker) if not ticker.endswith("USDT") else fetch_crypto_batch([ticker]).get(ticker)
        if current is None:
            return await msg.channel.send("Unknown asset.")
        if direction not in ("above", "below"):
            direction = "above" if current <= price else "below"
        em = Embed(title="Confirm Price Alert", color=discord.Color.blue())
        em.add_field(name="Asset", value=ticker)
        em.add_field(name="Target", value=str(price))
        em.add_field(name="Direction", value=direction)
        return await msg.channel.send(embed=em, view=ConfirmView(ticker, price, direction))



bot.run(DISCORD_TOKEN)