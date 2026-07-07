import re
import csv

def classify_counterparty(entry):
    if not entry or entry.strip() == "":
        return "none", None
    entry = entry.strip()
    if entry == "(fee)":
        return "fee", None
    elif re.match(r'^[0-9a-f]{16}$', entry):
        return "unlabeled_cluster", entry
    else:
        return "labeled_entity", entry

def parse_transaction_row(row):
    received_from = row["received from"]
    sent_to = row["sent to"]
    counterparty_raw = received_from if received_from else sent_to
    category, value = classify_counterparty(counterparty_raw)
    return {
        "date": row["date"],
        "direction": "in" if received_from else "out",
        "counterparty_category": category,
        "counterparty_value": value,
        "received_amount": row["received amount"],
        "sent_amount": row["sent amount"],
        "balance": row["balance"],
        "txid": row["transaction"]
    }

named_entities = []

# Replace this path with the location of your own WalletExplorer CSV export
CSV_FILE_PATH = "path/to/your/walletexplorer-export.csv"

with open(CSV_FILE_PATH, newline='', encoding='utf-8') as f:
    next(f)  # skip the "#Wallet..." metadata line
    reader = csv.DictReader(f)
    for r in reader:
        parsed = parse_transaction_row(r)
        if parsed["counterparty_category"] == "labeled_entity":
            named_entities.append(parsed)

print(f"Found {len(named_entities)} transactions with named entities:")
for row in named_entities:
    print(row)
