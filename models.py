from dataclasses import dataclass, asdict
from typing import Optional
import json
import os


@dataclass
class UserProfile:
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    birthday: Optional[str] = None
    profile_photo: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def save_group(output_dir: str, group_id: str, profiles: list["UserProfile"]):
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"{group_id}.json")
        data = [p.to_dict() for p in profiles]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
