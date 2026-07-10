import os
from loguru import logger
from telethon import TelegramClient, functions
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import User
from telethon.errors import ChatAdminRequiredError, ChannelPrivateError, UsernameNotOccupiedError, UserAlreadyParticipantError

from models import UserProfile


async def join_group(client: TelegramClient, group: str) -> bool:
    try:
        entity = await client.get_entity(group)
        await client(functions.channels.JoinChannelRequest(entity))
        logger.info(f"Joined group: {group}")
        return True
    except UserAlreadyParticipantError:
        logger.info(f"Already in group: {group}")
        return True
    except (UsernameNotOccupiedError, ValueError) as e:
        logger.error(f"Group not found: {group} — {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to join {group}: {e}")
        return False


async def _download_photo(client: TelegramClient, user_id: int, photos_dir: str) -> str | None:
    os.makedirs(photos_dir, exist_ok=True)
    try:
        photos = await client.get_profile_photos(user_id, limit=1)
        if not photos:
            return None
        path = await client.download_media(
            photos[0],
            file=os.path.join(photos_dir, f"user_{user_id}.jpg"),
        )
        return path
    except Exception as e:
        logger.debug(f"No photo for user {user_id}: {e}")
        return None


async def _get_user_profile(client: TelegramClient, user: User, photos_dir: str) -> UserProfile:
    full = await client(GetFullUserRequest(user.id))
    photo_path = await _download_photo(client, user.id, photos_dir)
    birthday = None
    if hasattr(full.full_user, "birthday") and full.full_user.birthday:
        b = full.full_user.birthday
        if b.month and b.day:
            birthday = f"{b.year or '????'}-{b.month:02d}-{b.day:02d}"
    return UserProfile(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        bio=full.full_user.about,
        phone=user.phone if hasattr(user, "phone") else None,
        birthday=birthday,
        profile_photo=photo_path,
    )


async def scrape_members(
    client: TelegramClient, group: str, photos_dir: str, photo_only: bool = False
) -> list[UserProfile]:
    entity = await client.get_entity(group)
    participants = await client.get_participants(entity)
    logger.info(f"Found {len(participants)} participants in {group}")
    profiles = []
    for user in participants:
        if isinstance(user, User) and not user.bot:
            profile = await _get_user_profile(client, user, photos_dir)
            if photo_only and not profile.profile_photo:
                logger.debug(f"Skipped (no photo): {user.username or user.id}")
                continue
            profiles.append(profile)
            logger.debug(f"Scraped: {user.username or user.id}")
    return profiles


async def scrape_members_safe(
    client: TelegramClient, group: str, photos_dir: str, photo_only: bool = False
) -> list[UserProfile] | None:
    try:
        return await scrape_members(client, group, photos_dir, photo_only)
    except (ChatAdminRequiredError, ChannelPrivateError) as e:
        logger.warning(f"Members API failed for {group}: {e}")
        return None
    except (UsernameNotOccupiedError, ValueError) as e:
        logger.error(f"Group not found: {group} — {e}")
        return None


async def scrape_from_messages(
    client: TelegramClient,
    group: str,
    photos_dir: str,
    limit: int = 10000,
    photo_only: bool = False,
) -> list[UserProfile] | None:
    try:
        entity = await client.get_entity(group)
    except (UsernameNotOccupiedError, ValueError) as e:
        logger.error(f"Group not found: {group} — {e}")
        return None
    seen_ids: set[int] = set()
    profiles: list[UserProfile] = []

    # Pre-fetch participants to populate entity cache
    try:
        participants = await client.get_participants(entity)
        logger.info(f"Pre-loaded {len(participants)} participants into cache")
    except Exception as e:
        logger.debug(f"Could not pre-load participants: {e}")

    logger.info(f"Scanning messages in {group} (limit={limit})")
    async for message in client.iter_messages(entity, limit=limit):
        if message.sender_id and message.sender_id not in seen_ids:
            seen_ids.add(message.sender_id)
            try:
                user = None
                try:
                    user = await message.get_sender()
                except (ValueError, TypeError):
                    pass
                if user is None:
                    try:
                        from telethon.tl.types import PeerUser
                        user = await client.get_entity(PeerUser(message.sender_id))
                    except Exception:
                        pass
                if user is None or not isinstance(user, User) or user.bot:
                    continue
                profile = await _get_user_profile(client, user, photos_dir)
                if photo_only and not profile.profile_photo:
                    logger.debug(f"Skipped (no photo): {user.username or user.id}")
                    continue
                profiles.append(profile)
                logger.debug(f"Scraped from chat: {user.username or user.id}")
            except Exception as e:
                logger.debug(f"Failed to fetch sender {message.sender_id}: {e}")
                continue
    logger.info(f"Collected {len(profiles)} unique profiles from messages")
    return profiles
