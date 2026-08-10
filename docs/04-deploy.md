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
Data's free tier caps at 8 API credits/minute, and a batched `/quote` call costs one
credit per symbol — so once your portfolio passes 8 tickers, `sam remote invoke
FetchPricesFunction` (and the real scheduled run) automatically splits the fetch into
≤8-symbol chunks with a ~61s pause between them. That means a run over 8 tickers takes
noticeably longer than one under 8 — expected, not a hang. If you invoke manually and
it seems to sit there for a minute, that's the pause, not a stuck function.

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

Steps 9–10 from the project plan:

- **Screenshot ingestion** — the S3 bucket and its CORS config are deployed, but the
  presigned-upload endpoint, the Bedrock vision extraction Lambda, and the review screen
  aren't written. Positions go in through the API for now.
- **React frontend** — the API is CORS-open and ready for it.

Both are deliberately later. The numbers have to be right before anything is built on
top of them.
