from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
import uuid
from datetime import datetime
import psycopg2
import os

app = FastAPI()

# --- DB Connection ---
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


# Allow API for website + app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------- API -------------

@app.get("/")
def root():
    return {"status": "ok", "service": "RLNGroup backend"}


# 📌 Создание заявки (теперь в БАЗУ)
@app.post("/order/create")
def create_order(
    client_name: str = Form(...),
    client_phone: str = Form(...),
    comment: str = Form(""),
):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders (user_id, status, comment)
        VALUES (NULL, %s, %s)
        RETURNING id;
    """, ("Новая", comment))

    order_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    return {
        "status": "saved",
        "order_id": order_id,
        "client_name": client_name,
        "client_phone": client_phone,
        "comment": comment
    }


# 📌 Получение списка заявок из базы
@app.get("/order/list")
def order_list():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, status, comment, created_at FROM orders ORDER BY id DESC;")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {"id": r[0], "status": r[1], "comment": r[2], "created_at": r[3]}
        for r in rows
    ]
