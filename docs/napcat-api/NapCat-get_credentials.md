# NapCat `get_credentials`：获取登录凭证

功能：获取登录凭证

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226657054e0.md

调用方法：先 `napcat_describe(action="get_credentials")` 核对本机参数，再 `napcat_call(action="get_credentials", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取登录凭证

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "domain": {
      "description": "需要获取 cookies 的域名",
      "type": "string"
    }
  },
  "required": [
    "domain"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "domain": "qun.qq.com"
}
```

## 返回数据结构

```json
{
  "type": "object",
  "properties": {
    "cookies": {
      "description": "Cookies",
      "type": "string"
    },
    "token": {
      "description": "CSRF Token",
      "type": "number"
    }
  },
  "required": [
    "cookies",
    "token"
  ]
}
```


凭据和原始包返回值通过本地不透明引用处理，不把 Cookie、密钥或票据写进聊天、文档或个人记忆。
