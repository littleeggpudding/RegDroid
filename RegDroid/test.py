from bs4 import BeautifulSoup
import requests
import re

pkg = "it.feio.android.omninotes"

headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
cookies = {"CONSENT": "YES+"}  # 跳过 Google Play 的隐私同意页

# ================= Google Play =================
gp_url = f"https://play.google.com/store/apps/details?id={pkg}&hl=en&gl=US"
r = requests.get(gp_url, headers=headers, cookies=cookies, timeout=25)
soup = BeautifulSoup(r.text, "html.parser")

# Downloads：找 "Downloads" 标签的兄弟节点
downloads = ""
for label in soup.find_all("div", class_="g1rdde"):
    if "download" in label.get_text(strip=True).lower():
        sibling = label.find_previous_sibling("div")
        if sibling:
            downloads = sibling.get_text(strip=True)
            break

# 兜底（正则）
if not downloads:
    for pat in (
        re.compile(r"([0-9][0-9,.\+MK]+)\s*\+\s*downloads", re.I),
        re.compile(r"([0-9][0-9,.\+MK]+)\s*\+\s*installs", re.I),
        re.compile(r'"downloads"\s*:\s*"([^"]+)"', re.I),
    ):
        m = pat.search(r.text)
        if m:
            downloads = (m.group(1) or "").strip()
            if downloads and not downloads.endswith("+"):
                downloads += "+"
            break

# Rating：只取纯数字的首文本节点，避免把“star”带上
rating = ""
rating_div = soup.find("div", class_="TT9eCd")
if rating_div:
    txt = rating_div.find(string=True, recursive=False)
    if txt:
        rating = txt.strip()

print("=== Google Play ===")
print("Downloads:", downloads)
print("Rating:", rating)
print("URL:", gp_url)

# ================= F-Droid =================
# 方式一：先用 F-Droid API 直接判断是否存在（最稳），404 就表示没有该包
fd_api = f"https://f-droid.org/api/v1/packages/{pkg}"
fd_found = False
fd_apk_count = 0

try:
    r_api = requests.get(fd_api, headers=headers, timeout=20)
    if r_api.status_code == 200:
        fd_found = True
except requests.RequestException:
    pass  # 网络异常时，走网页兜底

# 方式二（兜底）：解析 F-Droid 网页，统计 APK 下载链接数量
fd_url = f"https://f-droid.org/packages/{pkg}/"
try:
    r_fd = requests.get(fd_url, headers=headers, timeout=25)
    if r_fd.status_code == 200:
        soup_fd = BeautifulSoup(r_fd.text, "html.parser")
        # 下载按钮通常是 a.package-version-download，href 指向 .apk
        hrefs = set()
        for a in soup_fd.find_all("a", class_="package-version-download"):
            href = a.get("href") or ""
            if href.endswith(".apk"):
                hrefs.add(href)
        # 有些主题/语言下 class 名会变，补一个兜底：找所有指向 .apk 的链接
        if not hrefs:
            for a in soup_fd.find_all("a", href=True):
                if a["href"].endswith(".apk"):
                    hrefs.add(a["href"])

        fd_apk_count = len(hrefs)
        # 如果 API 未命中，但页面上能找到 APK 链接，也认为“可搜到”
        if fd_apk_count > 0:
            fd_found = True
except requests.RequestException:
    pass

print("\n=== F-Droid ===")
print("Found on F-Droid:", fd_found)
print("APK links count:", fd_apk_count)
print("URL:", fd_url)
