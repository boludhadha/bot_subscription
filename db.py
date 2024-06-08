import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import datetime
import logging

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_sessions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                payment_reference TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                telegram_chat_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                subscription_type TEXT,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                payment_reference TEXT,
                group_id TEXT
            )
        """
        )
        conn.commit()
        logging.info("Tables created successfully or already exist.")
    except Exception as e:
        logging.error(f"Error creating tables: {e}")
    finally:
        conn.close()


def add_subscription(
    chat_id,
    username,
    subscription_type,
    start_date,
    end_date,
    payment_reference,
    group_id,
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO subscriptions (telegram_chat_id, username, subscription_type, start_date, end_date, payment_reference, group_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (telegram_chat_id) DO UPDATE
        SET username = EXCLUDED.username,
            subscription_type = EXCLUDED.subscription_type,
            start_date = EXCLUDED.start_date,
            end_date = EXCLUDED.end_date,
            payment_reference = EXCLUDED.payment_reference,
            group_id = EXCLUDED.group_id
    """,
        (
            chat_id,
            username,
            subscription_type,
            start_date,
            end_date,
            payment_reference,
            group_id,
        ),
    )
    conn.commit()
    conn.close()


def add_payment_session(user_id, payment_reference, status="pending"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO payment_sessions (user_id, payment_reference, status)
        VALUES (%s, %s, %s)
        ON CONFLICT (payment_reference) DO UPDATE
        SET status = EXCLUDED.status
    """,
        (user_id, payment_reference, status),
    )
    conn.commit()
    conn.close()


def update_payment_session_status(payment_reference, status):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE payment_sessions
        SET status = %s
        WHERE payment_reference = %s
    """,
        (status, payment_reference),
    )
    conn.commit()
    conn.close()


def get_payment_session(payment_reference):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        """
        SELECT * FROM payment_sessions
        WHERE payment_reference = %s
    """,
        (payment_reference,),
    )
    payment_session = cursor.fetchone()
    conn.close()
    return payment_session


def get_expired_subscriptions():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        """
        SELECT * FROM subscriptions
        WHERE end_date < CURRENT_TIMESTAMP
    """
    )
    expired_subscriptions = cursor.fetchall()
    conn.close()
    return expired_subscriptions


def remove_subscription(chat_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        DELETE FROM subscriptions WHERE telegram_chat_id = %s
    """,
        (chat_id,),
    )
    conn.commit()
    conn.close()
