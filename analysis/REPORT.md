# Sunderland – Post-Game Momentum Analysis

31 Premier League games ingested from `CSV Game Report/`. Analysis reproducible by
running `python3 analysis/analyse.py`.

> Note: the prompt mentioned "6 matches" but the repo contains 31 CSVs (season
> 2025/26 up to 22 Mar 2026). The whole set is used here — if you want the
> analysis restricted to a subset, point me at the list.

## Scoring convention

Each action ends with one or more outcome symbols in the `Row` cell. The
momentum delta for an action is computed as:

| symbol | meaning            | value per occurrence |
|--------|--------------------|----------------------|
| ✅     | success             | **+1**               |
| ❌     | failure             | **−1**               |
| ⚠      | warning             | **−0.5**             |
| 🚧     | work in progress    |  0                   |
| 🔎     | "review later"      |  0                   |
| ⚽     | goal (scored/conceded — sign follows the ✅/❌ on that row) | annotated on curve |

So `[IP3a] Build (...)✅✅` → +2, `[OP4a] Low Block (...)❌❌❌⚽` → −3 **and**
a conceded-goal marker.

## Clock handling

- 7 CSVs contain a `GameTime` column → real match clock.
- 24 "chronological" CSVs do not → we use the cumulative `Duration` column
  and then linearly rescale so the last action sits at ~93 min. This gives a
  monotone minute estimate that's fine for cumulative curves and 15-min
  buckets, but exact minute-stamps should be taken with a small pinch of
  salt for those 24 files.

---

## 1. Momentum curves by game

Per-game plots are under `analysis/figures/per_game/`, one PNG per match.
Goals scored are marked with a green ★, goals conceded with a red ✕.
`analysis/figures/overlay_all_games.png` is all 31 curves on one canvas plus
the mean (royal blue) ± 1 SD band.

### What the curves actually show

| Window   | Mean Δ | Home mean | Away mean |
|----------|-------:|----------:|----------:|
| 0 – 15   | +4.37  | **+6.81** | +1.77     |
| 15 – 30  | +4.27  | +4.66     | +3.87     |
| 30 – 45  | +5.08  | +5.75     | +4.37     |
| 45 – 60  | +4.90  | +4.50     | +5.33     |
| **60 – 75** | **+1.73** | +1.53 | +1.93 |
| 75 – 90  | +2.56  | +3.62     | +1.43     |

**Headlines:**

1. **There is a real fade — and it lands exactly at 60 min.** The per-window
   mean drops from +4.9 (45-60) to +1.7 (60-75) — roughly a 65 % reduction in
   net momentum production. It recovers slightly in the final 15 min (mostly
   from "emergency mode" set pieces and IP4 attempts).
2. **At home you *start* the games; away you don't.** The 0-15 window is
   +6.81 at home vs +1.77 away — a 5-point swing over 15 minutes. That's the
   largest venue effect anywhere in the dataset.
3. **Away games pivot on 45-60.** Away the strongest window is the first
   15 min after half-time (+5.33) — by a small margin the peak away
   momentum. So the away story is "survive → punch after HT → hang on."
4. **First-half dominance.** Avg first-half net momentum is **+13.7**,
   second-half **+9.2** — 23 / 31 games have a weaker second half. You are a
   first-half team.

### Spiral-before-concede check

Of the 12 goals conceded in the dataset, virtually all are preceded by a
run of ❌ / ⚠ actions in the 2–3 minutes beforehand rather than being
isolated moments of quality from the opponent (see the per-game plots —
red ✕ markers almost always sit on or just after a downward local slope).
The most common phase failing immediately before a concession is
**OP4 (Low Block)** — i.e. we are usually already under pressure and the
spiral has begun before the ball ends up in the net. Concession from a
high momentum state is essentially absent in the data.

---

## 2. "What happens after we fail?"

For every **failed** action in a key phase we look at the next 3 actions
and ask: does the team *recover* (net Δ > 0), *spiral* (net Δ < 0), or
*stay neutral*?

| Phase | Failures | Recover % | **Spiral %** | Neutral % | Top 4 next-phase outcomes |
|-------|---------:|----------:|-------------:|----------:|---------------------------|
| IP1 (GK restart in poss.)   | 187 | 48.7 | 34.2 | 17.1 | Other(121), OP4(90), IP1(69), OP2(48) |
| **IP2 (low build-up)**      |  99 | 51.5 | **34.3** | 14.1 | Other(68), OP4(39), IP1(37), OP2(30) |
| IP3 (progression)           | 107 | 46.7 | 29.0 | 24.3 | IP3(50), Other(47), DefTrans(44), OP3(31) |
| IP4 (attacking phase)       |  57 | **63.2** | 21.1 | 15.8 | Other(36), DefTrans(28), OP1(14), OP2(14) |
| OP2 (high press)            |  83 | 44.6 | **45.8** | 9.6  | IP1(51), Other(46), OP4(41), OP3(30) |
| OP3 (mid block)             |  87 | 50.6 | 40.2 | 9.2  | Other(69), IP1(39), OP4(26), OP3(19) |
| OP4 (low block)             | 128 | 45.3 | 39.8 | 14.8 | Other(112), IP1(68), OP4(58), OP2(25) |

**Reading that table — the three coaching-relevant findings:**

1. **Failed IP2 (low build-up) → the opponent ends up in our Low Block
   39 % of the time.** Nearly 4 in 10 build-up errors bypass OP2 and OP3
   entirely and land us straight in OP4 defensive mode within 3 actions.
   That's the single biggest leakage in the game model — one sloppy GK
   connection triggers a **back-foot sequence, not a high press reset**.
2. **Failed OP2 (high press) is the highest-spiral phase in the dataset
   at 45.8 %.** When the press breaks down, recovery is under 50/50 and
   we concede territory faster than any other phase. The 30 hits in OP3
   and 41 in OP4 in the following 3 actions confirm the team collapses
   backwards rather than re-pressing.
3. **Failed IP4 is the *best* phase to fail in (63.2 % recovery).**
   Contrary to intuition, losing the ball in the attacking third usually
   leads to a counter-press win — 28 DefTrans hits in the window, but the
   net Δ is positive. That's your rest-defence working and should be
   highlighted to the players.

Goals-against within 3 actions of a failed phase are rare overall (≤1.8 %
for all phases). Spirals usually cost you territory and an OP4 reset, not
directly a goal — so the coaching intervention is about **preventing
territorial loss**, not about emergency panic.

Full numbers: `analysis/tables/post_failure_transitions.csv`.

---

## 3. Phase conversion chains

For every **successful** action in IPx, we trace the next ≤4 actions
(stopping when possession is lost: DefTrans or an OP phase) and see how
far up the chain the attack progressed.

| Start phase | Successes | → reached IP3 | → reached IP4 | → reached IP5 | → goal |
|-------------|----------:|--------------:|--------------:|--------------:|-------:|
| IP1 (GK restart)      | 185 | 18.9 % | 26.5 % | 0.5 % | 2.7 % |
| IP2 (low build-up)    |  82 | 15.9 % | 24.4 % | 3.7 % | 1.2 % |
| IP3 (progression)     | 113 |   –    | 25.7 % | 2.7 % | 2.7 % |
| IP4 (attacking phase) | 121 |   –    |   –    | 8.3 % | 0.8 % |

Plot: `analysis/figures/phase_conversion.png`.

**Key insight — the funnel is extremely narrow at the end:**

- A clean **IP2 build-up only yields an attacking-phase (IP4) 24 % of the
  time**. Three quarters of successful build-ups dead-end in set
  pieces, reset passes, or give the ball back.
- **IP3 → IP4 is not materially better than IP2 → IP4** (25.7 % vs 24.4 %).
  The progression phase is where the chain is most often recycled rather
  than accelerated — lots of IP3 actions beget more IP3, not IP4.
- **Only 8.3 % of successful IP4 actions turn into IP5 (attack the box)
  within the next 4 actions.** This is the single biggest efficiency
  leak in the offensive game plan. The attacking phase is happening, but
  it isn't converting to final-third arrivals.
- **Most efficient direct route to goal in the data:** IP1 (GK restart)
  → 2.7 % goal rate — slightly above IP3 (2.7 %) and IP2 (1.2 %). The
  quick GK restart is actually the most dangerous sequence on a per-
  attempt basis, which matches the goal log (several ⚽ events come from
  `[IP1]GK Restart ✅✅⚽`, `[OSP] Throw-in`, etc.).

**Coaching implication:** the weakest link in the attacking chain is
IP4 → IP5, not IP2 → IP3. If the ask is "score more goals," the work is
on how the team decides to enter the box (crosses vs cut-backs vs
combinations), not on the build-up.

---

## 4. Home vs Away patterns

Plot: `analysis/figures/home_vs_away_by_window.png`.
Full table: `analysis/tables/home_vs_away_success_rates.csv`.

| Phase           | Home success % | Away success % | Δ (pp) |
|-----------------|---------------:|---------------:|-------:|
| **IP1** (GK restart) | 55.9 | 43.5 | **+12.4** |
| IP2 (low build-up)   | 44.7 | 45.8 | −1.1  |
| **IP3** (progression) | 57.8 | 44.2 | **+13.5** |
| **IP4** (attacking)   | 73.2 | 61.7 | **+11.5** |
| OP1 (def GK restart)  | 72.2 | 77.8 | −5.6  |
| OP2 (high press)      | 68.7 | 72.6 | −3.9  |
| **OP3** (mid block)   | 76.2 | 68.5 | +7.7  |
| OP4 (low block)       | 62.6 | 61.4 | +1.2  |
| OffTrans              | 57.5 | 43.0 | **+14.5** |
| AttSetPlay            | 56.8 | 47.1 | +9.8  |

**Headlines:**

1. **Attacking output is crushed away from home.** IP1/IP3/IP4 are all
   +11 to +14 pp worse away. Offensive transitions are −14.5 pp. You
   basically lose the ability to progress the ball with quality as soon
   as you leave the Stadium of Light.
2. **IP2 is the exception — build-up success is identical home/away
   (44.7 % vs 45.8 %).** So the first pass out of the back is not the
   problem. It's what happens in the IP3 / IP4 stages that falls apart
   on the road.
3. **The high press actually works slightly *better* away (+3.9 pp).**
   Counter-intuitive but consistent: away opponents take more risk to
   press us, which creates more OP2 success for Sunderland. So the
   tactical suggestion that the press works at home is not supported by
   the data — if anything it's the other way round.
4. **OP3 (mid block) is the one defensive phase that is clearly better
   at home (+7.7 pp)** — the crowd effect seems to make the mid-block
   more aggressive and better organised.
5. **Set plays for us swing 10 pp home/away** — probably less to do with
   set-piece quality and more to do with referees awarding fewer of them
   away. Worth looking at the raw counts.

---

## Files produced

```
analysis/
├── analyse.py                                     # reproducible pipeline
├── REPORT.md                                      # this file
├── figures/
│   ├── overlay_all_games.png                      # all 31 curves + mean band
│   ├── home_vs_away_by_window.png                 # 15-min bar chart
│   ├── phase_conversion.png                       # IPx → next level bars
│   └── per_game/*.png                             # one plot per match
└── tables/
    ├── per_game_summary.csv                       # net / FH / SH / goals
    ├── post_failure_transitions.csv               # recover / spiral %
    ├── phase_conversion.csv                       # IP1..IP4 conversion
    └── home_vs_away_success_rates.csv             # phase success % split
```

## Suggested next steps

- **Validate the scoring constants.** I treated ✅ = +1 / ❌ = −1 / ⚠ = −0.5.
  If your internal model uses different weights (e.g. ❌ in IP2 worth more
  than ❌ in OP4), drop the weights in and rerun — the pipeline parameters
  are at the top of `analyse.py`.
- **Look at 60-75 min specifically** — the fade is real. Cross-reference
  with physical-load data / subs timings to see if it's fitness, substitution
  policy, or tactical resignation.
- **OP2 failure → OP4 pipeline** (finding #2 above) deserves a dedicated
  video session: every instance of a lost high press that became a low
  block within 3 actions.
- **IP4 → IP5 conversion** is the single biggest attacking lever
  (only 8.3 %). Dedicated final-third training variations — not more
  build-up work.
