# 🛡️ 风险平价理财配置器 (Risk-Parity Earn Allocator)

## 简介

基于APR/风险比加权原则分配理财资金，为每类产品分配风险评分，结合实时APR计算风险调整收益率权重，实现更智能的资产配置。

## 详细描述

风险平价理财配置器将风险调整收益率理论应用于加密货币理财产品配置。核心公式：`weight_i = (APR_i / risk_i) / Σ(APR_j / risk_j)`——不仅考虑风险，还考虑各产品的预期收益率，将资金更多分配给风险调整收益率更优的产品。

策略为每类理财产品预设了风险评分：活期理财(1分) < 链上理财(2分) < 流动性挖矿(3分) < 双币理财(4分) < DoubleWin(5分)。

核心特性：
- **APR/risk权重** — 综合考虑收益率和风险；双币理财使用log10压缩极端APR，硬上限20%
- **DoubleWin固定5%** — DoubleWin无APR，固定分配5%，不参与权重计算
- **资金自动检测** — 实盘/Testnet模式自动读取FUND余额+理财持仓作为总资本
- **增量配置** — 对比现有持仓与目标权重，仅申购差额
- **投资币种指定** — 必须指定投资币种，策略只管理该币种的分配
- **币种支持检查** — 自动验证各类产品是否支持指定币种
- **双币理财方向** — USDT→低买(BuyLow)，非USDT→高卖(SellHigh)
- **产品选择偏好** — 在指定期限内（默认1天）选择行权价最远、APR≥15%的产品
- **不可提前赎回** — 双币理财/DoubleWin超配时等待到期，不强制赎回
- **下单金额限制** — 每类产品有最小/最大申购金额限制
- **流动性挖矿风险提示** — 首次运行时若配置包含流动性挖矿，警告用户再平衡赎回可能因无常损失造成资金损失
- **流动性挖矿赎回币种** — 再平衡赎回流动性挖矿时，指定赎回为用户投资币种
- **三种模式** — Debug（dry-run）、Testnet（测试网实盘）、Mainnet（正式实盘）
- **FUND账户** — 使用资金账户下单

## 策略运行逻辑

1. **检查币种支持** — 验证指定投资币种是否被各类产品支持（DoubleWin仅支持USDT）
2. **获取产品APR** — 查询各类产品当前最佳APR
3. **计算权重** — 双币理财使用 `log10(APR/risk)` 压缩极端收益率，其他产品使用 `APR/risk`；双币理财硬上限20%，DoubleWin固定5%
4. **约束调整** — 应用最大/最小配置限制，归一化权重
5. **金额校验** — 检查各产品最小/最大下单金额（双币50-20万、DoubleWin 50-1000、挖矿≥100、OnChain 50-20万）
6. **产品选择** — 双币理财在指定期限内（默认1天）选择行权价最远的产品（APR≥15%）；DoubleWin选最短到期；其他选最高APR
7. **增量配置** — 对比当前持仓与目标权重，仅申购差额部分
8. **漂移监控** — 每24小时重新计算总资本（FUND余额+持仓），检查权重偏离
9. **再平衡** — 仅赎回FlexibleSaving/OnChain/LiquidityMining超配部分；**双币理财和DoubleWin不支持提前赎回**，超配时等待到期后再平衡；流动性挖矿赎回时指定赎回为投资币种（`coin`字段设为用户指定的投资币种）

## 策略参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| totalCapital | 总配置资金（Debug模式必填；实盘/Testnet自动检测） | 自动 |
| coin | 投资币种（必填） | - |
| allowedProductTypes | 允许的产品类型 | FlexibleSaving,OnChain,LiquidityMining,DualAssets,DoubleWin |
| allowedRiskLevels | 允许的风险等级(1-5) | 1,2,3,4,5 |
| driftThreshold | 再平衡偏离阈值(10%) | 0.1 |
| maxSingleAllocation | 单产品最大配置(75%) | 0.75 |
| minSingleAllocation | 单产品最小配置(0%) | 0.00 |
| dualAssetPreference | 双币产品选择偏好 | nearest-farthest |
| dualAssetMaxDays | 双币理财最大期限（天） | 1 |
| debug | Debug模式（dry-run） | 关闭 |
| testnet | 使用Testnet API（需要API Key） | 关闭 |

**注意：** 账户类型固定为FUND（资金账户）。

**资金自动检测：** 实盘/Testnet模式下，总资本 = FUND账户余额 + 所有相关理财产品持仓金额。无需手动指定资金总量。

## 双币理财方向说明

根据投资币种自动确定双币理财方向：
- **coin = USDT** → 申购**低买(BuyLow)**产品，关注quoteCoin=USDT的产品。价格跌到行权价时以该价格买入目标币种。
- **coin ≠ USDT（如BTC）** → 申购**高卖(SellHigh)**产品，关注baseCoin=该币种的产品。价格涨到行权价时以该价格卖出持有币种。

产品选择偏好（默认nearest-farthest）：优先选到期日最近的产品，同到期日选行权价距现价最远的。

## 下单金额限制

| 产品类型 | 最小金额 | 最大金额 |
|---------|---------|---------|
| FlexibleSaving | 无限制 | 无限制 |
| OnChain | 50 USD | 200,000 USD |
| LiquidityMining | 100 USD | 无限制 |
| DualAssets | 50 USD | 200,000 USD |
| DoubleWin | 50 USD | 1,000 USD |

低于最小金额的配置将被跳过，超过最大金额的配置将被截断。

## 安装方法

复制以下指令发送给你的AI助手：

```
Please read https://github.com/bybit-exchange/skills/blob/main/skills/risk-parity-allocator/skill.md and install it as a skill
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

# 实盘模式（自动检测账户总资本）
python scripts/risk_parity.py --coin USDT

# BTC组合配置
python scripts/risk_parity.py --coin BTC \
  --allowed-types FlexibleSaving,OnChain,DualAssets

# Debug模式（无需配置API Key，--capital必填）
python scripts/risk_parity.py --capital 10000 --coin USDT --debug

# Testnet模式（需要API Key，自动检测Testnet账户余额）
python scripts/risk_parity.py --coin USDT --testnet

# 自定义风险偏好
python scripts/risk_parity.py --coin USDT \
  --allowed-levels 1,2,3 --max-alloc 0.6 --drift 0.08
```

## Debug模式说明

使用 `--debug` 参数启动Debug模式：
- 不需要配置API Key和Secret
- 必须指定 `--capital` 参数
- 正常查询产品API（检查币种支持和获取APR）
- 输出：目标配置权重、选中的具体产品、完整API请求体（JSON格式）
- 不执行实际下单操作
- **生成日志文件** `riskparity_debug_{YYYYMMDD_HHMMSS}.log`，记录每一步获取的信息及判断逻辑
- 可通过 `--log-dir` 指定日志文件输出目录（默认当前目录）
- 输出计划后退出（不循环）

## Testnet模式说明

使用 `--testnet` 参数启动Testnet模式：
- 需要配置API Key和Secret（Testnet环境的Key）
- 连接 `api-testnet.bybit.com`
- 自动检测Testnet账户余额+持仓作为总资本
- 执行真实下单操作（在测试网，不影响真实资金）
- 自动跳过CONFIRM确认步骤
- `--debug` 和 `--testnet` 互斥，不可同时使用

## 风险提示

- 风险评分为启发式分配，非精算计算，实际风险可能与评分不符
- APR为历史数据，不代表未来收益
- DoubleWin产品波动不足时可能损失全部本金
- 即使是"低风险"的活期理财也存在智能合约漏洞等尾部风险
- 市场体制变化可能使历史风险评估失效
- **流动性挖矿再平衡赎回时，可能因无常损失(impermanent loss)导致实际赎回金额低于原始投入**
- 再平衡操作本身也有执行风险
- 建议先在Debug模式或Testnet环境测试
