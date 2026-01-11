from datetime import datetime
from flask import Flask, render_template, session, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-change-me"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///slowteabar.sqlite3"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class Beverage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Integer, nullable=False)  # store as integer rupiah
    active = db.Column(db.Boolean, default=True)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    total = db.Column(db.Integer, nullable=False, default=0)
    payment_method = db.Column(db.String(30), default="cash")  # cash/qris/etc

class SaleLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sale.id"), nullable=False)
    beverage_id = db.Column(db.Integer, db.ForeignKey("beverage.id"), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Integer, nullable=False)
    line_total = db.Column(db.Integer, nullable=False)

def get_cart():
    return session.setdefault("cart", {})  # {beverage_id: qty}

@app.route("/")
def pos():
    beverages = Beverage.query.filter_by(active=True).order_by(Beverage.name).all()
    cart = get_cart()

    # build cart display
    items = []
    total = 0
    for bev in beverages:
        qty = cart.get(str(bev.id), 0)
        if qty > 0:
            line_total = qty * bev.price
            total += line_total
            items.append({"id": bev.id, "name": bev.name, "qty": qty, "price": bev.price, "line_total": line_total})

    return render_template("pos.html", beverages=beverages, items=items, total=total)

@app.post("/cart/add/<int:bev_id>")
def cart_add(bev_id):
    cart = get_cart()
    key = str(bev_id)
    cart[key] = cart.get(key, 0) + 1
    session["cart"] = cart
    return redirect(url_for("pos"))

@app.post("/cart/inc/<int:bev_id>")
def cart_inc(bev_id):
    return cart_add(bev_id)

@app.post("/cart/dec/<int:bev_id>")
def cart_dec(bev_id):
    cart = get_cart()
    key = str(bev_id)
    cart[key] = max(0, cart.get(key, 0) - 1)
    if cart[key] == 0:
        cart.pop(key, None)
    session["cart"] = cart
    return redirect(url_for("pos"))

@app.post("/checkout")
def checkout():
    cart = get_cart()
    if not cart:
        return redirect(url_for("pos"))

    beverages = {str(b.id): b for b in Beverage.query.all()}
    sale = Sale(payment_method=request.form.get("payment_method", "cash"), total=0)
    db.session.add(sale)
    db.session.flush()  # get sale.id

    total = 0
    for bev_id, qty in cart.items():
        bev = beverages.get(bev_id)
        if not bev or qty <= 0:
            continue
        line_total = qty * bev.price
        total += line_total
        db.session.add(SaleLine(
            sale_id=sale.id,
            beverage_id=bev.id,
            qty=qty,
            unit_price=bev.price,
            line_total=line_total
        ))

    sale.total = total
    db.session.commit()
    session["cart"] = {}
    return redirect(url_for("pos"))

@app.get("/init")
def init_db():
    db.create_all()
    # seed a few beverages if empty
    if Beverage.query.count() == 0:
        db.session.add_all([
            Beverage(name="Slow Milk Tea", price=22000),
            Beverage(name="Jasmine Lemon Tea", price=18000),
            Beverage(name="Oolong Peach", price=25000),
        ])
        db.session.commit()
    return "DB initialized. Go to /"

if __name__ == "__main__":
    app.run(debug=True)
