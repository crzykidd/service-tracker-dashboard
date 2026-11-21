"""Settings page section registry (design: docs/design/2026-11-20-settings-modernization.md §4).

Pure data, no Flask import. The sidebar, the mobile select and the routes all read it:
the template builds the navigation from `GROUPS` / `SECTIONS`, and the routes use
`resolve()` to validate `?section=`. Order here is the order on the page.
"""

# (key, label): the six labelled sidebar groups, in order.
GROUPS = (
    ('general', 'General'),
    ('dashboard', 'Dashboard'),
    ('sources', 'Sources'),
    ('integrations', 'Integrations'),
    ('access', 'Access'),
    ('data', 'Data'),
)

# (slug, label, group key). The slug is the `#fragment`, the `?section=` value and the
# suffix of the element id `section-<slug>`.
SECTIONS = (
    ('about', 'About', 'general'),
    ('configuration', 'Configuration', 'general'),
    ('groups', 'Groups', 'dashboard'),
    ('widgets', 'Widgets', 'dashboard'),
    ('docker', 'Docker', 'sources'),
    ('streams', 'Streams', 'sources'),
    ('image-updates', 'Image updates', 'sources'),
    ('notifications', 'Notifications', 'integrations'),
    ('home-assistant', 'Home Assistant', 'integrations'),
    ('users', 'Users', 'access'),
    ('api-keys', 'API keys', 'access'),
    ('audit-log', 'Audit log', 'access'),
    ('backup', 'Backup & restore', 'data'),
    ('deleted', 'Deleted', 'data'),
)

DEFAULT = 'about'

# Legacy `?section=` values (bookmarks, old links) and the section they now mean.
ALIASES = {'info': 'about', 'exposure': 'docker', 'api': 'api-keys'}

SLUGS = tuple(slug for slug, _label, _group in SECTIONS)


def resolve(raw):
    """A slug or a legacy alias -> the canonical slug; anything else -> None."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if value in SLUGS:
        return value
    return ALIASES.get(value)
