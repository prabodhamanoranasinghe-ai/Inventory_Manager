import unittest
from decimal import Decimal

from app import Invoice, Product, PurchaseOrder, Supplier, create_app, db, financial_year_label


class InventoryAppTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login(self, username: str, password: str):
        return self.client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=True,
        )

    def test_login_required_redirect(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response.location)

    def test_admin_can_add_product(self):
        self.login("admin", "admin123")
        response = self.client.post(
            "/products",
            data={
                "name": "Test Laptop",
                "sku": "SKU-LAP-1",
                "category": "Electronics",
                "unit_price": "1200",
                "stock_quantity": "3",
                "reorder_level": "1",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Product.query.count(), 1)

    def test_cashier_cannot_add_product(self):
        self.login("cashier", "cashier123")
        response = self.client.post(
            "/products",
            data={
                "name": "Forbidden Product",
                "sku": "SKU-FORBIDDEN-1",
                "category": "Electronics",
                "unit_price": "500",
                "stock_quantity": "5",
                "reorder_level": "2",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Product.query.count(), 0)

    def test_invoice_reduces_stock_with_tax_sequence(self):
        product = Product(
            name="Wireless Mouse",
            sku="SKU-MOUSE-1",
            category="Accessories",
            unit_price=Decimal("25.00"),
            stock_quantity=10,
            reorder_level=2,
        )
        db.session.add(product)
        db.session.commit()

        self.login("cashier", "cashier123")
        response = self.client.post(
            "/billing/create",
            data={
                "customer_name": "Alice",
                "product_id[]": [str(product.id)],
                "quantity[]": ["2"],
                "tax_type": "VAT",
                "tax_rate": "10",
                "discount": "0",
                "payment_method": "cash",
                "status": "PAID",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Invoice.query.count(), 1)
        invoice = Invoice.query.first()
        fy = financial_year_label()
        self.assertTrue(invoice.invoice_number.startswith(f"VAT/{fy}/"))
        refreshed_product = db.session.get(Product, product.id)
        self.assertEqual(refreshed_product.stock_quantity, 8)

    def test_invoice_pdf_download(self):
        product = Product(
            name="USB Cable",
            sku="SKU-USB-1",
            category="Accessories",
            unit_price=Decimal("10.00"),
            stock_quantity=5,
            reorder_level=1,
        )
        db.session.add(product)
        db.session.commit()

        self.login("cashier", "cashier123")
        self.client.post(
            "/billing/create",
            data={
                "customer_name": "Bob",
                "product_id[]": [str(product.id)],
                "quantity[]": ["1"],
                "tax_type": "GST",
                "tax_rate": "5",
                "discount": "0",
                "payment_method": "card",
                "status": "PAID",
            },
            follow_redirects=True,
        )
        invoice = Invoice.query.first()
        pdf_response = self.client.get(f"/invoices/{invoice.id}/pdf")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")

    def test_purchase_order_received_increases_stock(self):
        product = Product(
            name="Keyboard",
            sku="SKU-KB-1",
            category="Accessories",
            unit_price=Decimal("50.00"),
            stock_quantity=2,
            reorder_level=1,
        )
        supplier = Supplier(name="Tech Supplies Ltd", email="supply@example.com")
        db.session.add_all([product, supplier])
        db.session.commit()

        self.login("admin", "admin123")
        response = self.client.post(
            "/purchase-orders/create",
            data={
                "supplier_id": str(supplier.id),
                "status": "RECEIVED",
                "tax_rate": "5",
                "product_id[]": [str(product.id)],
                "quantity[]": ["4"],
                "unit_cost[]": ["35"],
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PurchaseOrder.query.count(), 1)
        refreshed_product = db.session.get(Product, product.id)
        self.assertEqual(refreshed_product.stock_quantity, 6)


if __name__ == "__main__":
    unittest.main()
