import ccxt
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import numpy as np
import os
import time

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("CryptoBot")

# Define conversation states
AMOUNT = 0

# Initialize Binance exchange via ccxt
binance = ccxt.binance({"enableRateLimit": True})
try:
    binance.load_markets()
except Exception as e:
    logger.error(f"Failed to load markets: {e}")
    raise

# Pre-filter active USDT pairs and sort by volume
active_usdt_pairs = []
for symbol in binance.markets:
    if symbol.endswith("/USDT") and binance.markets[symbol].get("active", False):
        active_usdt_pairs.append(symbol)

# Fetch tickers to sort by volume
try:
    tickers = binance.fetch_tickers([symbol for symbol in active_usdt_pairs])
    active_usdt_pairs.sort(
        key=lambda symbol: tickers[symbol]["quoteVolume"] if symbol in tickers else 0,
        reverse=True
    )
    active_usdt_pairs = active_usdt_pairs[:50]  # Limit to top 50 by volume
    logger.info(f"Limited to top {len(active_usdt_pairs)} USDT pairs by volume")
except Exception as e:
    logger.error(f"Failed to fetch tickers for volume sorting: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation and ask for the investment amount."""
    # Log the chat ID for scheduled messages (you can remove this after getting your chat ID)
    logger.info(f"Chat ID: {update.message.chat_id}")
    await update.message.reply_text(
        "Welcome to the Scalping Bot! Please enter the amount you want to invest in USDT (e.g., 100):"
    )
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the investment amount and provide a scalping recommendation."""
    await update.message.reply_text("Analyzing top Binance coins for scalping opportunities, please wait...")
    
    try:
        amount = float(update.message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid number greater than 0:")
        return AMOUNT
    context.user_data["amount"] = amount

    try:
        # Find a scalping opportunity
        recommended_coin, current_price, take_profit_price, stop_loss_price, volume, indicators = find_scalping_opportunity()
        if recommended_coin:
            # Calculate potential profit and loss
            buy_amount = amount / current_price  # Number of coins to buy
            profit_usdt = buy_amount * take_profit_price - amount  # Profit if sold at take-profit
            loss_usdt = amount - buy_amount * stop_loss_price  # Loss if sold at stop-loss

            await update.message.reply_text(
                f"Scalping Opportunity Found!\n"
                f"Recommended Coin: {recommended_coin}\n"
                f"Current Price: {current_price:.4f} USDT\n"
                f"Take-Profit Price: {take_profit_price:.4f} USDT (+2%)\n"
                f"Stop-Loss Price: {stop_loss_price:.4f} USDT (-1%)\n"
                f"24h Trading Volume: {volume:.2f} USDT\n"
                f"Indicators:\n"
                f"- Price Change (1h): {indicators['price_change_1h']:.2f}%\n"
                f"- Price Change (5m): {indicators['price_change_5m']:.2f}%\n"
                f"- RSI (14): {indicators['rsi']:.2f}\n"
                f"- MACD: {indicators['macd']:.4f}, Signal: {indicators['signal']:.4f}\n"
                f"- Volume Surge (5m): {indicators['volume_surge']:.2f}x\n"
                f"With {amount:.2f} USDT, you can buy {buy_amount:.4f} {recommended_coin}.\n"
                f"Potential Profit: ~{profit_usdt:.2f} USDT\n"
                f"Potential Loss: ~{loss_usdt:.2f} USDT\n\n"
                f"⚠️ **Risk Warning**: Scalping is a high-risk strategy. Prices can be volatile, and you may lose your investment. Always trade responsibly and consider using a stop-loss."
            )
        else:
            await update.message.reply_text(
                "No good scalping opportunities found at the moment. Try again later."
            )

    except Exception as e:
        logger.error(f"Error in get_amount: {e}")
        await update.message.reply_text(f"An error occurred: {str(e)}")

    return ConversationHandler.END

def calculate_rsi(closes, period=14):
    """Calculate the Relative Strength Index (RSI) for a given list of closing prices."""
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(closes, fast_period=12, slow_period=26, signal_period=9):
    """Calculate the MACD and signal line for a given list of closing prices."""
    def ema(data, period):
        k = 2 / (period + 1)
        ema_values = [data[0]]
        for i in range(1, len(data)):
            ema_values.append(data[i] * k + ema_values[-1] * (1 - k))
        return np.array(ema_values)

    fast_ema = ema(closes, fast_period)
    slow_ema = ema(closes, slow_period)
    macd = fast_ema - slow_ema

    signal = ema(macd, signal_period)
    return macd[-1], signal[-1]

def find_scalping_opportunity() -> tuple:
    """Find a coin with a good scalping opportunity using multiple indicators."""
    try:
        tickers = binance.fetch_tickers([symbol for symbol in active_usdt_pairs])
        logger.info(f"Fetched tickers for {len(tickers)} USDT pairs")
    except Exception as e:
        logger.error(f"Failed to fetch tickers: {e}")
        return None, 0, 0, 0, 0, {}

    best_coin = None
    best_score = 0
    current_price = 0
    take_profit_price = 0
    stop_loss_price = 0
    volume = 0
    best_indicators = {}

    for symbol in active_usdt_pairs:
        try:
            if symbol not in tickers:
                continue
            ticker = tickers[symbol]
            current_price = ticker.get("last")
            if not current_price or current_price <= 0:
                continue
            volume = ticker.get("quoteVolume", 0)
            if volume < 100000:
                continue

            since_1h = binance.milliseconds() - 3600 * 1000 * 2
            ohlcv_1h = binance.fetch_ohlcv(symbol, timeframe="1h", since=since_1h, limit=3)
            if len(ohlcv_1h) < 3:
                continue
            price_1h_ago = ohlcv_1h[1][4]
            price_change_1h = (current_price - price_1h_ago) / price_1h_ago * 100

            since_5m = binance.milliseconds() - 300 * 1000 * 30
            ohlcv_5m = binance.fetch_ohlcv(symbol, timeframe="5m", since=since_5m, limit=30)
            if len(ohlcv_5m) < 30:
                continue
            closes_5m = [candle[4] for candle in ohlcv_5m]
            volumes_5m = [candle[5] for candle in ohlcv_5m]

            price_5m_ago = ohlcv_5m[-2][4]
            price_change_5m = (current_price - price_5m_ago) / price_5m_ago * 100

            rsi = calculate_rsi(closes_5m, period=14)
            macd, signal = calculate_macd(closes_5m)

            avg_volume = np.mean(volumes_5m[-6:-1])
            current_volume = volumes_5m[-1]
            volume_surge = current_volume / avg_volume if avg_volume > 0 else 1

            if (
                -5 <= price_change_1h <= -1 and
                0.2 <= price_change_5m <= 1 and
                rsi < 30 and
                macd > signal and
                volume_surge > 1.5
            ):
                score = (
                    abs(price_change_1h) * 0.3 +
                    price_change_5m * 0.2 +
                    (30 - rsi) * 0.2 +
                    (macd - signal) * 100 * 0.2 +
                    volume_surge * 0.1
                )
                if score > best_score:
                    best_score = score
                    best_coin = symbol.split("/")[0]
                    current_price = current_price
                    take_profit_price = current_price * 1.02
                    stop_loss_price = current_price * 0.99
                    volume = volume
                    best_indicators = {
                        "price_change_1h": price_change_1h,
                        "price_change_5m": price_change_5m,
                        "rsi": rsi,
                        "macd": macd,
                        "signal": signal,
                        "volume_surge": volume_surge
                    }

        except Exception as e:
            logger.error(f"Error evaluating {symbol}: {e}")
            continue

    logger.info(f"Best scalping opportunity: {best_coin}, score: {best_score}")
    return best_coin, current_price, take_profit_price, stop_loss_price, volume, best_indicators

async def check_market(context: ContextTypes.DEFAULT_TYPE):
    """Periodically check for scalping opportunities and send alerts."""
    recommended_coin, current_price, take_profit_price, stop_loss_price, volume, indicators = find_scalping_opportunity()
    if recommended_coin:
        await context.bot.send_message(
            chat_id=600076643,  # Replace with your chat ID
            text=(
                f"Scalping Opportunity Found!\n"
                f"Recommended Coin: {recommended_coin}\n"
                f"Current Price: {current_price:.4f} USDT\n"
                f"Take-Profit Price: {take_profit_price:.4f} USDT (+2%)\n"
                f"Stop-Loss Price: {stop_loss_price:.4f} USDT (-1%)\n"
                f"24h Trading Volume: {volume:.2f} USDT\n"
                f"Indicators:\n"
                f"- Price Change (1h): {indicators['price_change_1h']:.2f}%\n"
                f"- Price Change (5m): {indicators['price_change_5m']:.2f}%\n"
                f"- RSI (14): {indicators['rsi']:.2f}\n"
                f"- MACD: {indicators['macd']:.4f}, Signal: {indicators['signal']:.4f}\n"
                f"- Volume Surge (5m): {indicators['volume_surge']:.2f}x\n\n"
                f"⚠️ **Risk Warning**: Scalping is a high-risk strategy."
            )
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text("Conversation cancelled.")
    return ConversationHandler.END

def main() -> None:
    """Run the bot."""
    application = Application.builder().token("7107491554:AAGizcW0xlmMWdxbsWgg5Boq30Tvjws56XY").build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    # Schedule market checks every 5 minutes
    application.job_queue.run_repeating(check_market, interval=300, first=10)

    # Use webhook for Heroku
    port = int(os.environ.get("PORT", 8443))
    token = "7107491554:AAGizcW0xlmMWdxbsWgg5Boq30Tvjws56XY"  # Must match the token above
    app_name = "bottelegram05"  # Replace with your Heroku app name
    while True:
        try:
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=token,
                webhook_url=f"https://{app_name}.herokuapp.com/{token}"
            )
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
            time.sleep(60)  # Wait 60 seconds before restarting

if __name__ == "__main__":
    main()
