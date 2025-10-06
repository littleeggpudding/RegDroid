# 从 README 提取 Google Play 包名 -> 调 SearchAPI.io 拉取 category/description -> 写回 CSV（处理全部行）
import os, csv, time, json, pathlib, requests, concurrent.futures, re, base64
import logging
import argparse

IN_CSV  = "android_repos_with_apk2plus_after_filter_0.csv"   # 输入
OUT_CSV = "android_repos_with_category_desc.csv"              # 输出
WORKERS = 10

# 建议用环境变量传 key（安全）；若未设置则回落到你给的 key（仅测试用）
SEARCHAPI_KEY = os.getenv("SEARCHAPI_KEY", "JGBrfsU8UDCyNaZRMmzsAmpF")

UA = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
}

# --------- GitHub README 提取 ----------
PLAY_LINK_RE = re.compile(
    r"play\.google\.com/store/apps/details\?[^)\s\"'>]*\bid=([a-zA-Z0-9._]+)",
    re.IGNORECASE
)

def gh_headers(token=None):
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "gp-category-extractor",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

# 支持多 Token 轮换（如需）
TOKENS = [t.strip() for t in filter(None, [
    os.getenv("GITHUB_TOKEN_1"),
    os.getenv("GITHUB_TOKEN_2"),
    os.getenv("GITHUB_CLASSIC_TOKEN"),
])]

def rest_get(url, params=None, timeout=30, retry=5):
    for k in range(retry):
        token = TOKENS[k % max(1, len(TOKENS))] if TOKENS else None
        try:
            r = requests.get(url, headers=gh_headers(token), params=params, timeout=timeout)
            if r.status_code in (403, 429, 502, 503):
                time.sleep(1.2*(k+1)); continue
            if r.status_code == 404:
                return r
            r.raise_for_status()
            return r
        except requests.RequestException:
            time.sleep(1.2*(k+1))
    raise RuntimeError(f"GET fail: {url}")

def fetch_readme_text(full_name: str) -> str:
    """读仓库 README 明文，失败返回空串"""
    url = f"https://api.github.com/repos/{full_name}/readme"
    try:
        r = rest_get(url, timeout=25)
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
        logging.warning(f"README fetch error for {full_name}: {e}")
        return ""

def extract_play_packages(text: str):
    """从 README 文本中抽取所有 Google Play 包名（set）"""
    if not text:
        return set()
    return set(m.group(1) for m in PLAY_LINK_RE.finditer(text))

# --------- SearchAPI.io 拉详情 ----------
def fetch_gp_detail_via_searchapi(pkg: str):
    """
    调 SearchAPI.io 的 google_play_product
    返回 (ok: bool, category_str: str, description: str)
    """
    url = "https://www.searchapi.io/api/v1/search"
    params = {
        "engine": "google_play_product",
        "store": "apps",
        "product_id": pkg,
        "hl": "en",
        "gl": "us",
        "api_key": SEARCHAPI_KEY,
    }
    try:
        r = requests.get(url, params=params, headers=UA, timeout=25)
        if r.status_code != 200:
            logging.info(f"SearchAPI non-200 for {pkg}: {r.status_code} {r.text[:200]}")
            return False, "", ""
        data = r.json()

        p = data.get("product") or {}
        # category：可能是数组；收集 title
        cats = []
        for c in (p.get("categories") or []):
            t = (c.get("title") or "").strip()
            if t:
                cats.append(t)
        category_str = ";".join(cats)

        desc = (p.get("description") or "").strip()

        # 有分类或描述即视为成功
        ok = bool(category_str or desc)
        return ok, category_str, desc
    except Exception as e:
        logging.warning(f"SearchAPI error for {pkg}: {e}")
        return False, "", ""

# --------- 单仓库处理 ----------
def process_one(full_name: str):
    """
    1) 取 README -> 抽包名（可能多个，逐个试）
    2) 调 SearchAPI 拿 category/description（命中即停）
    """
    try:
        readme = fetch_readme_text(full_name)
        play_pkgs = sorted(extract_play_packages(readme))
        if not play_pkgs:
            return {"full": full_name, "status": "FAILED", "category": "", "description": ""}

        for pkg in play_pkgs:
            ok, cat, desc = fetch_gp_detail_via_searchapi(pkg)
            if ok:
                return {"full": full_name, "status": "SUCCESS", "category": cat, "description": desc}

        return {"full": full_name, "status": "FAILED", "category": "", "description": ""}
    except Exception as e:
        logging.error(f"ERROR {full_name} - {str(e)}")
        return {"full": full_name, "status": "FAILED", "category": "", "description": ""}

# --------- 主流程 ----------
def main(start_line=0, use_target_lines=False):
    # 可选：目标行过滤（保持接口一致）
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
         open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as fout:
        r = csv.DictReader(fin)
        # 新增两列
        fieldnames = r.fieldnames + ["category", "description"]
        w = csv.DictWriter(fout, fieldnames=fieldnames)
        w.writeheader()

        rows, fulls = [], []
        total = 0

        # 读取全部行（不再筛选）
        for line_num, row in enumerate(r):
            total += 1
            if use_target_lines and line_num not in target_lines:
                continue
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            rows.append((line_num, row))
            fulls.append(full)

        # 并发处理
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(process_one, fn): fn for fn in fulls}
            for fut in concurrent.futures.as_completed(futs):
                info = fut.result()
                full = futs[fut]
                results[full] = info

                line_num = next((ln for ln, r0 in rows
                                 if (r0.get("full_name") or f"{r0.get('owner')}/{r0.get('repo')}") == full),
                                "N/A")
                logging.info(f"{info['status']} LINE {line_num} - {full}")

        # 写出（全部写，分类/描述可能为空）
        written = 0
        for line_num, row in rows:
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            info = results.get(full, None)
            if not info:
                # 没有结果也写出空列，避免丢行
                row["category"] = ""
                row["description"] = ""
            else:
                row["category"] = info.get("category", "")
                row["description"] = info.get("description", "")
            w.writerow(row)
            written += 1

        logging.info(f"总行数: {total} | 写出: {written}")
        print(f"完成：读取 {total} 行，写出 {written} 行 -> {OUT_CSV}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Google Play category & description via SearchAPI.io")
    parser.add_argument("--start", type=int, default=0, help="（保留参数位，未使用）")
    parser.add_argument("--target", action="store_true", help="使用 check_log.log 中的目标行号")
    logging.basicConfig(
        filename='gp_category_desc.log',
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        encoding='utf-8',
        filemode='a'
    )
    args = parser.parse_args()
    main(start_line=args.start, use_target_lines=args.target)
