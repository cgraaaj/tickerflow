🧱 PHASE 1 — Core Django SaaS Backend (Auth + API keys + DB)
🎯 Goal:

User accounts, API keys, raw SQL access to TimescaleDB.

📌 Cursor Prompt:

Create a Django project using Django REST Framework for a B2C data SaaS.

Requirements:

Custom User model using email login

APIKey model with hashed storage

Middleware that authenticates requests using X-API-KEY

PostgreSQL connection to TimescaleDB

Use raw SQL for time-series queries (do not rely on Django ORM for hypertables)

Admin interface for users and API keys

Environment variable based settings

Output:

Full project structure

Settings.py configured for Timescale/Postgres

Middleware code

Models

Admin registrations

Example authenticated API endpoint

📊 PHASE 2 — Historical Tick + Candle API
🎯 Goal:

High performance read endpoints with Timescale features.

📌 Cursor Prompt:

Extend the Django REST backend with high performance market data APIs.

Implement:

GET /api/v1/ticks endpoint with parameters:
instrument_id, start, end, limit

GET /api/v1/candles endpoint using Timescale time_bucket

Raw SQL queries optimized with indexes

Pagination for tick results

Input validation

Query execution time logging

Use psycopg or Django connection cursor directly.

Output:

Views

Serializers

SQL queries

Performance-safe pagination

URL routing

💳 PHASE 3 — Usage Based Billing System
🎯 Goal:

Track every API call and bill users by data usage.

📌 Cursor Prompt:

Implement a usage-based billing system in the Django backend.

Requirements:

UsageLedger model:
user, endpoint, units_consumed, timestamp

After every API response:

calculate rows returned

deduct from user balance

block requests when balance insufficient

Admin reporting for usage

Middleware or decorator based enforcement

Output:

Models

Middleware/decorators

Example integration in tick/candle endpoints

Admin dashboards

⚡ PHASE 4 — Rate Limiting & Abuse Protection
🎯 Goal:

Stop scraping and overload.

📌 Cursor Prompt:

Add Redis-based rate limiting to the Django API.

Requirements:

Per API key limits per minute

Tier-based limits (basic, pro, enterprise)

Fast Redis counters with expiry

Automatic 429 response on limit exceeded

Middleware implementation

Output:

Redis integration

Middleware code

Settings config

Example limits per plan

📦 PHASE 5 — Stripe Usage-Based Subscription
🎯 Goal:

Monetize properly.

📌 Cursor Prompt:

Integrate Stripe usage-based billing into the Django SaaS backend.

Requirements:

Subscription plans

Metered usage reporting to Stripe

Monthly auto billing

Webhook handling for payment success/failure

User subscription status updates

Output:

Stripe client integration

Webhook handlers

Models for subscription state

Example usage report flow

🔥 PHASE 6 — Continuous Aggregates & Performance Layer
🎯 Goal:

Massive speedups for candles & analytics.

📌 Cursor Prompt:

Optimize TimescaleDB performance using continuous aggregates.

Implement:

1m, 5m, 15m candle aggregates

Refresh policies

Query routing to aggregate tables

Compression for older chunks

Output:

SQL migration scripts

Django startup hooks

Query fallback logic