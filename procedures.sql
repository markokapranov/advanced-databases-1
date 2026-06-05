
CREATE PROCEDURE create_fraud_alert(p_transaction_id BIGINT, p_risk_score INT)
LANGUAGE plpgsql
AS $$
DECLARE
    v_broken_ids BIGINT[];
    v_reason VARCHAR;
BEGIN
    v_broken_ids := get_triggered_ids(p_transaction_id);

    INSERT INTO fraud_alerts
    with rule_ids as (
        SELECT p_transaction_id as transaction_id,
               id as rule_id
        FROM UNNEST(v_broken_ids) as t(id)
    ),
    new_id as (
        SELECT 1 + max(alert_id)
        FROM fraud_alerts
    )
    SELECT (SELECT * FROM new_id) as alert_id,
           r.transaction_id as transaction_id,
           f.rule_id as rule_id,
           f.rule_name as reason,
           p_risk_score as risk_score,
           'UNRESOLVED' as alert_status,
           now() as changed_at

    FROM rule_ids r
    JOIN fraud_rules f on f.rule_id = r.rule_id;

END;
$$;


CREATE PROCEDURE freeze_account(p_account_id BIGINT)
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE accounts SET status = 'FROZEN' WHERE account_id = p_account_id;
    UPDATE cards SET status = 'FROZEN' WHERE account_id = p_account_id;
END;
$$;


CREATE PROCEDURE approve_pending_transactions()
LANGUAGE plpgsql
AS $$
BEGIN





END;
$$;


CREATE PROCEDURE refresh_fraud_dashboard()
LANGUAGE plpgsql
AS $$
BEGIN
END;
$$;



CREATE PROCEDURE process_transaction(p_transaction_id BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
    v_risk_score INT ;
    v_status VARCHAR ;
    v_balance DECIMAL;
    v_amount DECIMAL;
BEGIN
    SELECT calculate_transaction_risk_score(p_transaction_id)
    INTO v_risk_score;

    SELECT amount
    INTO v_amount
    FROM transactions
    WHERE transaction_id = p_transaction_id;

    v_status := CASE
    WHEN v_risk_score <= 29 THEN 'APPROVED'
    WHEN v_risk_score >= 30 and v_risk_score <= 69 THEN 'FLAGGED'
    ELSE 'DECLINED'
    END;

    IF v_status in ('FLAGGED', 'DECLINED') THEN
        call create_fraud_alert(p_transaction_id, v_risk_score);
    END IF;


    SELECT balance into v_balance
    FROM accounts
    JOIN transactions using (account_id)
    WHERE transaction_id = p_transaction_id;

    IF v_balance - v_amount < 0 THEN
        v_status := 'DECLINED';
    end if;


    UPDATE transactions set status = v_status, risk_score = v_risk_score
    WHERE transaction_id = p_transaction_id;

END;

$$;


-----


CREATE PROCEDURE transfer_money(p_transaction_id BIGINT)
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

    UPDATE accounts SET balance = balance - v_amount
    WHERE account_id= v_account_id;

END;

$$;