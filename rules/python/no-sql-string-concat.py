# ruleid: no-sql-string-concat
cursor.execute("SELECT * FROM users WHERE id = " + user_id)

# ruleid: no-sql-string-concat
db.query("UPDATE accounts SET balance = " + str(amount) + " WHERE id = " + account_id)

# ruleid: no-sql-string-concat
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")

# ok: no-sql-string-concat
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# ok: no-sql-string-concat
db.query("SELECT * FROM users WHERE id = :uid", {"uid": user_id})