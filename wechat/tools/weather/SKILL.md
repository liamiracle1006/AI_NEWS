# Skill: weather

## 简介

查城市天气。用 open-meteo 免 key API：先 geocode 找城市坐标，再查 current weather。

## 触发词

- `天气`
- `weather`

参数是城市名（可中可英）；没说就默认上海。

## 输入 → 输出

| 用户发 | bot 回（示例） |
|---|---|
| `上海天气` | `上海·中国：晴，28°C，体感 30°C，湿度 65%，风速 2.1m/s。` |
| `Tokyo weather` | `Tokyo·Japan：多云，24°C，湿度 70%，风速 3.0m/s。` |
| `天气` | `上海·中国：...`（默认上海）|
| `天气 火星` | `找不到『火星』这个地方，换个写法试试？` |

## 工作流

1. 抽城市名（去掉触发词 + 去掉"的/今天/查"等冗余）
2. open-meteo geocoding API 找坐标
3. open-meteo forecast API 拿当前天气
4. WMO 天气代码 → 中文描述
5. 拼成"地点：天气，温度，体感，湿度，风速。"格式

## 安全边界

- 仅公网调用（无认证）
- 无文件 IO
- 5 秒超时，失败友好提示
- 不会泄露用户位置（用户自己说哪个城市才查那个）

## 给 @claude 的提示

潜在升级：
- 加预报（forecast next 5 days）→ open-meteo 的 `daily` 参数
- 加空气质量 → `air_quality` API（也免 key）
- 加台风路径 / 暴雨预警 → 国内的气象局 API（需要 key）
- WMO 描述表不全 → 补 `_WMO_DESC` 字典
- 城市名解析有歧义（如"福州"vs"福州市"）→ 加 LLM 兜底重排序
