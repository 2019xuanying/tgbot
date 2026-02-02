import os
import sys
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

# 导入数据库
from utils.database import db, ADMIN_ID

# 导入插件
from plugins import yanci, flexiroam, jetfi, travelgoogoo

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

if not BOT_TOKEN:
    sys.exit("❌ 错误：未找到 TG_BOT_TOKEN")

# 定义状态
FEEDBACK_STATE = 1
ADMIN_PUSH_STATE = 2

# ================= 辅助函数 =================

async def check_channel_join(user_id, context):
    """检查用户是否加入了指定频道"""
    channel_id = db.get_config("force_join_channel", "")
    if not channel_id:
        return True # 未设置则跳过
    
    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status in ['left', 'kicked']:
            return False
        return True
    except Exception as e:
        logger.error(f"Check channel error: {e}")
        return True # 异常情况默认放行，避免配置错误导致无法使用

# ================= 主菜单逻辑 =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    
    # 1. 邀请处理与用户创建
    inviter_id = None
    if args and args[0].isdigit():
        inviter_id = int(args[0])
    
    # 获取或创建用户 (数据库操作)
    db_user = db.get_or_create_user(user.id, user.username, user.first_name, inviter_id)
    
    if db_user.is_banned:
        await update.message.reply_text("🚫 您的账号已被封禁。")
        return

    text = (
        f"🤖 **聚合控制中心 v2.0**\n\n"
        f"你好，{user.first_name}！\n"
        f"ID: `{user.id}`\n"
        f"💰 积分: **{db_user.balance}**\n\n"
        f"🔗 **您的邀请链接**:\n"
        f"`https://t.me/{context.bot.username}?start={user.id}`\n"
        f"(邀请有用户名的新用户可获奖励)\n"
    )

    keyboard = [
        [InlineKeyboardButton("📅 每日签到", callback_data="feature_checkin"), 
         InlineKeyboardButton("📝 提交反馈", callback_data="feature_feedback")],
        [InlineKeyboardButton("🌏 Yanci", callback_data="plugin_yanci_entry"),
         InlineKeyboardButton("🌐 Flexiroam", callback_data="plugin_flexi_entry")],
        [InlineKeyboardButton("🚙 JetFi", callback_data="plugin_jetfi_entry"),
         InlineKeyboardButton("🏝 TravelGooGoo", callback_data="plugin_travel_entry")],
        [InlineKeyboardButton("👥 我的邀请", callback_data="feature_my_invites")]
    ]

    if str(user.id) == str(ADMIN_ID):
         keyboard.append([InlineKeyboardButton("👮 管理员后台", callback_data="admin_menu_main")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ================= 通用功能回调 =================

async def feature_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    data = query.data

    # 1. 强制关注检查
    if not await check_channel_join(user.id, context):
        channel_id = db.get_config("force_join_channel")
        await query.edit_message_text(
            f"⚠️ **请先加入频道**\n为了使用本机器人，请先加入频道。\n\n加入后重新输入 /start",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("加入频道", url=f"https://t.me/{channel_id.replace('@','')}")]])
        )
        return

    # 2. 每日签到
    if data == "feature_checkin":
        success, msg = db.daily_checkin(user.id)
        await query.edit_message_text(
            f"📅 **签到结果**\n\n{msg}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]])
        )
        return

    # 3. 我的邀请
    if data == "feature_my_invites":
        invitees = db.get_invite_list(user.id)
        text = f"👥 **我的邀请记录**\n\n累计邀请: {len(invitees)} 人\n\n"
        if not invitees:
            text += "暂无邀请记录，快去分享链接吧！"
        else:
            text += "最近 10 位:\n"
            for inv in invitees[:10]:
                name = inv[1] or "无用户名"
                text += f"- `{inv[0]}` ({name})\n"
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]], parse_mode='Markdown'))
        return

    # 4. 反馈入口
    if data == "feature_feedback":
        await query.edit_message_text("📝 **请输入您的反馈内容：**\n(请直接回复消息，输入 /cancel 取消)")
        return str(FEEDBACK_STATE) # 返回状态给 ConversationHandler

# ================= 反馈处理 =================

async def feedback_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    content = update.message.text
    user = update.effective_user
    db.add_feedback(user.id, content)
    await update.message.reply_text(
        "✅ **反馈已提交**\n管理员会尽快处理。",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]], parse_mode='Markdown')
    )
    return ConversationHandler.END

async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("已取消。")
    return ConversationHandler.END

# ================= 管理员后台 =================

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if str(user.id) != str(ADMIN_ID): return
    await query.answer()
    data = query.data

    if data == "admin_menu_main":
        text = "👮 **管理员控制台**"
        kb = [
            [InlineKeyboardButton("📢 全员推送", callback_data="admin_push_msg")],
            [InlineKeyboardButton("🔨 用户管理 (封禁/充值)", callback_data="admin_user_mgmt")],
            [InlineKeyboardButton("⚙️ 参数设置", callback_data="admin_settings")],
            [InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return

    if data == "admin_push_msg":
        await query.edit_message_text("📢 **请输入要推送的消息内容：**\n(支持 Markdown，输入 /cancel 取消)")
        return str(ADMIN_PUSH_STATE)

    if data == "admin_settings":
        # 显示当前配置
        cfg_inv = db.get_config("invite_reward")
        cfg_chk = db.get_config("checkin_reward")
        cfg_y = db.get_config("cost_yanci")
        text = (
            f"⚙️ **系统参数**\n\n"
            f"邀请奖励: {cfg_inv}\n"
            f"签到奖励: {cfg_chk}\n"
            f"Yanci消耗: {cfg_y}\n\n"
            f"⚠️ 修改请直接修改数据库 `settings` 表或后续开发指令设置。"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_menu_main")]]))
        return
        
    # 用户管理子菜单 (简化版，实际可通过命令 /ban uid 实现)
    if data == "admin_user_mgmt":
        text = "🔨 请使用命令操作：\n\n`/ban 123456` - 封禁用户\n`/unban 123456` - 解封用户\n`/add 123456 100` - 充值积分"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_menu_main")]]), parse_mode='Markdown')
        return

# === 管理员命令处理 ===

async def admin_cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID): return
    try:
        target_id = int(context.args[0])
        db.set_ban(target_id, True)
        await update.message.reply_text(f"✅ 用户 {target_id} 已封禁。")
    except: await update.message.reply_text("用法: /ban <uid>")

async def admin_cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID): return
    try:
        target_id = int(context.args[0])
        db.set_ban(target_id, False)
        await update.message.reply_text(f"✅ 用户 {target_id} 已解封。")
    except: await update.message.reply_text("用法: /unban <uid>")

async def admin_cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID): return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        db.admin_add_points(target_id, amount)
        await update.message.reply_text(f"✅ 已给 {target_id} 增加 {amount} 积分。")
    except: await update.message.reply_text("用法: /add <uid> <amount>")

async def admin_push_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    user_ids = db.get_all_user_ids()
    count = 0
    status_msg = await update.message.reply_text(f"🚀 开始向 {len(user_ids)} 人推送...")
    
    for uid in user_ids:
        try:
            await context.bot.send_message(uid, f"📢 **系统通知**\n\n{msg}", parse_mode='Markdown')
            count += 1
        except Exception:
            pass # 用户可能已封锁机器人
        if count % 20 == 0:
            await asyncio.sleep(1) # 限流
            
    await status_msg.edit_text(f"✅ 推送完成，成功发送: {count} 人。")
    return ConversationHandler.END

# ================= 启动逻辑 =================

async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "主菜单"),
        BotCommand("ban", "封禁 (Admin)"),
        BotCommand("add", "充值 (Admin)"),
    ])

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # 1. 对话处理器 (反馈 & 推送)
    fb_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(feature_callback, pattern="^feature_feedback$")],
        states={str(FEEDBACK_STATE): [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_handle)]},
        fallbacks=[CommandHandler("cancel", cancel_feedback)]
    )
    
    push_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^admin_push_msg$")],
        states={str(ADMIN_PUSH_STATE): [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_push_handle)]},
        fallbacks=[CommandHandler("cancel", cancel_feedback)]
    )
    
    application.add_handler(fb_handler)
    application.add_handler(push_handler)

    # 2. 基础命令
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ban", admin_cmd_ban))
    application.add_handler(CommandHandler("unban", admin_cmd_unban))
    application.add_handler(CommandHandler("add", admin_cmd_add))

    # 3. 回调处理
    application.add_handler(CallbackQueryHandler(start, pattern="^main_menu_root$"))
    application.add_handler(CallbackQueryHandler(feature_callback, pattern="^feature_.*"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_.*"))
    
    # 4. 插件加载
    yanci.register_handlers(application)
    flexiroam.register_handlers(application)
    jetfi.register_handlers(application)
    travelgoogoo.register_handlers(application)

    print("✅ 机器人 v2.0 (MySQL版) 已启动...")
    application.run_polling()

if __name__ == '__main__':
    main()
