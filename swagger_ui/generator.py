"""
swagger_ui/generator.py — Встроенный Swagger UI.

Генерирует самодостаточный ``index.html``, подгружающий Swagger UI из CDN
(unpkg.com) и указывающий на ``../openapi.yaml``.

Особенности
-----------
- Один HTML файл без локальных зависимостей
- CDN: ``https://unpkg.com/swagger-ui-dist@5``
- Конфигурируемый ``spec_url`` (по умолчанию ``../openapi.yaml``)
- ``deepLinking: true`` — сохраняет состояние в URL
- ``persistAuthorization: true`` — не теряет токен при обновлении
- ``tryItOutEnabled: true`` — сразу открыт режим "Try it out"
- CSP-совместимый: нет inline ``onclick``, только addEventListener
- Кастомная тема: цвета AITU / 1C2API

Usage::

    from parser_1c.swagger_ui.generator import generate_swagger_ui
    from pathlib import Path

    html = generate_swagger_ui(spec_url="../openapi.yaml")
    (output_dir / "swagger-ui" / "index.html").write_text(html, encoding="utf-8")
"""

from __future__ import annotations

import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

_SWAGGER_UI_VERSION = "5.17.14"
_CDN_BASE = f"https://unpkg.com/swagger-ui-dist@{_SWAGGER_UI_VERSION}"

# Цветовая схема 1C2API
_BRAND_PRIMARY   = "#e04b2f"   # 1С-красный
_BRAND_SECONDARY = "#2d3748"   # тёмно-серый
_BRAND_BG        = "#f7fafc"   # светло-серый фон


# ---------------------------------------------------------------------------
# HTML шаблон
# ---------------------------------------------------------------------------

def _build_html(
    spec_url: str,
    title: str,
    brand_primary: str,
    brand_secondary: str,
    brand_bg: str,
    cdn_base: str,
) -> str:
    """Сгенерировать HTML строку Swagger UI.

    Args:
        spec_url:        URL к OpenAPI YAML/JSON файлу.
        title:           Заголовок страницы.
        brand_primary:   Основной бренд-цвет (кнопки, методы GET).
        brand_secondary: Вторичный цвет (шапка, текст).
        brand_bg:        Цвет фона страницы.
        cdn_base:        Базовый URL CDN (без завершающего слэша).

    Returns:
        Полная HTML строка.
    """
    return textwrap.dedent(f"""\
    <!DOCTYPE html>
    <html lang="ru">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>{title}</title>
      <link rel="icon" type="image/svg+xml"
            href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📄</text></svg>" />
      <link rel="stylesheet"
            href="{cdn_base}/swagger-ui.css" />
      <style>
        /* ── Reset & base ─────────────────────────────────── */
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; }}
        body {{
          background: {brand_bg};
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                       "Helvetica Neue", Arial, sans-serif;
        }}

        /* ── Top banner ───────────────────────────────────── */
        .topbar {{
          background: {brand_secondary} !important;
          padding: 10px 20px;
          display: flex;
          align-items: center;
          gap: 12px;
          box-shadow: 0 2px 8px rgba(0,0,0,.35);
        }}
        .topbar-logo {{
          font-size: 22px;
          font-weight: 800;
          color: #fff;
          letter-spacing: -0.5px;
          text-decoration: none;
        }}
        .topbar-logo span {{ color: {brand_primary}; }}
        .topbar-subtitle {{
          font-size: 12px;
          color: rgba(255,255,255,.55);
          margin-top: 1px;
        }}
        .topbar-spacer {{ flex: 1; }}
        .topbar-version {{
          background: rgba(255,255,255,.12);
          border-radius: 4px;
          padding: 2px 8px;
          font-size: 11px;
          color: rgba(255,255,255,.75);
          font-family: monospace;
        }}

        /* ── Swagger UI overrides ─────────────────────────── */
        .swagger-ui .topbar {{ display: none !important; }}

        .swagger-ui .info {{
          margin: 24px 0 8px;
        }}
        .swagger-ui .info .title {{
          font-size: 28px;
          color: {brand_secondary};
        }}

        /* Method colour overrides — keep Swagger defaults + soften */
        .swagger-ui .opblock.opblock-get    {{ border-color: #61affe; background: rgba(97,175,254,.07); }}
        .swagger-ui .opblock.opblock-post   {{ border-color: #49cc90; background: rgba(73,204,144,.07); }}
        .swagger-ui .opblock.opblock-put    {{ border-color: #fca130; background: rgba(252,161,48,.07); }}
        .swagger-ui .opblock.opblock-patch  {{ border-color: #50e3c2; background: rgba(80,227,194,.07); }}
        .swagger-ui .opblock.opblock-delete {{ border-color: #f93e3e; background: rgba(249,62,62,.07); }}

        /* Execute button */
        .swagger-ui .btn.execute {{
          background: {brand_primary};
          border-color: {brand_primary};
          border-radius: 4px;
        }}
        .swagger-ui .btn.execute:hover {{
          background: #c0392b;
          border-color: #c0392b;
        }}

        /* Authorize button */
        .swagger-ui .btn.authorize {{
          color: {brand_secondary};
          border-color: {brand_secondary};
        }}

        /* Tag headings */
        .swagger-ui .opblock-tag {{
          border-bottom: 2px solid {brand_secondary}22;
          color: {brand_secondary};
          font-size: 18px;
        }}

        /* Scrollbar */
        ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: #cbd5e0; border-radius: 3px; }}

        /* Container */
        #swagger-ui {{
          max-width: 1400px;
          margin: 0 auto;
          padding: 0 20px 60px;
        }}
      </style>
    </head>
    <body>

    <!-- ── Top banner ── -->
    <header class="topbar">
      <a href="#" class="topbar-logo">1C<span>2API</span></a>
      <div>
        <div class="topbar-subtitle">OpenAPI Explorer</div>
      </div>
      <div class="topbar-spacer"></div>
      <span class="topbar-version" id="api-version-badge">v—</span>
    </header>

    <!-- ── Swagger UI mount point ── -->
    <div id="swagger-ui"></div>

    <script src="{cdn_base}/swagger-ui-bundle.js"></script>
    <script src="{cdn_base}/swagger-ui-standalone-preset.js"></script>
    <script>
    (function () {{
      "use strict";

      var ui = SwaggerUIBundle({{
        url: "{spec_url}",
        dom_id: "#swagger-ui",

        // Layout
        layout: "BaseLayout",
        deepLinking: true,
        displayRequestDuration: true,
        defaultModelsExpandDepth: 1,
        defaultModelExpandDepth: 2,
        docExpansion: "list",

        // UX
        tryItOutEnabled: true,
        persistAuthorization: true,
        filter: true,
        showExtensions: false,
        showCommonExtensions: false,
        syntaxHighlight: {{ theme: "tomorrow-night" }},

        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset,
        ],
        plugins: [
          SwaggerUIBundle.plugins.DownloadUrl,
        ],

        // Show spec load errors
        onComplete: function () {{
          var info = ui.getState().getIn(["spec", "json", "info"]);
          if (info) {{
            var badge = document.getElementById("api-version-badge");
            if (badge) {{
              badge.textContent = "v" + (info.get ? info.get("version") : info.version || "—");
            }}
          }}
        }},
      }});

      window.ui = ui;
    }})();
    </script>

    </body>
    </html>
    """)


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------

def generate_swagger_ui(
    spec_url: str = "../openapi.yaml",
    *,
    title: str = "1C2API — OpenAPI Explorer",
    brand_primary: str = _BRAND_PRIMARY,
    brand_secondary: str = _BRAND_SECONDARY,
    brand_bg: str = _BRAND_BG,
    cdn_base: str = _CDN_BASE,
) -> str:
    """Сгенерировать HTML Swagger UI как строку.

    Создаёт самодостаточный ``index.html``, подгружающий Swagger UI из CDN
    и указывающий на указанный ``spec_url``.

    Args:
        spec_url:        Относительный или абсолютный URL к OpenAPI файлу.
                         По умолчанию ``../openapi.yaml`` — соответствует
                         размещению ``swagger-ui/index.html`` рядом с
                         ``openapi.yaml``.
        title:           Заголовок HTML страницы.
        brand_primary:   Основной бренд-цвет (hex).
        brand_secondary: Вторичный цвет (hex).
        brand_bg:        Цвет фона (hex).
        cdn_base:        Базовый URL CDN без завершающего слэша.

    Returns:
        Строка HTML, готовая к записи в файл.

    Example::

        html = generate_swagger_ui(spec_url="../openapi.yaml")
        (output / "swagger-ui" / "index.html").write_text(html, encoding="utf-8")
    """
    return _build_html(
        spec_url=spec_url,
        title=title,
        brand_primary=brand_primary,
        brand_secondary=brand_secondary,
        brand_bg=brand_bg,
        cdn_base=cdn_base,
    )
