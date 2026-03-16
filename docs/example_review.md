## Example PRGuard AI Review

Below is an example of the kind of Markdown review PRGuard AI posts on a pull request.

```markdown
## PRGuard AI Review

**Confidence Score:** 0.82

### Style
- `LOW` (line 23): Line exceeds 120 characters.
- `MEDIUM` (line 42): Tab character used for indentation instead of spaces.

### Logic
- `MEDIUM` (line 87): Possible missing `else` branch; control flow may skip error handling.
- `LOW` (line 105): TODO present in newly added code.

### Security
- `HIGH` (line 132): Potential SQL injection pattern detected in string-concatenated query.

### Disagreement Summary
- security reports high-severity issues while style does not.
```

For lines with clear file/line context, PRGuard AI may also post **inline comments** on the PR, for example:

- On `app/services/user_service.py:132`:

> ⚠ PRGuard AI  
> Issue: Potential SQL injection pattern detected in string-concatenated query.  
> Evidence: `query = "SELECT * FROM users WHERE name = '" + name + "'"`  
> Consider using parameterized queries instead of string concatenation.

The dashboard replay view (`/review/{pr_id}`) will show:

- Per-agent timelines and execution durations.
- Each agent’s issue list, severity, and confidence.
- The final arbitrated confidence score.

