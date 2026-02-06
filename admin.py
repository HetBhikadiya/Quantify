import streamlit as st
import pymysql
import pandas as pd
import yfinance as yf
from datetime import datetime
import random

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
# ADMIN HELPERS (Shared with main app)
# ==========================================
def get_current_price(base):
    return round(base * (1 + random.uniform(-0.03, 0.03)), 2)

def fetch_stock_data(ticker):
    try:
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
        
        info = stock.info
        return {
            'symbol': ticker.replace('.NS', '').upper(),
            'company_name': info.get('longName', ticker),
            'category': info.get('sector', 'N/A'),
            'prev_close': prev_close,
            'today_open': today_open
        }
    except:
        return None

def add_stock_to_db(ticker, conn):
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
                stock_data['symbol'], stock_data['company_name'], stock_data['category'],
                stock_data['prev_close'], stock_data['today_open'],
                stock_data['company_name'], stock_data['category'],
                stock_data['prev_close'], stock_data['today_open']
            ))
            conn.commit()
            return True
        except Exception as e:
            st.error(f"Database error: {str(e)}")
            return False
    return False

# ==========================================
# ADMIN PANEL UI
# ==========================================
st.set_page_config(page_title="Quantify Admin", page_icon="🔐", layout="wide")

st.title("🔐 Quantify Administrative Panel")

conn = get_connection()
c = conn.cursor()

admin_menu = st.sidebar.radio("Admin Navigation", ["Leaderboard", "Manage Stocks"])

# ==========================================
# LEADERBOARD SECTION
# ==========================================
if admin_menu == "Leaderboard":
    st.header("🏆 Global User Leaderboard")
    st.write("Current ranking of all users based on Wallet Balance + Portfolio Value.")
    
    with st.spinner("Calculating global rankings..."):
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
                    stock_row = stocks[stocks["symbol"] == sym]
                    if not stock_row.empty:
                        base = stock_row["today_open"].iloc[0]
                        # Using simulated current price for leaderboard consistency
                        portfolio_value += get_current_price(base) * qty

            leaderboard.append({"User": u["username"], "Email": u["email"], "Portfolio Value": portfolio_value})

        lb_df = pd.DataFrame(leaderboard).sort_values("Portfolio Value", ascending=False)
        lb_df["Rank"] = range(1, len(lb_df) + 1)

        st.dataframe(lb_df[["Rank", "User", "Email", "Portfolio Value"]], use_container_width=True, hide_index=True)

# ==========================================
# MANAGE STOCKS SECTION
# ==========================================
elif admin_menu == "Manage Stocks":
    st.header("🛠️ Market Management")
    
    # Add New Stock
    with st.expander("➕ Add New Stock to Market", expanded=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            new_ticker = st.text_input("Ticker Symbol", placeholder="e.g. RELIANCE, TCS, INFOSYS")
        with col2:
            st.write("##") 
            if st.button("Add/Update Stock", use_container_width=True):
                if new_ticker:
                    with st.spinner(f"Pulling data for {new_ticker}..."):
                        # Ensure .NS for Indian stocks if not provided
                        formatted_ticker = new_ticker if "." in new_ticker else f"{new_ticker}.NS"
                        success = add_stock_to_db(formatted_ticker.upper(), conn)
                        if success:
                            st.success(f"Successfully added/updated {new_ticker.upper()}")
                            st.rerun()
                        else:
                            st.error("Could not fetch data. Please check the ticker symbol.")

    st.divider()

    # Existing Stocks Sync/Delete
    db_stocks = pd.read_sql("SELECT symbol, company_name FROM stocks", conn)
    
    if not db_stocks.empty:
        stock_list = db_stocks['symbol'].tolist()
        selected_stock = st.selectbox("Select stock to manage:", stock_list)
        formatted_selected = f"{selected_stock}.NS"

        btn_col1, btn_col2, _ = st.columns([1, 1, 2])
        
        if btn_col1.button("🔄 Sync Live Data", use_container_width=True):
            with st.spinner(f"Syncing {selected_stock}..."):
                ticker_obj = yf.Ticker(formatted_selected)
                hist = ticker_obj.history(period="5d")
                
                if not hist.empty and len(hist) >= 2:
                    t_open = round(float(hist['Open'].iloc[-1]), 2)
                    p_close = round(float(hist['Close'].iloc[-2]), 2)
                    
                    c.execute("""
                        UPDATE stocks SET today_open=%s, prev_close=%s WHERE symbol=%s
                    """, (t_open, p_close, selected_stock))
                    conn.commit()
                    st.success(f"Updated {selected_stock}: Open ₹{t_open}, Prev Close ₹{p_close}")
                else:
                    st.error("Failed to fetch history.")

        if btn_col2.button("🗑️ Remove from Market", use_container_width=True):
            c.execute("DELETE FROM stocks WHERE symbol=%s", (selected_stock,))
            conn.commit()
            st.warning(f"Removed {selected_stock} from the active market list.")
            st.rerun()
    else:
        st.info("No stocks currently in database.")

conn.close()