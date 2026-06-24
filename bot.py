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

**Lệnh:**
• `!tinmung` → Bài đọc hôm nay
• `!tinmung hôm qua` → Bài đọc hôm qua
• `!tinmung ngày mai` → Bài đọc ngày mai
• `!tinmung 24/6` → Bài đọc ngày 24/6
• `!tinmung 24/6/2026` → Bài đọc ngày cụ thể
• `!tinmung help` → Hướng dẫn này
"""


def build_url(target_date: datetime) -> str:
    return f"{BASE_URL}/{target_date.year}/{target_date.month:02d}/{target_date.day:02d}.html"


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


def extract_gospel(soup: BeautifulSoup) -> str | None:
    """
    Vatican News HTML structure (stable):
    - Section heading: <h2>Tin Mừng ngày hôm nay</h2>  (or similar)
    - Then the gospel content follows until the next section or end

    Strategy:
    1. Find the "Tin Mừng ngày hôm nay" heading
    2. Collect all content after it until end markers
    """

    # --- Strategy 1: Find by heading "Tin Mừng ngày hôm nay" ---
    # Look for any heading tag containing this text
    gospel_heading = None
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b"]):
        text = tag.get_text(strip=True).lower()
        if "tin mừng ngày hôm nay" in text or "tin mung ngay hom nay" in text:
            gospel_heading = tag
            break

    if gospel_heading:
        # Collect all text from this heading onwards
        parts = []
        # Include any italic subtitle right after the heading
        for sibling in gospel_heading.find_next_siblings():
            tag_text = sibling.get_text(separator="\n", strip=True)
            if not tag_text:
                continue
            # Stop at donation/footer/share sections
            low = tag_text.lower()
            if any(kw in low for kw in [
                "xin hỗ trợ", "bản văn kinh thánh", "gửi đi", "nhóm phiên dịch",
                "thêm các sự kiện", "hoạt động của đgh", "cookie"
            ]):
                break
            parts.append(tag_text)
        if parts:
            return "\n\n".join(parts)

    # --- Strategy 2: Find by ✠ marker anywhere in the page ---
    full_text = soup.get_text(separator="\n")
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    gospel_lines = []
    in_gospel = False
    GOSPEL_START = re.compile(
        r"[✠☩✙†]\s*tin\s*m[ưu][ờo]ng\s+ch[úu]a",
        re.IGNORECASE | re.UNICODE
    )
    END_MARKERS = re.compile(
        r"xin\s*hỗ\s*trợ|bản\s*văn\s*kinh\s*thánh|nhóm\s*phiên\s*dịch|"
        r"gửi\s*đi|thêm\s*các\s*sự\s*kiện|hoạt\s*động\s*của",
        re.IGNORECASE | re.UNICODE
    )

    for line in lines:
        if not in_gospel:
            if GOSPEL_START.search(line):
                in_gospel = True
                gospel_lines.append(line)
        else:
            if END_MARKERS.search(line):
                break
            gospel_lines.append(line)

    return "\n".join(gospel_lines) if gospel_lines else None


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

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 404:
                    return {"error": "not_found", "url": url}
                if resp.status != 200:
                    return {"error": f"http_{resp.status}", "url": url}
                html = await resp.text()
    except Exception as e:
        return {"error": f"network: {e}", "url": url}

    soup = BeautifulSoup(html, "html.parser")
    # Remove noise
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    gospel = extract_gospel(soup)
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
                f"📭 Không tìm thấy bài đọc cho **{date_label}**.\n"
                f"Vatican News có thể chưa đăng bài này.\n🔗 {result['url']}"
            )
        elif err == "parse_failed":
            await message.channel.send(
                f"⚠️ Tải được trang nhưng không tìm thấy phần Tin Mừng cho **{date_label}**.\n"
                f"🔗 {result['url']}"
            )
        else:
            await message.channel.send(f"⚠️ Lỗi: `{err}`. Vui lòng thử lại.")
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
