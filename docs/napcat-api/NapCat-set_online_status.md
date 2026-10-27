# NapCat `set_online_status`：设置在线状态

功能：设置在线状态

分类：系统扩展

可用状态：本机 NapCat 4.18.41 已注册。

来源：https://napcat.apifox.cn/226658977e0.md

调用方法：先 `napcat_describe(action="set_online_status")` 核对本机参数，再 `napcat_call(action="set_online_status", params={...})`。只有真实管理员任务可执行；返回 `confirmed` 才能确认成功，`uncertain` 不能盲目重试。


## 状态列表

### 在线
```json5;
{ "status": 10, "ext_status": 0, "battery_status": 0; }
```

### Q我吧
```json5;
{ "status": 60, "ext_status": 0, "battery_status": 0; }
```

### 离开
```json5;
{ "status": 30, "ext_status": 0, "battery_status": 0; }
```

### 忙碌
```json5;
{ "status": 50, "ext_status": 0, "battery_status": 0; }
```

### 请勿打扰
```json5;
{ "status": 70, "ext_status": 0, "battery_status": 0; }
```

### 隐身
```json5;
{ "status": 40, "ext_status": 0, "battery_status": 0; }
```

### 听歌中
```json5;
{ "status": 10, "ext_status": 1028, "battery_status": 0; }
```

### 春日限定
```json5;
{ "status": 10, "ext_status": 2037, "battery_status": 0; }
```

### 一起元梦
```json5;
{ "status": 10, "ext_status": 2025, "battery_status": 0; }
```

### 求星搭子
```json5;
{ "status": 10, "ext_status": 2026, "battery_status": 0; }
```

### 被掏空
```json5;
{ "status": 10, "ext_status": 2014, "battery_status": 0; }
```

### 今日天气
```json5;
{ "status": 10, "ext_status": 1030, "battery_status": 0; }
```

### 我crash了
```json5;
{ "status": 10, "ext_status": 2019, "battery_status": 0; }
```

### 爱你
```json5;
{ "status": 10, "ext_status": 2006, "battery_status": 0; }
```

### 恋爱中
```json5;
{ "status": 10, "ext_status": 1051, "battery_status": 0; }
```

### 好运锦鲤
```json5;
{ "status": 10, "ext_status": 1071, "battery_status": 0; }
```

### 水逆退散
```json5;
{ "status": 10, "ext_status": 1201, "battery_status": 0; }
```

### 嗨到飞起
```json5;
{ "status": 10, "ext_status": 1056, "battery_status": 0; }
```

### 元气满满
```json5;
{ "status": 10, "ext_status": 1058, "battery_status": 0; }
```

### 宝宝认证
```json5;
{ "status": 10, "ext_status": 1070, "battery_status": 0; }
```

### 一言难尽
```json5;
{ "status": 10, "ext_status": 1063, "battery_status": 0; }
```

### 难得糊涂
```json5;
{ "status": 10, "ext_status": 2001, "battery_status": 0; }
```

### emo中
```json5;
{ "status": 10, "ext_status": 1401, "battery_status": 0; }
```

### 我太难了
```json5;
{ "status": 10, "ext_status": 1062, "battery_status": 0; }
```

### 我想开了
```json5;
{ "status": 10, "ext_status": 2013, "battery_status": 0; }
```

### 我没事
```json5;
{ "status": 10, "ext_status": 1052, "battery_status": 0; }
```

### 想静静
```json5;
{ "status": 10, "ext_status": 1061, "battery_status": 0; }
```

### 悠哉哉
```json5;
{ "status": 10, "ext_status": 1059, "battery_status": 0; }
```

### 去旅行
```json5;
{ "status": 10, "ext_status": 2015, "battery_status": 0; }
```

### 信号弱
```json5;
{ "status": 10, "ext_status": 1011, "battery_status": 0; }
```

### 出去浪
```json5;
{ "status": 10, "ext_status": 2003, "battery_status": 0; }
```

### 肝作业
```json5;
{ "status": 10, "ext_status": 2012, "battery_status": 0; }
```

### 学习中
```json5;
{ "status": 10, "ext_status": 1018, "battery_status": 0; }
```

### 搬砖中
```json5;
{ "status": 10, "ext_status": 2023, "battery_status": 0; }
```

### 摸鱼中
```json5;
{ "status": 10, "ext_status": 1300, "battery_status": 0; }
```

### 无聊中
```json5;
{ "status": 10, "ext_status": 1060, "battery_status": 0; }
```

### timi中
```json5;
{ "status": 10, "ext_status": 1027, "battery_status": 0; }
```

### 睡觉中
```json5;
{ "status": 10, "ext_status": 1016, "battery_status": 0; }
```

### 熬夜中
```json5;
{ "status": 10, "ext_status": 1032, "battery_status": 0; }
```

### 追剧中
```json5;
{ "status": 10, "ext_status": 1021, "battery_status": 0; }
```

### 我的电量
```json5;
{
  "status": 10,
    "ext_status": 1000,
      "battery_status": 0;
}
```


## 请求参数（本机 schema 优先）

```json
{
  "type": "object",
  "properties": {
    "status": {
      "description": "在线状态",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "ext_status": {
      "description": "扩展状态",
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "string"
        }
      ]
    },
    "battery_status": {
      "description": "电量状态",
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
    "status",
    "ext_status",
    "battery_status"
  ]
}
```

## 参数示例（示例 QQ／群号不是实际目标）

```json
{
  "status": 11,
  "ext_status": 0,
  "battery_status": 100
}
```

## 返回数据结构

```json
{
  "description": "设置结果",
  "type": "null"
}
```

