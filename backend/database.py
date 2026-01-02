from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_db(app):
    db.init_app(app)
    with app.app_context():
        # 导入所有模型
        from models import WeChatUser, Membership, Room, Booking, Transaction
        db.create_all()
        
        # 创建默认房间（如果不存在）
        if Room.query.count() == 0:
            import json
            default_rooms = [
                Room(
                    name='小型排练室',
                    description='适合1-5人乐队排练，设备齐全',
                    image_url='https://example.com/room1.jpg',
                    capacity=5,
                    equipment=json.dumps(['架子鼓', '电吉他', '贝斯', '键盘', '专业音箱']),
                    price_per_hour=80,
                    is_active=True,
                    sort_order=1
                ),
                Room(
                    name='中型排练室', 
                    description='适合5-10人乐队，空间宽敞',
                    image_url='https://example.com/room2.jpg',
                    capacity=10,
                    equipment=json.dumps(['专业录音设备', '多轨调音台', '监听音箱', '全套乐器']),
                    price_per_hour=120,
                    is_active=True,
                    sort_order=2
                ),
                Room(
                    name='大型排练室',
                    description='适合10-15人大型乐队或录音',
                    image_url='https://example.com/room3.jpg',
                    capacity=15,
                    equipment=json.dumps(['录音棚设备', '专业隔音', '多套乐器', '休息区']),
                    price_per_hour=180,
                    is_active=True,
                    sort_order=3
                )
            ]
            db.session.add_all(default_rooms)
            db.session.commit()
            print('已创建默认房间数据')