# 统计近三年 Releases & Tags 的 APK/AAB 指标（带 Rate Limit 检测 + 自动退避）
import os, csv, time, random, requests, concurrent.futures, logging, argparse
from datetime import datetime, timedelta, timezone
from dateutil import parser as dtparser

IN_CSV  = "android_repos_with_category_desc.csv"
OUT_CSV = "android_repos_with_5y_stats.csv"
WORKERS = 6                     # 建议别太高，6 比较稳
YEARS   = 5

# 多个 GitHub Token 轮换
TOKENS = [t.strip() for t in filter(None, [
    os.getenv("GITHUB_TOKEN_1"),
    os.getenv("GITHUB_TOKEN_2"),
    os.getenv("GITHUB_TOKEN_3"),
    os.getenv("GITHUB_TOKEN_4"),
    os.getenv("GITHUB_TOKEN_5"),
    os.getenv("GITHUB_CLASSIC_TOKEN"),
])]

# 连接复用
SESSION = requests.Session()

def gh_headers(token=None):
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "3y-release-tag-stats",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def _sleep_until_reset(resp, attempt):
    """根据响应头估算等待时间，带抖动"""
    now = int(time.time())
    retry_after = resp.headers.get("Retry-After")
    if retry_after and str(retry_after).isdigit():
        wait = int(retry_after)
    else:
        reset = resp.headers.get("X-RateLimit-Reset")
        if reset and str(reset).isdigit():
            wait = max(int(reset) - now, 1)
        else:
            # 次级限流或无头：指数退避
            wait = int(2.0 * (attempt + 1) ** 1.5)
    # 轻微抖动，避免“羊群效应”
    wait = wait + random.randint(1, 3)
    logging.warning(f"Rate limited. Sleeping {wait}s (attempt {attempt+1}). "
                    f"Remaining={resp.headers.get('X-RateLimit-Remaining')} "
                    f"Limit={resp.headers.get('X-RateLimit-Limit')}")
    time.sleep(wait)

def rest_get(url, params=None, timeout=40, retry=8):
    """
    带 Token 轮换 + RateLimit 检测 + 自动退避的 GET。
    - 命中 403/429 时根据响应头计算等待时间
    - 每次尝试更换 token
    """
    last_exc = None
    for k in range(retry):
        token = TOKENS[k % max(1, len(TOKENS))] if TOKENS else None
        try:
            resp = SESSION.get(url, headers=gh_headers(token), params=params, timeout=timeout)
            status = resp.status_code

            # 速率/滥用限流：403/429（有时也会 403 + X-RateLimit-Remaining: 0）
            if status in (403, 429):
                _sleep_until_reset(resp, k)
                continue

            # 其他暂时性网关错误
            if status in (502, 503, 504):
                time.sleep(1.2 * (k + 1))
                continue

            if status == 404:
                return resp

            resp.raise_for_status()

            # 如果快到配额边界，也稍微喘口气
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining and remaining.isdigit() and int(remaining) < 50:
                time.sleep(0.5)

            return resp

        except requests.RequestException as e:
            last_exc = e
            time.sleep(1.2 * (k + 1))

    raise RuntimeError(f"GET fail after retries: {url}") from last_exc

CUTOFF = datetime.now(timezone.utc) - timedelta(days=365*YEARS)

# ---------- Releases ----------
APK_EXTS  = (".apk", ".aab")  # 统计 APK + AAB
APK_CTYPE = ("application/vnd.android.package-archive", )  # 仅 APK 有稳定 ctype

def release_has_apk_assets(rel) -> bool:
    for a in (rel.get("assets") or []):
        name = (a.get("name") or "").lower()
        ctype = (a.get("content_type") or "").lower()
        url = (a.get("browser_download_url") or "").lower()
        if name.endswith(APK_EXTS) or url.endswith(APK_EXTS) or ctype in APK_CTYPE:
            return True
    return False

def releases_stats_3y(full_name: str):
    total = 0
    latest_dt = None
    apk_total = 0
    apk_latest_dt = None

    page = 1
    while True:
        r = rest_get(f"https://api.github.com/repos/{full_name}/releases",
                     params={"per_page": 100, "page": page})
        arr = r.json()
        if not isinstance(arr, list) or not arr:
            break

        for rel in arr:
            t = rel.get("published_at") or rel.get("created_at")
            if not t:
                continue
            tt = dtparser.parse(t)
            if tt.tzinfo is None:
                tt = tt.replace(tzinfo=timezone.utc)

            if tt < CUTOFF:
                continue

            total += 1
            if (latest_dt is None) or (tt > latest_dt):
                latest_dt = tt

            if release_has_apk_assets(rel):
                apk_total += 1
                if (apk_latest_dt is None) or (tt > apk_latest_dt):
                    apk_latest_dt = tt

        if len(arr) < 100:
            break
        page += 1

    return (
        total,
        latest_dt.isoformat() if latest_dt else "",
        apk_total,
        apk_latest_dt.isoformat() if apk_latest_dt else ""
    )

# ---------- Tags ----------
def tag_commit_datetime(full_name: str, sha: str):
    c = rest_get(f"https://api.github.com/repos/{full_name}/commits/{sha}").json()
    if not isinstance(c, dict):
        return None
    t = (c.get("commit") or {}).get("committer", {}).get("date")
    if not t:
        return None
    dt = dtparser.parse(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def tag_tree_has_apk(full_name: str, sha: str):
    tr = rest_get(f"https://api.github.com/repos/{full_name}/git/trees/{sha}",
                  params={"recursive": 1}).json()
    items = tr.get("tree") if isinstance(tr, dict) else None
    if not items:
        return False
    for it in items:
        path = (it.get("path") or "").lower()
        if path.endswith(APK_EXTS):
            return True
    return False

def tags_stats_3y(full_name: str):
    total = 0
    latest_dt = None
    apk_total = 0
    apk_latest_dt = None

    # page = 1
    # while True:
    #     r = rest_get(f"https://api.github.com/repos/{full_name}/tags",
    #                  params={"per_page": 100, "page": page})
    #     arr = r.json()
    #     if not isinstance(arr, list) or not arr:
    #         break

    #     for tag in arr:
    #         sha = (tag.get("commit") or {}).get("sha")
    #         if not sha:
    #             continue
    #         dt = tag_commit_datetime(full_name, sha)
    #         if not dt or dt < CUTOFF:
    #             continue

    #         total += 1
    #         if (latest_dt is None) or (dt > latest_dt):
    #             latest_dt = dt

    #         if tag_tree_has_apk(full_name, sha):
    #             apk_total += 1
    #             if (apk_latest_dt is None) or (dt > apk_latest_dt):
    #                 apk_latest_dt = dt

    #     if len(arr) < 100:
    #         break
    #     page += 1

    return (
        total,
        latest_dt.isoformat() if latest_dt else "",
        apk_total,
        apk_latest_dt.isoformat() if apk_latest_dt else ""
    )

# ---------- 日志解析 ----------
def parse_log_results(log_file='five_year_stats.log'):
    """从日志文件中解析结果"""
    results = {}
    if not os.path.exists(log_file):
        return results
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                # 匹配格式：timestamp - owner/repo -> R3y=X/Y latestR=... latestR_apk=... | T3y=A/B latestT=... latestT_apk=...
                if ' -> ' in line and 'R3y=' in line:
                    parts = line.strip().split(' -> ')
                    if len(parts) >= 2:
                        repo_part = parts[0]
                        data_part = parts[1]
                        
                        # 提取仓库名
                        if ' - ' in repo_part:
                            repo_name = repo_part.split(' - ')[-1].strip()
                            
                            # 解析数据部分
                            # 格式：R3y=X/Y latestR=... latestR_apk=... | T3y=A/B latestT=... latestT_apk=...
                            try:
                                # 分割 Release 和 Tag 数据
                                if ' | ' in data_part:
                                    r_part, t_part = data_part.split(' | ', 1)
                                else:
                                    r_part = data_part
                                    t_part = ""
                                
                                # 解析 Release 数据
                                r_total = 0
                                r_apk_total = 0
                                r_latest = ""
                                r_apk_latest = ""
                                
                                if 'R3y=' in r_part:
                                    r3y_match = r_part.split('R3y=')[1].split()[0]
                                    if '/' in r3y_match:
                                        r_total, r_apk_total = map(int, r3y_match.split('/'))
                                
                                if 'latestR=' in r_part:
                                    r_latest = r_part.split('latestR=')[1].split()[0]
                                if 'latestR_apk=' in r_part:
                                    r_apk_latest = r_part.split('latestR_apk=')[1].split()[0]
                                
                                # 解析 Tag 数据
                                t_total = 0
                                t_apk_total = 0
                                t_latest = ""
                                t_apk_latest = ""
                                
                                if 'T3y=' in t_part:
                                    t3y_match = t_part.split('T3y=')[1].split()[0]
                                    if '/' in t3y_match:
                                        t_total, t_apk_total = map(int, t3y_match.split('/'))
                                
                                if 'latestT=' in t_part:
                                    t_latest = t_part.split('latestT=')[1].split()[0]
                                if 'latestT_apk=' in t_part:
                                    t_apk_latest = t_part.split('latestT_apk=')[1].split()[0]
                                
                                # 处理 N/A 值
                                r_latest = r_latest if r_latest != 'N/A' else ""
                                r_apk_latest = r_apk_latest if r_apk_latest != 'N/A' else ""
                                t_latest = t_latest if t_latest != 'N/A' else ""
                                t_apk_latest = t_apk_latest if t_apk_latest != 'N/A' else ""
                                
                                results[repo_name] = {
                                    "full": repo_name,
                                    "release_3y_total": r_total,
                                    "release_3y_latest": r_latest,
                                    "release_3y_apk_total": r_apk_total,
                                    "release_3y_apk_latest": r_apk_latest,
                                    "tag_3y_total": t_total,
                                    "tag_3y_latest": t_latest,
                                    "tag_3y_apk_total": t_apk_total,
                                    "tag_3y_apk_latest": t_apk_latest,
                                }
                            except Exception as e:
                                print(f"解析仓库 {repo_name} 的数据时出错: {e}")
                                continue
    except Exception as e:
        print(f"读取日志文件时出错: {e}")
    
    return results

# ---------- 单 repo ----------
def process_one(full_name: str):
    try:
        r_total, r_latest, r_apk_total, r_apk_latest = releases_stats_3y(full_name)
        t_total, t_latest, t_apk_total, t_apk_latest = tags_stats_3y(full_name)
        logging.info(
            f"{full_name} -> R3y={r_total}/{r_apk_total} latestR={r_latest or 'N/A'} latestR_apk={r_apk_latest or 'N/A'} | "
            f"T3y={t_total}/{t_apk_total} latestT={t_latest or 'N/A'} latestT_apk={t_apk_latest or 'N/A'}"
        )
        return {
            "full": full_name,
            "release_3y_total": r_total,
            "release_3y_latest": r_latest,
            "release_3y_apk_total": r_apk_total,
            "release_3y_apk_latest": r_apk_latest,
            "tag_3y_total": t_total,
            "tag_3y_latest": t_latest,
            "tag_3y_apk_total": t_apk_total,
            "tag_3y_apk_latest": t_apk_latest,
        }
    except Exception as e:
        logging.error(f"ERROR {full_name} - {e}")
        return {
            "full": full_name,
            "release_3y_total": 0,
            "release_3y_latest": "",
            "release_3y_apk_total": 0,
            "release_3y_apk_latest": "",
            "tag_3y_total": 0,
            "tag_3y_latest": "",
            "tag_3y_apk_total": 0,
            "tag_3y_apk_latest": "",
        }

# ---------- 主流程 ----------
def main():
    parser = argparse.ArgumentParser(description="3-year stats for releases/tags with APK/AAB (rate-limit aware)")
    parser.add_argument("--in", dest="in_csv", default=IN_CSV)
    parser.add_argument("--out", dest="out_csv", default=OUT_CSV)
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--refer_log", action="store_true", help="Skip repos already processed in three_year_stats.log")
    parser.add_argument("--write_from_log", action="store_true", help="Read results from three_year_stats.log and write to CSV")
    args = parser.parse_args()

    in_csv = args.in_csv
    out_csv = args.out_csv
    workers = args.workers
    refer_log = args.refer_log
    write_from_log = args.write_from_log

    # 如果启用 write_from_log，直接从日志读取结果
    if write_from_log:
        print("从日志文件读取结果...")
        log_results = parse_log_results('three_year_stats.log')
        print(f"从日志中解析到 {len(log_results)} 个仓库的结果")
        
        with open(in_csv, newline="", encoding="utf-8-sig") as fin, \
             open(out_csv, "w", newline="", encoding="utf-8-sig") as fout:
            r = csv.DictReader(fin)
            fieldnames = r.fieldnames + [
                "release_3y_total","release_3y_latest",
                "release_3y_apk_total","release_3y_apk_latest",
                "tag_3y_total","tag_3y_latest",
                "tag_3y_apk_total","tag_3y_apk_latest",
            ]
            w = csv.DictWriter(fout, fieldnames=fieldnames)
            w.writeheader()
            
            written = 0
            for row in r:
                full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
                info = log_results.get(full, None)
                if info:
                    row["release_3y_total"]       = info["release_3y_total"]
                    row["release_3y_latest"]      = info["release_3y_latest"]
                    row["release_3y_apk_total"]   = info["release_3y_apk_total"]
                    row["release_3y_apk_latest"]  = info["release_3y_apk_latest"]
                    row["tag_3y_total"]           = info["tag_3y_total"]
                    row["tag_3y_latest"]          = info["tag_3y_latest"]
                    row["tag_3y_apk_total"]       = info["tag_3y_apk_total"]
                    row["tag_3y_apk_latest"]      = info["tag_3y_apk_latest"]
                    written += 1
                w.writerow(row)
            
            print(f"完成：从日志写出 {written} 行 -> {out_csv}")
        return

    # 如果启用 refer_log，读取已处理的仓库列表
    processed_repos = set()
    if refer_log and os.path.exists('three_year_stats.log'):
        try:
            with open('three_year_stats.log', 'r', encoding='utf-8') as f:
                for line in f:
                    # 匹配日志中的仓库名格式：timestamp - owner/repo -> ...
                    if ' -> ' in line:
                        repo_part = line.split(' -> ')[0]
                        if ' - ' in repo_part:
                            repo_name = repo_part.split(' - ')[-1].strip()
                            processed_repos.add(repo_name)
            print(f"从日志中读取到 {len(processed_repos)} 个已处理的仓库")
        except Exception as e:
            print(f"读取日志文件时出错: {e}")

    with open(in_csv, newline="", encoding="utf-8-sig") as fin, \
         open(out_csv, "w", newline="", encoding="utf-8-sig") as fout:
        r = csv.DictReader(fin)
        fieldnames = r.fieldnames + [
            "release_3y_total","release_3y_latest",
            "release_3y_apk_total","release_3y_apk_latest",
            "tag_3y_total","tag_3y_latest",
            "tag_3y_apk_total","tag_3y_apk_latest",
        ]
        w = csv.DictWriter(fout, fieldnames=fieldnames)
        w.writeheader()

        rows, fulls = [], []
        skipped_count = 0
        for row in r:
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            rows.append(row)
            
            # 如果启用 refer_log 且仓库已处理过，则跳过
            if refer_log and full in processed_repos:
                skipped_count += 1
                print(f"跳过已处理的仓库: {full}")
                continue
                
            fulls.append(full)
        
        if refer_log:
            print(f"总共跳过 {skipped_count} 个已处理的仓库，剩余 {len(fulls)} 个仓库需要处理")

        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(process_one, fn): fn for fn in fulls}
            for fut in concurrent.futures.as_completed(futs):
                info = fut.result()
                results[info["full"]] = info

        written = 0
        for row in rows:
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            
            # 如果启用 refer_log 且仓库已处理过，从日志中恢复数据
            if refer_log and full in processed_repos:
                # 从日志中解析数据（这里简化处理，实际可能需要更复杂的解析）
                # 为了简化，这里先写入空值，后续可以改进
                row["release_3y_total"]       = ""
                row["release_3y_latest"]      = ""
                row["release_3y_apk_total"]   = ""
                row["release_3y_apk_latest"]  = ""
                row["tag_3y_total"]           = ""
                row["tag_3y_latest"]          = ""
                row["tag_3y_apk_total"]       = ""
                row["tag_3y_apk_latest"]      = ""
                w.writerow(row)
                written += 1
                continue
            
            info = results.get(full, None)
            if not info:
                continue
            row["release_3y_total"]       = info["release_3y_total"]
            row["release_3y_latest"]      = info["release_3y_latest"]
            row["release_3y_apk_total"]   = info["release_3y_apk_total"]
            row["release_3y_apk_latest"]  = info["release_3y_apk_latest"]
            row["tag_3y_total"]           = info["tag_3y_total"]
            row["tag_3y_latest"]          = info["tag_3y_latest"]
            row["tag_3y_apk_total"]       = info["tag_3y_apk_total"]
            row["tag_3y_apk_latest"]      = info["tag_3y_apk_latest"]
            w.writerow(row)
            written += 1

        print(f"完成：写出 {written} 行 -> {out_csv}")

if __name__ == "__main__":
    logging.basicConfig(
        filename='five_year_stats.log',
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        encoding='utf-8',
        filemode='a'
    )
    main()
