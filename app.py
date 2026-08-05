from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import BytesIO

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, inspect, or_, text
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

ROLE_ADMIN = "admin"
ROLE_CASHIER = "cashier"
VALID_ROLES = {ROLE_ADMIN, ROLE_CASHIER}
VALID_TAX_TYPES = {"GST", "VAT"}
DEFAULT_SETTINGS = {
    "shop_name": "Inventory Manager",
    "shop_address": "Main Street",
    "shop_phone": "0000000000",
    "currency_symbol": "$",
    "currency_code": "USD",
    "receipt_width_mm": "80",
}


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=lambda: utc_now(), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: utc_now(),
        onupdate=lambda: utc_now(),
        nullable=False,
    )


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(60), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_CASHIER)

    def set_password(self, plain_password: str) -> None:
        self.password_hash = generate_password_hash(plain_password)

    def check_password(self, plain_password: str) -> bool:
        return check_password_hash(self.password_hash, plain_password)


class Product(TimestampMixin, db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    category = db.Column(db.String(80), nullable=False, default="General")
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    stock_quantity = db.Column(db.Integer, nullable=False, default=0)
    reorder_level = db.Column(db.Integer, nullable=False, default=5)

    invoice_items = db.relationship("InvoiceItem", back_populates="product")
    stock_movements = db.relationship("StockMovement", back_populates="product")
    purchase_order_items = db.relationship("PurchaseOrderItem", back_populates="product")


class Supplier(TimestampMixin, db.Model):
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    tax_registration = db.Column(db.String(80), nullable=True)

    purchase_orders = db.relationship("PurchaseOrder", back_populates="supplier")


class AppSetting(TimestampMixin, db.Model):
    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(80), nullable=False, unique=True, index=True)
    setting_value = db.Column(db.String(255), nullable=False)


class Customer(TimestampMixin, db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    customer_code = db.Column(db.String(40), nullable=True, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(30), nullable=True)

    invoices = db.relationship("Invoice", back_populates="customer")


class Invoice(TimestampMixin, db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="PAID")
    payment_method = db.Column(db.String(30), nullable=False, default="cash")
    tax_type = db.Column(db.String(10), nullable=False, default="GST")
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    discount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    grand_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    customer = db.relationship("Customer", back_populates="invoices")
    items = db.relationship(
        "InvoiceItem", back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)

    invoice = db.relationship("Invoice", back_populates="items")
    product = db.relationship("Product", back_populates="invoice_items")


class InvoiceSequence(db.Model):
    __tablename__ = "invoice_sequences"

    id = db.Column(db.Integer, primary_key=True)
    tax_type = db.Column(db.String(10), nullable=False)
    financial_year = db.Column(db.String(10), nullable=False)
    last_number = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint("tax_type", "financial_year", name="uq_tax_year_sequence"),
    )


class PurchaseOrder(TimestampMixin, db.Model):
    __tablename__ = "purchase_orders"

    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False)
    expected_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="DRAFT")
    stock_applied = db.Column(db.Boolean, nullable=False, default=False)
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    grand_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    notes = db.Column(db.String(255), nullable=True)

    supplier = db.relationship("Supplier", back_populates="purchase_orders")
    items = db.relationship(
        "PurchaseOrderItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
    )


class PurchaseOrderItem(db.Model):
    __tablename__ = "purchase_order_items"

    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(
        db.Integer, db.ForeignKey("purchase_orders.id"), nullable=False
    )
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)

    purchase_order = db.relationship("PurchaseOrder", back_populates="items")
    product = db.relationship("Product", back_populates="purchase_order_items")


class StockMovement(TimestampMixin, db.Model):
    __tablename__ = "stock_movements"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    movement_type = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    notes = db.Column(db.String(255), nullable=True)

    product = db.relationship("Product", back_populates="stock_movements")


def to_decimal(raw_value: str, default: str = "0") -> Decimal:
    value = (raw_value or "").strip() or default
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def to_int(raw_value: str, default: int = 0) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def format_currency(value: Decimal | int | float | None) -> str:
    if value is None:
        value = 0
    return f"{Decimal(value):,.2f}"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def financial_year_label(for_date: date | None = None) -> str:
    current_date = for_date or date.today()
    start_year = current_date.year if current_date.month >= 4 else current_date.year - 1
    end_year_short = str(start_year + 1)[-2:]
    return f"{start_year}-{end_year_short}"


def generate_invoice_number(tax_type: str) -> str:
    normalized_tax = tax_type.upper()
    if normalized_tax not in VALID_TAX_TYPES:
        normalized_tax = "GST"

    fy = financial_year_label()
    sequence = InvoiceSequence.query.filter_by(
        tax_type=normalized_tax, financial_year=fy
    ).first()
    if not sequence:
        sequence = InvoiceSequence(tax_type=normalized_tax, financial_year=fy, last_number=0)
        db.session.add(sequence)
        db.session.flush()

    sequence.last_number += 1
    db.session.flush()
    return f"{normalized_tax}/{fy}/{sequence.last_number:05d}"


def generate_purchase_order_number() -> str:
    next_id = (db.session.query(func.max(PurchaseOrder.id)).scalar() or 0) + 1
    return f"PO-{utc_now():%Y%m%d}-{next_id:04d}"


def get_setting_value(setting_key: str, default_value: str = "") -> str:
    row = AppSetting.query.filter_by(setting_key=setting_key).first()
    if row:
        return row.setting_value
    return default_value


def set_setting_value(setting_key: str, setting_value: str) -> None:
    row = AppSetting.query.filter_by(setting_key=setting_key).first()
    if not row:
        row = AppSetting(setting_key=setting_key, setting_value=setting_value)
        db.session.add(row)
    else:
        row.setting_value = setting_value


def get_all_settings() -> dict[str, str]:
    settings = dict(DEFAULT_SETTINGS)
    rows = AppSetting.query.all()
    for row in rows:
        settings[row.setting_key] = row.setting_value
    return settings


def get_current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not getattr(g, "current_user", None):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*allowed_roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if not user:
                return redirect(url_for("login", next=request.path))
            if user.role not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def ensure_legacy_schema() -> None:
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())

    if "invoices" in tables:
        invoice_columns = {column["name"] for column in inspector.get_columns("invoices")}
        if "tax_type" not in invoice_columns:
            db.session.execute(
                text(
                    "ALTER TABLE invoices ADD COLUMN tax_type VARCHAR(10) NOT NULL DEFAULT 'GST'"
                )
            )

    if "purchase_orders" in tables:
        po_columns = {column["name"] for column in inspector.get_columns("purchase_orders")}
        if "stock_applied" not in po_columns:
            db.session.execute(
                text(
                    "ALTER TABLE purchase_orders ADD COLUMN stock_applied BOOLEAN NOT NULL DEFAULT 0"
                )
            )

    if "customers" in tables:
        customer_columns = {column["name"] for column in inspector.get_columns("customers")}
        if "customer_code" not in customer_columns:
            db.session.execute(text("ALTER TABLE customers ADD COLUMN customer_code VARCHAR(40)"))
        db.session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_customers_customer_code ON customers(customer_code)"
            )
        )

    db.session.commit()


def seed_default_users() -> None:
    if User.query.count() > 0:
        return

    admin = User(full_name="System Administrator", username="admin", role=ROLE_ADMIN)
    admin.set_password("admin123")
    cashier = User(full_name="Default Cashier", username="cashier", role=ROLE_CASHIER)
    cashier.set_password("cashier123")
    db.session.add_all([admin, cashier])
    db.session.commit()


def seed_default_settings() -> None:
    for key, value in DEFAULT_SETTINGS.items():
        if not AppSetting.query.filter_by(setting_key=key).first():
            db.session.add(AppSetting(setting_key=key, setting_value=value))
    db.session.commit()


def apply_purchase_order_stock(po: PurchaseOrder) -> None:
    for item in po.items:
        item.product.stock_quantity += item.quantity
        db.session.add(
            StockMovement(
                product=item.product,
                movement_type="IN",
                quantity=item.quantity,
                notes=f"Purchased via {po.po_number}",
            )
        )
    po.stock_applied = True


def invoice_pdf_content(invoice: Invoice, settings: dict[str, str]) -> BytesIO:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    shop_name = settings.get("shop_name", "Inventory Manager")
    shop_address = settings.get("shop_address", "-")
    shop_phone = settings.get("shop_phone", "-")
    currency_symbol = settings.get("currency_symbol", "$")

    y = height - 50
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, f"{shop_name} - Tax Invoice")
    y -= 25

    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Address: {shop_address}")
    y -= 14
    pdf.drawString(40, y, f"Phone: {shop_phone}")
    y -= 14
    pdf.drawString(40, y, f"Invoice Number: {invoice.invoice_number}")
    pdf.drawString(320, y, f"Date: {invoice.created_at.strftime('%Y-%m-%d %H:%M')}")
    y -= 16
    pdf.drawString(40, y, f"Tax Type: {invoice.tax_type}")
    pdf.drawString(320, y, f"Payment: {invoice.payment_method.upper()}")
    y -= 16
    pdf.drawString(40, y, f"Status: {invoice.status}")
    y -= 26

    customer_name = invoice.customer.name if invoice.customer else "Walk-in Customer"
    customer_code = invoice.customer.customer_code if invoice.customer else "-"
    customer_email = invoice.customer.email if invoice.customer else "-"
    customer_phone = invoice.customer.phone if invoice.customer else "-"
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(40, y, "Bill To")
    y -= 16
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Name: {customer_name}")
    y -= 14
    pdf.drawString(40, y, f"Customer ID: {customer_code or '-'}")
    y -= 14
    pdf.drawString(40, y, f"Email: {customer_email or '-'}")
    y -= 14
    pdf.drawString(40, y, f"Phone: {customer_phone or '-'}")
    y -= 24

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, "Product")
    pdf.drawString(300, y, "Qty")
    pdf.drawString(360, y, "Unit")
    pdf.drawString(450, y, "Line Total")
    y -= 12
    pdf.line(40, y, width - 40, y)
    y -= 14

    pdf.setFont("Helvetica", 10)
    for item in invoice.items:
        if y < 120:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, item.product.name[:40])
        pdf.drawString(300, y, str(item.quantity))
        pdf.drawString(360, y, f"{currency_symbol} {Decimal(item.unit_price):,.2f}")
        pdf.drawRightString(width - 40, y, f"{currency_symbol} {Decimal(item.line_total):,.2f}")
        y -= 14

    y -= 16
    pdf.line(300, y, width - 40, y)
    y -= 16
    pdf.drawString(320, y, "Subtotal:")
    pdf.drawRightString(width - 40, y, f"{currency_symbol} {Decimal(invoice.subtotal):,.2f}")
    y -= 14
    pdf.drawString(320, y, f"{invoice.tax_type} Tax ({invoice.tax_rate}%):")
    pdf.drawRightString(width - 40, y, f"{currency_symbol} {Decimal(invoice.tax_amount):,.2f}")
    y -= 14
    pdf.drawString(320, y, "Discount:")
    pdf.drawRightString(width - 40, y, f"{currency_symbol} {Decimal(invoice.discount):,.2f}")
    y -= 16
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(320, y, "Grand Total:")
    pdf.drawRightString(
        width - 40, y, f"{currency_symbol} {Decimal(invoice.grand_total):,.2f}"
    )

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="inventory-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///inventory.db",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    app.jinja_env.filters["money"] = format_currency

    with app.app_context():
        db.create_all()
        ensure_legacy_schema()
        seed_default_users()
        seed_default_settings()

    @app.before_request
    def authenticate_user():
        g.current_user = get_current_user()
        endpoint = request.endpoint or ""
        open_endpoints = {"login", "static"}
        if endpoint.startswith("static") or endpoint in open_endpoints:
            return None

        if not g.current_user:
            return redirect(url_for("login", next=request.path))
        return None

    @app.context_processor
    def inject_template_context():
        settings = get_all_settings()
        return {
            "current_user": getattr(g, "current_user", None),
            "is_admin": bool(getattr(g, "current_user", None) and g.current_user.role == ROLE_ADMIN),
            "shop_name": settings.get("shop_name", DEFAULT_SETTINGS["shop_name"]),
            "shop_address": settings.get("shop_address", DEFAULT_SETTINGS["shop_address"]),
            "shop_phone": settings.get("shop_phone", DEFAULT_SETTINGS["shop_phone"]),
            "currency_symbol": settings.get(
                "currency_symbol", DEFAULT_SETTINGS["currency_symbol"]
            ),
            "currency_code": settings.get("currency_code", DEFAULT_SETTINGS["currency_code"]),
            "receipt_width_mm": settings.get(
                "receipt_width_mm", DEFAULT_SETTINGS["receipt_width_mm"]
            ),
        }

    @app.errorhandler(403)
    def forbidden(_error):
        flash("You do not have permission to access that action.", "danger")
        return redirect(url_for("dashboard"))

    @app.route("/auth/login", methods=["GET", "POST"])
    def login():
        if g.current_user:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "").strip()
            user = User.query.filter(func.lower(User.username) == username).first()
            if user and user.check_password(password):
                session["user_id"] = user.id
                flash(f"Welcome, {user.full_name}.", "success")
                next_path = request.args.get("next") or url_for("dashboard")
                return redirect(next_path)
            flash("Invalid username or password.", "danger")

        return render_template("login.html")

    @app.post("/auth/logout")
    @login_required
    def logout():
        session.clear()
        flash("Signed out successfully.", "success")
        return redirect(url_for("login"))

    @app.route("/")
    def home():
        return redirect(url_for("dashboard"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        total_products = Product.query.count()
        low_stock_products = (
            Product.query.filter(Product.stock_quantity <= Product.reorder_level)
            .order_by(Product.stock_quantity.asc())
            .all()
        )
        inventory_value = (
            db.session.query(func.sum(Product.unit_price * Product.stock_quantity)).scalar()
            or Decimal("0")
        )
        month_start = datetime.combine(date.today().replace(day=1), datetime.min.time())
        monthly_sales = (
            db.session.query(func.sum(Invoice.grand_total))
            .filter(Invoice.created_at >= month_start)
            .scalar()
            or Decimal("0")
        )
        recent_invoices = Invoice.query.order_by(Invoice.created_at.desc()).limit(5).all()
        top_products = (
            db.session.query(
                Product.name.label("name"), func.sum(InvoiceItem.quantity).label("sold_qty")
            )
            .join(InvoiceItem, InvoiceItem.product_id == Product.id)
            .group_by(Product.id)
            .order_by(func.sum(InvoiceItem.quantity).desc())
            .limit(5)
            .all()
        )

        current_time = utc_now()
        sales_window_start = current_time - timedelta(days=6)
        sales_rows = (
            db.session.query(
                func.date(Invoice.created_at).label("sold_on"),
                func.sum(Invoice.grand_total).label("total"),
            )
            .filter(Invoice.created_at >= sales_window_start)
            .group_by(func.date(Invoice.created_at))
            .all()
        )
        sales_map = {row.sold_on: float(row.total or 0) for row in sales_rows}
        chart_labels: list[str] = []
        chart_values: list[float] = []
        for offset in range(7):
            day = (current_time - timedelta(days=6 - offset)).date()
            day_key = day.strftime("%Y-%m-%d")
            chart_labels.append(day.strftime("%d %b"))
            chart_values.append(sales_map.get(day_key, 0.0))

        return render_template(
            "dashboard.html",
            total_products=total_products,
            low_stock_products=low_stock_products,
            inventory_value=inventory_value,
            monthly_sales=monthly_sales,
            recent_invoices=recent_invoices,
            top_products=top_products,
            chart_labels=chart_labels,
            chart_values=chart_values,
        )

    @app.route("/products")
    @login_required
    def products():
        keyword = request.args.get("q", "").strip()
        query = Product.query.order_by(Product.name.asc())
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(
                or_(
                    Product.name.ilike(like),
                    Product.sku.ilike(like),
                    Product.category.ilike(like),
                )
            )

        return render_template("products.html", products=query.all(), keyword=keyword)

    @app.post("/products")
    @roles_required(ROLE_ADMIN)
    def add_product():
        name = request.form.get("name", "").strip()
        sku = request.form.get("sku", "").strip()
        category = request.form.get("category", "").strip() or "General"
        if not name or not sku:
            flash("Name and SKU are required.", "danger")
            return redirect(url_for("products"))

        existing = Product.query.filter_by(sku=sku).first()
        if existing:
            flash("SKU already exists. Use a unique SKU.", "danger")
            return redirect(url_for("products"))

        product = Product(
            name=name,
            sku=sku,
            category=category,
            unit_price=to_decimal(request.form.get("unit_price", "0")),
            stock_quantity=max(to_int(request.form.get("stock_quantity", "0")), 0),
            reorder_level=max(to_int(request.form.get("reorder_level", "5")), 0),
        )
        db.session.add(product)
        db.session.commit()
        flash("Product added successfully.", "success")
        return redirect(url_for("products"))

    @app.post("/products/<int:product_id>/update")
    @roles_required(ROLE_ADMIN)
    def update_product(product_id: int):
        product = db.get_or_404(Product, product_id)
        product.name = request.form.get("name", "").strip() or product.name
        product.category = request.form.get("category", "").strip() or product.category
        product.unit_price = to_decimal(request.form.get("unit_price", str(product.unit_price)))
        product.reorder_level = max(
            to_int(request.form.get("reorder_level", str(product.reorder_level))),
            0,
        )
        db.session.commit()
        flash(f"{product.name} updated.", "success")
        return redirect(url_for("products"))

    @app.post("/products/<int:product_id>/delete")
    @roles_required(ROLE_ADMIN)
    def delete_product(product_id: int):
        product = db.get_or_404(Product, product_id)
        if product.invoice_items:
            flash("Product cannot be deleted because it is used in invoices.", "warning")
            return redirect(url_for("products"))

        db.session.delete(product)
        db.session.commit()
        flash("Product deleted.", "success")
        return redirect(url_for("products"))

    @app.post("/stock-movements")
    @roles_required(ROLE_ADMIN)
    def record_stock_movement():
        product = db.get_or_404(Product, to_int(request.form.get("product_id")))
        movement_type = request.form.get("movement_type", "IN").upper()
        quantity = max(to_int(request.form.get("quantity", "0")), 0)
        notes = request.form.get("notes", "").strip()
        if quantity <= 0:
            flash("Movement quantity must be greater than zero.", "danger")
            return redirect(url_for("products"))

        signed_quantity = quantity
        if movement_type == "IN":
            product.stock_quantity += quantity
        elif movement_type == "OUT":
            if product.stock_quantity < quantity:
                flash(f"Insufficient stock for {product.name}.", "danger")
                return redirect(url_for("products"))
            product.stock_quantity -= quantity
            signed_quantity = -quantity
        elif movement_type == "ADJUSTMENT":
            signed_quantity = quantity - product.stock_quantity
            product.stock_quantity = quantity
        else:
            flash("Invalid movement type.", "danger")
            return redirect(url_for("products"))

        db.session.add(
            StockMovement(
                product=product,
                movement_type=movement_type,
                quantity=signed_quantity,
                notes=notes or None,
            )
        )
        db.session.commit()
        flash(f"Stock updated for {product.name}.", "success")
        return redirect(url_for("products"))

    @app.route("/customers", methods=["GET", "POST"])
    @roles_required(ROLE_ADMIN, ROLE_CASHIER)
    def customers():
        if request.method == "POST":
            customer_code = request.form.get("customer_code", "").strip().upper()
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            email = request.form.get("email", "").strip() or None

            if not customer_code or not name or not phone:
                flash("Customer ID, name, and telephone are required.", "danger")
                return redirect(url_for("customers"))

            if Customer.query.filter(func.lower(Customer.customer_code) == customer_code.lower()).first():
                flash("Customer ID already exists.", "danger")
                return redirect(url_for("customers"))

            customer = Customer(
                customer_code=customer_code,
                name=name,
                phone=phone,
                email=email,
            )
            db.session.add(customer)
            db.session.commit()
            flash(f"Customer {name} registered.", "success")
            return redirect(url_for("customers"))

        customer_rows = Customer.query.order_by(Customer.created_at.desc()).all()
        return render_template("customers.html", customers=customer_rows)

    @app.route("/billing/new")
    @roles_required(ROLE_ADMIN, ROLE_CASHIER)
    def new_invoice():
        products_with_stock = (
            Product.query.filter(Product.stock_quantity > 0).order_by(Product.name.asc()).all()
        )
        customers = Customer.query.order_by(Customer.name.asc()).all()
        return render_template(
            "billing_new.html",
            products=products_with_stock,
            customers=customers,
            tax_types=sorted(VALID_TAX_TYPES),
        )

    @app.post("/billing/create")
    @roles_required(ROLE_ADMIN, ROLE_CASHIER)
    def create_invoice():
        customer = None
        existing_customer_id = to_int(request.form.get("customer_id"), 0)
        if existing_customer_id:
            customer = db.session.get(Customer, existing_customer_id)
        else:
            customer_name = request.form.get("customer_name", "").strip()
            if customer_name:
                customer_code = request.form.get("customer_code", "").strip().upper() or None
                if customer_code and Customer.query.filter(
                    func.lower(Customer.customer_code) == customer_code.lower()
                ).first():
                    flash("Customer ID already exists. Choose another ID.", "danger")
                    return redirect(url_for("new_invoice"))
                customer = Customer(
                    customer_code=customer_code,
                    name=customer_name,
                    email=request.form.get("customer_email", "").strip() or None,
                    phone=request.form.get("customer_phone", "").strip() or None,
                )
                db.session.add(customer)
                db.session.flush()

        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")
        if not product_ids:
            flash("At least one line item is required.", "danger")
            return redirect(url_for("new_invoice"))

        grouped_lines: dict[int, int] = {}
        for raw_product_id, raw_quantity in zip(product_ids, quantities):
            product_id = to_int(raw_product_id)
            quantity = to_int(raw_quantity)
            if product_id <= 0 or quantity <= 0:
                continue
            grouped_lines[product_id] = grouped_lines.get(product_id, 0) + quantity

        lines: list[dict] = []
        for product_id, quantity in grouped_lines.items():
            product = db.session.get(Product, product_id)
            if not product:
                continue
            if product.stock_quantity < quantity:
                flash(f"Insufficient stock for {product.name}.", "danger")
                return redirect(url_for("new_invoice"))

            line_total = Decimal(product.unit_price) * Decimal(quantity)
            lines.append(
                {
                    "product": product,
                    "quantity": quantity,
                    "unit_price": Decimal(product.unit_price),
                    "line_total": line_total,
                }
            )

        if not lines:
            flash("Please add valid product lines before generating bill.", "danger")
            return redirect(url_for("new_invoice"))

        tax_type = request.form.get("tax_type", "GST").strip().upper()
        if tax_type not in VALID_TAX_TYPES:
            tax_type = "GST"

        subtotal = sum((line["line_total"] for line in lines), Decimal("0"))
        tax_rate = max(to_decimal(request.form.get("tax_rate", "0")), Decimal("0"))
        discount = max(to_decimal(request.form.get("discount", "0")), Decimal("0"))
        tax_amount = subtotal * (tax_rate / Decimal("100"))
        grand_total = max(subtotal + tax_amount - discount, Decimal("0"))

        invoice = Invoice(
            invoice_number=generate_invoice_number(tax_type),
            customer=customer,
            status=request.form.get("status", "PAID"),
            payment_method=request.form.get("payment_method", "cash"),
            tax_type=tax_type,
            tax_rate=tax_rate,
            discount=discount,
            subtotal=subtotal,
            tax_amount=tax_amount,
            grand_total=grand_total,
        )
        db.session.add(invoice)
        db.session.flush()

        for line in lines:
            db.session.add(
                InvoiceItem(
                    invoice=invoice,
                    product=line["product"],
                    quantity=line["quantity"],
                    unit_price=line["unit_price"],
                    line_total=line["line_total"],
                )
            )
            line["product"].stock_quantity -= line["quantity"]
            db.session.add(
                StockMovement(
                    product=line["product"],
                    movement_type="OUT",
                    quantity=-line["quantity"],
                    notes=f"Sold under {invoice.invoice_number}",
                )
            )

        db.session.commit()
        flash(f"Invoice {invoice.invoice_number} generated.", "success")
        return redirect(url_for("invoice_detail", invoice_id=invoice.id))

    @app.route("/invoices")
    @roles_required(ROLE_ADMIN, ROLE_CASHIER)
    def invoices():
        query = Invoice.query.order_by(Invoice.created_at.desc())

        from_date_text = request.args.get("from", "").strip()
        to_date_text = request.args.get("to", "").strip()
        customer_query = request.args.get("customer", "").strip()
        status = request.args.get("status", "").strip()
        tax_type = request.args.get("tax_type", "").strip().upper()

        if from_date_text:
            from_dt = datetime.combine(date.fromisoformat(from_date_text), datetime.min.time())
            query = query.filter(Invoice.created_at >= from_dt)
        if to_date_text:
            to_dt = datetime.combine(date.fromisoformat(to_date_text), datetime.max.time())
            query = query.filter(Invoice.created_at <= to_dt)
        if customer_query:
            like = f"%{customer_query}%"
            query = query.outerjoin(Customer).filter(
                or_(
                    Customer.name.ilike(like),
                    Customer.email.ilike(like),
                    Customer.customer_code.ilike(like),
                    Customer.phone.ilike(like),
                )
            )
        if status:
            query = query.filter(Invoice.status == status)
        if tax_type in VALID_TAX_TYPES:
            query = query.filter(Invoice.tax_type == tax_type)

        return render_template(
            "invoices.html",
            invoices=query.all(),
            from_date=from_date_text,
            to_date=to_date_text,
            customer_query=customer_query,
            status=status,
            tax_type=tax_type,
        )

    @app.route("/invoices/<int:invoice_id>")
    @roles_required(ROLE_ADMIN, ROLE_CASHIER)
    def invoice_detail(invoice_id: int):
        invoice = db.get_or_404(Invoice, invoice_id)
        return render_template("invoice_detail.html", invoice=invoice)

    @app.route("/invoices/<int:invoice_id>/receipt")
    @roles_required(ROLE_ADMIN, ROLE_CASHIER)
    def invoice_receipt(invoice_id: int):
        invoice = db.get_or_404(Invoice, invoice_id)
        return render_template("invoice_receipt.html", invoice=invoice)

    @app.get("/invoices/<int:invoice_id>/pdf")
    @roles_required(ROLE_ADMIN, ROLE_CASHIER)
    def download_invoice_pdf(invoice_id: int):
        invoice = db.get_or_404(Invoice, invoice_id)
        pdf_buffer = invoice_pdf_content(invoice, get_all_settings())
        file_name = f"{invoice.invoice_number.replace('/', '-')}.pdf"
        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=file_name,
        )

    @app.route("/settings", methods=["GET", "POST"])
    @roles_required(ROLE_ADMIN)
    def settings():
        if request.method == "POST":
            shop_name = request.form.get("shop_name", "").strip() or DEFAULT_SETTINGS["shop_name"]
            shop_address = request.form.get("shop_address", "").strip() or DEFAULT_SETTINGS["shop_address"]
            shop_phone = request.form.get("shop_phone", "").strip() or DEFAULT_SETTINGS["shop_phone"]
            currency_symbol = (
                request.form.get("currency_symbol", "").strip()
                or DEFAULT_SETTINGS["currency_symbol"]
            )
            currency_code = (
                request.form.get("currency_code", "").strip().upper()
                or DEFAULT_SETTINGS["currency_code"]
            )
            receipt_width_mm = request.form.get("receipt_width_mm", "").strip() or DEFAULT_SETTINGS[
                "receipt_width_mm"
            ]
            if to_int(receipt_width_mm, 0) <= 0:
                flash("Receipt width must be a positive number in mm.", "danger")
                return redirect(url_for("settings"))

            set_setting_value("shop_name", shop_name)
            set_setting_value("shop_address", shop_address)
            set_setting_value("shop_phone", shop_phone)
            set_setting_value("currency_symbol", currency_symbol)
            set_setting_value("currency_code", currency_code)
            set_setting_value("receipt_width_mm", receipt_width_mm)
            db.session.commit()
            flash("Settings updated successfully.", "success")
            return redirect(url_for("settings"))

        return render_template("settings.html", settings=get_all_settings())

    @app.route("/suppliers", methods=["GET", "POST"])
    @roles_required(ROLE_ADMIN)
    def suppliers():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Supplier name is required.", "danger")
                return redirect(url_for("suppliers"))

            existing = Supplier.query.filter(func.lower(Supplier.name) == name.lower()).first()
            if existing:
                flash("Supplier name already exists.", "warning")
                return redirect(url_for("suppliers"))

            supplier = Supplier(
                name=name,
                email=request.form.get("email", "").strip() or None,
                phone=request.form.get("phone", "").strip() or None,
                address=request.form.get("address", "").strip() or None,
                tax_registration=request.form.get("tax_registration", "").strip() or None,
            )
            db.session.add(supplier)
            db.session.commit()
            flash("Supplier added.", "success")
            return redirect(url_for("suppliers"))

        supplier_rows = Supplier.query.order_by(Supplier.name.asc()).all()
        return render_template("suppliers.html", suppliers=supplier_rows)

    @app.route("/purchase-orders")
    @roles_required(ROLE_ADMIN)
    def purchase_orders():
        orders = PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).all()
        return render_template("purchase_orders.html", orders=orders)

    @app.route("/purchase-orders/new")
    @roles_required(ROLE_ADMIN)
    def new_purchase_order():
        supplier_rows = Supplier.query.order_by(Supplier.name.asc()).all()
        products = Product.query.order_by(Product.name.asc()).all()
        return render_template(
            "purchase_order_new.html",
            suppliers=supplier_rows,
            products=products,
        )

    @app.post("/purchase-orders/create")
    @roles_required(ROLE_ADMIN)
    def create_purchase_order():
        supplier_id = to_int(request.form.get("supplier_id"), 0)
        supplier = db.session.get(Supplier, supplier_id)
        if not supplier:
            flash("Valid supplier is required.", "danger")
            return redirect(url_for("new_purchase_order"))

        status = request.form.get("status", "DRAFT").upper().strip()
        if status not in {"DRAFT", "RECEIVED"}:
            status = "DRAFT"

        expected_date = None
        expected_date_text = request.form.get("expected_date", "").strip()
        if expected_date_text:
            try:
                expected_date = date.fromisoformat(expected_date_text)
            except ValueError:
                flash("Expected date must be a valid date.", "danger")
                return redirect(url_for("new_purchase_order"))

        product_ids = request.form.getlist("product_id[]")
        quantities = request.form.getlist("quantity[]")
        unit_costs = request.form.getlist("unit_cost[]")

        lines: list[dict] = []
        for raw_product_id, raw_quantity, raw_unit_cost in zip(
            product_ids, quantities, unit_costs
        ):
            product_id = to_int(raw_product_id)
            quantity = max(to_int(raw_quantity), 0)
            unit_cost = max(to_decimal(raw_unit_cost), Decimal("0"))
            if product_id <= 0 or quantity <= 0 or unit_cost <= 0:
                continue
            product = db.session.get(Product, product_id)
            if not product:
                continue
            line_total = unit_cost * Decimal(quantity)
            lines.append(
                {
                    "product": product,
                    "quantity": quantity,
                    "unit_cost": unit_cost,
                    "line_total": line_total,
                }
            )

        if not lines:
            flash("Add at least one valid item to create purchase order.", "danger")
            return redirect(url_for("new_purchase_order"))

        subtotal = sum((line["line_total"] for line in lines), Decimal("0"))
        tax_rate = max(to_decimal(request.form.get("tax_rate", "0")), Decimal("0"))
        tax_amount = subtotal * (tax_rate / Decimal("100"))
        grand_total = subtotal + tax_amount

        po = PurchaseOrder(
            po_number=generate_purchase_order_number(),
            supplier=supplier,
            expected_date=expected_date,
            status=status,
            tax_rate=tax_rate,
            subtotal=subtotal,
            tax_amount=tax_amount,
            grand_total=grand_total,
            notes=request.form.get("notes", "").strip() or None,
            stock_applied=False,
        )
        db.session.add(po)
        db.session.flush()

        for line in lines:
            db.session.add(
                PurchaseOrderItem(
                    purchase_order=po,
                    product=line["product"],
                    quantity=line["quantity"],
                    unit_cost=line["unit_cost"],
                    line_total=line["line_total"],
                )
            )

        db.session.flush()
        if status == "RECEIVED":
            apply_purchase_order_stock(po)

        db.session.commit()
        flash(f"Purchase Order {po.po_number} saved.", "success")
        return redirect(url_for("purchase_order_detail", po_id=po.id))

    @app.route("/purchase-orders/<int:po_id>")
    @roles_required(ROLE_ADMIN)
    def purchase_order_detail(po_id: int):
        po = db.get_or_404(PurchaseOrder, po_id)
        return render_template("purchase_order_detail.html", po=po)

    @app.post("/purchase-orders/<int:po_id>/mark-received")
    @roles_required(ROLE_ADMIN)
    def mark_purchase_order_received(po_id: int):
        po = db.get_or_404(PurchaseOrder, po_id)
        if po.stock_applied:
            flash("Stock has already been received for this purchase order.", "warning")
            return redirect(url_for("purchase_order_detail", po_id=po.id))

        apply_purchase_order_stock(po)
        po.status = "RECEIVED"
        db.session.commit()
        flash(f"{po.po_number} marked as received and stock updated.", "success")
        return redirect(url_for("purchase_order_detail", po_id=po.id))

    @app.get("/reports/sales.csv")
    @roles_required(ROLE_ADMIN, ROLE_CASHIER)
    def sales_report_csv():
        query = Invoice.query.order_by(Invoice.created_at.asc())
        from_date_text = request.args.get("from", "").strip()
        to_date_text = request.args.get("to", "").strip()
        if from_date_text:
            from_dt = datetime.combine(date.fromisoformat(from_date_text), datetime.min.time())
            query = query.filter(Invoice.created_at >= from_dt)
        if to_date_text:
            to_dt = datetime.combine(date.fromisoformat(to_date_text), datetime.max.time())
            query = query.filter(Invoice.created_at <= to_dt)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Invoice Number",
                "Date",
                "Customer",
                "Tax Type",
                "Subtotal",
                "Tax Amount",
                "Discount",
                "Grand Total",
                "Payment Method",
                "Status",
            ]
        )
        for invoice in query.all():
            writer.writerow(
                [
                    invoice.invoice_number,
                    invoice.created_at.strftime("%Y-%m-%d %H:%M"),
                    invoice.customer.name if invoice.customer else "Walk-in",
                    invoice.tax_type,
                    str(invoice.subtotal),
                    str(invoice.tax_amount),
                    str(invoice.discount),
                    str(invoice.grand_total),
                    invoice.payment_method,
                    invoice.status,
                ]
            )

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=sales-report.csv"},
        )

    @app.get("/api/metrics")
    @roles_required(ROLE_ADMIN, ROLE_CASHIER)
    def metrics_api():
        total_invoices = Invoice.query.count()
        total_sales = db.session.query(func.sum(Invoice.grand_total)).scalar() or Decimal("0")
        total_customers = Customer.query.count()
        total_suppliers = Supplier.query.count()
        return jsonify(
            {
                "totalInvoices": total_invoices,
                "totalSales": float(total_sales),
                "totalCustomers": total_customers,
                "totalSuppliers": total_suppliers,
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
