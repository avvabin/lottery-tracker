# -*- coding: utf-8 -*-
"""
Итоговая сводка за весь день - запускается один раз вечером (по Астане).
Показывает ВСЕ повторившиеся четвёрки за день (полный список), с
интервалами времени между повторами.
"""
import os
from datetime import date
from itertools import combinations
from collections import defaultdict
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


def build_end_of_day_summary() -> str:
    if not os.path.exists(DATA_FILE):
        return "Данных пока нет."

    from datetime import datetime, timedelta
    ASTANA_OFFSET = timedelta(hours=5)
    today = (datetime.utcnow() + ASTANA_OFFSET).date().isoformat()

    df = pd.read_csv(DATA_FILE, sep=';', encoding='utf-8-sig')
    normal = df[df['Выпавшие шары'] != 'ОТМЕНЕН'].copy()
    normal['dt_astana'] = pd.to_datetime(normal['Дата и Время']) + ASTANA_OFFSET
    normal['date_astana'] = normal['dt_astana'].dt.date.astype(str)

    today_df = normal[normal['date_astana'] == today].copy()

    if today_df.empty:
        return f"ИТОГ ДНЯ {today} (по Астане)\nЗа сегодня данных нет."

    today_df['balls_list'] = today_df['Выпавшие шары'].apply(lambda s: [int(x.strip()) for x in s.split(',')])
    today_df = today_df.sort_values('dt_astana')

    combo4_times = defaultdict(list)
    for _, row in today_df.iterrows():
        for c in combinations(sorted(row['balls_list']), 4):
            combo4_times[c].append(row['dt_astana'])
    repeated4 = [(c, times) for c, times in combo4_times.items() if len(times) >= 4]
    repeated4.sort(key=lambda x: -len(x[1]))

    lines = [
        f"ИТОГ ДНЯ — {today} (по Астане, GMT+5)",
        f"Всего тиражей за день: {len(today_df)}",
        "",
        f"ВСЕ четвёрки с 4+ повторами за день ({len(repeated4)}):",
    ]
    for combo, times in repeated4:
        times_str = ", ".join(t.strftime("%H:%M") for t in times)
        gaps = [f"{int((times[i]-times[i-1]).total_seconds()/60)}м" for i in range(1, len(times))]
        gaps_str = " -> ".join(gaps) if gaps else "-"
        lines.append(f"  {combo}: {len(times)}x [{times_str}] интервалы: {gaps_str}")

    lines.append("")
    lines.append("(Напоминание: это фоновый шум по 89-дневному анализу, не сигнал.)")

    return "\n".join(lines)

if __name__ == "__main__":
    summary = build_end_of_day_summary()
    send_telegram(summary)
    print(summary)
