import pymysql

print("1. Python is running.")

try:
    # Connect to XAMPP
    print("2. Connecting to XAMPP (localhost:3306)...")
    connection = pymysql.connect(
        host='localhost',
        user='root',
        password='',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    print("3. CONNECTION SUCCESSFUL!")

    try:
        with connection.cursor() as cursor:
            # Create Database
            print("4. Creating Database 'trading_app'...")
            cursor.execute("CREATE DATABASE IF NOT EXISTS trading_app")
            cursor.execute("USE trading_app")
            
            # --- UPDATED USERS TABLE ---
            print("5. Configuring 'users' table with role and KYC columns...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    email VARCHAR(255) PRIMARY KEY,
                    username VARCHAR(255),
                    password VARCHAR(255),
                    aadhar VARCHAR(12) UNIQUE,
                    pan VARCHAR(10) UNIQUE,
                    phone VARCHAR(15) UNIQUE,
                    gender VARCHAR(20),
                    dob DATE,
                    bank_name VARCHAR(255),
                    account_no VARCHAR(50) UNIQUE,
                    ifsc_code VARCHAR(20),
                    balance DOUBLE DEFAULT 0.0,
                    status VARCHAR(20) DEFAULT 'ACTIVE',
                )
            """)

            # Create Stocks Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stocks (
                    symbol VARCHAR(50) PRIMARY KEY,
                    company_name VARCHAR(255),
                    category VARCHAR(100),
                    prev_close DOUBLE,
                    today_open DOUBLE
                )
            """)

            # Create Transactions Table
            


            

            # Create Watchlist Table (Needed for your app logic)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    email VARCHAR(255),
                    symbol VARCHAR(50),
                    UNIQUE KEY (email, symbol)
                )
            """)
            
            print("6. All Tables Created Successfully.") 

        print("--- SETUP COMPLETE ---")

    finally:
        connection.close()

except Exception as e:
    print(f"\n❌ ERROR: {e}")