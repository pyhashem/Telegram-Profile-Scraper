import argparse
import asyncio
import json
import os
import socks
from loguru import logger

from session_manager import SessionManager
from profile_scraper import scrape_members_safe, scrape_from_messages, join_group
from models import UserProfile


def load_proxy(config_path: str) -> tuple | None:
    if not os.path.exists(config_path):
        return None
    with open(config_path, "r") as f:
        cfg = json.load(f)
    p = cfg.get("proxy", {})
    if not p.get("host"):
        return None
    ptype = socks.SOCKS5 if p.get("type", "socks5") == "socks5" else socks.HTTP
    return (ptype, p["host"], p["port"], True, p.get("username"), p.get("password"))


async def run(args):
    logger.add(os.path.join(args.output, "scraper.log"), rotation="10 MB", level="DEBUG")

    proxy = load_proxy(args.config)
    if proxy:
        logger.info(f"Using proxy: {proxy[1]}:{proxy[2]}")

    sm = SessionManager(args.sessions, proxy=proxy)
    sm.load_sessions(args.api_id, args.api_hash)
    await sm.start_all()

    group = args.group
    group_id = group.lstrip("@").replace("https://t.me/", "").replace("/", "")
    photos_dir = os.path.join(args.output, f"{group_id}_photos")

    if args.join:
        logger.info(f"Joining group: {group}")
        joined = await sm.execute_with_rotation(join_group, group)
        if not joined:
            logger.error(f"Could not join group {group}")
            await sm.stop_all()
            return

    profiles = None

    if args.mode in ("members", "auto"):
        logger.info(f"Trying members API for {group}")
        profiles = await sm.execute_with_rotation(
            scrape_members_safe, group, photos_dir, args.photo_only
        )
        if profiles is None and args.mode == "auto":
            logger.info("Members API failed, falling back to message scan")

    if profiles is None:
        logger.info(f"Scanning messages for {group} (limit={args.limit})")
        profiles = await sm.execute_with_rotation(
            scrape_from_messages, group, photos_dir, args.limit, args.photo_only
        )

    await sm.stop_all()

    if profiles is None:
        logger.error(f"Could not find group {group} — check the username and try again")
        return

    os.makedirs(args.output, exist_ok=True)
    UserProfile.save_group(args.output, group_id, profiles)
    logger.success(f"Saved {len(profiles)} profiles to {args.output}/{group_id}.json")


def main():
    parser = argparse.ArgumentParser(description="Telegram Profile Scraper")
    parser.add_argument("--group", required=True, help="Group username or link")
    parser.add_argument("--join", action="store_true", help="Join group before scraping")
    parser.add_argument("--photo-only", action="store_true", help="Only scrape users with profile pictures")
    parser.add_argument("--mode", choices=["members", "chat", "auto"], default="auto")
    parser.add_argument("--sessions", required=True, help="Path to sessions directory")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--limit", type=int, default=100000, help="Max messages to scan")
    parser.add_argument("--api-id", default=2040, type=int, help="Telegram API ID")
    parser.add_argument("--api-hash", default="b18441a1ff607e10a989891a5462e627", help="Telegram API Hash")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
