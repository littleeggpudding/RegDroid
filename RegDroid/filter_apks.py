# 过滤raw results  （按 Star=0 + 近三年未更新跳过）
import os, csv, time, json, pathlib, requests, concurrent.futures
from datetime import datetime, timezone, timedelta
from dateutil import parser as dtparser
import logging
import argparse

# 添加 base64 导入
import base64

IN_CSV  = "android_repos.csv"                       # 第一次结果
OUT_CSV = "android_repos_with_apk2plus.csv"         # 输出（仅≥2）
CACHE   = pathlib.Path("cache_releases")            # 简单缓存目录
WORKERS = 10                                        # 并发度
MIN_APK_RELEASES = 2                                 # 改成 3 表示"至少 3 个"
LOOKBACK_DAYS = None                                 # 只统计近 N 天；None 表示不限制（针对 releases）

# 可配置多个 PAT，轮换使用以提高吞吐（Classic 或 Fine-grained 都可）
TOKENS = [t.strip() for t in filter(None, [
    os.getenv("GITHUB_TOKEN_1"),
    os.getenv("GITHUB_TOKEN_2"),
    os.getenv("GITHUB_CLASSIC_TOKEN"),
])]

def gh_headers(token=None):
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "fast-apk2-filter",
    }
    if token: h["Authorization"] = f"Bearer {token}"
    return h

def rest_get(url, params=None, timeout=40, retry=5):
    for k in range(retry):
        token = TOKENS[k % max(1, len(TOKENS))] if TOKENS else None
        try:
            r = requests.get(url, headers=gh_headers(token), params=params, timeout=timeout)
            if r.status_code in (403, 429, 502, 503):
                time.sleep(1.2*(k+1)); continue
            if r.status_code == 404: return r
            r.raise_for_status(); return r
        except requests.RequestException:
            time.sleep(1.2*(k+1))
    raise RuntimeError(f"GET fail: {url}")

def ensure_dir(p: pathlib.Path): p.mkdir(parents=True, exist_ok=True)
def cache_load(p: pathlib.Path):
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return None
    return None
def cache_save(p: pathlib.Path, data):
    ensure_dir(p.parent)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def fetch_readme_content(repo_full_name: str):
    url = f"https://api.github.com/repos/{repo_full_name}/readme"
    try:
        r = rest_get(url, timeout=30)
        data = r.json()
        if "message" in data:
            logging.warning(f"GitHub API warning for {repo_full_name}: {data['message']}")
        return data
    except Exception as e:
        logging.error(f"Error fetching README for {repo_full_name}: {e}")
        return {}

def has_fdroid_or_gp_in_readme(repo_full_name: str) -> bool:
    """检查 README 是否包含 F-Droid 或 Google Play 链接（忽略大小写）"""
    try:
        data = fetch_readme_content(repo_full_name)
        # 被限流或其他错误时，GitHub会返回 {"message": "..."}；这时不要误判为 False，可记录并跳过
        if not data or "message" in data and "rate limit" in data["message"].lower():
            logging.warning(f"Rate-limited on README for {repo_full_name}")
            return False

        content = data.get("content")
        if not content:
            return False

        # GitHub返回 base64（可能包含换行）；按声明的编码处理
        if (data.get("encoding") or "").lower() == "base64":
            try:
                raw = base64.b64decode(content, validate=False).decode("utf-8", errors="ignore")
            except Exception:
                raw = ""
        else:
            # 极少数情况下直接是明文
            raw = str(content)

        raw_l = raw.lower()
        return ("f-droid.org" in raw_l) or ("play.google.com" in raw_l)
    except Exception as e:
        logging.error(f"Error checking README for {repo_full_name}: {e}")
        return False

def has_apk(rel) -> bool:
    for a in (rel.get("assets") or []):
        name = (a.get("name") or "").lower()
        ctype = (a.get("content_type") or "").lower()
        url = (a.get("browser_download_url") or "").lower()
        if name.endswith(".apk") or url.endswith(".apk") or ctype == "application/vnd.android.package-archive":
            return True
    return False

def count_apk_releases_min(full_name: str):
    """达到 MIN_APK_RELEASES 就早停；按时间从新到旧翻页。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS) if LOOKBACK_DAYS else None
    total = 0
    latest_dt = None
    page = 1

    while True:
        r = rest_get(f"https://api.github.com/repos/{full_name}/releases", 
                     params={"per_page":100, "page":page})
        arr = r.json()
        
        # 没有更多 releases 就退出
        if not arr:
            break

        for rel in arr:
            t = rel.get("published_at") or rel.get("created_at")
            tt = dtparser.parse(t) if t else None
            
            # 超过时间范围就退出
            if cutoff and tt and tt < cutoff:
                return total, (latest_dt.isoformat() if latest_dt else "")
            
            # 检查是否有 APK
            if has_apk(rel):
                total += 1
                if (latest_dt is None) or (tt and tt > latest_dt):
                    latest_dt = tt
                
                # 找到足够的 APK releases 就返回
                if total >= MIN_APK_RELEASES:
                    return total, (latest_dt.isoformat() if latest_dt else "")
        
        # 如果这一页少于 100 个，说明已经是最后一页了
        if len(arr) < 100:
            break
        
        page += 1

    return total, (latest_dt.isoformat() if latest_dt else "")

def process_one(full_name: str):
    try:
        # 先检查 README 中是否有 F-Droid 信息
        fdroid_in_readme = has_fdroid_or_gp_in_readme(full_name)
        
        # 如果 README 中没有 F-Droid，直接返回
        if not fdroid_in_readme:
            return full_name, 0, "", False
        
        # 如果 README 中有 F-Droid，再检查 APK releases 暂时不用
        # cnt, latest = count_apk_releases_min(full_name)
        cnt, latest = 0, ""
        
        return full_name, cnt, latest, fdroid_in_readme
    except Exception as e:
        logging.error(f"ERROR {full_name} - {str(e)}")
        return full_name, 0, "", False


def main(start_line=0, use_target_lines=False):
    ensure_dir(CACHE)

    # 如果使用目标行号
    target_lines = set()
    if use_target_lines:
        try:
            with open('check_log.log', 'r', encoding='utf-8') as f:
                # 跳过前几行描述性文本
                f.readline()  # 总行数
                f.readline()  # 最大行号
                f.readline()  # 缺失行数
                f.readline()  # 空行
                f.readline()  # "缺失的行号:"
                
                # 读取所有缺失的行号
                for line in f:
                    target_lines.update(map(int, line.strip().split(',')))
        except FileNotFoundError:
            print("未找到 check_log.log 文件")
            return

    with open(IN_CSV, newline="", encoding="utf-8-sig") as fin, \
         open(OUT_CSV, "a", newline="", encoding="utf-8-sig") as fout:
        r = csv.DictReader(fin)
        fieldnames = r.fieldnames + ["apk_release_count", "latest_apk_date_utc", "fdroid_in_readme"]
        w = csv.DictWriter(fout, fieldnames=fieldnames)
        
        # 只在文件为空时写入表头
        if fout.tell() == 0:
            w.writeheader()

        rows, fulls = [], []
        total_repos = 0
        skipped_repos = 0

        # 跳过前面的行
        for _ in range(start_line):
            next(r, None)

        # 收集需要处理的仓库
        for line_num, row in enumerate(r, start=start_line):
            # 如果使用目标行号，且当前行号不在目标行号中，则跳过
            if use_target_lines and line_num not in target_lines:
                continue

            total_repos += 1
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            
            rows.append((line_num, row))
            fulls.append(full)

        # 处理仓库
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(process_one, fn): fn for fn in fulls}
            for fut in concurrent.futures.as_completed(futs):
                full, cnt, latest, fdroid_in_readme = fut.result()
                
                # 找到对应的行号
                line_num = next((ln for ln, r in rows if (r.get("full_name") or f"{r.get('owner')}/{r.get('repo')}") == full), "N/A")
                
                # 条件：APK releases >= 2 或 README 中有 F-Droid
                # if cnt >= MIN_APK_RELEASES or fdroid_in_readme:
                if fdroid_in_readme:
                    logging.info(f"LINE {line_num} - SUCCESS {full} - APK Releases: {cnt}, F-Droid in README: {fdroid_in_readme}")
                else:
                    logging.info(f"LINE {line_num} - DROP {full} - APK Releases: {cnt}, F-Droid in README: {fdroid_in_readme}")
                
                results[full] = (cnt, latest, fdroid_in_readme)

        kept = 0
        for line_num, row in rows:
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            cnt, latest, fdroid_in_readme = results.get(full, (0, "", False))
            
            # 条件：APK releases >= 2 或 README 中有 F-Droid
            if fdroid_in_readme:
                row["apk_release_count"] = cnt
                row["latest_apk_date_utc"] = latest
                row["fdroid_in_readme"] = fdroid_in_readme
                w.writerow(row)
                kept += 1

        # 总结日志
        logging.info(f"总仓库数: {total_repos}")
        logging.info(f"跳过仓库数: {skipped_repos}")
        logging.info(f"处理仓库数: {len(rows)}")
        logging.info(f"保留仓库数: {kept}")

        print(
            f"完成：输入 {total_repos} 个仓库，"
            f"跳过 {skipped_repos} 个，"
            f"处理 {len(rows)} 个，"
            f"保留 {kept} 个（≥{MIN_APK_RELEASES} 个含APK的发布或README含F-Droid）。"
            f"输出：{OUT_CSV}"
        )

if __name__ == "__main__":
    # 添加命令行参数解析
    parser = argparse.ArgumentParser(description="Filter GitHub repositories with APK releases")
    parser.add_argument("--start", type=int, default=0, 
                        help="行号，从指定行开始处理（默认从0开始）")
    parser.add_argument("--target", action="store_true", 
                        help="使用 check_log.log 中的目标行号")
    
    # 配置日志（追加模式）
    logging.basicConfig(
        filename='filter_repos.log', 
        level=logging.INFO, 
        format='%(asctime)s - %(message)s',
        encoding='utf-8',
        filemode='a'  # 追加模式
    )

    # 解析参数并运行
    args = parser.parse_args()
    main(start_line=args.start, use_target_lines=args.target)
