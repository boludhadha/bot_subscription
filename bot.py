import logging
import os
import uuid
import pytz
import datetime
from dotenv import load_dotenv
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
    get_expired_subscriptions,
    get_user_subscription,
    update_subscription_status,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

FLUTTERWAVE_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")
PORT = int(os.environ.get("PORT", "8443"))

subscription_plans = {
    "15 Minutes": {"price": 15000},
    "30 Minutes": {"price": 25000},
    "1 Hour": {"price": 95000},
}

bot_instance = Bot(token=BOT_TOKEN)


def generate_unique_reference():
    reference = str(uuid.uuid4())
    if len(reference) > 100:
        reference = reference[:100]
    return reference


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    try:
        keyboard = [["Join Private Group"], ["Subscription Status"]]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            input_field_placeholder="Select an option below to interact with the bot",
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Welcome, please click on the 'Join private group' button below",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logging.error(f"Error in start handler: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_message = update.message.text

    if user_message == "Join Private Group":
        keyboard = [
            [InlineKeyboardButton("Flutterwave", callback_data="gateway_flutterwave")],
            [InlineKeyboardButton("Paystack", callback_data="gateway_paystack")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Choose a payment gateway:",
            reply_markup=reply_markup,
        )
    elif user_message == "Subscription Status":
        await check_subscription_status(update, context)
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="You selected an option. Please use /plans to see subscription plans or other options.",
        )


async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    keyboard = [
        [InlineKeyboardButton("15 minutes: 15,000 NGN", callback_data="15 Minutes")],
        [InlineKeyboardButton("30 minutes: 25,000 NGN", callback_data="30 Minutes")],
        [InlineKeyboardButton("1 Hour: 95,000 NGN", callback_data="1 Hour")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Choose a subscription plan:", reply_markup=reply_markup
    )


def expiry_formatting(day):
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return str(day) + suffix


async def check_subscription_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscription = get_user_subscription(update.effective_chat.id)

    if not subscription:
        await update.message.reply_text("You do not have an active subscription")
    else:
        logging.info(subscription["end_date"])
        expiry_date = datetime.datetime.fromisoformat(str(subscription["end_date"]))
        expiry_date = expiry_date.astimezone(pytz.timezone("Africa/Lagos"))
        day_with_suffix = expiry_formatting(expiry_date.day)
        formatted_expiry_date = expiry_date.strftime(
            f"{day_with_suffix} %B, %Y at %-I:%M%p"
        )
        formatted_expiry_date = (
            formatted_expiry_date[: len(day_with_suffix) + 1].lower()
            + formatted_expiry_date[len(day_with_suffix) + 1 :]
        )
        await update.message.reply_text(
            f"Your subscription expires on: {formatted_expiry_date}"
        )


async def check_subscription_expiry(context: ContextTypes.DEFAULT_TYPE):
    expired_subscriptions = get_expired_subscriptions()
    try:
        for subscription in expired_subscriptions:
            telegram_chat_id = subscription["telegram_chat_id"]
            payment_reference = subscription["payment_reference"]

            # Update subscription status to inactive
            update_subscription_status(telegram_chat_id, payment_reference, "inactive")

            # Remove user from the group
            await bot_instance.ban_chat_member(
                chat_id=TELEGRAM_GROUP_ID, user_id=telegram_chat_id
            )

            await delete_recent_user_messages(telegram_chat_id)

            keyboard = [
                [
                    InlineKeyboardButton(
                        "Renew", callback_data=f"renew|{telegram_chat_id}"
                    )
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await bot_instance.send_message(
                chat_id=telegram_chat_id,
                text="Your subscription has expired and you have been removed from the group. Renew your subscription to join again.",
                reply_markup=reply_markup,
            )
            logging.info(
                f"User {telegram_chat_id} removed from group due to expired subscription"
            )
    except:
        pass


async def delete_recent_user_messages(chat_id: int):
    # Get recent messages sent by the user in the group
    messages = await bot_instance.get_chat_history(chat_id)
    for message in messages:
        if message.from_user.id == chat_id:
            # Delete the message
            await bot_instance.delete_message(
                chat_id=chat_id, message_id=message.message_id
            )


if __name__ == "__main__":
    from callbacks import (
        cancel_payment,
        select_plan,
        handle_renew,
        handle_gateway_selection,
    )

    create_tables()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    start_handler = CommandHandler("start", start)
    plans_handler = CommandHandler("plans", plans)
    select_plan_handler = CallbackQueryHandler(
        select_plan, pattern="^15 Minutes$|^30 Minutes$|^1 Hour$"
    )
    gateway_selection_handler = CallbackQueryHandler(
        handle_gateway_selection, pattern="^gateway_flutterwave$|^gateway_paystack$"
    )
    cancel_handler = CallbackQueryHandler(cancel_payment, pattern="^cancel\\|")
    message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    renew_handler = CallbackQueryHandler(handle_renew, pattern="^renew\\|")

    application.add_handler(start_handler)
    application.add_handler(plans_handler)
    application.add_handler(select_plan_handler)
    application.add_handler(gateway_selection_handler)
    application.add_handler(cancel_handler)
    application.add_handler(message_handler)
    application.add_handler(renew_handler)

    job_queue = application.job_queue
    job_queue.run_repeating(
        check_subscription_expiry, interval=datetime.timedelta(seconds=10), first=0
    )

    application.run_polling()
