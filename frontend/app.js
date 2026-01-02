// app.js
App({
  onLaunch: function () {
    // 检查登录状态
    this.checkLoginStatus();
  },

  globalData: {
    userInfo: null,
    isLoggedIn: false,
    unionid: null,
    apiBaseUrl: 'https://your-server.com/api' // 替换为你的后端地址
  },

  // 检查本地存储的登录状态
  checkLoginStatus: function() {
    const token = wx.getStorageSync('auth_token');
    const userInfo = wx.getStorageSync('userInfo');
    
    if (token && userInfo) {
      this.globalData.userInfo = userInfo;
      this.globalData.isLoggedIn = true;
      this.globalData.unionid = userInfo.unionid;
    }
  },

  // 统一请求方法
  request: function(options) {
    const token = wx.getStorageSync('auth_token');
    
    return new Promise((resolve, reject) => {
      wx.request({
        url: this.globalData.apiBaseUrl + options.url,
        method: options.method || 'GET',
        data: options.data || {},
        header: {
          'Content-Type': 'application/json',
          'Authorization': token ? `Bearer ${token}` : ''
        },
        success: (res) => {
          if (res.statusCode === 200) {
            resolve(res.data);
          } else {
            reject(res.data);
          }
        },
        fail: reject
      });
    });
  }
});