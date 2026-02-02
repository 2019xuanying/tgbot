import os
import logging
import json
import time
import pymysql
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# 获取管理员 ID
ADMIN_ID = os.getenv("TG_ADMIN_ID")
try:
    if ADMIN_ID: ADMIN_ID = int(ADMIN_ID)
except: ADMIN_ID = None

class UserManager:
    def __init__(self):
        # 读取数据库配置
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = int(os.getenv("DB_PORT", 3306))
        self.user = os.getenv("DB_USER", "root")
        self.password = os.getenv("DB_PASSWORD", "")
        self.db_name = os.getenv("DB_NAME", "tg_bot_db")
        
        # 默认配置缓存 (减少数据库读取)
        self.default_config = {
            "checkin_reward": 10,
            "invite_reward": 20,
            "plugin_costs": {"yanci": 5, "flexiroam": 5, "jetfi": 5, "travelgoogoo": 0},
            "required_channel": "",
            "bot_active": True,
            "use_proxy": True,
            "send_qr": True
        }
        
        # 初始化数据库结构
        self._init_db()

    def _get_conn(self):
        """获取数据库连接"""
        try:
            return pymysql.connect(
                host=self.host, port=self.port, user=self.user, 
                password=self.password, database=self.db_name,
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True
            )
        except Exception as e:
            logger.error(f"连接数据库失败: {e}")
            raise

    def _init_db(self):
        """初始化表结构"""
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                # 1. 用户表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        name VARCHAR(255),
                        username VARCHAR(255),
                        points INT DEFAULT 0,
                        banned TINYINT(1) DEFAULT 0,
                        invited_by BIGINT DEFAULT NULL,
                        invite_count INT DEFAULT 0,
                        last_checkin DATE DEFAULT NULL,
                        join_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                        authorized TINYINT(1) DEFAULT 0
                    )
                """)
                # 2. 设置表 (Key-Value)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        setting_key VARCHAR(50) PRIMARY KEY,
                        setting_value TEXT
                    )
                """)
                # 3. 代理表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS proxies (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        proxy_str VARCHAR(255) UNIQUE
                    )
                """)
        finally:
            conn.close()

    # === 用户管理 ===
    
    def get_user(self, user_id):
        """获取用户信息，不存在则创建"""
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
                user = cursor.fetchone()
                
                if not user:
                    # 初始化新用户
                    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute(
                        "INSERT INTO users (user_id, join_date, name) VALUES (%s, %s, %s)",
                        (user_id, now_str, 'Unknown')
                    )
                    # 返回默认结构
                    return {
                        "user_id": user_id, "points": 0, "banned": False, 
                        "name": "Unknown", "invite_count": 0, "join_date": now_str,
                        "authorized": False, "invited_by": None
                    }
                
                # 类型转换兼容
                user['banned'] = bool(user['banned'])
                user['authorized'] = bool(user['authorized'])
                if isinstance(user['last_checkin'], datetime): # 处理 DATE 类型
                    user['last_checkin'] = user['last_checkin'].strftime("%Y-%m-%d")
                
                return user
        finally:
            conn.close()

    def update_user_info(self, user_id, name, username):
        """更新用户基本信息"""
        self.get_user(user_id) # 确保存在
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET name=%s, username=%s WHERE user_id=%s",
                    (name, username, user_id)
                )
        finally:
            conn.close()

    # === 封禁系统 ===
    
    def is_banned(self, user_id):
        if str(user_id) == str(ADMIN_ID): return False
        user = self.get_user(user_id)
        return user.get('banned', False)

    def set_ban(self, user_id, is_banned: bool):
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE users SET banned=%s WHERE user_id=%s", (1 if is_banned else 0, user_id))
        finally:
            conn.close()

    def get_all_users(self):
        """获取所有用户ID列表 (用于广播)"""
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT user_id FROM users")
                return [row['user_id'] for row in cursor.fetchall()]
        finally:
            conn.close()

    # === 积分系统 ===
    
    def get_points(self, user_id):
        user = self.get_user(user_id)
        return user.get('points', 0)

    def add_points(self, user_id, amount, reason="system"):
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE users SET points = points + %s WHERE user_id=%s", (amount, user_id))
                cursor.execute("SELECT points FROM users WHERE user_id=%s", (user_id,))
                res = cursor.fetchone()
                logger.info(f"User {user_id} added {amount} points. Total: {res['points']}")
                return res['points']
        finally:
            conn.close()

    def deduct_points(self, user_id, amount):
        if str(user_id) == str(ADMIN_ID): return True
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                # 乐观锁检查余额
                cursor.execute("UPDATE users SET points = points - %s WHERE user_id=%s AND points >= %s", (amount, user_id, amount))
                return cursor.rowcount > 0
        finally:
            conn.close()

    # === 签到系统 ===
    
    def check_in(self, user_id):
        today = datetime.now().strftime("%Y-%m-%d")
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                # 检查上次签到
                cursor.execute("SELECT last_checkin FROM users WHERE user_id=%s", (user_id,))
                res = cursor.fetchone()
                
                # 转换 DATE 对象为字符串进行比较
                last_check = res['last_checkin']
                if last_check and str(last_check) == today:
                    return False, 0
                
                # 执行签到
                reward = self.get_config("checkin_reward")
                cursor.execute(
                    "UPDATE users SET last_checkin=%s, points=points+%s WHERE user_id=%s",
                    (today, reward, user_id)
                )
                return True, reward
        finally:
            conn.close()

    # === 邀请系统 ===
    
    def set_inviter(self, new_user_id, inviter_id):
        if str(new_user_id) == str(inviter_id): return False
        
        # 检查是否已存在（不仅是查内存，要查库）
        user = self.get_user(new_user_id)
        if user.get('invited_by'): return False # 已经有邀请人了
        
        # 检查是否是老用户（根据业务逻辑，这里简单判读：只要 invited_by 为空且之前没被邀请过即可）
        # 这里为了防止老用户刷分，可以加一个逻辑：只有新注册(join_date在很近的时间)才行，或者依靠数据库里 invited_by 字段
        
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                # 更新新用户
                cursor.execute("UPDATE users SET invited_by=%s WHERE user_id=%s AND invited_by IS NULL", (inviter_id, new_user_id))
                if cursor.rowcount == 0: return False # 更新失败，可能已有邀请人
                
                # 给邀请人加分
                reward = self.get_config("invite_reward")
                cursor.execute("UPDATE users SET points=points+%s, invite_count=invite_count+1 WHERE user_id=%s", (reward, inviter_id))
                return True
        finally:
            conn.close()

    def get_invite_tree(self, user_id):
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT name, user_id FROM users WHERE invited_by=%s ORDER BY join_date DESC LIMIT 20", (user_id,))
                rows = cursor.fetchall()
                return [f"{r['name']} (ID: {r['user_id']})" for r in rows]
        finally:
            conn.close()

    # === 配置管理 (KV Table) ===
    
    def get_config(self, key, default=None):
        if default is None and key in self.default_config:
            default = self.default_config[key]
            
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT setting_value FROM settings WHERE setting_key=%s", (key,))
                res = cursor.fetchone()
                if res:
                    val = res['setting_value']
                    # 尝试解析 JSON (因为有些配置是字典)
                    try: return json.loads(val)
                    except: return val
                return default
        finally:
            conn.close()

    def set_config(self, key, value):
        # 如果是复杂对象，转 JSON 存
        if isinstance(value, (dict, list, bool, int)):
            val_str = json.dumps(value)
        else:
            val_str = str(value)
            
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value=%s",
                    (key, val_str, val_str)
                )
        finally:
            conn.close()

    def get_plugin_cost(self, plugin_name):
        costs = self.get_config("plugin_costs")
        return costs.get(plugin_name, 0)

    # === 代理管理 ===
    
    def get_proxies(self):
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT proxy_str FROM proxies")
                return [r['proxy_str'] for r in cursor.fetchall()]
        finally:
            conn.close()

    def add_proxies(self, proxy_list):
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                for p in proxy_list:
                    try:
                        cursor.execute("INSERT IGNORE INTO proxies (proxy_str) VALUES (%s)", (p,))
                    except: pass
        finally:
            conn.close()

    def clear_proxies(self):
        conn = self._get_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE proxies")
        finally:
            conn.close()
            
    # === 兼容接口 ===
    def is_authorized(self, user_id):
        return not self.is_banned(user_id)
        
    def authorize_user(self, uid, username=None):
        pass # 新版逻辑默认注册即由积分控制，不需要手动 auth，除非你要做白名单模式
        
    def revoke_user(self, uid):
        self.set_ban(uid, True)
        
    def increment_usage(self, uid, name):
        pass

user_manager = UserManager()
