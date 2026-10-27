# NapCat `send_online_folder`：发送在线文件夹

功能：发送在线文件夹

分类：文件扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/410334674e0.md

调用方法：先 `napcat_describe(action="send_online_folder")` 核对本机参数，再 `napcat_call(action="send_online_folder", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。

## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "user_id": {
      "description": "用户 QQ",
      "type": "string"
    },
    "folder_path": {
      "description": "本地文件夹路径",
      "type": "string"
    },
    "folder_name": {
      "description": "文件夹名称 (可选)",
      "type": "string"
    }
  },
  "required": [
    "user_id",
    "folder_path"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "user_id": "123456789",
  "folder_path": "C:\\path\\to\\folder"
}
```

## 返回数据结构

```json
{
  "description": "发送结果"
}
```

