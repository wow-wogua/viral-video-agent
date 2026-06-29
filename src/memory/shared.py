"""全局共享状态管理。跨智能体共享的数据放这里。"""

_user_preferences: dict[str, dict] = {}


def set_user_preference(user_id: str, key: str, value):
    if user_id not in _user_preferences:
        _user_preferences[user_id] = {}
    _user_preferences[user_id][key] = value


def get_user_preference(user_id: str, key: str, default=None):
    return _user_preferences.get(user_id, {}).get(key, default)


def get_all_preferences(user_id: str) -> dict:
    return _user_preferences.get(user_id, {})
