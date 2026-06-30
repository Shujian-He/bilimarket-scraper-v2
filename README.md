# Bilibili Market Scraper v2

[English README](README.md) | [中文 README](README.zh.md)

## Overview

**Bilibili Market Scraper v2** is a standalone Python scraper for Bilibili C2C
market listings. It fetches listing pages from the market API, filters by
price, discount and category, stores every parsed listing, and separately keeps
the listings whose names match your wanted keywords.

This v2 rewrite is focused on safer long-running collection:

- Resumable runs with a per-run `state.json` checkpoint.
- Bounded HTTP retries for network errors, HTTP 429 and HTTP 5xx.
- CSV and SQLite output written under one run directory.
- Checkpoint updates only after a page has been persisted.
- Polite default delays between requests and longer pauses during long runs.

## Project Structure

```text
├── bilimarket_scraper/        # Python package
│   ├── __main__.py            # Enables: python3 -m bilimarket_scraper
│   ├── auth.py                # Cookie loading and request headers
│   ├── cli.py                 # Command line interface
│   ├── client.py              # Market API HTTP client and retries
│   ├── config.py              # API URL, defaults and supported filters
│   ├── models.py              # Request, page and listing models
│   ├── rate_limit.py          # Delay policy
│   ├── runner.py              # Fetch, persist and checkpoint loop
│   └── storage.py             # CSV, SQLite and state.json storage
├── cookies.example.txt        # Placeholder cookie template
├── cookies.txt                # Your real cookie file, ignored by Git
├── pyproject.toml             # Package metadata and CLI entry point
├── requirements.txt           # Runtime dependencies
└── runs/                      # Generated output directory, ignored by Git
```

## Installation

### 1. Clone The Repository

```bash
git clone https://github.com/Shujian-He/bilimarket-scraper-v2.git
cd bilimarket-scraper-v2
```

### 2. Create A Virtual Environment

```bash
python3 -m venv .venv
. .venv/bin/activate
```

### 3. Install Dependencies

For running from source:

```bash
python3 -m pip install -r requirements.txt
```

The examples below use:

```bash
PYTHONPATH=. python3 -m bilimarket_scraper
```

## Cookies

The scraper needs your Bilibili authentication cookie to access the market API.
It reads the cookie from `cookies.txt` in this repository root.

Create the local cookie file:

```bash
cp cookies.example.txt cookies.txt
```

Open `cookies.txt` and replace the placeholder value with the cookie string from
your browser. `cookies.txt` is ignored by Git, so your real cookie stays local.

You can obtain the cookie from browser developer tools:

1. Log in to [Bilibili](https://www.bilibili.com/), then open the
   [Bilibili market page](https://mall.bilibili.com/neul-next/index.html?page=magic-market_index).
2. Open developer tools and switch to the **Network** tab.
3. Refresh the page.
4. Select the market `list` request.
5. In **Headers** - **Request Headers**, copy everything after `Cookie:`.

The scraper never prints the cookie value.

## Usage

Run a small one-page probe first:

```bash
PYTHONPATH=. python3 -m bilimarket_scraper \
  --category 2312 \
  --price 20000-0 \
  --discount 70-100 \
  --max-pages 1
```

Run with wanted keywords:

```bash
PYTHONPATH=. python3 -m bilimarket_scraper \
  --want 千早爱音 \
  --price 10000-20000 20000-0 \
  --discount 50-70 70-100 \
  --category 2312 \
  --max-pages 5
```

When the run ends, the CLI prints a summary similar to:

```text
Scrape ended: status=max_pages, pages=5, listings=100, matches=3, run_dir=runs/20260627-220000
```

Use `--max-pages` for controlled batches. Without it, the scraper continues
until the API has no next cursor, you interrupt it, or an error stops the run.

## Arguments

- `--want`: Zero or more wanted keywords. Matching is case-insensitive and
  checks whether a keyword appears in the listing name. If omitted,
  `matches.csv` is created with only a header row.
- `--price`: One or more supported price filters in cents. Default:
  `10000-20000 20000-0`.
- `--discount`: One or more supported discount filters. Default:
  `0-30 30-50 50-70 70-100`.
- `--category`: One category id, or blank for all categories. Default: blank.
- `--run-id`: Optional run directory name under `runs`.
- `--resume-dir`: Existing run directory to resume from.
- `--max-pages`: Stop after this many fetched pages in the current command.
- `--min-delay`: Minimum delay before each request. Default: `1.2`.
- `--max-delay`: Maximum delay before each request. Default: `2.8`.
- `--long-pause-every`: Take a longer pause after this many pages. Default:
  `50`.
- `--long-pause-seconds`: Long pause duration. Default: `45.0`.
- `--no-sleep`: Disable scraper sleeps. Use only for local tests or a small
  manual probe.

### Supported Price Filters

| Value | Meaning |
| - | - |
| `0-2000` | 0 to 20 RMB |
| `2000-3000` | 20 to 30 RMB |
| `3000-5000` | 30 to 50 RMB |
| `5000-10000` | 50 to 100 RMB |
| `10000-20000` | 100 to 200 RMB |
| `20000-0` | 200 RMB and above |

### Supported Discount Filters

| Value | Meaning |
| - | - |
| `0-30` | 0% to 30% price-ratio bucket |
| `30-50` | 30% to 50% price-ratio bucket |
| `50-70` | 50% to 70% price-ratio bucket |
| `70-100` | 70% to 100% price-ratio bucket |

### Supported Categories

| Value | Meaning |
| - | - |
| blank | All categories |
| `2312` | Figure |
| `2066` | Model |
| `2331` | Merch |
| `2273` | 3C |
| `fudai_cate_id` | Fudai |

The CLI validates price, discount and category values before sending a request.
Unsupported filters fail fast instead of producing confusing empty output.

## Resume A Run

Each run writes a checkpoint to `state.json` after a page has been saved to CSV
and SQLite. To continue a previous run:

```bash
PYTHONPATH=. python3 -m bilimarket_scraper \
  --resume-dir runs/<run-id> \
  --max-pages 5
```

When resuming, the CLI loads wanted keywords, price filters, discount filters,
category, cursor, and counters from `state.json`. Passing `--want`, `--price`,
`--discount`, or `--category` together with `--resume-dir` fails fast so a run
cannot accidentally continue with a mismatched cursor and filter set.

## Output

Every run gets its own directory under `runs/`, for example:

```text
runs/20260627-220000/
├── listings.csv
├── matches.csv
├── market.sqlite3
├── market.sqlite3-shm
├── market.sqlite3-wal
└── state.json
```

### CSV Files

`listings.csv` contains all parsed listings. `matches.csv` contains only
listings whose `name` contains one of the `--want` keywords.

Both CSV files have a header row:

| Column | Description |
| - | - |
| `captured_at` | UTC timestamp when the page was parsed |
| `listing_id` | Bilibili C2C listing id |
| `name` | Listing name |
| `current_price` | Current price in cents |
| `market_price` | Sum of original market prices in cents, if available |
| `discount` | `current_price / market_price`, if available |
| `item_count` | Number of items in the listing, if available |
| `seller_uid` | Seller user id, if available |
| `seller_name` | Seller display name, if available |
| `payment_time` | Payment time from the API, if available |
| `detail_count` | Number of detail records in the API item |

### SQLite Database

`market.sqlite3` stores the latest version of each listing by `listing_id`.

| Column | Type | Description |
| - | - | - |
| `listing_id` | TEXT | Primary key |
| `name` | TEXT | Listing name |
| `current_price` | INTEGER | Current price in cents |
| `market_price` | INTEGER | Original market price in cents, if available |
| `discount` | REAL | `current_price / market_price`, if available |
| `seller_uid` | TEXT | Seller user id, if available |
| `seller_name` | TEXT | Seller display name, if available |
| `item_count` | INTEGER | Number of items in the listing, if available |
| `payment_time` | TEXT | Payment time from the API, if available |
| `detail_count` | INTEGER | Number of detail records in the API item |
| `captured_at` | TEXT | UTC timestamp when the page was parsed |
| `raw_json` | TEXT | Full normalized API item JSON |

SQLite WAL sidecar files such as `market.sqlite3-shm` and
`market.sqlite3-wal` may appear while the database is open.

### Checkpoint

`state.json` records:

- `next_id`: Cursor for the next page, or `null` at the end.
- `pages_written`: Number of pages saved in this run directory.
- `listings_written`: Number of listing rows appended to CSV.
- `wanted_keywords`: Keywords used for `matches.csv`.
- `query`: Price, discount, category and sort values used for the run.
- `updated_at`: UTC checkpoint update timestamp.

## Request Failures And Retries

- Network exceptions, timeouts, HTTP 429 and HTTP 5xx responses are retried up
  to 4 attempts.
- HTTP 429 uses the server's `Retry-After` value when present.
- Other non-200 responses fail immediately with a short response preview.
- Malformed JSON, malformed API payloads and non-advancing cursors fail with a
  clear error.
- `state.json` is updated only after a complete page has been written to CSV
  and SQLite.
- Pressing `Ctrl+C` stops the process after the current operation boundary; the
  last completed page remains checkpointed.

## Use A Listing ID

You can open a listing detail page by replacing
`<REPLACE_THIS_WITH_LISTING_ID>` with a value from `listing_id`:

```text
https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId=<REPLACE_THIS_WITH_LISTING_ID>&from=market_index
```

Example:

```text
https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId=142389472138&from=market_index
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for
details.

## Acknowledgments

Thanks to [Codex](https://chatgpt.com/codex/) for assistance with the v2 rewrite and documentation.
