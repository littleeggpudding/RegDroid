# 过滤raw results  （按 Star=0 + 近三年未更新跳过）
import os, csv, time, json, pathlib, requests, concurrent.futures
from datetime import datetime, timezone, timedelta
from dateutil import parser as dtparser
import logging
import argparse
import base64

IN_CSV  = "android_repos_with_apk2plus.csv"            # 输入
OUT_CSV = "android_repos_with_manifest.csv"            # 输出
CACHE   = pathlib.Path("cache_releases")               # 简单缓存目录
WORKERS = 10                                           # 并发度
MIN_APK_RELEASES = 2
LOOKBACK_DAYS = None

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

def get_default_branch(full_name: str) -> str:
    url = f"https://api.github.com/repos/{full_name}"
    r = rest_get(url, timeout=30)
    if r.status_code == 404:
        return ""
    data = r.json()
    return data.get("default_branch") or "main"

def fetch_repo_tree(full_name: str, branch: str):
    """
    拉取默认分支的完整文件树（递归），带简单缓存。
    """
    cache_p = CACHE / "trees" / f"{full_name.replace('/', '__')}@{branch}.json"
    cached = cache_load(cache_p)
    if cached:
        return cached

    # 先拿这个分支 HEAD commit SHA
    r_ref = rest_get(f"https://api.github.com/repos/{full_name}/git/refs/heads/{branch}", timeout=30)
    if r_ref.status_code == 404:
        return None
    sha = (r_ref.json().get("object") or {}).get("sha")
    if not sha:
        return None

    # 再拉整棵树
    r_tree = rest_get(f"https://api.github.com/repos/{full_name}/git/trees/{sha}",
                      params={"recursive": "1"}, timeout=60)
    if r_tree.status_code == 404:
        return None
    tree = r_tree.json()
    cache_save(cache_p, tree)
    return tree

def find_manifest_paths(tree_json) -> list:
    """
    在整棵树里找所有 AndroidManifest.xml
    """
    if not tree_json:
        return []
    out = []
    for node in (tree_json.get("tree") or []):
        if node.get("type") == "blob":
            path = node.get("path") or ""
            # 通常大小写固定，但也兼容极少数小写
            if path.endswith("AndroidManifest.xml") or path.endswith("androidmanifest.xml"):
                out.append(path)
    return out

def has_android_manifest(full_name: str):
    """
    先检查常见的 app/src/main/AndroidManifest.xml
    如果没找到，再 fallback 到全仓库扫描
    返回: (has_manifest: bool, default_branch: str, manifest_paths: list[str])
    """
    branch = get_default_branch(full_name)
    if not branch:
        return False, "", []

    # 1) 快查固定路径
    url = f"https://api.github.com/repos/{full_name}/contents/app/src/main/AndroidManifest.xml"
    r = rest_get(url, params={"ref": branch}, timeout=20)
    if r.status_code == 200 and isinstance(r.json(), dict) and r.json().get("type") == "file":
        return True, branch, ["app/src/main/AndroidManifest.xml"]

    # 2) fallback 全量扫描
    tree = fetch_repo_tree(full_name, branch)
    paths = find_manifest_paths(tree)
    return (len(paths) > 0), branch, paths


def process_one(full_name: str):
    try:
        #是否存在 AndroidManifest.xml（先快查，后全扫）
        has_manifest, default_branch, manifest_paths = has_android_manifest(full_name)

        return {
            "full": full_name,
            "has_manifest": has_manifest,
            "default_branch": default_branch,
            "manifest_paths": ";".join(manifest_paths[:20]),
        }
    except Exception as e:
        logging.error(f"ERROR {full_name} - {str(e)}")
        return {
            "full": full_name,
            "has_manifest": False,
            "default_branch": "",
            "manifest_paths": "",
        }

def main(start_line=0, use_target_lines=False):
    ensure_dir(CACHE)

    # 如果使用目标行号
    target_lines = set()
    if use_target_lines:
        try:
            with open('check_log.log', 'r', encoding='utf-8') as f:
                f.readline()
                f.readline()
                f.readline()
                f.readline()
                f.readline()
                for line in f:
                    target_lines.update(map(int, line.strip().split(',')))
        except FileNotFoundError:
            print("未找到 check_log.log 文件")
            return

    with open(IN_CSV, newline="", encoding="utf-8-sig") as fin, \
         open(OUT_CSV, "a", newline="", encoding="utf-8-sig") as fout:
        r = csv.DictReader(fin)
        # 
        fieldnames = r.fieldnames + [
            "has_manifest",
            "default_branch",
            "manifest_paths",
        ]
        w = csv.DictWriter(fout, fieldnames=fieldnames)

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

                logging.info(
                    f"LINE {line_num} - {'KEEP' if info['has_manifest'] else 'DROP'} {full} "
                    f"- has_manifest={info['has_manifest']}, branch={info['default_branch']}, "
                    f"paths={info['manifest_paths']}"
                )

        kept = 0
        for line_num, row in rows:
            full = row.get("full_name") or f"{row.get('owner')}/{row.get('repo')}"
            info = results.get(full)
            if not info:
                continue

            # ✅ 最终保留条件：Manifest 为真
            if info["has_manifest"]:
                row["has_manifest"] = info["has_manifest"]
                row["default_branch"] = info["default_branch"]
                row["manifest_paths"] = info["manifest_paths"]
                w.writerow(row)
                kept += 1

        logging.info(f"总仓库数: {total_repos}")
        logging.info(f"跳过仓库数: {skipped_repos}")
        logging.info(f"处理仓库数: {len(rows)}")
        logging.info(f"保留仓库数: {kept}")

        print(
            f"完成：输入 {total_repos} 个仓库，"
            f"跳过 {skipped_repos} 个，"
            f"处理 {len(rows)} 个，"
            f"保留 {kept} 个（以 Manifest 判定）。"
            f"输出：{OUT_CSV}"
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter GitHub repositories by AndroidManifest.xml")
    parser.add_argument("--start", type=int, default=0, help="行号，从指定行开始处理（默认从0开始）")
    parser.add_argument("--target", action="store_true", help="使用 check_log.log 中的目标行号")

    logging.basicConfig(
        filename='filter_repos2.log',
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        encoding='utf-8',
        filemode='a'
    )

    args = parser.parse_args()
    main(start_line=args.start, use_target_lines=args.target)
