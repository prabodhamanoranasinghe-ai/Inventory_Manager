# Inventory Manager & Billing Web App

An end-to-end inventory management + billing web application built with **Flask** and **SQLite**.

## Basic Features

- Role-based login (Admin and Cashier)
- Product management (add, search, update, delete)
- Stock management with movement tracking:
  - Stock IN
  - Stock OUT
  - Stock ADJUSTMENT
- Low-stock alerts based on reorder level
- Bill generation with:
  - Multiple line items
  - GST or VAT selection
  - Tax rate
  - Discount
  - Payment method
- Printable invoice page

## Advanced Features

- Dashboard analytics:
  - Inventory value
  - Monthly sales
  - 7-day sales chart
  - Top-selling products
- Invoice filtering by date, customer, and status
- Sales report CSV export
- Customer records attached to invoices
- GST/VAT financial-year compliant invoice numbering:
  - Example: `GST/2026-27/00001`
- Invoice PDF download
- Supplier management
- Purchase order management with stock receiving workflow
- Metrics API endpoint (`/api/metrics`)

## Tech Stack

- Python
- Flask
- Flask-SQLAlchemy
- ReportLab (PDF generation)
- SQLite
- Bootstrap + Chart.js

## Run Locally

1. Create a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Start the app:

   ```bash
   python app.py
   ```

4. Open in browser:

   ```text
   http://localhost:5000
   ```

## Default Login Credentials

- Admin: `admin` / `admin123`
- Cashier: `cashier` / `cashier123`

Change these credentials before production use.

## Test

```bash
python -m unittest discover -s tests
```
