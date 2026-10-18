from typing import Any

from fastapi import APIRouter

from utils.config_manager import ConfigManager

router = APIRouter()


@router.get("")
def profiles():
    return ConfigManager().load_profiles()


@router.put("/{profile_id}")
def save_profile(profile_id: str, value: dict[str, Any]):
    if value.get("id", profile_id) != profile_id:
        raise ValueError("Profile ID must match the URL")
    ConfigManager().save_profile({**value, "id": profile_id})
    return {"status": "saved"}


@router.delete("/{profile_id}")
def delete_profile(profile_id: str):
    ConfigManager().delete_profile(profile_id)
    return {"status": "deleted"}
