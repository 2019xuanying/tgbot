import requests
import time
import random
import logging

logger = logging.getLogger(__name__)

class MailTm:
    BASE_URL = "https://api.mail.tm"

    @staticmethod
    def create_account():
        """创建临时账户，返回 (address, token)"""
        try:
            time.sleep(random.uniform(0.5, 2.0))
            
            domains_resp = requests.get(f"{MailTm.BASE_URL}/domains", timeout=10)
            if domains_resp.status_code != 200: return None, None
            
            domains_data = domains_resp.json().get('hydra:member', [])
            if not domains_data: return None, None
            
            domain = domains_data[0]['domain'] 

            username = "".join(random.choices("abcdefghijklmnopqrstuvwxyz1234567890", k=10))
            password = "".join(random.choices("abcdefghijklmnopqrstuvwxyz1234567890", k=12))
            address = f"{username}@{domain}"

            reg_resp = requests.post(
                f"{MailTm.BASE_URL}/accounts", 
                json={"address": address, "password": password},
                timeout=10
            )
            if reg_resp.status_code != 201: return None, None

            token_resp = requests.post(
                f"{MailTm.BASE_URL}/token",
                json={"address": address, "password": password},
                timeout=10
            )
            if token_resp.status_code != 200: return None, None

            token = token_resp.json().get('token')
            return address, token

        except Exception as e:
            logger.error(f"MailTm create_account exception: {e}")
            return None, None

    @staticmethod
    def check_inbox(token):
        if not token: return []
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.get(f"{MailTm.BASE_URL}/messages", headers=headers, timeout=10)
            if resp.status_code == 200: return resp.json().get('hydra:member', [])
            return []
        except: return []

    @staticmethod
    def get_message_content(token, msg_id):
        if not token: return None
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.get(f"{MailTm.BASE_URL}/messages/{msg_id}", headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                body = data.get('html')
                if not body: body = data.get('text')
                
                if body is None: body = ""
                elif not isinstance(body, str): body = str(body)

                subject = data.get('subject')
                if subject is None: subject = ""
                
                return {'body': body, 'subject': str(subject)}
            return None
        except: return None