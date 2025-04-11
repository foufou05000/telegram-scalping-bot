import os
import time
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, JobQueue
from telegram.ext.filters import Filters  # Updated import for Filters
import ccxt

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Define states for the conversation
AMOUNT = range(1)

def start(update, context):
    update.message.reply_text("Please enter the amount you want to invest:")
    return AMOUNT

def get_amount(update, context):
    context.user_data['amount'] = update.message.text
    update.message.reply_text(f"Amount set to {context.user_data['amount']}. Bot is now running.")
    return ConversationHandler.END

def cancel(update, context):
    update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

def check_market(context):
    try:
        # Initialize the Kraken exchange
        exchange = ccxt.kraken()
        # Fetch market data
        markets = exchange.fetch_markets()
        logger.info(f"Fetched {len(markets)} markets from Kraken")
        # Your market checking logic here
        # Example: Send a message to the chat if a condition is met
        chat_id = "600076643"  # Replace with your chat ID
        context.bot.send_message(chat_id=chat_id, text="Checking market... Found opportunities!")
    except ccxt.NetworkError as e:
        logger.error(f"Network error while fetching markets: {e}")
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error while fetching markets: {e}")
    except Exception as e:
        logger.error(f"Unexpected error while fetching markets: {e}")

def main() -> None:
    """Run the bot."""
    application = Application.builder().token("7107491554:AAGizcW0xlmMWdxbsWgg5Boq30Tvjws56XY").build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AMOUNT: [MessageHandler(Filters.text & ~Filters.command, get_amount)],  # Updated Filters usage
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # Ensure job_queue is initialized
    if application.job_queue is None:
        logger.warning("JobQueue is None, initializing manually...")
        application.job_queue = JobQueue()
        application.job_queue.set_application(application)
        application.job_queue.start()  # Start the job queue

    # Schedule market checks every 5 minutes
    application.job_queue.run_repeating(check_market, interval=300, first=10)

    # Use webhook for Heroku with retry logic
    port = int(os.environ.get("PORT", 8443))
    token = "7107491554:AAGizcW0xlmMWdxbsWgg5Boq30Tvjws56XY"  # Must match the token above
    app_name = "bottlegram05"  # Your Heroku app name
    max_retries = 5
    retry_delay = 30  # Seconds to wait between retries

    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to set webhook (attempt {attempt + 1}/{max_retries})...")
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=token,
                webhook_url=f"https://{app_name}.herokuapp.com/{token}"
            )
            logger.info("Webhook set successfully. Bot is running.")
            break  # Exit the loop if successful
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Bot failed to start.")
                raise  # Re-raise the exception to crash the dyno

if __name__ == '__main__':
    main()
