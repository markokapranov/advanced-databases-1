CREATE OR REPLACE FUNCTION calc_and_flag_transaction()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
END;
$$;


CREATE OR REPLACE TRIGGER trg_flagging_transactions
BEFORE INSERT OR UPDATE ON transactions
FOR EACH ROW
EXECUTE FUNCTION calc_and_flag_transaction();

--

CREATE OR REPLACE FUNCTION fraud_creation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
END;
$$;

CREATE OR REPLACE TRIGGER trg_fraud_alert_creation
BEFORE INSERT OR UPDATE ON transactions
FOR EACH ROW
EXECUTE FUNCTION fraud_creation();

--

CREATE OR REPLACE FUNCTION update_balance(p_transaction_id BIGINT)
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_status VARCHAR;
    v_amount DECIMAL;
    v_balance DECIMAL;
    v_account_id BIGINT;

BEGIN
    SELECT status, amount INTO v_status, v_amount
    FROM transactions
    WHERE transaction_id = p_transaction_id;

    SELECT balance, account_id into v_balance, v_account_id
    FROM accounts
    JOIN transactions using (account_id)
    WHERE transaction_id = p_transaction_id;

    IF v_status = 'APPROVED' THEN
    UPDATE accounts SET balance = balance - v_amount
    WHERE account_id= v_account_id;
    END IF;
END;
$$;


CREATE OR REPLACE TRIGGER trg_auto_balance_update
AFTER UPDATE ON transactions
FOR EACH ROW
EXECUTE FUNCTION update_balance(transaction_id );

--

CREATE OR REPLACE FUNCTION transaction_history()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO transaction_status_history (
    transaction_id,
    old_status,
    new_status,
    changed_at,changed_by)
    VALUES (NEW.transaction_id, OLD.status, NEW.status, NOW(), 'SYS');
    RETURN NEW;
END;
$$;


CREATE OR REPLACE TRIGGER trg_history_change
AFTER UPDATE ON transactions
FOR EACH ROW
EXECUTE FUNCTION transaction_history();


CREATE OR REPLACE FUNCTION deletion_protection()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
END;
$$;


CREATE OR REPLACE TRIGGER trg_deletion_protection
BEFORE INSERT OR UPDATE ON transactions
FOR EACH ROW
EXECUTE FUNCTION deletion_protection();
