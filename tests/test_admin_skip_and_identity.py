"""Admin "skip first-login change" option + sidebar signed-in identity / logout.

The skip option is tested at the DB layer (create_user_with_password with
force_password_change). The sidebar identity is checked at source/AST level
because dashboard.py runs st.* at import.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.database.db as db_mod  # noqa: E402
from src.auth import verify_password  # noqa: E402
from src.database.db import Base  # noqa: E402
from src.database.models import User  # noqa: E402


@pytest.fixture
def patched_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    orig_e, orig_f = db_mod._engine, db_mod._SessionFactory
    db_mod._engine, db_mod._SessionFactory = engine, Session
    try:
        yield Session
    finally:
        db_mod._engine, db_mod._SessionFactory = orig_e, orig_f


# ---- Admin skip-forced-change option --------------------------------------

def test_default_create_forces_first_login_change(patched_db):
    from src.delivery.views.admin import create_user_with_password
    uid = create_user_with_password("A", "a@x.com", "permpass1", role="viewer")
    with patched_db() as s:
        u = s.get(User, uid)
        assert u.must_change_password == 1
        assert verify_password("permpass1", u.password_hash)


def test_skip_keeps_permanent_password(patched_db):
    from src.delivery.views.admin import create_user_with_password
    uid = create_user_with_password(
        "B", "b@x.com", "permpass1", role="viewer", force_password_change=False,
    )
    with patched_db() as s:
        u = s.get(User, uid)
        assert u.must_change_password == 0  # NOT forced to change
        assert verify_password("permpass1", u.password_hash)  # password still works


def test_force_true_explicit_still_forces(patched_db):
    from src.delivery.views.admin import create_user_with_password
    uid = create_user_with_password(
        "C", "c@x.com", "permpass1", force_password_change=True,
    )
    with patched_db() as s:
        assert s.get(User, uid).must_change_password == 1


# ---- Sidebar signed-in identity + logout (source/AST) ---------------------

DASH_SRC = (ROOT / "src" / "delivery" / "dashboard.py").read_text()


def test_sidebar_identity_defined_escaped_and_wired():
    funcs = {n.name for n in ast.walk(ast.parse(DASH_SRC))
             if isinstance(n, ast.FunctionDef)}
    assert "_render_sidebar_identity" in funcs
    # render_sidebar must actually call it
    assert "_render_sidebar_identity()" in DASH_SRC
    # user-supplied name must be escaped; logout must be wired
    assert "html.escape" in DASH_SRC
    assert "clear_session_user" in DASH_SRC
    assert 'st.button("Log out"' in DASH_SRC
    compile(DASH_SRC, "dashboard.py", "exec")
