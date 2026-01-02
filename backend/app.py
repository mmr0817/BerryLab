from flask import Flask, request, jsonify, g
from flask_cors import CORS
from datetime import datetime, timedelta
import random
import string

from config import Config
from database import db, init_db
from models import WeChatUser, Membership, Room, Booking, BookingStatus, Transaction
from wechat_auth import WeChatAuth
from utils import login_required, admin_required, make_response, validate_phone, format_time_display

app = Flask(__name__)
app.config.from_object(Config)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# 初始化数据库
init_db(app)

# 生成预约单号
def generate_booking_number():
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_str = ''.join(random.choices(string.digits, k=4))
    return f'BK{timestamp}{random_str}'

# 1. 微信登录相关接口
@app.route('/api/wx/login', methods=['POST'])
def wechat_login():
    """微信小程序登录"""
    data = request.get_json()
    code = data.get('code')
    
    if not code:
        return make_response(400, '需要授权code')
    
    # 获取openid
    wechat_info = WeChatAuth.get_openid(code)
    if not wechat_info:
        return make_response(401, '微信登录失败')
    
    openid = wechat_info['openid']
    
    # 查找或创建用户
    user = WeChatUser.query.filter_by(openid=openid).first()
    is_new_user = False
    
    if not user:
        # 新用户注册
        user = WeChatUser(
            openid=openid,
            unionid=wechat_info.get('unionid'),
            bandname=data.get('bandname', ''),
        )
        db.session.add(user)
        db.session.flush()  # 获取user_id
        
        # 创建会员账户
        membership = Membership(user_id=user.id)
        db.session.add(membership)
        is_new_user = True
    else:
        # 更新用户信息（如果有新信息）
        user_info = data.get('userInfo')
        if user_info:
            user.bandname = user_info.get('bandname', user.bandname)
            user.last_login = datetime.utcnow()
    
    db.session.commit()
    
    # 生成JWT token
    token = WeChatAuth.generate_token(user.id, openid)
    
    return make_response(200, '登录成功', {
        'token': token,
        'user_info': {
            'user_id': user.id,
            'bandname': user.bandname,
            'is_admin': user.is_admin,
            'is_new_user': is_new_user
        }
    })

@app.route('/api/wx/update-user-info', methods=['POST'])
@login_required
def update_user_info():
    """更新用户信息（手机号、真实姓名等）"""
    data = request.get_json()
    user_id = g.user_id
    
    user = WeChatUser.query.get(user_id)
    if not user:
        return make_response(404, '用户不存在')


# 2. 房间相关接口
@app.route('/api/rooms/list', methods=['GET'])
def get_rooms():
    """获取所有房间列表"""
    rooms = Room.query.filter_by(is_active=True).order_by(Room.sort_order).all()
    
    room_list = []
    for room in rooms:
        room_list.append({
            'id': room.id,
            'name': room.name,
            'description': room.description,
            'image_url': room.image_url,
            'capacity': room.capacity,
            'equipment': room.equipment,
            'price_per_hour': room.price_per_hour
        })
    
    return make_response(200, 'success', {'rooms': room_list})

@app.route('/api/rooms/available-times', methods=['GET'])
def get_available_times():
    """获取指定日期可预约时间段"""
    date_str = request.args.get('date')
    room_id = request.args.get('room_id', type=int)
    
    if not date_str or not room_id:
        return make_response(400, '需要日期和房间ID参数')
    
    try:
        query_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return make_response(400, '日期格式错误')
    
    # 获取房间信息
    room = Room.query.get(room_id)
    if not room or not room.is_active:
        return make_response(404, '房间不存在')
    
    # 查询该房间当天的预约
    start_of_day = datetime.combine(query_date, datetime.min.time())
    end_of_day = datetime.combine(query_date, datetime.max.time())
    
    bookings = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING]),
        Booking.start_time >= start_of_day,
        Booking.end_time <= end_of_day
    ).all()
    
    # 生成所有时间段（每小时为单位）
    OPENING_HOUR = app.config['OPENING_HOUR']
    CLOSING_HOUR = app.config['CLOSING_HOUR']
    
    time_slots = []
    current_time = datetime.combine(query_date, datetime.min.time().replace(hour=OPENING_HOUR))
    
    while current_time.hour < CLOSING_HOUR:
        slot_end = current_time + timedelta(hours=1)
        
        # 检查该时间段是否可用
        is_available = True
        for booking in bookings:
            if not (slot_end <= booking.start_time or current_time >= booking.end_time):
                is_available = False
                break
        
        time_slots.append({
            'start_time': current_time.strftime('%H:%M'),
            'end_time': slot_end.strftime('%H:%M'),
            'is_available': is_available,
            'display': f"{current_time.strftime('%H:%M')}-{slot_end.strftime('%H:%M')}"
        })
        
        current_time = slot_end
    
    return make_response(200, 'success', {
        'room': {
            'id': room.id,
            'name': room.name,
            'price_per_hour': room.price_per_hour
        },
        'date': date_str,
        'time_slots': time_slots
    })

# 3. 预约相关接口
@app.route('/api/bookings/create', methods=['POST'])
@login_required
def create_booking():
    """创建预约"""
    data = request.get_json()
    user_id = g.user_id
    
    required_fields = ['room_id', 'date', 'start_time', 'end_time', 'contact_name', 'contact_phone']
    if not all(field in data for field in required_fields):
        return make_response(400, '缺少必要信息')
    
    # 验证手机号
    if not validate_phone(data['contact_phone']):
        return make_response(400, '手机号格式不正确')
    
    # 构建完整时间
    try:
        start_datetime = datetime.strptime(f"{data['date']} {data['start_time']}", '%Y-%m-%d %H:%M')
        end_datetime = datetime.strptime(f"{data['date']} {data['end_time']}", '%Y-%m-%d %H:%M')
    except ValueError:
        return make_response(400, '时间格式错误')
    
    # 验证时间
    if start_datetime >= end_datetime:
        return make_response(400, '结束时间必须晚于开始时间')
    
    if start_datetime < datetime.now():
        return make_response(400, '不能预约过去的时间')
    
    duration = (end_datetime - start_datetime).total_seconds() / 3600
    if duration > app.config['MAX_BOOKING_HOURS']:
        return make_response(400, f'单次预约不能超过{app.config["MAX_BOOKING_HOURS"]}小时')
    
    # 检查营业时间
    if start_datetime.hour < app.config['OPENING_HOUR'] or end_datetime.hour > app.config['CLOSING_HOUR']:
        return make_response(400, f'营业时间为{app.config["OPENING_HOUR"]}:00-{app.config["CLOSING_HOUR"]}:00')
    
    # 检查时间冲突
    room_id = data['room_id']
    conflicting_booking = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING]),
        Booking.start_time < end_datetime,
        Booking.end_time > start_datetime
    ).first()
    
    if conflicting_booking:
        return make_response(400, '该时间段已被预约')
    
    # 获取房间和用户信息
    room = Room.query.get(room_id)
    if not room:
        return make_response(404, '房间不存在')
    
    user = WeChatUser.query.get(user_id)
    membership = Membership.query.filter_by(user_id=user_id).first()
    
    # 计算价格
    total_price = room.price_per_hour * duration
    actual_price = total_price * (membership.discount_rate if membership else 1.0)
    
    # 检查余额
    if (membership.balance or 0) < actual_price:
        return make_response(400, '余额不足，请先充值', {
            'required': actual_price,
            'current_balance': membership.balance
        })
    
    # 扣款
    membership.balance -= actual_price
    membership.total_spent += actual_price
    
    # 创建预约
    booking = Booking(
        user_id=user_id,
        room_id=room_id,
        booking_number=generate_booking_number(),
        start_time=start_datetime,
        end_time=end_datetime,
        total_price=total_price,
        actual_price=actual_price,
        contact_name=data['contact_name'],
        contact_phone=data['contact_phone'],
        notes=data.get('notes', ''),
        status=BookingStatus.CONFIRMED
    )
    
    # 创建交易记录
    transaction = Transaction(
        user_id=user_id,
        amount=-actual_price,
        transaction_type='booking',
        transaction_no=generate_transaction_no(),
        booking_id=booking.id,
        payment_method='balance',
        description=f'预约{room.name}',
        status='completed'
    )
    
    db.session.add(booking)
    db.session.add(transaction)
    db.session.commit()
    
    return make_response(200, '预约成功', {
        'booking_id': booking.id,
        'booking_number': booking.booking_number,
        'room_name': room.name,
        'start_time': booking.start_time.isoformat(),
        'end_time': booking.end_time.isoformat(),
        'total_price': total_price,
        'actual_price': actual_price,
        'balance': membership.balance,
        'contact_name': booking.contact_name,
        'contact_phone': booking.contact_phone
    })

@app.route('/api/bookings/my', methods=['GET'])
@login_required
def get_my_bookings():
    """获取我的预约列表"""
    user_id = g.user_id
    status = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    
    query = Booking.query.filter_by(user_id=user_id)
    
    if status:
        query = query.filter_by(status=BookingStatus(status))
    
    bookings = query.order_by(Booking.start_time.desc())\
        .paginate(page=page, per_page=limit, error_out=False)
    
    booking_list = []
    for booking in bookings.items:
        booking_list.append({
            'id': booking.id,
            'booking_number': booking.booking_number,
            'room_name': booking.room.name,
            'room_image': booking.room.image_url,
            'start_time': booking.start_time.isoformat(),
            'end_time': booking.end_time.isoformat(),
            'start_display': format_time_display(booking.start_time),
            'end_display': format_time_display(booking.end_time),
            'status': booking.status.value,
            'total_price': booking.total_price,
            'actual_price': booking.actual_price,
            'contact_name': booking.contact_name,
            'contact_phone': booking.contact_phone,
            'notes': booking.notes,
            'created_at': booking.created_at.isoformat(),
            'can_cancel': booking.status == BookingStatus.CONFIRMED and 
                         (booking.start_time - datetime.now()).total_seconds() > 7200  # 2小时内不可取消
        })
    
    return make_response(200, 'success', {
        'bookings': booking_list,
        'total': bookings.total,
        'page': bookings.page,
        'pages': bookings.pages,
        'has_next': bookings.has_next,
        'has_prev': bookings.has_prev
    })

@app.route('/api/bookings/<int:booking_id>/detail', methods=['GET'])
@login_required
def get_booking_detail(booking_id):
    """获取预约详情"""
    user_id = g.user_id
    
    booking = Booking.query.get_or_404(booking_id)
    
    # 检查权限
    if booking.user_id != user_id and not booking.wechat_user.is_admin:
        return make_response(403, '无权查看')
    
    return make_response(200, 'success', {
        'id': booking.id,
        'booking_number': booking.booking_number,
        'room': {
            'id': booking.room.id,
            'name': booking.room.name,
            'image_url': booking.room.image_url,
            'description': booking.room.description,
            'equipment': booking.room.equipment
        },
        'start_time': booking.start_time.isoformat(),
        'end_time': booking.end_time.isoformat(),
        'status': booking.status.value,
        'total_price': booking.total_price,
        'actual_price': booking.actual_price,
        'contact_name': booking.contact_name,
        'contact_phone': booking.contact_phone,
        'notes': booking.notes,
        'created_at': booking.created_at.isoformat(),
        'can_cancel': booking.status == BookingStatus.CONFIRMED and 
                     (booking.start_time - datetime.now()).total_seconds() > 7200
    })

@app.route('/api/bookings/<int:booking_id>/cancel', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    """取消预约"""
    user_id = g.user_id
    
    booking = Booking.query.get_or_404(booking_id)
    
    # 检查权限
    if booking.user_id != user_id:
        return make_response(403, '无权操作')
    
    # 检查状态
    if booking.status != BookingStatus.CONFIRMED:
        return make_response(400, '只能取消已确认的预约')
    
    # 检查取消时间
    time_to_start = (booking.start_time - datetime.now()).total_seconds() / 3600
    if time_to_start <= 2:
        return make_response(400, '距离开始时间不足2小时，不可取消')
    
    # 计算退款金额
    if time_to_start > 24:
        refund_rate = 0.8  # 24小时前取消，退款80%
    else:
        refund_rate = 0.5  # 2-24小时取消，退款50%
    
    refund_amount = booking.actual_price * refund_rate
    
    # 更新预约状态
    booking.status = BookingStatus.CANCELLED
    
    # 退款到余额
    membership = Membership.query.filter_by(user_id=user_id).first()
    if membership and refund_amount > 0:
        membership.balance += refund_amount
        
        # 创建退款交易记录
        refund_transaction = Transaction(
            user_id=user_id,
            amount=refund_amount,
            transaction_type='refund',
            transaction_no=generate_transaction_no(),
            booking_id=booking.id,
            payment_method='balance',
            description=f'取消预约退款',
            status='completed'
        )
        db.session.add(refund_transaction)
    
    db.session.commit()
    
    return make_response(200, '取消成功', {
        'refund_amount': refund_amount,
        'new_balance': membership.balance if membership else 0
    })

# 4. 会员余额相关接口
@app.route('/api/membership/balance', methods=['GET'])
@login_required
def get_my_balance():
    """获取我的余额信息"""
    user_id = g.user_id
    
    membership = Membership.query.filter_by(user_id=user_id).first()
    if not membership:
        return make_response(404, '会员信息不存在')
    
    user = WeChatUser.query.get(user_id)
    
    return make_response(200, 'success', {
        'balance': membership.balance,
        'membership_level': membership.membership_level,
        'discount_rate': membership.discount_rate,
        'total_spent': membership.total_spent,
        'total_recharge': membership.total_recharge,
        'phone': user.phone,
        'real_name': user.real_name
    })

@app.route('/api/membership/recharge', methods=['POST'])
@login_required
def recharge():
    """充值余额（模拟）"""
    data = request.get_json()
    user_id = g.user_id
    
    amount = data.get('amount', 0)
    payment_method = data.get('payment_method', 'wechat')
    
    if amount <= 0:
        return make_response(400, '充值金额必须大于0')
    
    # 生产环境这里应该调用微信支付接口
    # 这里模拟支付成功
    
    membership = Membership.query.filter_by(user_id=user_id).first()
    if not membership:
        return make_response(404, '会员信息不存在')
    
    # 更新余额
    membership.balance += amount
    membership.total_recharge += amount
    
    # 创建交易记录
    transaction = Transaction(
        user_id=user_id,
        amount=amount,
        transaction_type='recharge',
        transaction_no=generate_transaction_no(),
        payment_method=payment_method,
        description='余额充值',
        status='completed'
    )
    
    db.session.add(transaction)
    db.session.commit()
    
    return make_response(200, '充值成功', {
        'new_balance': membership.balance,
        'transaction_no': transaction.transaction_no
    })

@app.route('/api/transactions/history', methods=['GET'])
@login_required
def get_transaction_history():
    """获取交易记录"""
    user_id = g.user_id
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 10, type=int)
    
    transactions = Transaction.query.filter_by(user_id=user_id)\
        .order_by(Transaction.created_at.desc())\
        .paginate(page=page, per_page=limit, error_out=False)
    
    transaction_list = []
    for trans in transactions.items:
        transaction_list.append({
            'id': trans.id,
            'transaction_no': trans.transaction_no,
            'amount': trans.amount,
            'type': trans.transaction_type,
            'payment_method': trans.payment_method,
            'description': trans.description,
            'status': trans.status,
            'created_at': trans.created_at.isoformat(),
            'created_display': format_time_display(trans.created_at)
        })
    
    return make_response(200, 'success', {
        'transactions': transaction_list,
        'total': transactions.total,
        'page': transactions.page,
        'pages': transactions.pages
    })

# 5. 首页数据接口
@app.route('/api/home/data', methods=['GET'])
@login_required
def get_home_data():
    """获取首页数据"""
    user_id = g.user_id
    
    # 获取用户信息
    user = WeChatUser.query.get(user_id)
    membership = Membership.query.filter_by(user_id=user_id).first()
    
    # 获取最近的预约
    recent_bookings = Booking.query.filter_by(user_id=user_id)\
        .order_by(Booking.start_time.desc())\
        .limit(3)\
        .all()
    
    # 获取公告/通知（这里简单实现）
    notices = [
        {'id': 1, 'title': '系统维护通知', 'content': '每周一凌晨2-4点进行系统维护', 'created_at': '2024-01-10'},
        {'id': 2, 'title': '春节营业时间调整', 'content': '春节期间营业时间调整为10:00-20:00', 'created_at': '2024-01-08'},
    ]
    
    booking_list = []
    for booking in recent_bookings:
        booking_list.append({
            'id': booking.id,
            'room_name': booking.room.name,
            'start_time': booking.start_time.strftime('%m-%d %H:%M'),
            'status': booking.status.value,
            'status_text': {
                'confirmed': '已确认',
                'pending': '待确认',
                'cancelled': '已取消',
                'completed': '已完成'
            }.get(booking.status.value, booking.status.value)
        })
    
    return make_response(200, 'success', {
        'user': {
            'bandname': user.bandname,
            'avatar_url': user.avatar_url,
            'balance': membership.balance if membership else 0
        },
        'recent_bookings': booking_list,
        'notices': notices,
        'quick_actions': [
            {'name': '立即预约', 'icon': 'booking', 'path': '/pages/booking/index'},
            {'name': '我的预约', 'icon': 'my-bookings', 'path': '/pages/my/bookings'},
            {'name': '余额充值', 'icon': 'recharge', 'path': '/pages/membership/recharge'},
            {'name': '联系客服', 'icon': 'service', 'path': '/pages/service/index'}
        ]
    })

# 6. 管理接口
@app.route('/api/admin/bookings/list', methods=['GET'])
@admin_required
def admin_get_bookings():
    """管理员获取预约列表"""
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    status = request.args.get('status')
    room_id = request.args.get('room_id', type=int)
    date = request.args.get('date')
    phone = request.args.get('phone')
    
    query = Booking.query
    
    # 过滤条件
    if status:
        query = query.filter_by(status=BookingStatus(status))
    if room_id:
        query = query.filter_by(room_id=room_id)
    if date:
        try:
            query_date = datetime.strptime(date, '%Y-%m-%d')
            start_of_day = datetime.combine(query_date, datetime.min.time())
            end_of_day = datetime.combine(query_date, datetime.max.time())
            query = query.filter(Booking.start_time >= start_of_day, Booking.start_time <= end_of_day)
        except ValueError:
            pass
    if phone:
        query = query.filter(Booking.contact_phone.like(f'%{phone}%'))
    
    bookings = query.order_by(Booking.start_time.desc())\
        .paginate(page=page, per_page=limit, error_out=False)
    
    booking_list = []
    for booking in bookings.items:
        booking_list.append({
            'id': booking.id,
            'booking_number': booking.booking_number,
            'user': {
                'id': booking.wechat_user.id,
                'bandname': booking.wechat_user.bandname,
                'phone': booking.wechat_user.phone
            },
            'room': {
                'id': booking.room.id,
                'name': booking.room.name
            },
            'start_time': booking.start_time.isoformat(),
            'end_time': booking.end_time.isoformat(),
            'duration': (booking.end_time - booking.start_time).total_seconds() / 3600,
            'status': booking.status.value,
            'status_text': {
                'confirmed': '已确认',
                'pending': '待确认',
                'cancelled': '已取消',
                'completed': '已完成'
            }.get(booking.status.value, booking.status.value),
            'total_price': booking.total_price,
            'actual_price': booking.actual_price,
            'contact_name': booking.contact_name,
            'contact_phone': booking.contact_phone,
            'notes': booking.notes,
            'created_at': booking.created_at.isoformat()
        })
    
    return make_response(200, 'success', {
        'bookings': booking_list,
        'total': bookings.total,
        'page': bookings.page,
        'pages': bookings.pages
    })

@app.route('/api/admin/bookings/<int:booking_id>/update', methods=['POST'])
@admin_required
def admin_update_booking(booking_id):
    """管理员更新预约状态"""
    data = request.get_json()
    new_status = data.get('status')
    notes = data.get('notes')
    
    if not new_status:
        return make_response(400, '需要状态参数')
    
    booking = Booking.query.get_or_404(booking_id)
    
    try:
        booking.status = BookingStatus(new_status)
        if notes is not None:
            booking.notes = notes
        
        db.session.commit()
        
        return make_response(200, '更新成功', {
            'id': booking.id,
            'status': booking.status.value
        })
    except ValueError:
        return make_response(400, '无效的状态值')

@app.route('/api/admin/bookings/<int:booking_id>/refund', methods=['POST'])
@admin_required
def admin_manual_refund(booking_id):
    """管理员手动退款"""
    data = request.get_json()
    refund_amount = data.get('amount')
    reason = data.get('reason', '')
    
    if not refund_amount or refund_amount <= 0:
        return make_response(400, '退款金额必须大于0')
    
    booking = Booking.query.get_or_404(booking_id)
    
    # 检查预约状态
    if booking.status != BookingStatus.CANCELLED:
        return make_response(400, '只能为已取消的预约退款')
    
    # 检查是否已退款
    existing_refund = Transaction.query.filter_by(
        booking_id=booking_id,
        transaction_type='refund'
    ).first()
    
    if existing_refund:
        return make_response(400, '该预约已退款')
    
    # 退款到余额
    membership = Membership.query.filter_by(user_id=booking.user_id).first()
    if not membership:
        return make_response(404, '用户会员信息不存在')
    
    membership.balance += refund_amount
    
    # 创建退款交易记录
    transaction = Transaction(
        user_id=booking.user_id,
        amount=refund_amount,
        transaction_type='refund',
        transaction_no=generate_transaction_no(),
        booking_id=booking.id,
        payment_method='balance',
        description=f'管理员手动退款: {reason}',
        status='completed'
    )
    
    db.session.add(transaction)
    db.session.commit()
    
    return make_response(200, '退款成功', {
        'booking_id': booking.id,
        'refund_amount': refund_amount,
        'new_balance': membership.balance
    })

@app.route('/api/admin/rooms', methods=['GET'])
@admin_required
def admin_get_rooms():
    """管理员获取所有房间"""
    rooms = Room.query.order_by(Room.sort_order, Room.id).all()
    
    room_list = []
    for room in rooms:
        room_list.append({
            'id': room.id,
            'name': room.name,
            'description': room.description,
            'image_url': room.image_url,
            'capacity': room.capacity,
            'equipment': room.equipment,
            'price_per_hour': room.price_per_hour,
            'is_active': room.is_active,
            'sort_order': room.sort_order,
            'created_at': room.created_at.isoformat(),
            'booking_count': Booking.query.filter_by(room_id=room.id).count()
        })
    
    return make_response(200, 'success', {'rooms': room_list})

@app.route('/api/admin/rooms/create', methods=['POST'])
@admin_required
def admin_create_room():
    """管理员创建房间"""
    data = request.get_json()
    
    required_fields = ['name', 'price_per_hour']
    if not all(field in data for field in required_fields):
        return make_response(400, '缺少必要信息')
    
    new_room = Room(
        name=data['name'],
        description=data.get('description', ''),
        image_url=data.get('image_url', ''),
        capacity=data.get('capacity', 5),
        equipment=data.get('equipment', ''),
        price_per_hour=data['price_per_hour'],
        is_active=data.get('is_active', True),
        sort_order=data.get('sort_order', 0)
    )
    
    db.session.add(new_room)
    db.session.commit()
    
    return make_response(200, '创建成功', {
        'id': new_room.id,
        'name': new_room.name
    })

@app.route('/api/admin/rooms/<int:room_id>/update', methods=['POST'])
@admin_required
def admin_update_room(room_id):
    """管理员更新房间信息"""
    data = request.get_json()
    
    room = Room.query.get_or_404(room_id)
    
    # 更新字段
    update_fields = ['name', 'description', 'image_url', 'capacity', 'equipment', 
                     'price_per_hour', 'is_active', 'sort_order']
    
    for field in update_fields:
        if field in data:
            setattr(room, field, data[field])
    
    db.session.commit()
    
    return make_response(200, '更新成功', {
        'id': room.id,
        'name': room.name
    })

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_get_users():
    """管理员获取用户列表"""
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    phone = request.args.get('phone')
    bandname = request.args.get('bandname')
    
    query = WeChatUser.query
    
    if phone:
        query = query.filter(WeChatUser.phone.like(f'%{phone}%'))
    if bandname:
        query = query.filter(WeChatUser.bandname.like(f'%{nbandname}%'))
    
    users = query.order_by(WeChatUser.created_at.desc())\
        .paginate(page=page, per_page=limit, error_out=False)
    
    user_list = []
    for user in users.items:
        membership = Membership.query.filter_by(user_id=user.id).first()
        booking_count = Booking.query.filter_by(user_id=user.id).count()
        
        user_list.append({
            'id': user.id,
            'openid': user.openid[:8] + '...' if user.openid else '',
            'bandname': user.bandname,
            'avatar_url': user.avatar_url,
            'phone': user.phone,
            'real_name': user.real_name,
            'is_admin': user.is_admin,
            'created_at': user.created_at.isoformat(),
            'last_login': user.last_login.isoformat() if user.last_login else None,
            'membership': {
                'balance': membership.balance if membership else 0,
                'membership_level': membership.membership_level if membership else 'standard',
                'total_spent': membership.total_spent if membership else 0,
                'total_recharge': membership.total_recharge if membership else 0
            },
            'booking_count': booking_count
        })
    
    return make_response(200, 'success', {
        'users': user_list,
        'total': users.total,
        'page': users.page,
        'pages': users.pages
    })

@app.route('/api/admin/users/<int:user_id>/update', methods=['POST'])
@admin_required
def admin_update_user(user_id):
    """管理员更新用户信息"""
    data = request.get_json()
    
    user = WeChatUser.query.get_or_404(user_id)
    
    # 更新字段
    if 'phone' in data:
        user.phone = data['phone']
    if 'real_name' in data:
        user.real_name = data['real_name']
    if 'is_admin' in data and g.current_user.is_admin:  # 只有超级管理员可以设置管理员
        user.is_admin = data['is_admin']
    
    # 更新会员信息
    if 'membership_level' in data or 'balance_adjustment' in data:
        membership = Membership.query.filter_by(user_id=user_id).first()
        if membership:
            if 'membership_level' in data:
                membership.membership_level = data['membership_level']
                # 根据会员等级设置折扣率
                discount_map = {
                    'standard': 1.0,
                    'silver': 0.9,
                    'gold': 0.8,
                    'platinum': 0.7
                }
                membership.discount_rate = discount_map.get(data['membership_level'], 1.0)
            
            if 'balance_adjustment' in data:
                adjustment = data['balance_adjustment']
                if isinstance(adjustment, (int, float)):
                    membership.balance += adjustment
                    
                    # 创建调整记录
                    transaction = Transaction(
                        user_id=user_id,
                        amount=adjustment,
                        transaction_type='system',
                        transaction_no=generate_transaction_no(),
                        payment_method='system',
                        description=data.get('adjustment_reason', '管理员调整余额'),
                        status='completed'
                    )
                    db.session.add(transaction)
    
    db.session.commit()
    
    return make_response(200, '更新成功', {
        'id': user.id,
        'bandname': user.bandname
    })

@app.route('/api/admin/dashboard', methods=['GET'])
@admin_required
def admin_dashboard():
    """管理员仪表板数据"""
    today = datetime.now().date()
    
    # 今日数据
    start_of_today = datetime.combine(today, datetime.min.time())
    end_of_today = datetime.combine(today, datetime.max.time())
    
    today_bookings = Booking.query.filter(
        Booking.created_at >= start_of_today,
        Booking.created_at <= end_of_today
    ).count()
    
    today_income = db.session.query(db.func.sum(Booking.actual_price)).filter(
        Booking.created_at >= start_of_today,
        Booking.created_at <= end_of_today,
        Booking.status == BookingStatus.CONFIRMED
    ).scalar() or 0
    
    # 本月数据
    start_of_month = datetime(today.year, today.month, 1)
    next_month = today.month + 1 if today.month < 12 else 1
    next_year = today.year if today.month < 12 else today.year + 1
    start_of_next_month = datetime(next_year, next_month, 1)
    
    month_bookings = Booking.query.filter(
        Booking.created_at >= start_of_month,
        Booking.created_at < start_of_next_month
    ).count()
    
    month_income = db.session.query(db.func.sum(Booking.actual_price)).filter(
        Booking.created_at >= start_of_month,
        Booking.created_at < start_of_next_month,
        Booking.status == BookingStatus.CONFIRMED
    ).scalar() or 0
    
    # 总数据
    total_users = WeChatUser.query.count()
    total_bookings = Booking.query.count()
    total_income = db.session.query(db.func.sum(Booking.actual_price)).filter(
        Booking.status == BookingStatus.CONFIRMED
    ).scalar() or 0
    
    # 今日预约明细
    today_booking_details = Booking.query.filter(
        Booking.start_time >= start_of_today,
        Booking.start_time <= end_of_today,
        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING])
    ).order_by(Booking.start_time).limit(10).all()
    
    booking_details = []
    for booking in today_booking_details:
        booking_details.append({
            'id': booking.id,
            'room_name': booking.room.name,
            'user_bandname': booking.wechat_user.bandname,
            'start_time': booking.start_time.strftime('%H:%M'),
            'end_time': booking.end_time.strftime('%H:%M'),
            'status': booking.status.value
        })
    
    # 房间使用情况
    room_stats = []
    rooms = Room.query.filter_by(is_active=True).all()
    for room in rooms:
        today_room_bookings = Booking.query.filter(
            Booking.room_id == room.id,
            Booking.start_time >= start_of_today,
            Booking.start_time <= end_of_today,
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING])
        ).count()
        
        room_stats.append({
            'id': room.id,
            'name': room.name,
            'today_bookings': today_room_bookings,
            'total_bookings': Booking.query.filter_by(room_id=room.id).count()
        })
    
    return make_response(200, 'success', {
        'summary': {
            'today': {
                'bookings': today_bookings,
                'income': float(today_income)
            },
            'month': {
                'bookings': month_bookings,
                'income': float(month_income)
            },
            'total': {
                'users': total_users,
                'bookings': total_bookings,
                'income': float(total_income)
            }
        },
        'today_bookings': booking_details,
        'room_stats': room_stats
    })

@app.route('/api/admin/transactions', methods=['GET'])
@admin_required
def admin_get_transactions():
    """管理员获取交易记录"""
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    user_id = request.args.get('user_id', type=int)
    transaction_type = request.args.get('type')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = Transaction.query
    
    if user_id:
        query = query.filter_by(user_id=user_id)
    if transaction_type:
        query = query.filter_by(transaction_type=transaction_type)
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Transaction.created_at >= start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Transaction.created_at <= end)
        except ValueError:
            pass
    
    transactions = query.order_by(Transaction.created_at.desc())\
        .paginate(page=page, per_page=limit, error_out=False)
    
    transaction_list = []
    for trans in transactions.items:
        transaction_list.append({
            'id': trans.id,
            'transaction_no': trans.transaction_no,
            'user': {
                'id': trans.wechat_user.id,
                'bandname': trans.wechat_user.bandname,
                'phone': trans.wechat_user.phone
            },
            'amount': trans.amount,
            'type': trans.transaction_type,
            'type_text': {
                'recharge': '充值',
                'booking': '预约扣款',
                'refund': '退款',
                'system': '系统调整'
            }.get(trans.transaction_type, trans.transaction_type),
            'payment_method': trans.payment_method,
            'description': trans.description,
            'status': trans.status,
            'booking_id': trans.booking_id,
            'created_at': trans.created_at.isoformat()
        })
    
    return make_response(200, 'success', {
        'transactions': transaction_list,
        'total': transactions.total,
        'page': transactions.page,
        'pages': transactions.pages
    })

# 7. 系统接口
@app.route('/api/system/config', methods=['GET'])
def get_system_config():
    """获取系统配置（小程序前端使用）"""
    return make_response(200, 'success', {
        'business_hours': {
            'open': app.config['OPENING_HOUR'],
            'close': app.config['CLOSING_HOUR']
        },
        'max_booking_hours': app.config['MAX_BOOKING_HOURS'],
        'default_price': app.config['PRICE_PER_HOUR'],
        'cancel_policy': {
            'before_24h_refund_rate': 0.8,
            'before_2h_refund_rate': 0.5,
            'within_2h_no_refund': True
        }
    })

@app.route('/api/system/health', methods=['GET'])
def system_health():
    """系统健康检查"""
    try:
        # 检查数据库连接
        db.session.execute('SELECT 1')
        db_status = 'healthy'
    except Exception as e:
        db_status = f'error: {str(e)}'
    
    return make_response(200, '系统运行正常', {
        'status': 'running',
        'timestamp': datetime.now().isoformat(),
        'database': db_status,
        'version': '1.0.0'
    })

# 8. 错误处理
@app.errorhandler(404)
def not_found_error(error):
    return make_response(404, '资源不存在')

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f'服务器内部错误: {str(error)}')
    return make_response(500, '服务器内部错误')

@app.errorhandler(400)
def bad_request_error(error):
    return make_response(400, '请求参数错误')

# 启动应用
if __name__ == '__main__':
    # 确保数据库表已创建
    with app.app_context():
        db.create_all()
    
        # 创建默认管理员（如果不存在）
        admin = WeChatUser.query.filter_by(is_admin=True).first()
        if not admin:
            # 这里应该从环境变量或配置文件读取管理员信息
            # 生产环境请务必修改
            admin_user = WeChatUser(
                openid='admin_default',
                bandname='管理员',
                phone='13800138000',
                real_name='系统管理员',
                is_admin=True
            )
            db.session.add(admin_user)
            db.session.flush()
            
            admin_membership = Membership(
                user_id=admin_user.id,
                balance=0.0,
                membership_level='platinum',
                discount_rate=0.7
            )
            db.session.add(admin_membership)
            db.session.commit()
            print('已创建默认管理员账户')
    
    app.run(host='0.0.0.0', port=5000, debug=True)