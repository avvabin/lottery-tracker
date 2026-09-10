# -*- coding: utf-8 -*-
"""
Отвечает в Telegram на любое сообщение пользователя текущей статистикой
за сегодня - только факты, без прогнозов и рекомендаций.

Работает через getUpdates с сохранением offset (чтобы не отвечать на
одно и то же сообщение дважды). Данные берёт из history_backfill.csv,
который наполняет collector.py (отдельный, почасовой workflow).
"""

import os
import json
from datetime import date
from itertools import combinations
from collections import Counter
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
    """Только факты: сколько тиражей, что повторялось - без выводов и прогнозов."""
    if not os.path.exists(DATA_FILE):
        return "Данных пока нет - бот ещё не собрал ни одного тиража."

    df = pd.read_csv(DATA_FILE, sep=';', encoding='utf-8-sig')
    normal = df[df['Выпавшие шары'] != 'ОТМЕНЕН'].copy()

    today = date.today().isoformat()
    today_df = normal[normal['Дата'] == today]

    if today_df.empty:
        return f"За сегодня ({today}) в базе пока нет данных."

    today_df = today_df.copy()
    today_df['balls_list'] = today_df['Выпавшие шары'].apply(lambda s: [int(x.strip()) for x in s.split(',')])

    freq = Counter()
    for balls in today_df['balls_list']:
        freq.update(balls)

    combo4 = Counter()
    for balls in today_df['balls_list']:
        for c in combinations(sorted(balls), 4):
            combo4[c] += 1
    repeated4 = sorted([(c, cnt) for c, cnt in combo4.items() if cnt >= 2], key=lambda x: -x[1])

    combo3 = Counter()
    for balls in today_df['balls_list']:
        for c in combinations(sorted(balls), 3):
            combo3[c] += 1
    repeated3 = sorted([(c, cnt) for c, cnt in combo3.items() if cnt >= 2], key=lambda x: -x[1])

    lines = [
        f"Статистика за {today}",
        f"Тиражей в базе за сегодня: {len(today_df)}",
        "",
        "Числа, выпавшие чаще всего сегодня:",
    ]
    for num, cnt in freq.most_common(5):
        lines.append(f"  {num}: {cnt} раз")

    lines.append("")
    lines.append(f"Четвёрки чисел, повторившиеся 2+ раза сегодня ({len(repeated4)}):")
    if repeated4:
        for combo, cnt in repeated4[:10]:
            lines.append(f"  {combo}: {cnt} раз")
    else:
        lines.append("  таких пока нет")

    lines.append("")
    lines.append(f"Тройки чисел, повторившиеся 2+ раза сегодня ({len(repeated3)}):")
    if repeated3:
        for combo, cnt in repeated3[:10]:
            lines.append(f"  {combo}: {cnt} раз")
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
