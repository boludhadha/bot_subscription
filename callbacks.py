import logging
from bot import bot_instance
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes,
)
from webhook_server import initiate_payment
from db import (
    add_payment_session,
    update_payment_session_status,
)
from bot import (
    TELEGRAM_GROUP_ID,
    subscription_plans,
    generate_unique_reference,
)

async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        logging.info(f"Cancel button clicked with callback data: {query.data}")

        if "|" in query.data:
            action, reference = query.data.split("|", 1)
            if action == "cancel" and reference:
                logging.info(f"Processing cancel action for reference: {reference}")
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
            text="Failed to cancel payment due to an internal error."
        )

async def handle_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_chat_id = query.data.split("|")[1]

    try:
        keyboard = [
            [InlineKeyboardButton("Flutterwave", callback_data="gateway_flutterwave")],
            [InlineKeyboardButton("Paystack", callback_data="gateway_paystack")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text="Choose a payment gateway:", reply_markup=reply_markup
        )
    except Exception as e:
        logging.error(f"Error in handle_renew handler: {e}")
        await query.edit_message_text(
            text="Failed to renew subscription due to an internal error."
        )

async def handle_gateway_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_data = context.user_data

    if query.data == "gateway_flutterwave":
        user_data['payment_gateway'] = 'flutterwave'
    elif query.data == "gateway_paystack":
        user_data['payment_gateway'] = 'paystack'

    keyboard = [
        [InlineKeyboardButton("15 minutes: 15,000 NGN", callback_data="15 Minutes")],
        [InlineKeyboardButton("30 minutes: 25,000 NGN", callback_data="30 Minutes")],
        [InlineKeyboardButton("1 Hour: 95,000 NGN", callback_data="1 Hour")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text="Choose a subscription plan:", reply_markup=reply_markup
    )
async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_plan = query.data

    if selected_plan not in subscription_plans:
        await query.edit_message_text(text="Invalid subscription plan selected.")
        return

    subscription_price = subscription_plans[selected_plan]["price"]
    unique_reference = generate_unique_reference()

    keyboard = [
        [InlineKeyboardButton("Cancel", callback_data=f"cancel|{unique_reference}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=f"Initiating {selected_plan} plan for {subscription_price/100:.2f} NGN. Please wait...",
        reply_markup=reply_markup,
    )

    payment_gateway = context.user_data.get('payment_gateway', 'flutterwave')

    payment_link = initiate_payment(
        amount=subscription_price,
        payment_reference=unique_reference,
        payment_gateway=payment_gateway,
    )

    if payment_link:
        await query.edit_message_text(
            text=f"Click the link to complete the payment: {payment_link}",
            reply_markup=reply_markup,
        )
        add_payment_session(query.message.chat.id, unique_reference, selected_plan, subscription_price)
    else:
        await query.edit_message_text(
            text="Failed to initiate payment. Please try again later."
        )
