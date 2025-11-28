from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
import uuid
from datetime import datetime

app = FastAPI()

# Разрешаем запросы с любых доменов (потом сузим)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ВРЕМЕННОЕ хранилище заявок (потом сделаем базу данных)
orders = []


@app.get("/")
async def root():
    return {"status": "ok", "service": "RLNGroup backend"}


@app.post("/order/create")
async def create_order(
    client_name: str = Form(...),
    client_phone: str = Form(...),
    comment: str = Form(""),
):
    """
    Создать новую заявку на утилизацию.
    """
    order_id = uuid.uuid4().hex
    order = {
        "id": order_id,
        "client_name": client_name,
        "client_phone": client_phone,
        "comment": comment,
        "status": "Новая",
        "created_at": datetime.utcnow().isoformat(),
    }
    orders.append(order)
    return {"status": "ok", "order_id": order_id}


@app.get("/order/list")
async def list_orders():
    """
    Получить список всех заявок (пока без фильтров).
    """
    return orders
