
import os
import re
import html
import sqlite3
import requests
import feedparser

from bs4 import BeautifulSoup
from urllib.parse import urljoin

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

FITGIRL_RSS = "https://fitgirl-repacks.site/feed/"
DODI_URL = "https://dodi-repacks.site/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 GameUpdateBot/1.0"
}

DB = sqlite3.connect("games.db")
DB.execute("""
CREATE TABLE IF NOT EXISTS seen (
    source TEXT,
    link TEXT,
    PRIMARY KEY(source, link)
)
""")
DB.commit()


def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    r = requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }, timeout=30)

    r.raise_for_status()

    if not r.json().get("ok"):
        raise RuntimeError("Telegram rejected message")


def is_seen(source, link):
    return DB.execute(
        "SELECT 1 FROM seen WHERE source=? AND link=?",
        (source, link)
    ).fetchone() is not None


def save(source, link):
    DB.execute(
        "INSERT OR IGNORE INTO seen VALUES (?, ?)",
        (source, link)
    )
    DB.commit()


def steam_release_date(title):
    try:
        r = requests.get(
            "https://store.steampowered.com/api/storesearch/",
            params={
                "term": title,
                "l": "english",
                "cc": "US"
            },
            timeout=20
        )
        r.raise_for_status()

        items = r.json().get("items", [])

        if not items:
            return "Not found"

        app_id = items[0]["id"]

        r = requests.get(
            "https://store.steampowered.com/api/appdetails",
            params={
                "appids": app_id,
                "cc": "US",
                "l": "english"
            },
            timeout=20
        )
        r.raise_for_status()

        data = r.json()[str(app_id)]["data"]

        return data.get(
            "release_date", {}
        ).get("date", "Not found")

    except Exception as e:
        print("Release date lookup:", e)
        return "Not available"


def notify(source, title, date, link, description):

    release = steam_release_date(title)

    title = html.escape(title[:220])
    date = html.escape(str(date)[:100])
    description = html.escape(description[:500])
    link = html.escape(link, quote=True)
    release = html.escape(release)

    message = (
        "🎮 <b>NEW GAME UPLOAD!</b>\n\n"
        f"🎯 <b>Game:</b> {title}\n"
        f"📅 <b>Upload Date:</b> {date}\n"
        f"🌐 <b>Website:</b> {source}\n"
        f"🗓 <b>Official Release:</b> {release}\n\n"
        f"📝 <b>Details:</b>\n{description}\n\n"
        f"🔗 <a href='{link}'>Original Post</a>"
    )

    send(message)


def fitgirl_posts():

    feed = feedparser.parse(FITGIRL_RSS)

    if not feed.entries:
        raise RuntimeError("FitGirl RSS returned no entries")

    posts = []

    for entry in feed.entries:

        link = entry.get("link")

        if not link:
            continue

        description = BeautifulSoup(
            entry.get("summary", ""),
            "html.parser"
        ).get_text(" ", strip=True)

        posts.append({
            "title": entry.get("title", "Unknown game"),
            "link": link,
            "date": entry.get("published", "Not available"),
            "description": description
        })

    return posts


def dodi_posts():

    r = requests.get(
        DODI_URL,
        headers=HEADERS,
        timeout=30
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    posts = []

    for article in soup.select("article"):

        heading = article.select_one("h2 a, h3 a")

        if not heading:
            continue

        link = urljoin(DODI_URL, heading.get("href", ""))
        title = heading.get_text(" ", strip=True)

        if not link or not title:
            continue

        time_tag = article.find("time")

        date = "Not available"

        if time_tag:
            date = (
                time_tag.get("datetime")
                or time_tag.get_text(strip=True)
            )

        description = article.get_text(" ", strip=True)

        posts.append({
            "title": title,
            "link": link,
            "date": date,
            "description": description[:500]
        })

    if not posts:
        raise RuntimeError(
            "DODI page structure changed or no posts found"
        )

    return posts


def process(source, posts):

    # First run: establish baseline, don't send old posts.
    baseline_key = f"baseline_{source}"

    baseline = DB.execute(
        "SELECT 1 FROM seen WHERE source=? LIMIT 1",
        (baseline_key,)
    ).fetchone()

    if not baseline:

        for post in posts:
            save(source, post["link"])

        save(baseline_key, "initialized")
        print(source, "baseline initialized")
        return

    # Oldest first, so notifications follow post order.
    for post in reversed(posts):

        link = post["link"]

        if is_seen(source, link):
            continue

        try:
            notify(
                source,
                post["title"],
                post["date"],
                link,
                post["description"] or "No description"
            )

            save(source, link)

            print("Sent:", post["title"])

        except Exception as e:
            print("Notification failed:", e)
            raise


def main():

    print("Starting game monitor")


    errors = []

    for source, function in [
        ("FitGirl", fitgirl_posts),
        ("DODI", dodi_posts)
    ]:

        try:
            posts = function()
            process(source, posts)

        except Exception as e:
            errors.append(source)
            print(source, "error:", e)

    if errors:
        raise RuntimeError(
            "Monitoring incomplete: " + ", ".join(errors)
        )

    print("Monitoring completed successfully")


if __name__ == "__main__":
    main()
