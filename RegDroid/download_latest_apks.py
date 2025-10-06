# 下载每个仓库“最新一个含 APK 的正式版 release”的所有 APK
# 命名：单 APK => <package>.apk；多 APK => <package>_<original_name>.apk
import os, csv, time, re, base64, argparse, logging, pathlib, random
from typing import List, Tuple, Optional, Dict
import requests
from dateutil import parser as dtparser

IN_CSV_DEFAULT  = "final.csv"
OUT_DIR_DEFAULT = "select_apks"
WORKERS_DEFAULT = 6  # 下载并发（按仓库并发的话可以自己包一层线程池）

# ------- GitHub Tokens（可多放，随便加环境变量） -------
TOKENS = [t.strip() for t in filter(None, [
    os.getenv("GITHUB_TOKEN_1"),
    os.getenv("GITHUB_TOKEN_2"),
    os.getenv("GITHUB_TOKEN_3"),
    os.getenv("GITHUB_TOKEN_4"),
    os.getenv("GITHUB_TOKEN_5"),
    os.getenv("GITHUB_CLASSIC_TOKEN"),
    os.getenv("GITHUB_TOKEN"),  # 也许你就配了一个
])]

# ------- 常量 / UA -------
UA = {
    "User-Agent": "latest-apk-downloader/1.0 (+github API client)"
}
APK_MIMES = ("application/vnd.android.package-archive",)
APK_EXTS  = (".apk",)  # 如需 AAB 可加 ".aab"

# ------- README 里提取 Google Play 包名 -------
PLAY_LINK_RE = re.compile(
    r"play\.google\.com/store/apps/details\?[^)\s\"'>]*\bid=([a-zA-Z0-9._]+)",
    re.IGNORECASE
)

def gh_headers(token=None):
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **UA,
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def rest_get(url, params=None, timeout=40, retry=6):
    """
    轮换 token 的 GET；遇到 403/429/502/503 指数退避；
    若命中 RateLimit，读 X-RateLimit-Reset 睡到窗口刷新。
    """
    for k in range(retry):
        token = TOKENS[k % max(1, len(TOKENS))] if TOKENS else None
        try:
            r = requests.get(url, headers=gh_headers(token), params=params, timeout=timeout)
            # 速率与网关问题
            if r.status_code in (502, 503):
                time.sleep(1.0 * (k + 1))
                continue
            if r.status_code in (403, 429):
                # Rate limit?
                reset = r.headers.get("X-RateLimit-Reset")
                rem   = r.headers.get("X-RateLimit-Remaining")
                if rem == "0" and reset:
                    try:
                        reset_ts = int(reset)
                        sleep_s = max(0, reset_ts - int(time.time())) + 1 + random.uniform(0, 1.5)
                        logging.warning(f"Rate limited. Sleeping {sleep_s:.1f}s until reset…")
                        time.sleep(sleep_s)
                        continue
                    except Exception:
                        pass
                # 否则常规退避
                time.sleep(1.2 * (k + 1))
                continue

            if r.status_code == 404:
                return r
            r.raise_for_status()
            return r
        except requests.RequestException:
            time.sleep(1.2 * (k + 1))
    raise RuntimeError(f"GET fail: {url}")

def fetch_readme_text(full_name: str) -> str:
    """读 README 明文；失败返回空串"""
    url = f"https://api.github.com/repos/{full_name}/readme"
    try:
        r = rest_get(url, timeout=25)
        if r.status_code == 404:
            return ""
        data = r.json()
        content = data.get("content")
        if not content:
            return ""
        if (data.get("encoding") or "").lower() == "base64":
            try:
                return base64.b64decode(content, validate=False).decode("utf-8", errors="ignore")
            except Exception:
                return ""
        # 偶尔 API 会直接给文本（极少）
        return str(content)
    except Exception as e:
        logging.warning(f"README fetch error for {full_name}: {e}")
        return ""

def extract_first_package_from_readme(full_name: str) -> Optional[str]:
    txt = fetch_readme_text(full_name)
    if not txt:
        return None
    for m in PLAY_LINK_RE.finditer(txt):
        pkg = m.group(1)
        if pkg:
            return pkg.strip()
    return None

# ------- Release 过滤：是否允许预发布 -------
PRE_KEYWORDS = ("alpha", "beta", "rc", "pre", "preview", "nightly")

def is_pre_release(rel) -> bool:
    """根据 GitHub 的 prerelease 字段 + 名称/标签里的常见关键词判断是否为预发布"""
    if rel.get("prerelease"):
        return True
    name = (rel.get("name") or "").lower()
    tag  = (rel.get("tag_name") or "").lower()
    return any(k in name or k in tag for k in PRE_KEYWORDS)

def list_apk_assets(rel) -> List[Dict]:
    """返回该 release 里所有 APK 资产（asset dict 列表）"""
    res = []
    for a in (rel.get("assets") or []):
        name = (a.get("name") or "").lower()
        url  = a.get("browser_download_url") or ""
        cty  = (a.get("content_type") or "").lower()
        if name.endswith(APK_EXTS) or url.lower().endswith(APK_EXTS) or cty in APK_MIMES:
            res.append(a)
    return res

def find_latest_release_with_apk(full_name: str, allow_pre: bool=False):
    """
    从最新往旧找第一个“符合条件”的 release：
      - 如果 allow_pre=False，则跳过所有预发布（含关键字和 prerelease=True）
      - 至少包含一个 APK 资产
    命中即返回 (release_dict, apk_assets_list)；否则 (None, [])
    """
    page = 1
    while True:
        r = rest_get(f"https://api.github.com/repos/{full_name}/releases",
                     params={"per_page": 100, "page": page})
        arr = r.json()
        if not isinstance(arr, list) or not arr:
            return None, []
        for rel in arr:
            if (not allow_pre) and is_pre_release(rel):
                continue
            apks = list_apk_assets(rel)
            if apks:
                return rel, apks
        if len(arr) < 100:
            return None, []
        page += 1

# ------- 下载工具 -------
def ensure_dir(p: pathlib.Path):
    p.mkdir(parents=True, exist_ok=True)

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip("_")

def stream_download(url: str, out_path: pathlib.Path, token: Optional[str]):
    """带 Token 的浏览器下载链接直下；处理 403/429 的退避"""
    headers = {**UA}
    if token:
        # GitHub 对 assets 的浏览器下载链接不需要 token，但加上也不影响；或者可换 Accept: application/octet-stream
        headers["Authorization"] = f"Bearer {token}"
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

def pick_token(i: int) -> Optional[str]:
    if not TOKENS:
        return None
    return TOKENS[i % len(TOKENS)]

# ------- 单仓库主流程 -------
def process_one_repo(full_name: str, outdir: pathlib.Path, allow_pre: bool=False) -> Tuple[str, str]:
    """
    返回 (status, message)
    - 成功：下载到 outdir 下，按命名规则保存；status='SUCCESS'
    - 失败：status='FAILED'
    """
    try:
        # 1) 包名（命名用）
        pkg = extract_first_package_from_readme(full_name)
        if not pkg:
            if "/" in full_name:
                owner, repo = full_name.split("/", 1)
                pkg = f"{owner}_{repo}"
            else:
                pkg = full_name.replace("/", "_")
        pkg = sanitize_filename(pkg)

        # 2) 找到最新一个含 APK 的（可选跳过预发布）
        rel, apk_assets = find_latest_release_with_apk(full_name, allow_pre=allow_pre)
        if not rel:
            return "FAILED", f"{full_name}: no qualifying release with APK (allow_pre={allow_pre})"

        # 3) 下载
        ensure_dir(outdir)
        token0 = pick_token(hash(full_name))

        downloaded_files = []  # 新增：记录下载的 apk 名称

        if len(apk_assets) == 1:
            a = apk_assets[0]
            name = f"{pkg}.apk"
            if not a.get("name", "").lower().endswith(".apk"):
                name = f"{pkg}.apk"
            dest = outdir / name
            stream_download(a["browser_download_url"], dest, token0)
            downloaded_files.append(name)
        else:
            for a in apk_assets:
                orig = a.get("name") or "unknown.apk"
                name = sanitize_filename(f"{pkg}_{orig}")
                dest = outdir / name
                stream_download(a["browser_download_url"], dest, token0)
                downloaded_files.append(name)

        tag = rel.get("tag_name") or rel.get("name") or ""
        # 在 log 中打印具体文件名
        msg = f"{full_name}: downloaded {len(apk_assets)} apk(s) from release {tag!r}: {downloaded_files}"
        print(msg)
        logging.info(msg)
        return "SUCCESS", msg
    except Exception as e:
        return "FAILED", f"{full_name}: error {e}"


# ------- CLI / 批处理 -------
def read_repos_from_csv(csv_path: str) -> List[str]:
    repos = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fin:
        r = csv.DictReader(fin)
        for row in r:
            full = row.get("full_name") or (f"{row.get('owner')}/{row.get('repo')}" if row.get("owner") and row.get("repo") else None)
            if full:
                repos.append(full.strip())
    return repos

def main():
    parser = argparse.ArgumentParser(description="Download APKs from latest qualifying GitHub release per repo")
    parser.add_argument("--in", dest="in_csv", default=IN_CSV_DEFAULT, help="CSV with 'full_name' or 'owner,repo'")
    parser.add_argument("--repo", help="Process a single repo like owner/name (overrides --in)")
    parser.add_argument("--outdir", default=OUT_DIR_DEFAULT, help="Output directory for APKs")
    parser.add_argument("--allow-pre", action="store_true", help="Allow alpha/beta/rc/preview/nightly releases")
    args = parser.parse_args()

    logging.basicConfig(
        filename='download_latest_apks.log',
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        encoding='utf-8',
        filemode='a'
    )

    outdir = pathlib.Path(args.outdir)
    ensure_dir(outdir)

    if args.repo:
        repos = [args.repo.strip()]
    else:
        repos = read_repos_from_csv(args.in_csv)

    # 串行稳妥（避免 assets 流式下载遇到太多同时打开连接）；你也可以自己用线程池包一层
    ok = 0
    for full in repos:
        status, msg = process_one_repo(full, outdir, allow_pre=args.allow_pre)
        print(f"{status} - {msg}")
        logging.info(f"{status} - {msg}")
        if status == "SUCCESS":
            ok += 1

    print(f"完成：成功 {ok}/{len(repos)} 个；输出目录：{outdir}")

if __name__ == "__main__":
    main()
