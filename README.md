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

```
S3 (screenshots) → Bedrock vision → review screen → DynamoDB (positions)
EventBridge cron → Twelve Data → DynamoDB (prices) → compute → Bedrock → SES email
React on CloudFront → API Gateway → Lambda → DynamoDB
```

Runs at roughly **$0.35/month** — everything sits in AWS's always-free tier except
Bedrock inference.

Two design rules worth knowing before reading further:

- **Bedrock narrates computed facts; it never originates numbers or price opinions.**
  Deltas, weights, and concentration are calculated in Lambda first.
- **Screenshot extraction requires human confirmation** before it's committed. Vision
  models misread numbers, and a wrong cost basis corrupts everything downstream.

## Layout

```
template.yaml                     SAM stack - DynamoDB, S3, HTTP API, 3 Lambdas, schedule
layers/common/python/portfolio_common/
  analytics.py                    every number the brief may state (pure, no deps)
  db.py                           single-table DynamoDB access
  money.py                        Decimal/float at the storage boundary
src/api/                          positions CRUD + brief retrieval
src/fetch_prices/                 Twelve Data -> price history
src/analyze/
  app.py                          orchestration
  brief.py                        Bedrock narration over computed facts
tests/test_analytics.py           20 tests over the analytics core
```

## Status

- [x] Account setup guide
- [x] App idea shortlist
- [x] Project chosen — portfolio monitor
- [x] SAM stack — DynamoDB, S3, HTTP API, EventBridge schedule
- [x] Positions CRUD API
- [x] Price fetcher (Twelve Data)
- [x] Analysis core — deltas, weights, concentration, drift, outliers (20 tests)
- [x] Bedrock narration + SES email
- [ ] **AWS account open, budget alarm set** ← you are here
- [ ] First deploy
- [ ] Screenshot upload + Bedrock vision extraction + review screen
- [ ] React frontend on S3 + CloudFront

## Tests

```bash
pip install -r requirements-dev.txt && python -m pytest tests/ -q
```
