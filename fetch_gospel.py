"""
Script chạy trên GitHub Actions mỗi ngày.
Lấy bài đọc Tin Mừng từ Vatican News và lưu vào data/YYYY-MM-DD.json
"""
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import os
import re

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


def fetch_gospel(target_date: datetime) -> dict | None:
    url = f"{BASE_URL}/{target_date.year}/{target_date.month:02d}/{target_date.day:02d}.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code} for {url}")
            return None
        resp.encoding = "utf-8"
        html = resp.text
    except Exception as e:
        print(f"  Fetch error: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    # Find "Tin Mừng ngày hôm nay" heading
    gospel_heading = None
    for tag in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
        text = tag.get_text(strip=True).lower()
        if "tin mừng ngày hôm nay" in text or "tin mung ngay hom nay" in text:
            gospel_heading = tag
            break

    content = None
    if gospel_heading:
        parts = []
        for sibling in gospel_heading.find_next_siblings():
            tag_text = sibling.get_text(separator="\n", strip=True)
            if not tag_text:
                continue
            low = tag_text.lower()
            if any(kw in low for kw in [
                "xin hỗ trợ", "bản văn kinh thánh", "gửi đi",
                "nhóm phiên dịch", "thêm các sự kiện", "cookie"
            ]):
                break
            parts.append(tag_text)
        if parts:
            content = "\n\n".join(parts)

    # Fallback: search for ✠ marker
    if not content:
        full_text = soup.get_text(separator="\n")
        lines = [l.strip() for l in full_text.splitlines() if l.strip()]
        gospel_lines = []
        in_gospel = False
        GOSPEL_START = re.compile(r"[✠☩✙†]\s*tin\s*m[ưu][ờo]ng", re.I | re.U)
        END_MARKERS = re.compile(
            r"xin\s*hỗ\s*trợ|bản\s*văn\s*kinh|nhóm\s*phiên\s*dịch|"
            r"gửi\s*đi|thêm\s*các\s*sự\s*kiện", re.I | re.U
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
        if gospel_lines:
            content = "\n".join(gospel_lines)

    if not content:
        print(f"  Parse failed for {url}")
        return None

    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "url": url,
        "content": content,
        "fetched_at": datetime.utcnow().isoformat(),
    }


def main():
    os.makedirs("data", exist_ok=True)
    today = datetime.utcnow()  # UTC+0; Vatican posts at midnight Rome time

    # Fetch yesterday, today, tomorrow (buffer)
    for delta in [-1, 0, 1, 2]:
        target = today + timedelta(days=delta)
        date_str = target.strftime("%Y-%m-%d")
        filepath = f"data/{date_str}.json"

        # Skip if already fetched today
        if os.path.exists(filepath):
            existing = json.load(open(filepath))
            fetched = existing.get("fetched_at", "")
            if fetched[:10] == today.strftime("%Y-%m-%d"):
                print(f"  Already fresh: {date_str}")
                continue

        print(f"Fetching {date_str}...")
        result = fetch_gospel(target)
        if result:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"  ✅ Saved {filepath} ({len(result['content'])} chars)")
        else:
            print(f"  ❌ Failed {date_str}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "debug":
        # Debug mode - print raw content
        url = "https://www.vaticannews.va/vi/loi-chua-hang-ngay/2026/06/24.html"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script","style","nav","footer"]): tag.decompose()
        lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
        for i, line in enumerate(lines[80:200],start=80):
            print(f"{i:3}: {line}")
    else:
        main()
