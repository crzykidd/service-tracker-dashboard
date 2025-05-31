import os
import requests
from datetime import datetime

def fetch_icon_if_missing(name, image_dir, logger):
    if not name:
        return None
    filename = f"{name}.svg"
    local_path = os.path.join(image_dir, filename)
    if os.path.exists(local_path):
        return filename

    icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{filename}"
    try:
        response = requests.get(icon_url, timeout=5)
        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(response.content)
            logger.info(f"⬇️ Downloaded icon for {name} to {local_path}")
            return filename
        else:
            logger.warning(f"⚠️ Icon not found for {name} (HTTP {response.status_code})")
    except Exception as e:
        logger.warning(f"⚠️ Failed to download icon for {name}: {e}")
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
    logger=None
):
    """
    Parses image info and resolves an icon.
    If image_raw is not provided, fallback_name can be used for the icon.
    """
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
        image_icon = fetch_icon_if_missing(icon_source_name, image_dir, logger)
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
                    logger.warning(f"⚠️ Could not download image_icon '{image_icon}' — status {response.status_code}")
            except Exception as e:
                failed_icon_cache[image_icon] = now
                logger.warning(f"⚠️ Failed to fetch image_icon '{image_icon}': {e}")

    return {
        "registry": registry,
        "owner": owner,
        "image_name": img_name,
        "image_tag": tag,
        "image_icon": image_icon
    }
