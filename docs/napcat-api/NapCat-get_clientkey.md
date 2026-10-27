# NapCat `get_clientkey`：获取ClientKey

功能：获取ClientKey

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/250286915e0.md

调用方法：先 `napcat_describe(action="get_clientkey")` 核对本机参数，再 `napcat_call(action="get_clientkey", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取当前登录帐号的ClientKey

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {}
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{}
```

## 返回数据结构

```json
{
  "description": "获取ClientKey结果",
  "type": "object",
  "properties": {
    "clientkey": {
      "description": "客户端Key",
      "type": "string"
    }
  }
}
```


凭据和原始包返回值通过本地不透明引用处理，不把 Cookie、密钥或票据写进聊天、文档或个人记忆。
