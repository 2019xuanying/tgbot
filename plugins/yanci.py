import logging
import requests
import re
import random
import time
import asyncio
import traceback
from urllib.parse import unquote, urlparse, parse_qs
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters

# 导入通用工具
from utils.database import user_manager, ADMIN_ID
from utils.mail import MailTm

logger = logging.getLogger(__name__)

# ================= 状态常量定义 =================
YANCI_STATE_NONE = 0
YANCI_STATE_WAIT_MANUAL_EMAIL = 4

# ================= 业务逻辑工具类 (完整版) =================

FIXED_PASSWORD = "Pass1234"
PRODUCT_ID = '974'

URLS = {
    "entry": "https://www.yanci.com.tw/register",
    "register": "https://www.yanci.com.tw/storeregd",
    "send_verify": "https://www.yanci.com.tw/sendvcurl", 
    "login": "https://www.yanci.com.tw/login",
    "update": "https://www.yanci.com.tw/updateopt",
    "order": "https://www.yanci.com.tw/gives"
}

HEADERS_BASE = {
    'Host': 'www.yanci.com.tw',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Origin': 'https://www.yanci.com.tw',
}

class YanciBotLogic:
    @staticmethod
    def generate_taiwan_phone():
        return f"09{random.randint(10000000, 99999999)}"

    @staticmethod
    def generate_random_name():
        if random.random() < 0.3:
            first_names_en = ["James", "John", "Robert", "Michael", "David", "William", "Richard", "Joseph", "Thomas", "Charles", "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen"]
            last_names_en = ["Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris"]
            return f"{random.choice(first_names_en)} {random.choice(last_names_en)}"
        else:
            last_names_cn = ["陳", "林", "黃", "張", "李", "王", "吳", "劉", "蔡", "楊", "許", "鄭", "謝", "郭", "洪", "曾", "邱", "廖", "賴", "徐"]
            first_names_cn = ["家豪", "志明", "俊傑", "建宏", "俊宏", "志偉", "志強", "文雄", "淑芬", "淑惠", "美玲", "雅婷", "美惠", "麗华", "秀英", "宗翰", "怡君", "雅雯", "欣怡", "心怡"]
            return f"{random.choice(last_names_cn)}{random.choice(first_names_cn)}"

    @staticmethod
    def generate_random_address():
        locations = [
            {"city": "臺北市", "area": "信義區", "zip": "110"},
            {"city": "臺北市", "area": "大安區", "zip": "106"},
            {"city": "新北市", "area": "板橋區", "zip": "220"},
            {"city": "桃園市", "area": "桃園區", "zip": "330"},
            {"city": "臺中市", "area": "西屯區", "zip": "407"},
            {"city": "臺南市", "area": "東區", "zip": "701"},
            {"city": "高雄市", "area": "左營區", "zip": "813"},
        ]
        roads = ["中正路", "中山路", "中華路", "建國路", "復興路", "三民路", "民生路", "信義路"]
        loc = random.choice(locations)
        road = random.choice(roads)
        section = f"{random.randint(1, 5)}段" if random.random() > 0.5 else ""
        no = f"{random.randint(1, 500)}號"
        floor = f"{random.randint(2, 20)}樓" if random.random() > 0.3 else ""
        full_addr = f"{road}{section}{no}{floor}"
        return {"city": loc["city"], "area": loc["area"], "zip": loc["zip"], "addr": full_addr}

    @staticmethod
    def extract_id(text_or_url):
        match_url = re.search(r'[&?](\d{5})(?:$|&)', text_or_url)
        if match_url: return match_url.group(1)
        match_html = re.search(r'vc=Y(?:&amp;|&)(\d{5})', text_or_url)
        if match_html: return match_html.group(1)
        return None
    
    @staticmethod
    def extract_verification_link(html_content):
        if not html_content or not isinstance(html_content, str): return None
        match = re.search(r'(https?://www\.yanci\.com\.tw/sendvcurl[^\s"\'<>]+)', html_content)
        if match: return match.group(1)
        return None

    @staticmethod
    def extract_text_from_html(html_content):
        try:
            alert_match = re.search(r"alert\(['\"](.*?)['\"]\)", html_content)
            if alert_match: return f"弹窗提示: {alert_match.group(1)}"
            clean_text = re.sub('<[^<]+?>', '', html_content).strip()
            return clean_text[:100].replace('\n', ' ')
        except: return "无法解析页面内容"
        
    @staticmethod
    def extract_esim_info(html_content):
        if not html_content or not isinstance(html_content, str): return None
        info = {}
        # 1. 提取 SM-DP+ Address 和 激活码
        sm_dp_match = re.search(r'【SM-DP\+Address】(?:[\s\n<[^>]+>]*)([\w\.\-]+)', html_content)
        code_match = re.search(r'【啟用碼】(?:[\s\n<[^>]+>]*)([\w\-]+)', html_content)

        if sm_dp_match and code_match:
            sm_dp = sm_dp_match.group(1).strip()
            code = code_match.group(1).strip()
            info['lpa_str'] = f"LPA:1${sm_dp}${code}"
            info['address'] = sm_dp
            info['code'] = code

        # 2. 提取二维码图片链接
        qr_match = re.search(r'(https?://quickchart\.io/qr\?[^"\'\s>]+)', html_content)
        if qr_match:
            info['qr_url'] = qr_match.group(1).replace('&amp;', '&')
        
        # 3. 备用提取
        if 'qr_url' not in info:
             img_candidates = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_content)
             for img_url in img_candidates:
                 if not any(k in img_url for k in ['icon', 'banner', 'footer', 'logo']):
                     if 'qr' in img_url.lower() or 'code' in img_url.lower():
                         info['qr_url'] = img_url
                         break
        
        # 4. 反向解析
        if 'lpa_str' not in info and 'qr_url' in info:
            try:
                parsed = urlparse(info['qr_url'])
                qs = parse_qs(parsed.query)
                if 'text' in qs:
                    info['lpa_str'] = qs['text'][0]
            except: pass

        return info if info else None

    @staticmethod
    def get_initial_session():
        session = requests.Session()
        session.headers.update(HEADERS_BASE)
        try:
            resp = session.get(URLS['entry'] + "?lg=tw", timeout=15, allow_redirects=True)
            found_id = YanciBotLogic.extract_id(resp.url) or YanciBotLogic.extract_id(resp.text)
            if found_id:
                logger.info(f"成功获取 ID: {found_id}")
                return session, found_id, "成功"
            else:
                random_id = str(random.randint(20000, 30000))
                logger.warning(f"未找到 ID，使用随机 ID: {random_id}")
                return session, random_id, "随机生成"
        except Exception as e:
            return None, None, f"网络错误: {str(e)}"

    @staticmethod
    def register_loop(session, email, phone, start_id):
        current_id = start_id
        max_retries = 3
        for attempt in range(max_retries):
            logger.info(f"注册尝试 {attempt+1}/{max_retries} (ID: {current_id}) -> {email}")
            payload = {'userMode': 'normal', 'userACC': email, 'userPWD': FIXED_PASSWORD, 'userPhn': phone, 'userChk': 'true', 'userPage': ''}
            headers = HEADERS_BASE.copy()
            headers['Referer'] = f"{URLS['entry']}?lg=tw&vc=Y&{current_id}"
            try:
                resp = session.post(URLS['register'], headers=headers, data=payload, timeout=20)
                resp.encoding = 'utf-8'
                try:
                    res_json = resp.json()
                    if isinstance(res_json, list) and len(res_json) > 0:
                        code = res_json[0].get('code')
                        msg = res_json[0].get('msg', '')
                        if code == '400':
                            if "唯一" in msg or "重複" in msg or "重复" in msg: return True, current_id, "账号已存在(视为成功)"
                            return False, current_id, f"服务器拒绝: {msg}"
                except: pass

                if "<!DOCTYPE html>" in resp.text or "vc=Y" in resp.text:
                    new_id = YanciBotLogic.extract_id(resp.text) or YanciBotLogic.extract_id(resp.url)
                    if new_id and new_id != current_id:
                        logger.info(f"检测到 ID 变更 (旧: {current_id} -> 新: {new_id})，准备重试...")
                        current_id = new_id
                        time.sleep(1)
                        continue
                    else: return False, current_id, "注册被拒绝且无法获取新ID"

                if resp.status_code == 200: return True, current_id, "注册请求已发送"
                return False, current_id, f"HTTP状态异常: {resp.status_code}"
            except Exception as e: return False, current_id, f"请求异常: {str(e)}"
        return False, current_id, "超过最大重试次数"

    @staticmethod
    def send_verify_email(session, verify_id):
        url = f"{URLS['send_verify']}{verify_id}"
        headers = HEADERS_BASE.copy()
        headers['Referer'] = f"{URLS['entry']}?lg=tw&vc=Y&{verify_id}"
        headers['Accept'] = 'application/json, text/plain, */*'
        try:
            time.sleep(1)
            resp = session.post(url, headers=headers, data='Y', timeout=20)
            if resp.status_code == 200 and "400" not in resp.text: return True, "发送成功"
            return False, f"发送失败 (Code: {resp.status_code})"
        except Exception as e: return False, str(e)
    
    @staticmethod
    def visit_verification_link(session, link):
        try:
            headers = HEADERS_BASE.copy()
            headers['Referer'] = 'https://mail.tm/'
            resp = session.get(link, headers=headers, timeout=20)
            if resp.status_code == 200: return True, "验证链接访问成功"
            return False, f"验证链接访问失败: {resp.status_code}"
        except Exception as e: return False, str(e)

    @staticmethod
    def login(session, email):
        headers = HEADERS_BASE.copy()
        headers['Referer'] = URLS['login']
        headers['X-Requested-With'] = 'XMLHttpRequest'
        headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
        payload = {'userMode': 'normal', 'userACC': email, 'userPWD': FIXED_PASSWORD, 'userRem': 'true', 'userPage': ''}
        try:
            resp = session.post(URLS['login'], headers=headers, data=payload, timeout=20)
            if resp.status_code == 200 and "alert" not in resp.text: return True, "登录成功"
            return False, "登录失败(可能是密码错误或未验证)"
        except Exception as e: return False, str(e)

    @staticmethod
    def update_profile(session, phone):
        name = YanciBotLogic.generate_random_name()
        addr_data = YanciBotLogic.generate_random_address()
        sex = '男性' if random.random() > 0.5 else '女性'
        headers = HEADERS_BASE.copy()
        headers['Referer'] = 'https://www.yanci.com.tw/member_edit'
        headers['X-Requested-With'] = 'XMLHttpRequest'
        payload = {'userName': name, 'userSex': sex, 'userPhn': phone, 'userTel': phone, 'userZip': addr_data['zip'], 'userCity': addr_data['city'], 'userArea': addr_data['area'], 'userAddr': addr_data['addr']}
        logger.info(f"正在更新资料: {name} | {addr_data['city']}{addr_data['area']}")
        try:
            resp = session.post(URLS['update'], headers=headers, data=payload, timeout=20)
            return resp.status_code == 200, name
        except: return False, name

    @staticmethod
    def place_order(session):
        time.sleep(1.0)
        headers = HEADERS_BASE.copy()
        headers['Referer'] = 'https://www.yanci.com.tw/product_give'
        headers['X-Requested-With'] = 'XMLHttpRequest'
        if 'Upgrade-Insecure-Requests' in headers: del headers['Upgrade-Insecure-Requests']
        payload = {'given': PRODUCT_ID, 'giveq': '1'}
        try:
            resp = session.post(URLS['order'], headers=headers, data=payload, timeout=20)
            resp.encoding = 'utf-8'
            logger.info(f"下单接口返回: Status={resp.status_code} | Body Len={len(resp.text)}")
            try:
                res_json = resp.json()
                if isinstance(res_json, list) and len(res_json) > 0:
                    data = res_json[0]
                    code = str(data.get('code', ''))
                    msg = data.get('msg', '无返回信息')
                    if code == '200': return True, f"下单成功: {msg}"
                    elif code == '400': return False, f"服务器拒绝: {msg}"
            except: pass 
            if resp.status_code == 200:
                if "<!DOCTYPE html>" in resp.text or "<html" in resp.text:
                    title_match = re.search(r'<title>(.*?)</title>', resp.text, re.IGNORECASE)
                    page_title = title_match.group(1) if title_match else "未知页面"
                    page_text = YanciBotLogic.extract_text_from_html(resp.text)
                    if "登入" in page_title or "Login" in page_title or "登入" in page_text: return False, "下单失败: 会话失效(需重登录)"
                    return False, f"服务器返回页面: {page_title} (可能是: {page_text})"
                return True, "请求发送成功 (未返回错误)"
            return False, f"HTTP {resp.status_code}"
        except Exception as e: return False, str(e)


# ================= 自动化任务流程 =================

async def run_auto_task(query, context, user):
    """
    任务入口：尝试自动获取邮箱。
    如果失败，提示用户手动输入，进入半自动化流程。
    """
    await query.edit_message_text("🏗 **[Yanci] 正在初始化环境...**\n⏳ 正在申请临时邮箱 (Mail.tm)...")
    
    # 尝试创建邮箱
    email, mail_token = MailTm.create_account()
    
    # === 降级逻辑：如果自动邮箱失败 ===
    if not email or not mail_token:
        logger.warning("MailTm 接口异常，切换到人工输入模式")
        context.user_data['yanci_state'] = YANCI_STATE_WAIT_MANUAL_EMAIL
        await query.edit_message_text(
            "⚠️ **自动获取邮箱失败 (API繁忙)**\n\n"
            "请直接回复一个 **可用的邮箱地址** (推荐 Gmail/Outlook 或其他网页临时邮箱)。\n"
            "机器人将使用您提供的邮箱继续完成注册和下单。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 取消", callback_data="plugin_yanci_entry")]])
        )
        return
        
    # === 正常逻辑：自动模式 ===
    user_manager.increment_usage(user.id, user.first_name)
    
    # 开始执行核心注册流程 (Phase 1)
    await core_flow_register(query.message, context, user, email, mail_token=mail_token)


async def core_flow_register(status_msg, context, user, email, mail_token=None):
    """
    核心流程阶段 1：注册 -> 发送验证邮件
    支持自动模式 (mail_token not None) 和手动模式 (mail_token is None)
    """
    is_manual = (mail_token is None)
    phone = YanciBotLogic.generate_taiwan_phone()
    
    # 编辑状态消息 (如果是手动模式，status_msg 可能需要先发送)
    try:
        if status_msg:
            await status_msg.edit_text(
                f"🚀 **任务启动 ({'人工接管' if is_manual else '自动模式'})**\n\n"
                f"📧 `{email}`\n"
                f"⏳ **正在连接服务器...**", 
                parse_mode='Markdown'
            )
        else:
            # 如果没有传入消息对象，发一个新的
            status_msg = await context.bot.send_message(
                chat_id=user.id, 
                text=f"🚀 **任务启动**\n📧 `{email}`\n⏳ **正在连接服务器...**",
                parse_mode='Markdown'
            )
    except: pass

    try:
        session, verify_id, init_msg = await asyncio.get_running_loop().run_in_executor(None, YanciBotLogic.get_initial_session)
        if not session:
            await status_msg.edit_text(f"❌ 初始化失败: {init_msg}")
            return

        await status_msg.edit_text(f"✅ 获取ID: {verify_id}\n⏳ **正在提交注册请求...**")
        reg_success, final_id, reg_msg = await asyncio.get_running_loop().run_in_executor(
            None, YanciBotLogic.register_loop, session, email, phone, verify_id
        )
        if not reg_success:
            await status_msg.edit_text(f"❌ 注册被拒: {reg_msg}")
            return

        await status_msg.edit_text(f"✅ 注册请求已通过\n⏳ **正在触发验证邮件...**")
        send_success, send_msg = await asyncio.get_running_loop().run_in_executor(
            None, YanciBotLogic.send_verify_email, session, final_id
        )
        if not send_success:
            await status_msg.edit_text(f"❌ 发信失败: {send_msg}")
            return

        # === 分支：自动模式 vs 手动模式 ===
        
        if not is_manual:
            # --- 自动模式：轮询收件箱 ---
            await status_msg.edit_text(f"📩 **验证信已发送！**\n⏳ 正在自动监听邮箱 (最多等2分钟)...")
            
            verification_link = None
            start_time = time.time()
            
            while time.time() - start_time < 120:
                mails = await asyncio.get_running_loop().run_in_executor(None, MailTm.check_inbox, mail_token)
                if mails:
                    for mail in mails:
                        if "驗證" in mail.get('subject', '') or "Verify" in mail.get('subject', '') or "验证" in mail.get('subject', ''):
                            mail_detail = await asyncio.get_running_loop().run_in_executor(None, MailTm.get_message_content, mail_token, mail.get('id'))
                            if mail_detail:
                                link = YanciBotLogic.extract_verification_link(mail_detail.get('body', ''))
                                if link:
                                    verification_link = link
                                    break
                if verification_link: break
                await asyncio.sleep(4)

            if not verification_link:
                await status_msg.edit_text("❌ 等待超时，未收到验证邮件。任务终止。")
                return

            await status_msg.edit_text(f"🔎 **捕获到验证链接！**\n⏳ 正在模拟点击验证...")
            visit_success, visit_msg = await asyncio.get_running_loop().run_in_executor(
                None, YanciBotLogic.visit_verification_link, session, verification_link
            )
            
            if not visit_success:
                await status_msg.edit_text(f"❌ 验证链接访问失败: {visit_msg}")
                return

            # 验证通过，直接进入第二阶段
            await core_flow_finish(status_msg, context, user, session, email, phone, mail_token)
            
        else:
            # --- 手动模式：暂停并等待用户确认 ---
            # 保存当前的 session 对象到 user_data，以便后续恢复 (注意使用带前缀的Key)
            context.user_data['yanci_pending_manual_session'] = {
                'session': session,
                'email': email,
                'phone': phone
            }
            
            # 发送操作指引
            await status_msg.edit_text(
                f"📩 **验证邮件已发送至** `{email}`\n\n"
                f"⚠️ **请执行以下操作：**\n"
                f"1. 前往您的邮箱查收邮件。\n"
                f"2. 点击邮件中的 **验证链接**。\n"
                f"3. 确认验证成功后，点击下方的按钮继续。\n",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ 我已完成验证", callback_data="yanci_manual_verify_done")]]),
                parse_mode='Markdown'
            )
            return

    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(f"💥 注册流程异常: {str(e)}")


async def core_flow_finish(status_msg, context, user, session, email, phone, mail_token=None):
    """
    核心流程阶段 2：登录 -> 完善资料 -> 下单 -> 取码
    """
    try:
        await status_msg.edit_text(f"✅ 验证确认通过！\n⏳ **正在登录并自动下单...**")
        
        login_success, login_msg = await asyncio.get_running_loop().run_in_executor(None, YanciBotLogic.login, session, email)
        if not login_success:
            await status_msg.edit_text(f"❌ 登录失败: {login_msg}")
            return
            
        update_success, name = await asyncio.get_running_loop().run_in_executor(None, YanciBotLogic.update_profile, session, phone)
        if not update_success:
            await status_msg.edit_text("❌ 资料保存失败。")
            return

        order_success, order_msg = await asyncio.get_running_loop().run_in_executor(None, YanciBotLogic.place_order, session)
        
        # 简单的重试逻辑
        if not order_success and ("登入" in order_msg or "失效" in order_msg):
             await status_msg.edit_text("⚠️ 会话闪断，正在重连...")
             relogin_success, _ = await asyncio.get_running_loop().run_in_executor(None, YanciBotLogic.login, session, email)
             if relogin_success:
                 order_success, order_msg = await asyncio.get_running_loop().run_in_executor(None, YanciBotLogic.place_order, session)

        if not order_success:
             await status_msg.edit_text(f"❌ 下单最终失败: {order_msg}")
             return

        # 下单成功后的处理
        if mail_token:
            # --- 自动模式：等待发货邮件 ---
            await status_msg.edit_text(
                f"🎉 **下单成功！**\n"
                f"📧 邮箱: `{email}`\n"
                f"⏳ **正在等待发货邮件 (最多5分钟)...**\n(请勿关闭此对话)", 
                parse_mode='Markdown'
            )
            
            esim_data = None
            wait_mail_start = time.time()
            
            while time.time() - wait_mail_start < 300: 
                mails = await asyncio.get_running_loop().run_in_executor(None, MailTm.check_inbox, mail_token)
                if mails:
                    for mail in mails:
                        subject = mail.get('subject', '')
                        if any(k in subject for k in ["訂單", "Order", "開通", "eSIM", "成功", "QR code"]):
                            mail_detail = await asyncio.get_running_loop().run_in_executor(None, MailTm.get_message_content, mail_token, mail.get('id'))
                            if mail_detail:
                                extracted = YanciBotLogic.extract_esim_info(mail_detail.get('body', ''))
                                if extracted and extracted.get('lpa_str'):
                                    esim_data = extracted
                                    break
                if esim_data: break
                await asyncio.sleep(5)

            if esim_data:
                lpa_str = esim_data.get('lpa_str', '未知')
                final_text = (
                    f"✅ **eSIM 自动提取成功！**\n\n"
                    f"📡 **LPA 激活串**: \n`{lpa_str}`\n\n"
                    f"祝您使用愉快！"
                )
                await context.bot.send_message(chat_id=user.id, text=final_text, parse_mode='Markdown')
                
                send_qr_setting = user_manager.get_config("send_qr", True)
                qr_url = esim_data.get('qr_url')
                
                if send_qr_setting and qr_url:
                    try:
                        await context.bot.send_photo(chat_id=user.id, photo=qr_url, caption="📷 eSIM 二维码")
                    except Exception as e:
                        logger.error(f"发图失败: {e}")
                        await context.bot.send_message(chat_id=user.id, text="⚠️ 图片发送失败，请使用上方的 LPA 码激活。")
            else:
                final_text = (
                    f"✅ **任务完成 (但未捕获到发货邮件)**\n\n"
                    f"发货可能延迟，请稍后查看您的临时邮箱。\n"
                )
                await context.bot.send_message(chat_id=user.id, text=final_text, parse_mode='Markdown')
        else:
            # --- 手动模式：结束 ---
            final_text = (
                f"🎉 **下单成功！**\n\n"
                f"由于是手动邮箱 (`{email}`)，机器人无法自动提取 eSIM。\n"
                f"请前往您的邮箱查收发货邮件（通常在1-5分钟内）。"
            )
            await status_msg.edit_text(final_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(f"💥 后续流程异常: {str(e)}")

# ================= 菜单与回调处理器 =================

async def yanci_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """插件的主菜单入口"""
    user = update.effective_user
    context.user_data['yanci_state'] = YANCI_STATE_NONE
    
    # 🛡️ 插件内部防线：如果未授权，直接弹回主菜单
    if not user_manager.is_authorized(user.id):
        await update.callback_query.answer("🚫 权限校验失败，请先申请。", show_alert=True)
        # 也可以选择显示一个“请去申请”的界面
        keyboard = [[InlineKeyboardButton("🔙 返回主菜单申请", callback_data="main_menu_root")]]
        await update.callback_query.edit_message_text("🚫 **无权访问**\n\n请返回主菜单申请全局使用权限。", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # === 修复：检查插件开关 ===
    # 如果插件被禁用，且用户不是管理员，则拦截
    if not user_manager.get_plugin_status("yanci") and str(user.id) != str(ADMIN_ID):
        await update.callback_query.edit_message_text(
            "🛑 **该功能目前维护中**\n\n请稍后再试，或联系管理员。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]]),
            parse_mode='Markdown'
        )
        return

    welcome_text = (
        f"🌏 **Yanci 自动抢单助手**\n"
        f"服务状态: {'✅ 运行中' if user_manager.get_config('bot_active', True) else '🔴 维护中'}\n\n"
        f"请选择操作："
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 一键全自动下单", callback_data="yanci_auto_task")],
        [InlineKeyboardButton("👤 我的统计", callback_data="yanci_info")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def yanci_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    
    data = query.data

    # 再次检查权限 (防止直接调接口)
    if not user_manager.is_authorized(user.id):
        await query.edit_message_text("🚫 无权访问。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]]))
        return

    # === 修复：检查插件开关 ===
    # 防止用户通过旧消息的按钮直接触发功能
    if not user_manager.get_plugin_status("yanci") and str(user.id) != str(ADMIN_ID):
        await query.edit_message_text(
            "🛑 **该功能已关闭**\n\n管理员已暂停此服务。", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu_root")]])
        )
        return

    if data == "yanci_info":
        stats = user_manager.get_all_stats().get(str(user.id), {})
        count = stats.get('count', 0)
        await query.edit_message_text(
            f"📊 **Yanci 任务统计**\n\n用户: {user.first_name}\n累计执行: {count} 次",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_yanci_entry")]]),
            parse_mode='Markdown'
        )
        return

    if data == "yanci_auto_task":
        if not user_manager.get_config("bot_active", True) and user.id != ADMIN_ID:
             await query.edit_message_text(
                 "⚠️ **机器人维护中**", 
                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_yanci_entry")]])
             )
             return
        
        # 启动任务
        asyncio.create_task(run_auto_task(query, context, user))
        return

    # 手动验证回调
    if data == "yanci_manual_verify_done":
        session_data = context.user_data.get('yanci_pending_manual_session')
        if not session_data:
            await query.edit_message_text("⚠️ 会话已过期，请重新开始任务。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="plugin_yanci_entry")]]))
            return
        
        del context.user_data['yanci_pending_manual_session']
        
        session = session_data['session']
        email = session_data['email']
        phone = session_data['phone']
        
        status_msg = query.message
        await status_msg.edit_text(f"✅ 收到确认！\n📧 账号：`{email}`\n⏳ **正在继续执行自动化流程...**", parse_mode='Markdown')
        
        asyncio.create_task(core_flow_finish(status_msg, context, user, session, email, phone, mail_token=None))
        return

async def yanci_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理手动输入的邮箱"""
    state = context.user_data.get('yanci_state', YANCI_STATE_NONE)
    if state == YANCI_STATE_WAIT_MANUAL_EMAIL:
        # 这里也可以选择加上开关检查，但通常入口卡住就足够了
        text = update.message.text.strip()
        user = update.effective_user
        
        # 格式验证
        if "@" not in text or "." not in text:
            await update.message.reply_text("⚠️ 邮箱格式看起来不正确，请重新输入：")
            return
        
        # 重置状态
        context.user_data['yanci_state'] = YANCI_STATE_NONE
        
        # 启动手动模式流程
        await update.message.reply_text(f"✅ 已确认邮箱：{text}\n正在启动任务...")
        
        status_msg = await update.message.reply_text("⏳ 初始化中...")
        user_manager.increment_usage(user.id, user.first_name)
        
        asyncio.create_task(core_flow_register(status_msg, context, user, email=text, mail_token=None))

# ================= 注册函数 =================

def register_handlers(application):
    application.add_handler(CallbackQueryHandler(yanci_callback, pattern="^yanci_.*"))
    application.add_handler(CallbackQueryHandler(yanci_menu, pattern="^plugin_yanci_entry$"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), yanci_text_handler))
    print("🔌 Yanci 插件已加载")
