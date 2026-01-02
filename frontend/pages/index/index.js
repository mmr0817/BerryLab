// pages/index/index.js
Page({
  data: {
    isLoggedIn: false,
    userInfo: null,
    canIUseGetUserProfile: false
  },

  onLoad: function() {
    // 检查是否支持新API
    if (wx.getUserProfile) {
      this.setData({
        canIUseGetUserProfile: true
      });
    }
    
    // 从全局获取登录状态
    const app = getApp();
    this.setData({
      isLoggedIn: app.globalData.isLoggedIn,
      userInfo: app.globalData.userInfo
    });
  },

  onShow: function() {
    // 页面显示时刷新数据
    const app = getApp();
    this.setData({
      isLoggedIn: app.globalData.isLoggedIn,
      userInfo: app.globalData.userInfo
    });
  },

  // 通过button获取用户信息（推荐方式）
  onGetUserInfo: function(e) {
    if (e.detail.userInfo) {
      this.loginWithUserInfo(e.detail.userInfo);
    } else {
      wx.showToast({
        title: '需要授权才能使用',
        icon: 'none'
      });
    }
  },

  // 使用getUserProfile API（新方式）
  getUserProfile: function() {
    wx.getUserProfile({
      desc: '用于完善会员资料',
      success: (res) => {
        this.loginWithUserInfo(res.userInfo);
      },
      fail: (err) => {
        console.error('获取用户信息失败:', err);
        wx.showToast({
          title: '获取信息失败',
          icon: 'error'
        });
      }
    });
  },

  // 登录逻辑
  loginWithUserInfo: function(userInfo) {
    const that = this;
    
    wx.showLoading({
      title: '登录中...',
    });

    // 1. 获取code
    wx.login({
      success: (loginRes) => {
        if (loginRes.code) {
          // 2. 发送到后端服务器
          const app = getApp();
          wx.request({
            url: app.globalData.apiBaseUrl + '/login',
            method: 'POST',
            data: {
              code: loginRes.code,
              userInfo: userInfo
            },
            success: (serverRes) => {
              wx.hideLoading();
              
              if (serverRes.data.success) {
                const userData = serverRes.data.data;
                
                // 保存登录状态
                wx.setStorageSync('auth_token', userData.token);
                wx.setStorageSync('userInfo', userData.userInfo);
                
                // 更新全局数据
                app.globalData.isLoggedIn = true;
                app.globalData.userInfo = userData.userInfo;
                app.globalData.unionid = userData.userInfo.unionid;
                
                // 更新页面数据
                that.setData({
                  isLoggedIn: true,
                  userInfo: userData.userInfo
                });
                
                wx.showToast({
                  title: '登录成功',
                  icon: 'success'
                });
                
                // 如果有bandName，提示
                if (userData.userInfo.bandName) {
                  wx.showModal({
                    title: '欢迎回来',
                    content: `您的乐队"${userData.userInfo.bandName}"已加载`,
                    showCancel: false
                  });
                }
              } else {
                wx.showToast({
                  title: serverRes.data.message || '登录失败',
                  icon: 'error'
                });
              }
            },
            fail: (err) => {
              wx.hideLoading();
              wx.showToast({
                title: '网络错误',
                icon: 'error'
              });
            }
          });
        }
      }
    });
  },

  // 检查我的乐队
  checkMyBand: function() {
    const app = getApp();
    if (!app.globalData.userInfo.bandName) {
      wx.showModal({
        title: '提示',
        content: '您还没有设置乐队名称，是否现在设置？',
        success: (res) => {
          if (res.confirm) {
            wx.navigateTo({
              url: '/pages/profile/profile'
            });
          }
        }
      });
    } else {
      wx.showToast({
        title: `正在加载${app.globalData.userInfo.bandName}...`,
        icon: 'none'
      });
      // 这里可以跳转到乐队详情页
    }
  },

  // 分享应用
  shareApp: function() {
    wx.showShareMenu({
      withShareTicket: true
    });
  },

  onShareAppMessage: function() {
    const bandName = this.data.userInfo?.bandName || '我们的乐队';
    return {
      title: `加入${bandName}，一起玩音乐！`,
      path: '/pages/index/index'
    };
  }
});