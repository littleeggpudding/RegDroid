# 过滤raw results -> 从 README 抽 Google Play 包名，验证是否在架，并解析安装量区间与评分
import os, csv, time, json, pathlib, requests, concurrent.futures, re
from datetime import datetime
import logging
import argparse
import base64
from bs4 import BeautifulSoup  # pip install beautifulsoup4

IN_CSV  = "android_repos_with_manifest.csv"     # 输入：至少包含 full_name 或 owner/repo
OUT_CSV = "android_repos_with_google_play.csv"  # 输出
WORKERS = 10                                    # 并发度

# 可配置多个 PAT，轮换使用以提高吞吐（Classic 或 Fine-grained 都可）
TOKENS = [t.strip() for t in filter(None, [
    os.getenv("GITHUB_TOKEN_1"),
    os.getenv("GITHUB_TOKEN_2"),
    os.getenv("GITHUB_CLASSIC_TOKEN"),
])]

UA_BROWSER = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
}
CONSENT_COOKIES = {"CONSENT": "YES+"}

# --------- 基础工具 ----------
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

# --------- Google Play 校验 + Downloads + Rating 解析 ----------
NOT_FOUND_HINTS = (
    "requested url was not found", "item not found", "we're sorry",
    "not available", "this app is not available", "try searching for it",
)

# 兜底用的正则（如果 DOM 抓不到）
DOWNLOAD_FALLBACK_PATS = [
    re.compile(r"([0-9][0-9,.\+MK]+)\s*\+\s*downloads", re.I),
    re.compile(r"([0-9][0-9,.\+MK]+)\s*\+\s*installs", re.I),
    re.compile(r'"downloads"\s*:\s*"([^"]+)"', re.I),
]

def verify_play_and_extract(pkg: str):
    """
    返回: (is_verify_gp: bool, clean_url: str, downloads: str, rate: str)
    - is_verify_gp: 是否在 Play 可检索（在架）
    - downloads: 例如 "5K+" / "10M+"（抓不到则 ""）
    - rate: 例如 "4.8"（抓不到则 ""）
    """
    print(f"[DEBUG] Starting verification for package: {pkg}")
    
    clean_url = f"https://play.google.com/store/apps/details?id={pkg}&gl=US"

    exists, downloads, rate = False, "", ""

    print(f"[DEBUG] Full URL: {clean_url}")

    try:
        print("[DEBUG] Preparing to send request")
        r = requests.get(
            clean_url,
            headers=UA_BROWSER, 
            cookies=CONSENT_COOKIES,
            timeout=25, 
            allow_redirects=True
        )
        print(f"[DEBUG] Request status code: {r.status_code}")
        
        # 记录响应内容的一些基本信息
        print(f"[DEBUG] Response length: {len(r.text)} characters")
        
        if r.status_code == 200:
            low = r.text.lower()
            print("[DEBUG] Checking for not found hints")
            
            if not any(sig in low for sig in NOT_FOUND_HINTS):
                exists = True
                print("[DEBUG] App exists, parsing with BeautifulSoup")
                soup = BeautifulSoup(r.text, "html.parser")

                # --------- Downloads ----------
                print("[DEBUG] Searching for downloads")
                for label in soup.find_all("div", class_="g1rdde"):
                    if "download" in label.get_text(strip=True).lower():
                        sibling = label.find_previous_sibling("div")
                        if sibling:
                            downloads = sibling.get_text(strip=True)
                            print(f"[DEBUG] Downloads found: {downloads}")
                            break

                # --------- Rating ----------
                print("[DEBUG] Searching for rating")
                rating_div = soup.find("div", class_="TT9eCd")
                if rating_div:
                    rate = rating_div.find(text=True, recursive=False).strip()
                    print(f"[DEBUG] Rating found: {rate}")

            else:
                print("[DEBUG] App not found - hints detected")
        else:
            print(f"[DEBUG] Unexpected status code: {r.status_code}")

    except requests.RequestException as e:
        print(f"[ERROR] Request error: {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")

    print(f"[DEBUG] Returning results for {pkg}")
    return exists, clean_url, downloads, rate

# --------- 处理单仓库 ----------
def process_one(full_name: str):
    """
    读 README -> 抽 Play 包名 -> 依次验证：
      只要有一个包名在 Play 可检索，就记为 is_verify_gp=True，并提取 downloads / rate
    """
    try:
        readme = fetch_readme_text(full_name)
        play_pkgs = sorted(extract_play_packages(readme))

        is_verify_gp = False
        gp_url = ""
        downloads = ""
        rate = ""

        for pkg in play_pkgs:
            ok, url, dl, rt = verify_play_and_extract(pkg)
            if ok:
                is_verify_gp = True
                gp_url = url
                downloads = dl
                rate = rt
                break

        return {
            "full": full_name,
            "is_verify_gp": is_verify_gp,
            "downloads": downloads,
            "rate": rate,
            # 可选：若你想排查，可加上下面这行（但不写入 CSV）
            # "play_pkgs": ";".join(play_pkgs)
        }
    except Exception as e:
        logging.error(f"ERROR {full_name} - {str(e)}")
        return {
            "full": full_name,
            "is_verify_gp": False,
            "downloads": "",
            "rate": "",
        }

# --------- 主流程 ----------
def main(start_line=0, use_target_lines=False):
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

        # 只新增你要的 3 列
        fieldnames = r.fieldnames + [
            "is_verify_gp",  # Google Play 是否可检索（在架）
            "downloads",     # 下载区间（如 5K+ / 10M+，解析不到则空）
            "rate",          # 评分数字（如 4.8，解析不到则空）
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
                full = info["full"]
                results[full] = info
                line_num = next((ln for ln, r0 in rows if (r0.get("full_name") or f"{r0.get('owner')}/{r0.get('repo')}") == full), "N/A")

                # 日志：SUCCESS/FAILED
                status = "SUCCESS" if info["is_verify_gp"] else "FAILED"
                logging.info(
                    f"{status} LINE {line_num} - {full} "
                    f"- is_verify_gp={info['is_verify_gp']}, downloads={info['downloads']}, rate={info['rate']}"
                )

        # 写出（不过滤；如需只保留 is_verify_gp=True 的，可加条件）
        kept = 0
        for line_num, row in rows:
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            info = results.get(full)
            if not info:
                continue
            if info["is_verify_gp"]:
                row["is_verify_gp"] = info["is_verify_gp"]
                row["downloads"] = info["downloads"]
                row["rate"] = info["rate"]
                w.writerow(row)
                kept += 1

        logging.info(f"总仓库数: {total_repos} | 写出行数: {kept}")
        print(
            f"完成：输入 {total_repos} 个仓库，写出 {kept} 行。输出：{OUT_CSV}\n"
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify on Google Play and extract downloads & rating")
    parser.add_argument("--start", type=int, default=0, help="行号，从指定行开始处理（默认从0开始）")
    parser.add_argument("--target", action="store_true", help="使用 check_log.log 中的目标行号")

    logging.basicConfig(
        filename='filter_repos3.log',
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        encoding='utf-8',
        filemode='a'
    )

    args = parser.parse_args()
    main(start_line=args.start, use_target_lines=args.target)
