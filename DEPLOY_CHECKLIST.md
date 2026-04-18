# Deploy Checklist

Виконувати після кожного `git push`. Деплой = перезапуск бота (~10-30 сек downtime).

**Safe window: після 20:00 Київ** (бот активний вдень).

---

## Перед git push

```bash
# 1. Немає untracked файлів (урок 14.04)
git status

# 2. Import check зміненого модуля
python3 -c "import bot.handlers.tracking"   # або інший змінений модуль

# 3. Unit тести (не потребують Railway)
python3 -m pytest tests/unit/ -v
```

## Після деплою (Railway підхопив коміт)

```bash
# 4. Smoke тести на продакшн БД
cat tests/smoke_test.py | railway ssh --native -- 'python3 /dev/stdin'

# 5. DB assertion
cat tests/db_assert.py | railway ssh --native -- 'python3 /dev/stdin'

# 6. Перевірити Railway логи через 5 хв на відсутність ERROR
```

---

## Очікувані результати

| Перевірка | Очікуваний результат |
|-----------|---------------------|
| `git status` | Немає untracked файлів |
| import check | Без помилок |
| `pytest tests/unit/` | 11/12 PASS (1 known fail — database.py) |
| smoke_test.py | 4/4 PASS після деплою |
| db_assert.py | 18/18 OK |
| Railway логи | Немає ERROR |

---

## Відомі pending задачі

- [ ] Оновити `get_all_active_routes_today()` у `database.py` — додати `odometer_start` у SELECT
- [ ] Оновити `auto_close_active_routes` у `scheduler.py` — використовувати `odometer_start` для коректного повідомлення адміну
- [ ] Після цього фіксу: `pytest tests/unit/` має давати 12/12 PASS
