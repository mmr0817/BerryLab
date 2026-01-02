import re
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, g
import jwt

from wechat_auth import WeChatAuth

def validate_phone(phone):
    """验证手机号格式"""
    pattern = r'^1[3-9]\d{9}$'
    return bool(re.match(pattern, phone))

def format_time_display(dt):
    """格式化时间显示"""
    if not dt:
        return ""
    
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    
    dt_date = dt.date()
    
    if dt_date == today:
        return f"今天 {dt.strftime('%H:%M')}"
    elif dt_date == yesterday:
        return f"昨天 {dt.strftime('%H:%M')}"
    elif dt_date == tomorrow:
        return f"明天 {dt.strftime('%H:%M')}"
    else:
        return dt.strftime('%m月%d日 %H:%M')

def login_required(f):
    """微信小程序登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 从header获取token
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({'code': 401, 'message': '缺少授权信息'}), 401
        
        # 处理Bearer token
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        else:
            token = auth_header
        
        # 验证token
        payload = WeChatAuth.verify_token(token)
        if not payload:
            return jsonify({'code': 401, 'message': '登录已过期，请重新登录'}), 401
        
        # 将用户信息存入g对象
        g.user_id = payload['user_id']
        g.openid = payload['openid']
        
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """管理员权限验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from models import User
        
        user_id = getattr(g, 'user_id', None)
        if not user_id:
            return jsonify({'code': 401, 'message': '请先登录'}), 401
        
        user = User.query.get(user_id)
        if not user or not user.is_admin:
            return jsonify({'code': 403, 'message': '需要管理员权限'}), 403
        
        g.current_user = user
        return f(*args, **kwargs)
    return decorated_function

def make_response(code=200, message='', data=None):
    """统一响应格式"""
    response = {
        'code': code,
        'message': message,
        'data': data
    }
    return jsonify(response), code if code != 200 else 200