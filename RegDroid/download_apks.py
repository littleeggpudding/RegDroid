# -*- coding: utf-8 -*-
"""
下载“近 N 年”所有 release 中的 APK（可选含 AAB），并生成清单 CSV。
- 单 APK 的 release：重命名为 <release_name>.apk
- 多 APK 的 release：重命名为 <release_name>_<original_name>
- 输出目录：<outdir>/<package_name>/...
"""

import os, csv, re, time, base64, argparse, logging, pathlib, random
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta, timezone

import requests
from dateutil import parser as dtparser

# ---------- 配置 ----------
UA = {"User-Agent": "repo-apk-archiver/1.0 (+github api client)"}
DEFAULT_OUTDIR = "select_apks"
DEFAULT_MANIFEST = "apks_manifest.csv"

# 支持多个 token 轮换
TOKENS = [t.strip() for t in filter(None, [
    os.getenv("GITHUB_TOKEN_1"),
    os.getenv("GITHUB_TOKEN_2"),
    os.getenv("GITHUB_TOKEN_3"),
    os.getenv("GITHUB_TOKEN_4"),
    os.getenv("GITHUB_TOKEN_5"),
    os.getenv("GITHUB_CLASSIC_TOKEN"),
    os.getenv("GITHUB_TOKEN"),
])]

# 默认只认 .apk；如需连 .aab 一起统计下载，可用 --include-aab
APK_MIMES = ("application/vnd.android.package-archive",)
APK_EXTS_ONLY_APK = (".apk",)
APK_EXTS_APK_AAB = (".apk", ".aab")

PRE_KEYWORDS = ("alpha", "beta", "rc", "pre", "preview", "nightly")

PLAY_LINK_RE = re.compile(
    r"play\.google\.com/store/apps/details\?[^)\s\"'>]*\bid=([a-zA-Z0-9._]+)",
    re.IGNORECASE
)

# ---------- 日志 ----------
logging.basicConfig(
    filename='download_repo_apks.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    encoding='utf-8',
    filemode='a'
)

# ---------- 工具 ----------
def gh_headers(token: Optional[str] = None):
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **UA
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def rest_get(url, params=None, timeout=40, retry=6):
    """带 token 轮换 + 速率限制退避的 GET"""
    for k in range(retry):
        token = TOKENS[k % max(1, len(TOKENS))] if TOKENS else None
        try:
            r = requests.get(url, headers=gh_headers(token), params=params, timeout=timeout)
            if r.status_code in (502, 503):
                time.sleep(1.0 * (k + 1)); continue
            if r.status_code in (403, 429):
                reset = r.headers.get("X-RateLimit-Reset")
                rem   = r.headers.get("X-RateLimit-Remaining")
                if rem == "0" and reset:
                    try:
                        sleep_s = max(0, int(reset) - int(time.time())) + 1 + random.uniform(0, 1.5)
                        logging.warning(f"Rate limited. Sleep {sleep_s:.1f}s...")
                        time.sleep(sleep_s); continue
                    except Exception:
                        pass
                time.sleep(1.2 * (k + 1)); continue
            if r.status_code == 404:
                return r
            r.raise_for_status()
            return r
        except requests.RequestException:
            time.sleep(1.2 * (k + 1))
    raise RuntimeError(f"GET fail: {url}")

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name or "").strip("_")

def ensure_dir(p: pathlib.Path):
    p.mkdir(parents=True, exist_ok=True)

def unique_path(p: pathlib.Path) -> pathlib.Path:
    """若已存在则追加 -1, -2..."""
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    i = 1
    while True:
        cand = p.with_name(f"{stem}-{i}{suffix}")
        if not cand.exists():
            return cand
        i += 1

def stream_download(url: str, out_path: pathlib.Path, token: Optional[str]):
    headers = {**UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with requests.get(url, headers=headers, stream=True, timeout=180) as r:
        r.raise_for_status()
        out_path = unique_path(out_path)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return out_path

def pick_token(i: int) -> Optional[str]:
    if not TOKENS: return None
    return TOKENS[i % len(TOKENS)]

# ---------- README 抽包名 ----------
def fetch_readme_text(full_name: str) -> str:
    r = rest_get(f"https://api.github.com/repos/{full_name}/readme", timeout=25)
    if r.status_code == 404:
        return ""
    data = r.json()
    content = data.get("content")
    if not content: return ""
    if (data.get("encoding") or "").lower() == "base64":
        try:
            return base64.b64decode(content, validate=False).decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return str(content)

def extract_package(full_name: str) -> str:
    txt = fetch_readme_text(full_name)
    if txt:
        m = PLAY_LINK_RE.search(txt)
        if m:
            return sanitize_filename(m.group(1))
    # fallback
    pkg = full_name.replace("/", "_")
    return sanitize_filename(pkg)

# ---------- Release 遍历与过滤 ----------
def is_pre_release(rel) -> bool:
    if rel.get("prerelease"):
        return True
    name = (rel.get("name") or "").lower()
    tag  = (rel.get("tag_name") or "").lower()
    return any(k in name or k in tag for k in PRE_KEYWORDS)

def list_app_assets(rel, include_aab: bool) -> List[Dict]:
    exts = APK_EXTS_APK_AAB if include_aab else APK_EXTS_ONLY_APK
    out = []
    for a in (rel.get("assets") or []):
        nm = (a.get("name") or "").lower()
        url = (a.get("browser_download_url") or "").lower()
        cty = (a.get("content_type") or "").lower()
        if nm.endswith(exts) or url.endswith(exts) or cty in APK_MIMES:
            out.append(a)
    return out

def iter_releases_3y(full_name: str, years: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=365*years)
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
            dt = dtparser.parse(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                # 这一页更旧的也都可能在 cutoff 之外，但保守继续遍历
                continue
            yield rel, dt
        if len(arr) < 100:
            break
        page += 1

# ---------- 主逻辑：下载近年所有 APK 并写 CSV ----------
def download_all_recent_apks(
    full_name: str,
    out_root: pathlib.Path,
    years: int = 3,
    skip_pre: bool = True,
    include_aab: bool = False,
    manifest_writer: Optional[csv.DictWriter] = None
) -> Tuple[int, int]:
    """
    返回 (releases_seen, apks_downloaded)
    """
    package = extract_package(full_name)
    repo_dir = out_root / package
    ensure_dir(repo_dir)

    rel_seen = 0
    apk_saved = 0
    token0 = pick_token(hash(full_name))

    for rel, rel_dt in iter_releases_3y(full_name, years):
        if skip_pre and is_pre_release(rel):
            continue

        assets = list_app_assets(rel, include_aab)
        if not assets:
            continue

        rel_seen += 1
        rel_name = sanitize_filename(rel.get("name") or rel.get("tag_name") or f"release_{rel.get('id')}")
        tag_name = rel.get("tag_name") or ""
        rel_date_iso = rel_dt.isoformat()

        if len(assets) == 1:
            a = assets[0]
            # 单 APK → <release_name>.apk（若下载的是 aab，也保留其后缀）
            suffix = ".apk"
            aname = (a.get("name") or "").lower()
            if include_aab and aname.endswith(".aab"):
                suffix = ".aab"
            target = repo_dir / f"{rel_name}{suffix}"
            saved_path = stream_download(a["browser_download_url"], target, token0)
            apk_saved += 1

            logging.info(f"{full_name} | {tag_name} | saved: {saved_path.name}")
            print(f"SAVED {full_name} -> {saved_path}")

            if manifest_writer:
                manifest_writer.writerow({
                    "repo": full_name,
                    "package": package,
                    "release_tag": tag_name,
                    "release_name": rel.get("name") or "",
                    "release_date_utc": rel_date_iso,
                    "asset_original_name": a.get("name") or "",
                    "saved_filename": saved_path.name,
                    "download_url": a.get("browser_download_url") or "",
                    "content_type": a.get("content_type") or "",
                    "size_bytes": a.get("size") or ""
                })
        else:
            # 多 APK → <release_name>_<original_name>
            for a in assets:
                original = a.get("name") or "unknown.apk"
                target = repo_dir / sanitize_filename(f"{rel_name}_{original}")
                saved_path = stream_download(a["browser_download_url"], target, token0)
                apk_saved += 1

                logging.info(f"{full_name} | {tag_name} | saved: {saved_path.name}")
                print(f"SAVED {full_name} -> {saved_path}")

                if manifest_writer:
                    manifest_writer.writerow({
                        "repo": full_name,
                        "package": package,
                        "release_tag": tag_name,
                        "release_name": rel.get("name") or "",
                        "release_date_utc": rel_date_iso,
                        "asset_original_name": original,
                        "saved_filename": saved_path.name,
                        "download_url": a.get("browser_download_url") or "",
                        "content_type": a.get("content_type") or "",
                        "size_bytes": a.get("size") or ""
                    })

    return rel_seen, apk_saved

# ---------- CSV 批量 / 单仓库 ----------
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
    ap = argparse.ArgumentParser(description="Download all recent releases' APKs (optionally AAB) for repos")
    ap.add_argument("--repo", help="single repo like owner/name")
    ap.add_argument("--in", dest="in_csv", help="CSV with column 'full_name' (or owner,repo)")
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR, help="root output dir (default: select_apks)")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST, help="CSV manifest filename (default: apks_manifest.csv)")
    ap.add_argument("--years", type=int, default=5, help="look back N years (default: 3)")
    ap.add_argument("--skip-pre", action="store_true", help="skip pre-releases (alpha/beta/rc...)")
    ap.add_argument("--include-aab", action="store_true", help="also include .aab bundles")
    args = ap.parse_args()

    # 准备 manifest
    out_root = pathlib.Path(args.outdir)
    ensure_dir(out_root)
    manifest_path = out_root / args.manifest

    fieldnames = [
        "repo","package","release_tag","release_name","release_date_utc",
        "asset_original_name","saved_filename","download_url","content_type","size_bytes"
    ]
    with open(manifest_path, "w", newline="", encoding="utf-8-sig") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()

        if args.repo:
            repos = [args.repo.strip()]
        else:
            if not args.in_csv:
                raise SystemExit("请提供 --repo 或 --in CSV")
            repos = read_repos_from_csv(args.in_csv)

        total_rel, total_apk = 0, 0
        for full in repos:
            rel_seen, apk_saved = download_all_recent_apks(
                full_name=full,
                out_root=out_root,
                years=args.years,
                skip_pre=args.skip_pre,
                include_aab=args.include_aab,
                manifest_writer=writer
            )
            total_rel += rel_seen
            total_apk += apk_saved
            logging.info(f"SUMMARY {full}: releases_seen={rel_seen}, apks_saved={apk_saved}")

    print(f"完成：处理 {len(repos)} 个仓库；近{args.years}年命中 release {total_rel} 个，下载 APK {total_apk} 个；清单：{manifest_path}")

if __name__ == "__main__":
    main()
