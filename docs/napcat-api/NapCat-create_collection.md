# NapCat `create_collection`：创建收藏

功能：创建收藏

分类：扩展接口

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226659178e0.md

调用方法：先 `napcat_describe(action="create_collection")` 核对本机参数，再 `napcat_call(action="create_collection", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "rawData": {
      "description": "原始数据",
      "type": "string"
    },
    "brief": {
      "description": "简要描述",
      "type": "string"
    }
  },
  "required": [
    "rawData",
    "brief"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "rawData": "收藏内容",
  "brief": "收藏标题"
}
```

## 返回数据结构

```json
{
  "description": "创建结果"
}
```

