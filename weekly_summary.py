# -*- coding: utf-8 -*-
"""
Недельная сводка - запускается раз в неделю (понедельник, по Астане).
Смотрит на последние 7 дней и показывает:
 - общую частоту чисел за неделю
 - четвёрки чисел, которые выпадали 2+ раза В РАЗНЫЕ ДНИ за неделю
   (это честнее, чем просто "много раз за неделю" - показывает, что
   комбинация встречалась не в один день пачкой, а действительно
   несколько разных дней подряд)
"""
import os
from datetime import date, timedelta
from itertools import combinations
from collections import Counter, defaultdict
import pandas as pd
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DATA_FILE = "history_backfill.csv"


def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram токен/chat_id не заданы.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    print("Telegram статус:", resp.status_code)


def build_weekly_summary() -> str:
    if not os.path.exists(DATA_FILE):
        return "Данных пока нет."

    df = pd.read_csv(DATA_FILE, sep=';', encoding='utf-8-sig')
    normal = df[df['Выпавшие шары'] != 'ОТМЕНЕН'].copy()

    end_date = date.today()
    start_date = end_date - timedelta(days=6)
    dates_range = [(start_date + timedelta(days=i)).isoformat() for i in range(7)]

    week_df = normal[normal['Дата'].isin(dates_range)].copy()

    if week_df.empty:
        return f"НЕДЕЛЬНАЯ СВОДКА ({start_date} — {end_date})\nДанных за этот период нет."

    week_df['balls_list'] = week_df['Выпавшие шары'].apply(lambda s: [int(x.strip()) for x in s.split(',')])

    # Проверка целостности: ищем пропуски в номерах тиражей внутри каждого дня
    integrity_issues = []
    check_df = week_df.copy()
    check_df['seq_num'] = check_df['Тираж'].str[-4:].astype(int)
    for d, group in check_df.groupby('Дата'):
        seqs = sorted(group['seq_num'].tolist())
        if not seqs:
            continue
        max_seq = seqs[-1]
        expected_set = set(range(1, max_seq + 1))
        missing = expected_set - set(seqs)
        if missing:
            integrity_issues.append((d, len(missing), max_seq))


    freq = Counter()
    for balls in week_df['balls_list']:
        freq.update(balls)
    expected = len(week_df) * 7 / 42

    # Четвёрки, встретившиеся в 2+ РАЗНЫХ дня за неделю
    combo_days = defaultdict(set)
    for _, row in week_df.iterrows():
        for c in combinations(sorted(row['balls_list']), 4):
            combo_days[c].add(row['Дата'])

    multi_day = [(c, days) for c, days in combo_days.items() if len(days) >= 2]
    multi_day.sort(key=lambda x: -len(x[1]))

    days_present = week_df['Дата'].nunique()

    lines = [
        f"НЕДЕЛЬНАЯ СВОДКА ({start_date} — {end_date})",
        f"Дней с данными: {days_present}/7, тиражей всего: {len(week_df)}",
        "",
        f"ТОП-10 чисел за неделю (ожид. ~{expected:.0f} на число):",
    ]
    for num, cnt in freq.most_common(10):
        dev = (cnt - expected) / expected * 100 if expected else 0
        lines.append(f"  {num}: {cnt} раз ({dev:+.0f}%)")

    lines.append("")
    lines.append(f"Четвёрки, встретившиеся в 2+ РАЗНЫХ днях за неделю ({len(multi_day)}):")
    if multi_day:
        for combo, days in multi_day[:15]:
            lines.append(f"  {combo}: {len(days)} дней ({', '.join(sorted(days))})")
        if len(multi_day) > 15:
            lines.append(f"  ...ещё {len(multi_day)-15}")
    else:
        lines.append("  таких нет")

    lines.append("")
    if integrity_issues:
        lines.append("⚠️ ПРОВЕРКА ЦЕЛОСТНОСТИ - найдены пропуски тиражей:")
        for d, n_missing, max_seq in integrity_issues:
            lines.append(f"  {d}: пропущено {n_missing} тиражей из {max_seq}")
    else:
        lines.append("Проверка целостности: пропусков в номерах тиражей за неделю не найдено.")

    return "\n".join(lines)


if __name__ == "__main__":
    summary = build_weekly_summary()
    send_telegram(summary)
    print(summary)
