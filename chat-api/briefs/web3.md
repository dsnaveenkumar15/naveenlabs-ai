## Intro

Web3 (web3.naveenlabs.tech) is a crypto trading-bot platform connected to an exchange. It runs 11 bot types, such as DCA, grid, trailing stop and Bollinger-band bots, with a live dashboard, backtests and alerts. The public site runs in **paper mode** on the exchange's test network: no real money moves.

<!-- more -->

Web3 automates crypto strategies with the controls a careful trader expects.

- **11 bot types**: DCA, Grid, Signal DCA, Trailing Stop, HODL, Bollinger Band, Scalping, Momentum, Combo, Short DCA (futures) and Multi-pair.
- **Deals and safety orders**: each bot opens deals, adds safety orders on dips and closes on take-profit or stop-loss; a user can force-close or adjust a deal.
- **Backtests and research** on historical candles.
- **Alerts** on Telegram, Discord and an in-app inbox; TradingView webhooks with a per-user token.
- **AI features**: reviews, vetoes, regime checks, briefings and a coach, never inside a bot tick.
- **Paper mode** is the default and the public site uses the exchange's test network.

## Architecture

A modular monolith: one FastAPI app and PostgreSQL 16, made of five bounded contexts (accounts, market, backtest, intelligence, trading) in hexagonal layers, plus a platform kernel, a workers package and one composition root. 25 import contracts enforce the layering, with no exceptions.

<!-- more -->

- **Layers**: `domain` (rules and frozen dataclasses), `application` (use cases and ports), `infrastructure` (database repositories and exchange, Telegram, model and HTTP adapters), `api` (thin routers). mypy is strict for domain and application.
- **The tick**: every 10 seconds the scheduler evaluates each active bot. Several app workers run the scheduler, but only one leader, the worker holding a Postgres advisory lock, runs the jobs; the others take over within 30 seconds if it stops.
- **One writer per bot**: a per-bot advisory lock means the 10-second tick and a user's command never act on the same deal at once; each bot runs in its own transaction, so one failing bot does not stop the others.
- **Paper or live** needs three switches to agree: the deal, its owner and the global setting must all allow live trading.
- **Order journal**: every order is journaled before the exchange call and settled by a job, so an uncertain outcome is never lost.
- **22 scheduled jobs** (the tick, market caps, indicators, summaries, the journal settler, reconciliation, a drawdown breaker, backups and the AI jobs), each watched: a failing job shows on `/health` and alerts the operator.
- **Domain events** (deal opened, safety order filled, deal closed, bot errored, risk limit hit) feed the alerts and incident notes.

## Strengths

- **Safe by construction**: live trading needs the deal, the user and the platform to agree; the AI never places or sizes orders.
- **Proven refactor**: the move to five contexts was verified equal to the old code by golden-master tests.
- **Tested**: about 2,590 tests (2,129 unit and integration, 457 golden), and mutation testing catches 3,878 of 4,262 injected bugs (91.0%).

<!-- more -->

- **Mutation testing**: the code was changed in 4,262 small ways and the tests run against each change; 3,878 (91.0%) were caught. The survivors were read one by one, which found and fixed real money bugs.
- **Golden masters**: a route inventory, recorded HTTP responses, engine replays and job outputs prove the rewrite behaves exactly like the old code.
- **Leader election and per-bot locks** in Postgres, so scaling the web workers never double-runs a job or a bot.
- **Observability**: Prometheus metrics behind a token, a health endpoint covering the database, the scheduler role, the price feed and failing jobs, and errors grouped by kind with an alert for each new kind, all kept on the server.
- **Reliability**: nightly backups with a weekly restore test, a job watchdog, and an order journal that settles uncertain orders; five failures in a row stop a bot with an alert instead of retrying forever.

## Intelligence

All AI lives in the **intelligence** context behind one gateway (Claude or a local Ollama model), with metering, a budget, a circuit breaker and a kill switch. It reviews bots, vetoes risky entries, detects market regimes, writes briefings and incident notes, and coaches the user. It never runs inside a bot tick and never places or sizes an order.

<!-- more -->

- **The gateway**: one entry point for every model call, with per-user settings, usage metering, a budget, a circuit breaker, a journal of calls and a kill switch. Providers: Claude or a local Ollama model.
- **What it does**: reviews with evidence and approvals (approving a suggestion changes a bot parameter in the same transaction), news vetoes and an economic calendar, regime detection and an entry gate, signals, exposure, "ask" questions about your bots, a coach, a critic, incident notes for a disabled bot, and a daily briefing.
- **Where it stops**: no model runs inside the 10-second tick; an entry gate can block a deal but cannot open, size or place one; a suggestion changes nothing until the user approves it.
