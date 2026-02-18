import streamlit as st
import pymysql
import pandas as pd
import plotly.graph_objects as go 
import random
import re
import bcrypt
import yfinance as yf
from datetime import datetime
import pytz
import feedparser
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh


# ==========================================
# DATABASE CONFIG
# ==========================================
def get_connection():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="",
        database="trading_app"
    )

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_live_exchange_price(symbol):
    """
    Fetch LIVE NSE price from exchange
    symbol: TCS, RELIANCE, INFY, ITC
    """
    try:
        # Auto-handle suffix if missing
        ticker_sym = symbol if "." in symbol else f"{symbol}.NS"
        ticker = yf.Ticker(ticker_sym)

        # Get the latest 1-minute interval data
        data = ticker.history(period="1d", interval="1m")

        if data.empty:
            return None, None

        # Extract Last Traded Price as a float
        ltp_val = data['Close'].iloc[-1]
        
        if pd.isna(ltp_val):
            return None, None
            
        ltp = float(round(ltp_val, 2))

        # Exchange timestamp
        ist = pytz.timezone("Asia/Kolkata")
        last_time = data.index[-1].tz_convert(ist)

        return ltp, last_time.strftime("%I:%M:%S %p")

    except Exception as e:
        print(f"Live price error for {symbol}: {e}")
        return None, None

def validate_email(email):
    return re.match(r'^[^@]+@[^@]+\.[^@]+$', email)

def validate_aadhar(aadhar):
    return bool(re.match(r'^\d{12}$', aadhar))

def validate_pan(pan):
    return bool(re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$', pan.upper()))

def validate_ifsc(ifsc):
    return bool(re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', ifsc.upper()))

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def validate_mobile(mobile):
    """
    Validates a 10-digit Indian mobile number.
    - Must be exactly 10 digits.
    - Must start with 6, 7, 8, or 9.
    """
    return bool(re.match(r'^[6-9]\d{9}$', str(mobile)))

def fetch_stock_data(ticker):
    """Accurately fetch Open and Prev Close using history"""
    try:
        # Auto-add .NS if missing and not already a global ticker
        if not ticker.endswith(".NS") and not ticker.endswith(".BO") and len(ticker) <= 5:
            search_ticker = f"{ticker}.NS"
        else:
            search_ticker = ticker
            
        stock = yf.Ticker(search_ticker)
        hist = stock.history(period="5d")
        
        if len(hist) < 2:
            return None

        today_open = round(float(hist['Open'].iloc[-1]), 2)
        prev_close = round(float(hist['Close'].iloc[-2]), 2)
        
        # Metadata
        info = stock.info
        ticker=ticker[:-3]
        return {
            'symbol': ticker.upper(), # Keep original symbol for DB match
            'company_name': info.get('longName', ticker),
            'category': info.get('sector', 'N/A'),
            'prev_close': prev_close,
            'today_open': today_open
        }
    except:
        return None

def sync_all_stocks(conn):
    """Fetch all stocks from DB and update their prices"""
    c = conn.cursor()
    c.execute("SELECT symbol FROM stocks")
    symbols = c.fetchall()
    
    for (sym,) in symbols:
        data = fetch_stock_data(sym)
        if data:
            c.execute("""
                UPDATE stocks 
                SET today_open=%s, prev_close=%s, company_name=%s
                WHERE symbol=%s
            """, (data['today_open'], data['prev_close'], data['company_name'], sym))
    conn.commit()


def save_trade_to_file(email, stock, qty, price, action, order_type):
    # Folder to store logs
    folder = "trade_logs"
    os.makedirs(folder, exist_ok=True)

    # Safe filename (replace @ and .)
    safe_email = email.replace("@","_").replace(".","_")
    file_path = os.path.join(folder, f"{safe_email}.txt")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    line = (
        f"{now} | {action} | {stock} | Qty: {qty} | "
        f"Price: ₹{price:.2f} | Brokerage: ₹{brokerage:.2f} | Type: {order_type}\n"
    )

    with open(file_path, "a", encoding="utf-8") as f:
        f.write(line)

def fetch_nse_news(limit):
    urls = [
    "https://in.investing.com/rss/news_25.rss"
    ]


    news = []

    for url in urls:
        feed = feedparser.parse(url)
        for e in feed.entries:
            news.append({
                "title": e.title,
                "summary": e.get("summary",""),
                "link": e.link
            })

    return news[:limit]

# ==========================================
# YFINANCE FUNCTIONS
# ==========================================

def add_stock_to_db(ticker, conn):
    """Add a stock to database using yfinance data"""
    stock_data = fetch_stock_data(ticker)
    
    if stock_data:
        try:
            c = conn.cursor()
            c.execute("""
                INSERT INTO stocks (symbol, company_name, category, prev_close, today_open)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                company_name=%s, category=%s, prev_close=%s, today_open=%s
            """, (
                stock_data['symbol'],
                stock_data['company_name'],
                stock_data['category'],
                stock_data['prev_close'],
                stock_data['today_open'],
                stock_data['company_name'],
                stock_data['category'],
                stock_data['prev_close'],
                stock_data['today_open']
            ))
            conn.commit()
            return True
        except Exception as e:
            st.error(f"Database error: {str(e)}")
            return False
    return False

# ==========================================
# AUTO EXECUTE LIMIT / STOP ORDERS
# ==========================================
def process_pending_limit_orders(conn):
    c = conn.cursor()
    # Fetch all pending orders across all users
    c.execute("SELECT id, email, symbol, qty, action, order_type, trigger_price FROM transactions WHERE status='PENDING'")
    pending_orders = c.fetchall()

    for order in pending_orders:
        oid, email, symbol, qty, action, o_type, t_price = order
        current_price, _ = get_live_exchange_price(symbol)
        
        if current_price is None: 
            continue

        # Logic: Does the market price satisfy the trigger?
        should_execute = False
        if "BUY" in o_type and current_price <= t_price:
            should_execute = True
        elif "SELL" in o_type and current_price >= t_price:
            should_execute = True
        elif o_type == "STOP-LOSS" and current_price <= t_price:
            should_execute = True
        if should_execute:
            total_val = current_price * qty
            # Fetch Brokerage (reuse your logic)
            COMMISSION_FLAT = 20.0
            COMMISSION_PCT = 0.0005
            brokerage = max(COMMISSION_FLAT, total_val * COMMISSION_PCT)

            if action == "BUY":
                c.execute("SELECT balance FROM users WHERE email=%s", (email,))
                user_bal = c.fetchone()[0]
                grand_total = total_val + brokerage
                
                if user_bal >= grand_total:
                    # Deduct from user, Pay Admin, Complete Order
                    c.execute("UPDATE users SET balance = balance - %s WHERE email=%s", (grand_total, email))
                    c.execute("UPDATE users SET balance = balance + %s WHERE email='admin@quantify.com'", (brokerage,))
                    c.execute("UPDATE transactions SET status='COMPLETE', price=%s WHERE id=%s", (current_price, oid))
            
            elif action == "SELL":
                user_receives = total_val - brokerage
                # Add to user, Pay Admin, Complete Order
                c.execute("UPDATE users SET balance = balance + %s WHERE email=%s", (user_receives, email))
                c.execute("UPDATE users SET balance = balance + %s WHERE email='admin@quantify.com'", (brokerage,))
                c.execute("UPDATE transactions SET status='COMPLETE', price=%s WHERE id=%s", (current_price, oid))
            
            conn.commit()

# ==========================================
# RELIABLE YFINANCE HELPERS (FIX FOR CHARTS)
# ==========================================
def get_intraday_data(symbol):
    """
    Fetch reliable intraday data. 
    Fix: Fetches 5 days of data and filters for the last available day 
    to ensure charts work even when the market is closed.
    """
    try:
        # Handle Ticker Suffix safely
        ticker = symbol
        if "." not in ticker:
            ticker = f"{symbol}.NS" # Default to NSE if no suffix

        stock = yf.Ticker(ticker)

        # FETCH 5 DAYS instead of 1 day to handle weekends/holidays
        df = stock.history(period="5d", interval="5m")

        if df.empty:
            return None

        # Reset index to access Datetime column
        df.reset_index(inplace=True)

        # Standardize column name (yfinance sometimes uses 'Date', sometimes 'Datetime')
        if 'Date' in df.columns:
            df = df.rename(columns={'Date': 'Datetime'})

        # Filter: Keep only the data for the LAST available date
        # This creates a "One Day" view regardless of whether it is today or last Friday
        df['JustDate'] = df['Datetime'].dt.date
        last_trading_day = df['JustDate'].max()
        final_df = df[df['JustDate'] == last_trading_day]

        return final_df

    except Exception as e:
        print(f"Error fetching chart data: {e}")
        return None

# ==========================================
# STREAMLIT CONFIG
# ==========================================
st.set_page_config(page_title="Quantify", page_icon="📈", layout="wide")

if "logged_in" not in st.session_state:
    st.session_state.update({
        "logged_in": False,
        "user_email": None,
        "user_name": None
    })

# ==========================================
# AUTHENTICATION / LANDING PAGE
# ==========================================
if not st.session_state["logged_in"]:
    st.markdown("<h1 style='text-align: center;'>📈 Quantify</h1>", unsafe_allow_html=True)
    st.write("---")

    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        auth_mode = st.selectbox("Welcome! Please select:", ["Login", "Sign Up"])

        # ---------- LOGIN PAGE ----------
        if auth_mode == "Login":
            with st.form("login_form"):
                st.subheader("User Login")
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                
                if st.form_submit_button("Login", use_container_width=True):
                
                    conn = get_connection()
                    c = conn.cursor()
        
                    # Fetch username, hashed password, and status
                    c.execute(
                        "SELECT username, password, status FROM users WHERE email=%s",
                        (email,)
                    )
                    user = c.fetchone()
        
                    if not user:
                        st.error("Invalid credentials")
                        conn.close()
        
                    else:
                        username, stored_password, status = user
        
                        # ✅ CHECK 1 — Suspension block
                        if status == "SUSPENDED":
                            st.error("🚫 Your account has been suspended by admin.")
                            conn.close()
                            st.stop()
        
                        # ✅ CHECK 2 — Password verification
                        if check_password(password, stored_password):
                        
                            with st.spinner("🔄 Synchronizing Market Data..."):
                                sync_all_stocks(conn)
        
                            st.session_state.update({
                                "logged_in": True,
                                "user_email": email,
                                "user_name": username
                            })
        
                            conn.close()
                            st.rerun()
        
                        else:
                            st.error("Invalid credentials")
                            conn.close()


        # ---------- SIGN UP PAGE (WITH AGE ELIGIBILITY) ----------
        elif auth_mode == "Sign Up":
            st.subheader("Create Account (KYC Required)")
            
            # --- STEP 1: BASIC DETAILS ---
            u_col1, u_col2 = st.columns(2)
            username = u_col1.text_input("Username")
            email = u_col2.text_input("Email")
            password = st.text_input("Password (min 6 chars)", type="password")
            
            p_col1, p_col2, p_col3 = st.columns(3)
            phone = p_col1.text_input("Phone Number")
            gender = p_col2.selectbox("Gender", ["Male", "Female", "Other"])
            dob = p_col3.date_input("Date of Birth", 
                                    min_value=datetime(1940, 1, 1), 
                                    max_value=datetime.now(),
                                    value=datetime(2000, 1, 1))
            
            i_col1, i_col2 = st.columns(2)
            aadhar = i_col1.text_input("Aadhar (12 Digits)")
            pan = i_col2.text_input("PAN (e.g. ABCDE1234F)")

            # --- AGE CALCULATION ---
            today = datetime.now().date()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

            if age < 18:
                st.error(f"You are only {age} years old. You are not Eligible to trade.")
            else:
                # --- STEP 2: BANK DETAILS (Only shows if 18+) ---
                st.success("You are eligible! Please provide your banking details.")
                st.write("---")
                st.caption("Bank Details for Settlements")
                
                b_col1, b_col2, b_col3 = st.columns(3)
                bank_name = b_col1.text_input("Bank Name")
                account_no = b_col2.text_input("Account Number")
                ifsc_code = b_col3.text_input("IFSC Code")

                # Submit button only appears for eligible users
                if st.button("Register & Complete KYC", use_container_width=True):
                    # Validations
                    if not validate_email(email):
                        st.error("Invalid email format.")
                    elif len(password) < 6:
                        st.error("Password must be at least 6 characters.")
                    elif not validate_aadhar(aadhar):
                        st.error("Invalid Aadhar format (12 digits required).")
                    elif not validate_pan(pan):
                        st.error("Invalid PAN format.")
                    elif not validate_ifsc(ifsc_code):
                        st.error("Invalid IFSC code.")
                    elif not validate_mobile(phone):
                        st.error("Please enter a valid 10-digit mobile number starting with 6-9.")
                    elif not account_no.isdigit():
                        st.error("Account number should only contain digits.")
                    elif not bank_name or not account_no or not ifsc_code:
                        st.error("Please fill all banking details.")
                    else:
                        try:
                            conn = get_connection()
                            c = conn.cursor()

                            # ===============================
                            # ✅ STEP 1 — CHECK PAN FIRST
                            # ===============================
                            c.execute("SELECT email, status FROM users WHERE pan=%s", (pan.upper(),))
                            pan_record = c.fetchone()

                            # 🚫 PAN exists & suspended → block signup completely
                            if pan_record and pan_record[1] == "SUSPENDED":
                                st.error("🚫 This PAN is linked to a suspended account. You cannot register again.")
                                conn.close()
                                st.stop()

                            # 🚫 PAN exists & active → already registered
                            if pan_record:
                                st.error("This PAN is already registered with another account.")
                                conn.close()
                                st.stop()

                            # ===============================
                            # ✅ STEP 2 — CHECK EMAIL
                            # ===============================
                            c.execute("SELECT email FROM users WHERE email=%s", (email,))
                            email_record = c.fetchone()

                            if email_record:
                                st.error("This email is already registered. Please login instead.")
                                conn.close()
                                st.stop()

                            # ===============================
                            # ✅ STEP 3 — INSERT NEW USER
                            # ===============================
                            query = """
                                INSERT INTO users (
                                    email, username, password, aadhar, pan, 
                                    phone, gender, dob, bank_name, account_no, ifsc_code, balance
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0.0)
                            """

                            c.execute(query, (
                                email, username, hash_password(password), aadhar, pan.upper(),
                                phone, gender, dob, bank_name, account_no, ifsc_code.upper()
                            ))

                            conn.commit()
                            conn.close()

                            st.success("Registration successful! You can now switch to Login.")
                        
                        except pymysql.err.IntegrityError:
                            st.error("This email is already registered.")

# ==========================================
# MAIN APPLICATION
# ==========================================
else:
    conn = get_connection()
    process_pending_limit_orders(conn)
    c = conn.cursor()

    au=pd.read_sql("SELECT email from users",conn)

    if st.session_state["user_email"] != 'admin@quantify.com':

        st.sidebar.title(f"Hello, {st.session_state['user_name']}")
        menu_options = ["Dashboard", "Live Market & Trade", "Watchlist", "Portfolio", "History", "Add Funds", "News"]

        # Initialize menu choice in session state if it doesn't exist
        if "menu_choice" not in st.session_state or st.session_state.menu_choice not in menu_options:
            st.session_state.menu_choice = "Dashboard"

        # Determine the index of the current choice to keep the radio button in sync
        current_index = menu_options.index(st.session_state.menu_choice)

        # Update choice based on sidebar selection
        st.session_state.menu_choice = st.sidebar.radio("Navigation", menu_options, index=current_index)
        menu = st.session_state.menu_choice

        if st.sidebar.button("Logout"):
            st.session_state["logged_in"] = False
            st.rerun()

        # ==========================================
        # DASHBOARD
        # ==========================================
        if menu == "Dashboard":
            st.header(f"📊 Market Overview - {datetime.now().strftime('%d %b %Y')}")

            c.execute("SELECT balance FROM users WHERE email=%s", (st.session_state["user_email"],))
            balance = c.fetchone()[0]

            col1, col2 = st.columns(2)
            col1.metric("Wallet Balance", f"₹ {balance:,.2f}")

            # This now reflects the fresh data synced at login
            df_stocks = pd.read_sql("SELECT symbol, company_name, prev_close, today_open FROM stocks", conn)

            if not df_stocks.empty:
                # Calculate Change % for the dashboard
                df_stocks['Change %'] = ((df_stocks['today_open'] - df_stocks['prev_close']) / df_stocks['prev_close'] * 100).round(2)
                st.dataframe(df_stocks, use_container_width=True, hide_index=True)
            else:
                st.info("No stocks available in the market.")

        # ==========================================
        # LIVE MARKET & TRADE
        # ==========================================
        elif menu == "Live Market & Trade":
            st.header("📈 Live Trading Terminal")
            # Brokerage Configuration
            COMMISSION_FLAT = 20.0  # Minimum ₹20
            COMMISSION_PCT = 0.0005 # 0.05% of trade value
            ADMIN_EMAIL = "admin@quantify.com"

            # 1. Stock Selection
            stocks = pd.read_sql("SELECT symbol, today_open FROM stocks", conn)
            if stocks.empty:
                st.warning("No stocks found. Go to 'Manage Stocks' to add some.")
                st.stop()

            col_list, col_chart = st.columns([1, 2])

            with col_list:
                stock = st.selectbox("Select Stock", stocks["symbol"])

                # Simulated Live Price (Fluctuation logic)
                base = stocks[stocks["symbol"] == stock]["today_open"].iloc[0]
                price, time_stamp = get_live_exchange_price(stock)

                if price is None:
                    st.warning("📴 Live market data unavailable")
                    st.stop()
                    
                st.metric("Live Price", f"₹ {price:,.2f}", delta=round(price - base, 2))

                st.divider()

                # Trading Panel
                qty = st.number_input("Quantity", min_value=1, value=1)
                action = st.radio("Action", ["BUY", "SELL"], horizontal=True)
                order_type = st.selectbox("Order Type", ["MARKET", "LIMIT BUY", "LIMIT SELL", "STOP-LOSS"])

                trigger_price = None
                if order_type != "MARKET":
                    trigger_price = st.number_input("Trigger Price (₹)", min_value=0.1, value=float(price))

                total = price * qty
                st.write(f"**Total Value:** ₹ {total:,.2f}")

                # Buttons
                if st.button("Confirm Order", use_container_width=True):
                    # 1. Calculate Costs
                    total_trade_value = price * qty
                    brokerage = max(COMMISSION_FLAT, total_trade_value * COMMISSION_PCT)

                    # Check current user balance
                    c.execute("SELECT balance FROM users WHERE email=%s", (st.session_state["user_email"],))
                    user_balance = c.fetchone()[0]

                    # --- INSIDE Confirm Order Logic ---
                    if order_type in ["LIMIT BUY", "LIMIT SELL", "STOP-LOSS"]:
                        # For Limit Orders, we just record the intent. No balance is deducted yet.
                        c.execute("""
                            INSERT INTO transactions (email, symbol, qty, price, action, order_type, trigger_price, status) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
                        """, (st.session_state["user_email"], stock, qty, price, action, order_type, trigger_price))
                        conn.commit()
                        st.info(f"Limit Order placed at ₹{trigger_price}. It will execute when the price hits this target.")
                        st.rerun()

                    if order_type == "MARKET":
                        if action == "BUY":
                            grand_total = total_trade_value + brokerage
                            if user_balance >= grand_total:
                                # Deduct from User (Price + Brokerage)
                                c.execute("UPDATE users SET balance = balance - %s WHERE email = %s", 
                                          (grand_total, st.session_state["user_email"]))

                                # Add to Admin (Brokerage only)
                                c.execute("UPDATE users SET balance = balance + %s WHERE email = %s", 
                                          (brokerage, ADMIN_EMAIL))

                                # Log Transaction
                                c.execute("""
                                    INSERT INTO transactions (email, symbol, qty, price, action, order_type,status) 
                                    VALUES (%s, %s, %s, %s, 'BUY', 'MARKET','COMPLETE')
                                """, (st.session_state["user_email"], stock, qty, price))

                                conn.commit()

                                save_trade_to_file(
                                st.session_state["user_email"],
                                stock,
                                qty,
                                price,
                                "BUY",
                                "MARKET"
                            )

                                st.rerun()
                            else:
                                st.error(f"Insufficient funds. You need ₹{grand_total - user_balance:.2f} more.")

                        elif action == "SELL":
                            # In a sell, the user gets the money MINUS the brokerage
                            user_receives = total_trade_value - brokerage

                            c.execute("SELECT COALESCE(SUM(CASE WHEN action='BUY' THEN qty ELSE -qty END),0) FROM transactions WHERE email=%s AND symbol=%s", 
                                      (st.session_state["user_email"], stock))
                            holding = c.fetchone()[0]

                            if holding >= qty:
                                # Add to User (Price - Brokerage)
                                c.execute("UPDATE users SET balance = balance + %s WHERE email = %s", 
                                          (user_receives, st.session_state["user_email"]))

                                # Add to Admin (Brokerage only)
                                c.execute("UPDATE users SET balance = balance + %s WHERE email = %s", 
                                          (brokerage, ADMIN_EMAIL))

                                # Log Transaction
                                c.execute("""
                                    INSERT INTO transactions (email, symbol, qty, price, action, order_type) 
                                    VALUES (%s, %s, %s, %s, 'SELL', 'MARKET')
                                """, (st.session_state["user_email"], stock, qty, price))

                                conn.commit()
                                st.success(f"Sold successfully! ₹{brokerage:.2f} brokerage sent to Admin.")
                                st.rerun()
                            else:
                                st.error("Not enough shares to sell.")
                        else:
                            c.execute("INSERT INTO transactions (email, symbol, qty, price, action, order_type, trigger_price) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                      (st.session_state["user_email"], stock, qty, price, action, order_type, trigger_price))
                            conn.commit()
                            st.success("Order Placed Successfully")

            with col_chart:
                # Add a manual refresh button for the chart
                col_header, col_btn = st.columns([4,1])
                col_header.subheader(f"{stock} Intraday Chart")
                if col_btn.button("🔄"):
                    st.rerun()

                data = get_intraday_data(stock)

                if data is None or data.empty:
                    st.warning("⚠️ Waiting for market data... (Market might be closed or Ticker invalid)")
                else:
                    # Get the date string for the title
                    chart_date = data['Datetime'].iloc[0].strftime('%d %b %Y')

                    fig = go.Figure()

                    # Candlestick Trace
                    fig.add_trace(go.Candlestick(
                        x=data['Datetime'],
                        open=data['Open'],
                        high=data['High'],
                        low=data['Low'],
                        close=data['Close'],
                        name='Price'
                    ))

                    fig.update_layout(
                        height=500,
                        xaxis_rangeslider_visible=False,
                        template="plotly_white",
                        title=f"<b>{stock}</b> • {chart_date} (5m Interval)",
                        yaxis_title="Price (INR)",
                        margin=dict(l=20, r=20, t=50, b=20)
                    )

                    st.plotly_chart(fig, use_container_width=True)

            st.subheader(f"📰 News for {stock}")
            stock_name = stock.split(".")[0].lower()
            news = fetch_nse_news(30)
            filtered = [
                n for n in news
                if stock_name in n["summary"].lower()
            ]
            if filtered:
                for n in filtered[:5]:
                    st.markdown(f"**{n['title']}**")
                    st.write(n["summary"])
                    st.markdown(f"[Read more]({n['link']})")
                    st.divider()
            else:
                st.info("No NSE news found for this stock yet.")



        # ==========================================
        # WATCHLIST
        # ==========================================
        elif menu == "Watchlist":
            stocks = pd.read_sql("SELECT symbol, today_open FROM stocks", conn)
            add_stock = st.selectbox("Add Stock", stocks["symbol"])

            if st.button("Add to Watchlist"):
                try:
                    c.execute("INSERT INTO watchlist (email,symbol) VALUES (%s,%s)",
                              (st.session_state["user_email"], add_stock))
                    conn.commit()
                    st.success("Added")
                except:
                    st.warning("Already in watchlist")

            wl_data = pd.read_sql("""
                SELECT w.symbol, s.today_open
                FROM watchlist w JOIN stocks s ON w.symbol=s.symbol
                WHERE w.email=%s
            """, conn, params=(st.session_state["user_email"],))

            if not wl_data.empty:
                wl_data['Live Price'] = wl_data['symbol'].apply(lambda x: get_live_exchange_price(x)[0])
                st.dataframe(wl_data, use_container_width=True)

        # ==========================================
        # PORTFOLIO
        # ==========================================
        elif menu == "Portfolio":
            st.header("💼 My Portfolio")

            # Calculate Holdings
            df = pd.read_sql("""
                SELECT symbol,
                SUM(CASE WHEN action='BUY' THEN qty ELSE -qty END) qty,
                SUM(CASE WHEN action='BUY' THEN price*qty ELSE -price*qty END) invested
                FROM transactions
                WHERE email=%s
                GROUP BY symbol
                HAVING qty>0
            """, conn, params=(st.session_state["user_email"],))

            if not df.empty:
                with st.spinner("Fetching real-time market valuations..."):

                    # We use .apply with a lambda to fetch the price for each symbol
                    df["Current Price"] = df["symbol"].apply(
                        lambda sym: get_live_exchange_price(sym)[0]
                    )

                    # Filter out any stocks where the price couldn't be fetched (None)
                    df = df.dropna(subset=["Current Price"])

                    # Mathematical calculations using float prices
                    df["Current Value"] = df["Current Price"] * df["qty"]
                    df["P/L"] = df["Current Value"] - df["invested"]
                    df["P/L %"] = (df["P/L"] / df["invested"] * 100).round(2)

                    # Summary Metrics
                    total_invested = df["invested"].sum()
                    current_value = df["Current Value"].sum()
                    total_pl = current_value - total_invested

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Total Invested", f"₹ {total_invested:,.2f}")
                    m2.metric("Current Value", f"₹ {current_value:,.2f}", delta=f"₹{total_pl:,.2f}")
                    m3.metric("Total P/L", f"₹ {total_pl:,.2f}")

                    st.divider()

                    col_charts1, col_charts2 = st.columns(2)

                    # Chart 1: Asset Allocation (Pie Chart)
                    with col_charts1:
                        st.subheader("Asset Allocation")
                        fig_pie = go.Figure(data=[go.Pie(labels=df['symbol'], values=df['Current Value'], hole=.4)])
                        fig_pie.update_layout(height=350, margin=dict(t=0, b=0, l=0, r=0))
                        st.plotly_chart(fig_pie, use_container_width=True)

                    # Chart 2: Profit/Loss per Stock (Bar Chart)
                    with col_charts2:
                        st.subheader("Stock-wise P/L")
                        colors = ['#2ecc71' if val >= 0 else '#e74c3c' for val in df['P/L']]
                        fig_bar = go.Figure(data=[go.Bar(
                            x=df['symbol'],
                            y=df['P/L'],
                            marker_color=colors
                        )])
                        fig_bar.update_layout(height=350, margin=dict(t=0, b=0, l=0, r=0))
                        st.plotly_chart(fig_bar, use_container_width=True)

                    # Detailed Table
                    st.subheader("Holdings Details")
                    st.dataframe(
                        df[["symbol", "qty", "invested", "Current Price", "Current Value", "P/L", "P/L %"]], 
                        use_container_width=True,
                        hide_index=True
                    )

                    # --- INSIDE Portfolio Section ---
                    st.write("---")
                    st.subheader("⏳ Pending Orders")

                    # Fetch only PENDING orders
                    pending_df = pd.read_sql("""
                        SELECT id, symbol, qty, action, order_type, trigger_price 
                        FROM transactions 
                        WHERE email=%s AND status='PENDING'
                    """, conn, params=(st.session_state["user_email"],))

                    if not pending_df.empty:
                        # Header row for the "Manual" table
                        h_col1, h_col2, h_col3, h_col4, h_col5, h_col6 = st.columns([2, 1, 1, 2, 2, 1])
                        h_col1.write("**Stock**")
                        h_col2.write("**Qty**")
                        h_col3.write("**Action**")
                        h_col4.write("**Type**")
                        h_col5.write("**Trigger**")
                        h_col6.write("**Cancel**")

                        for _, row in pending_df.iterrows():
                            c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1, 2, 2, 1])

                            c1.write(row['symbol'])
                            c2.write(row['qty'])
                            c3.write(row['action'])
                            c4.write(row['order_type'])
                            c5.write(f"₹{row['trigger_price']}")

                            # Unique key for each button using transaction ID
                            if c6.button("❌", key=f"cancel_{row['id']}"):
                                try:
                                    # Delete the pending order from DB
                                    c.execute("DELETE FROM transactions WHERE id=%s AND email=%s", 
                                              (row['id'], st.session_state["user_email"]))
                                    conn.commit()
                                    st.toast(f"Order for {row['symbol']} cancelled.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                    else:
                        st.info("No pending orders at the moment.")
            else:
                st.info("You don't own any stocks yet. Go to 'Live Market' to buy some!")

        # ==========================================
        # HISTORY
        # ==========================================
        elif menu == "History":
            st.dataframe(pd.read_sql("""
                SELECT symbol, qty, price, action, order_type, timestamp
                FROM transactions
                WHERE email=%s
                ORDER BY timestamp DESC
            """, conn, params=(st.session_state["user_email"],)), use_container_width=True)


        # ==========================================
        # ADD FUNDS (PROFESSIONAL FLOW)
        # ==========================================
        elif menu == "Add Funds":
            st.header("💳 Add Funds to Wallet")

            col1, col2 = st.columns([1, 1])

            with col1:
                amt = st.number_input("Enter Amount (₹)", min_value=100.0, step=100.0, help="Minimum deposit is ₹100")
                method = st.selectbox("Payment Method", ["UPI", "Net Banking", "Debit Card"])

                if st.button("Proceed to Pay", use_container_width=True):
                    if amt < 100:
                        st.error("Minimum amount is ₹100")
                    else:
                        # STEP 1: Simulate Payment Gateway
                        with st.status("Connecting to Payment Gateway...", expanded=True) as status:
                            st.write("Verifying Bank Details...")
                            import time
                            time.sleep(1)
                            st.write("Waiting for User Confirmation...")
                            time.sleep(1.5)
                            st.write("Payment Authorized!")
                            status.update(label="Payment Successful!", state="complete", expanded=False)

                        # STEP 2: Create a Transaction ID
                        tx_id = f"TXN{random.randint(100000, 999999)}"

                        try:
                            # STEP 3: Update User Balance
                            c.execute("UPDATE users SET balance = balance + %s WHERE email = %s", 
                                     (amt, st.session_state["user_email"]))

                            # STEP 4: Log the transaction (Assuming you have a fund_logs table)
                            # If you don't have this table yet, I recommend creating it!
                            # c.execute("INSERT INTO fund_logs (email, tx_id, amount, method, status) VALUES (%s, %s, %s, %s, 'SUCCESS')",
                            #          (st.session_state["user_email"], tx_id, amt, method))

                            conn.commit()

                            st.success(f"Successfully added ₹{amt:,.2f} to your account!")
                            st.info(f"Transaction ID: {tx_id}")

                            # Small delay before rerun to let user see the success message
                            time.sleep(2)
                            st.rerun()

                        except Exception as e:
                            st.error(f"Transaction Failed: {e}")

            with col2:
                # Display current balance for reference
                c.execute("SELECT balance FROM users WHERE email=%s", (st.session_state["user_email"],))
                current_bal = c.fetchone()[0]
                st.metric("Current Available Balance", f"₹ {current_bal:,.2f}")

                st.warning("""
                **Note:** * Funds will reflect in your account immediately.
                * Please do not refresh the page during transaction.
                """)
        
        elif menu == "News":
            st.header("📰 Indian NSE Market News")

            news = fetch_nse_news(20)
            
            for n in news:
                st.subheader(n["title"])
                st.write(n["summary"])
                st.markdown(f"[Read full article]({n['link']})")
                st.divider()

    # ==========================================
    # ADMIN SECTION
    # ==========================================
    else:
        st.sidebar.title("Hello, Admin")

        menu_options = ["Dashboard","Leaderboard","Transactions","Manage stocks"]

        if "menu_choice" not in st.session_state:
            st.session_state.menu_choice = "Dashboard"

        if st.session_state.menu_choice not in menu_options:
            st.session_state.menu_choice = menu_options[0]

        current_index = menu_options.index(st.session_state.menu_choice)
        st.session_state.menu_choice = st.sidebar.radio("Navigation", menu_options, index=current_index)
        menu = st.session_state.menu_choice

        if st.sidebar.button("Logout"):
            st.session_state["logged_in"] = False
            st.rerun()

        conn = get_connection()

        # ==========================================
        # ADMIN DASHBOARD
        # ==========================================
        if menu == "Dashboard":

            st.header("📊 Platform Overview")

            users = pd.read_sql("SELECT * FROM users", conn)
            tx = pd.read_sql("SELECT * FROM transactions", conn)
            stocks = pd.read_sql("SELECT * FROM stocks", conn)

            col1,col2,col3,col4 = st.columns(4)

            col1.metric("Total Users", len(users))
            col2.metric("Active Users", (users["status"]=="ACTIVE").sum())
            col3.metric("Suspended Users", (users["status"]=="SUSPENDED").sum())
            col4.metric("Stocks Listed", len(stocks))

            st.divider()

            st.subheader("Top Traders")
            if not tx.empty:
                top = users.sort_values("balance",ascending=False).head(10)
                chart_df = top.set_index("username")["balance"]
                st.bar_chart(chart_df)

        # ==========================================
        # LEADERBOARD + USER MANAGEMENT
        # ==========================================
        elif menu == "Leaderboard":

            users = pd.read_sql("SELECT * FROM users", conn)
            tx = pd.read_sql("SELECT email, symbol, qty, action FROM transactions", conn)

            # 🔎 SEARCH USER
            search = st.text_input("Search user")

            unique_stocks = tx['symbol'].unique()
            live_prices = {s: get_live_exchange_price(s)[0] for s in unique_stocks}

            leaderboard = []

            for _, u in users.iterrows():
                portfolio_value = u["balance"]
                user_tx = tx[tx["email"] == u["email"]]

                for sym in user_tx["symbol"].unique():
                    qty = user_tx[user_tx["symbol"] == sym].apply(
                        lambda x: x["qty"] if x["action"]=="BUY" else -x["qty"], axis=1
                    ).sum()

                    if qty>0:
                        price = live_prices.get(sym)
                        if price:
                            portfolio_value += price*qty

                leaderboard.append({
                    "User": u["username"],
                    "Email": u["email"],
                    "Portfolio Value": portfolio_value,
                    "Status": u["status"]
                })

            lb_df = pd.DataFrame(leaderboard).sort_values("Portfolio Value",ascending=False)
            lb_df["Rank"] = range(1,len(lb_df)+1)

            if search:
                lb_df = lb_df[lb_df["User"].str.contains(search,case=False)]

            # 🎖️ SHOW TABLE
            for _, row in lb_df.iterrows():

                col1,col2,col3,col4,col5,col6,col7 = st.columns([1,2,2,2,2,2,2])

                col1.write(row["Rank"])
                col2.write(row["User"])
                col3.write(f"₹ {row['Portfolio Value']:.2f}")
                col4.write(row["Status"])

                # 👁 VIEW USER DETAILS
                if col5.button("View", key="v_"+row["Email"]):
                    user_details = pd.read_sql(
                        "SELECT * FROM users WHERE email=%s",
                        conn,
                        params=(row["Email"],)
                    )
                    st.json(user_details.iloc[0].to_dict())

                # 📝 SUSPENSION REASON
                reason = col6.text_input("Reason", key="r_"+row["Email"])

                # 🔴 SUSPEND / 🟢 UNSUSPEND
                with conn.cursor() as cursor:

                    if row["Status"]=="ACTIVE":
                        if col7.button("Suspend", key="s_"+row["Email"]):
                            cursor.execute(
                                "UPDATE users SET status='SUSPENDED', suspend_reason=%s WHERE email=%s",
                                (reason,row["Email"])
                            )
                            conn.commit()
                            st.success(f"{row['User']} suspended")
                            st.rerun()
                    else:
                        if col7.button("Unsuspend", key="u_"+row["Email"]):
                            cursor.execute(
                                "UPDATE users SET status='ACTIVE', suspend_reason=NULL WHERE email=%s",
                                (row["Email"],)
                            )
                            conn.commit()
                            st.success(f"{row['User']} restored")
                            st.rerun()

        # ==========================================
        # TRANSACTION INSPECTOR
        # ==========================================
        elif menu == "Transactions":

            st.header("📜 All Transactions")

            tx = pd.read_sql(
                "SELECT email,symbol,qty,price,action,status,timestamp FROM transactions ORDER BY timestamp DESC",
                conn
            )

            st.dataframe(tx,use_container_width=True)

        # ==========================================
        # MANAGE STOCKS (YOUR ORIGINAL LOGIC KEPT)
        # ==========================================
        elif menu == "Manage stocks":

            st.header("🛠️ Real-Time Stock Management")

            with st.expander("➕ Add New Stock", expanded=True):
                col1,col2 = st.columns([3,1])
                new_ticker = col1.text_input("Ticker Symbol")
                if col2.button("Add/Update Stock",use_container_width=True):
                    if new_ticker:
                        new_ticker=new_ticker+'.NS'
                        success=add_stock_to_db(new_ticker.upper(),conn)
                        if success:
                            st.success("Stock Added/Updated")
                            st.rerun()
                        else:
                            st.warning("Enter Valid stock")

            st.divider()

            db_stocks=pd.read_sql("SELECT symbol,company_name FROM stocks",conn)

            if not db_stocks.empty:

                stock_list=db_stocks['symbol'].tolist()
                selected_stock=st.selectbox("Select stock",stock_list)+'.NS'

                btn1,btn2,_=st.columns([1,1,2])

                if btn1.button("🔄 Sync & Preview Data"):
                    stock_info=fetch_stock_data(selected_stock)
                    current_price,last_time=get_live_exchange_price(selected_stock)

                    if stock_info and current_price:
                        t_open=stock_info['today_open']
                        p_close=stock_info['prev_close']

                        with conn.cursor() as c:
                            c.execute(
                                "UPDATE stocks SET today_open=%s,prev_close=%s WHERE symbol=%s",
                                (t_open,p_close,selected_stock.replace('.NS',''))
                            )
                            conn.commit()

                        st.success("Database Updated")

                if btn2.button("🗑️ Delete Stock"):
                    with conn.cursor() as c:
                        c.execute("DELETE FROM stocks WHERE symbol=%s",(selected_stock,))
                        conn.commit()
                    st.warning("Stock removed")
                    st.rerun()
            else:
                st.info("Your database is empty. Add a stock symbol to get started.")
