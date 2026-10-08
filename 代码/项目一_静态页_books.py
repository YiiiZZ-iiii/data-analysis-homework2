# -*- coding: utf-8 -*-
"""
项目一 · 静态页抓取：books.toscrape.com
把整站约 1000 本书整理成一张表格（CSV）。

需提取字段：书名、价格、评分、库存、详情页链接
关键点：
  1) 按「位置 + 属性」从网页结构提取字段；
  2) 识别 URL 翻页规律（page-1.html / page-2.html ...）后用循环遍历全部页面；
  3) 清理符号、空格、乱码；
  4) 不遗漏最后一页，用总条数核对完整性。

使用前请先查看 robots.txt（见 main 函数），并控制请求频率（已加延时）。
"""
import csv
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://books.toscrape.com/"
RATING = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


def fetch(url, session):
    """带超时与简单重试的 GET，返回 HTML 文本。"""
    for _ in range(3):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            r.encoding = "utf-8"  # 该站为 UTF-8，但响应头未标注 charset，需手动指定，否则 £ 会乱码
            return r.text
        except requests.RequestException:
            time.sleep(2)
    raise RuntimeError(f"请求失败：{url}")


def parse_books(html, page_url):
    """从一页 HTML 中解析出所有书籍。"""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for art in soup.select("article.product_pod"):
        # 书名：取 h3 里 a 的 title 属性（完整书名），文本会被截断
        a_tag = art.select_one("h3 a")
        title = a_tag.get("title", "").strip() if a_tag else ""

        # 价格：去掉 £ 和多余空白
        price_el = art.select_one("p.price_color")
        price = price_el.get_text(strip=True) if price_el else ""
        price = price.replace("£", "").strip()

        # 评分：class="star-rating Three" 之类，映射成数字
        rating_el = art.select_one("p.star-rating")
        rating = ""
        if rating_el:
            cls = " ".join(rating_el.get("class", []))
            rating = next((str(RATING[k]) for k in RATING if k in cls), "")

        # 库存：取 availability 文本，清理换行与空格
        stock_el = art.select_one("p.instock.availability")
        stock = stock_el.get_text(" ", strip=True) if stock_el else ""
        stock = re.sub(r"\s+", " ", stock).strip()

        # 详情页链接：相对路径拼成绝对地址
        href = a_tag.get("href", "") if a_tag else ""
        detail = urljoin(page_url, href)

        rows.append([title, price, rating, stock, detail])
    return rows


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (homework scraper; polite 0.5s delay)"

    # 先查看 robots.txt，养成礼貌抓取的习惯（该站无 robots.txt，返回 404，跳过即可）
    try:
        rob = fetch(urljoin(BASE, "robots.txt"), session)
        print("robots.txt 首行：", rob.splitlines()[0] if rob.strip() else "(空)")
    except RuntimeError:
        print("robots.txt 不存在（HTTP 404），跳过，仍保持低频率礼貌抓取。")

    # 第一页，同时拿到总页数
    first = urljoin(BASE, "catalogue/page-1.html")
    html = fetch(first, session)
    soup = BeautifulSoup(html, "lxml")
    # 分页提示形如 "Page 1 of 50"
    pager = soup.select_one("li.current")
    total_pages = 50
    if pager:
        m = re.search(r"of\s+(\d+)", pager.get_text())
        if m:
            total_pages = int(m.group(1))
    print(f"共 {total_pages} 页，开始抓取……")

    all_books = []
    for page in range(1, total_pages + 1):
        if page == 1:
            html = html  # 复用第一页
        else:
            url = urljoin(BASE, f"catalogue/page-{page}.html")
            html = fetch(url, session)
        rows = parse_books(html, url if page != 1 else first)
        all_books.extend(rows)
        print(f"  第 {page}/{total_pages} 页完成，累计 {len(all_books)} 条")
        time.sleep(0.5)  # 控制请求频率，避免压垮网站

    # 保存 CSV（utf-8-sig 方便 Excel 直接打开不乱码）
    out = "../结果/books.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["书名", "价格", "评分", "库存", "详情页链接"])
        w.writerows(all_books)

    print(f"\n完成：共抓到 {len(all_books)} 本书，已写入 {out}")
    # 用总条数核对完整性（该站全书约 1000 本）
    print("完整性质检：", "通过（1000 本，无缺页）" if len(all_books) == 1000 else f"请检查，抓到 {len(all_books)} 条")


if __name__ == "__main__":
    main()
