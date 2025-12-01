from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uuid
from datetime import datetime
import psycopg2
import os
from typing import List

app = FastAPI()

# --- DB Connection ---
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


# Разрешаем запросы с сайта/приложения
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "service": "RLNGroup backend"}


# 📌 Создать заявку (сохраняем в базу)
@app.post("/order/create")
def create_order(
    client_name: str = Form(...),
    client_phone: str = Form(...),
    comment: str = Form(""),
):
    # Пока имя и телефон для простоты пишем в comment
    full_comment = f"Имя: {client_name}; Телефон: {client_phone}; Комментарий: {comment}"

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO orders (user_id, status, comment)
        VALUES (NULL, %s, %s)
        RETURNING id, created_at;
        """,
        ("Новая", full_comment),
    )

    row = cur.fetchone()
    order_id = row[0]
    created_at = row[1]

    conn.commit()
    cur.close()
    conn.close()

    return {
        "status": "saved",
        "order_id": order_id,
        "created_at": created_at,
    }


# 📌 Список заявок
@app.get("/order/list")
def order_list():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, status, comment, created_at FROM orders ORDER BY id DESC;"
    )
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            "id": r[0],
            "status": r[1],
            "comment": r[2],
            "created_at": r[3],
        }
        for r in rows
    ]


# 📌 Детали одной заявки
@app.get("/order/{order_id}")
def order_detail(order_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, status, comment, created_at, closed_at FROM orders WHERE id = %s;",
        (order_id,),
    )
    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    return {
        "id": row[0],
        "status": row[1],
        "comment": row[2],
        "created_at": row[3],
        "closed_at": row[4],
    }


# 📌 Обновить статус заявки
@app.post("/order/{order_id}/status")
def update_status(order_id: int, new_status: str = Form(...)):
    conn = get_conn()
    cur = conn.cursor()

    # Проверим, что заявка существует
    cur.execute("SELECT id FROM orders WHERE id = %s;", (order_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Заказ не найден")

    # Если закрываем - ставим closed_at
    if new_status.lower() in ["закрыта", "завершена", "completed"]:
        cur.execute(
            "UPDATE orders SET status = %s, closed_at = CURRENT_TIMESTAMP WHERE id = %s;",
            (new_status, order_id),
        )
    else:
        cur.execute(
            "UPDATE orders SET status = %s WHERE id = %s;",
            (new_status, order_id),
        )

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "ok", "order_id": order_id, "new_status": new_status}


# 📌 Загрузить файл (акт, фото, видео) к заявке
@app.post("/order/{order_id}/upload_file")
def upload_file(
    order_id: int,
    file: UploadFile = File(...),
    file_type: str = Form("other"),  # например: 'акт', 'фото', 'видео'
):
    conn = get_conn()
    cur = conn.cursor()

    # проверяем, что заказ существует
    cur.execute("SELECT id FROM orders WHERE id = %s;", (order_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Заказ не найден")

    # сохраняем файл в папку uploads (на Render хранение временное, но для MVP хватает)
    uploads_dir = "uploads"
    os.makedirs(uploads_dir, exist_ok=True)

    unique_name = f"{order_id}_{uuid.uuid4().hex}_{file.filename}"
    file_path = os.path.join(uploads_dir, unique_name)

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    # записываем в таблицу files
    cur.execute(
        """
        INSERT INTO files (order_id, file_url, file_type)
        VALUES (%s, %s, %s)
        RETURNING id, uploaded_at;
        """,
        (order_id, file_path, file_type),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return {
        "status": "uploaded",
        "file_id": row[0],
        "order_id": order_id,
        "file_type": file_type,
        "path": file_path,
        "uploaded_at": row[1],
    }


# 📌 Список файлов по заявке
@app.get("/order/{order_id}/files")
def list_files(order_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, file_url, file_type, uploaded_at
        FROM files
        WHERE order_id = %s
        ORDER BY uploaded_at DESC;
        """,
        (order_id,),
    )
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            "id": r[0],
            "file_url": r[1],
            "file_type": r[2],
            "uploaded_at": r[3],
        }
        for r in rows
    ]
from fastapi import UploadFile, File, Form
from storage_yandex import upload_file_to_yandex

@app.post("/upload")
async def upload_file(
    order_id: int = Form(...),
    doc_type: str = Form("generic"),
    file: UploadFile = File(...)
):
    data = await file.read()  # читаем байты
    url = upload_file_to_yandex(data, file.filename, order_id, doc_type)

    return {
        "status": "uploaded",
        "order_id": order_id,
        "doc_type": doc_type,
        "name": file.filename,
        "url": url
    }
