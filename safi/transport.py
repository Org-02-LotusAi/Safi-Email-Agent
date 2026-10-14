"""Mail transport (doc §5, §34). Two implementations behind one tiny protocol so the
same service loop drives live IMAP/SMTP and an offline in-memory mailbox identically.

Duplicate-message protection (doc §36) is deliberately NOT this module's job — IMAP may
legitimately redeliver, and :class:`InMemoryTransport` intentionally allows delivering the
same bytes twice so the service layer's dedup (Message-ID based) can be exercised.
"""

from __future__ import annotations

import imaplib
import smtplib
import time
from email import message_from_bytes
from email.policy import default as _default_policy
from typing import Protocol

from . import compose
from .models import AgentConfig


class MailTransport(Protocol):
    def fetch_new(self, agent: AgentConfig) -> list[tuple[str, bytes]]:
        """Return (uid, raw_bytes) for messages newly available for ``agent``."""
        ...

    def send(
        self,
        agent: AgentConfig,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        references: list[str] | None = None,
    ) -> None:
        """Send a reply/notification from ``agent``'s mailbox."""
        ...


# --- Offline / test transport ----------------------------------------------
class InMemoryTransport:
    """Fully offline mailbox simulator (doc §5 key architectural decision).

    ``deliver`` appends raw bytes to a mailbox's inbox. ``fetch_new`` returns everything
    delivered to an agent's mailbox since that mailbox's cursor last advanced (a per-mailbox
    "already fetched" position) — NOT deduped by Message-ID; that is the service's job
    (doc §36), so delivering identical bytes twice yields two fetchable items here.
    """

    def __init__(self) -> None:
        self._inboxes: dict[str, list[tuple[str, bytes]]] = {}
        self._cursors: dict[str, int] = {}
        self.sent: list[dict] = []
        self._uid_counter = 0

    def deliver(self, mailbox: str, raw_bytes: bytes) -> None:
        mailbox = (mailbox or "").strip().lower()
        self._uid_counter += 1
        uid = f"mem-{self._uid_counter}"
        self._inboxes.setdefault(mailbox, []).append((uid, raw_bytes))

    def fetch_new(self, agent: AgentConfig) -> list[tuple[str, bytes]]:
        mailbox = (agent.mailbox or "").strip().lower()
        inbox = self._inboxes.get(mailbox, [])
        start = self._cursors.get(mailbox, 0)
        new_items = inbox[start:]
        self._cursors[mailbox] = len(inbox)
        return list(new_items)

    def send(
        self,
        agent: AgentConfig,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        references: list[str] | None = None,
    ) -> None:
        raw = compose.make_message(
            sender=agent.mailbox,
            to=to_addr,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            references=references,
        )
        # Do NOT auto-deliver into any inbox — no agent-to-agent workflows (doc §43).
        self.sent.append(
            {
                "from": agent.mailbox,
                "to": to_addr,
                "subject": subject,
                "body": body,
                "in_reply_to": in_reply_to,
                "references": references or [],
                "raw": raw,
            }
        )

    def sent_to(self, addr: str) -> list[dict]:
        addr = (addr or "").strip().lower()
        return [m for m in self.sent if (m["to"] or "").strip().lower() == addr]


# --- Live transport ----------------------------------------------------------
class TransportError(RuntimeError):
    """Raised for any network/protocol failure so the caller gets a clear signal
    (doc §37) instead of a silently swallowed error."""


class ImapSmtpTransport:
    """Live transport using stdlib ``imaplib``/``smtplib``.

    ``agent.imap`` = {host, port, user, password, ssl}
    ``agent.smtp`` = {host, port, user, password, starttls}
    """

    def fetch_new(self, agent: AgentConfig) -> list[tuple[str, bytes]]:
        if not agent.imap:
            raise TransportError(f"agent {agent.agent_id} has no imap configuration")
        cfg = agent.imap
        try:
            conn = self._imap_connect(cfg)
        except Exception as exc:
            raise TransportError(f"IMAP connect/login failed for {agent.agent_id}: {exc}") from exc

        results: list[tuple[str, bytes]] = []
        try:
            typ, _ = conn.select("INBOX")
            if typ != "OK":
                raise TransportError(f"IMAP SELECT INBOX failed for {agent.agent_id}")
            typ, data = conn.search(None, "UNSEEN")
            if typ != "OK":
                raise TransportError(f"IMAP SEARCH UNSEEN failed for {agent.agent_id}")
            uids = data[0].split() if data and data[0] else []
            for uid in uids:
                typ, msg_data = conn.fetch(uid, "(RFC822)")
                if typ != "OK" or not msg_data or msg_data[0] is None:
                    continue
                raw = msg_data[0][1]
                # Fetching RFC822 (not BODY.PEEK[]) sets \Seen, so IMAP will not
                # return this message again on the next UNSEEN search.
                results.append((uid.decode() if isinstance(uid, bytes) else str(uid), raw))
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(f"IMAP fetch failed for {agent.agent_id}: {exc}") from exc
        finally:
            try:
                conn.close()
            except Exception:
                pass
            try:
                conn.logout()
            except Exception:
                pass
        return results

    def _imap_connect(self, cfg: dict) -> imaplib.IMAP4:
        if cfg.get("ssl", True):
            conn = imaplib.IMAP4_SSL(cfg["host"], cfg.get("port", 993))
        else:
            conn = imaplib.IMAP4(cfg["host"], cfg.get("port", 143))
        conn.login(cfg["user"], cfg["password"])
        return conn

    def send(
        self,
        agent: AgentConfig,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        references: list[str] | None = None,
    ) -> None:
        if not agent.smtp:
            raise TransportError(f"agent {agent.agent_id} has no smtp configuration")
        cfg = agent.smtp
        raw = compose.make_message(
            sender=agent.mailbox,
            to=to_addr,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            references=references,
        )
        try:
            if cfg.get("starttls", True):
                server = smtplib.SMTP(cfg["host"], cfg.get("port", 587), timeout=30)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(cfg["host"], cfg.get("port", 465), timeout=30)
            try:
                if cfg.get("user"):
                    server.login(cfg["user"], cfg["password"])
                server.sendmail(agent.mailbox, [to_addr], raw)
            finally:
                server.quit()
        except Exception as exc:
            raise TransportError(f"SMTP send failed for {agent.agent_id}: {exc}") from exc

    def idle_wait(self, agent: AgentConfig, timeout: int = 60) -> bool:
        """Wait for new mail via IMAP IDLE (Python 3.13+); fall back to a NOOP + short
        sleep on any failure. Never raises — this is a best-effort wake-up mechanism, and
        the caller will poll with :meth:`fetch_new` regardless (doc §37: never crash the
        loop over a connection hiccup).
        """
        if not agent.imap:
            time.sleep(min(timeout, 5))
            return False
        cfg = agent.imap
        try:
            conn = self._imap_connect(cfg)
        except Exception:
            time.sleep(min(timeout, 5))
            return False
        try:
            conn.select("INBOX")
            idle_fn = getattr(conn, "idle", None)
            if idle_fn is None:
                # imaplib without IDLE support (pre-3.13): fall back to NOOP + sleep.
                time.sleep(min(timeout, 5))
                return False
            try:
                with idle_fn() as idle_ctx:  # Python 3.13+ imaplib.IMAP4.idle()
                    idle_ctx.wait(timeout=timeout)
                return True
            except Exception:
                try:
                    conn.noop()
                except Exception:
                    pass
                time.sleep(min(timeout, 5))
                return False
        except Exception:
            time.sleep(min(timeout, 5))
            return False
        finally:
            try:
                conn.logout()
            except Exception:
                pass
