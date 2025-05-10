"""Discord price‑alert bot ‑ now with per‑user numbered delete ("remove n").
This is a drop‑in replacement for your existing bot.py.
Only changes compared with your last version are marked # NEW / # CHANGED comments.
"""

import os, re, asyncio, time, logging, json, requests, certifi
import discord
from discord import Embed
from discord.ext import tasks
from dotenv import load_dotenv
from openai import OpenAI
from norm import normalize_symbol
from db   import (
    init_db, insert_alert, get_active_alerts, mark_triggered,
    delete_alert   # <-- make sure you added this helper in db.py
)

# ---------- ENV / SSL ----------
os.environ['SSL_CERT_FILE'] = certifi.where()
load_dotenv()

DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
CRYPTO_INTERVAL = 5    # s
OTHER_INTERVAL  = 30   # s
BINANCE_URL     = "https://api.binance.com/api/v3/ticker/price"

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s: %(message)s")

# ---------- DISCORD ----------
intents = discord.Intents.default(); intents.message_content = True
bot = discord.Client(intents=intents)
ai  = OpenAI(api_key=OPENAI_API_KEY)

# ---------- STATE ----------
last_other_fetch: float = 0.0
price_cache: dict[str, tuple[float, float]] = {}
user_index_cache: dict[int, dict[str, int]] = {}   # NEW  {discord_id: {"1": alert_id, ...}}

# ---------- API HELPERS ----------

def fetch_crypto_batch(symbols: list[str]):
    if not symbols:
        return {}
    payload = json.dumps(symbols, separators=(',', ''))  # no spaces
    r = requests.get(BINANCE_URL, params={"symbols": payload}, timeout=5)
    r.raise_for_status()
    return {it['symbol']: float(it['price']) for it in r.json()}

def fetch_other_price(symbol: str):
    # TODO: implement yfinance lookup or other provider
    return None  # placeholder

# ---------- GPT PARSER ----------
async def gpt_extract(prompt: str):
    sys = (
        "You are a price‑alert parser. Extract ONE alert and return JSON like "
        "{\"asset\":\"BTCUSDT\",\"price\":30000,\"direction\":null}"
    )
    try:
        r = await ai.chat.completions.acreate(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":sys}, {"role":"user","content":prompt}],
            max_tokens=100
        )
        d = json.loads(r.choices[0].message.content.strip())
        return d.get("asset"), float(d.get("price")), d.get("direction")
    except Exception as e:
        logging.warning("GPT parse error: %s", e)
        return None, None, None

# ---------- PRICE LOOP ----------
@tasks.loop(seconds=CRYPTO_INTERVAL)
async def price_loop():
    global last_other_fetch
    alerts = get_active_alerts()  # rows: (id, user_id, asset, price, direction)
    crypto, other = set(), set()
    for _, _, asset, *_ in alerts:
        (crypto if asset.endswith("USDT") else other).add(asset)

    # crypto fetch
    if crypto:
        prices = fetch_crypto_batch(list(crypto))
        ts = time.time(); price_cache.update({k: (v, ts) for k, v in prices.items()})

    # stock/commodity fetch
    if time.time() - last_other_fetch >= OTHER_INTERVAL:
        for sym in other:
            p = fetch_other_price(sym)
            if p is not None:
                price_cache[sym] = (p, time.time())
        last_other_fetch = time.time()

    # evaluate alerts
    for aid, uid, asset, tgt, direction in alerts:
        price, _ = price_cache.get(asset, (None, None))
        if price is None:
            continue
        hit = (direction == 'above' and price >= tgt) or (direction == 'below' and price <= tgt)
        if hit:
            try:
                user = await bot.fetch_user(int(uid))
                em = Embed(title="🚨 Price Alert", color=discord.Color.gold())
                em.add_field(name="Asset", value=asset)
                em.add_field(name="Target", value=str(tgt))
                em.add_field(name="Current", value=str(price))
                await user.send(embed=em)
            except Exception as e:
                logging.warning("DM fail %s: %s", uid, e)
            mark_triggered(aid)

# ---------- UI VIEW ----------
class ConfirmView(discord.ui.View):
    def __init__(self, asset, price, direction):
        super().__init__(timeout=60)
        self.asset, self.price, self.direction = asset, price, direction
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, i: discord.Interaction, _):
        insert_alert(i.user.id, self.asset, self.price, self.direction)
        await i.response.edit_message(content="✅ Alert set!", embed=None, view=None)
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, i: discord.Interaction, _):
        await i.response.edit_message(content="❌ Cancelled", embed=None, view=None)

# ---------- EVENTS ----------
@bot.event
async def on_ready():
    print("Bot ready as", bot.user)
    price_loop.start()

@bot.event
async def on_message(msg: discord.Message):
    if msg.author == bot.user:
        return

    if bot.user in msg.mentions:
        pat = rf"<@!?{bot.user.id}>"; clean = re.sub(pat, "", msg.content).strip()

        # ---------------- LIST MODE ----------------
        if not clean:
            rows = get_active_alerts(str(msg.author.id))  # user‑only fetch
            em = Embed(title="📋 Your Active Alerts", color=discord.Color.purple())
            if not rows:
                em.description = "You have no active alerts."
            else:
                mapping = {}
                lines = []
                for idx, (aid, _, asset, tgt, dir_) in enumerate(rows, 1):
                    mapping[str(idx)] = aid
                    lines.append(f"{idx}\uFE0F\u20E3  **{asset}** – {dir_} {tgt}")
                em.description = "\n".join(lines)
                user_index_cache[msg.author.id] = mapping  # NEW
                # expire mapping after 2 min
                asyncio.get_running_loop().call_later(120, lambda: user_index_cache.pop(msg.author.id, None))
            return await msg.channel.send(embed=em)

        # ---------------- DELETE MODE ----------------
        if clean.lower().startswith("remove"):
              m = re.match(r"remove\s+(\d+)", clean.lower())
            if m and msg.author.id in user_index_cache:
                idx = m.group(1)
                aid = user_index_cache[msg.author.id].get(idx)
                if aid:
                    delete_alert(aid, str(msg.author.id))
                    await msg.channel.send(f"🗑️  Alert {idx} deleted.")
                    user_index_cache[msg.author.id].pop(idx, None)
                else:
                    await msg.channel.send("Index not valid or expired.")
            else:
                await msg.channel.send("Use `remove N` right after listing alerts.")
            return

        # ---------------- CREATE MODE ----------------
        asset_raw, price, direction = await gpt_extract(clean)
        if not asset_raw or not price:
            return await msg.channel.send("❌ Could not parse that alert.")
        ticker = normalize_symbol(asset_raw)
        cur = price_cache.get(ticker, (None,))[0]
        if cur is None:
            cur = fetch_crypto_batch([ticker]).get(ticker) if ticker.endswith("USDT") else fetch_other_price(ticker)
        if cur is None:
            return await msg.channel.send("Unknown asset.")
        if direction not in ("above","below"):
            direction = "above" if cur <= price else "below"
        em = Embed(title="Confirm Price Alert", color=discord.Color.blue())
        em.add_field(name="Asset", value=ticker)
        em.add_field(name="Target", value=str(price))
        em.add_field(name="Direction", value=direction)
        await msg.channel.send(embed=em, view=ConfirmView(ticker, price, direction))

# ---------- MAIN ----------
if __name__ == "__main__":
    init_db()
    bot.run(DISCORD_TOKEN)
