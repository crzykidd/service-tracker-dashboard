import os
import requests
from datetime import datetime
import inspect



def fetch_icon_if_missing(name, image_dir, logger, debug=False, source_hint=None):
    if not name:
        return None

    # Get calling function or route
    stack = inspect.stack()
    caller_function = stack[1].function if len(stack) > 1 else "unknown"

    if name.lower().endswith(".svg"):
        name = name[:-4]  # remove exactly 4 characters: ".svg"
    name = name.lower()
    filename = f"{name}.svg"
    local_path = os.path.join(image_dir, filename)

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
    registry = owner = img_name = tag = None

    if image_raw:
        tag_split = image_raw.split(":")
        base = tag_split[0]
        tag = tag_split[1] if len(tag_split) > 1 else None
        parts = base.split("/")
        if len(parts) == 3:
            registry, owner, img_name = parts
        elif len(parts) == 2:
            owner, img_name = parts
        elif len(parts) == 1:
            img_name = parts[0]
    elif fallback_name:
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
        icon_path = os.path.join(image_dir, image_icon)
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
        "image_icon": image_icon
    }
