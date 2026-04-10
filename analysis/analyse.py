"""
Sunderland game-momentum analysis.

Reads every CSV under ../CSV Game Report/ and produces:
  - per-game momentum curves (minute-by-minute cumulative score)
  - an overlay of every curve
  - a home-vs-away comparison
  - post-failure transition analysis (what happens after IP2/IP3 loss?)
  - phase conversion chains (IP2 -> IP3 -> IP4 -> IP5 / goal)
  - summary tables written to analysis/tables/

Scoring convention (documented in REPORT.md):
    checks  (successes)   +1 each   e.g. ✅✅ = +2
    crosses (failures)    -1 each   e.g. ❌❌ = -2
    warnings ⚠             -0.5
    work-in-progress 🚧    0
    review flag 🔎         0 (not a value, just "review later")
    goal ⚽               captured as a separate event; its sign
                           follows the accompanying ✅/❌ symbols
"""

from __future__ import annotations

import csv
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
CSV_DIR = ROOT.parent / "CSV Game Report"
FIG_DIR = ROOT / "figures"
TBL_DIR = ROOT / "tables"
FIG_DIR.mkdir(exist_ok=True)
TBL_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

PHASE_RX = re.compile(r"\[(OP|IP|DSP|OSP)(\d+[a-c]?)\]", re.IGNORECASE)
# filename date: first 6 chars (YYMMDD)
DATE_RX = re.compile(r"^(\d{6})_")


def score_row(label: str) -> tuple[float, bool, bool]:
    """Return (delta, is_goal_for, is_goal_against) for an action label."""
    checks = label.count("✅")
    crosses = label.count("❌")
    warns = label.count("⚠")
    # 🚧 and 🔎 contribute 0
    delta = checks - crosses - 0.5 * warns
    has_goal = "⚽" in label
    goal_for = has_goal and checks >= crosses  # scored
    goal_against = has_goal and crosses > checks  # conceded
    return delta, goal_for, goal_against


def classify_phase(label: str) -> str:
    """Map an action label to a coarse phase bucket."""
    m = PHASE_RX.search(label)
    if m:
        side, num = m.group(1).upper(), m.group(2).lower()
        # strip letter suffix for coarse bucket (e.g. 3a -> 3)
        base = re.match(r"\d+", num).group(0)
        return f"{side}{base}"
    lo = label.lower()
    if "defensive transition" in lo:
        return "DefTrans"
    if "offensive transition" in lo:
        return "OffTrans"
    if "attacking throw" in lo or "attacking corner" in lo or "attacking free" in lo:
        return "AttSetPlay"
    if "defending throw" in lo or "defending corner" in lo or "defending free" in lo:
        return "DefSetPlay"
    if "penalty" in lo:
        return "Penalty"
    return "Other"


def detect_home(filename: str) -> tuple[str, str]:
    """Return (venue, opponent) by inspecting the filename.

    CSV filenames follow 'DATE_HOMETEAM_AWAYTEAM(...)'. So if Sunderland is
    first, we're Home; otherwise Away.
    """
    stem = filename.split("/")[-1]
    stem = re.sub(r"^\d{6}_", "", stem)  # drop date
    stem = stem.split("(")[0].split("_ANALYST")[0].split(".")[0]
    # normalize 'Sunderland v Brentford'
    stem = stem.replace(" v ", "_").replace(" ", "")
    parts = stem.split("_")
    parts = [p for p in parts if p]
    home = parts[0] if parts else ""
    away = parts[1] if len(parts) > 1 else ""
    if home.lower().startswith("sunderland"):
        return "Home", away
    return "Away", home


def gametime_to_sec(s: str) -> float | None:
    if not s:
        return None
    # expect HH:MM:SS or MM:SS
    parts = s.strip().split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 3:
        h, m, sec = parts
        return h * 3600 + m * 60 + sec
    if len(parts) == 2:
        m, sec = parts
        return m * 60 + sec
    return None


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class Action:
    minute: float          # match minute (approx)
    label: str
    phase: str             # e.g. IP3, OP2, DefTrans
    delta: float           # momentum contribution
    goal_for: bool
    goal_against: bool


@dataclass
class Game:
    filename: str
    date: str
    venue: str             # Home / Away
    opponent: str
    has_real_clock: bool = False  # True if CSV contained GameTime
    actions: list[Action] = field(default_factory=list)

    @property
    def short(self) -> str:
        return f"{self.date} {self.venue[:1]} vs {self.opponent}"


# ---------------------------------------------------------------------------
# CSV ingestion
# ---------------------------------------------------------------------------


def parse_game(path: Path) -> Game:
    with open(path, newline="") as fp:
        reader = csv.reader(fp)
        header = next(reader)
        rows = list(reader)

    # locate columns
    col = {name: i for i, name in enumerate(header)}
    row_col = col.get("Row")
    dur_col = col.get("Duration")
    gt_col = col.get("GameTime")

    venue, opponent = detect_home(path.name)
    m = DATE_RX.match(path.name)
    date = m.group(1) if m else ""
    g = Game(filename=path.name, date=date, venue=venue, opponent=opponent)

    cumulative_sec = 0.0
    for r in rows:
        if not r or row_col is None or row_col >= len(r):
            continue
        label = r[row_col].strip()
        if not label:
            continue

        # derive minute
        minute = None
        if gt_col is not None and gt_col < len(r) and r[gt_col]:
            raw = r[gt_col].split(",")[0].strip()
            sec = gametime_to_sec(raw)
            if sec is not None:
                minute = sec / 60.0
                g.has_real_clock = True
        if minute is None and dur_col is not None and dur_col < len(r):
            try:
                dur = float(r[dur_col] or 0)
            except ValueError:
                dur = 0
            minute = cumulative_sec / 60.0
            cumulative_sec += dur

        if minute is None:
            minute = 0.0
        if minute > 130:
            minute = 130

        delta, gf, ga = score_row(label)
        phase = classify_phase(label)
        g.actions.append(Action(minute, label, phase, delta, gf, ga))

    # If the file had no GameTime column, the minutes are a "duration-only"
    # clock that systematically undershoots real minutes (gaps between
    # actions aren't represented). Linearly rescale so the last action
    # sits near the full-time whistle.
    if not g.has_real_clock and g.actions:
        max_m = max(a.minute for a in g.actions)
        if max_m > 0:
            scale = 93.0 / max_m
            for a in g.actions:
                a.minute = a.minute * scale

    return g


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------


def plot_single_game(g: Game, out_dir: Path) -> None:
    if not g.actions:
        return
    xs = [a.minute for a in g.actions]
    cum = np.cumsum([a.delta for a in g.actions])
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(xs, cum, linewidth=1.8, color="#c8102e")  # Sunderland red
    ax.fill_between(xs, cum, 0, where=(cum >= 0), alpha=0.25, color="#c8102e")
    ax.fill_between(xs, cum, 0, where=(cum < 0), alpha=0.25, color="#1a1a1a")
    ax.axhline(0, color="#999", linewidth=0.8)

    for a in g.actions:
        if a.goal_for:
            ax.scatter(a.minute, np.interp(a.minute, xs, cum),
                       marker="*", s=200, color="green", zorder=5,
                       edgecolor="black", label="Goal for")
        elif a.goal_against:
            ax.scatter(a.minute, np.interp(a.minute, xs, cum),
                       marker="X", s=140, color="black", zorder=5,
                       edgecolor="red", label="Goal against")

    ax.set_xlim(0, max(95, max(xs) + 1))
    ax.set_title(f"Momentum curve — {g.short}")
    ax.set_xlabel("Match minute")
    ax.set_ylabel("Cumulative momentum")
    ax.grid(True, alpha=0.3)
    handles, labels = ax.get_legend_handles_labels()
    seen = {}
    for h, l in zip(handles, labels):
        seen[l] = h
    if seen:
        ax.legend(seen.values(), seen.keys(), loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / f"{g.date}_{g.venue}_{g.opponent}.png", dpi=120)
    plt.close(fig)


def plot_overlay(games: list[Game], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    grid = np.arange(0, 96, 1.0)
    series = []
    for g in games:
        if not g.actions:
            continue
        xs = np.array([a.minute for a in g.actions])
        deltas = np.array([a.delta for a in g.actions])
        order = np.argsort(xs)
        xs, deltas = xs[order], deltas[order]
        cum = np.cumsum(deltas)
        # interpolate on minute grid (step-hold)
        interp = np.zeros_like(grid, dtype=float)
        i = 0
        last = 0.0
        for k, m in enumerate(grid):
            while i < len(xs) and xs[i] <= m:
                last = cum[i]
                i += 1
            interp[k] = last
        series.append(interp)
        colour = "#c8102e" if g.venue == "Home" else "#1a1a1a"
        ax.plot(grid, interp, alpha=0.25, color=colour, linewidth=1)
    if series:
        arr = np.vstack(series)
        mean = arr.mean(axis=0)
        ax.plot(grid, mean, color="royalblue", linewidth=3, label="Mean across all games")
        ax.fill_between(grid, mean - arr.std(axis=0), mean + arr.std(axis=0),
                        color="royalblue", alpha=0.15, label="±1 SD")
    ax.axhline(0, color="#666", linewidth=1)
    for m in (15, 30, 45, 60, 75):
        ax.axvline(m, color="#ccc", linewidth=0.6, linestyle="--")
    ax.set_title("Momentum curves — all Sunderland games (red=home, black=away)")
    ax.set_xlabel("Match minute")
    ax.set_ylabel("Cumulative momentum")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def phase_buckets_15(games: list[Game]) -> dict[str, np.ndarray]:
    """Per-game momentum delta aggregated into 15-minute windows."""
    buckets = np.zeros((len(games), 6))
    for gi, g in enumerate(games):
        for a in g.actions:
            idx = min(int(a.minute // 15), 5)
            buckets[gi, idx] += a.delta
    return buckets


def plot_home_vs_away(games: list[Game], out: Path) -> None:
    home = [g for g in games if g.venue == "Home"]
    away = [g for g in games if g.venue == "Away"]
    bh = phase_buckets_15(home).mean(axis=0) if home else np.zeros(6)
    ba = phase_buckets_15(away).mean(axis=0) if away else np.zeros(6)
    labels = ["0-15", "15-30", "30-45", "45-60", "60-75", "75-90"]
    x = np.arange(6)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(x - 0.2, bh, width=0.4, label=f"Home (n={len(home)})", color="#c8102e")
    ax.bar(x + 0.2, ba, width=0.4, label=f"Away (n={len(away)})", color="#1a1a1a")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.axhline(0, color="#666", linewidth=0.8)
    ax.set_ylabel("Avg net momentum per 15-min window")
    ax.set_title("Home vs Away — average momentum by game phase")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


# ---- post-failure transitions --------------------------------------------


FAIL_PHASES = ["IP1", "IP2", "IP3", "IP4", "IP5", "OP2", "OP3", "OP4"]


def post_failure_transitions(games: list[Game], window: int = 3) -> dict:
    """For every failed (delta<0) action in FAIL_PHASES, record what happens
    in the next `window` actions. Returns dict[phase] = {"recover": n,
    "spiral": n, "neutral": n, "next_phase": Counter()}.
    """
    stats: dict[str, dict] = {p: {"fail_count": 0, "recover": 0, "spiral": 0,
                                   "neutral": 0, "goal_against_within": 0,
                                   "next": Counter()} for p in FAIL_PHASES}
    for g in games:
        acts = g.actions
        for i, a in enumerate(acts):
            if a.delta >= 0:
                continue
            if a.phase not in FAIL_PHASES:
                continue
            s = stats[a.phase]
            s["fail_count"] += 1
            follow = acts[i + 1 : i + 1 + window]
            net = sum(x.delta for x in follow)
            if net > 0:
                s["recover"] += 1
            elif net < 0:
                s["spiral"] += 1
            else:
                s["neutral"] += 1
            if any(x.goal_against for x in follow):
                s["goal_against_within"] += 1
            for x in follow:
                s["next"][x.phase] += 1
    return stats


# ---- phase conversion chains ---------------------------------------------


def ip_chain_conversion(games: list[Game]) -> dict:
    """How often does a successful IP action lead to the next IP level within
    a short window? We look at successes (delta>0) in IP2/IP3 and ask whether
    the subsequent chain (within 4 actions, before the next DefTrans or
    possession loss) reaches IP3/IP4/IP5/goal.
    """
    levels = ["IP1", "IP2", "IP3", "IP4", "IP5"]
    results = {lvl: Counter() for lvl in levels}
    for g in games:
        acts = g.actions
        for i, a in enumerate(acts):
            if a.delta <= 0:
                continue
            if a.phase not in levels:
                continue
            chain_reached = set([a.phase])
            goal = False
            for j in range(i + 1, min(i + 5, len(acts))):
                nxt = acts[j]
                # possession ended if DefTrans or fail on OP side
                if nxt.phase == "DefTrans":
                    break
                if nxt.phase.startswith("OP"):
                    break
                if nxt.goal_for:
                    goal = True
                if nxt.phase in levels:
                    chain_reached.add(nxt.phase)
            results[a.phase]["total_success"] += 1
            if "IP3" in chain_reached and a.phase in ("IP1", "IP2"):
                results[a.phase]["->IP3"] += 1
            if "IP4" in chain_reached and a.phase in ("IP1", "IP2", "IP3"):
                results[a.phase]["->IP4"] += 1
            if "IP5" in chain_reached and a.phase in ("IP1", "IP2", "IP3", "IP4"):
                results[a.phase]["->IP5"] += 1
            if goal:
                results[a.phase]["->goal"] += 1
    return results


def plot_conversion(results: dict, out: Path) -> None:
    labels = ["IP1", "IP2", "IP3", "IP4"]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    width = 0.2
    x = np.arange(len(labels))
    def pct(lvl, key):
        tot = results[lvl]["total_success"]
        return (results[lvl][key] / tot * 100) if tot else 0
    ip3 = [pct(l, "->IP3") for l in labels]
    ip4 = [pct(l, "->IP4") for l in labels]
    ip5 = [pct(l, "->IP5") for l in labels]
    goal = [pct(l, "->goal") for l in labels]
    ax.bar(x - 1.5 * width, ip3, width, label="→ reached IP3", color="#7fbf7f")
    ax.bar(x - 0.5 * width, ip4, width, label="→ reached IP4", color="#4a9e4a")
    ax.bar(x + 0.5 * width, ip5, width, label="→ reached IP5", color="#1a6a1a")
    ax.bar(x + 1.5 * width, goal, width, label="→ goal", color="gold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("% of successful actions that progressed")
    ax.set_title("Phase conversion chain — from successful IP action to next level")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


# ---- home-vs-away phase success rates ------------------------------------


def phase_success_rates(games: list[Game]) -> dict:
    by_venue = {"Home": defaultdict(lambda: [0, 0]),
                "Away": defaultdict(lambda: [0, 0])}
    for g in games:
        for a in g.actions:
            cell = by_venue[g.venue][a.phase]
            if a.delta > 0:
                cell[0] += 1
            if a.delta != 0:
                cell[1] += 1
    return by_venue


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def main() -> None:
    csvs = sorted(CSV_DIR.glob("*.csv"))
    games = [parse_game(p) for p in csvs]
    games = [g for g in games if g.actions]
    print(f"Parsed {len(games)} games")

    sg_dir = FIG_DIR / "per_game"
    sg_dir.mkdir(exist_ok=True)
    for g in games:
        plot_single_game(g, sg_dir)
    plot_overlay(games, FIG_DIR / "overlay_all_games.png")
    plot_home_vs_away(games, FIG_DIR / "home_vs_away_by_window.png")

    # Per-game summary table
    with open(TBL_DIR / "per_game_summary.csv", "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["date", "venue", "opponent", "n_actions",
                    "net_momentum", "first_half", "second_half",
                    "goals_for", "goals_against"])
        for g in games:
            net = sum(a.delta for a in g.actions)
            fh = sum(a.delta for a in g.actions if a.minute < 45)
            sh = sum(a.delta for a in g.actions if a.minute >= 45)
            gf = sum(1 for a in g.actions if a.goal_for)
            ga = sum(1 for a in g.actions if a.goal_against)
            w.writerow([g.date, g.venue, g.opponent, len(g.actions),
                        round(net, 2), round(fh, 2), round(sh, 2), gf, ga])

    # Post-failure analysis
    pf = post_failure_transitions(games)
    with open(TBL_DIR / "post_failure_transitions.csv", "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["phase", "failures", "recover%", "spiral%", "neutral%",
                    "goal_against_within3%", "top_next_phases"])
        for phase, s in pf.items():
            tot = s["fail_count"] or 1
            top = ", ".join(f"{k}({v})" for k, v in s["next"].most_common(4))
            w.writerow([phase, s["fail_count"],
                        round(100 * s["recover"] / tot, 1),
                        round(100 * s["spiral"] / tot, 1),
                        round(100 * s["neutral"] / tot, 1),
                        round(100 * s["goal_against_within"] / tot, 1),
                        top])

    # Phase conversion
    conv = ip_chain_conversion(games)
    plot_conversion(conv, FIG_DIR / "phase_conversion.png")
    with open(TBL_DIR / "phase_conversion.csv", "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["start_phase", "successes", "->IP3%", "->IP4%", "->IP5%", "->goal%"])
        for lvl in ["IP1", "IP2", "IP3", "IP4"]:
            tot = conv[lvl]["total_success"] or 1
            w.writerow([lvl, conv[lvl]["total_success"],
                        round(100 * conv[lvl]["->IP3"] / tot, 1),
                        round(100 * conv[lvl]["->IP4"] / tot, 1),
                        round(100 * conv[lvl]["->IP5"] / tot, 1),
                        round(100 * conv[lvl]["->goal"] / tot, 1)])

    # Home vs Away phase success rates
    sr = phase_success_rates(games)
    all_phases = sorted(set(list(sr["Home"].keys()) + list(sr["Away"].keys())))
    with open(TBL_DIR / "home_vs_away_success_rates.csv", "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["phase", "home_decided", "home_success%",
                    "away_decided", "away_success%", "delta_pp"])
        for p in all_phases:
            h = sr["Home"].get(p, [0, 0])
            a = sr["Away"].get(p, [0, 0])
            hr = (h[0] / h[1] * 100) if h[1] else None
            ar = (a[0] / a[1] * 100) if a[1] else None
            delta = (hr - ar) if (hr is not None and ar is not None) else ""
            w.writerow([p, h[1], round(hr, 1) if hr is not None else "",
                        a[1], round(ar, 1) if ar is not None else "",
                        round(delta, 1) if delta != "" else ""])

    print("Done. See analysis/figures and analysis/tables.")


if __name__ == "__main__":
    main()
