# NapCat `check_url_safely`：检查URL安全性

功能：检查URL安全性

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/228534361e0.md

调用方法：先 `napcat_describe(action="check_url_safely")` 核对本机参数，再 `napcat_call(action="check_url_safely", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

检查指定URL的安全等级

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "url": {
      "description": "要检查的 URL",
      "type": "string"
    }
  },
  "required": [
    "url"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "url": "https://example.com"
}
```

## 返回数据结构

```json
{
  "type": "object",
  "properties": {
    "level": {
      "description": "安全等级 (1: 安全, 2: 未知, 3: 危险)",
      "type": "number"
    }
  },
  "required": [
    "level"
  ]
}
```

