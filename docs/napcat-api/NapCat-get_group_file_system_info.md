# NapCat `get_group_file_system_info`：获取群文件系统信息

功能：获取群文件系统信息

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658789e0.md

调用方法：先 `napcat_describe(action="get_group_file_system_info")` 核对本机参数，再 `napcat_call(action="get_group_file_system_info", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取群聊文件系统的空间及状态信息

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    }
  },
  "required": [
    "group_id"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456"
}
```

## 返回数据结构

```json
{
  "description": "群文件系统信息",
  "type": "object",
  "properties": {
    "file_count": {
      "description": "文件总数",
      "type": "number"
    },
    "limit_count": {
      "description": "文件上限",
      "type": "number"
    },
    "used_space": {
      "description": "已使用空间",
      "type": "number"
    },
    "total_space": {
      "description": "总空间",
      "type": "number"
    }
  },
  "required": [
    "file_count",
    "limit_count",
    "used_space",
    "total_space"
  ]
}
```

