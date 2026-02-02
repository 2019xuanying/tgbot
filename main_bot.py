import os
import sys
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.constants import ParseMode
from telegram.error import BadRequest

# 导入工具
from utils.database import user_manager, ADMIN_ID

# 导入插件
from plugins import yanci
from plugins import flexiroam
from plugins import jetfi
from plugins import travelgoogoo

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ 错误：未找到 TG_BOT_TOKEN")
    sys.exit(1)

# 定义管理状态
ADMIN_STATE_NONE = 0
ADMIN_WAIT_PROXY_LIST = 101
ADMIN_WAIT_BROADCAST_MSG = 102
ADMIN_WAIT_CHANNEL_SET = 103
ADMIN_WAIT_BAN_ID = 104
FEEDBACK_STATE = 200

# ================= 辅助函数 =================

async def check_channel_join(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """检查用户是否加入了指定频道"""
    channel = user_manager.get_config("required_channel")
    if not channel or str(user_id) == str(ADMIN_ID):
        return True, ""
    
    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ['left', 'kicked']:
            return False, channel
        return True, ""
    except BadRequest:
        # 机器人不在频道里，或者频道不存在，默认跳过
        return True, ""
    except Exception as e:
        logger.error(f"Channel check error: {e}")
        return True, ""

def get_main_keyboard(is_admin):
    kb = [
        [InlineKeyboardButton("📅 每日签到", callback_data="user_daily_checkin"),
         InlineKeyboardButton("👤 个人中心", callback_data="user_profile")],
        [InlineKeyboardButton("🌏 Yanci", callback_data="plugin_yanci_entry"),
         InlineKeyboardButton("🌐 Flexiroam", callback_data="plugin_flexi_entry")],
        [InlineKeyboardButton("🚙 JetFi", callback_data="plugin_jetfi_entry"),
         InlineKeyboardButton("🏝 TravelGoo", callback_data="plugin_travel_entry")],
        [InlineKeyboardButton("🐛 问题反馈", callback_data="user_feedback")]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("👮 管理员后台", callback_data="admin_menu_main")])
    return InlineKeyboardMarkup(kb)

# ================= 核心命令 =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    
    # 1. 更新数据库信息
    user_manager.update_user_info(user.id, user.full_name, user.username)
    
    # 2. 封禁检查
    if user_manager.is_banned(user.id):
        await update.message.reply_text("🚫 您的账号已被封禁。")
        return

    # 3. 处理邀请
    if args and len(args) > 0:
        inviter_id = args[0]
        if not user.username:
            await update.message.reply_text("⚠️ **提示**：您需要设置 Telegram 用户名 (Username) 才能接受邀请奖励。", parse_mode=ParseMode.MARKDOWN)
        else:
            if user_manager.set_inviter(user.id, inviter_id):
                reward = user_manager.get_config("invite_reward")
                try:
                    await context.bot.send_message(chat_id=inviter_id, text=f"🎉 新用户 {user.full_name} 加入！\n💰 获得积分: +{reward}")
                except: pass

    # 4. 强制关注检查
    is_joined, channel_name = await check_channel_join(user.id, context)
    if not is_joined:
        clean_name = channel_name.replace('@', '')
        kb = [[InlineKeyboardButton("👉 加入频道", url=f"https://t.me/{clean_name}")],
              [InlineKeyboardButton("✅ 我已加入", callback_data="main_menu_root")]]
        await update.message.reply_text(f"🛑 **需关注频道才能使用**\n请先加入: {channel_name}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        return

    text = (
        f"👋 **你好，{user.first_name}！**\n\n"
        f"💰 积分: `{user_manager.get_points(user.id)}`\n"
        f"🆔 ID: `{user.id}`\n\n"
        f"请选择功能："
    )
    await update.message.reply_text(text, reply_markup=get_main_keyboard(str(user.id) == str(ADMIN_ID)), parse_mode=ParseMode.MARKDOWN)

# ================= 用户回调 =================

async def user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    data = query.data
    await query.answer()

    if user_manager.is_banned(user.id):
        await query.edit_message_text("🚫 账号已封禁。")
        return

    if data == "main_menu_root":
        text = f"👋 **你好，{user.first_name}！**\n\n💰 积分: `{user_manager.get_points(user.id)}`\n🆔 ID: `{user.id}`"
        await query.edit_message_text(text, reply_markup=get_main_keyboard(str(user.id) == str(ADMIN_ID)), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "user_daily_checkin":
        success, reward = user_manager.check_in(user.id)
        if success:
            text = f"✅ **签到成功！**\n积分 +{reward}\n当前余额: {user_manager.get_points(user.id)}"
        else:
            text = f"⚠️ **今天已签到**\n明天再来吧！"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "user_profile":
        u_data = user_manager.get_user(user.id)
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={user.id}"
        
        text = (
            f"👤 **个人中心**\n\n"
            f"💰 积分: `{u_data['points']}`\n"
            f"📅 加入: {u_data['join_date']}\n"
            f"👥 邀请: {u_data['invite_count']} 人\n\n"
            f"🔗 **专属邀请链接**:\n`{link}`\n"
            f"(邀请一人得 {user_manager.get_config('invite_reward')} 积分)"
        )
        invitees = user_manager.get_invite_tree(user.id)
        if invitees: text += "\n\n📜 **最近邀请:**\n" + "\n".join(invitees)
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "user_feedback":
        context.user_data['state'] = FEEDBACK_STATE
        await query.edit_message_text("🐛 **请回复您遇到的问题：**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="main_menu_root")]]), parse_mode=ParseMode.MARKDOWN)
        return

    # 插件入口不做拦截，具体扣费在插件内部的 start_task 处执行
    pass

# ================= 管理员后台 =================

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if str(user.id) != str(ADMIN_ID): return
    data = query.data
    await query.answer()

    if data == "admin_menu_main":
        context.user_data['state'] = ADMIN_STATE_NONE
        text = "👮 **管理员控制台**"
        kb = [
            [InlineKeyboardButton("📢 广播消息", callback_data="admin_broadcast"),
             InlineKeyboardButton("📺 频道设置", callback_data="admin_set_channel")],
            [InlineKeyboardButton("👥 用户管理", callback_data="admin_user_manage"),
             InlineKeyboardButton("🌍 代理管理", callback_data="admin_ctrl_proxies")],
            [InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "admin_broadcast":
        context.user_data['state'] = ADMIN_WAIT_BROADCAST_MSG
        await query.edit_message_text("📢 **请回复广播内容**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="admin_menu_main")]]), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "admin_set_channel":
        curr = user_manager.get_config("required_channel", "未设置")
        context.user_data['state'] = ADMIN_WAIT_CHANNEL_SET
        await query.edit_message_text(f"📺 **当前频道**: `{curr}`\n请回复新 ID 或 @username (回复 clear 清除)。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_menu_main")]], parse_mode=ParseMode.MARKDOWN))
        return

    if data == "admin_user_manage":
        context.user_data['state'] = ADMIN_WAIT_BAN_ID
        await query.edit_message_text("🚫 **请回复要 封禁/解封 的用户ID**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_menu_main")]], parse_mode=ParseMode.MARKDOWN))
        return

    # 代理相关
    if data == "admin_ctrl_proxies":
        proxies = user_manager.get_proxies()
        await query.edit_message_text(f"🌍 代理数: {len(proxies)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📥 导入", callback_data="admin_proxy_import"), InlineKeyboardButton("🗑 清空", callback_data="admin_proxy_clear"), InlineKeyboardButton("🔙 返回", callback_data="admin_menu_main")]]))
        return
        
    if data == "admin_proxy_import":
        context.user_data['state'] = ADMIN_WAIT_PROXY_LIST
        await query.edit_message_text("请回复代理列表，每行一个", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="admin_menu_main")]]))
        return

    if data == "admin_proxy_clear":
        user_manager.clear_proxies()
        await query.answer("已清空", show_alert=True)
        await admin_callback(update, context)

# ================= 文本处理 =================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    state = context.user_data.get('state', 0)

    if state == FEEDBACK_STATE:
        if ADMIN_ID:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"📩 **反馈**\n用户: {user.full_name} ({user.id})\n内容: {text}")
            await update.message.reply_text("✅ 反馈已提交。")
        else:
            await update.message.reply_text("未设置管理员。")
        context.user_data['state'] = 0
        return

    if str(user.id) == str(ADMIN_ID):
        if state == ADMIN_WAIT_BROADCAST_MSG:
            ids = user_manager.get_all_users()
            sent = 0
            await update.message.reply_text(f"⏳ 正在广播给 {len(ids)} 人...")
            for uid in ids:
                try:
                    await context.bot.copy_message(chat_id=uid, from_chat_id=user.id, message_id=update.message.message_id)
                    sent += 1
                    await asyncio.sleep(0.05)
                except: pass
            await update.message.reply_text(f"✅ 成功发送: {sent}")
            context.user_data['state'] = ADMIN_STATE_NONE
            return

        if state == ADMIN_WAIT_CHANNEL_SET:
            val = "" if text == "clear" else text
            user_manager.set_config("required_channel", val)
            await update.message.reply_text(f"✅ 频道设置: {val}")
            context.user_data['state'] = ADMIN_STATE_NONE
            return

        if state == ADMIN_WAIT_BAN_ID:
            uid = text.strip()
            new_stat = not user_manager.is_banned(uid)
            user_manager.set_ban(uid, new_stat)
            await update.message.reply_text(f"用户 {uid} 封禁状态: {new_stat}")
            context.user_data['state'] = ADMIN_STATE_NONE
            return

        if state == ADMIN_WAIT_PROXY_LIST:
            proxies = text.strip().split('\n')
            user_manager.add_proxies(proxies)
            await update.message.reply_text(f"✅ 添加 {len(proxies)} 个代理")
            context.user_data['state'] = ADMIN_STATE_NONE
            return

async def post_init(app):
    await app.bot.set_my_commands([BotCommand("start", "主菜单"), BotCommand("feedback", "反馈")])

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("feedback", lambda u,c: user_callback(u,c) or u.callback_query.data=="user_feedback"))
    
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_.*"))
    app.add_handler(CallbackQueryHandler(user_callback, pattern="^user_.*|^main_menu_root$|^plugin_.*"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))
    
    # 注册插件
    yanci.register_handlers(app)
    flexiroam.register_handlers(app)
    jetfi.register_handlers(app)
    travelgoogoo.register_handlers(app)
    
    print("✅ Bot Started with MySQL...")
    app.run_polling()

if __name__ == '__main__':
    main()
