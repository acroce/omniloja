SELECT NOW() AS collected_at;

SELECT
    ID,
    USER,
    HOST,
    DB,
    COMMAND,
    TIME,
    STATE,
    INFO
FROM information_schema.processlist
WHERE DB = 'pleno'
ORDER BY TIME DESC;

SELECT
    trx_id,
    trx_state,
    trx_started,
    trx_wait_started,
    trx_mysql_thread_id,
    trx_query
FROM information_schema.innodb_trx
ORDER BY trx_started;

SELECT
    requesting_trx_id,
    requested_lock_id,
    blocking_trx_id,
    blocking_lock_id
FROM information_schema.innodb_lock_waits;

SELECT
    lock_id,
    lock_trx_id,
    lock_mode,
    lock_type,
    lock_table,
    lock_index,
    lock_space,
    lock_page,
    lock_rec,
    lock_data
FROM information_schema.innodb_locks;

SHOW ENGINE INNODB STATUS;
