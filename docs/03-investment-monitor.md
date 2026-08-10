# Project — Portfolio Monitor

Upload screenshots of your brokerage holdings. Bedrock reads them into structured data.
A daily job pulls closing prices, computes what changed, and emails you a brief.

This replaces the shortlist in [`02-app-ideas.md`](./02-app-ideas.md) as the main
project. It's a bigger build, but it exercises more of AWS than any idea on that list:
multimodal inference, scheduled execution, an external data feed, and time-series
storage.

---

## Architecture

```
INGEST  (occasional — whenever you re-snapshot your holdings)

  Browser ──presigned PUT──► S3 (screenshots/)
                               │
                               │ ObjectCreated event
                               ▼
                            Lambda: extract
                               │
                               ├──► Bedrock (vision) ──► holdings JSON
                               ▼
                            DynamoDB (status: PENDING_REVIEW)
                               │
                               ▼
                       ┌───────────────────┐
                       │  REVIEW SCREEN    │  ◄── you confirm the parse
                       └───────────────────┘
                               │
                               ▼
                            DynamoDB (positions, status: CONFIRMED)


DAILY  (EventBridge cron — weekdays, after market close)

  EventBridge ──► Lambda: fetch-prices
                    │
                    ├──► Twelve Data API (batch quote, all tickers)
                    ▼
                  DynamoDB (price history, TTL 400 days)
                    │
                    ▼
                  Lambda: analyze
                    │
                    ├── compute in code: deltas, weights, concentration, drift
                    ├──► Bedrock (narrate the computed facts)
                    ▼
                  DynamoDB (daily brief)
                    │
                    └──► SES ──► your inbox


READ

  React (S3 + CloudFront) ──► API Gateway ──► Lambda ──► DynamoDB
```

---

## Design decisions

### Bedrock outputs observations, not directives

**The rule:** every number in the brief is computed in Lambda before Bedrock sees it.
Bedrock explains and prioritizes; it never originates a figure or a price opinion.

The reason is a property of how these models fail. Asked "what should I do with my
holdings," a model will always produce a fluent, confident, plausible answer — including
when it has no grounding for one. It has no live market data beyond what you pass it, no
view of your tax situation, risk tolerance, or time horizon, and no reliable signal that
it's uncertain. The output that's grounded and the output that's invented look identical.

So don't ask it that question. Ask it to narrate facts you derived yourself:

| Compute in Lambda (verifiable) | Ask Bedrock to do (what it's good at) |
|---|---|
| Day/week/month % change per holding | Explain which changes are worth attention |
| Position weight, and drift since last snapshot | Point out concentration that crept up |
| Sector breakdown by weight | Flag correlated exposure |
| Holdings that moved > 2σ from their 30-day norm | Summarize the day in plain language |
| Portfolio value vs. cost basis | Prioritize — what would you look at first? |

Sample of the shape you want out:

> NVDA is now **34%** of the portfolio, up from 22% at your last snapshot. The position
> itself only grew 8% — most of the concentration change came from selling PFE. Three
> holdings moved more than 5% today. By weight the portfolio is **81% technology**;
> those five names have historically moved together, so effective diversification is
> lower than "12 holdings" suggests.

Every claim there traces to a number computed upstream. Compare to what you'd get from
an ungrounded prompt — "trim NVDA and rotate into healthcare" — which reads just as
authoritative and is backed by nothing.

**Prompt shape:**

```
You are summarizing a portfolio's daily change for its owner.

FACTS (computed, authoritative — do not recalculate or contradict):
{positions_json}
{price_changes_json}
{concentration_json}

Write a brief (max 200 words) that:
- leads with the single most notable change
- flags concentration or correlation risk if the computed numbers show it
- notes anything unusual vs. the holding's own 30-day range

Do not recommend buying, selling, or holding. Do not state any number
not present in FACTS. Do not speculate about future prices.
If nothing is notable, say so plainly in one sentence.
```

That last line matters — without it you get manufactured drama on quiet days.

### Read-only. No broker integration.

No trade execution, no broker API, no write path to anything financial. The app reads
screenshots and prices, and emails you words. Keep it that way.

### Personal use

This is a personal tool for your own holdings, which is fine. If you ever open it to
other people, generating securities recommendations for others is a regulated activity
in most jurisdictions — a different project with different requirements.

### Extraction requires human confirmation

Vision models misread numbers — a `1` vs `7`, a misplaced decimal, a share count read
off the wrong row. A wrong cost basis silently corrupts every downstream calculation
indefinitely, and you would not notice for weeks.

So the flow is **extract → review → commit**, never extract → commit. Rows land in
DynamoDB as `PENDING_REVIEW`, the UI shows the parsed table beside the source screenshot,
you fix and approve, and only then does status become `CONFIRMED`. Have the model return
a per-field confidence and highlight anything low.

It's also the most interesting screen in the app to build.

---

## Data sources

### Market data — use Twelve Data

| Provider | Free tier | Verdict |
|---|---|---|
| Alpha Vantage | **25 requests/day** | Too tight — 20 tickers exhausts it |
| **Twelve Data** | **800 credits/day, 8 credits/minute**, batch symbols per call, 50+ exchanges | **Use this, with the caveat below** |
| Finnhub | 60 requests/min, free WebSocket | Good alternative; better if you later want intraday |

All free tiers delay quotes (15 min – 4 hrs). Irrelevant here — the job runs after close
against daily bars.

Twelve Data supports batching, so one call *can* cover the whole portfolio:

```
GET https://api.twelvedata.com/quote?symbol=AAPL,MSFT,NVDA&apikey=...
```

That's ~21 requests/month against an 800/day limit — enormous headroom.

**But the 800/day figure is not the binding limit; the 8/minute figure is.**
A batched `/quote` call costs **one credit per symbol**, not one credit total
— confirmed directly from a live 429 response: *"9 API credits were used,
with the current limit being 8."* Any portfolio over 8 tickers blows the
per-minute cap on a single batched call, every time, regardless of the daily
pool being nowhere close to exhausted. `src/fetch_prices/app.py` handles this
by splitting the symbol list into ≤8-symbol chunks and pausing ~61s between
them — free to do since this runs once a day on a schedule, not on a
user-facing request path. If you swap in a different provider, check for a
per-minute limit separately from any daily one; "requests/day" alone
undersells the real constraint.

**Store the key in SSM Parameter Store as a `SecureString`** — free. Secrets Manager
does the same job for $0.40/secret/month.

```bash
aws ssm put-parameter --name /portfolio/twelvedata/apikey \
  --value "YOUR_KEY" --type SecureString
```

### Bedrock model

Enable model access first: Bedrock console → **Model access** → request access. It's
near-instant for Claude and Nova, and it's per-region — do it in `us-east-1`.

| Model | In / Out per 1M tokens | Est. cost/month | Use |
|---|---|---|---|
| **Claude Haiku 4.5** | $1 / $5 | **~$0.35** | Recommended — good vision, good writing |
| Amazon Nova Lite | $0.06 / $0.24 | ~$0.02 | If you want it nearly free |
| Claude Sonnet 4.5 | higher | ~$3–5 | Overkill here |

Estimate assumes ~8k input + ~1.5k output tokens × ~21 trading days. Screenshot
extraction adds a few thousand vision tokens a handful of times a month — under a cent.

Bedrock has **no always-free tier**, so this is the one line item that costs money. At
~$0.35/month it fits comfortably in the $5 budget from
[`01-aws-account-setup.md`](./01-aws-account-setup.md). Using Bedrock also earns $20 of
the signup bonus credits.

---

## DynamoDB model

Single table, `PortfolioMonitor`:

| Entity | PK | SK | Attributes |
|---|---|---|---|
| Position | `USER#<id>` | `POS#<ticker>` | shares, costBasis, status, updatedAt |
| Price bar | `TICKER#<sym>` | `BAR#<yyyy-mm-dd>` | close, prevClose, changePct, `ttl` |
| Daily brief | `USER#<id>` | `BRIEF#<yyyy-mm-dd>` | text, totalValue, dayChangePct |
| Snapshot | `USER#<id>` | `SNAP#<ts>` | s3Key, status, extractedJson |

- Prices are a natural time series: partition by ticker, sort by date. Range queries
  ("last 30 bars for NVDA") are a single efficient `Query`.
- Set **TTL** on price bars (~400 days) so old data self-deletes and storage stays
  inside the free 25 GB permanently.
- Briefs and positions share the user partition, so one `Query` loads the dashboard.

---

## Cost summary

| Service | Monthly |
|---|---|
| Lambda | $0 — always-free tier |
| DynamoDB | $0 — always-free tier |
| S3 + CloudFront | $0 — well inside limits |
| API Gateway | $0 for first 12 months |
| EventBridge | $0 — scheduled rules are free |
| SES | $0 — free tier covers a daily email |
| SSM Parameter Store | $0 — Standard tier |
| Twelve Data | $0 — free tier |
| **Bedrock** | **~$0.35** |
| **Total** | **~$0.35/month** |

---

## Build order

Deploy at every step. Don't build it all locally and meet AWS on day five.

1. **Hello-world Lambda + API Gateway** via SAM. Curl it.
2. **DynamoDB + positions CRUD.** Enter two holdings by hand via the API. No frontend,
   no Bedrock — just prove the data layer.
3. **Price fetcher.** Lambda calls Twelve Data with a hardcoded ticker list, writes bars.
   Invoke manually (`sam remote invoke`) until it's right.
4. **EventBridge schedule.** Put step 3 on a cron. Confirm it fires overnight.
   Weekdays only: `cron(0 21 ? * MON-FRI *)` — 21:00 UTC ≈ 5pm ET.
5. **Analysis Lambda — computed facts only, no Bedrock yet.** Deltas, weights,
   concentration. Print JSON to logs. This is the actual core of the app; get the
   numbers right before any prose is layered on.
6. **Add Bedrock narration** over step 5's output. Compare briefs against the raw JSON
   for a week to confirm it isn't drifting from the facts.
7. **SES email.** Verify your address first (sandbox mode only sends to verified
   addresses — fine, you're the only recipient).
8. **React frontend**, local, pointed at the deployed API. Fix CORS here.
9. **Screenshot upload** — presigned S3 PUT, extraction Lambda, review screen.
10. **Deploy frontend** to S3 + CloudFront.
11. **Set CloudWatch log retention to 7 days** on every log group.

Steps 1–5 are the real learning. Bedrock is genuinely the easy part — a single
`InvokeModel` call — and it's worth resisting the urge to start there.

---

## What this teaches

- S3 presigned uploads + event-triggered Lambda
- Bedrock multimodal (image → structured JSON) and text generation
- Grounding an LLM against computed facts instead of letting it free-associate
- EventBridge scheduled execution
- Third-party API integration + secret handling via Parameter Store
- DynamoDB time-series modeling, GSIs, and TTL
- Transactional email via SES
- React with a genuine review/approval workflow
