# NapCat `delete_group_folder`：删除群文件目录

功能：删除群文件目录

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658779e0.md

调用方法：先 `napcat_describe(action="delete_group_folder")` 核对本机参数，再 `napcat_call(action="delete_group_folder", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

在群文件系统中删除指定的文件夹

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "folder_id": {
      "description": "文件夹ID",
      "type": "string"
    },
    "folder": {
      "description": "文件夹ID",
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
  "group_id": "123456",
  "folder_id": "folder_uuid_123"
}
```

## 返回数据结构

```json
{
  "description": "删除结果"
}
```

