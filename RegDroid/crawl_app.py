# crawl_android_repos.py
import os, csv, time, math, requests
from datetime import date, timedelta
import random
import logging

# 手动设置编码
handler = logging.FileHandler('crawl_app.log', encoding='utf-8')
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# ====== 在这里硬编码多个 tokens（classic 或 fine-grained 都可；建议 classic）======
TOKENS = [
    "YOUR_GITHUB_TOKEN_1",   # TODO: 换成你的 token
    "YOUR_GITHUB_TOKEN_2",
    "YOUR_GITHUB_TOKEN_3",
    "YOUR_GITHUB_TOKEN_4",
]
TOKENS = [t.strip() for t in TOKENS if t.strip()]  # 过滤空白

BASE_QS = [
    'fork:false archived:false language:Java android in:name,description,readme stars:>0',
    'fork:false archived:false language:Kotlin android in:name,description,readme stars:>0',
]

DATE_START = date(2008, 1, 1)
DATE_END   = date.today()

PUSHED_LOOKBACK_DAYS = 365 * 3
PUSHED_SINCE = (DATE_END - timedelta(days=PUSHED_LOOKBACK_DAYS)).isoformat()

OUT_CSV = 'android_repos.csv'
DOWNLOAD_ZIP = False
ZIP_OUT_DIR = 'repo_zip'

# 当前使用的请求头（会在每个 Base Query 开始时切换 Authorization）
HEAD = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "android-repo-crawler"
}

def _mask_token(t: str) -> str:
    if not t: return "(none)"
    if len(t) <= 8: return t[:2] + "..." + t[-2:]
    return t[:4] + "..." + t[-4:]

def set_active_token(token: str):
    """在进入每个 Base Query 之前调用，切换当前用的 Token。"""
    if token:
        HEAD["Authorization"] = f"Bearer {token}"
    else:
        HEAD.pop("Authorization", None)

def gh_get(url: str, params=None, timeout=40, retry=5):
    for k in range(retry):
        r = requests.get(url, headers=HEAD, params=params, timeout=timeout)
        # search 接口可能触发二级限流或 403；简单退避
        if r.status_code in (403, 429, 502, 503):
            time.sleep(1.2 * (k + 1)); continue
        r.raise_for_status(); return r
    return r  # 让上层抛

def search_count(q: str) -> int:
    r = gh_get("https://api.github.com/search/repositories",
               params={"q": q, "per_page": 1})
    j = r.json()
    if not j.get("total_count"):
        if j.get("message") or j.get("errors"):
            logging.debug(f"DEBUG search_count: {{'q': {q}, 'message': {j.get('message')}, 'errors': {j.get('errors')}}}")
    return int(j.get("total_count", 0))

def search_page(q: str, page: int):
    r = gh_get("https://api.github.com/search/repositories",
               params={"q": q, "per_page": 100, "page": page,
                       "sort": "stars", "order": "desc"})
    return r.json().get("items", [])

def daterange_str(d1: date, d2: date) -> str:
    return f"{d1.isoformat()}..{d2.isoformat()}"

def mid_date(d1: date, d2: date) -> date:
    return d1 + timedelta(days=(d2 - d1).days // 2)

def ensure_dir(p): os.makedirs(p, exist_ok=True)

def zip_url(full_name: str, default_branch: str) -> str:
    return f"https://api.github.com/repos/{full_name}/zipball/{default_branch}"

def download(url: str, out_path: str):
    with gh_get(url, timeout=120, retry=6) as r:
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk: f.write(chunk)

def collect_range(base_q: str, d1: date, d2: date, writer: csv.writer, seen_ids: set):
    if d1 > d2: return
    q = f"{base_q} created:{daterange_str(d1, d2)}"
    cnt = search_count(q)
    logging.info(f"[{d1}..{d2}] total_count={cnt}  |  base_q={base_q}")

    if cnt == 0: return

    if cnt >= 1000:
        m = mid_date(d1, d2)
        if m == d1:
            for bucket in ["0..99", "100..*"]:
                qb = f"{base_q} created:{daterange_str(d1, d2)} stars:{bucket}"
                cb = search_count(qb)
                logging.info(f"  stars:{bucket} => {cb}")
                if cb == 0: continue
                if cb >= 1000:
                    collect_by_day(base_q, d1, d2, writer, seen_ids, stars_bucket=bucket)
                else:
                    fetch_and_write(qb, cb, writer, seen_ids)
            return
        collect_range(base_q, d1, m, writer, seen_ids)
        collect_range(base_q, m + timedelta(days=1), d2, writer, seen_ids)
        return

    fetch_and_write(q, cnt, writer, seen_ids)

def collect_by_day(base_q: str, d1: date, d2: date, writer: csv.writer, seen_ids: set, stars_bucket: str):
    cur = d1
    while cur <= d2:
        q = f"{base_q} created:{cur.isoformat()}..{cur.isoformat()} stars:{stars_bucket}"
        cnt = search_count(q)
        logging.info(f"    [{cur}] {stars_bucket} => {cnt}")
        if cnt > 0:
            if cnt >= 1000:
                for b in ["0..49","50..99","100..199","200..499","500..*"]:
                    qb = f"{base_q} created:{cur.isoformat()}..{cur.isoformat()} stars:{b}"
                    cb = search_count(qb)
                    if cb > 0:
                        fetch_and_write(qb, cb, writer, seen_ids)
                        time.sleep(0.15)
            else:
                fetch_and_write(q, cnt, writer, seen_ids)
        cur += timedelta(days=1); time.sleep(0.1)

def fetch_and_write(q: str, total_count: int, writer: csv.writer, seen_ids: set):
    pages = min(10, math.ceil(total_count / 100))
    for p in range(1, pages + 1):
        items = search_page(q, p)
        if not items: break
        for repo in items:
            rid = repo.get("id")
            if rid in seen_ids: continue
            seen_ids.add(rid)

            full = repo.get("full_name", "")
            default_branch = repo.get("default_branch") or "main"
            zurl = zip_url(full, default_branch)

            writer.writerow([
                repo.get("owner", {}).get("login", ""),
                repo.get("name", ""),
                full,
                repo.get("html_url", ""),
                repo.get("stargazers_count", 0),
                repo.get("forks_count", 0),
                repo.get("language", ""),
                repo.get("created_at", ""),
                repo.get("updated_at", ""),
                default_branch,
                zurl
            ])

            if DOWNLOAD_ZIP:
                ensure_dir(ZIP_OUT_DIR)
                safe = full.replace("/", "#")
                out = os.path.join(ZIP_OUT_DIR, f"{safe}@{default_branch}.zip")
                if not os.path.exists(out):
                    try: download(zurl, out)
                    except Exception as e: logging.error(f"      zip fail: {full} -> {e}")
        time.sleep(0.15 + random.random()*0.2)

def main():
    logging.info(f"Tokens loaded: {len(TOKENS)}")
    if not TOKENS:
        logging.warning("⚠️ 未配置 TOKENS，将以匿名方式请求（非常容易限速）。")

    seen = set()
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "owner","repo","full_name","html_url","stars","forks",
            "language","created_at","updated_at","default_branch","zipball_url"
        ])

        for i, base_q in enumerate(BASE_QS):
            token = TOKENS[i % len(TOKENS)] if TOKENS else ""
            set_active_token(token)

            q_with_pushed = f"{base_q} pushed:>={PUSHED_SINCE}"

            logging.info(f"\n=== Base query [{i+1}/{len(BASE_QS)}] ===")
            logging.info(f"Token: { _mask_token(token) }")
            logging.info(f"Query : {q_with_pushed}")

            # 这里要把 q_with_pushed 传进去，而不是 base_q
            collect_range(q_with_pushed, DATE_START, DATE_END, w, seen)

    logging.info(f"Done. Wrote {len(seen)} rows -> {OUT_CSV}")

if __name__ == "__main__":
    main()
