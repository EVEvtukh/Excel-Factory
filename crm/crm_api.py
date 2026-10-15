"""
crm_api.py
==========

FastAPI-бэкэнд для CRM.
Запуск:  uvicorn crm_api:app --reload
Или Docker:  docker compose up --build
"""
from __future__ import annotations

import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .crm_database import CRUDEngine, Client, Deal, Task

# =====================================================================
#  Pydantic-схемы (request/response)
# =====================================================================

# ---- Client ----
class ClientCreate(BaseModel):
    first_name: str = Field(..., min_length=1, description="Имя клиента")
    last_name: str = Field("", description="Фамилия")
    phone: str = Field("", description="Телефон")
    email: str = Field("", description="Email")
    notes: str = Field("", description="Заметки")

class ClientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None

class ClientOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    phone: str
    email: str
    status: str
    notes: str
    created_at: str
    updated_at: str

# ---- Deal ----
class DealCreate(BaseModel):
    client_id: Optional[int] = Field(None, description="ID клиента (nullable)")
    title: str = Field(..., min_length=1, description="Название сделки")
    description: str = Field("", description="Описание")
    status: str = Field("new", description="new / in_progress / closed / cancelled")
    amount: float = Field(0.0, description="Сумма сделки")

class DealUpdate(BaseModel):
    client_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[float] = None

class DealOut(BaseModel):
    id: int
    client_id: Optional[int]
    title: str
    description: str
    status: str
    amount: float
    created_at: str
    updated_at: str

# ---- Task ----
class TaskCreate(BaseModel):
    client_id: Optional[int] = Field(None, description="ID клиента (nullable)")
    deal_id: Optional[int] = Field(None, description="ID сделки (nullable)")
    title: str = Field(..., min_length=1, description="Название задачи")
    description: str = Field("", description="Описание")
    status: str = Field("pending", description="pending / in_progress / completed")
    priority: str = Field("normal", description="low / normal / high")
    due_date: str = Field("", description="ISO-дата дедлайна")

class TaskUpdate(BaseModel):
    client_id: Optional[int] = None
    deal_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None

class TaskOut(BaseModel):
    id: int
    client_id: Optional[int]
    deal_id: Optional[int]
    title: str
    description: str
    status: str
    priority: str
    due_date: str
    created_at: str

# =====================================================================
#  FastAPI app
# =====================================================================

app = FastAPI(
    title="Mini CRM",
    description="MVP CRM: клиенты, сделки, задачи",
    version="0.1.0",
)

_engine = CRUDEngine(db_path=os.getenv("CRM_DB_PATH", "crm.db"))

# =====================================================================
#  CLIENTS endpoints
# =====================================================================

@app.post("/clients", response_model=ClientOut, tags=["Clients"])
def add_client(body: ClientCreate):
    client = Client(
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        email=body.email,
        notes=body.notes,
    )
    created = _engine.create_client(client)
    return created

@app.get("/clients", response_model=list[ClientOut], tags=["Clients"])
def get_clients(
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    search: Optional[str] = Query(None, description="Поиск LIKE по имени/фамилии/телефону/email"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return _engine.list_clients(status=status, search=search, limit=limit, offset=offset)

@app.get("/clients/{client_id}", response_model=ClientOut, tags=["Clients"])
def get_client(client_id: int):
    client = _engine.get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return client

@app.patch("/clients/{client_id}", response_model=ClientOut, tags=["Clients"])
def patch_client(client_id: int, body: ClientUpdate):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    updated = _engine.update_client(client_id, **fields)
    if not updated:
        raise HTTPException(404, "Client not found")
    return updated

@app.post("/clients/{client_id}/archive", response_model=ClientOut, tags=["Clients"])
def archive_client(client_id: int):
    archived = _engine.archive_client(client_id)
    if not archived:
        raise HTTPException(404, "Client not found")
    return archived

@app.delete("/clients/{client_id}", tags=["Clients"])
def delete_client(client_id: int):
    if not _engine.delete_client(client_id):
        raise HTTPException(404, "Client not found")
    return {"ok": True}

# =====================================================================
#  DEALS endpoints
# =====================================================================

@app.post("/deals", response_model=DealOut, tags=["Deals"])
def add_deal(body: DealCreate):
    deal = Deal(
        client_id=body.client_id,
        title=body.title,
        description=body.description,
        status=body.status,
        amount=body.amount,
    )
    return _engine.create_deal(deal)

@app.get("/deals", response_model=list[DealOut], tags=["Deals"])
def get_deals(
    client_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return _engine.list_deals(client_id=client_id, status=status,
                               search=search, limit=limit, offset=offset)

@app.get("/deals/{deal_id}", response_model=DealOut, tags=["Deals"])
def get_deal(deal_id: int):
    deal = _engine.get_deal(deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    return deal

@app.patch("/deals/{deal_id}", response_model=DealOut, tags=["Deals"])
def patch_deal(deal_id: int, body: DealUpdate):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    updated = _engine.update_deal(deal_id, **fields)
    if not updated:
        raise HTTPException(404, "Deal not found")
    return updated

@app.delete("/deals/{deal_id}", tags=["Deals"])
def delete_deal(deal_id: int):
    if not _engine.delete_deal(deal_id):
        raise HTTPException(404, "Deal not found")
    return {"ok": True}

# =====================================================================
#  TASKS endpoints
# =====================================================================

@app.post("/tasks", response_model=TaskOut, tags=["Tasks"])
def add_task(body: TaskCreate):
    task = Task(
        client_id=body.client_id,
        deal_id=body.deal_id,
        title=body.title,
        description=body.description,
        status=body.status,
        priority=body.priority,
        due_date=body.due_date,
    )
    return _engine.create_task(task)

@app.get("/tasks", response_model=list[TaskOut], tags=["Tasks"])
def get_tasks(
    client_id: Optional[int] = Query(None),
    deal_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return _engine.list_tasks(client_id=client_id, deal_id=deal_id,
                               status=status, search=search, limit=limit, offset=offset)

@app.get("/tasks/{task_id}", response_model=TaskOut, tags=["Tasks"])
def get_task(task_id: int):
    task = _engine.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task

@app.patch("/tasks/{task_id}", response_model=TaskOut, tags=["Tasks"])
def patch_task(task_id: int, body: TaskUpdate):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    updated = _engine.update_task(task_id, **fields)
    if not updated:
        raise HTTPException(404, "Task not found")
    return updated

@app.post("/tasks/{task_id}/complete", response_model=TaskOut, tags=["Tasks"])
def complete_task(task_id: int):
    done = _engine.complete_task(task_id)
    if not done:
        raise HTTPException(404, "Task not found")
    return done

@app.delete("/tasks/{task_id}", tags=["Tasks"])
def delete_task(task_id: int):
    if not _engine.delete_task(task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}

# =====================================================================
#  Health check
# =====================================================================

@app.get("/", tags=["Meta"])
def health():
    return {"status": "ok", "service": "Mini CRM"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("crm_api:app", host="0.0.0.0", port=8000, reload=True)
