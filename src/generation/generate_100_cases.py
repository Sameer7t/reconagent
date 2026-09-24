"""
Real-World 100-Case Synthetic Dataset Generator for Accounts Payable & 3-Way Reconciliation.

Generates 100 realistic transaction cases (~301 total documents) across 12 diverse business scenarios:
1. PERFECT_MATCH (25 cases)
2. QUANTITY_SHORTAGE (15 cases)
3. PRICE_VARIANCE (15 cases)
4. MISSING_PO_REF (10 cases)
5. MATH_ERROR (10 cases)
6. ITEM_SUBSTITUTION (8 cases)
7. UNAUTHORIZED_CHARGE (5 cases)
8. SHIPPING_EXCEEDS_PO (4 cases)
9. PARTIAL_DELIVERY_MATCH (3 cases, 2 receipts each)
10. VENDOR_NAME_VARIATION (2 cases)
11. DISCOUNT_NOT_APPLIED (2 cases)
12. MISSING_RECEIPT (1 case, PO + Invoice only)

All generated documents are placed into a single mixed folder:
`dataset/mock_reconciliation_100/mixed_documents/`
"""
import os
import json
import random
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Any, Tuple

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TARGET_BASE_DIR = PROJECT_ROOT / "dataset" / "mock_reconciliation_100"
MIXED_DOCS_DIR = TARGET_BASE_DIR / "mixed_documents"
GROUND_TRUTH_FILE = TARGET_BASE_DIR / "ground_truth_labels.json"

# Set deterministic seed for 100% reproducibility
random.seed(2026)

# Corporate Entities & Industry Product Catalogs
INDUSTRIES = [
    {
        "domain": "IT & Computing Hardware",
        "vendor": "TechTraders Solutions Inc.",
        "address": "1024 Silicon Valley Blvd, Bldg 4A, San Jose, CA 95110",
        "tax_id": "12-3456789",
        "phone": "(408) 555-0199",
        "email": "sales@techtraders.com",
        "remit": "Wells Fargo Bank, Acct: ******9021, Routing: ******029",
        "products": [
            ("TT-CPU-109", "Intel Core i9-13900K Processor", Decimal("560.00")),
            ("TT-RAM-032", "Corsair Vengeance 32GB DDR5 RAM", Decimal("120.00")),
            ("TT-SSD-002", "Samsung 990 Pro 2TB NVMe SSD", Decimal("170.00")),
            ("TT-GPU-409", "NVIDIA GeForce RTX 4090 24GB", Decimal("1650.00")),
            ("TT-MBD-001", "ASUS ROG Maximus Z790 Motherboard", Decimal("450.00")),
            ("TT-PWR-850", "Seasonic Focus 850W Gold PSU", Decimal("135.00")),
        ],
    },
    {
        "domain": "Industrial Machinery & Tools",
        "vendor": "Titan Industrial Tools Corp",
        "address": "8840 Forge Parkway, Sector 9, Detroit, MI 48201",
        "tax_id": "38-9921456",
        "phone": "(313) 555-7821",
        "email": "orders@titanindustrial.com",
        "remit": "Comerica Bank, Acct: ******4412, Routing: ******105",
        "products": [
            ("TI-CNC-400", "Carbide End Mill 4-Flute 1/2in", Decimal("45.00")),
            ("TI-HYD-012", "Hydraulic Pressure Valve 3000 PSI", Decimal("320.00")),
            ("TI-PNE-088", "Pneumatic Actuator Cylinder 50mm", Decimal("210.00")),
            ("TI-LUB-005", "Synthetic Gear Lubricant 5-Gallon", Decimal("115.00")),
            ("TI-BRG-220", "Heavy-Duty Tapered Roller Bearing", Decimal("85.00")),
        ],
    },
    {
        "domain": "Medical & Clinical Diagnostics",
        "vendor": "BioMed Scientific Solutions LLC",
        "address": "400 Discovery Way, Suite 300, Cambridge, MA 02142",
        "tax_id": "04-7812903",
        "phone": "(617) 555-0344",
        "email": "billing@biomedscientific.com",
        "remit": "Bank of America, Acct: ******8819, Routing: ******011",
        "products": [
            ("BM-PIP-100", "Micro-Pipette Electronic 100uL", Decimal("280.00")),
            ("BM-CEN-015", "Centrifuge Tube Conical 15mL (500pk)", Decimal("95.00")),
            ("BM-REA-004", "RNA Extraction Reagent Kit 50 Preps", Decimal("340.00")),
            ("BM-SER-500", "Fetal Bovine Serum Premium 500mL", Decimal("420.00")),
            ("BM-GLV-008", "Nitrile Examination Gloves Medium (1000ct)", Decimal("75.00")),
        ],
    },
    {
        "domain": "Commercial Freight & Logistics",
        "vendor": "TransGlobal Logistics Corp",
        "address": "1200 Harbor View Rd, Pier 18, Long Beach, CA 90802",
        "tax_id": "95-1029384",
        "phone": "(562) 555-9011",
        "email": "dispatch@transgloballogistics.com",
        "remit": "JPMorgan Chase, Acct: ******5520, Routing: ******002",
        "products": [
            ("TG-FRT-LTL", "Less-Than-Truckload Freight Standard Zone 4", Decimal("650.00")),
            ("TG-PAL-HD4", "Heavy Duty Heat-Treated Wood Pallet 48x40", Decimal("28.00")),
            ("TG-STR-001", "Polypropylene Strapping Band 1/2in Coil", Decimal("65.00")),
            ("TG-WRK-002", "Stretch Wrap Industrial Cast 80 Gauge", Decimal("38.00")),
            ("TG-CRG-INS", "Container Drayage & Handling Fee", Decimal("450.00")),
        ],
    },
    {
        "domain": "Commercial Office Supplies",
        "vendor": "Global Office Supplies Inc",
        "address": "2500 Enterprise Ave, Floor 3, Chicago, IL 60606",
        "tax_id": "36-4491028",
        "phone": "(312) 555-4400",
        "email": "accounts@globalofficesupplies.com",
        "remit": "Northern Trust, Acct: ******1982, Routing: ******340",
        "products": [
            ("GO-TON-055", "OEM Black Laser Toner Cartridge 10K Yield", Decimal("185.00")),
            ("GO-PAP-A40", "Multipurpose Copy Paper 20lb (10-Ream Case)", Decimal("55.00")),
            ("GO-CHR-ERG", "High-Back Ergonomic Mesh Task Chair", Decimal("320.00")),
            ("GO-DSK-ADJ", "Motorized Dual-Motor Standing Desk Frame", Decimal("480.00")),
            ("GO-LAM-120", "Thermal Pouch Laminator 12-inch", Decimal("110.00")),
        ],
    },
    {
        "domain": "Chemical & Specialty Polymers",
        "vendor": "Apex Chemical Synthetics Inc",
        "address": "770 Catalyst Lane, Building C, Houston, TX 77015",
        "tax_id": "74-5519823",
        "phone": "(713) 555-6677",
        "email": "invoicing@apexchemical.com",
        "remit": "PNC Bank, Acct: ******3311, Routing: ******788",
        "products": [
            ("AC-POL-55G", "Polyethylene Glycol Industrial 55-Gal Drum", Decimal("540.00")),
            ("AC-SOL-020", "High-Purity Acetone ACS Grade 20L", Decimal("130.00")),
            ("AC-CAT-005", "Platinum Catalyst Solution 500mL", Decimal("890.00")),
            ("AC-ISO-055", "Isopropyl Alcohol 99.8% Technical Drum", Decimal("310.00")),
            ("AC-EPX-010", "Two-Part Structural Epoxy Adhesive 10kg", Decimal("160.00")),
        ],
    },
    {
        "domain": "Wholesale Food & Ingredients",
        "vendor": "Prairie Harvest Foods Corp",
        "address": "1500 Grain Terminal Rd, Omaha, NE 68102",
        "tax_id": "47-8891023",
        "phone": "(402) 555-1234",
        "email": "orders@prairieharvestfoods.com",
        "remit": "US Bank, Acct: ******7741, Routing: ******991",
        "products": [
            ("PH-FLR-050", "Organic Hard Red Wheat Flour 50lb Sack", Decimal("32.00")),
            ("PH-OAT-025", "Rolled Oats Whole Grain 25lb Bag", Decimal("24.00")),
            ("PH-HNY-060", "Pure Clover Raw Honey 60lb Pail", Decimal("195.00")),
            ("PH-OIL-035", "Non-GMO Canola Cooking Oil 35lb Jug", Decimal("48.00")),
            ("PH-SUG-050", "Cane Sugar Extra Fine Granulated 50lb", Decimal("42.00")),
        ],
    },
    {
        "domain": "Electrical & Power Systems",
        "vendor": "VoltTech Electric Systems LLC",
        "address": "3300 Kilowatt Way, Suite 100, Charlotte, NC 28208",
        "tax_id": "56-2299104",
        "phone": "(704) 555-8900",
        "email": "billing@volttechsystems.com",
        "remit": "Truist Bank, Acct: ******6619, Routing: ******442",
        "products": [
            ("VT-BRK-200", "Molded Case Circuit Breaker 200A 3-Pole", Decimal("450.00")),
            ("VT-TRF-075", "Dry-Type Distribution Transformer 75kVA", Decimal("3800.00")),
            ("VT-CBL-500", "Copper THHN Wire 500kcmil (500ft Spool)", Decimal("1450.00")),
            ("VT-SPD-120", "Surge Protective Device Type 1 120/208V", Decimal("290.00")),
            ("VT-PAN-42C", "Panelboard NEMA 1 Enclosure 42-Circuit", Decimal("620.00")),
        ],
    },
]

BUYER_PROFILES = [
    {
        "name": "Alpha Research Labs LLC",
        "dept": "Accounts Payable Dept",
        "address": "400 Science Parkway, Suite 101, Rochester, NY 14620",
        "dock": "Attn: Receiving Dock B",
    },
    {
        "name": "Omega Engineering Corp",
        "dept": "Procurement & Invoicing",
        "address": "1800 Technology Drive, Building 3, Austin, TX 78758",
        "dock": "Attn: Central Warehouse Gate 4",
    },
    {
        "name": "Apex Innovations Group",
        "dept": "Finance & Accounting",
        "address": "750 Innovation Blvd, Floor 4, Seattle, WA 98101",
        "dock": "Attn: Receiving Dock 1",
    },
    {
        "name": "Pinnacle Manufacturing Ltd",
        "dept": "Accounts Payable Division",
        "address": "900 Industrial Boulevard, Cleveland, OH 44114",
        "dock": "Attn: Loading Bay C",
    },
    {
        "name": "Beacon Health Systems Inc",
        "dept": "Supply Chain & AP",
        "address": "120 Medical Plaza, Tower East, Boston, MA 02115",
        "dock": "Attn: Materials Management Dock",
    },
]

# 100 Scenarios breakdown
SCENARIO_SCHEDULE: List[str] = (
    ["PERFECT_MATCH"] * 25 +
    ["QUANTITY_SHORTAGE"] * 15 +
    ["PRICE_VARIANCE"] * 15 +
    ["MISSING_PO_REF"] * 10 +
    ["MATH_ERROR"] * 10 +
    ["ITEM_SUBSTITUTION"] * 8 +
    ["UNAUTHORIZED_CHARGE"] * 5 +
    ["SHIPPING_EXCEEDS_PO"] * 4 +
    ["PARTIAL_DELIVERY_MATCH"] * 3 +
    ["VENDOR_NAME_VARIATION"] * 2 +
    ["DISCOUNT_NOT_APPLIED"] * 2 +
    ["MISSING_RECEIPT"] * 1
)
assert len(SCENARIO_SCHEDULE) == 100, f"Expected 100 scenarios, got {len(SCENARIO_SCHEDULE)}"


def _fmt(val: Decimal) -> str:
    """Format Decimal as currency string without dollar sign."""
    return f"{val:,.2f}"


def _make_po_text(
    trx_id: str,
    po_num: str,
    vendor: dict,
    buyer: dict,
    order_date: str,
    items: list,
    subtotal: Decimal,
    discount: Decimal,
    shipping: Decimal,
    tax: Decimal,
    total: Decimal,
) -> str:
    lines = [
        "=" * 80,
        "PURCHASE ORDER",
        "=" * 80,
        f"PO Number: {po_num}",
        f"PO Date: {order_date}",
        "Payment Terms: Net 30",
        "FOB Point: Destination",
        f"Transaction ID: {trx_id}",
        "",
        f"VENDOR: {vendor['vendor']}",
        f"Address: {vendor['address']}",
        f"Tax ID: {vendor['tax_id']}",
        f"Phone: {vendor['phone']}",
        f"Contact: {vendor['email']}",
        "",
        "BILL TO:",
        buyer["name"],
        buyer["dept"],
        buyer["address"],
        "",
        "SHIP TO:",
        buyer["name"],
        buyer["dock"],
        buyer["address"],
        "",
        "-" * 80,
        f"{'SKU / ITEM':<16} {'DESCRIPTION':<34} {'QTY':>6} {'UNIT PRICE':>12} {'TOTAL':>15}",
        "-" * 80,
    ]
    for sku, desc, qty, unit_price, line_tot in items:
        lines.append(f"{sku:<16} {desc:<34} {qty:>6} {'$'+_fmt(unit_price):>12} {'$'+_fmt(line_tot):>15}")
    lines.append("-" * 80)
    lines.append(f"{'SUBTOTAL:':>65} {'$'+_fmt(subtotal):>14}")
    if discount > 0:
        lines.append(f"{'DISCOUNT:':>65} {'$'+_fmt(discount):>14}")
    lines.append(f"{'SHIPPING:':>65} {'$'+_fmt(shipping):>14}")
    lines.append(f"{'TAX (8.0%):':>65} {'$'+_fmt(tax):>14}")
    lines.append(f"{'GRAND TOTAL:':>65} {'$'+_fmt(total):>14}")
    lines.append("=" * 80)
    lines.append("Authorized Signature: _______________________ (Purchasing Dept)")
    lines.append(f"Terms & Conditions: Please reference {po_num} on all delivery documents and invoices.")
    lines.append("=" * 80)
    return "\n".join(lines)


def _make_inv_text(
    trx_id: str,
    inv_num: str,
    po_ref: str,
    vendor: dict,
    vendor_display_name: str,
    buyer: dict,
    inv_date: str,
    due_date: str,
    items: list,
    subtotal: Decimal,
    discount: Decimal,
    shipping: Decimal,
    tax: Decimal,
    total: Decimal,
    tax_label: str = "TAX (8.0%):",
    surcharge_label: str = None,
    surcharge_val: Decimal = Decimal("0.00"),
) -> str:
    lines = [
        "=" * 80,
        "INVOICE",
        "=" * 80,
        f"Invoice Number: {inv_num}",
        f"Invoice Date: {inv_date}",
        f"Payment Due Date: {due_date}",
        f"PO Reference: {po_ref if po_ref else 'None'}",
        f"Transaction ID: {trx_id}",
        "",
        f"VENDOR: {vendor_display_name}",
        f"Address: {vendor['address']}",
        f"Tax ID: {vendor['tax_id']}",
        f"Remit To: {vendor['remit']}",
        "",
        "BILL TO:",
        buyer["name"],
        buyer["dept"],
        buyer["address"],
        "",
        "-" * 80,
        f"{'SKU / ITEM':<16} {'DESCRIPTION':<34} {'QTY':>6} {'UNIT PRICE':>12} {'TOTAL':>15}",
        "-" * 80,
    ]
    for sku, desc, qty, unit_price, line_tot in items:
        lines.append(f"{sku:<16} {desc:<34} {qty:>6} {'$'+_fmt(unit_price):>12} {'$'+_fmt(line_tot):>15}")
    lines.append("-" * 80)
    lines.append(f"{'SUBTOTAL:':>65} {'$'+_fmt(subtotal):>14}")
    if discount > 0:
        lines.append(f"{'DISCOUNT:':>65} {'$'+_fmt(discount):>14}")
    if surcharge_label and surcharge_val > 0:
        lines.append(f"{surcharge_label:>65} {'$'+_fmt(surcharge_val):>14}")
    lines.append(f"{'SHIPPING:':>65} {'$'+_fmt(shipping):>14}")
    lines.append(f"{tax_label:>65} {'$'+_fmt(tax):>14}")
    lines.append(f"{'GRAND TOTAL:':>65} {'$'+_fmt(total):>14}")
    lines.append("=" * 80)
    lines.append("Payment Terms: Net 30. Thank you for your business!")
    lines.append("=" * 80)
    return "\n".join(lines)


def _make_rec_text(
    trx_id: str,
    rec_num: str,
    po_ref: str,
    vendor: dict,
    vendor_display_name: str,
    buyer: dict,
    del_date: str,
    items: list,  # (sku, desc, qty_ordered, qty_delivered)
    carrier: str = "FedEx Freight Priority (Tracking #: 9812490192)",
    note: str = "Status: Complete / No Damaged Goods Reported",
) -> str:
    lines = [
        "=" * 80,
        "DELIVERY RECEIPT",
        "=" * 80,
        f"Receipt Number: {rec_num}",
        f"Delivery Date: {del_date}",
        f"PO Reference: {po_ref if po_ref else 'None'}",
        f"Transaction ID: {trx_id}",
        "",
        f"VENDOR: {vendor_display_name}",
        f"Address: {vendor['address']}",
        "",
        "DELIVERED TO:",
        buyer["name"],
        buyer["dock"],
        buyer["address"],
        "",
        f"Carrier: {carrier}",
        "",
        "-" * 80,
        f"{'SKU / ITEM':<16} {'DESCRIPTION':<34} {'QTY ORDERED':>14} {'QTY DELIVERED':>15}",
        "-" * 80,
    ]
    for sku, desc, q_ord, q_del in items:
        lines.append(f"{sku:<16} {desc:<34} {q_ord:>14} {q_del:>15}")
    lines.append("-" * 80)
    lines.append(note)
    lines.append("Received By: J. Martinez (Signature on file)")
    lines.append("Time of Delivery: 10:45 AM")
    lines.append("=" * 80)
    return "\n".join(lines)


def generate_all_100_cases() -> Tuple[int, int]:
    """
    Generates 100 transaction cases and saves ~301 mixed documents.
    Returns (num_cases, num_documents).
    """
    MIXED_DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # Clean existing files in directory if any
    for existing_f in MIXED_DOCS_DIR.glob("*.txt"):
        try:
            existing_f.unlink()
        except Exception:
            pass

    ground_truth = {}
    total_documents_written = 0

    for idx, scenario in enumerate(SCENARIO_SCHEDULE, start=1):
        trx_id = f"TRX_100_{idx:03d}"
        po_num = f"PO-2024-{idx:04d}"
        inv_num = f"INV-{30000 + idx}"
        rec_num = f"DR-{70000 + idx}"
        order_date = f"2024-0{((idx % 8) + 1):01d}-10"
        del_date = f"2024-0{((idx % 8) + 1):01d}-15"
        inv_date = f"2024-0{((idx % 8) + 1):01d}-16"
        due_date = f"2024-0{((idx % 8) + 2):01d}-16"

        vendor_data = INDUSTRIES[(idx - 1) % len(INDUSTRIES)]
        buyer_data = BUYER_PROFILES[(idx - 1) % len(BUYER_PROFILES)]
        catalog = vendor_data["products"]

        # Choose 2 or 3 distinct products for this transaction
        num_items = 2 if (idx % 2 == 0) else 3
        chosen_products = catalog[:num_items]

        # Standard PO quantities
        base_quantities = [Decimal(str(random.choice([5, 8, 10, 12, 15, 20]))) for _ in range(num_items)]

        # Construct base PO items: (sku, desc, qty, unit_price, line_tot)
        po_items = []
        for (sku, desc, unit_price), qty in zip(chosen_products, base_quantities):
            line_tot = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            po_items.append((sku, desc, qty, unit_price, line_tot))

        po_subtotal = sum(item[4] for item in po_items).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        po_discount = Decimal("0.00")
        po_shipping = Decimal("45.00")
        po_tax = (po_subtotal * Decimal("0.08")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        po_total = (po_subtotal - po_discount + po_shipping + po_tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        vendor_po_name = vendor_data["vendor"]
        vendor_inv_name = vendor_data["vendor"]
        vendor_rec_name = vendor_data["vendor"]

        # Default Invoice & Receipt items mirror PO
        inv_items = [(sku, desc, qty, unit_price, line_tot) for sku, desc, qty, unit_price, line_tot in po_items]
        rec_items = [(sku, desc, qty, qty) for sku, desc, qty, unit_price, line_tot in po_items]

        inv_po_ref = po_num
        inv_subtotal = po_subtotal
        inv_discount = po_discount
        inv_shipping = po_shipping
        inv_tax = po_tax
        inv_total = po_total
        tax_label = "TAX (8.0%):"
        surcharge_label = None
        surcharge_val = Decimal("0.00")

        second_receipt_text = None
        omit_receipt = False

        # Apply specific scenario modifications
        if scenario == "PERFECT_MATCH":
            # Everything matches perfectly
            pass

        elif scenario == "QUANTITY_SHORTAGE":
            # Receipt has shortage on item 0; Invoice bills full PO quantity
            short_qty = max(Decimal("1"), po_items[0][2] - Decimal("4"))
            rec_items[0] = (po_items[0][0], po_items[0][1], po_items[0][2], short_qty)

        elif scenario == "PRICE_VARIANCE":
            # Invoice unit price is higher by 15% on item 0
            new_unit_price = (po_items[0][3] * Decimal("1.15")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            new_line_tot = (po_items[0][2] * new_unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            inv_items[0] = (po_items[0][0], po_items[0][1], po_items[0][2], new_unit_price, new_line_tot)
            inv_subtotal = sum(item[4] for item in inv_items)
            inv_tax = (inv_subtotal * Decimal("0.08")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            inv_total = inv_subtotal - inv_discount + inv_shipping + inv_tax

        elif scenario == "MISSING_PO_REF":
            # Invoice completely omits the PO reference
            inv_po_ref = None

        elif scenario == "MATH_ERROR":
            # Invoice has a math discrepancy (subtotal reported is $150 too high, or grand total math error)
            if idx % 2 == 0:
                # Subtotal discrepancy
                inv_subtotal = po_subtotal + Decimal("150.00")
                inv_total = inv_subtotal - inv_discount + inv_shipping + inv_tax
            else:
                # Grand total calculation error
                inv_total = po_total + Decimal("200.00")

        elif scenario == "ITEM_SUBSTITUTION":
            # Supplier delivered and invoiced a substituted SKU / product for item 0
            sub_sku = f"{po_items[0][0]}-SUB"
            sub_desc = f"{po_items[0][1]} (Alternate Specification)"
            inv_items[0] = (sub_sku, sub_desc, po_items[0][2], po_items[0][3], po_items[0][4])
            rec_items[0] = (sub_sku, sub_desc, po_items[0][2], po_items[0][2])

        elif scenario == "UNAUTHORIZED_CHARGE":
            # Invoice adds an unauthorized fee/surcharge
            surcharge_label = "EXPEDITED HANDLING SURCHARGE:"
            surcharge_val = Decimal("175.00")
            inv_total = po_total + surcharge_val

        elif scenario == "SHIPPING_EXCEEDS_PO":
            # Invoice shipping is $185.00 instead of $45.00
            inv_shipping = Decimal("185.00")
            inv_total = inv_subtotal - inv_discount + inv_shipping + inv_tax

        elif scenario == "PARTIAL_DELIVERY_MATCH":
            # 2 delivery receipts that sum up to the total PO quantity
            rec_num_a = f"{rec_num}-A"
            rec_num_b = f"{rec_num}-B"

            # Split deliveries
            rec_items_a = []
            rec_items_b = []
            for sku, desc, q_ord, unit_price, line_tot in po_items:
                q_del_a = (q_ord // 2).quantize(Decimal("1"))
                q_del_b = q_ord - q_del_a
                rec_items_a.append((sku, desc, q_ord, q_del_a))
                rec_items_b.append((sku, desc, q_ord, q_del_b))

            rec_text_a = _make_rec_text(
                trx_id, rec_num_a, po_num, vendor_data, vendor_rec_name, buyer_data, del_date, rec_items_a,
                carrier="FedEx Freight Delivery 1/2", note="Status: Partial Delivery #1 Accepted"
            )
            second_receipt_text = _make_rec_text(
                trx_id, rec_num_b, po_num, vendor_data, vendor_rec_name, buyer_data, f"{del_date[:8]}18", rec_items_b,
                carrier="FedEx Freight Delivery 2/2", note="Status: Final Balance Delivery #2 Accepted"
            )
            # The primary receipt text is rec_text_a
            rec_text = rec_text_a

        elif scenario == "VENDOR_NAME_VARIATION":
            # Real world suffix noise: e.g. "Corp" vs "Corporation", "LLC" vs "Limited"
            vendor_inv_name = vendor_po_name.replace("Inc.", "Incorporated").replace("LLC", "Limited").replace("Corp", "Corporation")
            vendor_rec_name = vendor_po_name.replace("Solutions Inc.", "Solutions Co.").replace("Tools Corp", "Tools")

        elif scenario == "DISCOUNT_NOT_APPLIED":
            # PO specified a $100 contract discount; Invoice failed to apply it
            po_discount = Decimal("100.00")
            po_total = po_subtotal - po_discount + po_shipping + po_tax
            inv_discount = Decimal("0.00")
            inv_total = inv_subtotal - inv_discount + inv_shipping + inv_tax

        elif scenario == "MISSING_RECEIPT":
            # PO and Invoice exist, but receipt is missing / goods not delivered
            omit_receipt = True

        # Generate PO text
        po_text = _make_po_text(
            trx_id, po_num, vendor_data, buyer_data, order_date, po_items,
            po_subtotal, po_discount, po_shipping, po_tax, po_total
        )

        # Generate Invoice text
        inv_text = _make_inv_text(
            trx_id, inv_num, inv_po_ref, vendor_data, vendor_inv_name, buyer_data,
            inv_date, due_date, inv_items, inv_subtotal, inv_discount, inv_shipping,
            inv_tax, inv_total, tax_label=tax_label,
            surcharge_label=surcharge_label, surcharge_val=surcharge_val
        )

        # Generate Receipt text (if not partial scenario handled above)
        if scenario != "PARTIAL_DELIVERY_MATCH" and not omit_receipt:
            rec_text = _make_rec_text(
                trx_id, rec_num, po_num, vendor_data, vendor_rec_name, buyer_data, del_date, rec_items
            )

        # Write files into single mixed directory with non-descriptive doc labels
        # Shuffle document assignments per case so doc_1 is not always PO
        case_docs: List[Tuple[str, str]] = [("PO", po_text), ("INVOICE", inv_text)]
        if not omit_receipt:
            case_docs.append(("RECEIPT", rec_text))
        if second_receipt_text:
            case_docs.append(("RECEIPT", second_receipt_text))

        # Shuffle order of documents in this case
        random.shuffle(case_docs)

        for doc_i, (doc_type, content) in enumerate(case_docs, start=1):
            doc_filename = f"{trx_id}_doc_{doc_i}.txt"
            file_path = MIXED_DOCS_DIR / doc_filename
            file_path.write_text(content, encoding="utf-8")
            total_documents_written += 1

        ground_truth[trx_id] = scenario

    # Write ground truth mapping
    GROUND_TRUTH_FILE.write_text(json.dumps(ground_truth, indent=4), encoding="utf-8")

    return len(ground_truth), total_documents_written


if __name__ == "__main__":
    cases_cnt, docs_cnt = generate_all_100_cases()
    print(f"Generated {cases_cnt} cases with {docs_cnt} mixed documents in {MIXED_DOCS_DIR}")
    print(f"Ground truth saved to {GROUND_TRUTH_FILE}")

