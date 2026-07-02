# ⚡ 事件驱动DoubleWin捕手 (Event-Driven DoubleWin Hunter)

## 简介

定时扫描经济日历和加密新闻，由AI代理评估事件对目标币种的影响程度，在重大事件前自动申购DoubleWin产品，从波动中获利。

## 详细描述

事件驱动DoubleWin捕手策略的核心逻辑：重大宏观/加密事件（如FOMC利率决议、CPI数据、ETF审批等）往往引发显著的价格波动。DoubleWin产品在价格大幅波动（无论方向）时获利，与事件驱动的波动特征天然匹配。

策略每8小时从四个指定平台获取最新事件：
- **Investing.com** — 全球经济日历（利率决议、通胀数据等）
- **CoinDesk** — 加密货币行业新闻
- **CoinTelegraph** — 加密市场分析与快讯
- **The Block** — 加密市场深度报道

核心特性：
- **AI代理评级** — 不使用关键词匹配，由执行策略的AI代理自行判断事件影响程度
- **FUND资金账户** — 使用资金账户资产下单
- **余额检查** — 下单前检查FUND账户余额是否充足
- **到期时间防重复** — 记录到期时间，产品到期前不重复下单
- **产品到期>事件时间** — 确保选择的产品到期时间晚于事件发生时间
- **事件去重** — 由AI代理判断候选事件与历史事件是否为同一事件（支持标题不同但实质相同的事件识别）
- **Debug模式** — 无需API Key即可查看策略计划
- **单笔限额1000U** — 每笔最大投入1000 USDT

风险提示：DoubleWin产品在波动不足时可能导致本金全部亏损。本策略属于高风险策略，仅适合理解结构化产品的用户。

## 策略运行逻辑

1. **检查到期时间** — 若上一轮下单产品尚未到期，跳过本轮
2. **获取事件数据** — 从4个平台获取经济日历和新闻（Investing.com、CoinDesk、CoinTelegraph、The Block）
3. **双时间窗口过滤** — 未来entryWindowHours内的即将发生事件 + 过去entryWindowHours内刚发生的突发新闻
4. **事件去重（AI判断）** — 先精确匹配ID，再由AI代理判断候选事件与历史事件是否实质相同（即使标题略有不同也能识别）
5. **AI代理评级** — 展示事件详情，由AI代理判断影响程度（high/medium/low/skip）
6. **检查FUND余额** — 查询FUND账户USDT余额，不足则跳过
7. **获取DoubleWin产品** — 拉取目标币种的可用DoubleWin产品
8. **选择产品（到期>事件时间）** — 选择到期时间晚于事件时间的产品
9. **选择杠杆** — 根据评级和偏好选择杠杆倍数
10. **执行下单** — 使用FUND账户申购，成功后记录到期时间并保存去重记录

## 策略参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| targetCoin | 目标标的币种 | BTC |
| capitalPerTrade | 每笔投入USDT（最大1000） | 200 |
| entryWindowHours | 事件前入场窗口（小时） | 24 |
| minEventLevel | 最低事件级别: medium/high | medium |
| preferredLeverage | 杠杆偏好: auto/low/high | auto |
| debug | Debug模式（dry-run） | 关闭 |
| testnet | 使用Testnet API（需要API Key） | 关闭 |

**注意：** 账户类型固定为FUND（资金账户），单笔最大投入1000 USDT。

## 数据源平台

| 平台 | 类型 | 说明 |
|------|------|------|
| Investing.com | 经济日历 | 全球宏观经济事件（利率、CPI、非农等） |
| CoinDesk | 加密新闻RSS | 加密货币行业新闻和快讯 |
| CoinTelegraph | 加密新闻RSS | 加密市场分析与行业报道 |
| The Block | 加密新闻RSS | 加密市场深度新闻 |

每次扫描周期四个平台全部尝试。事件必须包含明确的时间信息，无法解析时间的事件自动丢弃。

## 安装方法

复制以下指令发送给你的AI助手：

```
Please read https://github.com/bybit-exchange/skills/blob/main/skills/event-driven-doublewin/skill.md and install it as a skill
```

## 运行环境要求

- Python 3.8+
- 依赖库：`requests`
- 环境变量配置：
  ```bash
  export BYBIT_API_KEY="your_api_key"
  export BYBIT_API_SECRET="your_secret_key"
  export BYBIT_ENV="mainnet"  # 或 "testnet"
  ```

## 运行

```bash
pip install requests

# 基本用法
python scripts/doublewin_hunter.py --target-coin BTC

# 保守设置（仅高影响事件，低杠杆）
python scripts/doublewin_hunter.py --target-coin ETH --capital-per-trade 100 \
  --min-level high --leverage low

# Debug模式（无需配置API Key）
python scripts/doublewin_hunter.py --target-coin BTC --debug

# Testnet模式（需要API Key，在测试网执行真实下单）
python scripts/doublewin_hunter.py --target-coin BTC --testnet
```

## Debug模式说明

使用 `--debug` 参数启动Debug模式：
- 不需要配置API Key和Secret
- 正常获取RSS新闻源（公开数据）
- 事件自动评级为medium（非交互）
- 事件去重自动判定为"不重复"（非交互）
- 对符合条件的事件：输出计划开仓的DoubleWin品种和API请求体（JSON格式）
- 不执行实际下单操作
- **生成日志文件** `doublewin_debug_{YYYYMMDD_HHMMSS}.log`，记录每一步获取的信息及判断逻辑
- 可通过 `--log-dir` 指定日志文件输出目录（默认当前目录）
- 单次扫描后退出（不循环）

## Testnet模式说明

使用 `--testnet` 参数启动Testnet模式：
- 需要配置API Key和Secret（Testnet环境的Key）
- 连接 `api-testnet.bybit.com`
- 执行真实下单操作（在测试网，不影响真实资金）
- 自动跳过CONFIRM确认步骤
- `--debug` 和 `--testnet` 互斥，不可同时使用

## 事件去重说明

策略维护本地交易历史文件（`doublewin_trade_history.json`），采用两层去重机制：

**第一层：精确ID匹配**
- 基于 title+source+time 生成MD5 ID，完全相同的事件直接跳过

**第二层：AI代理语义判断**
- 向AI代理展示候选事件和最近的历史交易事件列表
- 由AI代理判断候选事件是否与历史中的某个事件实质相同
- 即使标题、来源略有不同，只要指的是同一事件即视为重复
- 例如："Fed holds rates steady" 和 "FOMC leaves interest rates unchanged" 会被识别为同一事件

**存储格式：**
- 每条记录包含完整事件信息（ID、标题、来源、时间、摘要）
- 历史文件保留最近200条记录
- Debug/Testnet模式下自动判定为"不重复"（不阻塞自动化流程）

## 风险提示

- DoubleWin产品在波动不足时可能导致本金**全部亏损**
- 事件影响评估依赖AI代理判断，可能不准确
- 高杠杆放大亏损
- 事件可能已被市场提前定价（利好出尽变利空）
- 频繁交易可能累积较大总亏损
- 建议先在Debug模式或Testnet环境测试
