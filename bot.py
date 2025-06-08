#!/usr/bin/env python3
"""
Telegram HLS Downloader with configurable login (bot or user) and automatic TS→MP4 remux.

Configure your `.env`:

    API_ID=123456          # from my.telegram.org
    API_HASH=abcdef1234567890abcdef1234567890
    BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ  # optional, for bot login (50 MB limit)
    USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64)
    # Optional cookies for restricted streams
    COOKIES=__stid=...; PHPSESSID=...

Install dependencies:
    pip install -r requirements.txt

Install ffmpeg so it’s on your PATH.

Run:
    python3 bot.py

Login:
  • If `BOT_TOKEN` is set in `.env`, the script logs in as a bot (no prompts).
  • Otherwise, it logs in as a user (phone/code prompt once, session saved).

Send the bot either:
  • A direct `.m3u8` URL
  • An embed link (`https://anime1u.com/embed/...`)

It downloads HLS segments, merges into TS, remuxes to MP4, and uploads.
"""
import os
import asyncio
import tempfile
import subprocess
import urllib.request
from urllib.parse import urljoin, urlparse
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

# ── Initialize Telethon client (bot or user) ────────────────────────────────────
session_name = "hls_session"
if BOT_TOKEN:
    # login as bot account (50 MB upload limit)
    client = TelegramClient(session_name, API_ID, API_HASH) \
        .start(bot_token=BOT_TOKEN)
    print("🚀 Logged in as BOT (50 MB file limit)")
else:
    # login as user account (2 GB upload limit)
    client = TelegramClient(session_name, API_ID, API_HASH)
    client.start()
    print("🚀 Logged in as USER (2 GB file limit), session saved")

# ── HTML parser for <source src="...m3u8"> tags ─────────────────────────────────
class M3U8SourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'source':
            for k, v in attrs:
                if k.lower() == 'src' and v and '.m3u8' in v:
                    self.urls.append(v)

def extract_m3u8(embed_url: str, headers: dict) -> str:
    req = urllib.request.Request(embed_url, headers=headers)
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    # 1) parse <source src>
    parser = M3U8SourceParser()
    parser.feed(html)
    if parser.urls:
        return parser.urls[0]
    # 2) regex fallback
    m = re.search(r"(https?://[^\s'\"]+\.m3u8[^\s'\"]*)", html)
    if m:
        return m.group(1)
    raise ValueError("No .m3u8 URL found in embed page HTML.")

# ── Download and merge HLS segments ───────────────────────────────────────────────
def download_hls_sync(m3u8_url: str, ts_path: str, headers: dict):
    req = urllib.request.Request(m3u8_url, headers=headers)
    playlist = urllib.request.urlopen(req).read().decode().splitlines()
    base = m3u8_url.rsplit('/', 1)[0] + '/'
    segments = [line if line.startswith('http') else urljoin(base, line)
                for line in playlist if line and not line.startswith('#')]
    with open(ts_path, 'wb') as f:
        for idx, seg in enumerate(segments, 1):
            print(f"[{idx}/{len(segments)}] Downloading: {seg}")
            data = urllib.request.urlopen(urllib.request.Request(seg, headers=headers)).read()
            f.write(data)

async def download_hls(m3u8_url: str, ts_path: str, headers: dict):
    await asyncio.get_event_loop().run_in_executor(
        None, download_hls_sync, m3u8_url, ts_path, headers
    )

# ── Telegram message handler ─────────────────────────────────────────────────────
@client.on(events.NewMessage)
async def handler(event):
    text = event.raw_text.strip()
    hdrs = copy.deepcopy(BASE_HEADERS)

    # determine playlist URL
    if '/embed/' in text:
        embed = text
        await event.reply("🔍 Extracting playlist URL from embed page…")
        try:
            m3u8_url = extract_m3u8(embed, hdrs)
        except Exception as e:
            return await event.reply(f"❌ Extraction failed: {e}")
        hdrs['Referer'] = embed
    elif text.endswith('.m3u8') or '.m3u8?' in text:
        m3u8_url = text
        p = urlparse(m3u8_url)
        hdrs['Referer'] = f"{p.scheme}://{p.netloc}/"
    else:
        return  # ignore others

    status = await event.reply("⏳ Downloading and merging… please wait.")
    tmp = tempfile.mkdtemp()
    ts_path = os.path.join(tmp, 'output.ts')
    mp4_path = os.path.join(tmp, 'output.mp4')

    try:
        await download_hls(m3u8_url, ts_path, hdrs)
    except Exception as e:
        return await status.edit(f"❌ Download failed: {e}")

    # remux to MP4 (fast, no re-encode)
    subprocess.run(['ffmpeg', '-i', ts_path, '-c', 'copy', mp4_path], check=True)

    # send MP4
    await client.send_file(
        event.chat_id,
        mp4_path,
        caption="✅ Here’s your merged stream (MP4)!",
        force_document=True, allow_cache=False
    )
    await status.delete()

# ── Run the bot/service ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("🔔 Bot is up — waiting for links…")
    client.run_until_disconnected()
