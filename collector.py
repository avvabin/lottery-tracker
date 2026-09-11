# -*- coding: utf-8 -*-
"""
Автосборщик "7 из 42" для запуска по расписанию (GitHub Actions).
Не требует ручной навигации - просто снимает текущее окно результатов
демо-сайта и докапливает их в history_backfill.csv (та же схема, что и
у исторического архива, так что файлы полностью совместимы).

Дедуп по номеру тиража - можно гонять хоть каждый час, старые записи
не задвоятся.
"""

import time
import logging
import os
from datetime import date
import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

OUTPUT_FILE = "history_backfill.csv"
LOG_FILE = "collector.log"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def start_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,1000")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def open_results_panel(driver):
    driver.get("https://demo.betgames.tv/?language=ru")
    log.info("Страница загружена, ждём...")
    time.sleep(10)

    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    if iframes:
        driver.switch_to.frame(iframes[0])

    driver.execute_script("""
        let items = Array.from(document.querySelectorAll('*'));
        let target = items.find(el => el.children.length === 0 && el.textContent.trim().toUpperCase().includes('7 ИЗ 42'));
        if (target) {
            target.click();
            if (target.parentElement) target.parentElement.click();
        }
    """)
    time.sleep(4)

    driver.execute_script("""
        let buttons = Array.from(document.querySelectorAll('button, div, span, a'));
        let resBtn = buttons.find(b => {
            let t = b.textContent.trim().toLowerCase();
            return t === 'результаты' || t === 'results';
        });
        if (resBtn) resBtn.click();
    """)
    time.sleep(4)
    log.info("Панель 'Результаты' открыта.")


def scrape_current_page():
    """Возвращает JS-строку для execute_script (переиспользуем ту же логику, что в backfill.py)."""
    return """
        let results = [];
        let rowElements = document.querySelectorAll('tr, li, [class*="row"], [class*="item"], [class*="result"]');

        rowElements.forEach(row => {
            let text = row.innerText || '';
            let drawMatch = text.match(/(72\\d{9})/);
            let timeMatch = text.match(/(\\d{2}:\\d{2}:\\d{2}|\\d{2}:\\d{2})/);
            if (!drawMatch || !timeMatch) return;

            let ballSpans = row.querySelectorAll('span[class*="_1SRJjLr9LBM-"]');
            let drawId = "#" + drawMatch[1];
            let drawTime = timeMatch[0];

            if (ballSpans.length === 7) {
                let balls = [];
                ballSpans.forEach(s => {
                    let num = s.innerText.trim();
                    let cls = s.className || '';
                    let isYellow = cls.includes('XaIl0ponuvc-');
                    balls.push({ num: num, color: isYellow ? 'Желтый' : 'Черный' });
                });
                let numbers = balls.map(b => b.num).join(', ');
                let yellowCount = balls.filter(b => b.color === 'Желтый').length;
                let blackCount = balls.filter(b => b.color === 'Черный').length;
                results.push({
                    "Тираж": drawId, "Время": drawTime, "Выпавшие шары": numbers,
                    "Жёлтых": yellowCount, "Чёрных": blackCount
                });
            } else if (ballSpans.length === 0 && /отмен|cancel/i.test(text)) {
                results.push({
                    "Тираж": drawId, "Время": drawTime, "Выпавшие шары": "ОТМЕНЕН",
                    "Жёлтых": "", "Чёрных": ""
                });
            }
        });
        return results;
    """


def decode_date_from_tirage(t):
    """Дата зашифрована в самом номере тиража - надёжнее, чем читать её с экрана."""
    s = t.lstrip('#')
    year = 2020 + int(s[2])
    month = int(s[3:5])
    day = int(s[5:7])
    return f"{year:04d}-{month:02d}-{day:02d}"


def enrich_records(raw_records):
    for r in raw_records:
        d = decode_date_from_tirage(r["Тираж"])
        wd = WEEKDAYS_RU[pd.Timestamp(d).weekday()]
        r["Дата"] = d
        r["День недели"] = wd
        r["Дата и Время"] = f"{d} {r.pop('Время')}"
    return raw_records


def load_existing():
    if os.path.exists(OUTPUT_FILE):
        return pd.read_csv(OUTPUT_FILE, encoding="utf-8-sig", sep=";", dtype=str)
    return pd.DataFrame()


COLUMN_ORDER = ["Тираж", "Дата", "День недели", "Дата и Время", "Выпавшие шары", "Жёлтых", "Чёрных"]


def save_progress(df: pd.DataFrame):
    if df.empty:
        return
    df = df.drop_duplicates(subset=["Тираж"]).sort_values(by="Тираж")
    existing_cols = [c for c in COLUMN_ORDER if c in df.columns]
    other_cols = [c for c in df.columns if c not in existing_cols]
    df = df[existing_cols + other_cols]
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig", sep=";")
    log.info("Сохранено %d уникальных тиражей в %s", len(df), OUTPUT_FILE)


FAIL_COUNT_FILE = "fail_count.txt"


def load_fail_count():
    if os.path.exists(FAIL_COUNT_FILE):
        try:
            with open(FAIL_COUNT_FILE) as f:
                return int(f.read().strip())
        except Exception:
            return 0
    return 0


def save_fail_count(n):
    with open(FAIL_COUNT_FILE, "w") as f:
        f.write(str(n))


def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram токен/chat_id не заданы - уведомление не отправлено.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        if resp.status_code != 200:
            log.error("Telegram API ошибка: %s", resp.text)
        else:
            log.info("Уведомление отправлено в Telegram.")
    except Exception as e:
        log.error("Не удалось отправить в Telegram: %s", e)


def build_today_summary(combined):
    from itertools import combinations
    from collections import defaultdict
    from datetime import datetime, timedelta
    import pandas as pd

    ASTANA_OFFSET = timedelta(hours=5)
    today = (datetime.utcnow() + ASTANA_OFFSET).date().isoformat()

    normal = combined[combined['Выпавшие шары'] != 'ОТМЕНЕН'].copy()
    normal['dt_astana'] = pd.to_datetime(normal['Дата и Время']) + ASTANA_OFFSET
    normal['date_astana'] = normal['dt_astana'].dt.date.astype(str)

    today_df = normal[normal['date_astana'] == today].copy()

    if today_df.empty:
        return f"7 из 42 — {today} (по Астане)\nЗа сегодня пока нет данных."

    today_df['balls_list'] = today_df['Выпавшие шары'].apply(lambda s: [int(x.strip()) for x in s.split(',')])
    today_df = today_df.sort_values('dt_astana')

    combo4_times = defaultdict(list)
    for _, row in today_df.iterrows():
        for c in combinations(sorted(row['balls_list']), 4):
            combo4_times[c].append(row['dt_astana'])

    repeated4 = [(c, times) for c, times in combo4_times.items() if len(times) >= 4]
    repeated4.sort(key=lambda x: -len(x[1]))

    lines = [
        f"7 из 42 — сводка за {today} (по Астане, GMT+5)",
        f"Тиражей с начала дня: {len(today_df)}",
        "",
        "Это ПОЛНЫЙ пересчёт с полуночи (по Астане) на текущий момент",
        "(не новые события, а сумма всех повторов с начала дня).",
        "",
        f"Четвёрок чисел с 4+ повторами: {len(repeated4)}",
    ]
    for combo, times in repeated4[:15]:
        times_str = ", ".join(t.strftime("%H:%M") for t in times)
        gaps = []
        for i in range(1, len(times)):
            delta_min = int((times[i] - times[i-1]).total_seconds() / 60)
            gaps.append(f"{delta_min}м")
        gaps_str = " -> ".join(gaps) if gaps else "-"
        lines.append(f"  {combo}: {len(times)}x [{times_str}] интервалы: {gaps_str}")

    if len(repeated4) > 15:
        lines.append(f"  ...ещё {len(repeated4)-15}, полный список — в итоге дня")

    lines.append("")
    lines.append("(Напоминание: по анализу 89 дней это фоновый шум, не сигнал.)")

    return "\n".join(lines)

def main():
    log.info("=== Автосбор: снимаем текущее окно результатов ===")
    driver = start_driver()
    try:
        open_results_panel(driver)
        raw = driver.execute_script(scrape_current_page())
        log.info("Снято тиражей за этот запуск: %d", len(raw))
    except Exception as e:
        log.error("Ошибка при скрапинге: %s", e)
        raw = []
    finally:
        driver.quit()

    fail_count = load_fail_count()

    if not raw:
        fail_count += 1
        save_fail_count(fail_count)
        log.warning("Пусто за этот прогон (%d подряд) - возможно сайт не отдал данные.", fail_count)
        if fail_count >= 3:
            send_telegram(
                f"\u26a0\ufe0f Бот не может собрать данные уже {fail_count} раза(ов) подряд.\n"
                "Возможно, сайт изменился или недоступен - стоит проверить вручную."
            )
            save_fail_count(0)
        return

    save_fail_count(0)

    records = enrich_records(raw)
    new_df = pd.DataFrame(records)

    old_df = load_existing()
    combined = pd.concat([old_df, new_df], ignore_index=True) if not old_df.empty else new_df
    save_progress(combined)

    today = date.today().isoformat()
    today_rows = combined[combined["Дата"] == today]  # для лога, приблизительно
    log.info("=== Сводка за сегодня (%s): %d тиражей в архиве ===", today, len(today_rows))

    summary_text = build_today_summary(combined)
    send_telegram(summary_text)


if __name__ == "__main__":
    main()
