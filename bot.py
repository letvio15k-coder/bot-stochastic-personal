import os, threading, asyncio, requests, json
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ.get("TOKEN")

SUBS_FILE="subs.json"
subscribers=set()
try:
    if os.path.exists(SUBS_FILE):
        with open(SUBS_FILE,'r') as f: subscribers=set(json.load(f))
except: pass
def save_subs():
    try:
        with open(SUBS_FILE,'w') as f: json.dump(list(subscribers),f)
    except: pass

app_flask=Flask(__name__)
@app_flask.route('/')
def home(): return f"STOCHASTIC BOT - {len(subscribers)} users OK"

def get_klines(symbol, interval, limit=50):
    try:
        # Tự động thêm USDT nếu bạn chỉ gõ BTC
        if "USDT" not in symbol.upper():
            symbol = symbol.upper() + "USDT"
        url=f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r=requests.get(url,timeout=10).json()
        if isinstance(r,dict): return None, symbol
        closes=[float(x[4]) for x in r]
        highs=[float(x[2]) for x in r]
        lows=[float(x[3]) for x in r]
        return {"closes":closes,"highs":highs,"lows":lows}, symbol
    except:
        return None, symbol

def calc_stoch(highs, lows, closes, k_period=14, d_period=3):
    if len(closes) < k_period + d_period: return None
    k_values=[]
    for i in range(len(closes)):
        if i+1 < k_period:
            k_values.append(None)
            continue
        highest = max(highs[i+1-k_period:i+1])
        lowest = min(lows[i+1-k_period:i+1])
        if highest == lowest:
            k = 50
        else:
            k = (closes[i] - lowest) / (highest - lowest) * 100
        k_values.append(k)

    # %D là MA3 của %K
    d_values=[]
    for i in range(len(k_values)):
        if i+1 < d_period or k_values[i] is None:
            d_values.append(None)
        else:
            valid_k = [x for x in k_values[i+1-d_period:i+1] if x is not None]
            if len(valid_k) == d_period:
                d_values.append(sum(valid_k)/d_period)
            else:
                d_values.append(None)

    return {
        "k": k_values[-1],
        "d": d_values[-1],
        "k_prev": k_values[-2],
        "d_prev": d_values[-2],
        "k_values": k_values
    }

def analyze_stoch(symbol_input, interval):
    data, symbol = get_klines(symbol_input, interval, 50)
    if not data: return None
    stoch = calc_stoch(data["highs"], data["lows"], data["closes"])
    if not stoch or stoch["k"] is None or stoch["d"] is None: return None

    k, d = stoch["k"], stoch["d"]
    k_prev, d_prev = stoch["k_prev"], stoch["d_prev"]

    signal = None
    # ĐỌC SIGNAL CHUẨN CỦA STOCHASTIC
    if k < 20 and d < 20 and k_prev < d_prev and k > d:
        signal = f"🟢 MUA MANH - Qua ban <20 va GOLDEN CROSS"
    elif k > 80 and d > 80 and k_prev > d_prev and k < d:
        signal = f"🔴 BAN MANH - Qua mua >80 va DEATH CROSS"
    elif k_prev < d_prev and k > d and k < 50:
        signal = f"🟢 MUA - Golden Cross duoi 50"
    elif k_prev > d_prev and k < d and k > 50:
        signal = f"🔴 BAN - Death Cross tren 50"
    elif k < 20 and d < 20:
        signal = f"🟡 QUA BAN <20 - Canh hoi len"
    elif k > 80 and d > 80:
        signal = f"🟡 QUA MUA >80 - Canh chot loi"
    elif k > 50 and k > k_prev and d > d_prev:
        signal = f"🔵 TANG DAN - Luc mua dang tang"

    return {
        "symbol": symbol.replace("USDT",""),
        "full_symbol": symbol,
        "interval": interval,
        "price": data["closes"][-1],
        "k": k,
        "d": d,
        "signal": signal
    }

# Lấy top coin volume cao nhất Binance để quét
def get_top_coins(limit=50):
    try:
        url="https://data-api.binance.vision/api/v3/ticker/24hr"
        r=requests.get(url,timeout=10).json()
        usdt = [x for x in r if x["symbol"].endswith("USDT") and not x["symbol"].endswith("BUSDUSDT")]
        sorted_coins = sorted(usdt, key=lambda x: float(x["quoteVolume"]), reverse=True)
        return [x["symbol"] for x in sorted_coins[:limit]]
    except:
        return ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT"]

# COMMANDS
async def start_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "📈 BOT STOCHASTIC - BAT CU COIN NAO\n\n"
        "Cach dung:\n"
        "/stoch BTC - Check BTC khung 4h\n"
        "/stoch SOL 1h - Check SOL khung 1h\n"
        "/stoch PEPE 15m - Check PEPE khung 15m\n"
        "/stoch ETH 1d - Check ETH khung ngay\n\n"
        "/scan - Quet top 30 coin co signal STOCH hot (4h)\n"
        "/scan 1h - Quet khung 1h\n"
        "/scan_oversold - Chi quet coin dang QUA BAN <20\n"
        "/scan_overbought - Chi quet coin dang QUA MUA >80\n\n"
        "/auto_on - Bat bao tu dong top coin\n"
        "/auto_off - Tat bao"
    )

async def stoch_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text("Ban go: /stoch BTC hoac /stoch BTC 1h\nVD: /stoch PEPE 15m")
        return
    symbol = c.args[0]
    interval = c.args[1] if len(c.args)>1 else "4h"
    await u.message.reply_text(f"⏳ Dang check Stochastic {symbol.upper()} khung {interval}...")
    r = await asyncio.to_thread(analyze_stoch, symbol, interval)
    if not r:
        await u.message.reply_text(f"Khong tim thay coin {symbol}, ban check lai ten. VD: BTC, ETH, PEPE, WIF")
        return

    # Vẽ thanh Stochastic cho dễ nhìn
    bar_k = "█" * int(r['k']/10) + "░" * (10-int(r['k']/10))
    bar_d = "█" * int(r['d']/10) + "░" * (10-int(r['d']/10))

    msg = (
        f"📊 STOCH {r['symbol']} {interval.upper()} Gia ${r['price']:.6f}\n\n"
        f"%K: {r['k']:.2f}\n[{bar_k}] {r['k']:.0f}%\n\n"
        f"%D: {r['d']:.2f}\n[{bar_d}] {r['d']:.0f}%\n\n"
        f"{'✅ ' + r['signal'] if r['signal'] else '⚪️ Chua co signal ro rang - dang trung tinh'}\n\n"
        f"Nguong: <20 Qua Ban | >80 Qua Mua"
    )
    await u.message.reply_text(msg)

async def scan_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    interval = c.args[0] if c.args and c.args[0] in ["1h","4h","1d","15m","1m"] else "4h"
    await u.message.reply_text(f"⏳ Dang quet top 40 coin volume cao nhat Binance khung {interval}...")
    top = await asyncio.to_thread(get_top_coins, 40)
    found=[]
    for sym in top:
        r = await asyncio.to_thread(analyze_stoch, sym, interval)
        if r and r["signal"] and ("MUA MANH" in r["signal"] or "BAN MANH" in r["signal"]):
            found.append(f"{r['signal']} {r['symbol']} K {r['k']:.0f} D {r['d']:.0f} ${r['price']:.4f}")
    if not found:
        # Nếu không có MUA/BÁN mạnh thì lấy cả QUA BÁN/QUA MUA
        for sym in top:
            r = await asyncio.to_thread(analyze_stoch, sym, interval)
            if r and r["signal"]:
                found.append(f"{r['signal']} {r['symbol']} K {r['k']:.0f}")
        if found:
            await u.message.reply_text(f"📈 STOCH {interval} - Khong co MUA/BAN manh, co QUA BAN/MUA:\n" + "\n".join(found[:20]))
        else:
            await u.message.reply_text(f"⚪️ Khong co signal hot khung {interval}")
    else:
        await u.message.reply_text(f"🔥 STOCH HOT {interval.upper()}:\n" + "\n".join(found[:20]))

async def scan_oversold_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    interval = "4h"
    await u.message.reply_text(f"⏳ Dang tim coin QUA BAN <20 khung {interval} - Co hoi bat day...")
    top = await asyncio.to_thread(get_top_coins, 50)
    found=[]
    for sym in top:
        r = await asyncio.to_thread(analyze_stoch, sym, interval)
        if r and r["k"] < 20:
            found.append(f"🟢 QUA BAN {r['symbol']} K {r['k']:.1f} D {r['d']:.1f} ${r['price']:.4f} {r['signal'] or ''}")
    await u.message.reply_text(f"🟢 COIN QUA BAN <20 {interval}:\n" + "\n".join(found[:20]) if found else "Khong co coin qua ban")

async def scan_overbought_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    interval = "4h"
    await u.message.reply_text(f"⏳ Dang tim coin QUA MUA >80 khung {interval}...")
    top = await asyncio.to_thread(get_top_coins, 50)
    found=[]
    for sym in top:
        r = await asyncio.to_thread(analyze_stoch, sym, interval)
        if r and r["k"] > 80:
            found.append(f"🔴 QUA MUA {r['symbol']} K {r['k']:.1f} D {r['d']:.1f} ${r['price']:.4f}")
    await u.message.reply_text(f"🔴 COIN QUA MUA >80 {interval}:\n" + "\n".join(found[:20]) if found else "Khong co coin qua mua")

async def check_job(context: ContextTypes.DEFAULT_TYPE):
    if not subscribers: return
    top = await asyncio.to_thread(get_top_coins, 30)
    for sym in top:
        try:
            r = await asyncio.to_thread(analyze_stoch, sym, "4h")
            if not r or not r["signal"]: continue
            if "MUA MANH" in r["signal"]:
                msg = f"🟢🟢 STOCH MUA MANH {r['symbol']} 4h\nK {r['k']:.1f} D {r['d']:.1f} Qua ban <20 + Golden Cross\nGia ${r['price']:.4f} => Co hoi MUA!"
                for cid in list(subscribers):
                    try: await context.bot.send_message(chat_id=cid,text=msg)
                    except: pass
            elif "BAN MANH" in r["signal"]:
                msg = f"🔴🔴 STOCH BAN MANH {r['symbol']} 4h\nK {r['k']:.1f} D {r['d']:.1f} Qua mua >80 + Death Cross\nGia ${r['price']:.4f} => Canh CHOT!"
                for cid in list(subscribers):
                    try: await context.bot.send_message(chat_id=cid,text=msg)
                    except: pass
        except: continue

async def auto_on(u:Update,c:ContextTypes.DEFAULT_TYPE):
    subscribers.add(u.effective_chat.id); save_subs()
    if not c.job_queue.get_jobs_by_name("stoch_job"):
        c.job_queue.run_repeating(check_job,interval=1800,first=10,name="stoch_job")
    await u.message.reply_text("✅ DA BAT BAO STOCHASTIC!\n30 phut check 1 lan top 30 coin - Bao khi co MUA MANH <20 hoac BAN MANH >80 khung 4h")

async def auto_off(u:Update,c:ContextTypes.DEFAULT_TYPE):
    subscribers.discard(u.effective_chat.id); save_subs()
    await u.message.reply_text("🛑 Da tat bao Stochastic")

def run_flask(): app_flask.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))

if __name__=='__main__':
    try: asyncio.set_event_loop(asyncio.new_event_loop())
    except: pass
    threading.Thread(target=run_flask,daemon=True).start()
    app=Application.builder().token(TOKEN).read_timeout(30).write_timeout(30).connect_timeout(30).pool_timeout(30).build()
    app.add_handler(CommandHandler("start",start_cmd))
    app.add_handler(CommandHandler("stoch",stoch_cmd))
    app.add_handler(CommandHandler("scan",scan_cmd))
    app.add_handler(CommandHandler("scan_oversold",scan_oversold_cmd))
    app.add_handler(CommandHandler("scan_overbought",scan_overbought_cmd))
    app.add_handler(CommandHandler("auto_on",auto_on))
    app.add_handler(CommandHandler("auto_off",auto_off))
    app.job_queue.run_repeating(check_job,interval=1800,first=20,name="stoch_job")
    print("STOCHASTIC BOT RUNNING")
    app.run_polling()
