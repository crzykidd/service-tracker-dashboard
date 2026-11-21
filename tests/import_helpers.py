"""Helpers for driving the import UI the way a browser does (shared by the import UI tests and
the tests that used to exercise the old restore form).

`Page` parses the preview back; `Page.form()` is what the browser would submit; `import_flow`
runs upload -> preview -> apply and returns the final response.
"""

import io
import json
import re
from html.parser import HTMLParser

from werkzeug.datastructures import MultiDict


class Page(HTMLParser):
    """Collects the inputs and selects of the import form and the plain structure of a page."""

    def __init__(self, html):
        super().__init__()
        self.html = html
        self.inputs, self.selects = [], []
        self._in_form, self._select = False, None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and a.get("id") == "import-form":
            self._in_form = True
        elif tag == "input" and self._in_form:
            self.inputs.append({"name": a.get("name"), "type": a.get("type", "text"), "value": a.get("value", ""),
                                "checked": "checked" in a, "disabled": "disabled" in a,
                                "applicable": a.get("data-applicable") != "false", "kind": a.get("data-kind")})
        elif tag == "select" and self._in_form:
            self._select = {"name": a.get("name"), "options": [], "selected": None}
            self.selects.append(self._select)
        elif tag == "option" and self._select is not None:
            self._select["options"].append(a.get("value", ""))
            if "selected" in a:
                self._select["selected"] = a.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self._in_form = False
        elif tag == "select":
            self._select = None

    def box(self, name, value=None):
        found = [i for i in self.inputs if i["name"] == name and (value is None or i["value"] == value)]
        assert found, (name, value)
        return found[0]

    def ticked(self, name, value=None):
        return self.box(name, value)["checked"]

    def form(self):
        """What the browser submits: checked, enabled boxes, selected radios, hidden inputs, selects."""
        data = []
        for i in self.inputs:
            if not i["name"] or i["disabled"]:
                continue
            if i["type"] in ("checkbox", "radio") and not i["checked"]:
                continue
            data.append([i["name"], i["value"]])
        for s in self.selects:
            if s["name"] and s["selected"]:
                data.append([s["name"], s["selected"]])
        return data


def post_form(client, url, items):
    return client.post(url, data=MultiDict([tuple(x) for x in items]))


def upload(client, doc, name="export.json", follow=False):
    raw = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
    import io
    return client.post("/settings/import", data={"import_file": (io.BytesIO(raw), name)},
                       content_type="multipart/form-data", follow_redirects=follow)


def token_of(resp):
    assert resp.status_code == 302, resp.get_data(as_text=True)[:400]
    m = re.search(r"/settings/import/([A-Za-z0-9_-]+)$", resp.headers["Location"])
    assert m, resp.headers["Location"]
    return m.group(1)


def section(html, slug="backup"):
    """The markup of one settings section (to the next section, or the toast region)."""
    start = html.find(f'id="section-{slug}"')
    assert start != -1, slug
    ends = [i for i in (html.find('id="section-', start + 10), html.find('id="toast-region"', start)) if i != -1]
    return html[start:min(ends)] if ends else html[start:]




def import_flow(client, doc, *, mode="fill", create=True, restore=False, expect=200, name="import.json"):
    """Upload `doc` (a v1 dict, a legacy list, or bytes), tick what a careful operator would
    (every default tick, plus "Import as new" when `create`, plus every field box in overwrite
    mode) and apply. Returns the response of the apply POST."""
    raw = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
    resp = client.post("/settings/import", data={"import_file": (io.BytesIO(raw), name)},
                       content_type="multipart/form-data")
    token = token_of(resp)
    page = Page(client.get(f"/settings/import/{token}").get_data(as_text=True))
    items = [i for i in page.form() if i[0] != "mode"] + [["mode", mode]]
    have = {tuple(i) for i in items}
    for i in page.inputs:
        n = i["name"] or ""
        if create and n.startswith("create-") and (n, i["value"]) not in have:
            items.append([n, i["value"]])
        if restore and n.startswith("opt-") and i["value"] == "restore":
            items.append([n, i["value"]])
            items.append(["sel-" + n[len("opt-"):], "1"])
        if mode == "overwrite" and n.startswith("field-") and i["applicable"] and (n, i["value"]) not in have:
            items.append([n, i["value"]])
            sel = "sel-" + n[len("field-"):]
            if (sel, "1") not in have:
                items.append([sel, "1"])
                have.add((sel, "1"))
    resp = post_form(client, f"/settings/import/{token}/apply", items)
    assert resp.status_code == expect, resp.get_data(as_text=True)[:800]
    return resp
