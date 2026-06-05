CREATE FUNCTION get_customer_age(in customer_id_p BIGINT, out p_age INT)
RETURNS INT
LANGUAGE plpgsql AS $$
BEGIN
    SELECT extract(YEAR FROM now() - birth_date::timestamp)  FROM customers
    WHERE customer_id = customer_id_p INTO p_age;
    RETURN;
END;
$$;


CREATE FUNCTION is_country_high_risk(in p_country_code VARCHAR,
 out p_answer BOOLEAN)
RETURNS BOOLEAN
LANGUAGE plpgsql AS $$
BEGIN
        SELECT AVG(risk_score) > 50
        FROM customers c
        JOIN accounts a on c.customer_id = a.customer_id
        JOIN transactions t on t.account_id = t.account_id
        where c.country_code = p_country_code INTO p_answer;
        RETURN;
END;
$$;



CREATE FUNCTION mask_card( in p_cardnumber BIGINT,
                           out p_mask VARCHAR )
RETURNS VARCHAR
LANGUAGE plpgsql AS $$
BEGIN
        SELECT hashtext(p_cardnumber::VARCHAR) INTO p_mask;
END;
$$;

CREATE FUNCTION calculate_daily_customer_volume(in p_customer_id BIGINT, in p_target_date DATE, out p_volume INT)
RETURNS INT
LANGUAGE plpgsql AS $$
BEGIN
    SELECT COUNT(*)
    from customers c
    join accounts a using (customer_id)
    join transactions t using (account_id)
    WHERE c.customer_id = p_customer_id
    AND t.transaction_at::DATE == p_target_date ;

END;
$$;

CREATE FUNCTION calculate_transaction_risk_score( in p_transaction_id BIGINT,
                                                  out p_score INT)
LANGUAGE plpgsql AS $$
DECLARE
    v_score         INT := 0;
    v_amount        DECIMAL;
    v_merchant_ctry VARCHAR;
    v_card_status   VARCHAR;
    v_account_status VARCHAR;
    v_cust_country  VARCHAR;
    v_cust_created  TIMESTAMP;
    v_is_active     BOOLEAN;
    v_card_id       BIGINT;
    v_account_id    BIGINT;
    v_tx_count_1h   INT;
    v_tx_account_count INT;
BEGIN
    SELECT
        t.amount, t.merchant_country,
        t.card_id, t.account_id,
        c.status,
        a.status,
        cu.country_code, cu.created_at, cu.is_active
    INTO
        v_amount, v_merchant_ctry,
        v_card_id, v_account_id,
        v_card_status,
        v_account_status,
        v_cust_country, v_cust_created, v_is_active
    FROM transactions t
    JOIN cards    c  ON c.card_id    = t.card_id
    JOIN accounts a  ON a.account_id = t.account_id
    JOIN customers cu ON cu.customer_id = a.customer_id
    WHERE t.transaction_id = p_transaction_id;

    v_score := v_score + CASE
        WHEN v_amount > 50000 THEN 35
        WHEN v_amount > 10000 THEN 25
        WHEN v_amount > 5000  THEN 15
        WHEN v_amount > 1000  THEN 8
        ELSE 0
    END;

    IF v_merchant_ctry <> v_cust_country THEN
        v_score := v_score + 5;
    END IF;


    SELECT COUNT(*) INTO v_tx_count_1h
    FROM transactions
    WHERE card_id = v_card_id
      AND transaction_at >= NOW() - INTERVAL '1 hours'
      AND transaction_id != p_transaction_id;

    v_score := v_score + CASE
        WHEN v_tx_count_1h >= 10 THEN 20
        WHEN v_tx_count_1h >= 5  THEN 10
        WHEN v_tx_count_1h >= 2  THEN 5
        ELSE 0
    END;

    SELECT COUNT(*) INTO v_tx_account_count
    FROM transactions
    WHERE card_id = v_account_id
      AND transaction_at >= NOW() - INTERVAL '12 hours'
      AND transaction_id != p_transaction_id;

    v_score := v_score + CASE
        WHEN v_tx_account_count >= 30 THEN 20
        WHEN v_tx_account_count >= 20  THEN 10
        WHEN v_tx_account_count >= 10  THEN 5
        ELSE 0
    END;




    IF v_cust_created > NOW() - INTERVAL '30 days' AND v_amount > 1500 THEN
        v_score := v_score + 12;
    END IF;

    IF v_is_active = FALSE THEN
        v_score := v_score + 30;
    END IF;

    p_score := LEAST(v_score, 100);

    RETURN;
END;
$$;


CREATE FUNCTION get_triggered_ids( in p_transaction_id BIGINT)
RETURNS BIGINT[]
LANGUAGE plpgsql AS $$
DECLARE
    v_amount        DECIMAL;
    v_merchant_ctry VARCHAR;
    v_card_status   VARCHAR;
    v_account_status VARCHAR;
    v_cust_country  VARCHAR;
    v_cust_created  TIMESTAMP;
    v_is_active     BOOLEAN;
    v_card_id       BIGINT;
    v_account_id    BIGINT;
    v_tx_count_1h   INT;
    v_tx_account_count INT;
    v_id_array BIGINT[];
BEGIN
    SELECT
        t.amount, t.merchant_country,
        t.card_id, t.account_id,
        c.status,
        a.status,
        cu.country_code, cu.created_at, cu.is_active
    INTO
        v_amount, v_merchant_ctry,
        v_card_id, v_account_id,
        v_card_status,
        v_account_status,
        v_cust_country, v_cust_created, v_is_active
    FROM transactions t
    JOIN cards    c  ON c.card_id    = t.card_id
    JOIN accounts a  ON a.account_id = t.account_id
    JOIN customers cu ON cu.customer_id = a.customer_id
    WHERE t.transaction_id = p_transaction_id;

    IF v_amount > 1000 THEN
        v_id_array := array_append(v_id_array, 1);
    END IF;

    IF v_merchant_ctry <> v_cust_country THEN
        v_id_array := array_append(v_id_array, 2);
    END IF;


    SELECT COUNT(*) INTO v_tx_count_1h
    FROM transactions
    WHERE card_id = v_card_id
      AND transaction_at >= NOW() - INTERVAL '1 hours'
      AND transaction_id != p_transaction_id;

    IF v_tx_count_1h > 5 THEN
         v_id_array := array_append(v_id_array, 3);
    END IF;

    SELECT COUNT(*) INTO v_tx_account_count
    FROM transactions
    WHERE card_id = v_account_id
      AND transaction_at >= NOW() - INTERVAL '12 hours'
      AND transaction_id != p_transaction_id;

    IF v_tx_count_1h >= 20 THEN
         v_id_array := array_append(v_id_array, 4);
    END IF;




    IF v_cust_created > NOW() - INTERVAL '30 days' AND v_amount > 1500 THEN
         v_id_array := array_append(v_id_array, 5);
    END IF;

    IF v_is_active = FALSE THEN
         v_id_array := array_append(v_id_array, 6);
    END IF;


    RETURN v_id_array;
END;
$$;