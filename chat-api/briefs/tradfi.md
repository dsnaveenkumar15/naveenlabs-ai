## Intro

TradFi (tradfi.naveenlabs.tech) is an automated trading system for Indian F&O stocks, connected to a broker. Its main strategy is an "always in trade" ladder: it buys more on dips and takes profit on rises without ever fully leaving the position. It is multi-user with two-factor login, and the public site runs in **paper mode**: no real orders are placed.

<!-- more -->

TradFi automates a disciplined ladder strategy and the bookkeeping around it.

- **Ladders**: an initial buy, then one more step on every dip (1% by default) down to a maximum drawdown (10% by default). When a level rises to its target (1.3% by default), TradFi buys a replacement at market first and only then sells the old lot, so the position is never left empty.
- **Bots**: six signal strategies (swing DCA with RSI and MACD, momentum EMA cross, time-based SIP, trailing breakout, Bollinger-band reversal, and a combo of the others).
- **Advisor**: rule-based verdicts on stocks from fundamentals, with switchable investor "lenses" and a track record against the NIFTY 50. No AI decides a verdict.
- **Backtests, portfolio and tax views**, watchlists and a trading journal.
- **Alerts** on Telegram; TradingView webhooks with a per-user token.
- **Paper mode** is on for the public site: everything runs end to end, but orders are simulated.

## Architecture

A modular monolith: one FastAPI app and PostgreSQL 16 on one server, split into 9 bounded contexts (accounts, brokerage, market, investing, advisor, notebook, backtest, intelligence, trading), each in hexagonal layers. Each user gets their own runner with a live price feed and the strategy engines. Generated import contracts enforce the layering.

<!-- more -->

- **Layers**: each context has `domain` (pure rules, no I/O), `application` (use cases and ports), `infrastructure` (database, broker, Telegram, model and HTTP adapters, jobs) and `api` (thin routers). Dependencies point inward; other contexts are reached only through their application layer; only infrastructure touches tables. Generated import contracts and a conformance suite enforce all of it.
- **Paper or live** is decided in exactly one place, a broker port that returns the paper broker or the real one; the paper broker refuses real order calls.
- **A tick**: the price feed calls the engine; the engine takes a per-bot lock and plans the tick in pure domain code (sell the cheapest level whose target was hit, else buy the next dip within the drawdown limit).
- **An order** goes through one use case: the risk check (position, loss and rate limits, the circuit breaker), then the AI entry gates, then the placement, then the wait for the fill. The order journal row is written before the broker is called, and an order with an unknown outcome blocks further live orders until it is settled.
- **Safety**: a fill that cannot be recorded trips a circuit breaker, because the broker and the database disagree. Scheduled jobs log in to the broker each morning, start and stop the price feed around market hours, and back up the database nightly.
- **One runner per user** holds that user's price feed, engines and jobs; a shared scheduler host runs the common jobs.

## Strengths

- **Correctness first**: the order journal is written before the broker call, unknown outcomes block live orders, and a mismatch trips a circuit breaker.
- **Refactored safely**: the layered rewrite was proven equal to the old code by golden-master tests.
- **Tested**: about 3,380 tests (2,864 unit and integration, 519 golden), and mutation testing catches 7,419 of 8,496 injected bugs (87.3%).

<!-- more -->

- **Money paths are guarded twice**: a risk check in pure domain code, then the AI entry gates, which can only block an order, never place or size one.
- **Proven rewrite**: the move from a monolith to 9 contexts ran behind golden-master suites (recorded HTTP responses, engine replays and job outputs), so behaviour stayed identical while the structure changed.
- **Mutation testing**: tests were attacked with 8,496 small code changes; 7,419 (87.3%) were caught, and the survivors on the money paths were read one by one, which found and fixed real gaps.
- **Found by running it**: a soak run on the server found and fixed real issues, for example a price feed that did not reconnect on the second morning and a second morning login that cancelled a valid session.
- **Honest limits**: reconciliation with the broker exists for live mode but has not yet been proven on a real account; that is on the list before going live.
- **Secure by default**: password and two-factor login, every route needs a signed-in user unless it is on a short public list, per-user webhook tokens, and a hardened non-root container.

## Intelligence

All AI lives in one context, **intelligence**, and it never places, sizes or decides an order. Its entry gates (a news veto and a market-regime check) can only block a trade. AI also writes reviews and explanations. The **Advisor** is deliberately rule-based: no language model in the verdict, so every verdict can be explained and reproduced.

<!-- more -->

- **What AI does**: reviews of bots and trades, explanations, and two entry gates (a news veto and a market-regime check). A gate can block an order; it can never place, size or choose one.
- **Where it sits**: in the order use case, after the risk check and before placement, so a model can only make the system more cautious.
- **The Advisor**: verdicts on stocks from fundamentals and computed ratios, with switchable investor lenses (Graham-, Lynch- and Buffett-style rule packs) and a track record measured against the NIFTY 50. Verdicts are rules with editable thresholds, not model output, because a model's verdict cannot be explained or reproduced.
- **Honest status**: the live AI path has never run with a real provider key; the AI features are built and tested, but run without one on the public site.
