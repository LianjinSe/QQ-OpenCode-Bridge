# NapCat `create_group_file_folder`：创建群文件目录

功能：创建群文件目录

分类：Go-CQHTTP

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658773e0.md

调用方法：先 `napcat_describe(action="create_group_file_folder")` 核对本机参数，再 `napcat_call(action="create_group_file_folder", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

在群文件系统中创建新的文件夹

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "string"
    },
    "folder_name": {
      "description": "文件夹名称",
      "type": "string"
    },
    "name": {
      "description": "文件夹名称",
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
  "group_id": "123456789",
  "folder_name": "新建文件夹"
}
```

## 返回数据结构

```json
{
  "description": "创建文件夹结果",
  "type": "object",
  "properties": {
    "result": {
      "description": "操作结果"
    },
    "groupItem": {
      "description": "群项信息"
    }
  },
  "required": [
    "result",
    "groupItem"
  ]
}
```

