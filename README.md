# aws-practice

Learning AWS by building a small full-stack app — frontend, backend, and database —
while keeping the bill at or near $0.

## Start here

1. **[Open an AWS account safely](docs/01-aws-account-setup.md)** — signup walkthrough,
   which plan to pick (the free tier changed in July 2025 and most tutorials are out of
   date), locking down the root user, billing alarms, and the cost traps that generate
   surprise bills.
2. **[Pick something to build](docs/02-app-ideas.md)** — the zero-cost serverless
   architecture, six project ideas with what each one teaches, and a build order.

## The stack

```
Browser → CloudFront → S3            (React frontend)
        → API Gateway → Lambda → DynamoDB   (backend + data)
```

Chosen so hobby-scale usage stays inside AWS's *always-free* monthly limits rather
than burning the expiring signup credits. See the app ideas doc for why each piece
was picked over the more conventional alternative.

## Status

- [x] Account setup guide
- [x] App idea shortlist
- [ ] Pick a project
- [ ] Deploy hello-world Lambda + API Gateway
- [ ] Add DynamoDB
- [ ] Build the API
- [ ] Build the frontend
- [ ] Deploy frontend to S3 + CloudFront
