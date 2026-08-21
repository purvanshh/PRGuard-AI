package main

import "database/sql"

func fetchByID(db *sql.DB, id string) {
    // ruleid: no-sql-concat
    db.Query("SELECT * FROM users WHERE id = " + id)

    // ruleid: no-sql-concat
    db.Query("UPDATE accounts SET balance = " + amount)

    // ok: no-sql-concat
    db.Query("SELECT * FROM users WHERE id = ?", id)

    // ok: no-sql-concat
    rows, err := db.Query("SELECT * FROM users WHERE id = ?", id)
    _ = rows
    _ = err
}