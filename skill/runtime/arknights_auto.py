"""Compatibility name for the ONE packaged runtime; never search an author's PC."""
import sys
import arknights_daily_runtime_v12 as _runtime

if __name__ == '__main__':
    from ark import main
    raise SystemExit(main())
else:
    sys.modules[__name__] = _runtime
