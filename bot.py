import os
import asyncio
import tempfile
import urllib.request
from urllib.parse import urljoin
import copy
import re

from dotenv import load_dotenv
from telethon import TelegramClient, events

# ── Load environment variables ─────────────────────────────────────────────────
load_dotenv()
API_ID    = int(os.getenv("API_ID"))
API_HASH  = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ── Base headers (User-Agent + optional cookies) ────────────────────────────────
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0")
COOKIES    = os.getenv("COOKIES", "")
BASE_HEADERS = {"User-Agent": USER_AGENT}
if COOKIES:
    BASE_HEADERS["Cookie"] = COOKIES

# ── Initialize Telegram client ───────────────────────────────────────────────────
client = TelegramClient("hls_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ── Extract .m3u8 from an embed HTML page ─────────────────────────────────────────
def extract_m3u8_from_embed(embed_url: str, headers: dict) -> str:
    req = urllib.request.Request(embed_url, headers=headers)
    html = urllib.request.urlopen(req).read().decode('utf-8')
    # Match any http(s) URL ending with .m3u8
    match = re.search(r'(https?://[^\s\'\"]+\.m3u8[^\s\'\"]*)', html)
    if not match:
        raise ValueError("No .m3u8 URL found in embed page HTML.")
    return match.group(1)

# ── Synchronous HLS download + merge ─────────────────────────────────────────────
def download_hls_sync(m3u8_url: str, output_path: str, headers: dict):
    req = urllib.request.Request(m3u8_url, headers=headers)
    playlist = urllib.request.urlopen(req).read().decode().splitlines()
    base = m3u8_url.rsplit('/', 1)[0] + '/'
    segments = [
        line if line.startswith('http') else urljoin(base, line)
        for line in playlist if line and not line.startswith('#')
    ]
    with open(output_path, 'wb') as wf:
        for i, seg_url in enumerate(segments, 1):
            print(f"[{i}/{len(segments)}] Downloading: {seg_url}")
            seg_req = urllib.request.Request(seg_url, headers=headers)
            wf.write(urllib.request.urlopen(seg_req).read())

# ── Async wrapper ───────────────────────────────────────────────────────────────
async def download_hls(m3u8_url: str, output_path: str, headers: dict):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, download_hls_sync, m3u8_url, output_path, headers)

# ── Telegram message handler ─────────────────────────────────────────────────────
@client.on(events.NewMessage)
async def on_message(event):
    text = event.raw_text.strip()
    headers = copy.deepcopy(BASE_HEADERS)
    # Determine message type
    if ".m3u8" in text:
        m3u8_url = text
    elif "/embed/" in text:
        headers["Referer"] = text
        await event.reply("🔍 Extracting playlist URL from embed page…")
        try:
            m3u8_url = extract_m3u8_from_embed(text, headers)
        except Exception as e:
            return await event.reply(f"❌ Failed to extract playlist URL: {e}")
    else:
        return  # ignore other messages

    status = await event.reply("⏳ Downloading and merging… please wait.")
    tmpdir = tempfile.mkdtemp()
    output_ts = os.path.join(tmpdir, 'output.ts')
    try:
        await download_hls(m3u8_url, output_ts, headers)
    except Exception as e:
        return await status.edit(f"❌ Download failed: {e}")

    await client.send_file(
        event.chat_id,
        output_ts,
        caption="✅ Here's your merged stream!",
        force_document=True,
        allow_cache=False,
    )
    await status.delete()

# ── Run the bot ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("🚀 Bot started – listening for links…")
    client.run_until_disconnected()
