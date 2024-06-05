import logging
import os
import uuid
import datetime
import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Bot,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from db import (
    create_tables,
    add_subscription,
    add_payment_session,
    get_expired_subscriptions,
    remove_subscription,
    update_payment_session_status,
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")
PORT = int(os.environ.get("PORT", "8443"))

subscription_plans = {
    "1 Month": {"duration": datetime.timedelta(days=30), "price": 5000},
    "3 Months": {"duration": datetime.timedelta(days=90), "price": 12000},
    "1 Year": {"duration": datetime.timedelta(days=365), "price": 45000},
}

bot_instance = Bot(token=BOT_TOKEN)


def generate_unique_reference():
    reference = str(uuid.uuid4())
    if len(reference) > 100:
        reference = reference[:100]
    return reference


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        keyboard = [["Join Signal Group"], [
            "Mentorship"], ["Subscription Status"]]

        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            input_field_placeholder="Select an option below to continue👇🏽",
        )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Welcome, what would you like to do today at Only 1 Chuks sniper gang?",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logging.error(f"Error in start handler: {e}")


async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("1 Month: 5000 NGN", callback_data="1 Month")],
        [InlineKeyboardButton("3 Months: 12000 NGN",
                              callback_data="3 Months")],
        [InlineKeyboardButton("1 Year: 45000 NGN", callback_data="1 Year")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Choose a subscription plan:", reply_markup=reply_markup
    )


async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_plan = query.data
    logging.info(f"Selected plan: {selected_plan}")
    if selected_plan in subscription_plans:
        subscription_details = subscription_plans[selected_plan]
        username = query.from_user.username
        email = username + "@example.com"
        reference = generate_unique_reference()
        telegram_chat_id = query.from_user.id
        amount = subscription_details["price"]
        subscription_type = selected_plan

        payment_response = initiate_payment(
            amount, email, reference, telegram_chat_id, subscription_type, username
        )

        if payment_response.get("status"):
            # Add payment session to the database
            add_payment_session(telegram_chat_id, reference)

            payment_url = payment_response["data"]["authorization_url"]
            keyboard = [
                [InlineKeyboardButton("Pay Now", url=payment_url)],
                [InlineKeyboardButton(
                    "Cancel", callback_data=f"cancel|{reference}")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text=f"You selected the {selected_plan} plan. Note that this is not a recurring subscription but rather a one-time payment for only {selected_plan}. Proceed to payment to join the 01C gang:",
                reply_markup=reply_markup,
            )
        else:
            await query.edit_message_text(
                text="Failed to initiate payment. Please try again later."
            )
    else:
        logging.error(f"Invalid plan selected: {selected_plan}")
        await query.edit_message_text(
            text="Invalid subscription plan selected. Please try again."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text

    if user_message == "Join Signal Group":
        await plans(update, context)
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="You selected an option. Please use /plans to see subscription plans or other options.",
        )


async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        logging.info(f"Cancel button clicked with callback data: {query.data}")

        if "|" in query.data:
            action, reference = query.data.split("|", 1)
            if action == "cancel" and reference:
                logging.info(
                    f"Processing cancel action for reference: {reference}")
                # Update payment session status to 'cancelled'
                update_payment_session_status(reference, "cancelled")
                await query.edit_message_text(text="Payment process has been canceled.")
            else:
                logging.error(
                    f"Invalid action or reference in callback data: {query.data}"
                )
                await query.edit_message_text(
                    text="Failed to cancel payment. Please try again later."
                )
        else:
            logging.error("Invalid callback data format")
            await query.edit_message_text(
                text="Failed to cancel payment. Please try again later."
            )
    except Exception as e:
        logging.error(f"Error in cancel_payment handler: {e}")
        await query.edit_message_text(
            text="Failed to cancel payment. Please try again later."
        )


async def check_subscription_expiry(context: ContextTypes.DEFAULT_TYPE):
    expired_subscriptions = get_expired_subscriptions()
    for subscription in expired_subscriptions:
        telegram_chat_id = subscription["telegram_chat_id"]
        # Notify user about subscription expiration
        await bot_instance.send_message(
            chat_id=telegram_chat_id,
            text="Your subscription has expired. You will be removed from the group.",
        )
        # Remove user from the group
        await bot_instance.ban_chat_member(
            chat_id=TELEGRAM_GROUP_ID, user_id=telegram_chat_id
        )
        remove_subscription(telegram_chat_id)
        logging.info(
            f"User {telegram_chat_id} removed from group due to expired subscription"
        )


if __name__ == "__main__":
    # Create database tables if they do not exist
    create_tables()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    start_handler = CommandHandler("start", start)
    start_handler = CommandHandler("plans", plans)
    plans_handler = CallbackQueryHandler(
        select_plan, pattern="^1 Month$|^3 Months$|^1 Year$"
    )
    cancel_handler = CallbackQueryHandler(cancel_payment, pattern="^cancel\\|")
    message_handler = MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message)

    application.add_handler(start_handler)
    application.add_handler(plans_handler)
    application.add_handler(cancel_handler)
    application.add_handler(message_handler)

    # Periodically check for expired subscriptions
    job_queue = application.job_queue
    job_queue.run_repeating(
        check_subscription_expiry, interval=datetime.timedelta(seconds=200), first=0
    )  # Check every 5 seconds for testing

    # Run the bot
    application.run_polling()
