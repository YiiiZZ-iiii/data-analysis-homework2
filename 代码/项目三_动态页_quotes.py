# -*- coding: utf-8 -*-
"""
项目三 · 动态页抓取：quotes.toscrape.com
两个页面：/js 与 /scroll，普通 requests.get 直接解析 HTML 是拿不到内容的。

为什么拿不到？
  服务器第一次返回的 HTML 只是一个「空房间」，名言内容是后来由 JavaScript 填进去的；
  浏览器会执行 JavaScript，而 Python 的 requests 不会。
  应对策略（本练习采用「直接找数据接口」这条更聪明的路）：
    - /js    ：名言数据其实就嵌在页面 <script> 里的 var data = [...] JSON 中，直接解析出来；
    - /scroll：真正的数据来自接口 /api/quotes?page=N，直接请求该接口拿 JSON。

需提取字段：名言内容 + 作者。
"""
import csv
import json
import re
import time
from urllib.parse import urljoin

import requests

BASE = "https://quotes.toscrape.com/"


def fetch(session, url, **kw):
    for _ in range(3):
        try:
            r = session.get(url, timeout=30, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            time.sleep(2)
    raise RuntimeError(f"请求失败：{url}")


def extract_js_array(html):
    """从 /js 页面的 <script> 中把 var data = [...] 的 JSON 数组抠出来（括号配对法，更稳）。"""
    m = re.search(r"var\s+data\s*=\s*(\[)", html)
    if not m:
        return []
    start = m.start(1)
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return json.loads(html[start:i + 1])
    return []


def scrape_js(session):
    """/js 页：数据嵌在页面里，解析 <script> 里的 JSON。"""
    html = fetch(session, urljoin(BASE, "js/")).text
    data = extract_js_array(html)
    rows = [[q.get("text", "").strip(), q.get("author", {}).get("name", "")] for q in data]
    return rows


def scrape_scroll(session):
    """/scroll 页：直接请求 /api/quotes?page=N 接口，直到 has_next 为 False。"""
    rows = []
    page = 1
    while True:
        r = fetch(session, urljoin(BASE, "api/quotes"), params={"page": page})
        j = r.json()
        for q in j.get("quotes", []):
            rows.append([q.get("text", "").strip(), q.get("author", {}).get("name", "")])
        print(f"  /scroll 第 {page} 页：{len(j.get('quotes', []))} 条，has_next={j.get('has_next')}")
        if not j.get("has_next"):
            break
        page += 1
        time.sleep(0.5)
    return rows


def save(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["名言内容", "作者"])
        w.writerows(rows)


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (homework scraper; polite 0.5s delay)"

    js_rows = scrape_js(session)
    save("../结果/quotes_js.csv", js_rows)
    print(f"/js 完成：共 {len(js_rows)} 条名言，数据来源 = 页面 <script> 内嵌的 var data JSON")

    scroll_rows = scrape_scroll(session)
    save("../结果/quotes_scroll.csv", scroll_rows)
    print(f"/scroll 完成：共 {len(scroll_rows)} 条名言，数据来源 = /api/quotes?page=N 接口")

    print("\n一句话讲清加载机制：")
    print("  /js     → 名言写死在页面 <script> 的 JSON 里，浏览器用 JS 把它渲染成列表；")
    print("  /scroll → 每翻一页浏览器就向 /api/quotes 接口要一批 JSON，滚动时再拼进页面。")


if __name__ == "__main__":
    main()
