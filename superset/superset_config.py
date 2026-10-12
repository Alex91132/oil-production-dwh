# Конфигурация Superset для локального демо-стенда.
import os

# Ключ подписи сессий. На реальном сервере — длинная случайная строка из секретов.
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "local-demo-only-change-me")

# Метаданные Superset (дашборды, графики) — в SQLite внутри тома superset-home.
# Для локального стенда этого достаточно; в продакшене — отдельный PostgreSQL.
SQLALCHEMY_DATABASE_URI = "sqlite:////app/superset_home/superset.db"

# Интерфейс на русском (с переключателем на английский)
BABEL_DEFAULT_LOCALE = "ru"
LANGUAGES = {
    "ru": {"flag": "ru", "name": "Русский"},
    "en": {"flag": "us", "name": "English"},
}

# Русская локаль чисел и дат: «6 290», «50,8 %», месяцы по-русски
D3_FORMAT = {
    "decimal": ",",
    "thousands": " ",          # неразрывный пробел
    "grouping": [3],
    "currency": ["", " ₽"],
}
D3_TIME_FORMAT = {
    "dateTime": "%A, %e %B %Y г. %X",
    "date": "%d.%m.%Y",
    "time": "%H:%M:%S",
    "periods": ["AM", "PM"],
    "days": ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"],
    "shortDays": ["вс", "пн", "вт", "ср", "чт", "пт", "сб"],
    "months": ["январь", "февраль", "март", "апрель", "май", "июнь",
               "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"],
    "shortMonths": ["янв", "фев", "мар", "апр", "май", "июн",
                    "июл", "авг", "сен", "окт", "ноя", "дек"],
}

FEATURE_FLAGS = {
    "DASHBOARD_CROSS_FILTERS": True,
}

ROW_LIMIT = 50000
