# NapCat `can_send_record`：是否可以发送语音

功能：是否可以发送语音

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226657080e0.md

调用方法：先 `napcat_describe(action="can_send_record")` 核对本机参数，再 `napcat_call(action="can_send_record", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

检查是否可以发送语音

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
  "type": "object",
  "properties": {
    "yes": {
      "description": "是否可以发送",
      "type": "boolean"
    }
  },
  "required": [
    "yes"
  ]
}
```

