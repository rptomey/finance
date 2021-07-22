import os
import re

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    # Get contents of user's portfolio
    stocks = db.execute("SELECT stock_symbol, stock_name, SUM(quantity) AS total_quantity FROM transactions WHERE user_id = ? GROUP BY stock_symbol ORDER BY total_quantity DESC, stock_name ASC", session["user_id"])
    # Set variable for summing total current portfolio value
    value = 0.00

    if len(stocks) > 0:
        # Get current value of each stock, then add current price and a calculation of value to stocks
        for stock in stocks:
            symbol = stock["stock_symbol"]
            result = lookup(symbol)
            stock["price"] = result["price"]
            stock["value"] = result["price"] * stock["total_quantity"]
            # Also add to portfolio value
            value += (result["price"] * stock["total_quantity"])

        # Get usd formatted current cash balance
        available_cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
        balance = available_cash

        # Format value as usd, including cash balance
        value = value + available_cash

        # Render the template
        return render_template("index.html", balance=balance, value=value, stocks=stocks)

    # Get usd formatted current cash balance
    available_cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
    balance = available_cash

    return render_template("index.html", balance=balance, value=balance)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        # Get the stock symbol and quantity from the form submit
        symbol = request.form.get("symbol")
        quantity = request.form.get("shares")

        # Handle missing symbol
        if not symbol:
            return apology("must include stock symbol", 403)

        # Handle missing quantity
        if not quantity:
            return apology("must include quantity", 403)

        # Handle unexpected quantities
        if re.search("\D", quantity) is not None:
            return apology("invalid quantity", 400)

        # Convert quantity to int
        quantity = int(quantity)

        # Execute API call to look up stock
        result = lookup(symbol)

        # Handle stock not found
        if result == None:
            return apology("symbol not found", 400)

        # Get current stock price and name and calculate order total
        stock_price = result["price"]
        stock_name = result["name"]
        order_total = quantity * stock_price

        # Get user's current cash reserves
        available_cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]

        # Handle insufficient funds
        if order_total > available_cash:
            return apology("insufficient funds", 403)

        # Log transaction and update cash reserves
        db.execute("INSERT INTO transactions (user_id, stock_symbol, stock_name, price, quantity, amount) VALUES (?, ?, ?, ?, ?, ?)", session["user_id"], symbol, stock_name, stock_price, quantity, order_total)
        new_cash_balance = available_cash - order_total
        db.execute("UPDATE users SET cash = ? WHERE id = ?", new_cash_balance, session["user_id"])

        # Send user back to index page
        return redirect("/")

    if request.method == "GET":
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    # Get user's transaction history
    transactions = db.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY date ASC", session["user_id"])

    # Handle no transactions
    if len(transactions) == 0:
        render_template("history.html")

    # Modify transactions to match history table columns
    for transaction in transactions:
        transaction["type"] = "BUY" if transaction["quantity"] > 0 else "SELL"
        if transaction["amount"] < 0:
            transaction["amount"] = "(" + usd(abs(transaction["amount"])) + ")"
        else:
            transaction["amount"] = usd(transaction["amount"])
        transaction["quantity"] = abs(transaction["quantity"])

    # Render template with transaction history
    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        # Get the value from the form submit
        symbol = request.form.get("symbol")

        # Handle missing symbol
        if not symbol:
            return apology("must include symbol", 400)

        # Execute API call to look up stock
        result = lookup(symbol)

        # Handle stock not found
        if result == None:
            return apology("symbol not found", 400)

        # Render quote template with results
        result["price"] = usd(result["price"])
        return render_template("quote.html", result=result)

    if request.method == "GET":
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        # Get the values from the form submit
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        # Handle missing username
        if not username:
            return apology("must include username", 400)

        # Handle missing password or confirmation
        if not password:
            return apology("must include password", 400)

        # Handle unsecure password
        if len(password) < 8 or re.search("[A-Z]", password) is None or re.search("[0-9]", password) is None or re.search("[!@#\$%\^&\*-_]", password) is None:
            return apology("review password requirements", 400)

        # Handle mismatched password and confirmation
        if password != confirmation:
            return apology("password must match confirmation", 400)

        # Handle already registered user
        # Moved to after the missing checks so that we don't bother querying the database if we don't need to.
        rows = db.execute("SELECT * FROM users WHERE username = ?", username)
        if len(rows) != 0:
            return apology("user already exists", 400)

        # Insert the new user
        hashed_password = generate_password_hash(password)
        db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", username, hashed_password)

        # Send to login page
        return redirect("/")

    if request.method == "GET":
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":
        # Get the stock symbol and quantity from the form submit
        symbol = request.form.get("symbol")
        quantity = request.form.get("shares")

        # Handle missing symbol
        if not symbol:
            return apology("must include stock symbol", 403)

        # Handle missing quantity
        if not quantity:
            return apology("must include quantity", 403)

        # Convert quantity to int
        quantity = int(quantity)

        # Check portfolio for stock quantity
        stocks = db.execute("SELECT SUM(quantity) AS total_quantity FROM transactions WHERE stock_symbol = ? AND user_id = ? GROUP BY stock_symbol", symbol, session["user_id"])

        # Handle if stock does not exist in portfolio
        if len(stocks) == 0 or stocks[0]["total_quantity"] < 1:
            return apology("you do not hold this stock", 403)

        # Handle if quantity exceeds stock holdings
        if quantity > stocks[0]["total_quantity"]:
            return apology("quantity exceeds your holdings", 400)

        # Execute API call to look up stock
        result = lookup(symbol)

        # Get current stock price and name and calculate order total
        stock_price = result["price"]
        stock_name = result["name"]
        order_total = quantity * stock_price

        # Get user's current cash reserves
        available_cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]

        # Log transaction and update cash reserves
        negative_quantity = 0 - quantity
        negative_total = 0 - order_total
        db.execute("INSERT INTO transactions (user_id, stock_symbol, stock_name, price, quantity, amount) VALUES (?, ?, ?, ?, ?, ?)", session["user_id"], symbol, stock_name, stock_price, negative_quantity, negative_total)
        new_cash_balance = available_cash + order_total
        db.execute("UPDATE users SET cash = ? WHERE id = ?", new_cash_balance, session["user_id"])

        # Send user back to index page
        return redirect("/")

    if request.method == "GET":
        stocks = db.execute("SELECT stock_symbol FROM (SELECT stock_symbol, SUM(quantity) AS total_quantity FROM transactions WHERE user_id = ? GROUP BY stock_symbol ORDER BY stock_symbol ASC) WHERE total_quantity > 0", session["user_id"])
        return render_template("sell.html", stocks=stocks)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
