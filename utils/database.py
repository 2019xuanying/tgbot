import os
import logging
from datetime import datetime, date
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Date, BigInteger, Text, func
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# 获取配置
ADMIN_ID = os.getenv("TG_ADMIN_ID")
try:
    if ADMIN_ID: ADMIN_ID = int(ADMIN_ID)
except: ADMIN_ID = None

# 数据库连接字符串
DB_USER = os.getenv("MYSQL_USER", "root")
DB_PASS = os.getenv("MYSQL_PASSWORD", "")
DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_PORT = os.getenv("MYSQL_PORT", "3306")
DB_NAME = os.getenv("MYSQL_DB", "tg_bot_db")

DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

Base = declarative_base()

# ================= 数据模型 =================

class User(Base):
    __tablename__ = 'users'
    id = Column(BigInteger, primary_key=True)  # Telegram User ID
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    balance = Column(Integer, default=0)       # 积分余额
    invited_by = Column(BigInteger, default=0) # 邀请人ID
    join_date = Column(DateTime, default=datetime.now)
    last_checkin = Column(Date, nullable=True) # 上次签到日期
    is_banned = Column(Boolean, default=False) # 是否封禁
    is_admin = Column(Boolean, default=False)

class Config(Base):
    __tablename__ = 'settings'
    key = Column(String(100), primary_key=True)
    value = Column(String(255), nullable=True)
    description = Column(String(255), nullable=True)

class Feedback(Base):
    __tablename__ = 'feedback'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    status = Column(Integer, default=0) # 0:未处理, 1:已解决

# ================= 数据库管理器 =================

class DBManager:
    def __init__(self):
        self.engine = create_engine(DATABASE_URL, pool_recycle=3600)
        Base.metadata.create_all(self.engine) # 自动建表
        self.Session = sessionmaker(bind=self.engine)
        self.init_default_config()

    def get_session(self):
        return self.Session()

    def init_default_config(self):
        """初始化默认配置"""
        defaults = {
            "invite_reward": "10",        # 邀请奖励
            "checkin_reward": "5",        # 签到奖励
            "cost_yanci": "10",           # Yanci 消耗
            "cost_flexiroam": "5",        # Flexi 消耗
            "cost_jetfi": "5",            # Jetfi 消耗
            "force_join_channel": "",     # 强制加入的频道 ID (空则不开启)
        }
        session = self.get_session()
        try:
            for k, v in defaults.items():
                if not session.query(Config).filter_by(key=k).first():
                    session.add(Config(key=k, value=v))
            session.commit()
        except Exception as e:
            logger.error(f"Init Config Error: {e}")
        finally:
            session.close()

    # --- 用户操作 ---
    def get_or_create_user(self, user_id, username=None, first_name=None, inviter_id=None):
        session = self.get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                # 新用户
                user = User(
                    id=user_id, 
                    username=username, 
                    first_name=first_name, 
                    invited_by=inviter_id if inviter_id and str(inviter_id) != str(user_id) else 0,
                    balance=0
                )
                session.add(user)
                
                # 如果有邀请人，且邀请人存在，处理邀请奖励
                if inviter_id and str(inviter_id) != str(user_id):
                    inviter = session.query(User).filter_by(id=inviter_id).first()
                    if inviter:
                        # 简单的防刷：被邀请人必须有 username 才能给邀请人加分 (需求2)
                        reward = int(self.get_config("invite_reward", "10"))
                        if username: 
                            inviter.balance += reward
                            logger.info(f"User {inviter_id} rewarded {reward} for inviting {user_id}")
            else:
                # 更新信息
                if username: user.username = username
                if first_name: user.first_name = first_name
            
            session.commit()
            # 刷新对象以返回最新数据，detach 防止 session 关闭后无法访问
            session.refresh(user)
            return user
        except Exception as e:
            logger.error(f"User Error: {e}")
            session.rollback()
            return None
        finally:
            session.close()

    def get_user(self, user_id):
        session = self.get_session()
        try:
            return session.query(User).filter_by(id=user_id).first()
        finally:
            session.close()

    # --- 积分与签到 ---
    def daily_checkin(self, user_id):
        session = self.get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if not user: return False, "未找到用户"
            
            today = date.today()
            if user.last_checkin == today:
                return False, "今日已签到"
            
            reward = int(self.get_config("checkin_reward", "5"))
            user.balance += reward
            user.last_checkin = today
            session.commit()
            return True, f"签到成功！获得 {reward} 积分，当前余额: {user.balance}"
        finally:
            session.close()

    def deduct_points(self, user_id, plugin_name):
        """扣除积分，返回 (是否成功, 信息/余额)"""
        session = self.get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if not user: return False, "用户不存在"
            
            cost_key = f"cost_{plugin_name}"
            cost = int(self.get_config(cost_key, "0"))
            
            if user.balance < cost:
                return False, f"积分不足！需要 {cost} 积分，当前余额 {user.balance}。"
            
            user.balance -= cost
            session.commit()
            return True, user.balance
        finally:
            session.close()

    def admin_add_points(self, user_id, points):
        session = self.get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user:
                user.balance += points
                session.commit()
                return True
            return False
        finally:
            session.close()

    # --- 邀请链 ---
    def get_invite_list(self, user_id):
        """查询某人邀请了谁 (直属下级)"""
        session = self.get_session()
        try:
            users = session.query(User).filter_by(invited_by=user_id).all()
            return [(u.id, u.username, u.balance) for u in users]
        finally:
            session.close()

    # --- 配置管理 ---
    def get_config(self, key, default_val=None):
        session = self.get_session()
        try:
            cfg = session.query(Config).filter_by(key=key).first()
            return cfg.value if cfg else default_val
        finally:
            session.close()

    def set_config(self, key, value):
        session = self.get_session()
        try:
            cfg = session.query(Config).filter_by(key=key).first()
            if cfg:
                cfg.value = str(value)
            else:
                session.add(Config(key=key, value=str(value)))
            session.commit()
        finally:
            session.close()

    # --- 管理功能 ---
    def set_ban(self, user_id, is_banned):
        session = self.get_session()
        try:
            user = session.query(User).filter_by(id=user_id).first()
            if user:
                user.is_banned = is_banned
                session.commit()
                return True
            return False
        finally:
            session.close()

    def add_feedback(self, user_id, content):
        session = self.get_session()
        try:
            fb = Feedback(user_id=user_id, content=content)
            session.add(fb)
            session.commit()
            return True
        finally:
            session.close()
            
    def get_all_user_ids(self):
        session = self.get_session()
        try:
            users = session.query(User.id).all()
            return [u[0] for u in users]
        finally:
            session.close()

db = DBManager()
