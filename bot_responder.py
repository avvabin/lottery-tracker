# -*- coding: utf-8 -*-
"""
Отвечает в Telegram на любое сообщение пользователя текущей статистикой
по ЧЕТВЁРКАМ чисел за сегодня - только факты, без прогнозов.

Работает через getUpdates с сохранением offset (чтобы не отвечать на
одно и то же сообщение дважды). Данные берёт из history_backfill.csv,
который наполняет collector.py (отдельный, почасовой workflow).
"""

import os
import json
from datetime import date
from itertools import combinations
from collections import defaultdict
import pandas as pd
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DATA_FILE = "history_backfill.csv"
OFFSET_FILE = "telegram_offset.json"


def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 5}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("result", [])


def send_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)


def load_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            return json.load(f).get("last_update_id")
    return None


def save_offset(update_id):
    with open(OFFSET_FILE, "w") as f:
        json.dump({"last_update_id": update_id}, f)


def build_stats_reply() -> str:
    """Только факты по четвёркам: полный пересчёт с начала дня на этот момент."""
    if not os.path.exists(DATA_FILE):
        return "Данных пока нет - бот ещё не собрал ни одного тиража."

    df = pd.read_csv(DATA_FILE, sep=';', encoding='utf-8-sig')
    normal = df[df['Выпавшие шары'] != 'ОТМЕНЕН'].copy()

    today = date.today().isoformat()
    today_df = normal[normal['Дата'] == today].copy()

    if today_df.empty:
        return f"За сегодня ({today}) в базе пока нет данных."

    today_df['balls_list'] = today_df['Выпавшие шары'].apply(lambda s: [int(x.strip()) for x in s.split(',')])
    today_df['dt'] = pd.to_datetime(today_df['Дата и Время'])
    today_df = today_df.sort_values('dt')

    combo4_times = defaultdict(list)
    for _, row in today_df.iterrows():
        for c in combinations(sorted(row['balls_list']), 4):
            combo4_times[c].append(row['dt'])

    repeated4 = [(c, times) for c, times in combo4_times.items() if len(times) >= 4]
    repeated4.sort(key=lambda x: -len(x[1]))

    lines = [
        f"Статистика по четвёркам за {today}",
        f"Тиражей с начала дня: {len(today_df)}",
        "",
        "Это ПОЛНЫЙ пересчёт с полуночи на текущий момент",
        "(не новое событие, а сумма всех повторов с начала дня).",
        "",
        f"Четвёрок с 4+ повторами: {len(repeated4)}",
    ]
    if repeated4:
        for combo, times in repeated4[:20]:
            times_str = ", ".join(t.strftime("%H:%M") for t in times)
            gaps = [f"{int((times[i]-times[i-1]).total_seconds()/60)}м" for i in range(1, len(times))]
            gaps_str = " -> ".join(gaps) if gaps else "-"
            lines.append(f"  {combo}: {len(times)}x [{times_str}] интервалы: {gaps_str}")
        if len(repeated4) > 20:
            lines.append(f"  ...ещё {len(repeated4)-20}")
    else:
        lines.append("  таких пока нет")

    return "\n".join(lines)


def main():
    offset = load_offset()
    updates = get_updates(offset)

    if not updates:
        return

    last_id = offset
    for upd in updates:
        last_id = upd["update_id"] + 1
        msg = upd.get("message")
        if not msg:
            continue
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != TELEGRAM_CHAT_ID:
            continue  # отвечаем только своему чату

        reply = build_stats_reply()
        send_message(reply)

    save_offset(last_id)


if __name__ == "__main__":
    main()
