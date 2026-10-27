# NapCat `get_unidirectional_friend_list`：获取单向好友列表

功能：获取单向好友列表

分类：用户扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/266151878e0.md

调用方法：先 `napcat_describe(action="get_unidirectional_friend_list")` 核对本机参数，再 `napcat_call(action="get_unidirectional_friend_list", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

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
  "description": "单向好友列表",
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "uin": {
        "description": "QQ号",
        "type": "number"
      },
      "uid": {
        "description": "用户UID",
        "type": "string"
      },
      "nick_name": {
        "description": "昵称",
        "type": "string"
      },
      "age": {
        "description": "年龄",
        "type": "number"
      },
      "source": {
        "description": "来源",
        "type": "string"
      }
    },
    "required": [
      "uin",
      "uid",
      "nick_name",
      "age",
      "source"
    ]
  }
}
```

