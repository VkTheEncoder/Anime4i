#!/usr/bin/env python3
"""
Telegram HLS Downloader Bot with robust embed extraction and dynamic headers.

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

The bot will extract (via HTML parsing + regex) and download the playlist, then merge segments into one TS file.
"""
import os
import asyncio
import tempfile
import urllib.request
from urllib.parse import urljoin
import copy
import re
from html.parser import HTMLParser

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ── Load environment variables ─────────────────────────────────────────────────
load_dotenv()
API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ── Base headers for requests ───────────────────────────────────────────────────
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0")
COOKIES    = os.getenv("COOKIES", "")
BASE_HEADERS = {"User-Agent": USER_AGENT}
if COOKIES:
    BASE_HEADERS["Cookie"] = COOKIES

# ── Initialize Telegram bot client ──────────────────────────────────────────────
client = TelegramClient("hls_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ── HTML parser to find <source> tags with .m3u8 ─────────────────────────────────
class M3U8SourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.m3u8_urls = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'source':
            for (k, v) in attrs:
                if k.lower() == 'src' and v and '.m3u8' in v:
                    self.m3u8_urls.append(v)

# ── Extract .m3u8 URL from embed HTML ────────────────────────────────────────────
def extract_m3u8_from_embed(embed_url: str) -> str:
    req = urllib.request.Request(embed_url, headers=BASE_HEADERS)
    resp = urllib.request.urlopen(req)
    html = resp.read().decode('utf-8', errors='ignore')

    # 1) Try HTML parsing for <source src="...m3u8">
    parser = M3U8SourceParser()
    parser.feed(html)
    if parser.m3u8_urls:
        return parser.m3u8_urls[0]

    # 2) Fallback: regex search
    # Find any http(s) link ending with .m3u8
    regex = re.compile(r'(https?://[^\s\'\"]+\.m3u8[^\s\'\"]*)')
    m = regex.search(html)
    if m:
        return m.group(1)

    # 3) If still not found, error out
    raise ValueError("No .m3u8 URL found in embed page HTML.")

# ── Download + merge HLS segments synchronously ─────────────────────────────────
def download_hls_sync(m3u8_url: str, output_ts: str, headers: dict):
    # Fetch playlist
    req = urllib.request.Request(m3u8_url, headers=headers)
    playlist = urllib.request.urlopen(req).read().decode().splitlines()

    base = m3u8_url.rsplit('/', 1)[0] + '/'
    segments = []
    for line in playlist:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        segments.append(line if line.startswith('http') else urljoin(base, line))

    # Download each segment and append
    with open(output_ts, 'wb') as f:
        for i, seg_url in enumerate(segments, 1):
            print(f"[{i}/{len(segments)}] Downloading: {seg_url}")
            req = urllib.request.Request(seg_url, headers=headers)
            data = urllib.request.urlopen(req).read()
            f.write(data)

# ── Async wrapper ───────────────────────────────────────────────────────────────
async def download_hls(m3u8_url: str, output_ts: str, headers: dict):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, download_hls_sync, m3u8_url, output_ts, headers)

# ── Telegram message handler ─────────────────────────────────────────────────────
@client.on(events.NewMessage)
async def on_message(event):
    text = event.raw_text.strip()
    headers = copy.deepcopy(BASE_HEADERS)

    # Determine link type
    if '/embed/' in text:
        embed_url = text
        await event.reply("🔍 Extracting playlist URL from embed page…")
        try:
            m3u8_url = extract_m3u8_from_embed(embed_url)
        except Exception as e:
            return await event.reply(f"❌ Extraction failed: {e}")
        # Set Referer for subsequent requests
        headers['Referer'] = embed_url
    elif text.endswith('.m3u8') or '.m3u8?' in text:
        m3u8_url = text
        # Optionally set Referer to domain
        # headers['Referer'] = 'https://anime1u.com/'
    else:
        return  # ignore unrelated messages

    status = await event.reply("⏳ Downloading and merging… please wait.")
    tmpdir = tempfile.mkdtemp()
    out_path = os.path.join(tmpdir, 'output.ts')

    try:
        await download_hls(m3u8_url, out_path, headers)
    except Exception as e:
        return await status.edit(f"❌ Download failed: {e}")

    # Send merged file
    await client.send_file(
        event.chat_id,
        out_path,
        caption="✅ Here’s your merged stream!",
        force_document=True,
        allow_cache=False,
    )
    await status.delete()

# ── Run the bot ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("🚀 Bot started – listening for embed or .m3u8 URLs…")
    client.run_until_disconnected()
