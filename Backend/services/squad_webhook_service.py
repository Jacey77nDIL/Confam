"""Verify and apply Squad webhook notifications (card tokenization, refunds, chat charge sync)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.session import SessionLocal
from models.connected_card import ConnectedCard
from models.payment_transaction import PaymentTransaction
from services import recipient_service, squad_card_service, squad_client

logger = logging.getLogger(__name__)


def verify_signature_detailed(raw_body: bytes, header_value: str | None) -> tuple[bool, str]:
    """
    Validate x-squad-encrypted-body (HMAC-SHA512 of payload, hex).
    Returns (ok, reason) for logging when verification fails.
    """
    if not header_value or not str(header_value).strip():
        return False, "missing_x_squad_encrypted_body_header"
    if not squad_client.squad_is_configured():
        return False, "squad_secret_not_configured"
    try:
        key = squad_client.squad_secret().encode("utf-8")
    except squad_client.SquadConfigurationError:
        return False, "squad_secret_unavailable"
    hv = str(header_value).strip()
    digest = hmac.new(key, raw_body, hashlib.sha512).hexdigest()
    try:
        if hmac.compare_digest(digest.upper(), hv.upper()):
            return True, "hmac_raw_request_body"
    except Exception:  # noqa: BLE001
        pass
    try:
        obj = json.loads(raw_body.decode("utf-8"))
        compact = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        alt = hmac.new(key, compact, hashlib.sha512).hexdigest()
        if hmac.compare_digest(alt.upper(), hv.upper()):
            return True, "hmac_compact_json_representation"
    except Exception:  # noqa: BLE001
        return False, "hmac_mismatch_json_parse_failed"
    return False, "hmac_mismatch_raw_and_compact"


def verify_signature(raw_body: bytes, header_value: str | None) -> bool:
    return verify_signature_detailed(raw_body, header_value)[0]


def _body_dict(root: dict[str, Any]) -> dict[str, Any]:
    inner = root.get("Body") or root.get("body")
    if isinstance(inner, dict):
        return inner
    return root


def _metadata_purpose(root: dict[str, Any], body: dict[str, Any]) -> str | None:
    for blob in (body, root):
        for key in ("metadata", "meta", "meta_data"):
            meta = blob.get(key)
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:  # noqa: BLE001
                    continue
            if isinstance(meta, dict):
                purpose = meta.get("purpose")
                if purpose:
                    return str(purpose).strip()
    return None


def _gateway_ref_from_webhook(root: dict[str, Any], body: dict[str, Any]) -> str | None:
    """Squad refund API needs gateway_transaction_ref; webhooks use several key spellings."""
    candidates: list[dict[str, Any]] = []
    seen_blob_ids: set[int] = set()

    def push(blob: dict[str, Any]) -> None:
        bid = id(blob)
        if bid in seen_blob_ids:
            return
        seen_blob_ids.add(bid)
        candidates.append(blob)

    if isinstance(body, dict):
        push(body)
    if isinstance(root, dict):
        push(root)
        for nested_key in ("Body", "body", "Data", "data"):
            n = root.get(nested_key)
            if isinstance(n, dict):
                push(n)
                inner = n.get("data") or n.get("Data")
                if isinstance(inner, dict):
                    push(inner)
    keys = (
        "gateway_ref",
        "gateway_transaction_ref",
        "GatewayRef",
        "GatewayTransactionRef",
        "gatewayTransactionRef",
    )
    for blob in candidates:
        for key in keys:
            v = blob.get(key)
            if v is not None:
                s = str(v).strip()
                if s:
                    return s
    return None


def _transaction_refs(root: dict[str, Any], body: dict[str, Any]) -> tuple[str | None, str | None]:
    tx = (
        root.get("TransactionRef")
        or root.get("transaction_ref")
        or body.get("transaction_ref")
        or body.get("TransactionRef")
    )
    if tx is not None:
        tx = str(tx).strip() or None
    return tx, _gateway_ref_from_webhook(root, body)


TOKENIZATION_FAILED_DETAIL = (
    "Card verification succeeded but tokenization failed. Please try a different card."
)

# Squad GET /transaction/verify does not include payment_information.token_id (only webhooks do).
VERIFY_OK_NO_TOKEN_USER_MSG = (
    "Squad confirmed your payment, but their verify API never includes a card token; only the "
    "charge_successful webhook does. Configure Squad's webhook URL to your public "
    "https://.../webhooks/squad (ngrok in dev). The NGN 100 verification charge was submitted for "
    "refund automatically when possible."
)


def payment_token_from_payload(blob: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """token_id, card_type, pan from webhook body or verify-transaction merged payload."""
    pinfo = blob.get("payment_information") or blob.get("paymentInformation")
    token = card_type = pan = None
    if isinstance(pinfo, dict):
        t = pinfo.get("token_id") or pinfo.get("tokenId")
        if t is not None:
            token = str(t).strip() or None
        ct = pinfo.get("card_type") or pinfo.get("cardType")
        if ct is not None:
            card_type = str(ct).strip() or None
        p = pinfo.get("pan") or pinfo.get("PAN")
        if p is not None:
            pan = str(p).strip() or None
    if not token:
        t2 = blob.get("token_id") or blob.get("tokenId") or blob.get("TokenId")
        if isinstance(t2, str) and t2.strip():
            token = t2.strip()
    if not token:
        cd = blob.get("card_details") or blob.get("cardDetails") or blob.get("CardDetails")
        if isinstance(cd, dict):
            t3 = cd.get("token_id") or cd.get("tokenId") or cd.get("token") or cd.get("Token")
            if isinstance(t3, str) and t3.strip():
                token = t3.strip()
            if not card_type:
                ct = cd.get("card_type") or cd.get("cardType")
                if isinstance(ct, str) and ct.strip():
                    card_type = ct.strip()
            if not pan:
                p = cd.get("pan") or cd.get("PAN")
                if isinstance(p, str) and p.strip():
                    pan = p.strip()
    if not token:
        token, d_ct, d_pan = _payment_token_deep_bfs(blob)
        if d_ct and not card_type:
            card_type = d_ct
        if d_pan and not pan:
            pan = d_pan
    return token, card_type, pan


def _payment_token_deep_bfs(root: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Breadth-first search for token_id / tokenId on nested dicts (Squad verify shapes vary)."""
    q: deque[dict[str, Any]] = deque([root])
    seen: set[int] = set()
    fallback_token: str | None = None
    card_type = pan = None
    while q:
        cur = q.popleft()
        bid = id(cur)
        if bid in seen or not isinstance(cur, dict):
            continue
        seen.add(bid)
        for tk in ("token_id", "tokenId", "TokenId"):
            v = cur.get(tk)
            if isinstance(v, str) and len(v.strip()) > 2:
                if not card_type:
                    ct = cur.get("card_type") or cur.get("cardType")
                    if isinstance(ct, str) and ct.strip():
                        card_type = ct.strip()
                if not pan:
                    p = cur.get("pan") or cur.get("PAN")
                    if isinstance(p, str) and p.strip():
                        pan = p.strip()
                return v.strip(), card_type, pan
        v = cur.get("token")
        if isinstance(v, str) and len(v.strip()) > 8 and fallback_token is None:
            s = v.strip()
            if s.replace("-", "").replace("_", "").isalnum():
                fallback_token = s
        for v in cur.values():
            if isinstance(v, dict):
                q.append(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        q.append(item)
    if fallback_token:
        return fallback_token, card_type, pan
    return None, None, None


def payment_token_from_verify_shards(shards: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    """Try each verify fragment, then deep-search the largest blob."""
    for shard in shards:
        t, ct, p = payment_token_from_payload(shard)
        if t:
            return t, ct, p
    for shard in shards:
        t, ct, p = _payment_token_deep_bfs(shard)
        if t:
            return t, ct, p
    return None, None, None


def _transaction_success_from_shards(shards: list[dict[str, Any]]) -> bool:
    for s in shards:
        st = str(s.get("transaction_status") or s.get("TransactionStatus") or "").lower()
        if st in ("success", "successful"):
            return True
    return False


def _apply_card_verification_to_row(
    db: Session,
    row: ConnectedCard,
    *,
    token_id: str,
    card_type: str | None,
    pan: str | None,
    tx_ref: str,
    gw_ref: str | None,
) -> None:
    """Persist active card + optional refund. Caller commits."""
    fully_done = (
        row.status == "active"
        and row.authorization_token == token_id
        and row.refund_initiated
    )
    if fully_done:
        logger.info(
            "Squad card verify skip already complete connected_card_id=%s tx_ref=%s",
            row.id,
            tx_ref[:64],
        )
        return

    activating = not (row.status == "active" and row.authorization_token == token_id)
    if activating:
        masked, last4, em, ey = squad_card_service.parse_masked_pan(pan)
        row.authorization_token = token_id
        row.reusable_reference = tx_ref
        row.card_type = card_type
        row.masked_pan = masked
        row.last4 = last4
        row.expiry_month = em
        row.expiry_year = ey
        row.status = "active"
        if gw_ref:
            row.verification_gateway_ref = gw_ref
        db.add(row)

        db.execute(
            update(ConnectedCard)
            .where(
                ConnectedCard.user_id == row.user_id,
                ConnectedCard.id != row.id,
            )
            .values(status="disabled"),
        )
        logger.info(
            "Squad card verify activated connected_card_id=%s user_id=%s tx_ref=%s",
            row.id,
            row.user_id,
            tx_ref[:64],
        )
    else:
        if gw_ref and not row.verification_gateway_ref:
            row.verification_gateway_ref = gw_ref
        db.add(row)
        logger.info(
            "Squad card verify duplicate webhook (already active) connected_card_id=%s tx_ref=%s",
            row.id,
            tx_ref[:64],
        )

    effective_gw = (row.verification_gateway_ref or "").strip() or (gw_ref or "").strip()
    if not effective_gw and tx_ref:
        resolved = squad_card_service.fetch_gateway_transaction_ref(transaction_ref=tx_ref)
        if resolved:
            row.verification_gateway_ref = resolved
            effective_gw = resolved
            db.add(row)
            logger.info(
                "Squad card verify resolved gateway ref via verify API tx_ref=%s gateway=%s",
                tx_ref[:64],
                resolved[:64],
            )

    if not row.refund_initiated and tx_ref:
        if not effective_gw:
            logger.error(
                "Squad card verify REFUND SKIPPED no gateway ref after webhook+verify "
                "connected_card_id=%s tx_ref=%s",
                row.id,
                tx_ref,
            )
        else:
            logger.info(
                "Squad card verify calling refund API tx_ref=%s gateway_transaction_ref=%s",
                tx_ref[:64],
                effective_gw[:80],
            )
            ref = squad_card_service.refund_full_transaction(
                gateway_transaction_ref=effective_gw,
                transaction_ref=tx_ref,
                reason="Confam ₦100 card verification",
            )
            row.refund_initiated = bool(ref.get("success"))
            if ref.get("success"):
                inner = ref.get("data") if isinstance(ref.get("data"), dict) else {}
                logger.info(
                    "Squad card verify REFUND API OK connected_card_id=%s tx_ref=%s "
                    "refund_payload_keys=%s gateway_refund_status=%s",
                    row.id,
                    tx_ref[:64],
                    sorted(inner.keys()) if isinstance(inner, dict) else [],
                    inner.get("gateway_refund_status") if isinstance(inner, dict) else None,
                )
            else:
                logger.warning(
                    "Squad card verify REFUND API FAILED connected_card_id=%s tx_ref=%s detail=%s",
                    row.id,
                    tx_ref[:64],
                    ref.get("user_message"),
                )

    db.add(row)


def finalize_pending_cards_from_squad_verify(db: Session, user_id: int) -> dict[str, Any]:
    """
    When Squad cannot POST webhooks to this host (localhost), poll verify API for recent
    pending/abandoned card rows and complete activation + refund.
    """
    rows = list(
        db.scalars(
            select(ConnectedCard)
            .where(
                ConnectedCard.user_id == user_id,
                ConnectedCard.status.in_(("pending", "abandoned")),
            )
            .order_by(ConnectedCard.id.desc())
            .limit(12),
        ).all()
    )
    if not rows:
        logger.info("Squad finalize: no pending/abandoned card rows for user_id=%s", user_id)
        return {
            "success": False,
            "message": "No in-progress card link found. Open Cards and run checkout again.",
        }

    last_msg = "Could not confirm card with Squad yet."
    for row in rows:
        tx_ref = (row.verification_transaction_ref or "").strip()
        if not tx_ref:
            continue
        _status, raw_envelope, shards = squad_card_service.verify_transaction_dict_shards(tx_ref)
        if not raw_envelope or not shards:
            last_msg = "Squad verify did not return data for the last checkout attempt."
            logger.info("Squad finalize: no verify shards tx_ref=%s row_id=%s", tx_ref[:64], row.id)
            continue
        if not _transaction_success_from_shards(shards):
            st = ""
            for s in shards:
                if isinstance(s, dict):
                    st = str(s.get("transaction_status") or s.get("TransactionStatus") or "").strip()
                    if st:
                        break
            last_msg = f"Squad payment status is still: {st.lower() or 'unknown'}."
            logger.info(
                "Squad finalize: tx_ref=%s row_id=%s status=%r (not success)",
                tx_ref[:64],
                row.id,
                st,
            )
            continue
        token_id, card_type, pan = payment_token_from_verify_shards(shards)
        gw_ref = None
        for s in shards:
            g2 = _gateway_ref_from_webhook(s, s)
            if g2:
                gw_ref = g2
                break
        if not gw_ref:
            gw_ref = _gateway_ref_from_webhook(raw_envelope, raw_envelope)
        if not token_id:
            dump = json.dumps(raw_envelope, indent=2, default=str)
            if len(dump) > 14000:
                dump = dump[:14000] + "\n... (truncated)"
            logger.warning(
                "Squad finalize: verify Success but no token_id (expected: Squad verify omits "
                "payment_information; token only on charge_successful webhook). JSON:\n%s",
                dump,
            )
            data_inner = raw_envelope.get("data") if isinstance(raw_envelope.get("data"), dict) else None
            effective_gw = (gw_ref or "").strip() or None
            if not effective_gw and isinstance(data_inner, dict):
                g = (
                    data_inner.get("gateway_transaction_ref")
                    or data_inner.get("gateway_ref")
                    or data_inner.get("GatewayTransactionRef")
                )
                if isinstance(g, str) and g.strip():
                    effective_gw = g.strip()
            inner_tx = tx_ref
            if isinstance(data_inner, dict):
                tr = data_inner.get("transaction_ref") or data_inner.get("transactionRef")
                if isinstance(tr, str) and tr.strip():
                    inner_tx = tr.strip()
            if effective_gw and inner_tx and not row.refund_initiated:
                ref = squad_card_service.refund_full_transaction(
                    gateway_transaction_ref=effective_gw,
                    transaction_ref=inner_tx,
                    reason="Confam ₦100 card verification (no webhook token; verify-only refund)",
                )
                logger.info(
                    "Squad finalize: verify-only refund tx=%s ok=%s",
                    inner_tx[:64],
                    ref.get("success"),
                )
            elif not effective_gw:
                logger.warning(
                    "Squad finalize: cannot auto-refund without gateway_transaction_ref row_id=%s",
                    row.id,
                )
            db.delete(row)
            db.commit()
            return {
                "success": False,
                "error": "tokenization_failed",
                "message": VERIFY_OK_NO_TOKEN_USER_MSG,
            }
        logger.info(
            "Squad finalize: completing card row_id=%s tx_ref=%s via verify API",
            row.id,
            tx_ref[:64],
        )
        _apply_card_verification_to_row(
            db,
            row,
            token_id=token_id,
            card_type=card_type,
            pan=pan,
            tx_ref=tx_ref,
            gw_ref=gw_ref,
        )
        db.commit()
        return {"success": True, "message": "Card linked and refund requested via Squad."}

    return {"success": False, "message": last_msg}


def process_webhook_json(data: dict[str, Any]) -> None:
    """Sync handler for BackgroundTasks — opens its own DB session."""
    db = SessionLocal()
    try:
        event = str(data.get("Event") or data.get("event") or "").lower()
        body = _body_dict(data)
        purpose = _metadata_purpose(data, body)
        tx_ref, gw_ref = _transaction_refs(data, body)

        body_keys = sorted(body.keys())[:40] if isinstance(body, dict) else []
        logger.info(
            "Squad webhook handler: event=%r tx_ref=%r purpose=%r body_keys=%s",
            event,
            tx_ref,
            purpose,
            body_keys,
        )

        charge_like = event in {"charge_successful", "chargesuccessful"} or (
            str(body.get("transaction_status") or "").lower() in ("success", "successful")
        )
        if not charge_like:
            logger.info("Squad webhook: ignoring (not a completed charge) event=%r", event)
            return
        if not tx_ref:
            logger.warning("Squad webhook: completed charge missing transaction_ref")
            return

        conn_row = db.scalar(
            select(ConnectedCard).where(ConnectedCard.verification_transaction_ref == tx_ref),
        )
        if conn_row:
            token_id, card_type, pan = payment_token_from_payload(body)
            if not token_id:
                dump = json.dumps(data, indent=2, default=str)
                if len(dump) > 12000:
                    dump = dump[:12000] + "\n... (truncated)"
                logger.warning(
                    "Squad webhook: matched connected_card id=%s tx_ref=%s but no token_id. "
                    "Full webhook JSON (truncated):\n%s",
                    conn_row.id,
                    tx_ref,
                    dump,
                )
                return

            logger.info(
                "Squad webhook: applying card verification connected_card_id=%s user_id=%s tx_ref=%s",
                conn_row.id,
                conn_row.user_id,
                tx_ref[:64],
            )
            _apply_card_verification_to_row(
                db,
                conn_row,
                token_id=token_id,
                card_type=card_type,
                pan=pan,
                tx_ref=tx_ref,
                gw_ref=gw_ref,
            )
            db.commit()
            return

        # Chat send: Squad card charge settled — mark FUNDS_COLLECTED (collection-only; no auto-payout).
        pt = db.scalar(
            select(PaymentTransaction).where(PaymentTransaction.authorization_reference == tx_ref),
        )
        if pt:
            note = (
                f"Funds held in Confam balance. Manual disbursement required for Ref: {tx_ref} "
                f"to Account: {pt.recipient_account}."
            )
            meta = dict(pt.meta or {})
            meta["squad_webhook_charge_confirmed"] = True
            meta["squad_webhook_received_at"] = datetime.now(timezone.utc).isoformat()
            meta["manual_disbursement_note"] = note
            meta["collection_only"] = True
            if pt.status != PaymentTransaction.STATUS_FUNDS_COLLECTED:
                pt.status = PaymentTransaction.STATUS_FUNDS_COLLECTED
            pt.meta = meta
            db.add(pt)
            db.commit()
            logger.info("Squad webhook: payment_transactions id=%s %s", pt.id, note)
            recipient_service.record_recipient(
                db,
                pt.user_id,
                display_name=pt.recipient_name,
                account_number=pt.recipient_account,
                bank_name=pt.recipient_bank,
                extra_alias=None,
                tx_ref=tx_ref,
                account_name=(pt.recipient_name or "").strip() or None,
            )
            try:
                db.commit()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Squad webhook: commit after saved_recipients failed payment_transactions id=%s tx_ref=%s",
                    pt.id,
                    tx_ref,
                    exc_info=True,
                )
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    logger.debug("Squad webhook rollback after commit failure", exc_info=True)
            return

        logger.info(
            "Squad webhook: tx_ref=%s not matched (no connected_cards row or payment_transactions "
            "authorization_reference). purpose=%r",
            tx_ref,
            purpose,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Squad webhook processing failed")
        db.rollback()
    finally:
        db.close()
