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
def home(): return f"STOCHASTIC FINAL FIX - {len(subscribers)} users - OK"

def get_klines(symbol, interval, limit=50):
    try:
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
        k = 50 if highest==lowest else (closes[i]-lowest)/(highest-lowest)*100
        k_values.append(k)
    d_values=[]
    for i in range(len(k_values)):
        if i+1 < d_period or k_values[i] is None:
            d_values.append(None)
        else:
            valid=[x for x in k_values[i+1-d_period:i+1] if x is not None]
            d_values.append(sum(valid)/d_period if len(valid)==d_period else None)
    if k_values[-1] is None or d_values[-1] is None: return None
    return {"k":k_values[-1],"d":d_values[-1],"k_prev":k_values[-2],"d_prev":d_values[-2]}

def analyze_stoch(symbol_input, interval):
    data, symbol = get_klines(symbol_input, interval, 50)
    if not data: return None
    stoch = calc_stoch(data["highs"], data["lows"], data["closes"])
    if not stoch: return None
    k,d = stoch["k"], stoch["d"]
    k_prev,d_prev = stoch["k_prev"], stoch["d_prev"]
    signal=None
    if k<20 and d<20 and k_prev<d_prev and k>d:
        signal=f"🟢 MUA MANH - Qua ban <20 + Golden Cross"
    elif k>80 and d>80 and k_prev>d_prev and k<d:
        signal=f"🔴 BAN MANH - Qua mua >80 + Death Cross"
    elif k_prev<d_prev and k>d:
        signal=f"🟢 MUA - Golden Cross K {k:.0f} D {d:.0f}"
    elif k_prev>d_prev and k<d:
        signal=f"🔴 BAN - Death Cross K {k:.0f} D {d:.0f}"
    elif k<20:
        signal=f"🟡 QUA BAN <20 K {k:.0f}"
    elif k>80:
        signal=f"🟡 QUA MUA >80 K {k:.0f}"
    return {"symbol":symbol.replace("USDT",""),"full_symbol":symbol,"interval":interval,"price":data["closes"][-1],"k":k,"d":d,"signal":signal,"k_prev":k_prev,"d_prev":d_prev}

def get_top_coins(limit=40):
    try:
        url="https://data-api.binance.vision/api/v3/ticker/24hr"
        r=requests.get(url,timeout=10).json()
        usdt=[x for x in r if x["symbol"].endswith("USDT")]
        s=sorted(usdt,key=lambda x: float(x["quoteVolume"]),reverse=True)
        return [x["symbol"] for x in s[:limit]]
    except:
        return ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT"]

async def start_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("📈 BOT STOCHASTIC FINAL FIX\n\n/stoch BTC - Check coin bat ky\n/stoch SOL 1h\n/scan - Quet top 40 coin hot 4h\n/scan_oversold - Coin qua ban <20\n/scan_overbought - Coin qua mua >80\n/auto_on - Bat bao tu dong\n/auto_off - Tat")

async def stoch_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text("Go: /stoch BTC hoac /stoch PEPE 15m"); return
    symbol=c.args[0]; interval=c.args[1] if len(c.args)>1 else "4h"
    await u.message.reply_text(f"⏳ Check {symbol.upper()} {interval}...")
    r=await asyncio.to_thread(analyze_stoch,symbol,interval)
    if not r:
        await u.message.reply_text(f"Khong tim thay {symbol}"); return
    await u.message.reply_text(f"📊 STOCH {r['symbol']} {interval.upper()} ${r['price']:.4f}\nK: {r['k']:.1f} D: {r['d']:.1f}\n{r['signal'] or 'Trung tinh'}")

async def scan_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    interval=c.args[0] if c.args and c.args[0] in ["1h","4h","1d","15m"] else "4h"
    await u.message.reply_text(f"⏳ Quet top 40 coin {interval}...")
    top=await asyncio.to_thread(get_top_coins,40)
    found=[]
    for sym in top:
        r=await asyncio.to_thread(analyze_stoch,sym,interval)
        if r and r["signal"] and ("MUA MANH" in r["signal"] or "BAN MANH" in r["signal"]):
            found.append(f"{r['signal']} {r['symbol']} ${r['price']:.3f}")
    if not found:
        for sym in top:
            r=await asyncio.to_thread(analyze_stoch,sym,interval)
            if r and r["signal"]:
                found.append(f"{r['signal']} {r['symbol']}")
    await u.message.reply_text(f"🔥 STOCH {interval}:\n"+"\n".join(found[:20]) if found else f"Khong co signal hot {interval}")

async def scan_oversold_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("⏳ Tim coin QUA BAN <20...")
    top=await asyncio.to_thread(get_top_coins,50)
    found=[]
    for sym in top:
        r=await asyncio.to_thread(analyze_stoch,sym,"4h")
        if r and r["k"]<20:
            found.append(f"🟢 QUA BAN {r['symbol']} K {r['k']:.0f} D {r['d']:.0f} ${r['price']:.4f}")
    await u.message.reply_text("\n".join(found[:20]) if found else "Khong co coin qua ban")

async def scan_overbought_cmd(u:Update,c:ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("⏳ Tim coin QUA MUA >80...")
    top=await asyncio.to_thread(get_top_coins,50)
    found=[]
    for sym in top:
        r=await asyncio.to_thread(analyze_stoch,sym,"4h")
        if r and r["k"]>80:
            found.append(f"🔴 QUA MUA {r['symbol']} K {r['k']:.0f} ${r['price']:.4f}")
    await u.message.reply_text("\n".join(found[:20]) if found else "Khong co coin qua mua")

async def check_job(context: ContextTypes.DEFAULT_TYPE):
    if not subscribers: return
    top=await asyncio.to_thread(get_top_coins,30)
    for sym in top:
        try:
            r=await asyncio.to_thread(analyze_stoch,sym,"4h")
            if not r or not r["signal"]: continue
            if "MUA MANH" in r["signal"] or "BAN MANH" in r["signal"]:
                msg=f"{'🟢🟢' if 'MUA' in r['signal'] else '🔴🔴'} {r['signal']}\n{r['symbol']} 4h K {r['k']:.0f} D {r['d']:.0f} Gia ${r['price']:.4f}"
                for cid in list(subscribers):
                    try: await context.bot.send_message(chat_id=cid,text=msg)
                    except: pass
        except: continue

async def auto_on(u:Update,c:ContextTypes.DEFAULT_TYPE):
    subscribers.add(u.effective_chat.id); save_subs()
    if not c.job_queue.get_jobs_by_name("stoch_job"):
        c.job_queue.run_repeating(check_job,interval=1800,first=10,name="stoch_job")
    await u.message.reply_text("✅ DA BAT AUTO STOCHASTIC - 30p check 1 lan")

async def auto_off(u:Update,c:ContextTypes.DEFAULT_TYPE):
    subscribers.discard(u.effective_chat.id); save_subs()
    await u.message.reply_text("🛑 Da tat auto")

def run_flask(): app_flask.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))

if __name__=='__main__':
    threading.Thread(target=run_flask,daemon=True).start()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start_cmd))
    app.add_handler(CommandHandler("stoch",stoch_cmd))
    app.add_handler(CommandHandler("scan",scan_cmd))
    app.add_handler(CommandHandler("scan_oversold",scan_oversold_cmd))
    app.add_handler(CommandHandler("scan_overbought",scan_overbought_cmd))
    app.add_handler(CommandHandler("auto_on",auto_on))
    app.add_handler(CommandHandler("auto_off",auto_off))
    app.job_queue.run_repeating(check_job,interval=1800,first=20,name="stoch_job")
    print("STOCHASTIC FINAL FIX RUNNING")
    app.run_polling()
