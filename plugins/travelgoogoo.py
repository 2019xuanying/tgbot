import logging
import asyncio
import traceback
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from PIL import Image
from pyzbar.pyzbar import decode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

# 导入通用工具
from utils.database import user_manager
from utils.proxy import get_safe_session

logger = logging.getLogger(__name__)

# ================= 状态常量 =================
TRAVEL_STATE_NONE = 0
TRAVEL_STATE_WAIT_INPUT = 1

# ================= 核心逻辑 =================

class TravelLogic:
    # URL 模板
    URL_TEMPLATE = "https://travelgoogoo-public-qr-prd.s3.ap-southeast-1.amazonaws.com/{year}/{month}/{day}/{number}.png"

    @staticmethod
    def luhn_calc(num_str):
        """计算 Luhn 校验位"""
        digits = [int(c) for c in num_str]
        odd_sum = sum(digits[-1::-2])
        even_sum = sum([sum(divmod(2 * d, 10)) for d in digits[-2::-2]])
        total = odd_sum + even_sum
        return (10 - (total % 10)) % 10

    @staticmethod
    def generate_targets(base_number: str):
        """
        生成扫描目标列表。
        Base(15) + Suffix(3) + Luhn(1) = 19位
        Base(15) + Suffix(4) + Luhn(1) = 20位
        """
        targets = []
        
        # 模式 1: 3位后缀 (000-999) -> 总长 19
        for i in range(1000):
            body = f"{base_number}{i:03d}"
            check = TravelLogic.luhn_calc(body)
            targets.append(f"{body}{check}")
            
        # 模式 2: 4位后缀 (0000-1000) -> 总长 20
        for i in range(1000): 
            body = f"{base_number}{i:04d}"
            check = TravelLogic.luhn_calc(body)
            targets.append(f"{body}{check}")
            
        return targets

    @staticmethod
    def check_and_decode(number: str, date_str: str, session: requests.Session):
        """
        下载并解码
        date_str 格式: YYYYMMDD
        """
        try:
            year, month, day = date_str[:4], date_str[4:6], date_str[6:8]
            url = TravelLogic.URL_TEMPLATE.format(year=year, month=month, day=day, number=number)
            
            # 1. HEAD 请求预检
            try:
                head_resp = session.head(url, timeout=3)
                if head_resp.status_code != 200:
                    return None
            except:
                return None

            # 2. GET 下载
            resp = session.get(url, timeout=5)
            if resp.status_code == 200:
                try:
                    img = Image.open(BytesIO(resp.content))
                    decoded = decode(img)
                    if decoded:
                        # 提取解码内容，通常只有一个
                        content_list = [d.data.decode('utf-8') for d in decoded]
                        content_str = "\n".join(content_list) # 拼接，以防有多个
                        return {
                            'number': number, 
                            'url': url, 
                            'content': content_str,  # 这里存字符串
                            'bytes': resp.content
                        }
                except:
                    pass
        except Exception:
            pass
        return None

# ================= 任务流程 =================

async def run_scan_task(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_input: str):
    user = update.effective_user
    
    parts = raw_input.split()
    base_number = parts[0]
    
    if len(parts) > 1:
        date_str = parts[1]
    else:
        date_str = datetime.now().strftime("%Y%m%d")

    # 简单校验
    if len(base_number) != 15 or not base_number.isdigit():
        await update.message.reply_text("❌ Base Number 必须是 15 位数字。")
        return
    if len(date_str) != 8 or not date_str.isdigit():
        await update.message.reply_text("❌ 日期格式错误，应为 YYYYMMDD (例如 20260202)。")
        return

    status_msg = await update.message.reply_text(
        f"🚀 **任务已启动**\n"
        f"🎯 基数: `{base_number}`\n"
        f"📅 日期: `{date_str}`\n"
        f"⏳ 正在初始化扫描...",
        parse_mode='Markdown'
    )

    targets = TravelLogic.generate_targets(base_number)
    total = len(targets)
    
    session = await asyncio.get_running_loop().run_in_executor(None, get_safe_session)
    
    scanned = 0
    
    def batch_scan():
        nonlocal scanned
        results = []
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = {executor.submit(TravelLogic.check_and_decode, num, date_str, session): num for num in targets}
            
            for f in as_completed(futures):
                scanned += 1
                res = f.result()
                if res:
                    results.append(res)
        return results

    try:
        await status_msg.edit_text(f"📡 **正在扫描 {total} 个目标...**\n(使用 HEAD 预检 + 代理池)")
        
        final_results = await asyncio.get_running_loop().run_in_executor(None, batch_scan)
        
        if not final_results:
            await status_msg.edit_text(
                f"💨 **扫描结束**\n"
                f"Base: `{base_number}`\n"
                f"Date: `{date_str}`\n"
                f"结果: 未发现有效 QR 码 (已扫 {total} 个地址)。"
            )
        else:
            await status_msg.edit_text(f"🎉 **扫描完成！发现 {len(final_results)} 个有效码**")
            
            for item in final_results:
                # === 核心修改处：优化输出信息 ===
                content_text = item.get('content', '无法解码')
                
                caption = (
                    f"🎫 **eSIM QR Code**\n"
                    f"ID: `{item['number']}`\n\n"
                    f"📝 **安装代码 (LPA)**:\n"
                    f"`{content_text}`\n\n" # 将解码内容放入代码块，方便复制
                    f"🔗 [原始图片链接]({item['url']})"
                )
                try:
                    await context.bot.send_photo(
                        chat_id=user.id,
                        photo=item['bytes'],
                        caption=caption,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"发图失败: {e}")
                    # 如果发图失败（比如图片太大或格式问题），尝试只发文字
                    await context.bot.send_message(
                        chat_id=user.id,
                        text=f"⚠️ 图片发送失败，但已解码：\n\n{caption}",
                        parse_mode='Markdown'
                    )
                    
    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(f"💥 发生错误: {e}")

# ================= 菜单与交互 =================

async def travel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_manager.is_authorized(update.effective_user.id):
        return

    text = (
        "🏝 **TravelGooGoo 扫描器 (Pro)**\n\n"
        "✅ **功能特点**:\n"
        "1. 自动计算校验码 (19/20位)\n"
        "2. 支持自定义日期 (默认今天)\n"
        "3. **自动解析并显示 LPA 激活码**\n"
    )
    keyboard = [[InlineKeyboardButton("🚀 开始扫描", callback_data="travel_start")],
                [InlineKeyboardButton("🔙 返回", callback_data="main_menu_root")]]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def travel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "travel_start":
        context.user_data['travel_state'] = TRAVEL_STATE_WAIT_INPUT
        await query.edit_message_text(
            "📝 **请输入参数**\n\n"
            "格式: `BaseNumber [日期]`\n"
            "示例: `896501251118099 20260202`\n\n"
            "请直接回复消息:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_travel_entry")]]),
            parse_mode='Markdown'
        )

async def travel_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('travel_state') == TRAVEL_STATE_WAIT_INPUT:
        context.user_data['travel_state'] = TRAVEL_STATE_NONE
        await run_scan_task(update, context, update.message.text.strip())

def register_handlers(app):
    app.add_handler(CallbackQueryHandler(travel_menu, pattern="^plugin_travel_entry$"))
    app.add_handler(CallbackQueryHandler(travel_callback, pattern="^travel_.*"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), travel_text), group=2)
