# NapCat `get_doubt_friends_add_request`：获取可疑好友申请

功能：获取可疑好友申请

分类：系统接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/289565516e0.md

调用方法：先 `napcat_describe(action="get_doubt_friends_add_request")` 核对本机参数，再 `napcat_call(action="get_doubt_friends_add_request", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取系统的可疑好友申请列表

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "count": {
      "default": 50,
      "description": "获取数量",
      "type": "number"
    }
  },
  "required": [
    "count"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "count": 10
}
```

## 返回数据结构

```json
{
  "description": "可疑好友申请列表"
}
```

