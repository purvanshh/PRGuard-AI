# ruleid: no-unsafe-eval
result = eval(user_input)

# ruleid: no-unsafe-eval
exec(compile(source, "x.py", "exec"))

# ok: no-unsafe-eval
result = ast.literal_eval(user_input)

# ok: no-unsafe-eval
result = int(user_input)