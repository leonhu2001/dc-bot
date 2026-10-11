from pathlib import Path


path = Path("scripts/_apply_loyalty_edit_reconcile.py")
text = path.read_text(encoding="utf-8")
old = '''            aggregate = buckets.setdefault(scope, dict(bucket))
            aggregate["paid_units"] = float(aggregate.get("paid_units") or 0) + paid_units
'''
new = '''            aggregate = buckets.get(scope)
            if aggregate is None:
                aggregate = dict(bucket)
                aggregate["paid_units"] = 0.0
                buckets[scope] = aggregate
            aggregate["paid_units"] = float(aggregate.get("paid_units") or 0) + paid_units
'''
if text.count(old) != 1:
    raise SystemExit(f"bucket fix expected one match, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
exec(code, {"__name__": "__main__", "__file__": str(path)})
