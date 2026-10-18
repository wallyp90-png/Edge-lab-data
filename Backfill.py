import argparse, json, os, time
from pathlib import Path
import pandas as pd

URL = "https://mcp.endzoneapi.com/v1/get_player_props"
CREDITS = 10


def game_ids(seasons, weeks):
    import nflreadpy as nfl
    s = nfl.load_schedules(list(seasons)).to_pandas()
    s = s[(s.game_type == "REG") & s.home_score.notna()]
    if weeks:
        s = s[s.week.isin(list(weeks))]
    return sorted(s.game_id)


def fetch(gid, key, cache, session=None):
    p = Path(cache) / f"{gid}.json"
    if p.exists():
        return json.loads(p.read_text()), 0
    if session is None:
        import requests as session
    r = session.post(URL, json={"game_id": gid}, headers={"x-api-key": key, "Content-Type": "application/json"}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(r.json()))
    return r.json(), CREDITS


def pull(ids, max_credits, cache, key, session=None):
    spent = done = 0
    for g in ids:
        cached = (Path(cache) / f"{g}.json").exists()
        if not cached and spent + CREDITS > max_credits:
            return dict(status="stopped_at_budget", games=done, credits_spent=spent)
        _, paid = fetch(g, key, cache, session)
        spent += paid
        done += 1
        if paid:
            time.sleep(0.3)
    return dict(status="complete", games=done, credits_spent=spent)


def tidy(cache, out):
    rows = []
    for f in sorted(Path(cache).glob("*.json")):
        for p in json.loads(f.read_text()).get("props", []):
            rows.append({"game_id": p.get("game_id", f.stem), "player_name": p.get("player_name"), "gsis_id": p.get("gsis_id"), "market": p.get("market"),
                         "bookmaker": p.get("bookmaker"), "line": p.get("line"), "over_odds": p.get("over_odds"), "under_odds": p.get("under_odds"), "captured_at": p.get("captured_at")})
    df = pd.DataFrame(rows)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return df


def summarize(df):
    if not len(df):
        return {"rows": 0, "note": "no rows returned"}
    return {"rows": int(len(df)), "games": int(df.game_id.nunique()), "markets": df.market.value_counts().head(25).to_dict(),
            "bookmakers": df.bookmaker.value_counts().to_dict(), "share_missing_gsis_id": float(df.gsis_id.isna().mean())}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int, default=[2025])
    ap.add_argument("--weeks", nargs="*", type=int, default=[1, 2, 3])
    ap.add_argument("--max-credits", type=int, default=480)
    a = ap.parse_args()
    key = os.environ.get("ENDZONEAPI_API_KEY")
    if not key:
        raise SystemExit("ENDZONEAPI_API_KEY is not set")
    res = pull(game_ids(a.seasons, a.weeks), a.max_credits, "data/props_private/raw", key)
    summ = {"pull": res, **summarize(tidy("data/props_private/raw", "data/props_private/props_tidy.csv"))}
    Path("data/props_summary").mkdir(parents=True, exist_ok=True)
    Path("data/props_summary/props_summary.json").write_text(json.dumps(summ, indent=2, default=str))
    print(json.dumps(summ, indent=2, default=str)[:2000])
