# Bilibili Market Scraper v2

A standalone, polite, resumable scraper for Bilibili C2C market listings.

## Install

From this repository root:

```bash
python3 -m pip install -r requirements.txt
```

## Cookies

Copy the example cookie file, then replace the placeholder values with your
browser cookie string:

```bash
cp cookies.example.txt cookies.txt
```

`cookies.txt` is ignored by Git so real cookies stay local. The scraper reads
`BILI_COOKIE` first, then falls back to `cookies.txt` in this repository root.
It never prints the cookie value.

## Run A One-Page Probe

From this repository root:

```bash
PYTHONPATH=. python3 -m bilimarket_scraper \
  --category 2312 \
  --price 20000-0 \
  --discount 70-100 \
  --max-pages 1
```

## Output

Each run gets its own directory under `runs/`:

- `listings.csv`: all parsed listings with a header row
- `matches.csv`: listings whose name contains one of the `--want` keywords
- `market.sqlite3`: upserted listing table
- `state.json`: cursor checkpoint written after each persisted page

## Resume

```bash
PYTHONPATH=. python3 -m bilimarket_scraper \
  --resume-dir runs/<run-id> \
  --max-pages 5
```

Use `--max-pages` for controlled batches. The defaults intentionally sleep
between pages and take a longer pause after every 50 pages.
