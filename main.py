from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uuid
from datetime import datetime
import psycopg2
import os
from typing import List, Optional

from storage_yandex import upload_bytes_to_yandex  # используем наш модуль для Яндекс S3

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


# --- Ограничения для файлов (акт / видео для RLN-M3) ---

ALLOWED_ACT_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
}

ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",  # .mov
}

MAX_ACT_SIZE_MB = 10
MAX_VIDEO_SIZE_MB = 100


# 📌 Загрузить файл (акт, фото, видео) к заявке — уже через Яндекс Object Storage
@app.post("/order/{order_id}/upload_file")
async def upload_order_file(
    order_id: int,
    file: UploadFile = File(...),
    file_type: str = Form("other"),  # 'act', 'video', 'other'
):
    """
    Загрузка файла к заявке:
    - для RLN-M3: file_type = 'act' или 'video'
    - файл уходит в Яндекс Object Storage
    - в таблице files сохраняем ссылку (file_url)
    """

    conn = get_conn()
    cur = conn.cursor()

    # проверяем, что заказ существует
    cur.execute("SELECT id FROM orders WHERE id = %s;", (order_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Заказ не найден")

    content_type = file.content_type or "application/octet-stream"

    # Проверка типов и размеров
    if file_type == "act":
        if content_type not in ALLOWED_ACT_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Недопустимый тип файла для акта: {content_type}",
            )
        max_size_bytes = MAX_ACT_SIZE_MB * 1024 * 1024

    elif file_type == "video":
        if content_type not in ALLOWED_VIDEO_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Недопустимый тип видео: {content_type}",
            )
        max_size_bytes = MAX_VIDEO_SIZE_MB * 1024 * 1024

    else:
        # для прочих файлов можно задать общий лимит
        max_size_bytes = 20 * 1024 * 1024  # 20 МБ

    data = await file.read()

    if len(data) > max_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Файл слишком большой. Лимит: {max_size_bytes // (1024 * 1024)} МБ",
        )

    # Формируем путь в бакете: orders/{order_id}/{file_type}/{timestamp}_{original_name}
    safe_filename = file.filename.replace(" ", "_")
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    object_name = f"orders/{order_id}/{file_type}/{timestamp}_{safe_filename}"

    # Загружаем байты в Яндекс S3 и получаем URL
    try:
        file_url = upload_bytes_to_yandex(
            data=data,
            content_type=content_type,
            object_name=object_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки в Yandex S3: {e}")

    # записываем в таблицу files ссылку на файл
    try:
        cur.execute(
            """
            INSERT INTO files (order_id, file_url, file_type)
            VALUES (%s, %s, %s)
            RETURNING id, uploaded_at;
            """,
            (order_id, file_url, file_type),
        )
        row = cur.fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла в базе: {e}")
    finally:
        cur.close()
        conn.close()

    return {
        "status": "uploaded",
        "file_id": row[0],
        "order_id": order_id,
        "file_type": file_type,
        "url": file_url,
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
            "file_url": r[1],   # здесь уже будет полный URL из Яндекса
            "file_type": r[2],
            "uploaded_at": r[3],
        }
        for r in rows
    ]
