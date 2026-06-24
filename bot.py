import discord
import aiohttp
from datetime import datetime, timedelta
import re
import os

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

WEEKDAYS_VI = {
    0: "Thứ Hai", 1: "Thứ Ba", 2: "Thứ Tư",
    3: "Thứ Năm", 4: "Thứ Sáu", 5: "Thứ Bảy", 6: "Chúa Nhật",
}

HELP_TEXT = """📖 **Bot Bài Đọc Tin Mừng** - Hướng dẫn:

• `!tinmung` → Bài đọc hôm nay
• `!tinmung hôm qua` → Bài đọc hôm qua
• `!tinmung ngày mai` → Bài đọc ngày mai
• `!tinmung 24/6` → Bài đọc ngày 24/6
• `!tinmung 24/6/2026` → Ngày cụ thể
• `!tinmung help` → Hướng dẫn này
"""

# GitHub repo raw content URL
GITHUB_USER = os.environ.get("GITHUB_USER", "phulee1982")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "gospel-bot")
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/data"


def parse_date(text: str) -> datetime | None:
    text = text.strip().lower()
    today = datetime.now()
    if text in ("", "hôm nay", "hom nay"):
        return today
    if text in ("hôm qua", "hom qua", "qua"):
        return today - timedelta(days=1)
    if text in ("ngày mai", "ngay mai", "mai"):
        return today + timedelta(days=1)
    if text in ("kia", "ngày kia"):
        return today + timedelta(days=2)
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{4}))?$", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    return None


async def fetch_gospel(target_date: datetime) -> dict:
    date_str = target_date.strftime("%Y-%m-%d")
    url = f"{RAW_BASE}/{date_str}.json"
    vatican_url = (
        f"https://www.vaticannews.va/vi/loi-chua-hang-ngay"
        f"/{target_date.year}/{target_date.month:02d}/{target_date.day:02d}.html"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 404:
                    return {"error": "not_found", "url": vatican_url}
                if resp.status != 200:
                    return {"error": f"http_{resp.status}", "url": vatican_url}
                data = await resp.json(content_type=None)

        content = data.get("content", "").strip()
        if not content:
            return {"error": "empty", "url": vatican_url}

        return {
            "date": target_date,
            "content": content,
            "url": data.get("url", vatican_url),
        }
    except Exception as e:
        return {"error": f"exception: {e}", "url": vatican_url}


def format_date_vi(dt: datetime) -> str:
    return f"{WEEKDAYS_VI[dt.weekday()]}, ngày {dt.day}/{dt.month}/{dt.year}"


def chunk_text(text: str, max_len: int = 1900) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    return chunks


@client.event
async def on_ready():
    print(f"✅ Bot đã đăng nhập: {client.user}")
    await client.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="📖 Lời Chúa hàng ngày"
        )
    )


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip()
    lower = content.lower()

    if lower.startswith("!tinmung"):
        args = content[len("!tinmung"):].strip()
    elif lower.startswith("!tinhung"):
        args = content[len("!tinhung"):].strip()
    else:
        return

    if args.lower() in ("help", "giúp", "?", "huong dan", "hướng dẫn"):
        await message.channel.send(HELP_TEXT)
        return

    target_date = parse_date(args)
    if target_date is None:
        await message.channel.send(
            f"❓ Không hiểu ngày **`{args}`**.\n"
            "Thử: `hôm nay`, `hôm qua`, `ngày mai`, `24/6`, `24/6/2026`"
        )
        return

    async with message.channel.typing():
        result = await fetch_gospel(target_date)

    date_label = format_date_vi(target_date)

    if "error" in result:
        err = result["error"]
        if err == "not_found":
            await message.channel.send(
                f"📭 Chưa có bài đọc cho **{date_label}**.\n"
                f"Dữ liệu được cập nhật lúc 7:00 sáng mỗi ngày.\n"
                f"🔗 {result['url']}"
            )
        else:
            await message.channel.send(
                f"⚠️ Lỗi tải bài đọc cho **{date_label}** (`{err}`).\nThử lại sau nhé."
            )
        return

    header = (
        f"✝️ **TIN MỪNG NGÀY HÔM NAY**\n"
        f"📅 {date_label}\n"
        f"{'─' * 38}\n"
    )
    footer = f"\n{'─' * 38}\n🔗 [Nguồn: Vatican News]({result['url']})"

    chunks = chunk_text(result["content"], max_len=1800)
    await message.channel.send(header + chunks[0] + (footer if len(chunks) == 1 else ""))
    for i, chunk in enumerate(chunks[1:], 1):
        await message.channel.send(chunk + (footer if i == len(chunks) - 1 else ""))


TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Thiếu DISCORD_TOKEN!")

client.run(TOKEN)
