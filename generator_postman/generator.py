"""
generator_postman/generator.py — Postman Collection v2.1 генератор.

Принимает OpenAPI 3.0 dict (результат ``yaml.safe_load`` или
:meth:`~parser_1c.generator_openapi.OpenAPIGenerator.generate_dict`) и
строит Postman Collection v2.1, которую можно импортировать напрямую.

Структура коллекции
--------------------
Collection
└── Folder (по одному на каждый тег OpenAPI)
    └── Request (каждая операция path+method)
        ├── method, url
        ├── params (query параметры со значениями по умолчанию)
        ├── headers (Content-Type для операций с телом)
        ├── body (JSON example из схемы)
        └── описание из OpenAPI summary/description

Переменные коллекции
---------------------
- ``{{base_url}}``  — базовый URL (берётся из servers[0].url)
- ``{{api_key}}``   — заглушка для авторизации (не активирована)

$ref разрешаются рекурсивно из ``components/schemas`` и
``components/parameters``.
"""

from __future__ import annotations

import logging
import re
import uuid
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)

# Тип для OpenAPI/Postman словарей
OADict = dict[str, Any]

# HTTP методы в порядке отображения в коллекции
_METHOD_ORDER = ("get", "post", "put", "patch", "delete", "head", "options")

# Postman Collection schema URI
_COLLECTION_SCHEMA = (
    "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
)


# ---------------------------------------------------------------------------
# $ref resolver
# ---------------------------------------------------------------------------

def _resolve_ref(ref: str, spec: OADict) -> OADict:
    """Разрешить JSON Reference вида ``#/components/schemas/Foo``.

    Args:
        ref:  Строка вида ``#/path/to/component``.
        spec: Корень OpenAPI документа.

    Returns:
        Разыменованный объект или пустой dict при неразрешимом ref.
    """
    if not ref.startswith("#/"):
        return {}
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return {}
    return node if isinstance(node, dict) else {}


def _deref(obj: OADict, spec: OADict, *, _depth: int = 0) -> OADict:
    """Рекурсивно разыменовать все ``$ref`` внутри *obj*.

    Ограничение глубины рекурсии — 8 уровней (защита от циклических схем).

    Args:
        obj:    Объект, потенциально содержащий ``$ref``.
        spec:   Корень OpenAPI (нужен для разрешения ссылок).
        _depth: Внутренний счётчик глубины.

    Returns:
        Новый объект без ``$ref`` (они заменены разыменованными значениями).
    """
    if _depth > 8:
        return obj
    if not isinstance(obj, dict):
        return obj

    if "$ref" in obj:
        resolved = _resolve_ref(obj["$ref"], spec)
        return _deref(resolved, spec, _depth=_depth + 1)

    return {k: _deref(v, spec, _depth=_depth + 1) if isinstance(v, dict) else v
            for k, v in obj.items()}


# ---------------------------------------------------------------------------
# Пример JSON из схемы
# ---------------------------------------------------------------------------

def _example_from_schema(schema: OADict, spec: OADict, *, _depth: int = 0) -> Any:
    """Рекурсивно сгенерировать минимальный JSON-пример из JSON Schema.

    Логика:
    - ``example`` / ``default`` → берём как есть
    - type object  → рекурсивно строим из ``properties``
    - type array   → ``[<пример одного элемента>]``
    - type string  → ``"string"`` / format-специфичные заглушки
    - type number  → ``0``
    - type boolean → ``false``
    - ``$ref``     → разрешаем и повторяем

    Args:
        schema: JSON Schema объект.
        spec:   Корень OpenAPI для разрешения ``$ref``.
        _depth: Внутренний счётчик глубины (ограничение 6 уровней).

    Returns:
        Python объект (dict / list / str / int / bool / None).
    """
    if _depth > 6:
        return None

    if "$ref" in schema:
        schema = _deref(schema, spec, _depth=_depth)

    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]

    t = schema.get("type", "object")

    if t == "object":
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        result: OADict = {}
        for name, prop_schema in props.items():
            # Пропускаем readOnly поля в примере тела запроса, но включаем при _depth > 0
            if prop_schema.get("readOnly") and _depth == 0:
                continue
            result[name] = _example_from_schema(prop_schema, spec, _depth=_depth + 1)
        return result

    if t == "array":
        items = schema.get("items", {})
        return [_example_from_schema(items, spec, _depth=_depth + 1)]

    if t == "string":
        fmt = schema.get("format", "")
        if fmt == "uuid":
            return "00000000-0000-0000-0000-000000000000"
        if fmt == "date-time":
            return "2024-01-01T00:00:00Z"
        if fmt == "date":
            return "2024-01-01"
        if fmt == "email":
            return "user@example.com"
        if fmt == "uri":
            return "https://example.com"
        # Используем description или title как подсказку
        hint = (schema.get("description") or schema.get("title") or "string")[:32]
        return hint

    if t in ("number", "integer"):
        return 0

    if t == "boolean":
        return False

    if t == "null":
        return None

    return None


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def _build_url(
    raw_path: str,
    base_url: str,
    path_params: list[OADict],
    query_params: list[OADict],
) -> OADict:
    """Построить Postman URL объект из пути OpenAPI.

    Args:
        raw_path:     Путь вида ``/catalogs/Номенклатура/{id}``.
        base_url:     Базовый URL (используется как ``{{base_url}}``).
        path_params:  Разыменованные path-параметры (для ``variable`` блока).
        query_params: Разыменованные query-параметры.

    Returns:
        Postman URL объект.
    """
    # Заменяем {param} → :param для Postman
    postman_path = re.sub(r"\{(\w+)\}", r":\1", raw_path)
    # Сегменты пути без ведущего слэша
    segments = [s for s in postman_path.lstrip("/").split("/") if s]

    url: OADict = {
        "raw": f"{{{{base_url}}}}{postman_path}",
        "host": ["{{base_url}}"],
        "path": segments,
    }

    if path_params:
        url["variable"] = [
            {
                "key": p["name"],
                "value": _example_from_schema(p.get("schema", {}), {}),
                "description": p.get("description", ""),
            }
            for p in path_params
        ]

    if query_params:
        url["query"] = [
            {
                "key": p["name"],
                "value": str(_example_from_schema(p.get("schema", {}), {})),
                "description": p.get("description", ""),
                "disabled": not p.get("required", False),
            }
            for p in query_params
        ]

    return url


# ---------------------------------------------------------------------------
# Request builder
# ---------------------------------------------------------------------------

def _build_request(
    path: str,
    method: str,
    operation: OADict,
    path_item: OADict,
    spec: OADict,
    base_url: str,
) -> OADict:
    """Собрать один Postman Request из операции OpenAPI.

    Args:
        path:      URL путь (/catalogs/Номенклатура).
        method:    HTTP метод в нижнем регистре.
        operation: Объект операции из spec['paths'][path][method].
        path_item: Объект пути (может содержать path-level parameters).
        spec:      Корень OpenAPI.
        base_url:  Базовый URL.

    Returns:
        Postman Request объект.
    """
    # --- Параметры: сливаем path-level + operation-level ---
    all_params_raw: list[OADict] = (
        list(path_item.get("parameters", []))
        + list(operation.get("parameters", []))
    )
    # Разыменовываем $ref
    all_params = [_deref(p, spec) for p in all_params_raw]

    path_params  = [p for p in all_params if p.get("in") == "path"]
    query_params = [p for p in all_params if p.get("in") == "query"]
    header_params = [p for p in all_params if p.get("in") == "header"]

    # --- URL ---
    url = _build_url(path, base_url, path_params, query_params)

    # --- Headers ---
    headers: list[OADict] = []
    for hp in header_params:
        headers.append({
            "key": hp["name"],
            "value": str(_example_from_schema(hp.get("schema", {}), spec)),
            "description": hp.get("description", ""),
        })

    # --- Body ---
    body: OADict | None = None
    req_body = operation.get("requestBody", {})
    if req_body:
        content = req_body.get("content", {})
        json_content = content.get("application/json", {})
        if json_content:
            body_schema = _deref(json_content.get("schema", {}), spec)
            example_data = _example_from_schema(body_schema, spec)

            import json
            headers.append({
                "key": "Content-Type",
                "value": "application/json",
            })
            body = {
                "mode": "raw",
                "raw": json.dumps(example_data, ensure_ascii=False, indent=2),
                "options": {
                    "raw": {"language": "json"},
                },
            }

    # --- Responses (описание) ---
    responses = operation.get("responses", {})

    # --- Собираем Request ---
    request: OADict = {
        "method": method.upper(),
        "header": headers,
        "url": url,
        "description": operation.get("description") or operation.get("summary", ""),
    }
    if body:
        request["body"] = body

    return request


# ---------------------------------------------------------------------------
# Postman Response builder (документационные примеры)
# ---------------------------------------------------------------------------

def _build_example_response(
    status_code: str,
    response_obj: OADict,
    spec: OADict,
) -> OADict:
    """Построить пример ответа для Postman.

    Args:
        status_code:  Строка "200", "404" и т.д.
        response_obj: Объект ответа из spec.
        spec:         Корень OpenAPI.

    Returns:
        Postman Response Example объект.
    """
    import json

    content = response_obj.get("content", {})
    json_content = content.get("application/json", {})
    body = ""
    if json_content:
        schema = _deref(json_content.get("schema", {}), spec)
        body = json.dumps(_example_from_schema(schema, spec), ensure_ascii=False, indent=2)

    return {
        "name": f"{status_code} — {response_obj.get('description', '')}",
        "originalRequest": {},
        "status": _http_status_text(status_code),
        "code": int(status_code) if status_code.isdigit() else 200,
        "_postman_previewlanguage": "json",
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "cookie": [],
        "body": body,
    }


def _http_status_text(code: str) -> str:
    _MAP = {
        "200": "OK", "201": "Created", "204": "No Content",
        "400": "Bad Request", "401": "Unauthorized", "403": "Forbidden",
        "404": "Not Found", "422": "Unprocessable Entity",
        "500": "Internal Server Error",
    }
    return _MAP.get(code, "")


# ---------------------------------------------------------------------------
# Folder builder
# ---------------------------------------------------------------------------

def _collect_operations(spec: OADict) -> dict[str, list[tuple[str, str, OADict, OADict]]]:
    """Собрать все операции, сгруппированные по первому тегу.

    Returns:
        ``{tag_name: [(path, method, operation, path_item), ...]}``
    """
    grouped: dict[str, list[tuple[str, str, OADict, OADict]]] = {}

    for path, path_item in spec.get("paths", {}).items():
        for method in _METHOD_ORDER:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            tags = operation.get("tags") or ["Default"]
            primary_tag = tags[0]
            grouped.setdefault(primary_tag, []).append(
                (path, method, operation, path_item)
            )

    return grouped


# ---------------------------------------------------------------------------
# Публичный класс
# ---------------------------------------------------------------------------

class PostmanGenerator:
    """Генератор Postman Collection v2.1 из OpenAPI 3.0 спецификации.

    Принимает разобранный OpenAPI dict (из ``yaml.safe_load`` или
    :meth:`~parser_1c.generator_openapi.OpenAPIGenerator.generate_dict`).

    Архитектура генерации:
    - операции группируются по первому тегу → папки коллекции
    - ``$ref`` разрешаются рекурсивно
    - для каждой операции строятся примеры request body и response
    - переменная ``{{base_url}}`` берётся из ``servers[0].url``

    Usage::

        spec = yaml.safe_load(Path("openapi.yaml").read_text())
        collection = PostmanGenerator(spec).generate()
        Path("postman.json").write_text(json.dumps(collection, ensure_ascii=False, indent=2))

    Args:
        spec:              OpenAPI 3.0 dict.
        collection_name:   Название коллекции (по умолчанию из info.title).
        include_responses: Добавлять ли примеры ответов в каждый реквест.
    """

    def __init__(
        self,
        spec: OADict,
        *,
        collection_name: str | None = None,
        include_responses: bool = True,
    ) -> None:
        self._spec = spec
        self._collection_name = collection_name or spec.get("info", {}).get("title", "API")
        self._include_responses = include_responses
        self._base_url = self._extract_base_url()

    # ------------------------------------------------------------------
    # Публичный метод
    # ------------------------------------------------------------------

    def generate(self) -> OADict:
        """Сгенерировать Postman Collection v2.1 как Python dict.

        Returns:
            Словарь, готовый к сериализации через ``json.dumps``.
        """
        folders = self._build_folders()

        collection: OADict = {
            "info": {
                "_postman_id": str(uuid.uuid4()),
                "name": self._collection_name,
                "description": self._spec.get("info", {}).get("description", ""),
                "schema": _COLLECTION_SCHEMA,
            },
            "variable": [
                {
                    "key": "base_url",
                    "value": self._base_url,
                    "type": "string",
                    "description": "Базовый URL API сервера",
                },
            ],
            "item": folders,
            "auth": None,
            "event": [],
        }

        total_requests = sum(len(f["item"]) for f in folders)
        logger.info(
            "PostmanGenerator: %d folders, %d requests",
            len(folders), total_requests,
        )
        return collection

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _extract_base_url(self) -> str:
        servers = self._spec.get("servers", [])
        if servers and isinstance(servers[0], dict):
            return servers[0].get("url", "http://localhost:8000/api/v1")
        return "http://localhost:8000/api/v1"

    def _build_folders(self) -> list[OADict]:
        """Построить список Postman Folder объектов, по одному на тег."""
        grouped = _collect_operations(self._spec)

        # Порядок папок следует порядку тегов в spec["tags"]
        tag_order = [t["name"] for t in self._spec.get("tags", [])]
        # Добавляем теги, которые встречаются в операциях, но отсутствуют в tags
        for tag in grouped:
            if tag not in tag_order:
                tag_order.append(tag)

        folders: list[OADict] = []
        for tag in tag_order:
            if tag not in grouped:
                continue
            items = [
                self._build_item(path, method, op, path_item)
                for path, method, op, path_item in grouped[tag]
            ]
            # Описание тега из spec["tags"]
            tag_desc = next(
                (t.get("description", "") for t in self._spec.get("tags", []) if t["name"] == tag),
                "",
            )
            folders.append({
                "name": tag,
                "description": tag_desc,
                "item": items,
            })

        return folders

    def _build_item(
        self,
        path: str,
        method: str,
        operation: OADict,
        path_item: OADict,
    ) -> OADict:
        """Собрать один Postman Item (Request + optional responses)."""
        name = operation.get("summary") or f"{method.upper()} {path}"

        request = _build_request(
            path=path,
            method=method,
            operation=operation,
            path_item=path_item,
            spec=self._spec,
            base_url=self._base_url,
        )

        item: OADict = {
            "name": name,
            "request": request,
            "response": [],
        }

        if self._include_responses:
            examples = []
            for code, resp_obj in operation.get("responses", {}).items():
                try:
                    resolved_resp = _deref(resp_obj, self._spec) if "$ref" in resp_obj else resp_obj
                    ex = _build_example_response(str(code), resolved_resp, self._spec)
                    ex["originalRequest"] = deepcopy(request)
                    examples.append(ex)
                except Exception:  # noqa: BLE001
                    pass
            item["response"] = examples

        return item
