# B站市集爬虫 v2

[English README](README.md) | [中文 README](README.zh.md)

## 概述

**B站市集爬虫 v2** 是一个独立的 Python 爬虫，用于抓取 Bilibili C2C 市集
商品列表。它会从市集 API 获取商品分页，按价格、折扣和类别筛选，保存所有
解析成功的商品，并单独保存名称命中关键词的商品。

v2 版本重点加强了长时间采集时的可靠性：

- 每次运行都有独立的 `state.json` checkpoint，可中断续跑。
- 网络错误、HTTP 429 和 HTTP 5xx 会进行有限次数重试。
- CSV 与 SQLite 输出都写入同一个 run 目录。
- 只有当一整页已经写入 CSV 和 SQLite 后，才会更新 checkpoint。
- 默认在请求之间等待，并在长批次中定期长暂停，避免过于激进。

## 项目结构

```text
├── bilimarket_scraper/        # Python 包
│   ├── __main__.py            # 支持 python3 -m bilimarket_scraper
│   ├── auth.py                # Cookie 读取和请求头构造
│   ├── cli.py                 # 命令行入口
│   ├── client.py              # 市集 API HTTP 客户端和重试逻辑
│   ├── config.py              # API 地址、默认值和支持的筛选项
│   ├── models.py              # 请求、分页和商品模型
│   ├── rate_limit.py          # 延迟策略
│   ├── runner.py              # 抓取、保存和 checkpoint 主循环
│   └── storage.py             # CSV、SQLite 和 state.json 存储
├── cookies.example.txt        # Cookie 占位模板
├── cookies.txt                # 你的真实 Cookie 文件，被 Git 忽略
├── pyproject.toml             # 包元数据和 CLI 入口配置
├── requirements.txt           # 运行依赖
└── runs/                      # 运行输出目录，被 Git 忽略
```

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/Shujian-He/bilimarket-scraper-v2.git
cd bilimarket-scraper-v2
```

### 2. 创建虚拟环境

```bash
python3 -m venv .venv
. .venv/bin/activate
```

### 3. 安装依赖

从源码目录运行时，安装运行依赖即可：

```bash
python3 -m pip install -r requirements.txt
```

下文示例使用：

```bash
PYTHONPATH=. python3 -m bilimarket_scraper
```

## Cookies

爬虫需要使用你的 Bilibili 登录 Cookie 访问市集 API。Cookie 读取顺序如下：

1. 环境变量 `BILI_COOKIE`。
2. 仓库根目录下的 `cookies.txt`。

使用本地 Cookie 文件时，先复制模板：

```bash
cp cookies.example.txt cookies.txt
```

然后打开 `cookies.txt`，把占位内容替换为浏览器里的 Cookie 字符串。
`cookies.txt` 已经被 Git 忽略，所以真实 Cookie 会留在本地，不会被提交。

可以通过浏览器开发者工具获取 Cookie：

1. 登录 [Bilibili](https://www.bilibili.com/)，然后打开
   [B站市集页面](https://mall.bilibili.com/neul-next/index.html?page=magic-market_index)。
2. 打开开发者工具，切换到 **Network** 标签。
3. 刷新页面。
4. 选择市集的 `list` 请求。
5. 在 **Headers** - **Request Headers** 中，复制 `Cookie:` 后面的全部内容。

爬虫不会打印 Cookie 值。

## 使用方法

建议先运行一个只抓一页的小批次：

```bash
PYTHONPATH=. python3 -m bilimarket_scraper \
  --category 2312 \
  --price 20000-0 \
  --discount 70-100 \
  --max-pages 1
```

带关键词运行：

```bash
PYTHONPATH=. python3 -m bilimarket_scraper \
  --want 千早爱音 \
  --price 10000-20000 20000-0 \
  --discount 50-70 70-100 \
  --category 2312 \
  --max-pages 5
```

运行结束时，CLI 会输出类似下面的摘要：

```text
Scrape ended: status=max_pages, pages=5, listings=100, matches=3, run_dir=runs/20260627-220000
```

建议使用 `--max-pages` 控制批次大小。如果不传，爬虫会一直运行到 API 没有
下一页、你手动中断，或遇到错误停止。

## 参数说明

- `--want`：零个或多个想要匹配的关键词。匹配时不区分大小写，只要关键词
  出现在商品名称中即可。未传时，`matches.csv` 只会包含表头。
- `--price`：一个或多个支持的价格筛选项，单位为分。默认：
  `10000-20000 20000-0`。
- `--discount`：一个或多个支持的折扣筛选项。默认：
  `0-30 30-50 50-70 70-100`。
- `--category`：一个类别 id，留空表示全部类别。默认留空。
- `--run-id`：可选的 run 目录名，会创建在 `runs` 下。
- `--resume-dir`：已有 run 目录，用于中断续跑。
- `--max-pages`：当前命令最多抓取多少页。
- `--min-delay`：每次请求前的最短等待时间。默认：`1.2`。
- `--max-delay`：每次请求前的最长等待时间。默认：`2.8`。
- `--long-pause-every`：每抓取多少页后进行一次长暂停。默认：`50`。
- `--long-pause-seconds`：长暂停秒数。默认：`45.0`。
- `--no-sleep`：禁用等待。仅建议在本地测试或小规模手动探测时使用。

### 支持的价格筛选项

| 值 | 含义 |
| - | - |
| `0-2000` | 0 至 20 元 |
| `2000-3000` | 20 至 30 元 |
| `3000-5000` | 30 至 50 元 |
| `5000-10000` | 50 至 100 元 |
| `10000-20000` | 100 至 200 元 |
| `20000-0` | 200 元以上 |

### 支持的折扣筛选项

| 值 | 含义 |
| - | - |
| `0-30` | 0% 至 30% 的价格比例区间 |
| `30-50` | 30% 至 50% 的价格比例区间 |
| `50-70` | 50% 至 70% 的价格比例区间 |
| `70-100` | 70% 至 100% 的价格比例区间 |

### 支持的商品类别

| 值 | 含义 |
| - | - |
| 留空 | 全部类别 |
| `2312` | 手办 |
| `2066` | 模型 |
| `2331` | 周边 |
| `2273` | 3C 数码 |
| `fudai_cate_id` | 福袋 |

CLI 会在发起请求前校验价格、折扣和类别。如果传入不支持的值，程序会直接报错，
而不是生成令人困惑的空结果。

## 中断续跑

每次成功保存一页后，爬虫都会把 checkpoint 写入 `state.json`。继续之前的
run 时：

```bash
PYTHONPATH=. python3 -m bilimarket_scraper \
  --resume-dir runs/<run-id> \
  --max-pages 5
```

续跑时，CLI 会从 `state.json` 读取想要匹配的关键词、价格筛选、折扣筛选、
类别、游标和计数信息。`--resume-dir` 不能和 `--want`、`--price`、
`--discount` 或 `--category` 同时使用；如果传入这些参数，程序会直接报错，
避免用不匹配的游标和筛选条件继续抓取。

## 输出文件

每次运行都会在 `runs/` 下生成一个独立目录，例如：

```text
runs/20260627-220000/
├── listings.csv
├── matches.csv
├── market.sqlite3
├── market.sqlite3-shm
├── market.sqlite3-wal
└── state.json
```

### CSV 文件

`listings.csv` 包含所有解析成功的商品。`matches.csv` 只包含 `name` 命中
`--want` 关键词的商品。

两个 CSV 文件都有表头：

| 列名 | 说明 |
| - | - |
| `captured_at` | 解析该页时的 UTC 时间戳 |
| `listing_id` | Bilibili C2C 商品列表 id |
| `name` | 商品名称 |
| `current_price` | 当前价格，单位为分 |
| `market_price` | 原始市价合计，单位为分；接口无数据时为空 |
| `discount` | `current_price / market_price`；无法计算时为空 |
| `item_count` | 商品数量；接口无数据时为空 |
| `seller_uid` | 卖家用户 id；接口无数据时为空 |
| `seller_name` | 卖家昵称；接口无数据时为空 |
| `payment_time` | 接口返回的支付时间；接口无数据时为空 |
| `detail_count` | API item 中的详情记录数量 |

### SQLite 数据库

`market.sqlite3` 会按 `listing_id` 保存每个商品的最新版本。

| 列名 | 类型 | 说明 |
| - | - | - |
| `listing_id` | TEXT | 主键 |
| `name` | TEXT | 商品名称 |
| `current_price` | INTEGER | 当前价格，单位为分 |
| `market_price` | INTEGER | 原始市价，单位为分；接口无数据时为空 |
| `discount` | REAL | `current_price / market_price`；无法计算时为空 |
| `seller_uid` | TEXT | 卖家用户 id；接口无数据时为空 |
| `seller_name` | TEXT | 卖家昵称；接口无数据时为空 |
| `item_count` | INTEGER | 商品数量；接口无数据时为空 |
| `payment_time` | TEXT | 接口返回的支付时间；接口无数据时为空 |
| `detail_count` | INTEGER | API item 中的详情记录数量 |
| `captured_at` | TEXT | 解析该页时的 UTC 时间戳 |
| `raw_json` | TEXT | 标准化后的完整 API item JSON |

数据库打开期间可能会出现 `market.sqlite3-shm` 和 `market.sqlite3-wal` 这样的
SQLite WAL 辅助文件。

### Checkpoint

`state.json` 记录：

- `next_id`：下一页游标；到达末尾时为 `null`。
- `pages_written`：当前 run 目录内已保存的页数。
- `listings_written`：已追加到 CSV 的商品行数。
- `wanted_keywords`：用于写入 `matches.csv` 的匹配关键词。
- `query`：本次运行的价格、折扣、类别和排序参数。
- `updated_at`：UTC checkpoint 更新时间。

## 请求失败与重试

- 网络异常、超时、HTTP 429 和 HTTP 5xx 最多重试 4 次。
- HTTP 429 如果带有 `Retry-After`，会优先使用服务器指定的等待时间。
- 其他非 200 响应会立即失败，并显示简短响应预览。
- JSON 格式错误、API 数据结构异常、游标不前进都会显示明确错误并停止。
- `state.json` 只会在完整页面已经写入 CSV 和 SQLite 后更新。
- 按 `Ctrl+C` 中断时，最后一页成功保存的数据仍然保留在 checkpoint 中。

## 使用商品 ID

你可以用 `listing_id` 打开对应的商品详情页。把下面 URL 中的
`<REPLACE_THIS_WITH_LISTING_ID>` 替换成具体商品 ID：

```text
https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId=<REPLACE_THIS_WITH_LISTING_ID>&from=market_index
```

例如：

```text
https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId=142389472138&from=market_index
```

## 许可证

本项目基于 MIT 许可证发布。详情请查看 [LICENSE](LICENSE)。

## 致谢

感谢 [Codex](https://chatgpt.com/codex/) 协助完成 v2 重写和文档整理。
