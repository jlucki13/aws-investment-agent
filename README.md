# aws-practice

Learning AWS by building a small full-stack app — frontend, backend, and database —
while keeping the bill at or near $0.

## Start here

1. **[Open an AWS account safely](docs/01-aws-account-setup.md)** — signup walkthrough,
   which plan to pick (the free tier changed in July 2025 and most tutorials are out of
   date), locking down the root user, billing alarms, and the cost traps that generate
   surprise bills.
2. **[Background: app ideas + the stack](docs/02-app-ideas.md)** — the zero-cost
   serverless architecture and why each service was picked over the conventional
   alternative.
3. **[The project: Portfolio Monitor](docs/03-investment-monitor.md)** — what we're
   actually building.
4. **[Deploying](docs/04-deploy.md)** — prerequisites, `sam deploy`, smoke tests,
   teardown.

## The project

Upload screenshots of your brokerage holdings. Bedrock reads them into structured
data. A daily job pulls closing prices, computes what changed, and emails you a brief.
Live and running on a real portfolio.

```
S3 (screenshots) → Bedrock vision → review screen → DynamoDB (positions)
EventBridge cron → Twelve Data → DynamoDB (prices) → compute → Bedrock → SES email
React on CloudFront → API Gateway → Lambda → DynamoDB
```

Runs at roughly **$0.35/month** — everything sits in AWS's always-free tier except
Bedrock inference.

Two design rules worth knowing before reading further:

- **Bedrock narrates computed facts and suggests actions grounded in them; it
  never originates numbers.** Deltas, weights, and concentration are calculated
  in Lambda first, and every buy/sell/hold/rebalance suggestion in the brief
  must cite one of those pre-computed figures.
- **Screenshot extraction requires human confirmation** before it's committed. Vision
  models misread numbers, and a wrong cost basis corrupts everything downstream.

## Layout

```
template.yaml                     SAM stack - DynamoDB, S3 x2, HTTP API, CloudFront,
                                   Step Functions, EventBridge schedule, 4 Lambdas
layers/common/python/portfolio_common/
  analytics.py                    every number the brief may state (pure, no deps)
  snapshots.py                    screenshot key handling + vision-response parsing (pure)
  db.py                           single-table DynamoDB access
  money.py                        Decimal/float at the storage boundary
src/api/                          positions + snapshots CRUD, brief retrieval
src/fetch_prices/                 Twelve Data -> price history (paced, self-healing on 429)
src/extract_screenshot/           S3-triggered Bedrock vision extraction
src/analyze/
  app.py                          orchestration
  brief.py                        Bedrock narration over computed facts
frontend/                         React (Vite) - dashboard, positions, screenshot review
tests/                            47 tests across analytics, snapshots, routing, pacing
```

## Status

Deployed and running on a real brokerage portfolio (9 live positions).

- [x] Account setup, budget alarm, SAM/CLI tooling
- [x] Deployed — DynamoDB, S3, HTTP API, EventBridge schedule
- [x] Positions CRUD API
- [x] Price fetcher (Twelve Data) — paced one-symbol-per-request with 429 recovery,
      after batching turned out not to work the way the provider's own docs claimed
- [x] Analysis core — deltas, weights, concentration, drift, outliers
- [x] Bedrock narration — grounded in computed facts only
- [x] Screenshot upload → Bedrock vision extraction → human review → confirm
      — tested end to end against a real Schwab screenshot
- [x] React frontend — dashboard, positions manager, screenshot review
- [x] Frontend hosting — S3 + CloudFront (OAC), `frontend/deploy.sh` / `deploy.ps1`
      publishes `frontend/dist/`; run it and note the live `FrontendUrl` here
- [ ] SES daily email — send call succeeds (`brief emailed to ...` in the logs),
      not yet confirmed as actually landing in the inbox — under investigation
- [ ] Real cost basis on the 9 positions pulled in before the extraction fix
      (they currently hold price-as-cost-basis from the earlier bug)

## Tests

```bash
pip install -r requirements-dev.txt && python -m pytest tests/ -q
```

47 tests: analytics (every figure the brief may state), snapshot key handling and
vision-response parsing, API routing (including a regression test for a router bug
that shipped in the first deploy), and Twelve Data request pacing.
