# 🎯 双币抄底定投 (Dual Asset Buy-Low Recurring)

## 简介

定期使用双币理财尝试以低于市价买入目标币种，自动选择最优行权价，条件匹配时自动申购，到期未成交则循环续期。

## 详细描述

双币抄底定投策略巧妙利用Bybit双币理财产品的结构特性：当结算价低于行权价时，您可以以行权价买入目标加密货币，同时无论是否成交都能赚取溢价收益。

策略定期扫描可用的双币理财产品，筛选目标币种/投入币种对应的产品，将行权价直接与您设定的目标买入价对比。当行权价 ≤ 目标买入价且溢价年化收益达标时，自动执行申购。

核心特性：
- **有效买入价 = 行权价**（直接使用行权价作为判断标准）
- **资金账户下单**（使用FUND账户资产）
- **余额检查**（下单前检查资金账户余额是否充足）
- **防重复下单**（记录到期时间，到期前不重复下单）
- **大额拆单**（超过产品maxInvestmentAmount的80%自动拆分，每轮重新查询限额，每笔间隔5秒并重新检查条件）
- **Debug模式**（无需API Key即可查看策略计划，输出日志文件记录完整判断过程）

风险提示：若市场大幅下跌超过行权价，将以行权价买入，可能面临进一步下跌风险。

## 策略运行逻辑

1. **检查到期时间** — 若上一轮下单产品尚未到期，跳过本轮
2. **获取双币产品** — 拉取所有DualAssets产品，筛选baseCoin=targetCoin且quoteCoin=指定投入币种的产品
3. **验证产品存在** — 若无匹配产品，告知用户并终止运行
4. **检查账户余额** — 查询FUND账户中投入币种余额，不足则跳过本轮
5. **获取报价详情** — 获取各产品的行权价、溢价和期限信息
6. **条件判断** — 行权价 ≤ targetBuyPrice 且 溢价年化 ≥ minPremiumYield
7. **选择最优档位** — 根据期限偏好（最短/最长/平衡）选择产品；同等条件下优先选择行权价距当前市场价最远的产品（折扣最深）
8. **执行申购（动态拆单）** — 投入金额超过产品maxInvestmentAmount时按其80%拆为多笔，每笔下单前重新查询最新限额，间隔5秒且重新检查条件
9. **记录到期时间** — 成功下单后记录settlementTime，到期前不再重复下单
10. **循环执行** — 按schedule频率（每日/每周）循环执行

## 策略参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| targetCoin | 目标累积币种 | BTC |
| quoteCoin | 投入币种（支持自定义） | USDT |
| targetBuyPrice | 最高可接受行权价（必填） | - |
| investPerRound | 每轮投入金额（投入币种计） | 500 |
| minPremiumYield | 最低溢价年化(10%) | 0.10 |
| recurringSchedule | 执行频率: daily/weekly | daily |
| preferredDuration | 期限偏好: shortest/longest/balanced | shortest |
| debug | Debug模式（dry-run） | 关闭 |
| testnet | 使用Testnet API（需要API Key） | 关闭 |

## 安装方法

复制以下指令发送给你的AI助手：

```
Please read https://github.com/bybit-exchange/skills/blob/main/skills/dual-asset-buy-low/skill.md and install it as a skill
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
python scripts/buy_low.py --target-coin BTC --target-price 60000

# 自定义投入币种和金额
python scripts/buy_low.py --target-coin ETH --target-price 2800 \
  --quote-coin USDC --invest 1000 --schedule weekly

# Debug模式（无需配置API Key）
python scripts/buy_low.py --target-coin BTC --target-price 60000 --debug

# Testnet模式（需要API Key，在测试网执行真实下单）
python scripts/buy_low.py --target-coin BTC --target-price 60000 --testnet
```

## 大额拆单说明

当每轮投入金额（investPerRound）超过产品的 `maxInvestmentAmount` 时，策略自动将订单拆分为多笔：
- 每笔订单金额不超过 `maxInvestmentAmount * 80%`
- 每笔下单前调用 `product-extra-info` 接口重新查询最新的 `maxInvestmentAmount`（确保使用实时限额）
- 每笔订单间隔5秒
- 每笔下单前重新检查条件（行权价 ≤ targetBuyPrice 且 溢价年化 ≥ minPremiumYield）
- 若条件不满足或限额查询失败，本轮剩余订单终止（实际投入可能少于investPerRound）
- 若 `maxInvestmentAmount` 查询失败，使用保守回退值 200,000

## Debug模式说明

使用 `--debug` 参数启动Debug模式：
- 不需要配置API Key和Secret
- 不执行实际下单操作
- 输出匹配的产品信息和计划下单详情
- 输出即将调用的下单API请求体（JSON格式）
- **生成日志文件** `buylow_debug_{YYYYMMDD_HHMMSS}.log`，记录每一步获取的信息及判断逻辑
- 可通过 `--log-dir` 指定日志文件输出目录（默认当前目录）
- 适合在正式运行前验证策略逻辑和排查问题

## Testnet模式说明

使用 `--testnet` 参数启动Testnet模式：
- 需要配置API Key和Secret（Testnet环境的Key）
- 连接 `api-testnet.bybit.com`
- 执行真实下单操作（在测试网，不影响真实资金）
- 自动跳过CONFIRM确认步骤
- `--debug` 和 `--testnet` 互斥，不可同时使用

## 风险提示

- 若市场大幅下跌超过行权价，将以行权价买入，可能面临进一步下跌风险
- 双币理财到期前资金被锁定，无法提前赎回
- 溢价收益不能完全对冲价格下跌带来的损失
- 大额拆单时，后续子订单可能因条件变化而无法执行
- 请根据自身风险承受能力谨慎设置targetBuyPrice
- 建议先在Testnet环境或Debug模式下测试
