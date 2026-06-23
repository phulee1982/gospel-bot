import discord
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import os

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

VATICAN_URL = "https://www.vaticannews.va/vi/loi-chua-hang-ngay.html"

WEEKDAYS_VI = {
    0: "Thứ Hai",
    1: "Thứ Ba",
    2: "Thứ Tư",
    3: "Thứ Năm",
    4: "Thứ Sáu",
    5: "Thứ Bảy",
    6: "Chúa Nhật",
}

HELP_TEXT = """📖 **Bot Bài Đọc Tin Mừng** - Hướng dẫn sử dụng:

**Lệnh cơ bản:**
• `!tinhung` → Bài đọc Tin Mừng hôm nay
• `!tinhung hôm nay` → Bài đọc hôm nay
• `!tinhung hôm qua` → Bài đọc hôm qua
• `!tinhung ngày mai` → Bài đọc ngày mai

**Lệnh theo ngày cụ thể:**
• `!tinhung 24/6` → Bài đọc ngày 24 tháng 6
• `!tinhung 24/6/2026` → Bài đọc ngày 24/6/2026

**Lệnh khác:**
• `!tinhung help` → Hiển thị hướng dẫn này
"""


def build_url_for_date(target_date: datetime) -> str:
    """Build Vatican News URL for a specific date."""
    date_str = target_date.strftime("%Y-%m-%d")
    return f"https://www.vaticannews.va/vi/loi-chua-hang-ngay/{date_str}.html"


def parse_date_from_message(text: str) -> datetime | None:
    """Parse date keywords or date strings from user message."""
    text = text.strip().lower()
    today = datetime.now()

    if text in ("", "hôm nay", "hom nay"):
        return today
    if text in ("hôm qua", "hom qua", "qua"):
        return today - timedelta(days=1)
    if text in ("ngày mai", "ngay mai", "mai"):
        return today + timedelta(days=1)
    if text in ("kia", "ngày kia", "ngay kia"):
        return today + timedelta(days=2)

    # dd/mm or dd/mm/yyyy
    match = re.match(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{4}))?$", text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    return None


async def fetch_gospel(target_date: datetime) -> dict:
    """Fetch and parse the Gospel reading from Vatican News."""
    url = build_url_for_date(target_date)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 404:
                return {"error": "not_found"}
            if resp.status != 200:
                return {"error": f"http_{resp.status}"}
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")

    # Try to find article body
    article = (
        soup.find("div", class_="article__body")
        or soup.find("div", class_=re.compile(r"article"))
        or soup.find("main")
    )

    if not article:
        return {"error": "parse_failed"}

    # Extract all text paragraphs
    paragraphs = []
    gospel_section = []
    in_gospel = False

    all_text = article.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in all_text.splitlines() if l.strip()]

    for line in lines:
        lower = line.lower()
        # Detect gospel section
        if "tin mừng" in lower and ("thánh" in lower or "theo" in lower or "mc" in lower or "mt" in lower or "lc" in lower or "ga" in lower):
            in_gospel = True
        if in_gospel:
            gospel_section.append(line)
            # Stop at next major section
            if len(gospel_section) > 3 and any(
                kw in lower for kw in ["lời chúa", "lời nguyện", "suy niệm", "nguồn:", "© vatican"]
            ):
                gospel_section.pop()  # Remove the stopping line
                break

    if not gospel_section:
        # Fallback: return all text
        return {
            "date": target_date,
            "content": "\n".join(lines[:60]),
            "url": url,
            "fallback": True,
        }

    return {
        "date": target_date,
        "content": "\n".join(gospel_section),
        "url": url,
        "fallback": False,
    }


def format_date_vi(dt: datetime) -> str:
    weekday = WEEKDAYS_VI[dt.weekday()]
    return f"{weekday}, ngày {dt.day}/{dt.month}/{dt.year}"


def chunk_text(text: str, max_len: int = 1900) -> list[str]:
    """Split long text into Discord-safe chunks."""
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
    print(f"✅ Bot đã đăng nhập: {client.user} (ID: {client.user.id})")
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

    # Match !tinhung [args]
    if not content.lower().startswith("!tinhung"):
        return

    args = content[len("!tinhung"):].strip()

    # Help
    if args.lower() in ("help", "giúp", "huong dan", "hướng dẫn", "?"):
        await message.channel.send(HELP_TEXT)
        return

    # Parse date
    target_date = parse_date_from_message(args)
    if target_date is None:
        await message.channel.send(
            f"❓ Mình không hiểu ngày **`{args}`**.\n"
            "Thử dùng: `hôm nay`, `hôm qua`, `ngày mai`, hoặc `24/6` hoặc `24/6/2026`.\n"
            "Gõ `!tinhung help` để xem hướng dẫn."
        )
        return

    # Show typing indicator
    async with message.channel.typing():
        result = await fetch_gospel(target_date)

    date_label = format_date_vi(target_date)

    if "error" in result:
        if result["error"] == "not_found":
            await message.channel.send(
                f"📭 Không tìm thấy bài đọc cho **{date_label}**.\n"
                f"Có thể Vatican News chưa đăng bài cho ngày này.\n🔗 {build_url_for_date(target_date)}"
            )
        else:
            await message.channel.send(
                f"⚠️ Lỗi khi tải bài đọc ({result['error']}). Vui lòng thử lại sau."
            )
        return

    header = (
        f"✝️ **BÀI ĐỌC TIN MỪNG**\n"
        f"📅 {date_label}\n"
        f"{'─' * 40}\n"
    )
    footer = f"\n{'─' * 40}\n🔗 [Xem trên Vatican News]({result['url']})"

    gospel_text = result["content"]
    chunks = chunk_text(gospel_text, max_len=1800)

    # Send first chunk with header
    await message.channel.send(header + chunks[0] + (footer if len(chunks) == 1 else ""))

    # Send remaining chunks
    for i, chunk in enumerate(chunks[1:], 1):
        is_last = i == len(chunks) - 1
        await message.channel.send(chunk + (footer if is_last else ""))


TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Thiếu DISCORD_TOKEN trong biến môi trường!")

client.run(TOKEN)
