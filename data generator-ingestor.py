"""
Banking Fraud Simulation — Data Ingestion Script
=================================================
Covers:
  • Seed all tables with realistic fake data
  • Simulate all 4 fraud rule types:
      1. HIGH_AMOUNT     — single transaction exceeds threshold
      2. HIGH_FREQUENCY  — velocity: many transactions in a short window
      3. COUNTRY_MISMATCH— merchant country differs from customer country
      4. FROZEN_CARD     — transaction attempted on a frozen card / account

Requirements:
    pip install psycopg2-binary faker

Usage:
    python ingest_data.py --host localhost --port 5432 \
        --dbname banking --user postgres --password secret

    # Dry-run (print SQL only, no DB connection needed):
    python ingest_data.py --dry-run
"""

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timedelta, date
from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values
from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

# ──────────────────────────────────────────────
# Config knobs
# ──────────────────────────────────────────────
NUM_CUSTOMERS        = 40
ACCOUNTS_PER_CUSTOMER = 2          # up to
CARDS_PER_ACCOUNT     = 2          # up to
NORMAL_TXN_COUNT      = 120        # non-fraud baseline
FRAUD_HIGH_AMT_COUNT  = 6
FRAUD_VELOCITY_COUNT  = 12         # rapid burst per one card
FRAUD_MISMATCH_COUNT  = 8
FRAUD_FROZEN_COUNT    = 5

CURRENCIES   = ["UAH", "USD", "EUR"]
COUNTRIES    = ["UA", "US", "DE", "FR", "PL", "GB", "CN", "AE", "BR"]
MERCHANT_CAT = ["grocery", "electronics", "travel", "restaurant",
                "atm", "clothing", "pharmacy", "fuel", "gaming", "luxury"]

# Fraud rule thresholds (must match what we insert into fraud_rules)
THRESHOLD_HIGH_AMOUNT    = 5_000     # any single txn > this → high amount rule
THRESHOLD_HIGH_FREQUENCY = 5         # N+ txns within 10 minutes → velocity rule
RISK_SCORE_HIGH_AMOUNT   = 85
RISK_SCORE_VELOCITY      = 75
RISK_SCORE_MISMATCH      = 55
RISK_SCORE_FROZEN        = 95

# ──────────────────────────────────────────────
# ID counters (simple incrementing)
# ──────────────────────────────────────────────
_counters: dict[str, int] = {}

def next_id(name: str) -> int:
    _counters[name] = _counters.get(name, 0) + 1
    return _counters[name]


def hash_card(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def d(dt: date) -> str:
    return dt.strftime("%Y-%m-%d")


# ──────────────────────────────────────────────
# Data builders
# ──────────────────────────────────────────────

def build_customers(n: int) -> list[dict]:
    rows = []
    for _ in range(n):
        cid  = next_id("customer")
        rows.append(dict(
            customer_id  = cid,
            name         = fake.first_name(),
            surname      = fake.last_name(),
            birth_date   = d(fake.date_of_birth(minimum_age=18, maximum_age=75)),
            email        = f"user{cid}_{fake.unique.user_name()}@example.com",
            is_active    = random.random() > 0.05,
            country_code = random.choice(COUNTRIES),
            created_at   = ts(fake.date_time_between(start_date="-3y", end_date="-1m")),
        ))
    return rows


def build_accounts(customers: list[dict]) -> list[dict]:
    rows = []
    for c in customers:
        for _ in range(random.randint(1, ACCOUNTS_PER_CUSTOMER)):
            rows.append(dict(
                account_id     = next_id("account"),
                customer_id    = c["customer_id"],
                account_number = f"UA{fake.unique.bothify('??########')}",
                currency       = random.choice(CURRENCIES),
                balance        = round(random.uniform(100, 50_000), 2),
                status         = "ACTIVE",
                created_at     = ts(fake.date_time_between(
                                    start_date=c["created_at"], end_date="-2w")),
            ))
    return rows


def build_cards(accounts: list[dict]) -> list[dict]:
    rows = []
    for a in accounts:
        for _ in range(random.randint(1, CARDS_PER_ACCOUNT)):
            raw = fake.credit_card_number()
            rows.append(dict(
                card_id          = next_id("card"),
                account_id       = a["account_id"],
                card_number_hash = hash_card(raw),
                card_type        = random.choice(["VISA", "MASTERCARD", "AMEX"]),
                status           = "ACTIVE",
                expiration_date  = d(fake.date_between(start_date="+1m", end_date="+5y")),
            ))
    return rows


def build_fraud_rules() -> list[dict]:
    return [
        dict(rule_id=1, rule_name="HIGH_AMOUNT",
             rule_type="THRESHOLD",    threshold_value=THRESHOLD_HIGH_AMOUNT, is_active=True),
        dict(rule_id=2, rule_name="HIGH_FREQUENCY",
             rule_type="VELOCITY",     threshold_value=THRESHOLD_HIGH_FREQUENCY, is_active=True),
        dict(rule_id=3, rule_name="COUNTRY_MISMATCH",
             rule_type="GEO",          threshold_value=1,                     is_active=True),
        dict(rule_id=4, rule_name="FROZEN_CARD",
             rule_type="STATUS_CHECK", threshold_value=1,                     is_active=True),
    ]


def _txn(account_id, card_id, amount, currency, merchant_cat, merchant_country,
         status, risk_score, at: datetime, card_number_hash=None) -> dict:
    tid = next_id("txn")
    raw = card_number_hash or fake.credit_card_number()
    return dict(
        transaction_id   = tid,
        account_id       = account_id,
        card_id          = card_id,
        amount           = round(float(amount), 2),
        currency         = currency,
        merchant_category= merchant_cat,
        merchant_country = merchant_country,
        status           = status,
        card_number_hash = hash_card(str(tid) + raw),   # unique per txn
        risk_score       = risk_score,
        transaction_at   = ts(at),
        created_at       = ts(at + timedelta(seconds=random.randint(1, 10))),
    )


def build_normal_transactions(accounts: list[dict], cards: list[dict]) -> list[dict]:
    """Low-risk, approved baseline transactions."""
    card_by_account: dict[int, list[dict]] = {}
    for c in cards:
        card_by_account.setdefault(c["account_id"], []).append(c)

    rows = []
    active_accounts = [a for a in accounts if a["status"] == "ACTIVE"]
    for _ in range(NORMAL_TXN_COUNT):
        acc = random.choice(active_accounts)
        if acc["account_id"] not in card_by_account:
            continue
        card = random.choice(card_by_account[acc["account_id"]])
        at   = fake.date_time_between(start_date="-60d", end_date="-1d")
        rows.append(_txn(
            account_id       = acc["account_id"],
            card_id          = card["card_id"],
            amount           = round(random.uniform(5, 800), 2),
            currency         = acc["currency"],
            merchant_cat     = random.choice(MERCHANT_CAT),
            merchant_country = acc.get("_customer_country", "UA"),   # filled below
            status           = "APPROVED",
            risk_score       = random.randint(0, 25),
            at               = at,
        ))
    return rows


# ── Fraud scenario builders ───────────────────

def build_fraud_high_amount(accounts, cards) -> tuple[list[dict], list[dict]]:
    """Rule 1: single transaction amount > threshold."""
    txns, alerts = [], []
    card_by_acc = {c["account_id"]: c for c in cards}
    for acc in random.sample(accounts, min(FRAUD_HIGH_AMT_COUNT, len(accounts))):
        if acc["account_id"] not in card_by_acc:
            continue
        card = card_by_acc[acc["account_id"]]
        at   = fake.date_time_between(start_date="-30d", end_date="now")
        amount = round(random.uniform(THRESHOLD_HIGH_AMOUNT + 500, 50_000), 2)
        txn = _txn(
            account_id       = acc["account_id"],
            card_id          = card["card_id"],
            amount           = amount,
            currency         = acc["currency"],
            merchant_cat     = random.choice(["luxury", "electronics", "travel"]),
            merchant_country = random.choice(COUNTRIES),
            status           = random.choice(["FLAGGED", "DECLINED"]),
            risk_score       = RISK_SCORE_HIGH_AMOUNT,
            at               = at,
        )
        txns.append(txn)
        alerts.append(_alert(txn["transaction_id"], rule_id=1,
                             reason="Transaction amount exceeds high-amount threshold",
                             risk_score=RISK_SCORE_HIGH_AMOUNT))
    return txns, alerts


def build_fraud_velocity(accounts, cards) -> tuple[list[dict], list[dict]]:
    """Rule 2: N+ transactions on same card within 10 minutes."""
    txns, alerts = [], []
    card_by_acc = {c["account_id"]: c for c in cards}
    chosen = random.sample(accounts, min(FRAUD_VELOCITY_COUNT // THRESHOLD_HIGH_FREQUENCY,
                                         len(accounts)))
    for acc in chosen:
        if acc["account_id"] not in card_by_acc:
            continue
        card   = card_by_acc[acc["account_id"]]
        base_t = fake.date_time_between(start_date="-14d", end_date="now")
        burst  = THRESHOLD_HIGH_FREQUENCY + random.randint(1, 4)
        burst_txns = []
        for i in range(burst):
            at = base_t + timedelta(seconds=i * random.randint(30, 90))
            t  = _txn(
                account_id       = acc["account_id"],
                card_id          = card["card_id"],
                amount           = round(random.uniform(10, 500), 2),
                currency         = acc["currency"],
                merchant_cat     = "gaming",
                merchant_country = random.choice(COUNTRIES),
                status           = "FLAGGED",
                risk_score       = RISK_SCORE_VELOCITY,
                at               = at,
            )
            burst_txns.append(t)
        txns.extend(burst_txns)
        # One alert per burst (linked to first txn)
        alerts.append(_alert(burst_txns[0]["transaction_id"], rule_id=2,
                             reason=f"Velocity breach: {burst} txns within 10 minutes",
                             risk_score=RISK_SCORE_VELOCITY))
    return txns, alerts


def build_fraud_country_mismatch(customers, accounts, cards) -> tuple[list[dict], list[dict]]:
    """Rule 3: merchant_country ≠ customer country_code."""
    txns, alerts = [], []
    cust_by_id  = {c["customer_id"]: c for c in customers}
    acc_by_cust = {}
    for a in accounts:
        acc_by_cust.setdefault(a["customer_id"], []).append(a)
    card_by_acc = {c["account_id"]: c for c in cards}

    chosen_custs = random.sample(customers, min(FRAUD_MISMATCH_COUNT, len(customers)))
    for cust in chosen_custs:
        accs = acc_by_cust.get(cust["customer_id"], [])
        if not accs:
            continue
        acc  = random.choice(accs)
        if acc["account_id"] not in card_by_acc:
            continue
        card = card_by_acc[acc["account_id"]]
        home = cust["country_code"]
        foreign = random.choice([c for c in COUNTRIES if c != home])
        at = fake.date_time_between(start_date="-20d", end_date="now")
        t  = _txn(
            account_id       = acc["account_id"],
            card_id          = card["card_id"],
            amount           = round(random.uniform(50, 3_000), 2),
            currency         = acc["currency"],
            merchant_cat     = random.choice(["travel", "atm", "luxury"]),
            merchant_country = foreign,
            status           = "FLAGGED",
            risk_score       = RISK_SCORE_MISMATCH,
            at               = at,
        )
        txns.append(t)
        alerts.append(_alert(t["transaction_id"], rule_id=3,
                             reason=f"Merchant country {foreign} ≠ customer home {home}",
                             risk_score=RISK_SCORE_MISMATCH))
    return txns, alerts


def build_fraud_frozen_card(accounts, cards) -> tuple[list[dict], list[dict]]:
    """Rule 4: transaction on a frozen card / account."""
    txns, alerts = [], []
    # Pick some cards to freeze for this scenario
    frozen_cards = random.sample(cards, min(FRAUD_FROZEN_COUNT, len(cards)))
    acc_by_id = {a["account_id"]: a for a in accounts}

    for card in frozen_cards:
        card["status"] = "FROZEN"   # mutate in-place so INSERT reflects frozen state
        acc = acc_by_id.get(card["account_id"])
        if not acc:
            continue
        at = fake.date_time_between(start_date="-10d", end_date="now")
        t  = _txn(
            account_id       = acc["account_id"],
            card_id          = card["card_id"],
            amount           = round(random.uniform(50, 2_000), 2),
            currency         = acc["currency"],
            merchant_cat     = random.choice(MERCHANT_CAT),
            merchant_country = random.choice(COUNTRIES),
            status           = "DECLINED",
            risk_score       = RISK_SCORE_FROZEN,
            at               = at,
        )
        txns.append(t)
        alerts.append(_alert(t["transaction_id"], rule_id=4,
                             reason="Transaction attempted on frozen card",
                             risk_score=RISK_SCORE_FROZEN))
    return txns, alerts


def _alert(transaction_id: int, rule_id: int, reason: str, risk_score: int) -> dict:
    return dict(
        transaction_id = transaction_id,
        rule_id        = rule_id,
        reason         = reason,
        risk_score     = risk_score,
        alert_status   = "UNRESOLVED",
        changed_at     = ts(datetime.utcnow()),
    )


def build_audit_log(customers: list[dict], transactions: list[dict]) -> list[dict]:
    rows = []
    cust_ids = [c["customer_id"] for c in customers]
    for txn in random.sample(transactions, min(30, len(transactions))):
        cid = random.choice(cust_ids)
        rows.append(dict(
            customer_id = cid,
            table_name  = "transactions",
            operation   = "UPDATE",
            old_value   = json.dumps({"status": "PENDING"}),
            new_value   = json.dumps({"status": txn["status"],
                                      "risk_score": txn["risk_score"]}),
            changed_at  = txn["created_at"],
        ))
    return rows


def build_txn_status_history(transactions: list[dict]) -> list[dict]:
    rows = []
    for txn in transactions:
        if txn["status"] != "PENDING":
            rows.append(dict(
                transaction_id = txn["transaction_id"],
                old_status     = "PENDING",
                new_status     = txn["status"],
                changed_at     = txn["created_at"],
                changed_by     = "SYS",
            ))
    return rows


# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────

def insert(cur, table: str, rows: list[dict], *, dry_run: bool = False) -> None:
    if not rows:
        return
    cols   = list(rows[0].keys())
    values = [[r[c] for c in cols] for r in rows]
    sql    = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
              f"ON CONFLICT DO NOTHING")
    if dry_run:
        print(f"-- {table}: {len(rows)} rows")
        print(f"   {sql[:120]}...\n")
        return
    execute_values(cur, sql, values)
    print(f"  ✓  {table:<35} {len(rows):>5} rows")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def run(conn_params: dict, dry_run: bool) -> None:
    print("\n══════════════════════════════════════════")
    print("  Banking Fraud Simulation — Data Ingestion")
    print("══════════════════════════════════════════\n")

    # ── Build all data ────────────────────────
    print("● Generating data …")

    customers = build_customers(NUM_CUSTOMERS)
    accounts  = build_accounts(customers)

    # Attach customer country to accounts for geo-mismatch logic
    cust_country = {c["customer_id"]: c["country_code"] for c in customers}
    for a in accounts:
        a["_customer_country"] = cust_country[a["customer_id"]]

    cards       = build_cards(accounts)
    fraud_rules = build_fraud_rules()

    # Normal transactions
    txns_normal = build_normal_transactions(accounts, cards)

    # Fraud scenarios
    txns_hi_amt,  alerts_hi_amt  = build_fraud_high_amount(accounts, cards)
    txns_vel,     alerts_vel     = build_fraud_velocity(accounts, cards)
    txns_mismatch,alerts_mismatch= build_fraud_country_mismatch(customers, accounts, cards)
    txns_frozen,  alerts_frozen  = build_fraud_frozen_card(accounts, cards)

    all_txns   = (txns_normal + txns_hi_amt + txns_vel +
                  txns_mismatch + txns_frozen)
    all_alerts = alerts_hi_amt + alerts_vel + alerts_mismatch + alerts_frozen

    audit_log    = build_audit_log(customers, all_txns)
    txn_history  = build_txn_status_history(all_txns)

    # Strip helper keys not in schema
    for a in accounts:
        a.pop("_customer_country", None)

    print(f"  customers            : {len(customers)}")
    print(f"  accounts             : {len(accounts)}")
    print(f"  cards                : {len(cards)}")
    print(f"  fraud_rules          : {len(fraud_rules)}")
    print(f"  transactions (normal): {len(txns_normal)}")
    print(f"  transactions (fraud) : {len(all_txns) - len(txns_normal)}")
    print(f"    ↳ HIGH_AMOUNT      : {len(txns_hi_amt)}")
    print(f"    ↳ HIGH_FREQUENCY   : {len(txns_vel)}")
    print(f"    ↳ COUNTRY_MISMATCH : {len(txns_mismatch)}")
    print(f"    ↳ FROZEN_CARD      : {len(txns_frozen)}")
    print(f"  fraud_alerts         : {len(all_alerts)}")
    print(f"  audit_log entries    : {len(audit_log)}")
    print(f"  txn_status_history   : {len(txn_history)}")

    if dry_run:
        print("\n[DRY-RUN] No DB writes — printing statement previews:\n")
        cur = None
    else:
        print("\n● Connecting to database …")
        conn = psycopg2.connect(**conn_params)
        conn.autocommit = False
        cur = conn.cursor()
        print("  Connected.\n● Inserting …\n")

    try:
        insert(cur, "customers",                customers,    dry_run=dry_run)
        insert(cur, "accounts",                 accounts,     dry_run=dry_run)
        insert(cur, "cards",                    cards,        dry_run=dry_run)
        insert(cur, "fraud_rules",              fraud_rules,  dry_run=dry_run)
        insert(cur, "transactions",             all_txns,     dry_run=dry_run)
        insert(cur, "fraud_alerts",             all_alerts,   dry_run=dry_run)
        insert(cur, "audit_log",                audit_log,    dry_run=dry_run)
        insert(cur, "transaction_status_history", txn_history, dry_run=dry_run)

        if not dry_run:
            conn.commit()
            print("\n✔  All data committed successfully.")
    except Exception as exc:
        if not dry_run:
            conn.rollback()
        print(f"\n✘  Error: {exc}", file=sys.stderr)
        raise
    finally:
        if not dry_run:
            cur.close()
            conn.close()

    print("\n══════════════════════════════════════════")
    print("  Fraud scenario summary")
    print("══════════════════════════════════════════")
    print(f"  Rule 1 HIGH_AMOUNT     → {len(alerts_hi_amt)} alert(s), "
          f"amount > {THRESHOLD_HIGH_AMOUNT}")
    print(f"  Rule 2 HIGH_FREQUENCY  → {len(alerts_vel)} alert(s), "
          f"{THRESHOLD_HIGH_FREQUENCY}+ txns / 10 min")
    print(f"  Rule 3 COUNTRY_MISMATCH→ {len(alerts_mismatch)} alert(s), "
          f"foreign merchant vs home country")
    print(f"  Rule 4 FROZEN_CARD     → {len(alerts_frozen)} alert(s), "
          f"txn on frozen card")
    print()


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Banking fraud data ingestion")
    p.add_argument("--host",     default="localhost")
    p.add_argument("--port",     default=5432, type=int)
    p.add_argument("--dbname",   default="banking")
    p.add_argument("--user",     default="postgres")
    p.add_argument("--password", default="")
    p.add_argument("--dry-run",  action="store_true",
                   help="Print SQL previews without connecting to DB")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    conn_params = dict(
        host     = args.host,
        port     = args.port,
        dbname   = args.dbname,
        user     = args.user,
        password = args.password,
    )
    run(conn_params, dry_run=args.dry_run)