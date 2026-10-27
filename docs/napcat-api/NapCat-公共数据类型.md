# NapCat 公共数据类型与消息段

来源：本机 NapCat 4.18.41 运行时参数与返回 schema。

## OB11MessageMixType

```json
{
  "description": "OneBot 11 消息混合类型",
  "anyOf": [
    {
      "type": "array",
      "items": {
        "$ref": "#/$defs/OB11MessageData"
      }
    },
    {
      "type": "string"
    },
    {
      "$ref": "#/$defs/OB11MessageData"
    }
  ]
}
```

## OB11MessageData

```json
{
  "description": "OneBot 11 消息段",
  "anyOf": [
    {
      "$ref": "#/$defs/OB11MessageText"
    },
    {
      "$ref": "#/$defs/OB11MessageFace"
    },
    {
      "$ref": "#/$defs/OB11MessageMFace"
    },
    {
      "$ref": "#/$defs/OB11MessageAt"
    },
    {
      "$ref": "#/$defs/OB11MessageReply"
    },
    {
      "$ref": "#/$defs/OB11MessageImage"
    },
    {
      "$ref": "#/$defs/OB11MessageRecord"
    },
    {
      "$ref": "#/$defs/OB11MessageVideo"
    },
    {
      "$ref": "#/$defs/OB11MessageFile"
    },
    {
      "$ref": "#/$defs/OB11MessageIdMusic"
    },
    {
      "$ref": "#/$defs/OB11MessageCustomMusic"
    },
    {
      "$ref": "#/$defs/OB11MessagePoke"
    },
    {
      "$ref": "#/$defs/OB11MessageDice"
    },
    {
      "$ref": "#/$defs/OB11MessageRPS"
    },
    {
      "$ref": "#/$defs/OB11MessageContact"
    },
    {
      "$ref": "#/$defs/OB11MessageLocation"
    },
    {
      "$ref": "#/$defs/OB11MessageJson"
    },
    {
      "$ref": "#/$defs/OB11MessageXml"
    },
    {
      "$ref": "#/$defs/OB11MessageMarkdown"
    },
    {
      "$ref": "#/$defs/OB11MessageMiniApp"
    },
    {
      "$ref": "#/$defs/OB11MessageNode"
    },
    {
      "$ref": "#/$defs/OB11MessageForward"
    },
    {
      "$ref": "#/$defs/OB11MessageOnlineFile"
    },
    {
      "$ref": "#/$defs/OB11MessageFlashTransfer"
    }
  ]
}
```

## OB11MessageText

```json
{
  "description": "纯文本消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "text",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "text": {
          "description": "纯文本内容",
          "type": "string"
        }
      },
      "required": [
        "text"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageFace

```json
{
  "description": "QQ表情消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "face",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "id": {
          "description": "表情ID",
          "type": "string"
        },
        "resultId": {
          "description": "结果ID",
          "type": "string"
        },
        "chainCount": {
          "description": "连击数",
          "type": "number"
        }
      },
      "required": [
        "id"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageMFace

```json
{
  "description": "商城表情消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "mface",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "emoji_package_id": {
          "description": "表情包ID",
          "type": "number"
        },
        "emoji_id": {
          "description": "表情ID",
          "type": "string"
        },
        "key": {
          "description": "表情key",
          "type": "string"
        },
        "summary": {
          "description": "表情摘要",
          "type": "string"
        }
      },
      "required": [
        "emoji_package_id",
        "emoji_id",
        "key",
        "summary"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageAt

```json
{
  "description": "@消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "at",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "qq": {
          "description": "QQ号或all",
          "type": "string"
        },
        "name": {
          "description": "显示名称",
          "type": "string"
        }
      },
      "required": [
        "qq"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageReply

```json
{
  "description": "回复消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "reply",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "id": {
          "description": "消息ID的短ID映射",
          "type": "string"
        },
        "seq": {
          "description": "消息序列号，优先使用",
          "type": "number"
        }
      }
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageImage

```json
{
  "description": "图片消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "image",
      "type": "string"
    },
    "data": {
      "type": "object",
      "allOf": [
        {
          "description": "文件消息段基础数据",
          "type": "object",
          "properties": {
            "file": {
              "description": "文件路径/URL/file:///",
              "type": "string"
            },
            "path": {
              "description": "文件路径",
              "type": "string"
            },
            "url": {
              "description": "文件URL",
              "type": "string"
            },
            "name": {
              "description": "文件名",
              "type": "string"
            },
            "thumb": {
              "description": "缩略图",
              "type": "string"
            }
          },
          "required": [
            "file"
          ]
        },
        {
          "type": "object",
          "properties": {
            "summary": {
              "description": "图片摘要",
              "type": "string"
            },
            "sub_type": {
              "description": "图片子类型",
              "type": "number"
            }
          }
        }
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageRecord

```json
{
  "description": "语音消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "record",
      "type": "string"
    },
    "data": {
      "$ref": "#/$defs/FileBaseData"
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## FileBaseData

```json
{
  "description": "文件消息段基础数据",
  "type": "object",
  "properties": {
    "file": {
      "description": "文件路径/URL/file:///",
      "type": "string"
    },
    "path": {
      "description": "文件路径",
      "type": "string"
    },
    "url": {
      "description": "文件URL",
      "type": "string"
    },
    "name": {
      "description": "文件名",
      "type": "string"
    },
    "thumb": {
      "description": "缩略图",
      "type": "string"
    }
  },
  "required": [
    "file"
  ]
}
```

## OB11MessageVideo

```json
{
  "description": "视频消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "video",
      "type": "string"
    },
    "data": {
      "$ref": "#/$defs/FileBaseData"
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageFile

```json
{
  "description": "文件消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "file",
      "type": "string"
    },
    "data": {
      "$ref": "#/$defs/FileBaseData"
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageIdMusic

```json
{
  "description": "ID音乐消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "music",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "type": {
          "description": "音乐平台类型",
          "anyOf": [
            {
              "const": "qq",
              "type": "string"
            },
            {
              "const": "163",
              "type": "string"
            },
            {
              "const": "kugou",
              "type": "string"
            },
            {
              "const": "migu",
              "type": "string"
            },
            {
              "const": "kuwo",
              "type": "string"
            }
          ]
        },
        "id": {
          "description": "音乐ID",
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "number"
            }
          ]
        }
      },
      "required": [
        "type",
        "id"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageCustomMusic

```json
{
  "description": "自定义音乐消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "music",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "type": {
          "description": "音乐平台类型",
          "anyOf": [
            {
              "const": "qq",
              "type": "string"
            },
            {
              "const": "163",
              "type": "string"
            },
            {
              "const": "kugou",
              "type": "string"
            },
            {
              "const": "migu",
              "type": "string"
            },
            {
              "const": "kuwo",
              "type": "string"
            },
            {
              "const": "custom",
              "type": "string"
            }
          ]
        },
        "id": {
          "type": "undefined"
        },
        "url": {
          "description": "点击后跳转URL",
          "type": "string"
        },
        "audio": {
          "description": "音频URL",
          "type": "string"
        },
        "title": {
          "description": "音乐标题",
          "type": "string"
        },
        "image": {
          "description": "封面图片URL",
          "type": "string"
        },
        "content": {
          "description": "音乐简介",
          "type": "string"
        }
      },
      "required": [
        "type",
        "id",
        "url",
        "image"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessagePoke

```json
{
  "description": "戳一戳消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "poke",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "type": {
          "description": "戳一戳类型",
          "type": "string"
        },
        "id": {
          "description": "戳一戳ID",
          "type": "string"
        }
      },
      "required": [
        "type",
        "id"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageDice

```json
{
  "description": "骰子消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "dice",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "result": {
          "description": "骰子结果",
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
        "result"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageRPS

```json
{
  "description": "猜拳消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "rps",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "result": {
          "description": "猜拳结果",
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
        "result"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageContact

```json
{
  "description": "联系人消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "contact",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "type": {
          "description": "联系人类型",
          "anyOf": [
            {
              "const": "qq",
              "type": "string"
            },
            {
              "const": "group",
              "type": "string"
            }
          ]
        },
        "id": {
          "description": "联系人ID",
          "type": "string"
        }
      },
      "required": [
        "type",
        "id"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageLocation

```json
{
  "description": "位置消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "location",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "lat": {
          "description": "纬度",
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "number"
            }
          ]
        },
        "lon": {
          "description": "经度",
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "number"
            }
          ]
        },
        "title": {
          "description": "标题",
          "type": "string"
        },
        "content": {
          "description": "内容",
          "type": "string"
        }
      },
      "required": [
        "lat",
        "lon"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageJson

```json
{
  "description": "JSON消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "json",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "data": {
          "description": "JSON数据",
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "object",
              "properties": {}
            }
          ]
        },
        "config": {
          "type": "object",
          "properties": {
            "token": {
              "description": "token",
              "type": "string"
            }
          },
          "required": [
            "token"
          ]
        }
      },
      "required": [
        "data"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageXml

```json
{
  "description": "XML消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "xml",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "data": {
          "description": "XML数据",
          "type": "string"
        }
      },
      "required": [
        "data"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageMarkdown

```json
{
  "description": "Markdown消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "markdown",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "content": {
          "description": "Markdown内容",
          "type": "string"
        }
      },
      "required": [
        "content"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageMiniApp

```json
{
  "description": "小程序消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "miniapp",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "data": {
          "description": "小程序数据",
          "type": "string"
        }
      },
      "required": [
        "data"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageNode

```json
{
  "description": "合并转发消息节点",
  "type": "object",
  "properties": {
    "type": {
      "const": "node",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "id": {
          "description": "转发消息ID",
          "type": "string"
        },
        "user_id": {
          "description": "发送者QQ号",
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "string"
            }
          ]
        },
        "uin": {
          "description": "发送者QQ号(兼容go-cqhttp)",
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "string"
            }
          ]
        },
        "nickname": {
          "description": "发送者昵称",
          "type": "string"
        },
        "name": {
          "description": "发送者昵称(兼容go-cqhttp)",
          "type": "string"
        },
        "content": {
          "description": "消息内容 (OB11MessageMixType)"
        },
        "source": {
          "description": "消息来源",
          "type": "string"
        },
        "news": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "text": {
                "description": "新闻文本",
                "type": "string"
              }
            },
            "required": [
              "text"
            ]
          }
        },
        "summary": {
          "description": "摘要",
          "type": "string"
        },
        "prompt": {
          "description": "提示",
          "type": "string"
        },
        "time": {
          "description": "时间",
          "type": "string"
        }
      },
      "required": [
        "nickname",
        "content"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageForward

```json
{
  "description": "合并转发消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "forward",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "id": {
          "description": "合并转发ID",
          "type": "string"
        },
        "content": {
          "description": "消息内容 (OB11Message[])"
        }
      },
      "required": [
        "id"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageOnlineFile

```json
{
  "description": "在线文件消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "onlinefile",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "msgId": {
          "description": "消息ID",
          "type": "string"
        },
        "elementId": {
          "description": "元素ID",
          "type": "string"
        },
        "fileName": {
          "description": "文件名",
          "type": "string"
        },
        "fileSize": {
          "description": "文件大小",
          "type": "string"
        },
        "isDir": {
          "description": "是否为目录",
          "type": "boolean"
        }
      },
      "required": [
        "msgId",
        "elementId",
        "fileName",
        "fileSize",
        "isDir"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11MessageFlashTransfer

```json
{
  "description": "QQ闪传消息段",
  "type": "object",
  "properties": {
    "type": {
      "const": "flashtransfer",
      "type": "string"
    },
    "data": {
      "type": "object",
      "properties": {
        "fileSetId": {
          "description": "文件集ID",
          "type": "string"
        }
      },
      "required": [
        "fileSetId"
      ]
    }
  },
  "required": [
    "type",
    "data"
  ]
}
```

## OB11User

```json
{
  "description": "OneBot 11 用户信息",
  "type": "object",
  "properties": {
    "birthday_year": {
      "description": "出生年份",
      "type": "number"
    },
    "birthday_month": {
      "description": "出生月份",
      "type": "number"
    },
    "birthday_day": {
      "description": "出生日期",
      "type": "number"
    },
    "phone_num": {
      "description": "手机号",
      "type": "string"
    },
    "email": {
      "description": "邮箱",
      "type": "string"
    },
    "category_id": {
      "description": "分组ID",
      "type": "number"
    },
    "user_id": {
      "description": "QQ号",
      "type": "number"
    },
    "nickname": {
      "description": "昵称",
      "type": "string"
    },
    "remark": {
      "description": "备注",
      "type": "string"
    },
    "sex": {
      "description": "性别",
      "type": "string"
    },
    "level": {
      "description": "等级",
      "type": "number"
    },
    "age": {
      "description": "年龄",
      "type": "number"
    },
    "qid": {
      "description": "QID",
      "type": "string"
    },
    "login_days": {
      "description": "登录天数",
      "type": "number"
    },
    "categoryName": {
      "description": "分组名称",
      "type": "string"
    },
    "categoryId": {
      "description": "分组ID",
      "type": "number"
    }
  },
  "required": [
    "user_id",
    "nickname"
  ]
}
```

## OB11Group

```json
{
  "description": "OneBot 11 群信息",
  "type": "object",
  "properties": {
    "group_all_shut": {
      "description": "是否全员禁言",
      "type": "number"
    },
    "group_remark": {
      "description": "群备注",
      "type": "string"
    },
    "group_id": {
      "description": "群号",
      "type": "number"
    },
    "group_name": {
      "description": "群名称",
      "type": "string"
    },
    "member_count": {
      "description": "成员人数",
      "type": "number"
    },
    "max_member_count": {
      "description": "最大成员人数",
      "type": "number"
    }
  },
  "required": [
    "group_all_shut",
    "group_remark",
    "group_id",
    "group_name"
  ]
}
```

## OB11GroupMember

```json
{
  "description": "OneBot 11 群成员信息",
  "type": "object",
  "properties": {
    "group_id": {
      "description": "群号",
      "type": "number"
    },
    "user_id": {
      "description": "QQ号",
      "type": "number"
    },
    "nickname": {
      "description": "昵称",
      "type": "string"
    },
    "card": {
      "description": "名片",
      "type": "string"
    },
    "sex": {
      "description": "性别",
      "type": "string"
    },
    "age": {
      "description": "年龄",
      "type": "number"
    },
    "join_time": {
      "description": "入群时间戳",
      "type": "number"
    },
    "last_sent_time": {
      "description": "最后发言时间戳",
      "type": "number"
    },
    "level": {
      "description": "等级",
      "type": "string"
    },
    "qq_level": {
      "description": "QQ等级",
      "type": "number"
    },
    "role": {
      "description": "角色 (owner/admin/member)",
      "type": "string"
    },
    "title": {
      "description": "头衔",
      "type": "string"
    },
    "area": {
      "description": "地区",
      "type": "string"
    },
    "unfriendly": {
      "description": "是否不良记录",
      "type": "boolean"
    },
    "title_expire_time": {
      "description": "头衔过期时间",
      "type": "number"
    },
    "card_changeable": {
      "description": "是否允许修改名片",
      "type": "boolean"
    },
    "shut_up_timestamp": {
      "description": "禁言截止时间戳",
      "type": "number"
    },
    "is_robot": {
      "description": "是否为机器人",
      "type": "boolean"
    },
    "qage": {
      "description": "Q龄",
      "type": "number"
    }
  },
  "required": [
    "group_id",
    "user_id",
    "nickname"
  ]
}
```

## OB11Notify

```json
{
  "description": "OneBot 11 通知信息",
  "type": "object",
  "properties": {
    "request_id": {
      "description": "请求ID",
      "type": "number"
    },
    "invitor_uin": {
      "description": "邀请者QQ",
      "type": "number"
    },
    "invitor_nick": {
      "description": "邀请者昵称",
      "type": "string"
    },
    "group_id": {
      "description": "群号",
      "type": "number"
    },
    "group_name": {
      "description": "群名称",
      "type": "string"
    },
    "message": {
      "description": "附言",
      "type": "string"
    },
    "checked": {
      "description": "是否已处理",
      "type": "boolean"
    },
    "actor": {
      "description": "操作者QQ",
      "type": "number"
    },
    "requester_nick": {
      "description": "申请者昵称",
      "type": "string"
    }
  },
  "required": [
    "request_id",
    "invitor_uin",
    "invitor_nick",
    "group_id",
    "group_name",
    "message",
    "checked",
    "actor",
    "requester_nick"
  ]
}
```