import unittest
from decimal import Decimal

from app import Product, Invoice, create_app, db


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

    def test_can_add_product(self):
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

    def test_invoice_reduces_stock(self):
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

        response = self.client.post(
            "/billing/create",
            data={
                "customer_name": "Alice",
                "product_id[]": [str(product.id)],
                "quantity[]": ["2"],
                "tax_rate": "10",
                "discount": "0",
                "payment_method": "cash",
                "status": "PAID",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Invoice.query.count(), 1)
        refreshed_product = Product.query.get(product.id)
        self.assertEqual(refreshed_product.stock_quantity, 8)


if __name__ == "__main__":
    unittest.main()
