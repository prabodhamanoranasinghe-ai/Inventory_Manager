from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_

db = SQLAlchemy()


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=lambda: utc_now(), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: utc_now(),
        onupdate=lambda: utc_now(),
        nullable=False,
    )


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


class Customer(TimestampMixin, db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(30), nullable=True)

    invoices = db.relationship("Invoice", back_populates="customer")


class Invoice(TimestampMixin, db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="PAID")
    payment_method = db.Column(db.String(30), nullable=False, default="cash")
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


def generate_invoice_number() -> str:
    next_id = (db.session.query(func.max(Invoice.id)).scalar() or 0) + 1
    return f"INV-{utc_now():%Y%m%d}-{next_id:04d}"


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

    @app.route("/")
    def home():
        return redirect(url_for("dashboard"))

    @app.route("/dashboard")
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

    @app.route("/billing/new")
    def new_invoice():
        products_with_stock = (
            Product.query.filter(Product.stock_quantity > 0).order_by(Product.name.asc()).all()
        )
        customers = Customer.query.order_by(Customer.name.asc()).all()
        return render_template(
            "billing_new.html",
            products=products_with_stock,
            customers=customers,
        )

    @app.post("/billing/create")
    def create_invoice():
        customer = None
        existing_customer_id = to_int(request.form.get("customer_id"), 0)
        if existing_customer_id:
            customer = db.session.get(Customer, existing_customer_id)
        else:
            customer_name = request.form.get("customer_name", "").strip()
            if customer_name:
                customer = Customer(
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

        subtotal = sum((line["line_total"] for line in lines), Decimal("0"))
        tax_rate = max(to_decimal(request.form.get("tax_rate", "0")), Decimal("0"))
        discount = max(to_decimal(request.form.get("discount", "0")), Decimal("0"))
        tax_amount = subtotal * (tax_rate / Decimal("100"))
        grand_total = max(subtotal + tax_amount - discount, Decimal("0"))

        invoice = Invoice(
            invoice_number=generate_invoice_number(),
            customer=customer,
            status=request.form.get("status", "PAID"),
            payment_method=request.form.get("payment_method", "cash"),
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
    def invoices():
        query = Invoice.query.order_by(Invoice.created_at.desc())

        from_date_text = request.args.get("from", "").strip()
        to_date_text = request.args.get("to", "").strip()
        customer_query = request.args.get("customer", "").strip()
        status = request.args.get("status", "").strip()

        if from_date_text:
            from_dt = datetime.combine(date.fromisoformat(from_date_text), datetime.min.time())
            query = query.filter(Invoice.created_at >= from_dt)
        if to_date_text:
            to_dt = datetime.combine(date.fromisoformat(to_date_text), datetime.max.time())
            query = query.filter(Invoice.created_at <= to_dt)
        if customer_query:
            like = f"%{customer_query}%"
            query = query.outerjoin(Customer).filter(
                or_(Customer.name.ilike(like), Customer.email.ilike(like))
            )
        if status:
            query = query.filter(Invoice.status == status)

        return render_template(
            "invoices.html",
            invoices=query.all(),
            from_date=from_date_text,
            to_date=to_date_text,
            customer_query=customer_query,
            status=status,
        )

    @app.route("/invoices/<int:invoice_id>")
    def invoice_detail(invoice_id: int):
        invoice = db.get_or_404(Invoice, invoice_id)
        return render_template("invoice_detail.html", invoice=invoice)

    @app.get("/reports/sales.csv")
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
    def metrics_api():
        total_invoices = Invoice.query.count()
        total_sales = db.session.query(func.sum(Invoice.grand_total)).scalar() or Decimal("0")
        total_customers = Customer.query.count()
        return jsonify(
            {
                "totalInvoices": total_invoices,
                "totalSales": float(total_sales),
                "totalCustomers": total_customers,
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
