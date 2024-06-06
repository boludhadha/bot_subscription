from telegram import Bot
from io import BytesIO
import hmac
import hashlib
import datetime
import asyncio
import logging
import os
import requests
from logging import StreamHandler
from flask import Flask, request, Request, abort
from dotenv import load_dotenv
from db import add_subscription, update_payment_session_status, get_connection

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")

app = Flask(__name__)

# Configure logging
log_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
console_handler = StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

logger = logging.getLogger(__name__)
logger.addHandler(console_handler)
logger.setLevel(logging.INFO)


bot_instance = Bot(token=BOT_TOKEN)


def calculate_end_date(subscription_type):
    current_date = datetime.datetime.now()
    if subscription_type == "1 Month":
        return current_date + datetime.timedelta(minutes=5)
    elif subscription_type == "3 Months":
        return current_date + datetime.timedelta(minutes=5)
    elif subscription_type == "1 Year":
        return current_date + datetime.timedelta(minutes=5)
    return None


async def send_notification(bot, telegram_chat_id, message):
    try:
        await bot.send_message(chat_id=telegram_chat_id, text=message)
    except Exception as e:
        logging.error(f"Error sending notification: {e}")


def verify_payment(payment_reference):
    url = f"https://api.paystack.co/transaction/verify/{payment_reference}"
    headers = {
        "Authorization": f'Bearer {os.getenv("PAYSTACK_SECRET_KEY")}',
        "Content-Type": "application/json",
    }
    response = requests.get(url, headers=headers)
    return response.json()


async def create_temporary_invite_link(
    bot, chat_id, expire_seconds=14400, member_limit=1
):
    try:
        expire_date = datetime.datetime.now() + datetime.timedelta(
            seconds=expire_seconds
        )
        invite_link = await bot.create_chat_invite_link(
            chat_id=chat_id, expire_date=expire_date, member_limit=member_limit
        )
        return invite_link.invite_link
    except Exception as e:
        logging.error(f"Error creating invite link: {e}")
        return None


def verify_paystack_webhook(request_body, signature):
    hash = hmac.new(
        PAYSTACK_SECRET_KEY.encode(), request_body, hashlib.sha512
    ).hexdigest()
    return hash == signature


@app.route("/webhook/paystack", methods=["POST"])
def paystack_webhook():
    try:
        logger.info("Received Paystack webhook notification")
        payload = request.get_json()
        logger.info("Webhook payload: %s", payload)

        # Verify that the webhook is from paystack
        signature = request.headers.get("x-paystack-signature")
        raw_body = request.get_data()
        if verify_paystack_webhook(raw_body, signature) == False:
            logger.info(
                "Unauthorized request to paystack webhook from {} blocked".format(
                    request.origin
                )
            )
            abort(405)

        if payload and payload.get("event") == "charge.success":
            data = payload.get("data", {})
            metadata = data.get("metadata", {})
            payment_reference = metadata.get("payment_reference")
            amount = data.get("amount")  # Amount in kobo
            currency = data.get("currency")
            telegram_chat_id = metadata.get("telegram_chat_id")
            username = metadata.get("username")
            subscription_type = metadata.get("subscription_type")
            start_date = datetime.datetime.now()
            end_date = calculate_end_date(subscription_type)

            if payment_reference:
                payment_verification = verify_payment(payment_reference)
                if payment_verification.get("status"):
                    update_payment_session_status(payment_reference, "success")

                    # Add subscription to database
                    add_subscription(
                        chat_id=telegram_chat_id,
                        username=username,
                        subscription_type=subscription_type,
                        start_date=start_date,
                        end_date=end_date,
                        payment_reference=payment_reference,
                        group_id=TELEGRAM_GROUP_ID,
                    )

                    # temporary invite link
                    invite_link = asyncio.run(
                        create_temporary_invite_link(bot_instance, TELEGRAM_GROUP_ID)
                    )

                    amount_in_naira = amount // 100

                    # notification with invite link
                    asyncio.run(
                        send_notification(
                            bot_instance,
                            telegram_chat_id,
                            f"Your subscription of {amount_in_naira} NGN for {subscription_type} was successful. Here is your invite link to join the Signal group: {invite_link}",
                        )
                    )

                    logger.info(
                        "Payment received - Reference: %s, Amount: %s %s",
                        payment_reference,
                        amount_in_naira,
                        currency,
                    )

        return "Webhook received successfully", 200
    except Exception as e:
        logger.error("Error processing Paystack webhook: %s", e)
        return "An error occurred", 500


if __name__ == "__main__":
    app.run(debug=True, port=4000)
