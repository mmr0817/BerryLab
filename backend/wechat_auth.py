import requests
import json
from flask import current_app
from datetime import datetime, timedelta
import jwt

class WeChatAuth:
    @staticmethod
    def get_openid(code):
        """通过code获取openid和session_key"""
        appid = current_app.config['WECHAT_APPID']
        secret = current_app.config['WECHAT_SECRET']
        
        url = f"https://api.weixin.qq.com/sns/jscode2session?appid={appid}&secret={secret}&js_code={code}&grant_type=authorization_code"
        
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            
            if 'openid' in data:
                return {
                    'openid': data['openid'],
                    'session_key': data.get('session_key'),
                    'unionid': data.get('unionid')
                }
            else:
                current_app.logger.error(f"WeChat API error: {data}")
                return None
        except Exception as e:
            current_app.logger.error(f"WeChat API call failed: {e}")
            return None
    
    @staticmethod
    def generate_token(user_id, openid):
        """生成JWT token"""
        payload = {
            'user_id': user_id,
            'openid': openid,
            'exp': datetime.utcnow() + timedelta(seconds=current_app.config['JWT_ACCESS_TOKEN_EXPIRES'])
        }
        return jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    
    @staticmethod
    def verify_token(token):
        """验证JWT token"""
        try:
            payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None