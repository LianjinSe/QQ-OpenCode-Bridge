# NapCat `delete_group_file`：删除群文件

功能：删除群文件

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658755e0.md

调用方法：先 `napcat_describe(action="delete_group_file")` 核对本机参数，再 `napcat_call(action="delete_group_file", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

在群文件系统中删除指定的文件

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "file_id": {
      "description": "文件ID",
      "type": "string"
    },
    "bus_id": {
      "minimum": 1,
      "maximum": 4294967295,
      "multipleOf": 1,
      "description": "文件业务ID，默认使用文件列表中的 busid",
      "type": "number"
    },
    "busid": {
      "minimum": 1,
      "maximum": 4294967295,
      "multipleOf": 1,
      "description": "文件业务ID，兼容 busid 字段",
      "type": "number"
    }
  },
  "required": [
    "group_id",
    "file_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "file_id": "file_uuid_123",
  "bus_id": 104
}
```

## 返回数据结构

```json
{
  "description": "删除结果"
}
```

