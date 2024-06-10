from telegram import Bot
import hmac
import hashlib
import datetime
import asyncio
import logging
import os
import json
import requests
from logging import StreamHandler
from flask import Flask, request, Request, abort
from dotenv import load_dotenv
from db import add_subscription, update_payment_session_status

load_dotenv()

FLW_SECRET_KEY = os.getenv("FLW_SECRET_KEY")
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
    if subscription_type == "15 Minutes":
        return current_date + datetime.timedelta(minutes=2)
    elif subscription_type == "30 Minutes":
        return current_date + datetime.timedelta(minutes=30)
    elif subscription_type == "1 Hour":
        return current_date + datetime.timedelta(minutes=60)
    return None


async def send_notification(bot, telegram_chat_id, message):
    try:
        await bot.send_message(chat_id=telegram_chat_id, text=message)
        logger.info(f"Notification sent to {telegram_chat_id}: {message}")
    except Exception as e:
        logger.error(f"Error sending notification: {e}")


async def unban_user(bot, chat_id, user_id):
    try:
        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
        logger.info(f"User {user_id} unbanned in chat {chat_id}")
    except Exception as e:
        logger.error(f"Error unbanning user: {e}")

def initiate_payment(
    amount, email, reference, telegram_chat_id, subscription_type, username
):
    url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "amount": amount * 100,  # Paystack expects the amount in kobo (NGN)
        "email": email,
        "reference": reference,
        "metadata": {
            "telegram_chat_id": telegram_chat_id,
            "payment_reference": reference,
            "subscription_type": subscription_type,
            "username": username,
        },
    }
    response = requests.post(url, json=data, headers=headers)
    return response.json()
    

def verify_payment(payment_reference, payment_gateway):
    if payment_gateway == 'flutterwave':
        url = f"https://api.flutterwave.com/v3/transactions/{payment_reference}/verify"
        headers = {
            "Authorization": f'Bearer {FLW_SECRET_KEY}',
            "Content-Type": "application/json",
        }
        response = requests.get(url, headers=headers)
    else:
        url = f"https://api.paystack.co/transaction/verify/{payment_reference}"
        headers = {
            "Authorization": f'Bearer {PAYSTACK_SECRET_KEY}',
            "Content-Type": "application/json",
        }
        response = request.get(url, headers=headers)
    logger.info(f"Payment verification response: {response.json()}")
    return response.json()


async def create_temporary_invite_link(bot, chat_id, minutes_expire=30, member_limit=1):
    try:
        expire_date = datetime.datetime.now() + datetime.timedelta(
            minutes=minutes_expire
        )
        invite_link = await bot.create_chat_invite_link(
            chat_id=chat_id, expire_date=expire_date, member_limit=member_limit
        )
        logger.info(f"Invite link created: {invite_link.invite_link}")
        return invite_link.invite_link
    except Exception as e:
        logger.error(f"Error creating invite link: {e}")
        return None


def verify_paystack_webhook(request_body, signature):
    hash = hmac.new(
        PAYSTACK_SECRET_KEY.encode(), request_body, hashlib.sha512
    ).hexdigest()
    is_valid = hash == signature
    logger.info(f"Webhook verification: {'success' if is_valid else 'failure'}")
    return is_valid


def verify_flutterwave_webhook(payload, signature):
    computed_hash = hmac.new(
        FLW_SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return computed_hash == signature



@app.route("/webhook/paystack", methods=["POST"])
def paystack_webhook():
    try:
        logger.info("Received Paystack webhook notification")
        payload = request.get_json()
        logger.info(f"Webhook payload: {payload}")

        # Verify webhook is from paystack
        signature = request.headers.get("x-paystack-signature")
        raw_body = request.get_data()
        if not verify_paystack_webhook(raw_body, signature):
            logger.warning("Unauthorized request to paystack webhook blocked")
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
                    logger.info(
                        f"Payment session updated for reference: {payment_reference}"
                    )

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
                    logger.info(f"Subscription added to database for user {username}")

                    # Create temporary invite link
                    loop = asyncio.get_event_loop()
                    invite_link = loop.run_until_complete(
                        create_temporary_invite_link(bot_instance, TELEGRAM_GROUP_ID)
                    )

                    amount_in_naira = amount // 100

                    loop.run_until_complete(
                        unban_user(bot_instance, TELEGRAM_GROUP_ID, telegram_chat_id)
                    )

                    # Notification with invite link
                    loop.run_until_complete(
                        send_notification(
                            bot_instance,
                            telegram_chat_id,
                            f"Your subscription of {amount_in_naira} NGN for {subscription_type} was successful. Here is your invite link to join the group: {invite_link}",
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
        logger.error(f"Error processing Paystack webhook: {e}")
        return "An error occurred", 500



@app.route("/webhook/flutterwave", methods=["POST"])
def flutterwave_webhook():
    try:
        logger.info("Received Flutterwave webhook notification")
        payload = request.get_json()
        logger.info(f"Webhook payload: {payload}")

        # Verify webhook is from Flutterwave
        signature = request.headers.get("verif-hash")
        if not verify_flutterwave_webhook(json.dumps(payload), signature):
            logger.warning("Unauthorized request to Flutterwave webhook blocked")
            abort(405)

        if payload and payload.get("event") == "charge.completed":
            data = payload
            payment_reference = data.get("tx_ref")
            amount = data.get("amount")  # Amount in smallest currency unit
            currency = data.get("currency")
            metadata = data.get("meta")
            telegram_chat_id = metadata.get("telegram_chat_id")
            username = metadata.get("username")
            subscription_type = metadata.get("subscription_type")
            start_date = datetime.datetime.now()
            end_date = calculate_end_date(subscription_type)

            if payment_reference:
                # Verify payment with Flutterwave
                # Add your verification logic here
                payment_verification = {}  # Placeholder for verification logic

                if payment_verification.get("status"):
                    update_payment_session_status(payment_reference, "success")
                    logger.info(
                        f"Payment session updated for reference: {payment_reference}"
                    )

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
                    logger.info(f"Subscription added to database for user {username}")

                    # Create temporary invite link
                    loop = asyncio.get_event_loop()
                    invite_link = loop.run_until_complete(
                        create_temporary_invite_link(bot_instance, TELEGRAM_GROUP_ID)
                    )

                    amount_in_naira = amount // 100

                    loop.run_until_complete(
                        unban_user(bot_instance, TELEGRAM_GROUP_ID, telegram_chat_id)
                    )

                    # Notification with invite link
                    loop.run_until_complete(
                        send_notification(
                            bot_instance,
                            telegram_chat_id,
                            f"Your subscription of {amount_in_naira} NGN for {subscription_type} was successful. Here is your invite link to join the group: {invite_link}",
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
        logger.error(f"Error processing Flutterwave webhook: {e}")
        return "An error occurred", 500

if __name__ == "__main__":
    app.run(debug=True, port=4000)