# 1C2API

**Конфигурация 1С → Современный API-контракт**

> Парсит EDT-выгрузку 1С и автоматически генерирует OpenAPI, Postman коллекцию, Markdown документацию и Redoc UI.

**Статус:** ✅ `v0.1 готов` — парсинг EDT, OpenAPI 3.0, Postman, Markdown, Redoc работают.

---

## Проблема

Интеграция с 1С — это боль. Каждый раз: ручное создание HTTP-сервисов, написание документации, поддержка SDK. На среднюю конфигурацию уходит **1–2 недели**.

## Решение

```bash
python -m parser_1c.cli ./my-config --output ./api
```

**5 минут** — и у тебя готов полный API-контракт.

---

## Что умеет v0.1

- ✔️ Парсинг EDT-выгрузок (справочники, реквизиты, табличные части)
- ✔️ Генерация JSON Schema Draft-07
- ✔️ Генерация OpenAPI 3.0.3 (CRUD, пагинация `$top/$skip`, `$filter`)
- ✔️ Генерация Postman Collection v2.1
- ✔️ Генерация Markdown API Reference
- ✔️ Генерация Redoc HTML (интерактивная документация)
- ⏳ Swagger UI (в плане)
- ⏳ SDK через OpenAPI Generator (в плане)
- ⏳ Поддержка `.cf` через конфигуратор (в плане)

---

## Что генерируется

| Файл | Описание |
|---|---|
| `openapi.yaml` | OpenAPI 3.0.3 спецификация с CRUD эндпоинтами |
| `postman_collection.json` | Готовая коллекция для Postman / Insomnia |
| `api_docs.md` | Markdown API Reference |
| `redoc.html` | Интерактивная документация (открывается в браузере) |

---

## Быстрый старт

### Требования

- Python 3.11+
- EDT-выгрузка из 1С (папка с `.mdo` файлами)

### Установка

```bash
git clone https://github.com/Smrbruh/1c2api
cd 1c2api
pip install -r requirements.txt
```

### Запуск на тестовой конфигурации

```bash
# Запуск на встроенной фикстуре (справочник Номенклатура)
python -m parser_1c.cli tests/fixtures/simple-edt --output ./api

# Запуск на своей EDT-выгрузке
python -m parser_1c.cli ./my-edt-export --output ./api

# Только OpenAPI
python -m parser_1c.cli ./my-edt-export --output ./api --format openapi

# Только Markdown
python -m parser_1c.cli ./my-edt-export --output ./api --format markdown
```

### Результат в `./api/`

```
api/
├── openapi.yaml
├── postman_collection.json
├── api_docs.md
└── redoc.html          ← открой в браузере
```

> 📸 _Скриншот Redoc — placeholder_

---

## Архитектура

```
EDT XML (папка с .mdo файлами)
        │
        ▼
   EDTParser (lxml)
        │
        ▼
  Pydantic Models
  (Catalog, Field, TabularSection)
        │
        ▼
  JSON Schema (ядро)
        │
   ┌────┼────┬────────┐
   ▼    ▼    ▼        ▼
OpenAPI Postman Markdown Redoc
```

**Принцип:** JSON Schema — единый источник истины. Все генераторы берут данные из неё.

---

## Roadmap

| Версия | Что | Статус |
|---|---|---|
| `v0.1` | EDT → OpenAPI, Postman, Markdown, Redoc | ✅ Готово |
| `v0.1.5` | Поддержка `.cf` через конфигуратор 1С | ⏳ В плане |
| `v0.2` | Документы, регистры, перечисления | ⏳ В плане |
| `v0.3` | Тесты (Pytest/Vitest) + mock-сервер | ⏳ В плане |
| `v0.4` | BSL-генератор: HTTP-сервисы для 1С | ⏳ В плане |
| `v1.0` | Enterprise-фичи, CI/CD, SaaS | ⏳ В плане |

---

## Участие

1. Открой Issue с проблемой или предложением
2. Форкни репо и создай Pull Request
3. Запусти на своей конфигурации и напиши, что сломалось

Любой фидбек ценен — особенно: _«у меня не работает на конфигурации X версии Y»_.

---

## Лицензия

MIT

---

<div align="center">

**Сделано Bakdaulet Sotsial**

[Issues](https://github.com/Smrbruh/1c2api/issues) · [Smrbruh](https://github.com/Smrbruh)

</div>
