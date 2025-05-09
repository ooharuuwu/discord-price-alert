# import json

# PATH = "alltickers.json"

# with open(PATH, "r", encoding="utf-8") as f:
#     text = f.read()

# try:
#     json.loads(text)
#     print("✅ JSON is valid")
# except json.JSONDecodeError as e:
#     print(f"❌ JSON error: {e.msg}")
#     print(f"At line {e.lineno}, column {e.colno}, char {e.pos}")
#     lines = text.splitlines()
#     # show the offending line and point to the column
#     bad_line = lines[e.lineno - 1]
#     print(f"\n{e.lineno:4d} | {bad_line}")
#     print("     " + " "*(e.colno-1) + "^")





#     @tasks.loop(seconds=CRYPTO_INTERVAL)
# async def price_loop():                         
#     global last_other_fetch
#     alerts = get_active_alerts()
#     crypto, other = set(), set()

#     for _, _, asset, _, _ in alerts:
#         (crypto if asset.endswith("USDT") else other).add(asset)


#     if crypto:
#         for k, v in fetch_crypto_batch(list(crypto)).items():
#             price_cache[k] = (v, time.time())


#     if time.time() - last_other_fetch >=OTHER_INTERVAL:
#         for sym in other:
#             try:
#                 price_cache[sym] = (fetch_other_price(sym), time.time())
#             except Exception as e:
#                 logging.warning("yfinance fail %s: %s", sym, e)
#         last_other_fetch = time.time()
            
#     for aid, uid, asset, target, direction in alerts:
#         price, _ = price_cache.get(asset, (None, None))
#         if price is None:
#             continue #loop shifts here to next asset
#         if (direction == "above" and price >= target) or (direction == "below" and price <= target):
#             try:
#                 user = await bot.fetch_user(int(uid))
#                 em = Embed(title="🚨 Price Alert", color=discord.Color.gold())
#                 em.add_field(name="Asset", value=asset)
#                 em.add_field(name="Target", value=str(target))
#                 em.add_field(name="Current", value=str(price))
#                 await user.send(embed=em)
#             except Exception as e:
#                 logging.warning("DM fail %s: %s", uid, e)
#             mark_triggered(aid)
                
