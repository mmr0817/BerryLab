import os

class Config:
    # 基础配置
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'wechat-rehearsal-secret-key'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///wechat_rehearsal.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # 微信小程序配置
    WECHAT_APPID = os.environ.get('WECHAT_APPID', 'your-wechat-appid')
    WECHAT_SECRET = os.environ.get('WECHAT_SECRET', 'your-wechat-app-secret')
    
    # JWT配置
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'jwt-secret-key-change-me'
    JWT_ACCESS_TOKEN_EXPIRES = 3600 * 24 * 7  # 7天有效期
    JWT_TOKEN_LOCATION = ['headers', 'cookies']
    
    
    # Redis配置（可选，用于缓存）
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    
    # 缓存配置
    CACHE_TYPE = 'simple'  # 生产环境建议使用 'redis'
    CACHE_DEFAULT_TIMEOUT = 300