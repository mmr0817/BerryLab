from datetime import datetime
from database import db
import enum

class BookingStatus(enum.Enum):
    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    CANCELLED = 'cancelled'
    COMPLETED = 'completed'

class WeChatUser(db.Model):
    __tablename__ = 'wechat_users'
    
    id = db.Column(db.Integer, primary_key=True)
    openid = db.Column(db.String(100), unique=True, nullable=False, index=True)
    unionid = db.Column(db.String(100), unique=True, nullable=True)
    bandname = db.Column(db.String(100))
    avatar_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关联信息
    phone = db.Column(db.String(20), unique=True, nullable=True)
    real_name = db.Column(db.String(50))
    is_admin = db.Column(db.Boolean, default=False)
    
    # 关联关系
    bookings = db.relationship('Booking', backref='wechat_user', lazy=True)
    membership = db.relationship('Membership', backref='wechat_user', uselist=False)
    transactions = db.relationship('Transaction', backref='wechat_user', lazy=True)

class Membership(db.Model):
    __tablename__ = 'memberships'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('wechat_users.id'), unique=True)
    balance = db.Column(db.Float, default=0.0)
    membership_level = db.Column(db.String(20), default='standard')
    discount_rate = db.Column(db.Float, default=1.0)
    total_spent = db.Column(db.Float, default=0.0)  # 累计消费
    total_recharge = db.Column(db.Float, default=0.0)  # 累计充值
    expiry_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Room(db.Model):
    __tablename__ = 'rooms'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))  # 房间图片
    capacity = db.Column(db.Integer)
    equipment = db.Column(db.Text)  # JSON格式存储设备信息
    price_per_hour = db.Column(db.Float)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)  # 排序字段
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    bookings = db.relationship('Booking', backref='room', lazy=True)

class Booking(db.Model):
    __tablename__ = 'bookings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('wechat_users.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    booking_number = db.Column(db.String(20), unique=True, nullable=False)  # 预约单号
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.Enum(BookingStatus), default=BookingStatus.PENDING)
    total_price = db.Column(db.Float)
    actual_price = db.Column(db.Float)  # 实际支付价格（考虑折扣后）
    notes = db.Column(db.Text)
    contact_name = db.Column(db.String(50))
    contact_phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 索引
    __table_args__ = (
        db.Index('idx_booking_number', 'booking_number'),
        db.Index('idx_user_status', 'user_id', 'status'),
        db.Index('idx_room_time', 'room_id', 'start_time', 'end_time'),
    )

class Transaction(db.Model):
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('wechat_users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(20))  # 'recharge', 'booking', 'refund', 'system'
    transaction_no = db.Column(db.String(50), unique=True)  # 交易单号
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=True)

    status = db.Column(db.String(20), default='pending')  # pending, completed, failed, refunded
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)