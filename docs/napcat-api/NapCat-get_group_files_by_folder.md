# NapCat `get_group_files_by_folder`：获取群文件夹文件列表

功能：获取群文件夹文件列表

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658865e0.md

调用方法：先 `napcat_describe(action="get_group_files_by_folder")` 核对本机参数，再 `napcat_call(action="get_group_files_by_folder", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

获取指定群文件夹下的文件及子文件夹列表

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
    },
    "file_count": {
      "default": 50,
      "description": "文件数量",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    }
  },
  "required": [
    "group_id",
    "file_count"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "group_id": "123456",
  "folder_id": "folder_id"
}
```

## 返回数据结构

```json
{
  "description": "群文件夹文件列表",
  "type": "object",
  "properties": {
    "files": {
      "description": "文件列表",
      "type": "array",
      "items": {}
    },
    "folders": {
      "description": "文件夹列表",
      "type": "array",
      "items": {}
    }
  },
  "required": [
    "files",
    "folders"
  ]
}
```

