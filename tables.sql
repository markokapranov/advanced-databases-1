CREATE TABLE customers (
    customer_id BIGINT PRIMARY KEY ,
    name VARCHAR,
    surname VARCHAR,
    birth_date DATE,
    email VARCHAR UNIQUE,
    is_active BOOLEAN,
    country_code VARCHAR,
    created_at TIMESTAMP
);

CREATE TABLE accounts (
    account_id BIGINT PRIMARY KEY,
    customer_id BIGINT,
    account_number VARCHAR UNIQUE,
    currency VARCHAR CHECK (currency IN ('UAH', 'USD', 'EUR')),
    balance DECIMAL CHECK (balance >= 0),
    status VARCHAR CHECK (status IN ('ACTIVE', 'FROZEN')),
    created_at TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE cards (
    card_id BIGINT PRIMARY KEY,
    account_id BIGINT,
    card_number_hash VARCHAR UNIQUE,
    card_type VARCHAR,
    status VARCHAR CHECK (status IN ('ACTIVE', 'FROZEN')),
    expiration_date DATE,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE TABLE audit_log (
    audit_id SERIAL PRIMARY KEY,
    customer_id BIGINT,
    table_name VARCHAR,
    operation VARCHAR,
    old_value JSON,
    new_value JSON,
    changed_at TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);


CREATE TABLE transactions (
    transaction_id BIGINT PRIMARY KEY,
    account_id BIGINT,
    card_id BIGINT,
    amount DECIMAL CHECK (amount > 0),
    currency VARCHAR CHECK (currency IN ('UAH', 'USD', 'EUR')),
    merchant_category VARCHAR,
    merchant_country VARCHAR,
    status VARCHAR CHECK( status IN ('PENDING', 'APPROVED', 'DECLINED', 'FLAGGED')),
    card_number_hash VARCHAR UNIQUE,
    risk_score INT,
    transaction_at TIMESTAMP,
    created_at TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id),
    FOREIGN KEY (card_id) REFERENCES cards(card_id)
);


CREATE TABLE fraud_rules(
    rule_id BIGINT PRIMARY KEY,
    rule_name VARCHAR,
    rule_type VARCHAR,
    threshold_value INT,
    is_active BOOLEAN
);

CREATE TABLE transaction_status_history (
    history_id SERIAL PRIMARY KEY ,
    transaction_id BIGINT,
    old_status VARCHAR,
    new_status VARCHAR,
    changed_at TIMESTAMP,
    changed_by VARCHAR,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);


CREATE TABLE fraud_alerts (
    alert_id SERIAL PRIMARY KEY,
    transaction_id BIGINT,
    rule_id BIGINT,
    reason VARCHAR,
    risk_score INT,
    alert_status VARCHAR,
    changed_at TIMESTAMP,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id),
    FOREIGN KEY (rule_id) REFERENCES fraud_rules(rule_id)
);

