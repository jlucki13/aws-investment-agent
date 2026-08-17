# Deploying

Assumes you've finished [`01-aws-account-setup.md`](./01-aws-account-setup.md) —
account open, IAM user with MFA, `aws sts get-caller-identity` working, budget alarm
set, SAM CLI installed.

Everything below is `us-east-1`.

---

## One-time prerequisites

### 1. Twelve Data API key

Sign up free at <https://twelvedata.com/pricing> (800 credits/day — but see the note
below, the real constraint for portfolios over 8 tickers is **8 credits/minute**, not
the daily figure). Then store the key in Parameter Store — **free**, unlike Secrets
Manager at $0.40/secret/month:

```bash
aws ssm put-parameter \
  --name /portfolio/twelvedata/apikey \
  --value "YOUR_KEY_HERE" \
  --type SecureString \
  --region us-east-1
```

Verify:

```bash
aws ssm get-parameter --name /portfolio/twelvedata/apikey \
  --with-decryption --query Parameter.Value --output text
```

### 2. Bedrock model access

Model access is opt-in per region and per model, and deploys will fail with
`AccessDeniedException` without it.

1. Console → **Bedrock** → **Model access** (left sidebar, bottom)
2. **Modify model access** → check the Anthropic Claude models → Submit
3. Approval is usually instant

Then confirm the inference profile ID:

```bash
aws bedrock list-inference-profiles --region us-east-1 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId,'haiku')].inferenceProfileId" \
  --output table
```

Newer Claude models are only callable through a regional inference profile (the `us.`
prefix), not the bare model ID. Whatever that command prints is what belongs in
`BedrockModelId`. If it differs from the template default, pass it at deploy time.

### 3. SES email verification

The daily brief is emailed. New accounts are in the SES sandbox, which only sends to
verified addresses — fine here, since you're the only recipient.

```bash
aws ses verify-email-identity --email-address you@example.com --region us-east-1
```

Click the confirmation link in your inbox. Leave `AlertEmail` blank at deploy time to
skip email entirely; briefs still land in DynamoDB.

---

## Deploy

```bash
cp samconfig.toml.example samconfig.toml   # then edit AlertEmail
sam build
sam deploy --guided                        # first time only
```

Subsequent deploys are just:

```bash
sam build && sam deploy
```

Save the `ApiUrl` from the outputs:

```bash
export API=$(aws cloudformation describe-stacks --stack-name portfolio-monitor \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
echo $API
```

---

## Frontend (S3 + CloudFront)

`sam deploy` above already creates the hosting infrastructure — a private S3 bucket
(`FrontendBucket`) and a CloudFront distribution in front of it, reached through an
Origin Access Control so the bucket itself stays fully private. That's the same
`template.yaml` change as any other; nothing new to run for it.

What `sam deploy` does *not* do is put your built frontend files into that bucket —
CloudFormation manages infrastructure, not file contents, and SAM has no equivalent of
CDK's asset-bundling step for this. That's what `frontend/deploy.sh` (or
`frontend/deploy.ps1` on Windows) is for. It looks up the bucket name and distribution
ID from the stack itself (no hardcoded values to go stale), so it keeps working even if
the stack is ever recreated:

```bash
cd frontend
./deploy.sh
```

```powershell
cd frontend
.\deploy.ps1
```

Either script: runs `npm run build`, syncs `dist/` to the bucket with `--delete` (so
removed files don't linger), invalidates the CloudFront cache, and prints the live
`FrontendUrl` at the end.

**A freshly created distribution can take several minutes to finish propagating to all
edge locations.** If you hit the URL right after the first `sam deploy` and get a 404 or
a CloudFront error page, that's very likely just propagation still in progress, not a
broken deploy — wait a few minutes and reload before assuming something's wrong. (This
project's history is full of "is this actually broken or does it just need more time"
moments — the Twelve Data pacing above is another one. This is the same kind of thing.)

You can also pull the URL directly, same pattern as `ApiUrl` above:

```bash
aws cloudformation describe-stacks --stack-name portfolio-monitor \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendUrl'].OutputValue" --output text
```

Re-run the deploy script any time frontend source changes — it's the only step that
needs repeating; the S3/CloudFront infrastructure only needs `sam deploy` again if
`template.yaml` itself changes.

---

## Smoke test, in the order things were built

### Positions API

```bash
curl -s -X PUT "$API/positions/AAPL" \
  -H 'content-type: application/json' \
  -d '{"shares": 25, "costBasis": 180.50}' | jq

curl -s -X PUT "$API/positions/MSFT" \
  -H 'content-type: application/json' \
  -d '{"shares": 10, "costBasis": 390.00}' | jq

curl -s "$API/positions" | jq
```

### Price fetch

```bash
sam remote invoke FetchPricesFunction --stack-name portfolio-monitor
```

Expect `{"fetched": 2, "symbols": ["AAPL","MSFT"], "errors": []}`. A non-empty `errors`
array usually means a bad API key (Twelve Data returns that as HTTP 200 with an error
body, which the fetcher checks for explicitly) or a bad/delisted symbol.

**A rate limit is different: it surfaces as a genuine HTTP 429**, not a 200. Twelve
Data's free "Basic 8" plan caps at 8 API credits/minute. The fetcher does **not** batch
multiple symbols into one `/quote` call — an earlier version did, on the assumption
(straight from Twelve Data's own docs) that batching cost one credit per symbol, but a
live 429 proved that wrong: a verified 5-symbol batched call still came back "9 credits
used, limit 8," while a single-symbol call succeeded cleanly. So it fetches **one symbol
per request**, paced 12 seconds apart. That means a run takes noticeably longer than a
single instant call — roughly two minutes for a 9-ticker portfolio — which is expected,
not a hang. If you invoke manually and it seems to sit there for a while, that's the
pacing, not a stuck function.

### Analysis + brief

```bash
sam remote invoke AnalyzeFunction --stack-name portfolio-monitor
curl -s "$API/briefs/latest" | jq -r .text
```

On the first run you'll likely get the quiet-day line, because a single bar gives no
day-over-day change. Run the fetcher again the next trading day and it becomes real.

### The schedule

The Step Functions pipeline fires weekdays at 22:00 UTC (6pm EDT / 5pm EST). To test
without waiting:

```bash
aws stepfunctions start-execution \
  --state-machine-arn $(aws cloudformation describe-stack-resources \
    --stack-name portfolio-monitor \
    --logical-resource-id DailyPipeline \
    --query "StackResources[0].PhysicalResourceId" --output text)
```

---

## Watching it

```bash
sam logs --stack-name portfolio-monitor --name AnalyzeFunction --tail
```

Token usage is logged on every Bedrock call (`bedrock tokens in=... out=...`) so you can
see the real cost rather than trusting the estimate.

---

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

The analytics tests are the ones that matter. Bedrock will narrate whatever numbers it's
given in equally confident prose, so a wrong weight produces a wrong-but-persuasive
brief with nothing downstream to catch it. Keep them green.

---

## Tearing down

```bash
sam delete --stack-name portfolio-monitor
```

The S3 bucket must be empty first if you've uploaded screenshots:

```bash
aws s3 rm s3://portfolio-monitor-screenshots-<account-id> --recursive
```

Then check for orphans — log groups and buckets outlive most stack deletions.

---

## Cost check after a week

```bash
aws ce get-cost-and-usage \
  --time-period Start=$(date -u -d '7 days ago' +%Y-%m-%d),End=$(date -u +%Y-%m-%d) \
  --granularity DAILY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[].Groups[?Metrics.UnblendedCost.Amount!=`0`]' 
```

Expect Bedrock to be the only non-zero line, at roughly a cent a day. Anything else
appearing is worth investigating immediately.

---

## Not built yet

- **Screenshot ingestion** — the S3 bucket and its CORS config are deployed, but the
  presigned-upload endpoint, the Bedrock vision extraction Lambda, and the review screen
  aren't written. Positions go in through the API for now.

The React frontend itself is built and now has a real hosting path (S3 + CloudFront,
see above) — what's still manual is running `frontend/deploy.sh`/`deploy.ps1` yourself
after source changes, since CloudFormation doesn't watch the filesystem for you.
