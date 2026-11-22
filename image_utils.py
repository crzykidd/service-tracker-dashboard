import inspect
import os
import re
from datetime import datetime

import requests

from image_ref import parse as parse_image_ref

_ICON_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
MAX_ICON_NAME_LENGTH = 100


def safe_icon_filename(name):
    """Return a safe '<name>.svg' icon filename, or None if `name` is unsafe.

    Lowercases, strips one trailing '.svg', and accepts only
    [a-z0-9][a-z0-9._-]* (no slashes, no '..'). The result is at most
    MAX_ICON_NAME_LENGTH characters including '.svg' (the DB column limit).
    """
    if not isinstance(name, str):
        return None
    name = name.strip().lower()
    if name.endswith(".svg"):
        name = name[:-4]
    if not name or len(name) + 4 > MAX_ICON_NAME_LENGTH:
        return None
    if ".." in name or not _ICON_NAME_RE.match(name):
        return None
    return f"{name}.svg"


def icon_path_in_dir(image_dir, filename):
    """Join `filename` onto `image_dir`; return the path only if it stays inside it."""
    base = os.path.realpath(image_dir)
    path = os.path.realpath(os.path.join(base, filename))
    if not path.startswith(base + os.sep):
        return None
    return path


def fetch_icon_if_missing(name, image_dir, logger, debug=False, source_hint=None):
    if not name:
        return None

    # Get calling function or route
    stack = inspect.stack()
    caller_function = stack[1].function if len(stack) > 1 else "unknown"

    filename = safe_icon_filename(name)
    local_path = icon_path_in_dir(image_dir, filename) if filename else None
    if not local_path:
        if logger:
            logger.warning(f"Skipping icon with unsafe name: {name!r}")
        return None

    if os.path.exists(local_path):
        return filename

    sources = [
        (f"https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/{filename}", "jsDelivr CDN"),
        (f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{filename}", "GitHub Raw")
    ]

    label_hint = f" - {source_hint}" if source_hint else ""
    caller_hint = f" [caller: {caller_function}]"

    for url, label in sources:
        try:
            logger.info(f"🌐 Trying {label} for icon: {filename}{label_hint}{caller_hint}")
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                with open(local_path, 'wb') as f:
                    f.write(response.content)
                logger.info(f"✅ Downloaded icon '{filename}' from {label}{label_hint}{caller_hint}")
                return filename
            else:
                msg = f"{label} failed for {filename}{label_hint} — HTTP {response.status_code}{caller_hint}"
                if debug:
                    logger.debug(f"❌ {msg} | URL: {url}")
                else:
                    logger.warning(f"⚠️ {msg}")
        except Exception as e:
            msg = f"Exception while downloading {filename}{label_hint} from {label}: {e}{caller_hint}"
            if debug:
                logger.debug(f"❌ {msg} | URL: {url}")
            else:
                logger.error(f"❌ {msg}")

    logger.error(f"🛑 All sources failed for icon: {filename}{label_hint}{caller_hint}")
    return None


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == 'true'
    return None


def resolve_image_metadata(
    image_raw=None,
    image_icon_override=None,
    fallback_name=None,
    image_dir=None,
    failed_icon_cache=None,
    retry_interval=None,
    logger=None,
    debug=False
):
    registry = owner = img_name = tag = image_ref = None

    parsed = parse_image_ref(image_raw) if image_raw else None
    if parsed:
        # Docker Hub keeps the legacy shape (registry NULL, no "library" owner) so
        # existing entries display and link as before; the canonical string is image_ref.
        registry = None if parsed.is_docker_hub else parsed.registry
        owner = parsed.owner
        if parsed.is_docker_hub and owner == "library":
            owner = None
        img_name = parsed.name
        tag = parsed.tag
        image_ref = parsed.canonical
    elif fallback_name and not image_raw:
        img_name = fallback_name

    icon_source_name = img_name or fallback_name
    image_icon = image_icon_override

    if not image_icon and icon_source_name:
        image_icon = fetch_icon_if_missing(
            icon_source_name,
            image_dir,
            logger,
            debug=debug,
            source_hint=fallback_name
        )
    elif image_icon:
        safe_name = safe_icon_filename(image_icon)
        icon_path = icon_path_in_dir(image_dir, safe_name) if safe_name else None
        if not icon_path:
            logger.warning(f"Ignoring image_icon with unsafe name: {image_icon!r}")
            return {
                "registry": registry,
                "owner": owner,
                "image_name": img_name,
                "image_tag": tag,
                "image_icon": None,
                "image_ref": image_ref,
            }
        image_icon = safe_name
        now = datetime.now()
        last_fail = failed_icon_cache.get(image_icon)

        if not os.path.exists(icon_path) and (not last_fail or now - last_fail > retry_interval):
            try:
                icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{image_icon}"
                response = requests.get(icon_url, timeout=5)
                if response.status_code == 200:
                    with open(icon_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"⬇️ Downloaded explicitly provided icon: {image_icon}")
                    failed_icon_cache.pop(image_icon, None)
                else:
                    failed_icon_cache[image_icon] = now
                    msg = f"Could not download image_icon '{image_icon}' — status {response.status_code}"
                    if debug:
                        logger.debug(f"❌ {msg} | URL: {icon_url}")
                    else:
                        logger.warning(f"⚠️ {msg}")
            except Exception as e:
                failed_icon_cache[image_icon] = now
                msg = f"Failed to fetch image_icon '{image_icon}': {e}"
                if debug:
                    logger.debug(f"❌ {msg} | URL: {icon_url}")
                else:
                    logger.warning(f"⚠️ {msg}")

    return {
        "registry": registry,
        "owner": owner,
        "image_name": img_name,
        "image_tag": tag,
        "image_icon": image_icon,
        "image_ref": image_ref,
    }
