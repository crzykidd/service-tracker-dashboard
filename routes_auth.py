"""Authentication and user-management routes.

Owns the `auth` blueprint: /login, /logout, and admin user CRUD
endpoints. Also home to:

- `is_admin_required` — shared decorator imported by other route
  modules that gate admin-only endpoints. Lives here because it's
  conceptually part of the auth surface (it reads `current_user` and
  delegates to `login_manager.unauthorized()`).
- `@login_manager.user_loader` registration — Flask-Login requires
  exactly one user_loader and it has to know how to materialize a
  User from a session id. Co-locating with the auth routes keeps the
  three things that depend on the User model (login, user_loader,
  admin gate) in one file.
"""

import logging
from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user
from werkzeug.security import check_password_hash

from extensions import db, login_manager
from models import User

auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)


DEFAULT_ADMIN_PASSWORD = "changeme123"


def refresh_default_password_flag(app):
    """Recompute whether `admin` still uses the default password.

    Hashing is slow, so this runs at startup and after password changes and
    the result is cached on app.config rather than computed per request.
    """
    in_use = False
    try:
        with app.app_context():
            admin = User.query.filter_by(username="admin").first()
            in_use = bool(admin and admin.check_password(DEFAULT_ADMIN_PASSWORD))
    except Exception as e:  # DB not migrated/created yet
        logger.debug(f"Could not check default admin password: {e}")
    app.config["DEFAULT_ADMIN_PASSWORD_IN_USE"] = in_use
    if in_use:
        logger.warning(
            "⚠️ The 'admin' user still has the default password. "
            "Change it under Settings → Users."
        )
    return in_use


def _render_settings_for(**kwargs):
    """Re-render Settings from here; routes_dashboard imports this module, so import lazily."""
    from routes_dashboard import render_settings_for

    return render_settings_for(**kwargs)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def is_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)  # Forbidden
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()

        if user and user.is_active and check_password_hash(user.password_hash, password):
            login_user(user)  # <-- This is the key line you’re missing
            session.permanent = True
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard.dashboard"))
        else:
            flash("Invalid username or password.", "error")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You’ve been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/settings/users/<int:user_id>/set_password", methods=["POST"])
@is_admin_required
def set_user_password(user_id):
    new_password = request.form.get("new_password", "").strip()
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found", "danger")
        return redirect(url_for("dashboard.settings", section="users"))
    if not new_password or len(new_password) < 6:
        # Re-render with the set-password dialog open (the password is never echoed).
        flash("Password must be at least 6 characters", "danger")
        return _render_settings_for(
            section="users", open_modal="password-modal", status=400, password_user=user)

    user.set_password(new_password)
    db.session.commit()
    refresh_default_password_flag(current_app._get_current_object())
    flash(f"Password updated for {user.username}", "success")
    return redirect(url_for("dashboard.settings", section="users"))


@auth_bp.route("/add_user", methods=["POST"])
@login_required
@is_admin_required
def add_user():
    username = request.form.get("username")
    email = request.form.get("email")
    password = request.form.get("password")
    is_admin = request.form.get("is_admin") == "on"

    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash("User already exists with this username or email", "danger")
        # Re-render with the Add user dialog open; username and email are kept, the password is not.
        return _render_settings_for(
            section="users", open_modal="user-modal", status=400,
            user_form={"username": username or "", "email": email or "", "is_admin": is_admin})

    user = User(username=username, email=email, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    flash(f"✅ User '{username}' created", "success")
    return redirect(url_for("dashboard.settings", section="users"))


@auth_bp.route("/delete_user", methods=["POST"])
@login_required
@is_admin_required
def delete_user():
    user_id = request.form.get("user_id")
    user = db.session.get(User, user_id)
    if user and not user.is_admin:
        db.session.delete(user)
        db.session.commit()
        flash(f"🗑️ User {user.username} deleted", "success")
    else:
        flash("❌ Cannot delete admin or invalid user", "danger")
    return redirect(url_for("dashboard.settings", section="users"))
