# 过滤raw results  (GitHub Releases APK >=2 或 F-Droid APK >=2 保留)
import os, csv, time, json, pathlib, requests, concurrent.futures, re, base64  # 添加 base64
from datetime import datetime, timezone, timedelta
from dateutil import parser as dtparser
import logging
import argparse

IN_CSV  = "android_repos_with_high_downloads_high_stars.csv"
OUT_CSV = "android_repos_with_apk2plus_after_filter.csv"
WORKERS = 10
MIN_APK_RELEASES = 2

# 可配置多个 PAT，提高吞吐
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

# ---------- GitHub Releases: 统计含 APK 的 release 数 ----------
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
    total = 0
    latest_dt = None
    page = 1

    while True:
        r = rest_get(f"https://api.github.com/repos/{full_name}/releases", 
                     params={"per_page":100, "page":page})
        arr = r.json()
        if not isinstance(arr, list):
            break
        if not arr:
            break

        for rel in arr:
            t = rel.get("published_at") or rel.get("created_at")
            tt = dtparser.parse(t) if t else None
            if has_apk(rel):
                total += 1
                if (latest_dt is None) or (tt and tt > latest_dt):
                    latest_dt = tt
                if total >= MIN_APK_RELEASES:
                    return total, (latest_dt.isoformat() if latest_dt else "")
        if len(arr) < 100:
            break
        page += 1

    return total, (latest_dt.isoformat() if latest_dt else "")


# --------- 从 README 抽 Google Play 包名 ----------
# 更宽松：不限定 http/https，抓取任何 play.google.com/...id= 的包名
PLAY_LINK_RE = re.compile(
    r"play\.google\.com/store/apps/details\?[^)\s\"'>]*\bid=([a-zA-Z0-9._]+)",
    re.IGNORECASE
)

def fetch_readme_text(full_name: str) -> str:
    """读仓库 README，返回明文字符串（UTF-8），失败则返回空串"""
    url = f"https://api.github.com/repos/{full_name}/readme"
    try:
        r = rest_get(url, timeout=30)
        data = r.json()
        content = data.get("content")
        if not content:
            return ""
        if (data.get("encoding") or "").lower() == "base64":
            try:
                return base64.b64decode(content, validate=False).decode("utf-8", errors="ignore")
            except Exception:
                return ""
        return str(content)
    except Exception as e:
        logging.error(f"Error fetching README for {full_name}: {e}")
        return ""

def extract_play_packages(text: str):
    """从 README 文本中抽取所有 Google Play 包名（set）"""
    if not text:
        return set()
    return set(m.group(1) for m in PLAY_LINK_RE.finditer(text))


def fdroid_apk_count(pkg: str) -> int:
    """
    调用 F-Droid API，返回 packages 数组长度（即版本数）；异常时返回 0，并打印错误
    """
    url = f"https://f-droid.org/api/v1/packages/{pkg}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code == 404:
            return 0
        if r.status_code != 200:
            logging.warning(f"F-Droid API 非 200 状态码: {r.status_code} for {pkg}")
            return 0
        data = r.json()
        pkgs = data.get("packages")
        return len(pkgs) if isinstance(pkgs, list) else 0
    except Exception as e:
        logging.error(f"F-Droid API 请求异常: {e} for {pkg}")
        return 0


# ---------- 单仓库处理 ----------
def process_one(full_name: str):
    try:
        # 1) GitHub Releases APK 计数
        gh_cnt, latest = count_apk_releases_min(full_name)
        print(f"DEBUG {full_name} - {gh_cnt} - {latest}")

        # 2) F-Droid APK 计数（从 README 抽包名后统计）
        readme = fetch_readme_text(full_name)
        fd_pkgs = sorted(extract_play_packages(readme))
        fd_cnt_total = 0
        fd_pkg_used = ""
        print(f"DEBUG {full_name} - {fd_pkgs}")
        for pkg in fd_pkgs:
            c = fdroid_apk_count(pkg)
            
            if c > 0:
                fd_cnt_total = max(fd_cnt_total, c)
                
                # 不早停：也可以早停，这里保留最大值
        return {
            "full": full_name,
            "gh_apk_count": gh_cnt,
            "latest_apk_date_utc": latest,
            "fdroid_pkg": fd_pkg_used,
            "fdroid_apk_count": fd_cnt_total,
        }
    except Exception as e:
        logging.error(f"ERROR {full_name} - {str(e)}")
        return {
            "full": full_name,
            "gh_apk_count": 0,
            "latest_apk_date_utc": "",
            "fdroid_pkg": "",
            "fdroid_apk_count": 0,
        }

# ---------- 主流程 ----------
def main(start_line=0, use_target_lines=False):
    # 如果使用目标行号
    target_lines = set()
    if use_target_lines:
        try:
            with open('check_log.log', 'r', encoding='utf-8') as f:
                f.readline(); f.readline(); f.readline(); f.readline(); f.readline()
                for line in f:
                    target_lines.update(map(int, line.strip().split(',')))
        except FileNotFoundError:
            print("未找到 check_log.log 文件")
            return

    with open(IN_CSV, newline="", encoding="utf-8-sig") as fin, \
         open(OUT_CSV, "a", newline="", encoding="utf-8-sig") as fout:
        r = csv.DictReader(fin)
        # 追加我们要写出的字段
        fieldnames = r.fieldnames + [
            "apk_release_count",
            "latest_apk_date_utc",
            "fdroid_pkg",
            "fdroid_apk_count",
        ]
        w = csv.DictWriter(fout, fieldnames=fieldnames)

        if fout.tell() == 0:
            w.writeheader()

        rows, fulls = [], []
        total_repos = 0

        # 跳过前面的行
        for _ in range(start_line):
            next(r, None)

        # 收集需要处理的仓库
        for line_num, row in enumerate(r, start=start_line):
            if use_target_lines and line_num not in target_lines:
                continue
            total_repos += 1
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            rows.append((line_num, row))
            fulls.append(full)

        # 并发处理
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(process_one, fn): fn for fn in fulls}
            for fut in concurrent.futures.as_completed(futs):
                info = fut.result()
                full = futs[fut]  # ✅ 从映射取回 full
                results[full] = info

                # 是否满足：GitHub APK≥2 或 F-Droid APK≥2
                keep = (info["gh_apk_count"] >= MIN_APK_RELEASES) or (info["fdroid_apk_count"] >= MIN_APK_RELEASES)
                line_num = next((ln for ln, r0 in rows if (r0.get("full_name") or f"{r0.get('owner')}/{r0.get('repo')}") == full), "N/A")
                status = "SUCCESS" if keep else "FAILED"
                logging.info(
                    f"LINE {line_num} - {status} {full} - GH_APK={info['gh_apk_count']} "
                    f"/ FDroid_APK={info['fdroid_apk_count']} (pkg={info['fdroid_pkg']})"
                )

        kept = 0
        for line_num, row in rows:
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            info = results.get(full, None)
            if not info:
                continue

            keep = (info["gh_apk_count"] >= MIN_APK_RELEASES) or (info["fdroid_apk_count"] >= MIN_APK_RELEASES)
            if keep:
                row["apk_release_count"] = info["gh_apk_count"]
                row["latest_apk_date_utc"] = info["latest_apk_date_utc"]
                row["fdroid_pkg"] = info["fdroid_pkg"]
                row["fdroid_apk_count"] = info["fdroid_apk_count"]
                w.writerow(row)
                kept += 1

        logging.info(f"总仓库数: {total_repos}")
        logging.info(f"保留仓库数: {kept}")

        print(
            f"完成：输入 {total_repos} 个仓库，处理 {len(rows)} 个，"
            f"保留 {kept} 个（规则：GitHub APK≥{MIN_APK_RELEASES} 或 F-Droid APK≥{MIN_APK_RELEASES}）。\n"
            f"输出：{OUT_CSV}"
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter Android repos by GitHub/F-Droid APK availability")
    parser.add_argument("--start", type=int, default=0, help="行号，从指定行开始处理（默认从0开始）")
    parser.add_argument("--target", action="store_true", help="使用 check_log.log 中的目标行号")

    logging.basicConfig(
        filename='filter_repos5.log',
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        encoding='utf-8',
        filemode='a'  # 追加模式
    )

    args = parser.parse_args()
    main(start_line=args.start, use_target_lines=args.target)
