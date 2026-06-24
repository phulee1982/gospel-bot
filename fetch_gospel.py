import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import os
import re
import sys

BASE_URL = "https://www.vaticannews.va/vi/loi-chua-hang-ngay"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def get_lines(target_date):
    url = f"{BASE_URL}/{target_date.year}/{target_date.month:02d}/{target_date.day:02d}.html"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if resp.status_code != 200:
        return None, url, f"HTTP {resp.status_code}"
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
    return lines, url, None


def extract_gospel(lines):
    """
    Structure observed:
    ...
    "Bài đọc ngày hôm nay"   <- section marker
    "SINH NHẬT THÁNH..."      <- feast name
    "Bài đọc 1" / "Bài đọc 2" <- readings
    "Tin Mừng"                <- gospel marker ← WE WANT FROM HERE
    "Mc 1,..." / "Lc 1,..."   <- citation
    ... gospel text ...
    "Lời Chúa của Chúa"  OR end of readings
    """

    gospel_start = None

    # Find the line that says "Tin Mừng" as a section header
    # It appears as a standalone line (short), NOT embedded in a longer sentence
    for i, line in enumerate(lines):
        # Standalone "Tin Mừng" section marker (short line, not a full sentence)
        if re.match(r'^Tin\s+M[ưừ]ng\s*$', line, re.I | re.U):
            gospel_start = i
            break

    if gospel_start is None:
        # Fallback: look for ✠ symbol
        for i, line in enumerate(lines):
            if '✠' in line or '☩' in line:
                gospel_start = i
                break

    if gospel_start is None:
        # Fallback 2: look for gospel citation pattern like "Mc 1,57-66" etc.
        for i, line in enumerate(lines):
            if re.match(r'^(Mt|Mc|Lc|Ga)\s+\d+,', line):
                # Go back to find the "Tin Mừng" label before it
                gospel_start = max(0, i - 2)
                break

    if gospel_start is None:
        return None

    # Collect gospel lines until end markers
    gospel_lines = []
    END_MARKERS = re.compile(
        r'^(Lời Chúa của Chúa|Đó là Lời Chúa|Suy niệm|Lời nguyện|'
        r'Xin hỗ trợ|Bản văn Kinh Thánh|Nhóm Phiên Dịch|'
        r'Về Vatican News|Cookie|©)',
        re.I | re.U
    )

    for line in lines[gospel_start:]:
        if END_MARKERS.search(line):
            break
        gospel_lines.append(line)

    return "\n".join(gospel_lines) if gospel_lines else None


def fetch_gospel(target_date):
    lines, url, err = get_lines(target_date)
    if err:
        print(f"  Fetch error: {err} for {url}")
        return None, url

    gospel = extract_gospel(lines)
    if not gospel:
        print(f"  Parse failed for {url}")
        # Print surrounding context for debugging
        for i, line in enumerate(lines):
            if 'Tin' in line and 'M' in line:
                print(f"  DEBUG line {i}: {line}")
        return None, url

    return gospel, url


def main():
    os.makedirs("data", exist_ok=True)
    today = datetime.now(tz=None)

    for delta in [-1, 0, 1, 2]:
        target = today + timedelta(days=delta)
        date_str = target.strftime("%Y-%m-%d")
        filepath = f"data/{date_str}.json"

        if os.path.exists(filepath):
            try:
                existing = json.load(open(filepath, encoding="utf-8"))
                fetched = existing.get("fetched_at", "")
                if fetched[:10] == today.strftime("%Y-%m-%d") and existing.get("content"):
                    print(f"  Already fresh: {date_str}")
                    continue
            except Exception:
                pass

        print(f"Fetching {date_str}...")
        gospel, url = fetch_gospel(target)
        if gospel:
            data = {
                "date": date_str,
                "url": url,
                "content": gospel,
                "fetched_at": datetime.utcnow().isoformat(),
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  ✅ Saved {filepath} ({len(gospel)} chars)")
        else:
            print(f"  ❌ Failed {date_str}")


def debug_mode():
    """Print lines 115-250 to inspect structure around gospel section."""
    target = datetime.now()
    lines, url, err = get_lines(target)
    if err:
        print(f"Error: {err}")
        return
    print(f"Total lines: {len(lines)}")
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 115
    end = int(sys.argv[3]) if len(sys.argv) > 3 else min(start + 120, len(lines))
    for i, line in enumerate(lines[start:end], start=start):
        print(f"{i:3}: {line}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "debug":
        debug_mode()
    else:
        main()
