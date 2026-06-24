import discord
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import os

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

BASE_URL = "https://www.vaticannews.va/vi/loi-chua-hang-ngay"

WEEKDAYS_VI = {
    0: "Thứ Hai", 1: "Thứ Ba", 2: "Thứ Tư",
    3: "Thứ Năm", 4: "Thứ Sáu", 5: "Thứ Bảy", 6: "Chúa Nhật",
}

HELP_TEXT = """📖 **Bot Bài Đọc Tin Mừng** - Hướng dẫn sử dụng:

**Lệnh cơ bản:**
• `!tinmung` → Bài đọc Tin Mừng hôm nay
• `!tinmung hôm nay` → Bài đọc hôm nay
• `!tinmung hôm qua` → Bài đọc hôm qua
• `!tinmung ngày mai` → Bài đọc ngày mai

**Lệnh theo ngày cụ thể:**
• `!tinmung 24/6` → Bài đọc ngày 24 tháng 6 (năm hiện tại)
• `!tinmung 24/6/2026` → Bài đọc ngày 24/6/2026

**Lệnh khác:**
• `!tinmung help` → Hiển thị hướng dẫn này
"""


def build_url(target_date: datetime) -> str:
    """Build Vatican News URL: /vi/loi-chua-hang-ngay/YYYY/MM/DD.html"""
    return f"{BASE_URL}/{target_date.year}/{target_date.month:02d}/{target_date.day:02d}.html"


def parse_date(text: str) -> datetime | None:
    text = text.strip().lower()
    today = datetime.now()

    if text in ("", "hôm nay", "hom nay", "today"):
        return today
    if text in ("hôm qua", "hom qua", "qua", "yesterday"):
        return today - timedelta(days=1)
    if text in ("ngày mai", "ngay mai", "mai", "tomorrow"):
        return today + timedelta(days=1)
    if text in ("kia", "ngày kia", "ngay kia"):
        return today + timedelta(days=2)

    # dd/mm or dd/mm/yyyy
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{4}))?$", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    return None


def extract_gospel(html: str) -> str | None:
    """
    Extract only the Gospel (Tin Mừng) section from the page HTML.
    The Gospel always starts with the ✠ symbol followed by 'Tin Mừng'
    and ends before the next major section or end of article.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Get all text from the article body
    article = (
        soup.find("div", class_=re.compile(r"article", re.I))
        or soup.find("main")
        or soup.find("body")
    )
    if not article:
        return None

    full_text = article.get_text(separator="\n")
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    gospel_lines = []
    in_gospel = False

    # Patterns that signal the START of gospel
    # ✠ symbol always precedes "Tin Mừng" / "Tin Mung" / Gospel heading
    GOSPEL_START_PATTERNS = [
        re.compile(r"[✠☩†]\s*tin\s*m[ươ]ng", re.I | re.UNICODE),
        re.compile(r"tin\s*m[ươ]ng\s+ch[úu]a\s+gi[eê]", re.I | re.UNICODE),
        re.compile(r"gospel\s+of", re.I),
    ]

    # Patterns that signal END of gospel section
    GOSPEL_END_PATTERNS = [
        re.compile(r"^(đó là lời|lời chúa|nguồn:|suy ni[eê]m|lời nguy[eê]n|bình lu[aậ]n|comment)", re.I | re.UNICODE),
        re.compile(r"^©\s*(vatican|holy see)", re.I),
        re.compile(r"^(share|chia s[eẻ]|facebook|twitter)", re.I | re.UNICODE),
    ]

    for i, line in enumerate(lines):
        if not in_gospel:
            # Check if this line is the gospel header
            for pat in GOSPEL_START_PATTERNS:
                if pat.search(line):
                    in_gospel = True
                    gospel_lines.append(line)
                    break
        else:
            # Check if we've hit an end marker
            stop = False
            for pat in GOSPEL_END_PATTERNS:
                if pat.search(line):
                    stop = True
                    break

            # Also stop if we see a new major heading that's clearly NOT gospel content
            # (e.g. a line that looks like a section title after sufficient content)
            if len(gospel_lines) > 5 and len(line) < 60 and line.isupper():
                stop = True

            if stop:
                break
            gospel_lines.append(line)

    if not gospel_lines:
        return None

    return "\n".join(gospel_lines)


async def fetch_gospel(target_date: datetime) -> dict:
    url = build_url(target_date)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "vi-VN,vi;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 404:
                return {"error": "not_found", "url": url}
            if resp.status != 200:
                return {"error": f"http_{resp.status}", "url": url}
            html = await resp.text()

    gospel = extract_gospel(html)
    if not gospel:
        return {"error": "parse_failed", "url": url}

    return {"date": target_date, "content": gospel, "url": url}


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

    # Accept both !tinmung and !tinhung (backward compat)
    lower = content.lower()
    if lower.startswith("!tinmung"):
        args = content[len("!tinmung"):].strip()
    elif lower.startswith("!tinhung"):
        args = content[len("!tinhung"):].strip()
    else:
        return

    # Help
    if args.lower() in ("help", "giúp", "?", "huong dan", "hướng dẫn"):
        await message.channel.send(HELP_TEXT)
        return

    # Parse date
    target_date = parse_date(args)
    if target_date is None:
        await message.channel.send(
            f"❓ Mình không hiểu ngày **`{args}`**.\n"
            "Thử: `hôm nay`, `hôm qua`, `ngày mai`, `24/6`, `24/6/2026`\n"
            "Gõ `!tinmung help` để xem hướng dẫn."
        )
        return

    async with message.channel.typing():
        result = await fetch_gospel(target_date)

    date_label = format_date_vi(target_date)

    if "error" in result:
        err = result["error"]
        if err == "not_found":
            await message.channel.send(
                f"📭 Không tìm thấy bài đọc cho **{date_label}**.\n"
                f"Vatican News có thể chưa đăng bài cho ngày này.\n"
                f"🔗 {result['url']}"
            )
        elif err == "parse_failed":
            await message.channel.send(
                f"⚠️ Tải được trang nhưng không tìm thấy phần Tin Mừng cho **{date_label}**.\n"
                f"🔗 {result['url']}"
            )
        else:
            await message.channel.send(f"⚠️ Lỗi khi tải bài đọc (`{err}`). Vui lòng thử lại sau.")
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
        is_last = (i == len(chunks) - 1)
        await message.channel.send(chunk + (footer if is_last else ""))


TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Thiếu DISCORD_TOKEN trong biến môi trường!")

client.run(TOKEN)
