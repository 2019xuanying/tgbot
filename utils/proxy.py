import requests
import random
import logging
from utils.database import user_manager

logger = logging.getLogger(__name__)

class ProxyManager:
    @staticmethod
    def parse_proxy(proxy_str):
        """
        解析代理字符串，支持两种格式：
        1. ip:port:user:pass -> socks5://user:pass@ip:port
        2. ip:port -> http://ip:port
        """
        try:
            parts = proxy_str.strip().split(':')
            if len(parts) == 4:
                # Format: ip:port:user:pass (SOCKS5)
                ip, port, user, password = parts
                return f"socks5://{user}:{password}@{ip}:{port}"
            elif len(parts) == 2:
                # Format: ip:port (HTTP)
                ip, port = parts
                return f"http://{ip}:{port}"
            else:
                return None
        except:
            return None

    @staticmethod
    def get_configured_session(test_url="https://www.google.com", timeout=10):
        """
        核心方法：获取一个配置好的 Session。
        """
        session = requests.Session()
        
        # 1. 基础 Header
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        # 2. 检查全局开关
        use_proxy = user_manager.get_config("use_proxy", True)
        if not use_proxy:
            # logger.info("代理开关已关闭，使用直连模式。") 
            return session

        # 3. 获取代理列表
        raw_proxies = user_manager.get_proxies()
        if not raw_proxies:
            logger.warning("代理列表为空，使用直连模式。")
            return session

        # 4. 尝试连接 (最多5次)
        max_retries = 5
        candidates = random.sample(raw_proxies, min(len(raw_proxies), max_retries * 2)) 
        
        tried_count = 0
        for proxy_str in candidates:
            if tried_count >= max_retries:
                break
            
            formatted_proxy = ProxyManager.parse_proxy(proxy_str)
            if not formatted_proxy:
                continue

            # 配置临时代理进行测试
            proxies_dict = {'http': formatted_proxy, 'https': formatted_proxy}
            
            try:
                # logger.info(f"正在尝试代理 ({tried_count+1}/{max_retries}): {proxy_str} ...")
                test_sess = requests.Session()
                test_sess.proxies = proxies_dict
                
                # 增加 verify=False 避免部分代理 SSL 握手问题导致失败，仅测试连通性
                # 注意：这可能会有安全警告，但在测试代理连通性时是可以接受的
                resp = test_sess.get(test_url, timeout=timeout)
                
                if resp.status_code == 200:
                    logger.info(f"✅ 代理连接成功: {formatted_proxy}")
                    session.proxies = proxies_dict
                    return session
            except Exception as e:
                # === 修改处：打印详细错误信息以便排查 ===
                # 常见错误：
                # 1. ProxyError: 代理无法连接 (IP死的/端口不对)
                # 2. ConnectTimeout: 超时
                # 3. SSLError: 代理不支持 HTTPS 握手
                logger.error(f"⚠️ 代理 {proxy_str} 失败: {type(e).__name__} - {str(e)}")
            
            tried_count += 1

        # 5. 降级处理
        logger.error(f"❌ 所有 {tried_count} 次代理尝试均失败，降级为【服务器直连】模式。")
        return session

# 方便外部调用
get_safe_session = ProxyManager.get_configured_session
