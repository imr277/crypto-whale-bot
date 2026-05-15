import os
import time
import json
import hashlib
import requests
from datetime import datetime, timezone
from xml.etree import ElementTree

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
INTERVAL = int(os.environ.get("INTERVAL_MINUTES", "3"))
MIN_WHALE_USD = int(os.environ.get("MIN_WHALE_USD", "500000"))

TG_URL = f"https://api.telegram.org/bot{TOKEN}"

seen = set()

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def send_telegram(text):
    try:
        r = requests.post(f"{TG_URL}/sendMessage", json={
            "chat_id": CHAT_ID,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
        data = r.json()
        if not data.get("ok"):
            log(f"Telegram error: {data.get('description')}")
            return False
        return True
    except Exception as e:
        log(f"Telegram exception: {e}")
        return False

def uid(text):
    return hashlib.md5(text.encode()).hexdigest()[:12]

def fmt(n):
    if n >= 1_000_000_000: return f"${n/1_000_000_000:.2f}B"
    if n >= 1_000_000: return f"${n/1_000_000:.1f}M"
    if n >= 1_000: return f"${n/1_000:.0f}K"
    return f"${n:.0f}"

# ─── WHALE ALERT ─────────────────────────────────────────────────────────────

def fetch_whale_alert():
    """Surveille les gros mouvements via Whale Alert RSS"""
    try:
        r = requests.get(
            "https://api.allorigins.win/get?url=" + requests.utils.quote("https://api.whale-alert.io/v1/transactions?api_key=free&min_value=500000&limit=20"),
            timeout=8
        )
        data = r.json().get("contents", "{}")
        txs = json.loads(data).get("transactions", [])
        alerts = []
        for tx in txs:
            tid = str(tx.get("id", ""))
            if tid in seen:
                continue
            seen.add(tid)
            amount_usd = tx.get("amount_usd", 0)
            if amount_usd < MIN_WHALE_USD:
                continue
            symbol = tx.get("symbol", "").upper()
            amount = tx.get("amount", 0)
            from_owner = tx.get("from", {}).get("owner", "unknown")
            to_owner = tx.get("to", {}).get("owner", "unknown")
            from_type = tx.get("from", {}).get("owner_type", "")
            to_type = tx.get("to", {}).get("owner_type", "")
            alerts.append({
                "id": tid,
                "symbol": symbol,
                "amount": amount,
                "amount_usd": amount_usd,
                "from": from_owner,
                "to": to_owner,
                "from_type": from_type,
                "to_type": to_type,
                "hash": tx.get("hash", ""),
            })
        return alerts
    except Exception as e:
        log(f"Whale Alert error: {e}")
        return []

def interpret_whale(w):
    """Interprète le sens du mouvement"""
    from_ex = any(k in w["from"].lower() for k in ["binance","coinbase","kraken","okx","bybit","huobi","exchange"])
    to_ex = any(k in w["to"].lower() for k in ["binance","coinbase","kraken","okx","bybit","huobi","exchange"])
    from_type = w.get("from_type", "")
    to_type = w.get("to_type", "")

    if to_ex and not from_ex:
        return "⚠️ VENTE PROBABLE", "La baleine envoie vers un exchange — vente potentielle imminente"
    if from_ex and not to_ex:
        return "🟢 ACCUMULATION", "La baleine retire d'un exchange vers cold wallet — accumulation, signal haussier"
    if from_type == "exchange" and to_type == "exchange":
        return "🔄 TRANSFERT EXCHANGE", "Mouvement inter-exchanges — surveillance requise"
    return "🐋 MOUVEMENT BALEINE", "Gros mouvement détecté — origine ou destination inconnue"

# ─── SOURCES RSS CRYPTO ───────────────────────────────────────────────────────

RSS_SOURCES = [
    {"name": "CoinDesk",        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "Cointelegraph",   "url": "https://cointelegraph.com/rss"},
    {"name": "The Block",       "url": "https://www.theblock.co/rss.xml"},
    {"name": "Decrypt",         "url": "https://decrypt.co/feed"},
    {"name": "Bitcoin Magazine","url": "https://bitcoinmagazine.com/feed"},
    {"name": "CryptoSlate",     "url": "https://cryptoslate.com/feed/"},
    {"name": "BeInCrypto",      "url": "https://beincrypto.com/feed/"},
    {"name": "Blockworks",      "url": "https://blockworks.co/feed"},
]

REDDIT_SOURCES = [
    {"name": "r/CryptoCurrency","url": "https://www.reddit.com/r/CryptoCurrency/hot.json?limit=15"},
    {"name": "r/Bitcoin",       "url": "https://www.reddit.com/r/Bitcoin/hot.json?limit=10"},
    {"name": "r/ethereum",      "url": "https://www.reddit.com/r/ethereum/hot.json?limit=10"},
    {"name": "r/solana",        "url": "https://www.reddit.com/r/solana/hot.json?limit=10"},
    {"name": "r/altcoin",       "url": "https://www.reddit.com/r/altcoin/hot.json?limit=10"},
    {"name": "r/defi",          "url": "https://www.reddit.com/r/defi/hot.json?limit=10"},
]

TELEGRAM_SOURCES = [
    {"name": "@WhaleCryptoClub","url": "https://rsshub.app/telegram/channel/WhaleCryptoClub"},
    {"name": "@CoinDesk",       "url": "https://rsshub.app/telegram/channel/CoinDeskNews"},
    {"name": "@Cointelegraph",  "url": "https://rsshub.app/telegram/channel/cointelegraph"},
    {"name": "@whale_alert_io", "url": "https://rsshub.app/telegram/channel/whale_alert_io"},
    {"name": "@cryptonewscom",  "url": "https://rsshub.app/telegram/channel/cryptonewscom"},
    {"name": "@BitcoinMagazine","url": "https://rsshub.app/telegram/channel/bitcoinmagazine"},
]

YOUTUBE_SOURCES = [
    {"name": "Coin Bureau",     "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCqK_GSMbpiV8spgD3ZGloSw"},
    {"name": "Benjamin Cowen",  "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCRvqjQPSeaWn-uEx-w0XOIg"},
    {"name": "Altcoin Daily",   "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCbLhGKVY-bJPcawebgtNfbw"},
]

HIGH_VALUE_KEYWORDS = [
    "hack","exploit","breach","stolen","rugpull",
    "etf","approved","rejected","sec","regulation","ban","legal",
    "listing","delisting","binance","coinbase",
    "partnership","acquisition","launch","mainnet",
    "crash","surge","pump","dump","ath","all-time high",
    "bankruptcy","insolvent","seized","arrested",
    "whale","million","billion","massive","huge",
    "breaking","urgent","flash","alert","just in",
    "fed","rate","inflation","fomc",
]

def fetch_rss(src):
    try:
        r = requests.get(
            f"https://api.allorigins.win/get?url={requests.utils.quote(src['url'])}",
            timeout=8
        )
        j = r.json()
        xml = ElementTree.fromstring(j["contents"])
        items = xml.findall(".//item") or xml.findall(".//{http://www.w3.org/2005/Atom}entry")
        news = []
        for i in items[:10]:
            title = (i.findtext("title") or i.findtext("{http://www.w3.org/2005/Atom}title") or "").replace("<![CDATA[","").replace("]]>","").strip()
            link = (i.findtext("link") or "").strip()
            if title and len(title) > 10:
                news.append({"title": title, "link": link, "source": src["name"]})
        return news
    except:
        return []

def fetch_reddit(src):
    try:
        r = requests.get(src["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        posts = r.json().get("data", {}).get("children", [])
        news = []
        for p in posts:
            d = p.get("data", {})
            if d.get("stickied"): continue
            title = d.get("title", "")
            ups = d.get("ups", 0)
            if title and len(title) > 10 and ups > 200:
                news.append({
                    "title": title,
                    "link": "https://reddit.com" + d.get("permalink",""),
                    "source": src["name"],
                    "ups": ups
                })
        return news
    except:
        return []

def fetch_all_news():
    all_news = []
    for src in RSS_SOURCES:
        all_news.extend(fetch_rss(src))
    for src in TELEGRAM_SOURCES:
        all_news.extend(fetch_rss(src))
    for src in YOUTUBE_SOURCES:
        all_news.extend(fetch_rss(src))
    for src in REDDIT_SOURCES:
        all_news.extend(fetch_reddit(src))
    return all_news

def is_high_value(title):
    t = title.lower()
    return any(k in t for k in HIGH_VALUE_KEYWORDS)

# ─── FUNDING RATES ────────────────────────────────────────────────────────────

def fetch_funding_rates():
    """Récupère les funding rates extrêmes depuis Binance"""
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=8)
        data = r.json()
        extremes = []
        for item in data:
            rate = float(item.get("lastFundingRate", 0))
            symbol = item.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            rate_pct = rate * 100
            if abs(rate_pct) >= 0.1:  # Seuil extrême
                extremes.append({
                    "symbol": symbol.replace("USDT",""),
                    "rate": rate_pct,
                    "price": float(item.get("markPrice", 0))
                })
        return sorted(extremes, key=lambda x: abs(x["rate"]), reverse=True)[:5]
    except Exception as e:
        log(f"Funding rates error: {e}")
        return []

# ─── ANALYSE IA ───────────────────────────────────────────────────────────────

def analyze_whale(whale, interpretation):
    if not ANTHROPIC_KEY:
        return None
    try:
        prompt = (
            f"Tu es un expert en trading crypto et analyse on-chain.\\n\\n"
            f"MOUVEMENT DÉTECTÉ :\\n"
            f"Crypto : {whale['symbol']}\\n"
            f"Montant : {fmt(whale['amount_usd'])} ({whale['amount']:,.0f} {whale['symbol']})\\n"
            f"De : {whale['from']}\\n"
            f"Vers : {whale['to']}\\n"
            f"Interprétation initiale : {interpretation[1]}\\n\\n"
            f"Analyse en 3 points ultra-courts en français :\\n"
            f"1. Impact probable sur le prix à court terme\\n"
            f"2. Action recommandée (Acheter / Vendre / Attendre)\\n"
            f"3. Niveau de confiance (Faible/Moyen/Fort)"
        )
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 200, "messages": [{"role": "user", "content": prompt}]},
            timeout=20
        )
        return r.json()["content"][0]["text"].strip()
    except:
        return None

def analyze_news(item):
    if not ANTHROPIC_KEY:
        return None
    try:
        prompt = (
            f"Tu es un expert en trading crypto.\\n\\n"
            f"NEWS : {item['title']}\\n"
            f"SOURCE : {item['source']}\\n\\n"
            f"Réponds en JSON strict :\\n"
            f'{{\"score\": <1-10>, \"impact\": \"<HAUSSIER/BAISSIER/NEUTRE>\", \"crypto\": \"<crypto concernée ou ALL>\", \"action\": \"<ACHETER/VENDRE/ATTENDRE>\", \"analyse\": \"<2 phrases max en français>\"}}\\n\\n'
            f"7+ = opportunité réelle"
        )
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 200, "messages": [{"role": "user", "content": prompt}]},
            timeout=20
        )
        text = r.json()["content"][0]["text"].strip().replace("```json","").replace("```","").strip()
        return json.loads(text)
    except:
        return None

# ─── BOUCLE PRINCIPALE ────────────────────────────────────────────────────────

def run_whale_check():
    log("Scan baleines...")
    whales = fetch_whale_alert()
    for w in whales:
        interp_label, interp_text = interpret_whale(w)
        analysis = analyze_whale(w, (interp_label, interp_text))
        impact_icon = "🔴" if "VENTE" in interp_label else "🟢" if "ACCUMULATION" in interp_label else "🔄"
        msg = (
            f"{impact_icon} <b>MOUVEMENT BALEINE</b>\\n\\n"
            f"💰 {fmt(w['amount_usd'])} en {w['symbol']}\\n"
            f"📤 De : {w['from']}\\n"
            f"📥 Vers : {w['to']}\\n\\n"
            f"{interp_label}\\n{interp_text}\\n"
        )
        if analysis:
            msg += f"\\n🤖 <b>Analyse IA</b>\\n{analysis}"
        if w.get("hash"):
            msg += f"\\n\\n🔗 https://blockchain.info/tx/{w['hash']}"
        send_telegram(msg)
        log(f"Alerte baleine : {w['symbol']} {fmt(w['amount_usd'])}")
        time.sleep(2)

def run_news_check():
    log("Scan news crypto...")
    news = fetch_all_news()
    sent = 0
    for item in news:
        nid = uid(item["title"] + item["source"])
        if nid in seen:
            continue
        seen.add(nid)
        if not is_high_value(item["title"]):
            continue
        data = analyze_news(item)
        if not data:
            continue
        score = int(data.get("score", 0))
        if score < 7:
            log(f"Score {score}/10 ignoré : {item['title'][:50]}")
            continue
        impact = data.get("impact", "NEUTRE")
        action = data.get("action", "ATTENDRE")
        crypto = data.get("crypto", "")
        analyse = data.get("analyse", "")
        impact_icon = "🟢" if impact == "HAUSSIER" else "🔴" if impact == "BAISSIER" else "⚪"
        action_icon = "📈" if action == "ACHETER" else "📉" if action == "VENDRE" else "⏳"
        msg = (
            f"{impact_icon} <b>SIGNAL CRYPTO [{score}/10] — {item['source'].upper()}</b>\\n\\n"
            f"📰 {item['title']}\\n"
            f"{f'🔗 {item[chr(34)link{chr(34)}]}' if item.get('link') else ''}\\n\\n"
            f"Crypto : <b>{crypto}</b>\\n"
            f"Impact : <b>{impact}</b>\\n"
            f"{action_icon} Action : <b>{action}</b>\\n\\n"
            f"🤖 {analyse}"
        )
        if send_telegram(msg):
            sent += 1
            log(f"Alerte news [{score}/10] : {item['title'][:50]}")
        time.sleep(2)
        if sent >= 3:
            break
    if sent == 0:
        log("Aucune news à haute valeur")

def run_funding_check():
    log("Scan funding rates...")
    extremes = fetch_funding_rates()
    if not extremes:
        return
    alerts = [f for f in extremes if abs(f["rate"]) >= 0.15]
    if not alerts:
        return
    fid = uid("funding" + str(alerts[0]["rate"]) + alerts[0]["symbol"])
    if fid in seen:
        return
    seen.add(fid)
    lines = []
    for f in alerts:
        direction = "LONG extrême 🔴" if f["rate"] > 0 else "SHORT extrême 🟢"
        lines.append(f"• {f['symbol']} : {f['rate']:+.3f}% ({direction})")
    msg = (
        f"⚡ <b>FUNDING RATES EXTRÊMES</b>\\n\\n"
        f"Quand le funding est extrême, le marché fait souvent l'inverse :\\n\\n"
        f"{chr(10).join(lines)}\\n\\n"
        f"💡 Funding très positif = trop de longs = risque de liquidation en cascade\\n"
        f"💡 Funding très négatif = trop de shorts = risque de short squeeze"
    )
    send_telegram(msg)
    log(f"Alerte funding rates : {len(alerts)} cryptos")

def main():
    log("=== Bot Crypto Whale Intelligence démarré ===")
    if not TOKEN or not CHAT_ID:
        log("ERREUR : TOKEN ou CHAT_ID manquant")
        return

    total_sources = len(RSS_SOURCES) + len(REDDIT_SOURCES) + len(TELEGRAM_SOURCES) + len(YOUTUBE_SOURCES)
    send_telegram(
        f"🐋 <b>Bot Crypto Whale Intelligence démarré</b>\\n\\n"
        f"✅ {total_sources} sources surveillées\\n"
        f"✅ Baleines : mouvements > {fmt(MIN_WHALE_USD)}\\n"
        f"✅ Funding rates extrêmes\\n"
        f"✅ News crypto score IA\\n"
        f"✅ Scan toutes les {INTERVAL} min\\n"
        f"✅ Analyse IA : {'activée' if ANTHROPIC_KEY else 'désactivée'}\\n\\n"
        f"Tu recevras une alerte dès qu'une baleine bouge ou qu'un signal fort est détecté."
    )

    cycle = 0
    while True:
        cycle += 1
        run_whale_check()
        run_news_check()
        if cycle % 4 == 0:  # Funding rates toutes les 12 min
            run_funding_check()
        log(f"Prochain scan dans {INTERVAL} min...")
        time.sleep(INTERVAL * 60)

if __name__ == "__main__":
    main()
