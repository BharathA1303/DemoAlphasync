import json
import secrets
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cache.redis_client import get_redis


GROUPS_KEY = "alphasync:admin:groups"
USER_GROUP_KEY = "alphasync:admin:user_group"
TOKEN_GROUP_KEY = "alphasync:admin:group_tokens"
GROUP_BACKUP_FILE = Path(__file__).resolve().parents[1] / "data" / "admin_groups_backup.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_group_name(name: str) -> str:
    raw = str(name or "").strip()
    return " ".join(raw.split())


async def _get_redis_client():
    cache = await get_redis()
    return getattr(cache, "_redis", None)


def _read_backup_payload() -> dict:
    try:
        if not GROUP_BACKUP_FILE.exists():
            return {}
        raw = GROUP_BACKUP_FILE.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _write_backup_payload(payload: dict) -> None:
    try:
        GROUP_BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        GROUP_BACKUP_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception:
        # Backup failures must never break admin operations.
        return


async def _persist_backup_from_redis(redis_client) -> None:
    if not redis_client:
        return

    try:
        groups_map = await redis_client.hgetall(GROUPS_KEY)
        user_group_map = await redis_client.hgetall(USER_GROUP_KEY)
        token_group_map = await redis_client.hgetall(TOKEN_GROUP_KEY)
        _write_backup_payload(
            {
                "groups": groups_map or {},
                "user_groups": user_group_map or {},
                "token_groups": token_group_map or {},
                "updated_at": _utc_now_iso(),
            }
        )
    except Exception:
        return


async def _restore_from_backup_if_needed(redis_client) -> bool:
    if not redis_client:
        return False

    existing_groups = await redis_client.hlen(GROUPS_KEY)
    if existing_groups:
        return False

    payload = _read_backup_payload()
    groups = payload.get("groups") or {}
    user_groups = payload.get("user_groups") or {}
    token_groups = payload.get("token_groups") or {}

    if not isinstance(groups, dict) or not groups:
        return False

    pipe = redis_client.pipeline()
    pipe.hset(GROUPS_KEY, mapping=groups)
    if isinstance(token_groups, dict) and token_groups:
        pipe.hset(TOKEN_GROUP_KEY, mapping=token_groups)
    if isinstance(user_groups, dict) and user_groups:
        pipe.hset(USER_GROUP_KEY, mapping=user_groups)
    await pipe.execute()
    return True


def _safe_parse_group(raw: str) -> Optional[dict]:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        gid = str(data.get("id") or "").strip()
        name = str(data.get("name") or "").strip()
        token = str(data.get("token") or "").strip()
        if not gid or not name or not token:
            return None
        return {
            "id": gid,
            "name": name,
            "token": token,
            "auto_approval": bool(data.get("auto_approval", False)),
            "created_at": data.get("created_at"),
            "created_by": data.get("created_by"),
        }
    except Exception:
        return None


async def _read_groups_map() -> dict[str, dict]:
    redis_client = await _get_redis_client()
    if not redis_client:
        return {}

    await _restore_from_backup_if_needed(redis_client)

    raw_map = await redis_client.hgetall(GROUPS_KEY)
    groups: dict[str, dict] = {}
    for _, raw in (raw_map or {}).items():
        parsed = _safe_parse_group(raw)
        if parsed:
            groups[parsed["id"]] = parsed
    return groups


async def list_groups() -> list[dict]:
    redis_client = await _get_redis_client()
    if not redis_client:
        return []

    groups_map = await _read_groups_map()
    user_group_map = await redis_client.hgetall(USER_GROUP_KEY)
    counts = Counter(user_group_map.values()) if user_group_map else Counter()

    groups = []
    for group in groups_map.values():
        groups.append(
            {
                **group,
                "member_count": int(counts.get(group["id"], 0)),
            }
        )

    groups.sort(key=lambda g: (g.get("created_at") or "", g.get("name") or ""))
    return groups


async def create_group(name: str, created_by: Optional[str] = None) -> dict:
    redis_client = await _get_redis_client()
    if not redis_client:
        return {"success": False, "error": "Group storage is unavailable"}

    group_name = _normalize_group_name(name)
    if len(group_name) < 2 or len(group_name) > 60:
        return {
            "success": False,
            "error": "Group name must be between 2 and 60 characters",
        }

    existing_groups = await _read_groups_map()
    lower_name = group_name.lower()
    if any((g.get("name") or "").strip().lower() == lower_name for g in existing_groups.values()):
        return {"success": False, "error": "A group with this name already exists"}

    group_id = f"grp_{secrets.token_hex(6)}"
    token = secrets.token_urlsafe(18).replace("-", "").replace("_", "")

    payload = {
        "id": group_id,
        "name": group_name,
        "token": token,
        "auto_approval": False,
        "created_at": _utc_now_iso(),
        "created_by": str(created_by) if created_by else None,
    }

    pipe = redis_client.pipeline()
    pipe.hset(GROUPS_KEY, group_id, json.dumps(payload, separators=(",", ":")))
    pipe.hset(TOKEN_GROUP_KEY, token, group_id)
    await pipe.execute()
    await _persist_backup_from_redis(redis_client)

    return {"success": True, "group": {**payload, "member_count": 0}}


async def generate_group_link(group_id: str) -> dict:
    redis_client = await _get_redis_client()
    if not redis_client:
        return {"success": False, "error": "Group storage is unavailable"}

    groups_map = await _read_groups_map()
    group = groups_map.get(str(group_id or ""))
    if not group:
        return {"success": False, "error": "Group not found"}

    old_token = group.get("token")
    new_token = secrets.token_urlsafe(18).replace("-", "").replace("_", "")
    group["token"] = new_token

    pipe = redis_client.pipeline()
    if old_token:
        pipe.hdel(TOKEN_GROUP_KEY, old_token)
    pipe.hset(TOKEN_GROUP_KEY, new_token, group["id"])
    pipe.hset(GROUPS_KEY, group["id"], json.dumps(group, separators=(",", ":")))
    await pipe.execute()
    await _persist_backup_from_redis(redis_client)

    return {"success": True, "group": group}


async def rename_group(group_id: str, new_name: str) -> dict:
    redis_client = await _get_redis_client()
    if not redis_client:
        return {"success": False, "error": "Group storage is unavailable"}

    normalized_name = _normalize_group_name(new_name)
    if len(normalized_name) < 2 or len(normalized_name) > 60:
        return {
            "success": False,
            "error": "Group name must be between 2 and 60 characters",
        }

    groups_map = await _read_groups_map()
    group = groups_map.get(str(group_id or ""))
    if not group:
        return {"success": False, "error": "Group not found"}

    lower_name = normalized_name.lower()
    for gid, existing_group in groups_map.items():
        if gid == group["id"]:
            continue
        if (existing_group.get("name") or "").strip().lower() == lower_name:
            return {"success": False, "error": "A group with this name already exists"}

    group["name"] = normalized_name
    await redis_client.hset(GROUPS_KEY, group["id"], json.dumps(group, separators=(",", ":")))
    await _persist_backup_from_redis(redis_client)
    return {"success": True, "group": group}


async def set_group_auto_approval(group_id: str, enabled: bool) -> dict:
    redis_client = await _get_redis_client()
    if not redis_client:
        return {"success": False, "error": "Group storage is unavailable"}

    groups_map = await _read_groups_map()
    group = groups_map.get(str(group_id or ""))
    if not group:
        return {"success": False, "error": "Group not found"}

    group["auto_approval"] = bool(enabled)
    await redis_client.hset(GROUPS_KEY, group["id"], json.dumps(group, separators=(",", ":")))
    await _persist_backup_from_redis(redis_client)
    return {"success": True, "group": group}


async def delete_group(group_id: str) -> dict:
    redis_client = await _get_redis_client()
    if not redis_client:
        return {"success": False, "error": "Group storage is unavailable"}

    groups_map = await _read_groups_map()
    group = groups_map.get(str(group_id or ""))
    if not group:
        return {"success": False, "error": "Group not found"}

    user_group_map = await redis_client.hgetall(USER_GROUP_KEY)
    members_to_clear = [uid for uid, gid in (user_group_map or {}).items() if gid == group["id"]]

    pipe = redis_client.pipeline()
    pipe.hdel(GROUPS_KEY, group["id"])
    if group.get("token"):
        pipe.hdel(TOKEN_GROUP_KEY, group["token"])
    if members_to_clear:
        pipe.hdel(USER_GROUP_KEY, *members_to_clear)
    await pipe.execute()
    await _persist_backup_from_redis(redis_client)

    return {"success": True, "deleted_group_id": group["id"], "removed_members": len(members_to_clear)}


async def assign_user_to_group(user_id: str, group_id: str) -> dict:
    redis_client = await _get_redis_client()
    if not redis_client:
        return {"success": False, "error": "Group storage is unavailable"}

    groups_map = await _read_groups_map()
    group = groups_map.get(str(group_id or ""))
    if not group:
        return {"success": False, "error": "Group not found"}

    await redis_client.hset(USER_GROUP_KEY, str(user_id), group["id"])
    await _persist_backup_from_redis(redis_client)
    return {"success": True, "group": group}


async def remove_user_from_group(user_id: str) -> dict:
    redis_client = await _get_redis_client()
    if not redis_client:
        return {"success": False, "error": "Group storage is unavailable"}

    await redis_client.hdel(USER_GROUP_KEY, str(user_id))
    await _persist_backup_from_redis(redis_client)
    return {"success": True}


async def resolve_group_by_token(token: str) -> Optional[dict]:
    redis_client = await _get_redis_client()
    if not redis_client:
        return None

    normalized = str(token or "").strip()
    if not normalized:
        return None

    group_id = await redis_client.hget(TOKEN_GROUP_KEY, normalized)
    if not group_id:
        return None

    groups_map = await _read_groups_map()
    return groups_map.get(str(group_id))


async def get_users_group_assignments(user_ids: list[str]) -> dict[str, dict]:
    redis_client = await _get_redis_client()
    if not redis_client or not user_ids:
        return {}

    groups_map = await _read_groups_map()
    user_group_map = await redis_client.hgetall(USER_GROUP_KEY)
    assignments: dict[str, dict] = {}

    for uid in user_ids:
        gid = user_group_map.get(str(uid)) if user_group_map else None
        group = groups_map.get(str(gid)) if gid else None
        if group:
            assignments[str(uid)] = {
                "group_id": group["id"],
                "group_name": group["name"],
            }
    return assignments
