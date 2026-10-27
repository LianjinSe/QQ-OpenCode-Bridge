# NapCat `rename_group_file`：重命名群文件

功能：重命名群文件

分类：文件扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/283136375e0.md

调用方法：先 `napcat_describe(action="rename_group_file")` 核对本机参数，再 `napcat_call(action="rename_group_file", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

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
    "current_parent_directory": {
      "description": "当前父目录",
      "type": "string"
    },
    "new_name": {
      "description": "新文件名",
      "type": "string"
    }
  },
  "required": [
    "group_id",
    "file_id",
    "current_parent_directory",
    "new_name"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "file_id": "/file_id",
  "current_parent_directory": "/",
  "new_name": "new_name.jpg"
}
```

## 返回数据结构

```json
{
  "description": "重命名文件结果",
  "type": "object",
  "properties": {
    "ok": {
      "description": "是否成功",
      "type": "boolean"
    }
  },
  "required": [
    "ok"
  ]
}
```

