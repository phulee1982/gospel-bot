import discord
import aiohttp
from datetime import datetime, timedelta
import re
import os
import json

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

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def build_url(target_date: datetime) -> str:
    return (
        f"https://www.vaticannews.va/vi/loi-chua-hang-ngay"
        f"/{target_date.year}/{target_date.month:02d}/{target_date.day:02d}.html"
    )


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


async def fetch_gospel_via_claude(target_date: datetime) -> dict:
    """Use Claude AI with web_search tool to fetch the Gospel reading."""
    url = build_url(target_date)
    date_str = target_date.strftime("%d/%m/%Y")

    prompt = (
        f"Hãy truy cập trang web này và trích xuất CHỈ phần bài đọc Tin Mừng (Gospel): {url}\n\n"
        f"Tìm phần có tiêu đề 'Tin Mừng ngày hôm nay' hoặc bắt đầu bằng ký hiệu ✠\n"
        f"Trả về ĐÚNG nội dung bài Tin Mừng, bắt đầu từ '✠Tin Mừng Chúa Giê-su Ki-tô...' "
        f"cho đến hết bài đọc. KHÔNG thêm bình luận, KHÔNG thêm nội dung khác.\n"
        f"Nếu không tìm thấy, trả về chính xác: NOT_FOUND"
    )

    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2000,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": prompt}],
    }

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "interleaved-thinking-2025-05-14",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    return {"error": f"api_{resp.status}: {err_text[:200]}", "url": url}
                data = await resp.json()

        # Extract text from response
        full_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                full_text += block.get("text", "")

        full_text = full_text.strip()
        if not full_text or full_text == "NOT_FOUND" or "NOT_FOUND" in full_text:
            return {"error": "not_found", "url": url}

        return {"date": target_date, "content": full_text, "url": url}

    except Exception as e:
        return {"error": f"exception: {e}", "url": url}


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
    if not ANTHROPIC_API_KEY:
        print("⚠️  CẢNH BÁO: Thiếu ANTHROPIC_API_KEY!")
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

    if not ANTHROPIC_API_KEY:
        await message.channel.send(
            "⚠️ Bot chưa được cấu hình đầy đủ.\n"
            "Vui lòng thêm `ANTHROPIC_API_KEY` vào Railway Variables."
        )
        return

    async with message.channel.typing():
        result = await fetch_gospel_via_claude(target_date)

    date_label = format_date_vi(target_date)

    if "error" in result:
        err = result["error"]
        if err == "not_found":
            await message.channel.send(
                f"📭 Không tìm thấy bài đọc cho **{date_label}**.\n"
                f"🔗 {result['url']}"
            )
        else:
            await message.channel.send(
                f"⚠️ Lỗi: `{err}`\nVui lòng thử lại."
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


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("❌ Thiếu DISCORD_TOKEN!")

client.run(DISCORD_TOKEN)
