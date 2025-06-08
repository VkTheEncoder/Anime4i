#!/usr/bin/env python3
"""
Telegram HLS Downloader Bot with robust headers and dynamic Referer for both embed and direct playlists.

Configure credentials and optional cookies in a `.env` file:

    API_ID=123456
    API_HASH=abcdef1234567890abcdef1234567890
    BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ
    USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64)
    COOKIES=__stid=...; PHPSESSID=...

Install dependencies:
    pip install -r requirements.txt

Run:
    python3 bot.py

Send either:
  • A direct `.m3u8` URL
  • An embed page URL (`https://anime1u.com/embed/...`)

The bot will extract or download the playlist, set the appropriate Referer, then merge segments into one TS file.
"""
import os
import asyncio
import tempfile
import urllib.request
from urllib.parse import urljoin, urlparse
import copy
import re
from html.parser import HTMLParser

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ── Load env vars ───────────────────────────────────────────────────────────────
load_dotenv()
API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ── Base headers (User-Agent + optional Cookies) ─────────────────────────────────
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0")
COOKIES    = os.getenv("COOKIES", "")
BASE_HEADERS = {"User-Agent": USER_AGENT}
if COOKIES:
    BASE_HEADERS["Cookie"] = COOKIES

# ── Initialize Telegram client ───────────────────────────────────────────────────
client = TelegramClient("hls_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ── HTML parser to find <source src="...m3u8"> tags ──────────────────────────────
class M3U8SourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.m3u8_urls = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'source':
            for (k, v) in attrs:
                if k.lower() == 'src' and v and '.m3u8' in v:
                    self.m3u8_urls.append(v)

# ── Extract playlist from embed page ─────────────────────────────────────────────
def extract_m3u8_from_embed(embed_url: str, headers: dict) -> str:
    req = urllib.request.Request(embed_url, headers=headers)
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    # 1) HTML parser
    parser = M3U8SourceParser()
    parser.feed(html)
    if parser.m3u8_urls:
        return parser.m3u8_urls[0]
    # 2) Regex fallback
    regex = re.compile(r'(https?://[^\s\'\"]+\.m3u8[^\s\'\"]*)')
    m = regex.search(html)
    if m:
        return m.group(1)
    raise ValueError("No .m3u8 URL found in embed page HTML.")

# ── Download and merge HLS segments ───────────────────────────────────────────────
def download_hls_sync(m3u8_url: str, output_ts: str, headers: dict):
    req = urllib.request.Request(m3u8_url, headers=headers)
    playlist = urllib.request.urlopen(req).read().decode().splitlines()

    base = m3u8_url.rsplit('/', 1)[0] + '/'
    segments = []
    for line in playlist:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        segments.append(line if line.startswith('http') else urljoin(base, line))

    with open(output_ts, 'wb') as f:
        for i, seg_url in enumerate(segments, 1):
            print(f"[{i}/{len(segments)}] Downloading: {seg_url}")
            seg_req = urllib.request.Request(seg_url, headers=headers)
            f.write(urllib.request.urlopen(seg_req).read())

# ── Async wrapper ────────────────────────────────────────────────────────────────
async def download_hls(m3u8_url: str, output_ts: str, headers: dict):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, download_hls_sync, m3u8_url, output_ts, headers)

# ── Message handler ──────────────────────────────────────────────────────────────
@client.on(events.NewMessage)
async def on_message(event):
    text = event.raw_text.strip()
    headers = copy.deepcopy(BASE_HEADERS)

    # Determine playlist source
    if '/embed/' in text:
        embed_url = text
        await event.reply("🔍 Extracting playlist from embed page…")
        try:
            m3u8_url = extract_m3u8_from_embed(embed_url, headers)
        except Exception as e:
            return await event.reply(f"❌ Extraction failed: {e}")
        # Use embed page as Referer
        headers['Referer'] = embed_url
    elif text.endswith('.m3u8') or '.m3u8?' in text:
        m3u8_url = text
        # Derive Referer from playlist host
        p = urlparse(m3u8_url)
        headers['Referer'] = f"{p.scheme}://{p.netloc}/"
    else:
        return  # ignore unrelated messages

    status = await event.reply("⏳ Downloading & merging… this may take a moment.")
    tmpdir = tempfile.mkdtemp()
    out_ts = os.path.join(tmpdir, 'output.ts')

    try:
        await download_hls(m3u8_url, out_ts, headers)
    except Exception as e:
        return await status.edit(f"❌ Download failed: {e}")

    await client.send_file(
        event.chat_id,
        out_ts,
        caption="✅ Here’s your merged stream!",
        force_document=True,
        allow_cache=False,
    )
    await status.delete()

# ── Start bot ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("🚀 Bot started – ready for .m3u8 or embed links…")
    client.run_until_disconnected()
