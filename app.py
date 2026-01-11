import os
from datetime import datetime

from flask import Flask, render_template, session, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy

from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")

# DB (SQLite file). In Codespaces/local, this will be created automatically.
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///slowteabar.sqlite3"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Simple admin password (set it in Codespaces env var ADMIN_PASSWORD)
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "change-this-password")

db = SQLAlchemy(app)

# ----------------------------
# Models
# ----------------------------
class Beverage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)

    # Two sizes
    price_regular = db.Column(db.Integer, nullable=False, default=0)
    price_large = db.Column(db.Integer, nullable=False, default=0)

    active = db.Column(db.Boolean, default=True)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    total = db.Column(db.Integer, nullable=False, default=0)
    payment_method = db.Column(db.String(30), default="cash")  # cash/qris/transfer

class SaleLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=False)
    beverage_id = db.Column(db.Integer, db.ForeignKey("beverage.id"), nullable=False)

    qty = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Integer, nullable=False)
    line_total = db.Column(db.Integer, nullable=False)

    # Options captured per line item
    size = db.Column(db.String(10), nullable=False, default="regular")  # regular/large
    sugar_level = db.Column(db.String(10), nullable=False, default="default")  # less/default/more
    ice_level = db.Column(db.String(10), nullable=False, default="default")  # less/default/more


# ----------------------------
# Helpers
# ----------------------------
def cart_get():
    """
    Cart stored in session as dict:
      { "bevId|size|sugar|ice": qty }
    """
    return session.setdefault("cart", {})

def cart_key(bev_id: int, size: str, sugar: str, ice: str) -> str:
    return f"{bev_id}|{size}|{sugar}|{ice}"

def parse_cart_key(key: str):
    bev_id, size, sugar, ice = key.split("|")
    return int(bev_id), size, sugar, ice

def price_for(bev: Beverage, size: str) -> int:
    return bev.price_large if size == "large" else bev.price_regular


# ----------------------------
# POS Routes
# ----------------------------
@app.get("/")
def pos():
    beverages = Beverage.query.filter_by(active=True).order_by(Beverage.name).all()
    bev_map = {b.id: b for b in beverages}

    # Defaults for POS selectors
    selected_size = request.args.get("size", "regular")
    selected_sugar = request.args.get("sugar", "default")
    selected_ice = request.args.get("ice", "default")

    cart = cart_get()
    items = []
    total = 0

    # Build cart display
    # NOTE: cart might contain items for inactive beverages; handle safely
    all_bevs = {b.id: b for b in Beverage.query.all()}

    for key, qty in cart.items():
        if qty <= 0:
            continue
        bev_id, size, sugar, ice = parse_cart_key(key)
        bev = all_bevs.get(bev_id)
        if not bev:
            continue

        unit_price = price_for(bev, size)
        line_total = unit_price * qty
        total += line_total

        items.append({
            "key": key,
            "name": bev.name,
            "qty": qty,
            "size": size,
            "sugar": sugar,
            "ice": ice,
            "unit_price": unit_price,
            "line_total": line_total
        })

    # Sort cart items so it feels tidy
    items.sort(key=lambda x: (x["name"], x["size"], x["sugar"], x["ice"]))

    return render_template(
        "pos.html",
        beverages=beverages,
        items=items,
        total=total,
        selected_size=selected_size,
        selected_sugar=selected_sugar,
        selected_ice=selected_ice
    )

@app.post("/cart/add")
def cart_add():
    bev_id = int(request.form["bev_id"])
    size = request.form.get("size", "regular")
    sugar = request.form.get("sugar", "default")
    ice = request.form.get("ice", "default")

    # Normalize
    if size not in ("regular", "large"):
        size = "regular"
    if sugar not in ("less", "default", "more"):
        sugar = "default"
    if ice not in ("less", "default", "more"):
        ice = "default"

    key = cart_key(bev_id, size, sugar, ice)
    cart = cart_get()
    cart[key] = cart.get(key, 0) + 1
    session["cart"] = cart

    # Stay on POS and keep selector values
    return redirect(url_for("pos", size=size, sugar=sugar, ice=ice))

@app.post("/cart/inc")
def cart_inc():
    key = request.form["key"]
    cart = cart_get()
    cart[key] = cart.get(key, 0) + 1
    session["cart"] = cart
    return redirect(url_for("pos"))

@app.post("/cart/dec")
def cart_dec():
    key = request.form["key"]
    cart = cart_get()
    cart[key] = max(0, cart.get(key, 0) - 1)
    if cart[key] == 0:
        cart.pop(key, None)
    session["cart"] = cart
    return redirect(url_for("pos"))

@app.post("/cart/clear")
def cart_clear():
    session["cart"] = {}
    return redirect(url_for("pos"))

@app.post("/checkout")
def checkout():
    cart = cart_get()
    if not cart:
        return redirect(url_for("pos"))

    bevs = {b.id: b for b in Beverage.query.all()}

    sale = Sale(payment_method=request.form.get("payment_method", "cash"), total=0)
    db.session.add(sale)
    db.session.flush()

    total = 0
    for key, qty in cart.items():
        if qty <= 0:
            continue
        bev_id, size, sugar, ice = parse_cart_key(key)
        bev = bevs.get(bev_id)
        if not bev:
            continue

        unit_price = price_for(bev, size)
        line_total = unit_price * qty
        total += line_total

        db.session.add(SaleLine(
            sale_id=sale.id,
            beverage_id=bev.id,
            qty=qty,
            unit_price=unit_price,
            line_total=line_total,
            size=size,
            sugar_level=sugar,
            ice_level=ice
        ))

    sale.total = total
    db.session.commit()
    session["cart"] = {}
    return redirect(url_for("pos"))


# ----------------------------
# Init DB (one time)
# ----------------------------
@app.get("/init")
def init_db():
    db.create_all()

    # Seed beverages (only if empty)
    if Beverage.query.count() == 0:
        db.session.add_all([
            Beverage(name="Slow Milk Tea", price_regular=22000, price_large=26000, active=True),
            Beverage(name="Jasmine Lemon Tea", price_regular=18000, price_large=22000, active=True),
            Beverage(name="Oolong Peach", price_regular=25000, price_large=29000, active=True),
        ])
        db.session.commit()

    return "DB initialized. Go to / (and Admin at /admin)"


# ----------------------------
# Admin Panel (Flask-Admin) + simple login
# ----------------------------
class SecureAdminIndexView(AdminIndexView):
    @expose("/")
    def index(self):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return super().index()

class SecureModelView(ModelView):
    def is_accessible(self):
        return session.get("is_admin", False)

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("admin_login", next=request.url))

class ReadOnlyModelView(SecureModelView):
    can_create = False
    can_edit = False
    can_delete = False

admin = Admin(app, name="Slow Tea Bar Admin", template_mode="bootstrap4", index_view=SecureAdminIndexView())

# Editable: Beverage
admin.add_view(SecureModelView(Beverage, db.session, category="Master Data"))

# Read-only: sales history (optional but nice)
admin.add_view(ReadOnlyModelView(Sale, db.session, category="Sales"))
admin.add_view(ReadOnlyModelView(SaleLine, db.session, category="Sales"))

@app.get("/admin/login")
def admin_login():
    return render_template("admin_login.html")

@app.post("/admin/login")
def admin_login_post():
    pw = request.form.get("password", "")
    if pw == app.config["ADMIN_PASSWORD"]:
        session["is_admin"] = True
        return redirect("/admin")
    flash("Wrong password.")
    return redirect(url_for("admin_login"))

@app.get("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("pos"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
