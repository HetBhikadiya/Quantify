import streamlit as st
import pymysql
import pandas as pd
import matplotlib.pyplot as plt
import random
import re
import bcrypt
import yfinance as yf
from datetime import datetime

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
def get_current_price(base):
    return round(base * (1 + random.uniform(-0.03, 0.03)), 2)

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
        current_price = get_current_price(o["price"])

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

    st.sidebar.title(f"Hello, {st.session_state['user_name']}")

    # menu = st.sidebar.radio(
    #     "Navigation",
    #     ["Dashboard", "Live Market & Trade", "Watchlist", "Portfolio", "History", "Leaderboard", "Add Funds"]
    # )
    menu_options = ["Dashboard", "Live Market & Trade", "Watchlist", "Portfolio", "History", "Leaderboard", "Add Funds", "Manage Stocks"]
    
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
        stocks = pd.read_sql("SELECT symbol, today_open FROM stocks", conn)
        stock = st.selectbox("Select Stock", stocks["symbol"])

        base = stocks[stocks["symbol"] == stock]["today_open"].iloc[0]
        price = get_current_price(base)

        st.metric("Current Price", f"₹ {price}")

        qty = st.number_input("Quantity", min_value=1)
        action = st.radio("Action", ["BUY", "SELL"])
        order_type = st.selectbox("Order Type", ["MARKET", "LIMIT BUY", "LIMIT SELL", "STOP-LOSS"])

        trigger_price = None
        if order_type != "MARKET":
            trigger_price = st.number_input("Trigger Price", min_value=1.0)

        total = price * qty

        c.execute("SELECT balance FROM users WHERE email=%s", (st.session_state["user_email"],))
        balance = c.fetchone()[0]

        if st.button("Confirm Order"):
            if order_type == "MARKET":
                if action == "BUY":
                    if balance >= total:
                        # 1. Deduct balance from DB
                        c.execute("UPDATE users SET balance=balance-%s WHERE email=%s", 
                                 (total, st.session_state["user_email"]))
                        
                        # 2. Record Transaction
                        c.execute("""
                            INSERT INTO transactions (email, symbol, qty, price, action, order_type)
                            VALUES (%s, %s, %s, %s, 'BUY', 'MARKET')
                        """, (st.session_state["user_email"], stock, qty, price))
                             
                        conn.commit()
                        st.success(f"Market Buy Executed! ₹{total:,.2f} deducted.")
                        st.rerun()
                    else:
                        # --- INSUFFICIENT BALANCE LOGIC ---
                        st.error(f"Insufficient Balance! You need ₹{total - balance:,.2f} more.")
                        if st.button("Add Funds"):
                            st.session_state.menu_choice = "Add Funds"
                            st.rerun()

                elif action == "SELL":
                    c.execute("""
                        SELECT COALESCE(SUM(CASE WHEN action='BUY' THEN qty ELSE -qty END),0)
                        FROM transactions WHERE email=%s AND symbol=%s
                    """, (st.session_state["user_email"], stock))
                    holding = c.fetchone()[0]

                    if holding >= qty:
                        c.execute("UPDATE users SET balance=balance+%s WHERE email=%s",
                                  (total, st.session_state["user_email"]))
                        c.execute("""
                            INSERT INTO transactions (email,symbol,qty,price,action,order_type)
                            VALUES (%s,%s,%s,%s,'SELL','MARKET')
                        """, (st.session_state["user_email"], stock, qty, price))
                        conn.commit()
                        st.success("Market Sell Executed")
                        st.rerun()
                    else:
                        st.error("Not enough shares")
            else:
                c.execute("""
                    INSERT INTO transactions
                    (email,symbol,qty,price,action,order_type,trigger_price)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (st.session_state["user_email"], stock, qty, price, action, order_type, trigger_price))
                conn.commit()
                st.success("Conditional order placed")

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

        wl = pd.read_sql("""
            SELECT w.symbol, s.today_open
            FROM watchlist w JOIN stocks s ON w.symbol=s.symbol
            WHERE w.email=%s
        """, conn, params=(st.session_state["user_email"],))

        if not wl.empty:
            wl["Live Price"] = wl["today_open"].apply(get_current_price)
            st.dataframe(wl[["symbol", "Live Price"]], use_container_width=True)

    # ==========================================
    # PORTFOLIO
    # ==========================================
    elif menu == "Portfolio":
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
            stocks = pd.read_sql("SELECT symbol, today_open FROM stocks", conn)
            df = df.merge(stocks, on="symbol")
            df["Current Price"] = df["today_open"].apply(get_current_price)
            df["P/L"] = df["Current Price"] * df["qty"] - df["invested"]

            st.dataframe(df[["symbol", "qty", "Current Price", "P/L"]], use_container_width=True)

            fig, ax = plt.subplots()
            ax.bar(df["symbol"], df["P/L"])
            ax.axhline(0)
            ax.set_ylabel("Profit / Loss (₹)")
            st.pyplot(fig)
        else:
            st.info("No holdings")

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
    # LEADERBOARD
    # ==========================================
    elif menu == "Leaderboard":
        users = pd.read_sql("SELECT email, username, balance FROM users", conn)
        stocks = pd.read_sql("SELECT symbol, today_open FROM stocks", conn)
        tx = pd.read_sql("SELECT email, symbol, qty, action FROM transactions", conn)

        leaderboard = []

        for _, u in users.iterrows():
            portfolio_value = u["balance"]
            user_tx = tx[tx["email"] == u["email"]]

            for sym in user_tx["symbol"].unique():
                qty = user_tx[user_tx["symbol"] == sym].apply(
                    lambda x: x["qty"] if x["action"] == "BUY" else -x["qty"], axis=1
                ).sum()

                if qty > 0:
                    base = stocks[stocks["symbol"] == sym]["today_open"].iloc[0]
                    portfolio_value += get_current_price(base) * qty

            leaderboard.append({"User": u["username"], "Portfolio Value": portfolio_value})

        lb_df = pd.DataFrame(leaderboard).sort_values("Portfolio Value", ascending=False)
        lb_df["Rank"] = range(1, len(lb_df) + 1)

        st.dataframe(lb_df[["Rank", "User", "Portfolio Value"]], use_container_width=True)

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
# ==========================================
    # MANAGE STOCKS (ADMIN/POWER USER)
    # ==========================================
    # elif menu == "Manage Stocks":
    #     st.header("🛠️ Stock Inventory Management")
    #     st.write("Add symbols or sync prices with real-time market open/previous close data.")

        # --- Section 1: Add New Stock ---
        with st.expander("➕ Add New Stock", expanded=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                new_ticker = st.text_input("Ticker Symbol", placeholder="e.g. AAPL, RELIANCE.NS, TSLA")
                st.caption("Tip: Use '.NS' for Indian stocks (NSE).")
            with col2:
                st.write("##") 
                if st.button("Add/Update Stock", use_container_width=True):
                    if new_ticker:
                        with st.spinner(f"Pulling data for {new_ticker}..."):
                            # This calls the updated fetch function internally
                            success = add_stock_to_db(new_ticker.upper(), conn)
                            if success:
                                st.success(f"Added/Updated {new_ticker.upper()} with today's open price.")
                                st.rerun()
                    else:
                        st.warning("Please enter a ticker symbol.")

        st.divider()

    # ==========================================
    # MANAGE STOCKS (ADMIN/POWER USER)
    # ==========================================
    elif menu == "Manage Stocks":
        st.header("🛠️ Real-Time Stock Management")
        st.write("Sync database values with live exchange data (including 10:00 AM capture).")

            # --- Section 1: Add New Stock ---
        with st.expander("➕ Add New Stock", expanded=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                new_ticker = st.text_input("Ticker Symbol", placeholder="e.g. AAPL, RELIANCE.NS, TSLA")
                st.caption("Tip: Use '.NS' for Indian stocks (NSE).")
            with col2:
                st.write("##") 
                if st.button("Add/Update Stock", use_container_width=True):
                    if new_ticker:
                        with st.spinner(f"Pulling data for {new_ticker}..."):
                            # This calls the updated fetch function internally
                            success = add_stock_to_db(new_ticker.upper(), conn)
                            if success:
                                st.success(f"Added/Updated {new_ticker.upper()} with today's open price.")
                                st.rerun()
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
                    try:
                        ticker_obj = yf.Ticker(selected_stock)
                        
                        # 1. Fetch Daily History (for Open/Prev Close)
                        hist = ticker_obj.history(period="10d")
                        
                        if hist.empty or len(hist) < 2:
                            st.error("❌ Not enough data found. Check the ticker symbol.")
                        else:
                            # Identify standard prices
                            today_data = hist.iloc[-1]
                            prev_data = hist.iloc[-2]
                            t_open = round(float(today_data['Open']), 2)
                            p_close = round(float(prev_data['Close']), 2)
                            t_date_str = hist.index[-1].strftime('%Y-%m-%d')

                            # 2. FETCH 10:00 AM PRICE (Using 1-minute intervals)
                            # Start/End date for just 'Today'
                            start_dt = hist.index[-1].strftime('%Y-%m-%d')
                            end_dt = (hist.index[-1] + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                            
                            # Note: interval='1m' only works for data within the last 7 days
                            intra_hist = ticker_obj.history(start=start_dt, end=end_dt, interval="1m")
                            
                            price_10am = "N/A"
                            if not intra_hist.empty:
                                try:
                                    # Target 10:00:00 AM on today's trading date
                                    target_time = f"{t_date_str} 10:00:00"
                                    # Handle timezone (NSE is Asia/Kolkata)
                                    target_ts = pd.Timestamp(target_time).tz_localize(intra_hist.index.tz)
                                    
                                    # Find the index of the nearest minute to 10:00 AM
                                    closest_idx = intra_hist.index.get_indexer([target_ts], method='nearest')[0]
                                    price_10am_val = round(float(intra_hist.iloc[closest_idx]['Close']), 2)
                                    price_10am = f"₹ {price_10am_val}"
                                except Exception:
                                    price_10am = "Market Closed @ 10am"

                            # 3. UPDATE DATABASE
                            c.execute("""
                                UPDATE stocks 
                                SET today_open=%s, prev_close=%s 
                                WHERE symbol=%s
                            """, (t_open, p_close, selected_stock))
                            conn.commit()

                            # 4. DISPLAY RESULTS IN STREAMLIT
                            st.success(f"✅ Database Updated for {selected_stock}")
                            
                            # Row 1: Key Metrics
                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric("Today's Open", f"₹ {t_open}")
                            m2.metric("Prev Close", f"₹ {p_close}")
                            m3.metric("Price @ 10:00 AM", price_10am)
                            
                            change = t_open - p_close
                            pct = (change / p_close) * 100
                            m4.metric("Overnight Gap", f"{change:+.2f}", f"{pct:+.2f}%")
                                
                    except Exception as e:
                        st.error(f"❌ System Error: {str(e)}")

            # --- DELETE LOGIC ---
            if btn_col2.button("🗑️ Delete Stock", use_container_width=True):
                c.execute("DELETE FROM stocks WHERE symbol=%s", (selected_stock,))
                conn.commit()
                st.warning(f"Removed {selected_stock} from the database.")
                st.rerun()

        else:
            st.info("Your database is empty. Add a stock symbol to get started.")