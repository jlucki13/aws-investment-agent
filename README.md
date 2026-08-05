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

## Status

- [x] Account setup guide
- [x] App idea shortlist
- [x] Project chosen — portfolio monitor
- [ ] AWS account open, budget alarm set
- [ ] Hello-world Lambda + API Gateway
- [ ] DynamoDB + positions CRUD
- [ ] Price fetcher (Twelve Data)
- [ ] EventBridge daily schedule
- [ ] Analysis Lambda — computed facts
- [ ] Bedrock narration
- [ ] SES email
- [ ] React frontend
- [ ] Screenshot upload + review screen
- [ ] Deploy frontend to S3 + CloudFront
