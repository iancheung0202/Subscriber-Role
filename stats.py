import asyncio
import collections
import csv
import datetime
import os

import asyncpg
import discord
from dotenv import load_dotenv

load_dotenv()

WIDTH = 78
DAILY_QUOTA = 10000
lines = []


def out(text: str = ""):
    print(text)
    lines.append(text)


def heading(title: str):
    out()
    out(title.upper())
    out("-" * WIDTH)


def row(label: str, value, note: str = ""):
    value = f"{value:,}" if isinstance(value, int) else str(value)
    out(f"  {label:<38}{value:>10}  {note}".rstrip())


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "0%"


def bar(n: int, biggest: int, width: int = 32) -> str:
    if not biggest or not n:
        return ""
    return "█" * max(1, round(width * n / biggest))


def clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


async def database_stats():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        configs = await conn.fetch(
            "SELECT guild_id, COUNT(*) AS n FROM servers GROUP BY guild_id"
        )
        users = await conn.fetch(
            "SELECT guild_id, COUNT(*) AS linked, COUNT(refresh_token) AS with_token FROM users GROUP BY guild_id"
        )
        subs = await conn.fetch(
            "SELECT s.guild_id, COUNT(*) FILTER (WHERE sub.is_subscribed) AS subscribed, "
            "MAX(sub.last_checked) AS last_checked FROM subscriptions sub "
            "JOIN servers s ON s.id = sub.server_id GROUP BY s.guild_id"
        )
    finally:
        await conn.close()
    return (
        {r["guild_id"]: r["n"] for r in configs},
        {r["guild_id"]: (r["linked"], r["with_token"]) for r in users},
        {r["guild_id"]: (r["subscribed"], r["last_checked"]) for r in subs},
    )


async def discord_stats():
    client = discord.Client(intents=discord.Intents.default())
    ready = asyncio.Event()

    @client.event
    async def on_ready():
        ready.set()

    task = asyncio.create_task(client.start(os.environ["DISCORD_TOKEN"]))
    await ready.wait()
    await asyncio.sleep(5)

    guilds = [
        {
            "guild_id": g.id,
            "name": g.name,
            "members": g.member_count or 0,
            "bot_joined": (
                g.me.joined_at.date().isoformat() if g.me and g.me.joined_at else ""
            ),
        }
        for g in client.guilds
    ]
    premium = []
    sku_id = int(os.environ.get("DISCORD_PREMIUM_SKU_ID") or 0)
    try:
        async for e in client.entitlements(limit=None, exclude_ended=False):
            if not sku_id or e.sku_id == sku_id:
                premium.append(e)
    except Exception as exc:
        print(f"(could not list premium entitlements: {exc})")

    await client.close()
    await asyncio.gather(task, return_exceptions=True)
    return guilds, premium


def server_table(title: str, rows: list, key: str):
    heading(title)
    out(
        f"  {'#':>2}  {'Server':<30}{'Members':>9}{'Linked':>8}{'Subbed':>8}{'Cfg':>5}  Joined"
    )
    for i, r in enumerate(sorted(rows, key=lambda r: r[key], reverse=True)[:15], 1):
        out(
            f"  {i:>2}  {clip(r['name'], 29):<30}{r['members']:>9,}{r['linked_users']:>8,}"
            f"{r['subscribed_now']:>8,}{r['configs']:>5}  {r['bot_joined']}"
        )


async def main():
    now = datetime.datetime.now()
    configs, users, subs = await database_stats()
    rows, premium = await discord_stats()

    for r in rows:
        linked, with_token = users.get(r["guild_id"], (0, 0))
        subscribed, last_checked = subs.get(r["guild_id"], (0, None))
        r.update(
            configs=configs.get(r["guild_id"], 0),
            linked_users=linked,
            users_with_token=with_token,
            subscribed_now=subscribed,
            last_checked=last_checked.date().isoformat() if last_checked else "",
        )

    joined_ids = {r["guild_id"] for r in rows}
    set_up = sum(1 for r in rows if r["configs"])
    used = sum(1 for r in rows if r["linked_users"])
    linked = sum(r["linked_users"] for r in rows)
    daily = sum(r["users_with_token"] for r in rows)
    owners = {
        o.strip() for o in os.environ.get("OWNER_IDS", "").split(",") if o.strip()
    }
    paid = [e for e in premium if str(e.user_id) not in owners]

    out("=" * WIDTH)
    out(f"  SUBSCRIBER ROLE STATISTICS    {now:%Y-%m-%d %H:%M:%S}")
    out("=" * WIDTH)

    heading("Servers")
    row("In now", len(rows))
    row("Finished /setup", set_up, percent(set_up, len(rows)) + " of servers")
    row("With a verified member", used, percent(used, len(rows)) + " of servers")
    row("Set up, then removed the bot", sum(1 for g in configs if g not in joined_ids))
    row("Members across all servers", sum(r["members"] for r in rows))

    heading("Members")
    row("Linked YouTube accounts", linked)
    row(
        "Subscribed at the last check",
        sum(r["subscribed_now"] for r in rows),
        percent(sum(r["subscribed_now"] for r in rows), linked) + " of linked",
    )
    top = max(rows, key=lambda r: r["linked_users"], default=None)
    if top and linked:
        row(
            "Share held by the top server",
            percent(top["linked_users"], linked),
            clip(top["name"], 24),
        )

    heading("YouTube quota")
    row("Daily sync calls", daily, "about one quota unit each")
    row(
        "Default daily quota",
        DAILY_QUOTA,
        percent(daily, DAILY_QUOTA) + " used by the sync",
    )
    if daily > 0.8 * DAILY_QUOTA:
        out("  !! Near or over the default quota. Check usage in Google Cloud.")

    heading("Premium")
    row("Entitlements ever", len(premium))
    row("Bought by someone else", len(paid), "the rest belong to OWNER_IDS")
    for e in sorted(premium, key=lambda e: e.starts_at or now.astimezone()):
        kind = "paid " if e in paid else "owner"
        started = e.starts_at.date().isoformat() if e.starts_at else "unknown"
        ends = e.ends_at.date().isoformat() if e.ends_at else "no end"
        out(f"    {kind}  guild {e.guild_id}  buyer {e.user_id}  {started} to {ends}")

    heading("Joins per month (servers the bot is still in)")
    per_month = collections.Counter(
        r["bot_joined"][:7] for r in rows if r["bot_joined"]
    )
    biggest, total = max(per_month.values(), default=0), 0
    for month in sorted(per_month):
        total += per_month[month]
        out(
            f"  {month}  {per_month[month]:>5}  total {total:>5}  {bar(per_month[month], biggest)}"
        )

    heading("Joins per day (last 30 days)")
    per_day = collections.Counter(r["bot_joined"] for r in rows if r["bot_joined"])
    days = [
        (now.date() - datetime.timedelta(days=i)).isoformat() for i in range(29, -1, -1)
    ]
    biggest = max((per_day[d] for d in days), default=0)
    for day in days:
        out(f"  {day}  {per_day[day]:>4}  {bar(per_day[day], biggest)}")

    server_table("Largest servers", rows, "members")
    server_table("Most-used servers", rows, "linked_users")

    os.makedirs("stats", exist_ok=True)
    base = os.path.join("stats", now.strftime("%Y-%m-%d-%H-%M-%S"))
    fields = ["guild_id", "name", "members", "bot_joined", "configs", "linked_users"]
    fields += ["users_with_token", "subscribed_now", "last_checked"]
    with open(base + ".csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r["bot_joined"]))
    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSaved {base}.txt and {base}.csv")


if __name__ == "__main__":
    asyncio.run(main())
