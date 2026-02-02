import json
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# 获取管理员 ID
ADMIN_ID = os.getenv("TG_ADMIN_ID")
try:
    if ADMIN_ID:
        ADMIN_ID = int(ADMIN_ID)
except ValueError:
    ADMIN_ID = None

class UserManager:
    FILE_PATH = 'user_data.json'

    def __init__(self):
        self.data = self._load()

    def _load(self):
        default_config = {
            "send_qr": True, 
            "bot_active": True, 
            "plugins": {}, 
            "use_proxy": True,    # 默认开启代理
            "proxies": []         # 代理列表
        }
        
        if not os.path.exists(self.FILE_PATH):
            return {"users": {}, "config": default_config}
        
        try:
            with open(self.FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 确保 config 存在
                if "config" not in data:
                    data["config"] = default_config
                
                # 补全缺失的字段 (向后兼容)
                for key, val in default_config.items():
                    if key not in data["config"]:
                        data["config"][key] = val
                
                return data
        except Exception as e:
            logger.error(f"加载数据失败: {e}")
            return {"users": {}, "config": default_config}

    def _save(self):
        try:
            with open(self.FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    # === 用户相关 ===
    def authorize_user(self, user_id, username=None):
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {"authorized": True, "count": 0, "name": username or "Unknown"}
        else:
            self.data["users"][uid]["authorized"] = True
            if username: self.data["users"][uid]["name"] = username
        self._save()
        return True

    def revoke_user(self, user_id):
        uid = str(user_id)
        if uid in self.data["users"]:
            self.data["users"][uid]["authorized"] = False
            self._save()
            return True
        return False

    def is_authorized(self, user_id):
        if ADMIN_ID and str(user_id) == str(ADMIN_ID):
            return True
        uid = str(user_id)
        user = self.data["users"].get(uid)
        return user and user.get("authorized", False)

    def increment_usage(self, user_id, username=None):
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {"authorized": False, "count": 1, "name": username or "Unknown"}
        else:
            self.data["users"][uid]["count"] += 1
            if username: self.data["users"][uid]["name"] = username
        self._save()

    def get_all_users(self):
        return self.data["users"]
    
    # === 配置相关 ===
    def get_config(self, key, default=None):
        return self.data["config"].get(key, default)

    def set_config(self, key, value):
        if "config" not in self.data:
            self.data["config"] = {}
        self.data["config"][key] = value
        self._save()

    # === 插件开关 ===
    def get_plugin_status(self, plugin_name):
        if not self.data["config"].get("bot_active", True):
            return False
        plugins = self.data["config"].get("plugins", {})
        return plugins.get(plugin_name, True)

    def toggle_plugin(self, plugin_name):
        if "plugins" not in self.data["config"]:
            self.data["config"]["plugins"] = {}
        current = self.data["config"]["plugins"].get(plugin_name, True)
        self.data["config"]["plugins"][plugin_name] = not current
        self._save()
        return not current

    # === 代理管理 ===
    def get_proxies(self):
        return self.data["config"].get("proxies", [])

    def set_proxies(self, proxy_list):
        self.data["config"]["proxies"] = proxy_list
        self._save()

    def add_proxies(self, new_proxies):
        current = self.data["config"].get("proxies", [])
        # 去重添加
        for p in new_proxies:
            if p not in current:
                current.append(p)
        self.data["config"]["proxies"] = current
        self._save()

    def clear_proxies(self):
        self.data["config"]["proxies"] = []
        self._save()

user_manager = UserManager()
