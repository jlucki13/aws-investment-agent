# Step 1 — Opening an AWS account (and not getting billed)

> **Read this first:** AWS changed its free tier on **July 15, 2025**. Almost every
> tutorial or YouTube video older than that describes the *old* 12-month free tier
> (750 hours of EC2 t2.micro, etc.). That offer no longer applies to new accounts.
> If a guide tells you "you get 750 free EC2 hours for a year," it's out of date.

> ### Already have an AWS account?
>
> **Skip to [Using an existing account](#using-an-existing-account) below.** The plan
> choice and signup walkthrough don't apply to you, but the hardening and billing
> steps do — plus one audit step that's specific to accounts that have been sitting
> idle.

---

## What "free" actually means now

When you sign up you pick one of two plans. **This choice matters** — pick wrong and
either your account gets locked or you get a surprise bill.

| | **Free Plan** | **Paid Plan** |
|---|---|---|
| Credits on signup | $100, plus up to $100 more for completing onboarding tasks | Same $100 + $100 |
| What happens when credits run out | Account is **restricted**, then closed if you don't upgrade | You start paying for what you use |
| Duration | 6 months, or until credits are gone — whichever comes first | No expiry |
| Always-free tier after that | Lost when the plan ends | **Keeps working forever** |
| Risk of a surprise bill | Zero | Real, unless you set up budgets |

### Which should you pick?

**Pick the Paid Plan**, and set up billing alarms in the same sitting (Step 5 below).

That sounds backwards, so here's the reasoning: the architecture in
[`02-app-ideas.md`](./02-app-ideas.md) is designed to sit inside the **always-free**
monthly limits — the ones that reset every month and never expire. Those are the
limits that actually matter for a small learning app:

- **AWS Lambda** — 1,000,000 requests + 400,000 GB-seconds per month
- **DynamoDB** — 25 GB storage, 25 write units, 25 read units
- **CloudFront** — 1 TB data out, 10,000,000 requests per month

A hobby app will not come close to any of those. On the **Free Plan** you lose access
to them after 6 months and your project dies. On the **Paid Plan** the always-free
limits keep applying indefinitely, your $200 of credits absorb anything that does
spill over during the learning phase, and a budget alarm protects you from mistakes.

**Pick the Free Plan instead if** you're nervous about a card on file and you're fine
with the account hard-stopping in 6 months. It's a genuinely safe way to learn — you
just can't keep the project alive afterward.

Either way a credit or debit card is required at signup. AWS places a temporary
authorization hold (about $1) to verify it, then releases it.

---

## Using an existing account

If you already have an AWS account from some earlier project, use it. Two things change.

**What you don't get:** the $200 in credits and the Free/Paid plan choice are
new-account-only, and if the account is more than a year old its 12-month free tier
expired long ago. You're on straight pay-as-you-go.

**What you do keep:** the **always-free** monthly limits — Lambda's 1M requests,
DynamoDB's 25 GB, CloudFront's 1 TB — apply regardless of account age. Those are what
this project actually runs on, so the cost estimate is unchanged at **~$0.35/month**,
all of it Bedrock. The credits would only have covered that for a while anyway.

### Audit before you build

A dormant account is worth checking before you add to it. Forgotten resources bill
quietly for years, and old access keys are a genuine security risk.

Sign in via **"Sign in using root user email"** — the IAM sign-in form needs a 12-digit
account ID you almost certainly don't remember. Use "Forgot password" if needed.

1. **Billing and Cost Management → Bills.** Current month, expanded **by service**.
   Should be $0.00.
2. **Cost Explorer → last 6 months, grouped by service.** Catches anything that bills
   irregularly rather than monthly.
3. If either shows charges, the usual culprits are EC2 instances, EBS volumes orphaned
   by deleted instances, unattached Elastic IPs (~$3.60/mo each), RDS instances, NAT
   Gateways (~$32/mo), and Route 53 hosted zones. The Bills page breaks down by region,
   which saves hunting through the region selector one at a time.
4. **IAM → Users → each user → Security credentials.** Delete any access key you can't
   account for. A stale key committed to some old repo is the single most common way a
   personal AWS account gets drained.
5. **IAM → Users.** Delete users from projects that are over. Fewer credentials, fewer
   ways in.

If it's all zeros, that's five minutes well spent and the account is fine to use.

### Then continue below

Skip the signup section. Do these, checking whether each is already done:

- **Step 2** — MFA on root. Often missing on older accounts set up before you cared.
- **Step 3** — admin IAM user. This is what fills in the Account ID / username /
  password fields on the IAM sign-in page.
- **Step 4** — set region to `us-east-1`.
- **Step 5** — billing access, free tier alerts, and the **$5 budget**. Do this one
  regardless of what the audit found.
- **Steps 6–7** — AWS CLI and SAM CLI.

> **Not worth doing:** creating a fresh account on another email to claim the $200 in
> credits. AWS ties free tier eligibility to the customer rather than the account, so
> the credits may not appear, and you'd maintain two accounts to save about four
> dollars.

---

## Step-by-step signup

> Skip this section if you already have an account.

### 1. Create the account

1. Go to <https://portal.aws.amazon.com/billing/signup>
2. Enter your email and pick an **AWS account name** (e.g. `jlucki-personal`). This is
   cosmetic and changeable later.
3. Verify the email with the code they send.
4. Set a **strong, unique root password**. Put it in a password manager — this
   password controls billing and can close the account, and you'll rarely use it.
5. Choose **Personal** account type. Enter your address and phone.
6. Enter the card. Expect the ~$1 hold.
7. Verify your phone via SMS or voice call.
8. **Choose your plan** — Free or Paid, per the table above.
9. Support plan: choose **Basic (free)**. Do not pick Developer ($29/mo).

Account activation usually takes a few minutes but can take up to 24 hours. You'll get
a confirmation email.

### 2. Lock down the root user — do this immediately

The root user can do anything, including spending unlimited money. If it's
compromised, attackers mine crypto on your card. This takes two minutes.

1. Sign in at <https://console.aws.amazon.com> as **Root user**.
2. Top-right, click your account name → **Security credentials**.
3. Under **Multi-factor authentication (MFA)**, click **Assign MFA device**.
4. Choose **Authenticator app** (Google Authenticator, Authy, 1Password, etc.) or a
   passkey. Scan the QR code, enter two consecutive codes.
5. Confirm there are **no root access keys**. If any exist, delete them. Root should
   never have API keys.

### 3. Create a day-to-day admin user

Don't use root for building. Create a separate identity.

**The simple path (fine for solo learning):**

1. Console → search **IAM** → **Users** → **Create user**.
2. Username e.g. `jlucki-dev`. Check **Provide user access to the AWS Management Console**.
3. Choose **I want to create an IAM user**, set a password.
4. Permissions → **Attach policies directly** → check **AdministratorAccess**.
   - This is broad, which is normally bad practice, but it's a solo learning account.
     Scoping permissions is a good later exercise.
5. Create the user. **Save the sign-in URL** — it looks like
   `https://<account-id>.signin.aws.amazon.com/console`.
6. Sign out of root. Sign in as the new user. **Enable MFA on this user too.**

> AWS officially recommends **IAM Identity Center** (SSO) over IAM users these days.
> It's better — short-lived credentials instead of permanent keys — but it's more
> setup. An IAM user is fine to start; switching later is a worthwhile exercise.

### 4. Pick a region and stick to it

Use **`us-east-1` (N. Virginia)** unless you have a reason not to.

- It's the cheapest region and gets every service first.
- ACM certificates used by CloudFront **must** live in `us-east-1`. Building
  elsewhere means juggling two regions on day one.

The region selector is in the top-right of the console. Resources are region-scoped —
if you create something in `us-west-2` and then switch regions, it vanishes from the
console. That confuses everyone once.

### 5. Set up billing protection — do not skip this

This is the single most important step. Without it there's nothing between a mistake
and a four-figure bill.

**a) Let non-root users see billing:**

Sign in as **root** (one of the few things root is needed for). Account menu →
**Account** → scroll to **IAM user and role access to Billing Information** → **Edit**
→ check **Activate IAM Access** → Update.

**b) Turn on free tier alerts:**

**Billing and Cost Management** → **Billing preferences** → enable **Receive AWS Free
Tier alerts** and **Receive AWS Free Tier usage alerts**. Enter your email.

**c) Create a real budget (the actual safety net):**

1. **Billing and Cost Management** → **Budgets** → **Create budget**.
2. Choose **Customize (advanced)** → **Cost budget**.
3. Period **Monthly**, budget amount **$5** (adjust to your comfort).
4. Add alert thresholds at **50%**, **80%**, and **100%** of budgeted amount, each
   emailing you.
5. Add a second alert on **Forecasted** cost at 100% — this warns you early in the
   month when a running resource is trending toward the limit.

Budgets **alert only, they don't stop spending.** Treat an alert as "go delete
something now," not as a cap.

**d) Check the bill weekly.** Billing → **Bills**. Look at the per-service breakdown.
A line item you don't recognize is the warning sign.

### 6. Install the AWS CLI

```bash
# macOS
brew install awscli

# Windows — download the MSI from:
# https://awscli.amazonaws.com/AWSCLIV2.msi

# Linux
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip && sudo ./aws/install
```

Create access keys for your **IAM user** (not root): IAM → Users → your user →
**Security credentials** → **Create access key** → choose **Command Line Interface (CLI)**.

```bash
aws configure
# AWS Access Key ID:     AKIA...
# AWS Secret Access Key: ...
# Default region name:   us-east-1
# Default output format: json

aws sts get-caller-identity   # should print your account ID and user ARN
```

> Access keys are long-lived secrets. Never commit them. Never paste them into a chat,
> an issue, or a code sample. If one leaks, delete it in the IAM console immediately —
> deletion is instant and total.

Add to your `.gitignore` now:

```gitignore
.env
.env.*
*.pem
.aws/
```

### 7. Install the framework you'll deploy with

For the app in `02-app-ideas.md`, **AWS SAM** is the gentlest starting point — it's a
thin layer over CloudFormation, purpose-built for Lambda + API Gateway + DynamoDB.

```bash
brew install aws-sam-cli          # macOS
# or: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html

sam --version
```

**AWS CDK** is the other option — you define infrastructure in TypeScript/Python
instead of YAML. More powerful, more concepts to absorb at once. SAM first, CDK later.

---

## Cost traps — the things that actually generate surprise bills

Nearly every "AWS charged me $200" story involves one of these. None are needed for
what we're building; the point is to recognize them when a tutorial suggests one.

| Trap | Cost | Why it bites |
|---|---|---|
| **NAT Gateway** | **~$32/mo** | The classic. Created silently by "VPC wizard" flows. You do *not* need a VPC for this project. |
| **Application Load Balancer** | ~$16–18/mo | Tutorials reach for it reflexively. API Gateway does the job here for free. |
| **RDS database** | ~$13–15/mo | Even the smallest instance bills 24/7. Use DynamoDB. |
| **EC2 running 24/7** | ~$8+/mo | No always-free tier anymore. Lambda replaces it for this app. |
| **Public IPv4 addresses** | ~$3.60/mo each | Billed since Feb 2024, **including unattached Elastic IPs.** Releasing an EC2 instance but keeping its EIP quietly bills forever. |
| **CloudWatch Logs** | grows forever | Log groups default to **never expire**. Set retention to 7 days on every one you create. |
| **Route 53 hosted zone** | $0.50/mo | Only if you want a custom domain. CloudFront's default `*.cloudfront.net` URL is free. |
| **Idle Fargate / OpenSearch / SageMaker / Bedrock provisioned throughput** | $$$–$$$$ | Bill by the hour whether or not you're using them. Never leave one running overnight "to try tomorrow." |

**The habit that prevents all of it:** when you finish experimenting, tear it down.
With SAM that's one command:

```bash
sam delete
```

Then check the console for orphans — Elastic IPs, EBS volumes, S3 buckets, log groups.
Those four survive most cleanups.

---

## Your first-day checklist

- [ ] Account created, plan chosen deliberately *(new accounts)*
- [ ] Existing account audited — $0 in Bills, no unrecognized access keys *(existing accounts)*
- [ ] MFA on root user
- [ ] No root access keys
- [ ] Admin IAM user created, with its own MFA
- [ ] Signed out of root; using the IAM user
- [ ] Region set to `us-east-1`
- [ ] IAM billing access activated (as root)
- [ ] Free tier alerts on
- [ ] $5 budget with 50/80/100% + forecast alerts
- [ ] AWS CLI installed, `aws sts get-caller-identity` works
- [ ] SAM CLI installed
- [ ] `.gitignore` covers `.env` and credentials

Once that's done, move on to [`02-app-ideas.md`](./02-app-ideas.md).

---

## Sources

- [AWS: Free Tier now offers $200 in credits and 6-month free plan](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/)
- [AWS Free Tier Terms](https://aws.amazon.com/free/terms)
- [AWS Free Tier in 2026: What Changed, What's Still Free](https://infratally.com/articles/aws-free-tier-2026/)
- [AWS Free Tier Explained: What's Actually Free in 2026](https://spot.rackspace.com/blog/aws-free-tier)
