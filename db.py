import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
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
                telegram_chat_id BIGINT NOT NULL,
                payment_reference TEXT NOT NULL,
                username TEXT,
                subscription_type TEXT,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                group_id TEXT,
                status TEXT,
                PRIMARY KEY (telegram_chat_id, payment_reference)
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
        INSERT INTO subscriptions (telegram_chat_id, username, subscription_type, start_date, end_date, payment_reference, group_id, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
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


def get_user_subscription(chat_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        """
        SELECT * FROM subscriptions
        WHERE telegram_chat_id = %s
        AND status = 'active'
    """,
        (chat_id,),
    )
    subscription = cursor.fetchone()
    conn.close()

    return subscription


def get_expired_subscriptions():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        """
        SELECT * FROM subscriptions
        WHERE end_date < CURRENT_TIMESTAMP
        AND status = 'active'
    """
    )
    expired_subscriptions = cursor.fetchall()
    conn.close()
    return expired_subscriptions


def update_subscription_status(chat_id, payment_reference, status):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE subscriptions
        SET status = %s
        WHERE telegram_chat_id = %s AND payment_reference = %s
    """,
        (status, chat_id, payment_reference),
    )
    conn.commit()
    conn.close()

