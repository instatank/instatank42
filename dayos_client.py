"""Read-only Firestore REST client for DayOS data.

Deliberately mirrors time-tracker/api/cron-reminders.mjs: sign a service-account
JWT ourselves, swap it for an OAuth access token, then hit the Firestore REST
API directly. No firebase-admin, no grpc — two small deps (httpx, cryptography)
and every request is plain HTTPS you can read in the logs.

The service account key comes from FIREBASE_SERVICE_ACCOUNT_FILE (path) or
FIREBASE_SERVICE_ACCOUNT (inline JSON) — same JSON DayOS already uses on Vercel.
"""

import base64
import json
import os
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

FIRESTORE_BASE = "https://firestore.googleapis.com/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/datastore"
PAGE_SIZE = 300


class DayosConfigError(RuntimeError):
    """Configuration problem the owner has to fix (missing key, wrong project)."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def decode_value(v: dict):
    """One Firestore-typed value -> plain Python."""
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return v["booleanValue"]
    if "nullValue" in v:
        return None
    if "timestampValue" in v:
        return v["timestampValue"]
    if "arrayValue" in v:
        return [decode_value(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return decode_fields(v["mapValue"].get("fields", {}))
    if "referenceValue" in v:
        return v["referenceValue"]
    if "bytesValue" in v:
        return v["bytesValue"]
    if "geoPointValue" in v:
        return v["geoPointValue"]
    return None


def decode_fields(fields: dict) -> dict:
    return {k: decode_value(v) for k, v in fields.items()}


def _doc_id(name: str) -> str:
    return name.rsplit("/", 1)[1]


class FirestoreClient:
    def __init__(self, service_account: dict):
        for key in ("project_id", "client_email", "private_key"):
            if key not in service_account:
                raise DayosConfigError(
                    f"Service account JSON is missing '{key}' — is this the right file?"
                )
        self.sa = service_account
        self.project_id = service_account["project_id"]
        self._token = None
        self._token_expiry = 0.0
        self._http = httpx.Client(timeout=30.0)

    @classmethod
    def from_env(cls) -> "FirestoreClient":
        path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_FILE", "").strip()
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
        if path:
            p = Path(path)
            if not p.exists():
                raise DayosConfigError(
                    f"FIREBASE_SERVICE_ACCOUNT_FILE points to {path} but no file is there."
                )
            raw = p.read_text(encoding="utf-8")
        if not raw:
            raise DayosConfigError(
                "DayOS sync is not configured. Set FIREBASE_SERVICE_ACCOUNT_FILE "
                "(path to the Firebase service-account JSON) in .env — see deploy/DEPLOY.md."
            )
        try:
            sa = json.loads(raw)
        except json.JSONDecodeError as e:
            raise DayosConfigError(f"Service account JSON does not parse: {e}") from e
        return cls(sa)

    # --- Auth -----------------------------------------------------------

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 300:
            return self._token
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": self.sa["client_email"],
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }
        unsigned = _b64url(json.dumps(header).encode()) + "." + _b64url(json.dumps(claims).encode())
        pem = self.sa["private_key"].replace("\\n", "\n").encode()
        key = serialization.load_pem_private_key(pem, password=None)
        sig = key.sign(unsigned.encode(), padding.PKCS1v15(), hashes.SHA256())
        jwt = unsigned + "." + _b64url(sig)
        r = self._http.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt,
            },
        )
        if r.status_code != 200:
            raise RuntimeError(f"Google OAuth token request failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}"}

    @property
    def _db_root(self) -> str:
        return f"projects/{self.project_id}/databases/(default)/documents"

    # --- Reads ----------------------------------------------------------

    def list_collection(self, parent_path: str, collection_id: str) -> dict:
        """Full pull of one collection, paged. parent_path like 'users/<uid>'
        or 'projectRefs/<uid>' ('' for a root collection). Returns {doc_id: fields}."""
        url = f"{FIRESTORE_BASE}/{self._db_root}"
        if parent_path:
            url += f"/{parent_path}"
        url += f"/{collection_id}"
        docs: dict = {}
        page_token = None
        while True:
            params = {"pageSize": PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            r = self._http.get(url, params=params, headers=self._headers())
            if r.status_code != 200:
                raise RuntimeError(
                    f"Firestore list {parent_path}/{collection_id} -> {r.status_code} {r.text[:300]}"
                )
            data = r.json()
            for d in data.get("documents", []):
                docs[_doc_id(d["name"])] = decode_fields(d.get("fields", {}))
            page_token = data.get("nextPageToken")
            if not page_token:
                return docs

    def query_collection(self, parent_path: str, collection_id: str,
                         field: str, op: str, value: dict) -> dict:
        """runQuery with a single field filter. `value` is Firestore-typed,
        e.g. {'stringValue': '2026-06-01'}. Returns {doc_id: fields}."""
        url = f"{FIRESTORE_BASE}/{self._db_root}"
        if parent_path:
            url += f"/{parent_path}"
        url += ":runQuery"
        body = {
            "structuredQuery": {
                "from": [{"collectionId": collection_id}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": field},
                        "op": op,
                        "value": value,
                    }
                },
            }
        }
        r = self._http.post(url, json=body, headers=self._headers())
        if r.status_code != 200:
            raise RuntimeError(
                f"Firestore query {parent_path}/{collection_id} on {field} -> "
                f"{r.status_code} {r.text[:300]}"
            )
        docs = {}
        for row in r.json():
            doc = row.get("document")
            if doc:
                docs[_doc_id(doc["name"])] = decode_fields(doc.get("fields", {}))
        return docs

    def query_by_doc_id(self, parent_path: str, collection_id: str, min_doc_id: str) -> dict:
        """Docs whose ID >= min_doc_id — for DayOS collections keyed by date
        (ratings, eod, dfts, life_ratings)."""
        ref = f"{self._db_root}/{parent_path}/{collection_id}/{min_doc_id}"
        return self.query_collection(
            parent_path, collection_id,
            "__name__", "GREATER_THAN_OR_EQUAL", {"referenceValue": ref},
        )

    def discover_uid(self) -> str:
        """Find the single DayOS user's uid via a collection-group query
        (devices first — every registered phone writes one — then blocks)."""
        url = f"{FIRESTORE_BASE}/{self._db_root}:runQuery"
        for coll in ("devices", "blocks"):
            body = {
                "structuredQuery": {
                    "from": [{"collectionId": coll, "allDescendants": True}],
                    "limit": 25,
                }
            }
            r = self._http.post(url, json=body, headers=self._headers())
            if r.status_code != 200:
                continue
            uids = set()
            for row in r.json():
                name = (row.get("document") or {}).get("name", "")
                parts = name.split("/")
                if "users" in parts:
                    uids.add(parts[parts.index("users") + 1])
            if len(uids) == 1:
                return uids.pop()
            if len(uids) > 1:
                raise DayosConfigError(
                    f"Found more than one DayOS user ({sorted(uids)}) — "
                    "set DAYOS_UID in .env to pick yours."
                )
        raise DayosConfigError(
            "Could not find any DayOS data in this Firebase project. "
            "Check the service account belongs to the DayOS project, or set DAYOS_UID."
        )
