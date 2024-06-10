import logging
from bot import bot_instance
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from webhook_server import initiate_payment
from db import add_payment_session, update_payment_session_status

from bot import TELEGRAM_GROUP_ID, subscription_plans, generate_unique_reference

async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        logging.info(f"Cancel button clicked with callback data: {query.data}")

        if "|" in query.data:
            action, reference = query.data.split("|", 1)
            if action == "cancel" and reference:
                logging.info(f"Processing cancel action for reference: {reference}")
                # Update payment session status to 'cancelled'
                update_payment_session_status(reference, "cancelled")
                await query.edit_message_text(text="Payment process has been canceled.")
            else:
                logging.error(f"Invalid action or reference in callback data: {query.data}")
                await query.edit_message_text(text="Failed to cancel payment. Please try again later.")
        else:
            logging.error("Invalid callback data format")
            await query.edit_message_text(text="Failed to cancel payment. Please try again later.")
    except Exception as e:
        logging.error(f"Error in cancel_payment handler: {e}")
        await query.edit_message_text(text="Failed to cancel payment. Please try again later.")

async def handle_gateway_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_gateway = query.data
    context.user_data["payment_gateway"] = selected_gateway  # Store payment gateway in context
    logging.info(f"Selected payment gateway: {selected_gateway}")
    
    # Display subscription plans
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
    logging.info(f"Selected plan: {selected_plan}")
    payment_gateway = context.user_data.get("payment_gateway")  # Retrieve payment gateway from context
    if selected_plan in subscription_plans:
        subscription_details = subscription_plans[selected_plan]
        username = query.from_user.username
        email = "dboluwatife928@gmail.com"
        reference = generate_unique_reference()
        telegram_chat_id = query.from_user.id
        amount = subscription_details["price"]
        subscription_type = selected_plan

        payment_response = initiate_payment(
            amount, email, reference, telegram_chat_id, subscription_type, username, payment_gateway
        )

        if payment_response.get("status"):
            # Add payment session to the database
            add_payment_session(telegram_chat_id, reference)

            payment_url = payment_response["data"]["link"]
            keyboard = [
                [InlineKeyboardButton("Flutterwave Payment Page", url=payment_url)],
                [InlineKeyboardButton("Cancel", callback_data=f"cancel|{reference}")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"You selected the {selected_plan} plan.\n\n"
                f"Note that this is not a recurring subscription but rather a one-time payment, therefore after {selected_plan} you would be removed from the group.\n\n"
                "Proceed to payment by clicking the button link below👇🏽",
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

async def handle_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Display the subscription plans
    keyboard = [
        [InlineKeyboardButton("15 minutes: 15,000 NGN", callback_data="15 Minutes")],
        [InlineKeyboardButton("30 minutes: 25,000 NGN", callback_data="30 Minutes")],
        [InlineKeyboardButton("1 Hour: 95,000 NGN", callback_data="1 Hour")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text="Choose a subscription plan:", reply_markup=reply_markup
    )
