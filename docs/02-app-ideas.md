# Step 2 — What to build

## The stack (same for every idea below)

One architecture, chosen so that a hobby-scale app costs **$0/month indefinitely** —
it sits inside AWS's *always-free* limits, not the expiring credits.

```
Browser
   │
   ▼
CloudFront  ──────────►  S3 bucket          (React app: HTML/CSS/JS)
(CDN + HTTPS)            static files
   │
   │ /api/*
   ▼
API Gateway  ─────────►  Lambda  ─────────►  DynamoDB
(HTTP API)               (your code)         (data)
```

| Layer | Service | Free allowance | Realistic hobby usage |
|---|---|---|---|
| Frontend hosting | S3 + CloudFront | 1 TB out, 10M req/mo | < 1 GB |
| API | API Gateway (HTTP API) | 1M req/mo for 12 months | a few thousand |
| Backend | Lambda | 1M req + 400k GB-sec/mo, **always free** | a few thousand |
| Database | DynamoDB | 25 GB + 25 RCU/WCU, **always free** | < 100 MB |
| Auth (optional) | Cognito | generous monthly active user tier | you and 3 friends |

**Why this shape and not the "normal" one:**

- **Lambda, not EC2** — EC2 bills 24/7 whether or not anyone visits. Lambda bills per
  request and the first million each month are free. A hobby app gets ~0 traffic, so
  Lambda is free where EC2 is ~$8/mo.
- **DynamoDB, not RDS/Postgres** — RDS bills hourly for an idle instance (~$13/mo
  minimum). DynamoDB's free tier is permanent. The tradeoff is real: no SQL joins,
  and you design your keys around your queries. That's a genuinely useful thing to
  learn, but it *is* a different mental model.
- **API Gateway, not a load balancer** — an ALB is ~$16/mo minimum. API Gateway is
  per-request.
- **No VPC** — the moment you put Lambda in a VPC and give it internet access, you
  need a NAT Gateway at **$32/mo**. Skip the VPC entirely.

**Recommended languages:** Node.js (TypeScript) or Python for Lambda; React + Vite for
the frontend. Both Lambda runtimes have first-class support and the fastest cold starts
among the mainstream options.

---

## Six ideas

Rated on what each one *teaches*, since that's the point.

### 1. Link shortener — `short.ly/x7Bq2` → your long URL

**Build time:** a weekend · **Difficulty:** ★☆☆☆☆

Paste a URL, get a short code back. Visiting the short code redirects. A stats page
shows click counts.

- **Teaches:** the entire stack end-to-end with almost no business logic in the way.
  DynamoDB key design (the short code *is* the partition key), Lambda, HTTP redirects,
  atomic counters, CloudFront caching.
- **Why it's a good first build:** ~150 lines of backend. When something breaks you're
  debugging AWS wiring, not your own domain logic — which is exactly what you want
  while the platform is the unfamiliar part.
- **Weakness:** thin frontend. Two forms and a table.

### 2. Uptime monitor — "is my site up?"

**Build time:** 1–2 weekends · **Difficulty:** ★★★☆☆

Register a list of URLs. A scheduled Lambda pings each one every 5 minutes, records
status code and response time, and emails you when one goes down. Dashboard shows
uptime % and a response-time chart.

- **Teaches:** everything in #1, **plus** EventBridge scheduled rules (cron in the
  cloud), time-series data modeling in DynamoDB, DynamoDB TTL for auto-expiring old
  records, SNS for email alerts, and a real charting frontend.
- **Why it's strong:** it's the only idea here that isn't just CRUD. It's event-driven
  and it does something while you're asleep, which is the thing that makes cloud click.
  It's also genuinely useful — you'd actually run it.
- **Weakness:** more moving parts to debug at once.

### 3. Job application tracker

**Build time:** 1–2 weekends · **Difficulty:** ★★☆☆☆

Kanban board: Applied → Phone screen → Onsite → Offer/Rejected. Drag cards between
columns, attach notes and dates, see stats.

- **Teaches:** solid CRUD, DynamoDB single-table design with a GSI (query by status
  *and* by date), Cognito auth, and a genuinely interesting frontend (drag-and-drop,
  optimistic updates).
- **Why:** the richest *frontend* of the six, and useful if you're job hunting.
- **Weakness:** if you're not job hunting, motivation dies in week two.

### 4. Habit tracker with streaks

**Build time:** 1–2 weekends · **Difficulty:** ★★☆☆☆

Define habits, check them off daily, see a GitHub-style contribution grid and current
streak. Optional daily reminder email.

- **Teaches:** CRUD, date/timezone handling (harder than it sounds, and a genuinely
  valuable thing to get burned by once), EventBridge for reminders, a satisfying
  visual frontend.
- **Weakness:** timezone bugs will eat an evening. Educational, but frustrating.

### 5. Recipe box with photos

**Build time:** 1–2 weekends · **Difficulty:** ★★★☆☆

Save recipes with ingredients, steps, tags, and a photo. Search by ingredient.

- **Teaches:** the thing the others don't — **S3 presigned URLs** for direct
  browser-to-S3 uploads (the correct pattern; you never proxy file bytes through
  Lambda), plus image thumbnailing with a trigger-on-upload Lambda, and tag-based
  querying with a GSI.
- **Weakness:** image handling adds a chunk of incidental complexity.

### 6. Read-later / bookmark manager

**Build time:** a weekend · **Difficulty:** ★★☆☆☆

Save a URL, Lambda fetches the page title and description, tag it, search it.

- **Teaches:** Lambda making outbound HTTP calls, HTML parsing, tag-based GSI queries,
  full-text-ish search patterns in DynamoDB.
- **Weakness:** overlaps a lot with #1 conceptually.

---

## Recommendation

**Do #1 first, then #2.**

Build the **link shortener** over one weekend purely as a "hello world" for the stack.
The goal isn't the app — it's getting `sam deploy` to work, seeing a Lambda run, and
watching a React app on CloudFront call a real API. Everything after that is easier
because the plumbing is no longer mysterious.

Then build the **uptime monitor** as the real project. It reuses everything you just
learned and adds the genuinely cloud-native parts: scheduled execution, alerting, and
data that accumulates over time. It's also the one you'd keep running afterward.

If you'd rather do a single project and want the strongest frontend practice, pick
**#3, the job tracker**, instead.

---

## A suggested build order, whichever you pick

Deploy early and often. The classic mistake is building the whole app locally and
hitting every AWS problem at once on day five.

1. **Deploy nothing but a "hello world" Lambda + API Gateway** with SAM. Curl it.
2. **Add DynamoDB.** One endpoint that writes an item, one that reads it back.
3. **Build the API properly** — full CRUD, tested with curl or Postman. No frontend yet.
4. **Scaffold the React app locally** (`npm create vite@latest`), pointed at the
   deployed API. Fix CORS here — it will bite, and it's easier to debug with only one
   new variable in play.
5. **Deploy the frontend** to S3 + CloudFront.
6. **Then** add the extras — auth, scheduled jobs, alerts, charts.
7. **Set CloudWatch log retention to 7 days** on every log group. Do it now, not later.

Run `sam delete` whenever you're stepping away for a while. Redeploying takes two
minutes; a forgotten resource bills for a month.
