import streamlit as st
import pymysql
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objects as go 
import random
import re
import bcrypt
import yfinance as yf
from datetime import datetime
import pytz


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
def process_pending_orders(conn):
    c = conn.cursor()
    orders = pd.read_sql("""
        SELECT id, email, symbol, qty, action, order_type, trigger_price, price
        FROM transactions
        WHERE order_type != 'MARKET'
    """, conn)

    for _, o in orders.iterrows():
        # Get REAL market price for the pending order symbol
        current_price, _ = get_live_exchange_price(o["symbol"])
        if current_price is None: 
            continue

        execute = (
            (o["order_type"] == "LIMIT BUY" and current_price <= o["trigger_price"]) or
            (o["order_type"] == "LIMIT SELL" and current_price >= o["trigger_price"]) or
            (o["order_type"] == "STOP-LOSS" and current_price <= o["trigger_price"])
        )

        if execute:
            amount = current_price * o["qty"]

            if o["action"] == "BUY":
                c.execute("UPDATE users SET balance=balance-%s WHERE email=%s",
                          (amount, o["email"]))
            else:
                c.execute("UPDATE users SET balance=balance+%s WHERE email=%s",
                          (amount, o["email"]))

            c.execute("""
                UPDATE transactions
                SET order_type='MARKET', price=%s
                WHERE id=%s
            """, (current_price, o["id"]))

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
                    c.execute("SELECT username, password FROM users WHERE email=%s", (email,))
                    user = c.fetchone()

                    if user and check_password(password, user[1]):
                        with st.spinner("🔄 Synchronizing Market Data..."):
                            sync_all_stocks(conn) # <--- THIS UPDATES THE DB

                        st.session_state.update({
                            "logged_in": True, 
                            "user_email": email, 
                            "user_name": user[0]
                        })
                        conn.close()
                        st.rerun()
                    else:
                        st.error("Invalid credentials")

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
                    elif not phone.isdigit() or len(phone) < 10:
                        st.error("Please enter a valid 10-digit phone number.")
                    elif not account_no.isdigit():
                        st.error("Account number should only contain digits.")
                    elif not bank_name or not account_no or not ifsc_code:
                        st.error("Please fill all banking details.")
                    else:
                        try:
                            conn = get_connection()
                            c = conn.cursor()
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
    process_pending_orders(conn)
    c = conn.cursor()

    au=pd.read_sql("SELECT email from users",conn)

    if st.session_state["user_email"] != 'admin@quantify.com':

        st.sidebar.title(f"Hello, {st.session_state['user_name']}")
        menu_options = ["Dashboard", "Live Market & Trade", "Watchlist", "Portfolio", "History", "Add Funds"]

        # Initialize menu choice in session state if it doesn't exist
        if "menu_choice" not in st.session_state:
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
                st.info("No stocks available in the market. Please add some via 'Manage Stocks'.")
        # ==========================================
        # LIVE MARKET & TRADE
        # ==========================================
        elif menu == "Live Market & Trade":
            st.header("📈 Live Trading Terminal")

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

                st.metric(
                    "Live Exchange Price",
                    f"₹ {price}",
                    help=f"NSE • Last Updated: {time_stamp}"
                )

                # Metrics
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
                    # ... (Existing Order Logic - Copy your previous logic here or use the simplified version below) ...
                    c.execute("SELECT balance FROM users WHERE email=%s", (st.session_state["user_email"],))
                    balance = c.fetchone()[0]

                    if order_type == "MARKET":
                        if action == "BUY":
                            if balance >= total:
                                c.execute("UPDATE users SET balance=balance-%s WHERE email=%s", (total, st.session_state["user_email"]))
                                c.execute("INSERT INTO transactions (email, symbol, qty, price, action, order_type) VALUES (%s, %s, %s, %s, 'BUY', 'MARKET')", 
                                          (st.session_state["user_email"], stock, qty, price))
                                conn.commit()
                                st.success(f"Bought {qty} {stock}!")
                                st.rerun()
                            else:
                                st.error(f"Insufficient Funds. Need ₹{total-balance:,.2f} more.")

                        elif action == "SELL":
                            c.execute("SELECT COALESCE(SUM(CASE WHEN action='BUY' THEN qty ELSE -qty END),0) FROM transactions WHERE email=%s AND symbol=%s", 
                                      (st.session_state["user_email"], stock))
                            holding = c.fetchone()[0]
                            if holding >= qty:
                                c.execute("UPDATE users SET balance=balance+%s WHERE email=%s", (total, st.session_state["user_email"]))
                                c.execute("INSERT INTO transactions (email, symbol, qty, price, action, order_type) VALUES (%s, %s, %s, %s, 'SELL', 'MARKET')", 
                                          (st.session_state["user_email"], stock, qty, price))
                                conn.commit()
                                st.success(f"Sold {qty} {stock}!")
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
        # ADD FUNDS
        # ==========================================
        elif menu == "Add Funds":
            amt = st.number_input("Amount", min_value=1.0)
            if st.button("Add Money"):
                c.execute("UPDATE users SET balance=balance+%s WHERE email=%s",
                          (amt, st.session_state["user_email"]))
                conn.commit()
                st.success("Funds added")
                st.rerun()

    else:
        st.sidebar.title(f"Hello, Admin")
        menu_options = ["Leaderboard","Manage stocks"]

        if "menu_choice" not in st.session_state:
            st.session_state.menu_choice = "Leaderboard"

        # Determine the index of the current choice to keep the radio button in sync
        current_index = menu_options.index(st.session_state.menu_choice)

        # Update choice based on sidebar selection
        st.session_state.menu_choice = st.sidebar.radio("Navigation", menu_options, index=current_index)
        menu = st.session_state.menu_choice

        if st.sidebar.button("Logout"):
            st.session_state["logged_in"] = False
            st.rerun()
        # ==========================================
        # LEADERBOARD
        # ==========================================
        if menu == "Leaderboard":
            users = pd.read_sql("SELECT email, username, balance FROM users", conn)
            stocks = pd.read_sql("SELECT symbol, today_open FROM stocks", conn)
            tx = pd.read_sql("SELECT email, symbol, qty, action FROM transactions", conn)

            # Optimize: Fetch each stock price only once
            unique_stocks = tx['symbol'].unique()
            live_prices = {s: get_live_exchange_price(s)[0] for s in unique_stocks}

            leaderboard = []

            for _, u in users.iterrows():
                portfolio_value = u["balance"]
                user_tx = tx[tx["email"] == u["email"]]

                for sym in user_tx["symbol"].unique():
                    qty = user_tx[user_tx["symbol"] == sym].apply(
                        lambda x: x["qty"] if x["action"] == "BUY" else -x["qty"], axis=1
                    ).sum()

                    if qty > 0:
                        current_price = live_prices.get(sym)
                        if current_price:
                            portfolio_value += (current_price * qty)

                leaderboard.append({"User": u["username"], "Portfolio Value": portfolio_value})

            lb_df = pd.DataFrame(leaderboard).sort_values("Portfolio Value", ascending=False)
            lb_df["Rank"] = range(1, len(lb_df) + 1)

            st.dataframe(lb_df[["Rank", "User", "Portfolio Value"]], use_container_width=True)

        # ==========================================
        # MANAGE STOCKS (ADMIN/POWER USER)
        # ==========================================
        elif menu == "Manage stocks":
            st.header("🛠️ Real-Time Stock Management")
            st.write("Sync database values with live exchange data (including 10:00 AM capture).")

                # --- Section 1: Add New Stock ---
            with st.expander("➕ Add New Stock", expanded=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    new_ticker = st.text_input("Ticker Symbol", placeholder="e.g. AAPL, RELIANCE.NS, TSLA")
                with col2:
                    st.write("##") 
                    if st.button("Add/Update Stock", use_container_width=True):
                        if new_ticker:
                            with st.spinner(f"Pulling data for {new_ticker}..."):
                                # This calls the updated fetch function internally
                                new_ticker=new_ticker+'.NS'
                                success = add_stock_to_db(new_ticker.upper(), conn)
                                if success:

                                    st.success(f"Added/Updated {new_ticker.upper()} with today's open price.")
                                    st.rerun()
                                else:
                                    st.warning("Enter Appropriate Stock")
                        else:
                            st.warning("Please enter a ticker symbol.")

            st.divider()
            # Pull current stock list from your database
            db_stocks = pd.read_sql("SELECT symbol, company_name FROM stocks", conn)

            if not db_stocks.empty:
                stock_list = db_stocks['symbol'].tolist()
                selected_stock = st.selectbox("Select stock to synchronize:", stock_list)+'.NS'

                btn_col1, btn_col2, _ = st.columns([1, 1, 2])

                # --- REAL-TIME SYNC LOGIC ---
                if btn_col1.button("🔄 Sync & Preview Data", use_container_width=True):
                    with st.spinner(f"Requesting data for {selected_stock}..."):
                        # 1. Fetch Open and Previous Close using your helper
                        stock_info = fetch_stock_data(selected_stock)
                        
                        # 2. Fetch Live Price using your helper
                        current_price, last_time = get_live_exchange_price(selected_stock)
                
                        if not stock_info:
                            st.error("❌ Could not fetch historical data. Check the ticker symbol.")
                        elif current_price is None:
                            st.error("❌ Could not fetch live exchange price. Market might be closed.")
                        else:
                            t_open = stock_info['today_open']
                            p_close = stock_info['prev_close']
                
                            # 3. UPDATE DATABASE
                            try:
                                c.execute("""
                                    UPDATE stocks 
                                    SET today_open=%s, prev_close=%s 
                                    WHERE symbol=%s
                                """, (t_open, p_close, selected_stock.replace('.NS', ''))) # Sync symbol format
                                conn.commit()
                
                                # 4. DISPLAY RESULTS IN STREAMLIT
                                st.success(f"✅ Database Updated for {selected_stock}")
                
                                # Metrics Row
                                m1, m2, m3, m4 = st.columns(4)
                                m1.metric("Today's Open", f"₹ {t_open}")
                                m2.metric("Prev Close", f"₹ {p_close}")
                                m3.metric("Current Price", f"₹ {current_price}", help=f"Last traded: {last_time}")
                
                                change = t_open - p_close
                                pct = (change / p_close) * 100
                                m4.metric("Overnight Gap", f"{change:+.2f}", f"{pct:+.2f}%")
                
                            except Exception as e:
                                st.error(f"❌ Database Update Error: {str(e)}")

                # --- DELETE LOGIC ---
                if btn_col2.button("🗑️ Delete Stock", use_container_width=True):
                    c.execute("DELETE FROM stocks WHERE symbol=%s", (selected_stock,))
                    conn.commit()
                    st.warning(f"Removed {selected_stock} from the database.")
                    st.rerun()

            else:
                st.info("Your database is empty. Add a stock symbol to get started.")