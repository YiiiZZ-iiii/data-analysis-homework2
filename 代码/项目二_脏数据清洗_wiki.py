# -*- coding: utf-8 -*-
"""
项目二 · 脏数据清洗 + 入库 + 分析
数据源（课件指定的维基百科「各国人口列表」，任选其一）：
  - https://en.wikipedia.org/wiki/List_of_countries_and_dependencies_by_population
  - https://zh.wikipedia.org/wiki/各国人口列表

重点在「洗」不在「抓」——原始数据里的人口是「像数字的文字」：
  1) 千分位逗号：1,463,865,525
  2) [1][a] 类脚注：1,463,865,525[3]
  3) 不可见空格（NBSP / 窄空格）做千分位
  4) 数字中混杂的单位：≈1.41 billion / 340 million / 14.1亿
  5) 缺失值（空单元格 / —）
不清洗干净就无法参与计算。

流程：
  抓取(网页/本地样本) → 清洗 → 按类型分类入库(SQLite) → 读出 → 排序/求和/取前十 → 输出排名表
"""
import csv
import re
import sqlite3
import sys

import requests
from bs4 import BeautifulSoup

LIVE_URL = "https://zh.wikipedia.org/wiki/各国人口列表"
LOCAL_SAMPLE = "../数据/各国人口_dirty.html"

# —— 单位换算（中文维基用 亿/万，英文用 billion/million）——
UNIT_MULT = {
    "billion": 1e9, "十亿": 1e9,
    "million": 1e6, "百万": 1e6,
    "亿": 1e8,
    "万": 1e4,
}


def clean_population(raw):
    """把一条脏人口字符串洗成整数；缺失/无法识别返回 None。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "—", "–", "-", "N/A", "n/a", "NA"):
        return None

    # 1) 去掉约等号 / 近似标记
    s = re.sub(r"[≈~约]|approx\.?|about", "", s, flags=re.I)

    # 2) 识别单位
    mult = 1.0
    for u, m in UNIT_MULT.items():
        if u.lower() in s.lower():
            mult = m
            s = re.sub(re.escape(u), "", s, flags=re.I)
            break

    # 3) 去掉 [3] [a] 类脚注
    s = re.sub(r"\[\d+\]|\[[a-z]+\]", "", s, flags=re.I)

    # 4) 去掉千分位：逗号、不可见空格(NBSP/窄空格)、普通空格
    s = re.sub(r"[,\s    ​]", "", s)

    # 5) 只保留数字和小数点
    s = re.sub(r"[^0-9.]", "", s)
    if s in ("", "."):
        return None

    try:
        val = float(s) * mult
    except ValueError:
        return None
    # 人口是整数，四舍五入；剔除明显异常值（如 0 或负数）
    return int(round(val)) if val > 0 else None


def parse_table(html_text):
    """从 HTML 中解析「国家/地区 + 人口」两列。"""
    soup = BeautifulSoup(html_text, "lxml")
    table = soup.find("table", class_=re.compile("wikitable")) or soup.find("table")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        cells = [td.get_text(" ", strip=True) for td in tds]
        # 只取「第二列为名称、第三列为人口」的行，跳过表头
        if len(cells) >= 3 and not cells[1].lower().startswith(("国家", "country", "地区")):
            name, pop_raw = cells[1], cells[2]
            if name and pop_raw is not None:
                rows.append((name, pop_raw))
    return rows


def fetch(url, session):
    for _ in range(3):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except requests.RequestException:
            continue
    raise RuntimeError(f"请求失败：{url}")


def main():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (homework scraper; polite)"

    # 优先抓取维基百科；抓不到（被墙/无网）时回退到本地脏数据样本，保证脚本可复现
    source = "维基百科在线"
    try:
        html_text = fetch(LIVE_URL, session)
    except RuntimeError:
        html_text = open(LOCAL_SAMPLE, encoding="utf-8").read()
        source = "本地脏数据样本（215 国，世界银行 2023 数据）"
        print("⚠ 维基百科当前不可达，回退到本地样本演示清洗流程。")

    raw_rows = parse_table(html_text)
    print(f"数据源：{source}，解析到 {len(raw_rows)} 行原始数据")

    # —— 清洗 + 分类入库 ——
    db = sqlite3.connect(":memory:")  # 也可改成文件，如 ../结果/人口.db
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE countries (
            name TEXT,        -- 文字
            pop  INTEGER,     -- 整数
            pct  REAL         -- 小数（人口占世界比例）
        )
    """)

    cleaned, missing = [], 0
    for name, raw in raw_rows:
        pop = clean_population(raw)
        if pop is None:
            missing += 1
            cur.execute("INSERT INTO countries(name, pop, pct) VALUES(?, NULL, NULL)", (name,))
        else:
            cleaned.append((name, pop))

    # 先算世界总人口，再回填占比（小数类型）
    world_total = sum(p for _, p in cleaned)
    for name, pop in cleaned:
        cur.execute(
            "INSERT INTO countries(name, pop, pct) VALUES(?, ?, ?)",
            (name, pop, round(pop / world_total * 100, 4)),
        )
    db.commit()
    print(f"清洗完成：有效 {len(cleaned)} 行，缺失 {missing} 行（已按 NULL 处理，不参与排名）")

    # —— 读出：排序 + 求和 + 取前十 ——
    total = cur.execute("SELECT COUNT(*) FROM countries WHERE pop IS NOT NULL").fetchone()[0]
    total_pop = cur.execute("SELECT SUM(pop) FROM countries").fetchone()[0]
    top10 = cur.execute(
        "SELECT name, pop, pct FROM countries WHERE pop IS NOT NULL ORDER BY pop DESC LIMIT 10"
    ).fetchall()

    print(f"\n入库国家数：{total}，合计人口：{total_pop:,}")
    print("人口排名前十：")
    print(f"{'排名':<4}{'国家/地区':<22}{'人口':>16}{'占世界比例':>10}")
    for i, (name, pop, pct) in enumerate(top10, 1):
        print(f"{i:<4}{name:<22}{pop:>16,}{pct:>9.2f}%")

    # —— 输出排名结果表（过关标准：能输出一张排名结果表）——
    out = "../结果/人口排名前十.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["排名", "国家/地区", "人口", "占世界比例(%)"])
        for i, (name, pop, pct) in enumerate(top10, 1):
            w.writerow([i, name, pop, pct])
    print(f"\n排名结果表已写入 {out}")

    # 完整明细也存一份 CSV
    all_rows = cur.execute(
        "SELECT name, pop, pct FROM countries WHERE pop IS NOT NULL ORDER BY pop DESC"
    ).fetchall()
    with open("../结果/各国人口_清洗后.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["国家/地区", "人口", "占世界比例(%)"])
        for name, pop, pct in all_rows:
            w.writerow([name, pop, pct])
    print(f"完整明细（{len(all_rows)} 行）已写入 ../结果/各国人口_清洗后.csv")


if __name__ == "__main__":
    main()
