"""BigQuery persistence layer - substitui as abas da planilha "crm_database"
(ver sheets_db.py): "npi_periodos"/"npi_valores" (Resultados NPI) e
"projects"/"tasks" (Gantt).

Mesma interface publica das funcoes de sheets_db (mesmos dicts de retorno,
mesmos ids inteiros), pra rota trocar de backend so mudando a variavel de
ambiente NPI_STORAGE (backend/routes/npi_resultados.py) ou
PROJECTS_STORAGE (backend/routers/projects.py).

Tabelas no dataset PORTAL_BQ_DATASET (default "portal_crm") do projeto
BASE_VENDAS_BQ_PROJECT - o mesmo projeto que o portal ja consulta, onde a
conta de servico tem BigQuery Data Editor no dataset. O projeto tem custom
quota de ~30 GiB/dia de query (cota gratis = 1 TiB/mes), e toda query/DML
cobra no minimo 10 MB - por isso o cache de leitura de 30s, igual ao do
sheets_db.

Ids continuam inteiros sequenciais (MAX(id)+1 dentro do proprio INSERT) pra
preservar os ids ja existentes na planilha na migracao. Corrida entre dois
INSERTs simultaneos e teoricamente possivel, mas so admin escreve aqui e o
volume e de poucas linhas por mes.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from google.cloud import bigquery

from backend.event_sources import build_bigquery_client

_PROJECT_ID = os.getenv("BASE_VENDAS_BQ_PROJECT", "").strip()
_DATASET = os.getenv("PORTAL_BQ_DATASET", "portal_crm").strip()
_TIMEOUT_SECONDS = 30
_CACHE_TTL_SECONDS = 30

NPI_PERIODOS_SCHEMA = [
    bigquery.SchemaField("id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("nome", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("start_date", "DATE"),
    bigquery.SchemaField("end_date", "DATE"),
    bigquery.SchemaField("ordem", "INT64"),
    bigquery.SchemaField("created_by", "STRING"),
    bigquery.SchemaField("created_at", "TIMESTAMP"),
]

NPI_VALORES_SCHEMA = [
    bigquery.SchemaField("id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("periodo_id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("canal", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("receita", "NUMERIC"),
    bigquery.SchemaField("updated_by", "STRING"),
    bigquery.SchemaField("updated_at", "TIMESTAMP"),
]

PROJECTS_SCHEMA = [
    bigquery.SchemaField("id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("owner", "STRING"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("start_date", "DATE"),
    bigquery.SchemaField("end_date", "DATE"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("created_at", "TIMESTAMP"),
]

TASKS_SCHEMA = [
    bigquery.SchemaField("id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("project_id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("depends_on_task_id", "INT64"),
    bigquery.SchemaField("title", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("start_date", "DATE"),
    bigquery.SchemaField("end_date", "DATE"),
    bigquery.SchemaField("progress", "INT64"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("priority", "STRING"),
    bigquery.SchemaField("created_at", "TIMESTAMP"),
]

_SCHEMAS = {
    "npi_periodos": NPI_PERIODOS_SCHEMA,
    "npi_valores": NPI_VALORES_SCHEMA,
    "projects": PROJECTS_SCHEMA,
    "tasks": TASKS_SCHEMA,
}

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {name: (0.0, []) for name in _SCHEMAS}
_tables_ready = False


class BQDBError(Exception):
    """Generic BigQuery persistence error."""


def _table(name: str) -> str:
    if not _PROJECT_ID:
        raise BQDBError("Variavel BASE_VENDAS_BQ_PROJECT nao configurada")
    return f"`{_PROJECT_ID}.{_DATASET}.{name}`"


def _table_id(name: str) -> str:
    return f"{_PROJECT_ID}.{_DATASET}.{name}"


def _client() -> bigquery.Client:
    if not _PROJECT_ID:
        raise BQDBError("Variavel BASE_VENDAS_BQ_PROJECT nao configurada")
    try:
        return build_bigquery_client(_PROJECT_ID)
    except Exception as exc:
        raise BQDBError("Falha ao autenticar no BigQuery") from exc


def _run(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    _ensure_tables()
    client = _client()
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    try:
        rows = client.query(sql, job_config=job_config).result(timeout=_TIMEOUT_SECONDS)
        return [dict(row.items()) for row in rows]
    except Exception as exc:
        raise BQDBError(f"Falha ao executar consulta no BigQuery: {exc}") from exc


def _ensure_tables() -> None:
    """Cria as tabelas na primeira chamada do processo (idempotente)."""
    global _tables_ready
    if _tables_ready:
        return
    client = _client()
    try:
        for name, schema in _SCHEMAS.items():
            client.create_table(bigquery.Table(_table_id(name), schema=schema), exists_ok=True)
    except Exception as exc:
        raise BQDBError(f"Falha ao criar tabelas no dataset {_DATASET}: {exc}") from exc
    _tables_ready = True


def _get_cached(key: str) -> list[dict[str, Any]] | None:
    now = time.time()
    with _cache_lock:
        ts, data = _cache[key]
        if now - ts < _CACHE_TTL_SECONDS:
            return [item.copy() for item in data]
    return None


def _set_cache(key: str, data: list[dict[str, Any]]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), [item.copy() for item in data])


def _invalidate_cache(*keys: str) -> None:
    with _cache_lock:
        for key in keys:
            _cache[key] = (0.0, [])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat() + "Z"


def _parse_date(value: str | None) -> date | None:
    """Aceita ISO (formato que o portal grava) e dd/mm/aaaa (caso a planilha
    tenha reformatado a celula com USER_ENTERED)."""
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise BQDBError(f"Data invalida: {text!r}")


def _parse_timestamp(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%d/%m/%Y %H:%M:%S")
        except ValueError as exc:
            raise BQDBError(f"Data/hora invalida: {text!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _row_to_periodo(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "nome": row.get("nome") or "",
        "start_date": row["start_date"].isoformat() if row.get("start_date") else "",
        "end_date": row["end_date"].isoformat() if row.get("end_date") else "",
        "ordem": int(row.get("ordem") or 0),
        "created_by": row.get("created_by") or None,
        "created_at": _iso(row.get("created_at")),
    }


def _row_to_valor(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "periodo_id": int(row["periodo_id"]),
        "canal": row.get("canal") or "",
        "receita": float(row.get("receita") or 0),
        "updated_by": row.get("updated_by") or None,
        "updated_at": _iso(row.get("updated_at")),
    }


def get_npi_periodos() -> list[dict[str, Any]]:
    cached = _get_cached("npi_periodos")
    if cached is not None:
        return cached
    rows = _run(f"SELECT * FROM {_table('npi_periodos')} ORDER BY ordem, id")
    periodos = [_row_to_periodo(row) for row in rows]
    _set_cache("npi_periodos", periodos)
    return periodos


def get_npi_valores() -> list[dict[str, Any]]:
    cached = _get_cached("npi_valores")
    if cached is not None:
        return cached
    rows = _run(f"SELECT * FROM {_table('npi_valores')} ORDER BY id")
    valores = [_row_to_valor(row) for row in rows]
    _set_cache("npi_valores", valores)
    return valores


def create_npi_periodo(nome: str, start_date: str, end_date: str, created_by: str) -> dict[str, Any]:
    table = _table("npi_periodos")
    rows = _run(
        f"""
INSERT INTO {table} (id, nome, start_date, end_date, ordem, created_by, created_at)
SELECT
  COALESCE(MAX(id), 0) + 1, @nome, @start_date, @end_date,
  COALESCE(MAX(ordem), 0) + 1, @created_by, @created_at
FROM {table};
SELECT * FROM {table} WHERE id = (SELECT MAX(id) FROM {table});
""",
        [
            bigquery.ScalarQueryParameter("nome", "STRING", nome),
            bigquery.ScalarQueryParameter("start_date", "DATE", _parse_date(start_date)),
            bigquery.ScalarQueryParameter("end_date", "DATE", _parse_date(end_date)),
            bigquery.ScalarQueryParameter("created_by", "STRING", created_by),
            bigquery.ScalarQueryParameter("created_at", "TIMESTAMP", _now()),
        ],
    )
    _invalidate_cache("npi_periodos")
    return _row_to_periodo(rows[0])


def update_npi_periodo(periodo_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    table = _table("npi_periodos")
    rows = _run(
        f"""
UPDATE {table}
SET nome = @nome, start_date = @start_date, end_date = @end_date
WHERE id = @id;
SELECT * FROM {table} WHERE id = @id;
""",
        [
            bigquery.ScalarQueryParameter("id", "INT64", periodo_id),
            bigquery.ScalarQueryParameter("nome", "STRING", update_data["nome"]),
            bigquery.ScalarQueryParameter("start_date", "DATE", _parse_date(update_data["start_date"])),
            bigquery.ScalarQueryParameter("end_date", "DATE", _parse_date(update_data["end_date"])),
        ],
    )
    _invalidate_cache("npi_periodos")
    return _row_to_periodo(rows[0]) if rows else None


def delete_npi_periodo(periodo_id: int) -> bool:
    """Remove o periodo e todos os valores lancados nele (cascade)."""
    if not any(p["id"] == periodo_id for p in get_npi_periodos()):
        return False
    _run(
        f"""
BEGIN TRANSACTION;
DELETE FROM {_table('npi_valores')} WHERE periodo_id = @id;
DELETE FROM {_table('npi_periodos')} WHERE id = @id;
COMMIT TRANSACTION;
""",
        [bigquery.ScalarQueryParameter("id", "INT64", periodo_id)],
    )
    _invalidate_cache("npi_periodos", "npi_valores")
    return True


def upsert_npi_valores(periodo_id: int, receitas: dict[str, float], updated_by: str) -> list[dict[str, Any]]:
    """Grava varios canais do periodo num MERGE so (o calculo automatico
    salva os 5 canais de uma vez - 5 DMLs seguidos levariam ~10s)."""
    table = _table("npi_valores")
    entradas = [
        bigquery.StructQueryParameter(
            None,
            bigquery.ScalarQueryParameter("canal", "STRING", canal),
            bigquery.ScalarQueryParameter("receita", "NUMERIC", Decimal(str(round(receita, 2)))),
        )
        for canal, receita in receitas.items()
    ]
    rows = _run(
        f"""
MERGE {table} AS t
USING (
  SELECT
    e.canal, e.receita,
    (SELECT COALESCE(MAX(id), 0) FROM {table}) + ROW_NUMBER() OVER (ORDER BY e.canal) AS novo_id
  FROM UNNEST(@entradas) AS e
) AS s
ON t.periodo_id = @periodo_id AND t.canal = s.canal
WHEN MATCHED THEN
  UPDATE SET receita = s.receita, updated_by = @updated_by, updated_at = @updated_at
WHEN NOT MATCHED THEN
  INSERT (id, periodo_id, canal, receita, updated_by, updated_at)
  VALUES (s.novo_id, @periodo_id, s.canal, s.receita, @updated_by, @updated_at);
SELECT * FROM {table} WHERE periodo_id = @periodo_id AND canal IN UNNEST(@canais) ORDER BY id;
""",
        [
            bigquery.ArrayQueryParameter("entradas", "STRUCT", entradas),
            bigquery.ArrayQueryParameter("canais", "STRING", list(receitas.keys())),
            bigquery.ScalarQueryParameter("periodo_id", "INT64", periodo_id),
            bigquery.ScalarQueryParameter("updated_by", "STRING", updated_by),
            bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", _now()),
        ],
    )
    _invalidate_cache("npi_valores")
    return [_row_to_valor(row) for row in rows]


def upsert_npi_valor(periodo_id: int, canal: str, receita: float, updated_by: str) -> dict[str, Any]:
    return upsert_npi_valores(periodo_id, {canal: receita}, updated_by)[0]


def importar_npi(periodos: list[dict[str, Any]], valores: list[dict[str, Any]]) -> dict[str, Any]:
    """Substitui o conteudo das duas tabelas pelos registros informados (vindos
    de sheets_db), preservando ids. Usa load job com WRITE_TRUNCATE - gratis
    (nao conta na cota de query) e atomico por tabela. Valida tudo antes de
    gravar, pra nao deixar uma tabela migrada e a outra nao."""
    _ensure_tables()
    periodo_rows = [
        {
            "id": p["id"],
            "nome": p["nome"],
            "start_date": (d.isoformat() if (d := _parse_date(p["start_date"])) else None),
            "end_date": (d.isoformat() if (d := _parse_date(p["end_date"])) else None),
            "ordem": p["ordem"],
            "created_by": p["created_by"],
            "created_at": (t.isoformat() if (t := _parse_timestamp(p["created_at"])) else None),
        }
        for p in periodos
    ]
    valor_rows = [
        {
            "id": v["id"],
            "periodo_id": v["periodo_id"],
            "canal": v["canal"],
            "receita": str(round(v["receita"], 2)),
            "updated_by": v["updated_by"],
            "updated_at": (t.isoformat() if (t := _parse_timestamp(v["updated_at"])) else None),
        }
        for v in valores
    ]

    _load_truncate({"npi_periodos": periodo_rows, "npi_valores": valor_rows})
    return {"periodos": len(periodo_rows), "valores": len(valor_rows)}


def _load_truncate(rows_by_table: dict[str, list[dict[str, Any]]]) -> None:
    client = _client()
    try:
        for name, rows in rows_by_table.items():
            job_config = bigquery.LoadJobConfig(
                schema=_SCHEMAS[name],
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            )
            client.load_table_from_json(rows, _table_id(name), job_config=job_config).result(timeout=_TIMEOUT_SECONDS)
    except Exception as exc:
        raise BQDBError(f"Falha ao gravar dados migrados no BigQuery: {exc}") from exc
    _invalidate_cache(*rows_by_table.keys())


# --- Projects / tasks (Gantt) -------------------------------------------------

# Colunas editaveis via update_project/update_task e o tipo do parametro.
_PROJECT_FIELDS = {
    "name": "STRING",
    "owner": "STRING",
    "description": "STRING",
    "start_date": "DATE",
    "end_date": "DATE",
    "status": "STRING",
}
_TASK_FIELDS = {
    "depends_on_task_id": "INT64",
    "title": "STRING",
    "description": "STRING",
    "start_date": "DATE",
    "end_date": "DATE",
    "progress": "INT64",
    "status": "STRING",
    "priority": "STRING",
}


def _as_date(value: Any) -> date | None:
    """Rotas mandam `date` (pydantic); a planilha, string."""
    if value is None or isinstance(value, date):
        return value
    return _parse_date(str(value))


def _param(name: str, type_: str, value: Any) -> bigquery.ScalarQueryParameter:
    if type_ == "DATE":
        value = _as_date(value)
    return bigquery.ScalarQueryParameter(name, type_, value)


def _row_to_project(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": row.get("name") or "",
        "owner": row.get("owner") or None,
        "description": row.get("description") or None,
        "start_date": row["start_date"].isoformat() if row.get("start_date") else None,
        "end_date": row["end_date"].isoformat() if row.get("end_date") else None,
        "status": row.get("status") or "planned",
        "created_at": _iso(row.get("created_at")),
    }


def _row_to_task(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "project_id": int(row["project_id"]),
        "depends_on_task_id": int(row["depends_on_task_id"]) if row.get("depends_on_task_id") else None,
        "title": row.get("title") or "",
        "description": row.get("description") or None,
        "start_date": row["start_date"].isoformat() if row.get("start_date") else None,
        "end_date": row["end_date"].isoformat() if row.get("end_date") else None,
        "progress": max(0, min(100, int(row.get("progress") or 0))),
        "status": row.get("status") or "planned",
        "priority": row.get("priority") or "medium",
        "created_at": _iso(row.get("created_at")),
    }


def _load_projects() -> list[dict[str, Any]]:
    cached = _get_cached("projects")
    if cached is not None:
        return cached
    projects = [_row_to_project(row) for row in _run(f"SELECT * FROM {_table('projects')} ORDER BY id")]
    _set_cache("projects", projects)
    return projects


def _load_tasks() -> list[dict[str, Any]]:
    cached = _get_cached("tasks")
    if cached is not None:
        return cached
    tasks = [_row_to_task(row) for row in _run(f"SELECT * FROM {_table('tasks')} ORDER BY id")]
    _set_cache("tasks", tasks)
    return tasks


def get_projects() -> list[dict[str, Any]]:
    return _load_projects()


def get_project(project_id: int) -> dict[str, Any] | None:
    return next((p for p in _load_projects() if p["id"] == project_id), None)


def create_project(payload: dict[str, Any]) -> dict[str, Any]:
    table = _table("projects")
    values = {**payload, "status": payload.get("status") or "planned"}
    cols = list(_PROJECT_FIELDS)
    params = [_param(c, t, values.get(c)) for c, t in _PROJECT_FIELDS.items()]
    rows = _run(
        f"""
INSERT INTO {table} (id, {", ".join(cols)}, created_at)
SELECT COALESCE(MAX(id), 0) + 1, {", ".join("@" + c for c in cols)}, @created_at
FROM {table};
SELECT * FROM {table} WHERE id = (SELECT MAX(id) FROM {table});
""",
        params + [bigquery.ScalarQueryParameter("created_at", "TIMESTAMP", _now())],
    )
    _invalidate_cache("projects")
    return _row_to_project(rows[0])


def _update(table_name: str, fields: dict[str, str], row_id: int, update_data: dict[str, Any]) -> list[dict[str, Any]]:
    table = _table(table_name)
    keys = [k for k in update_data if k in fields]
    params = [_param(k, fields[k], update_data[k]) for k in keys]
    params.append(bigquery.ScalarQueryParameter("id", "INT64", row_id))
    update_sql = (
        f"UPDATE {table} SET {', '.join(f'{k} = @{k}' for k in keys)} WHERE id = @id;\n" if keys else ""
    )
    rows = _run(f"{update_sql}SELECT * FROM {table} WHERE id = @id;", params)
    _invalidate_cache(table_name)
    return rows


def update_project(project_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    rows = _update("projects", _PROJECT_FIELDS, project_id, update_data)
    return _row_to_project(rows[0]) if rows else None


def delete_project(project_id: int) -> bool:
    if get_project(project_id) is None:
        return False
    _run(
        f"""
BEGIN TRANSACTION;
DELETE FROM {_table('tasks')} WHERE project_id = @id;
DELETE FROM {_table('projects')} WHERE id = @id;
COMMIT TRANSACTION;
""",
        [bigquery.ScalarQueryParameter("id", "INT64", project_id)],
    )
    _invalidate_cache("projects", "tasks")
    return True


def get_all_tasks() -> list[dict[str, Any]]:
    return _load_tasks()


def get_tasks(project_id: int) -> list[dict[str, Any]]:
    return [t for t in _load_tasks() if t["project_id"] == project_id]


def get_task(task_id: int) -> dict[str, Any] | None:
    return next((t for t in _load_tasks() if t["id"] == task_id), None)


def create_task(project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    table = _table("tasks")
    values = {
        **payload,
        "progress": max(0, min(100, int(payload.get("progress", 0)))),
        "status": payload.get("status") or "planned",
        "priority": payload.get("priority") or "medium",
    }
    cols = list(_TASK_FIELDS)
    params = [_param(c, t, values.get(c)) for c, t in _TASK_FIELDS.items()]
    rows = _run(
        f"""
INSERT INTO {table} (id, project_id, {", ".join(cols)}, created_at)
SELECT COALESCE(MAX(id), 0) + 1, @project_id, {", ".join("@" + c for c in cols)}, @created_at
FROM {table};
SELECT * FROM {table} WHERE id = (SELECT MAX(id) FROM {table});
""",
        params + [
            bigquery.ScalarQueryParameter("project_id", "INT64", project_id),
            bigquery.ScalarQueryParameter("created_at", "TIMESTAMP", _now()),
        ],
    )
    _invalidate_cache("tasks")
    return _row_to_task(rows[0])


def update_task(task_id: int, update_data: dict[str, Any]) -> dict[str, Any] | None:
    rows = _update("tasks", _TASK_FIELDS, task_id, update_data)
    return _row_to_task(rows[0]) if rows else None


def delete_task(task_id: int) -> bool:
    if get_task(task_id) is None:
        return False
    _run(
        f"DELETE FROM {_table('tasks')} WHERE id = @id",
        [bigquery.ScalarQueryParameter("id", "INT64", task_id)],
    )
    _invalidate_cache("tasks")
    return True


def _iso_or_none(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def chave_project(p: dict[str, Any]) -> tuple:
    """Campos comparados na conferencia da migracao (datas normalizadas,
    porque a planilha pode devolver dd/mm/aaaa)."""
    return (
        p["id"], p["name"], p.get("owner"), p.get("description"),
        _iso_or_none(_as_date(p.get("start_date"))), _iso_or_none(_as_date(p.get("end_date"))), p.get("status"),
    )


def chave_task(t: dict[str, Any]) -> tuple:
    return (
        t["id"], t["project_id"], t.get("depends_on_task_id"), t["title"], t.get("description"),
        _iso_or_none(_as_date(t.get("start_date"))), _iso_or_none(_as_date(t.get("end_date"))),
        t.get("progress"), t.get("status"), t.get("priority"),
    )


def importar_projects(projects: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Mesmo esquema de importar_npi: substitui as duas tabelas pelos registros
    da planilha, preservando ids. Converte tudo antes de gravar, pra uma data
    invalida abortar sem deixar uma tabela migrada e a outra nao."""
    _ensure_tables()

    def _erro(tipo: str, item_id: int, exc: BQDBError) -> BQDBError:
        return BQDBError(f"{tipo} id={item_id}: {exc}")

    project_rows = []
    for p in projects:
        try:
            project_rows.append({
                "id": p["id"],
                "name": p["name"],
                "owner": p.get("owner"),
                "description": p.get("description"),
                "start_date": _iso_or_none(_as_date(p.get("start_date"))),
                "end_date": _iso_or_none(_as_date(p.get("end_date"))),
                "status": p.get("status"),
                "created_at": _iso_or_none(_parse_timestamp(p.get("created_at"))),
            })
        except BQDBError as exc:
            raise _erro("Projeto", p["id"], exc) from exc

    task_rows = []
    for t in tasks:
        try:
            task_rows.append({
                "id": t["id"],
                "project_id": t["project_id"],
                "depends_on_task_id": t.get("depends_on_task_id"),
                "title": t["title"],
                "description": t.get("description"),
                "start_date": _iso_or_none(_as_date(t.get("start_date"))),
                "end_date": _iso_or_none(_as_date(t.get("end_date"))),
                "progress": t.get("progress"),
                "status": t.get("status"),
                "priority": t.get("priority"),
                "created_at": _iso_or_none(_parse_timestamp(t.get("created_at"))),
            })
        except BQDBError as exc:
            raise _erro("Tarefa", t["id"], exc) from exc

    _load_truncate({"projects": project_rows, "tasks": task_rows})
    return {"projects": len(project_rows), "tasks": len(task_rows)}
