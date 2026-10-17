"""Unused bounded synthetic stream protocol for one local fixed-slot Peer.

There is NO network/client/SSH/default transport, effect callback, native import,
decision/ACK/finish/election or adoption API. An ordinary session is consumed
before its first input read. Reopening a consumed session permits STATUS only,
even if no ARM was reached. Before a terminal STATUS/PREPARED reply, one bounded
read must observe input EOF. The caller must close its write side before waiting
for that reply and owns streams and deadlines; this module does not drain input
or impose a deadline.
Host-binding hashes are externally supplied launch pins, not fresh host proof.
Existing local-only checkpoint/native metadata flags remain false.
"""

import fcntl
import hashlib
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from backend.market import historical_fixed_slot_checkpoint as fixed

VERSION = "synthetic-checkpoint-peer-stream/1"
FIXED = "a15a3720fe368a75d9aaf4e59d767347b7cb863dd180c531ebfa3c41f0b1ab2b"
TRAILER = b"CPRPC1\r\n"
EMPTY = hashlib.sha256(b"").hexdigest()
CLAIMS = {
    **fixed.FALSE_CLAIMS,
    "peer_commit_supported": False,
    "fresh_host_observation": False,
}
VERBS = {"HELLO", "STATUS", "ARM", "PUT", "VERIFY"}
PHASES = {"READY", "CONSUMED", "HELLO", "ARMED", "PREPARED", "PAUSED"}
FIELDS = {
    "version",
    "permit",
    "launch",
    "peer",
    "request",
    "operation",
    "prior",
    "control",
    "verb",
    "args",
    "payload_bytes",
    "payload_sha256",
}


# Pin the complete pure infrastructure closure without importing a native module.
def _sources():
    path = Path(fixed.__file__)
    fixed.raw._require(
        path.stat().st_size < fixed.raw.META, "Bounded checkpoint source required"
    )
    fixed.raw._require(
        fixed.raw._sha(path.read_bytes()) == FIXED, "Fixed-slot source differs"
    )
    return {
        "rpc": fixed.raw._sha(Path(__file__).read_bytes()),
        "fixed": FIXED,
        "raw": fixed.HELPER,
    }


# Bind owned local root identities without accepting paths from the wire.
def _root(path):
    path = fixed.raw._path(path)
    info = path.lstat()
    fixed.raw._require(
        stat.S_ISDIR(info.st_mode)
        and info.st_mode & 0o777 == 0o700
        and info.st_uid == os.getuid(),
        "Owned private root required",
    )
    return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid}


# Derive finite ingress quotas from complete capture bounds rather than only new slots.
def _quotas(peer):
    budget = fixed._capture_budget(peer.limits)
    frames = budget["body"] + budget["page"] + 8
    payload = peer.limits["raw_bytes"] + budget["page"] * fixed.raw.META
    fixed.raw._require(
        frames < 2**63 and payload + frames * (fixed.raw.META + 16) < 2**63,
        "Wire arithmetic exceeds finite counter range",
    )
    return {
        "frames": frames,
        "header_bytes": frames * (fixed.raw.META + 16),
        "payload_bytes": payload,
        "body_bytes": peer.limits["raw_bytes"],
        "page_bytes": budget["page"] * fixed.raw.META,
        "body_puts": budget["body"],
        "page_puts": budget["page"],
    }


# Declare only actual future permit/control/session/lock extents, not metadata headroom.
def _amounts():
    return {"file_bytes": 3 * fixed.raw.META + 4096, "file_inodes": 4, "directories": 1}


# Authenticate every future session inode without treating its data as host attestation.
def _resources(root):
    digest = hashlib.sha256(fixed.raw._encoded(_root(root)))
    for name, size in (
        ("permit", fixed.raw.META),
        ("control", fixed.raw.META),
        ("session", fixed.raw.META),
        ("lock", 4096),
    ):
        info = fixed.raw._extent(root / name, size, 1)
        fixed.raw._require(info.st_uid == os.getuid(), "Owned session inode required")
        digest.update(fixed.raw._encoded([name, info.st_dev, info.st_ino, size]))
    return digest.hexdigest()


# Create exactly one sidecar for an externally pinned idle operation before any ingress.
def prepare(
    peer, *, host_binding_sha256, launch_sha256, operation, prior, control_sha256
):
    fixed.raw._require(type(peer) is fixed.Peer, "Exact local Peer required")
    for digest in (host_binding_sha256, launch_sha256, prior, control_sha256):
        fixed.raw._digest(digest)
    fixed.raw._require(
        type(operation) is int and 0 <= operation < peer.limits["operations"],
        "Exact operation required",
    )
    with peer._locked():
        peer._resources()
        control = peer._control()
        fixed.raw._require(
            control["open"] is None
            and control["head"] == prior
            and control["next"] == operation
            and fixed.raw._sha(fixed.raw._encoded(control)) == control_sha256,
            "Externally pinned idle preimage required",
        )
        root = peer.root / "rpc-session"
        root.mkdir(mode=0o700)
        for name, size in (
            ("permit", fixed.raw.META),
            ("control", fixed.raw.META),
            ("session", fixed.raw.META),
            ("lock", 4096),
        ):
            fixed.raw._allocate(root / name, size)
            fixed._initialize(root / name, size)
        permit = {
            "version": VERSION,
            "scope": "SYNTHETIC_STREAM_ONLY",
            "sources": _sources(),
            "peer": peer.header["peer"],
            "owner": peer.common["owner"],
            "binding": peer.binding,
            "peer_header": fixed.raw._sha(fixed.raw._encoded(peer.header)),
            "profile": peer.common["identity_sha256"],
            "peer_root": _root(peer.root),
            "session_root": _root(root),
            "resources": _resources(root),
            "amounts": _amounts(),
            "host_binding": host_binding_sha256,
            "launch": launch_sha256,
            "operation": operation,
            "prior": prior,
            "control": control_sha256,
            "quotas": _quotas(peer),
            **CLAIMS,
        }
        fixed._write(root / "permit", fixed.raw.META, permit)
        fixed._write(
            root / "control",
            fixed.raw.META,
            {
                "consumed": False,
                "phase": "READY",
                "requests": 0,
                "next": 0,
                "headers": 0,
                "payload": 0,
                "body_bytes": 0,
                "page_bytes": 0,
                "body_puts": 0,
                "page_puts": 0,
                "prepared": None,
            },
        )
        fixed.raw._sync(root)
        fixed.raw._sync(peer.root)
        return {
            "permit_sha256": fixed.raw._sha(fixed.raw._encoded(permit)),
            "permit": fixed._copy(permit),
        }


# Read bounded positive fragments without accepting EOF or overreads.
def _receive(stream, amount):
    result = bytearray()
    while len(result) < amount:
        wanted = min(fixed.raw.READ, amount - len(result))
        value = stream.read(wanted)
        fixed.raw._require(
            type(value) is bytes and 0 < len(value) <= wanted,
            "Truncated, invalid or overread stream fragment",
        )
        result.extend(value)
    return bytes(result)


# Flush a bounded response without claiming the caller received its ACK.
def _send(stream, value):
    encoded = fixed.raw._encoded(value)
    fixed.raw._require(
        0 < len(encoded) < fixed.raw.META, "Response envelope cap exceeded"
    )
    framed = len(encoded).to_bytes(8, "big") + encoded + TRAILER
    offset = 0
    while offset < len(framed):
        value = stream.write(framed[offset : offset + fixed.raw.READ])
        fixed.raw._require(
            type(value) is int
            and 0 < value <= min(fixed.raw.READ, len(framed) - offset),
            "Response write failed or exceeded request",
        )
        offset += value
    stream.flush()


# Serve only a unique synthetic ordinary stream or one read-only STATUS request.
class Server:
    # Require externally pinned launch/host/permit plus actual owned local resources.
    def __init__(
        self,
        peer,
        *,
        expected_permit_sha256,
        expected_host_binding_sha256,
        expected_launch_sha256,
    ):
        fixed.raw._require(type(peer) is fixed.Peer, "Exact local Peer required")
        for digest in (
            expected_permit_sha256,
            expected_host_binding_sha256,
            expected_launch_sha256,
        ):
            fixed.raw._digest(digest)
        self.peer, self.root = peer, peer.root / "rpc-session"
        self.permit = fixed._read(self.root / "permit", fixed.raw.META)
        keys = {
            "version",
            "scope",
            "sources",
            "peer",
            "owner",
            "binding",
            "peer_header",
            "profile",
            "peer_root",
            "session_root",
            "resources",
            "amounts",
            "host_binding",
            "launch",
            "operation",
            "prior",
            "control",
            "quotas",
            *CLAIMS,
        }
        fixed.raw._require(
            type(self.permit) is dict
            and set(self.permit) == keys
            and fixed.raw._sha(fixed.raw._encoded(self.permit))
            == expected_permit_sha256,
            "Exact external permit required",
        )
        self.pin = expected_permit_sha256
        fixed.raw._require(
            self.permit["version"] == VERSION
            and self.permit["scope"] == "SYNTHETIC_STREAM_ONLY"
            and self.permit["host_binding"] == expected_host_binding_sha256
            and self.permit["launch"] == expected_launch_sha256
            and self.permit["quotas"] == _quotas(peer)
            and self.permit["amounts"] == _amounts()
            and all(self.permit[key] is False for key in CLAIMS),
            "Launch, scope or quota differs",
        )
        fixed.raw._require(
            type(self.permit["operation"]) is int
            and 0 <= self.permit["operation"] < peer.limits["operations"],
            "Exact pinned operation required",
        )
        for key in ("prior", "control"):
            fixed.raw._digest(self.permit[key])
        self._bound()

    # Recheck source/profile and actual future session-file ownership.
    def _bound(self):
        self.peer._declaration()
        value = self.permit
        fixed.raw._require(
            fixed._read(self.root / "permit", fixed.raw.META) == value
            and value["sources"] == _sources()
            and value["peer"] == self.peer.header["peer"]
            and value["owner"] == self.peer.common["owner"]
            and value["binding"] == self.peer.binding
            and value["profile"] == self.peer.common["identity_sha256"]
            and value["peer_header"]
            == fixed.raw._sha(fixed.raw._encoded(self.peer.header))
            and value["peer_root"] == _root(self.peer.root)
            and value["session_root"] == _root(self.root)
            and value["resources"] == _resources(self.root),
            "Pinned source/peer/root resources differ",
        )

    # Retain exact cumulative charges and consumed state across every stream failure.
    def _control(self):
        value = fixed._read(self.root / "control", fixed.raw.META)
        keys = {
            "consumed",
            "phase",
            "requests",
            "next",
            "headers",
            "payload",
            "body_bytes",
            "page_bytes",
            "body_puts",
            "page_puts",
            "prepared",
        }
        fixed.raw._require(
            type(value) is dict
            and set(value) == keys
            and type(value["consumed"]) is bool
            and type(value["phase"]) is str
            and value["phase"] in PHASES,
            "Exact session control required",
        )
        counters = (
            "requests",
            "next",
            "headers",
            "payload",
            "body_bytes",
            "page_bytes",
            "body_puts",
            "page_puts",
        )
        fixed.raw._require(
            all(type(value[key]) is int and 0 <= value[key] < 2**63 for key in counters)
            and value["next"] <= value["requests"]
            and value["requests"] <= self.permit["quotas"]["frames"]
            and value["headers"] == value["requests"] * (fixed.raw.META + 16),
            "Session counter state differs",
        )
        for key, quota in (
            ("payload", "payload_bytes"),
            ("body_bytes", "body_bytes"),
            ("page_bytes", "page_bytes"),
            ("body_puts", "body_puts"),
            ("page_puts", "page_puts"),
        ):
            fixed.raw._require(
                value[key] <= self.permit["quotas"][quota], "Ingress quota exceeded"
            )
        fixed.raw._require(
            value["payload"] == value["body_bytes"] + value["page_bytes"],
            "Ingress charge domains differ",
        )
        if not value["consumed"]:
            fixed.raw._require(
                value["phase"] == "READY"
                and all(value[key] == 0 for key in counters)
                and value["prepared"] is None,
                "Unused control differs",
            )
        else:
            fixed.raw._require(value["phase"] != "READY", "Consumed phase differs")
        fixed.raw._require(
            value["phase"] != "PREPARED" or value["prepared"] is not None,
            "Prepared reference missing",
        )
        if value["prepared"] is not None:
            self.peer._reference(value["prepared"])
            fixed.raw._require(
                value["prepared"]["kind"] == "page"
                and value["phase"] in {"PREPARED", "PAUSED"},
                "Prepared session reference differs",
            )
        return value

    # Authenticate consumption even if the mutable control write was interrupted.
    def _session(self):
        value = fixed._read(self.root / "session", fixed.raw.META)
        expected = {
            "permit": self.pin,
            "launch": self.permit["launch"],
            "operation": self.permit["operation"],
            "prior": self.permit["prior"],
            "peer_control": self.permit["control"],
        }
        fixed.raw._require(
            value is None or value == expected, "Immutable session consumption differs"
        )
        return value

    # Persist one detached session state without creating a new namespace entry.
    def _store(self, value):
        fixed._write(self.root / "control", fixed.raw.META, value)

    # Observe only infrastructure fixture fault cuts, never a native/model result.
    def point(self, name):
        pass

    # Serialize this sidecar and its exact Peer through continuous real kernel locks.
    @contextmanager
    def _locked(self):
        path = self.root / "lock"
        before = fixed.raw._extent(path, 4096, 1)
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            fixed.raw._opened(path, descriptor, before)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise fixed.raw.PhysicalPause("RPC session already active") from error
            fixed.raw._opened(path, descriptor, before)
            with self.peer._locked():
                yield
            fixed.raw._opened(path, descriptor, before)
        finally:
            os.close(descriptor)

    # Consume the immutable ordinary-session grant before its first external read.
    def _consume(self):
        control, peer = self._control(), self.peer._control()
        fixed.raw._require(
            not control["consumed"]
            and control["phase"] == "READY"
            and self._session() is None
            and peer["open"] is None
            and fixed.raw._sha(fixed.raw._encoded(peer)) == self.permit["control"],
            "Consumed or uncertain session: STATUS only",
        )
        self.peer._resources()
        receipt = {
            "permit": self.pin,
            "launch": self.permit["launch"],
            "operation": self.permit["operation"],
            "prior": self.permit["prior"],
            "peer_control": self.permit["control"],
        }
        fixed._write(self.root / "session", fixed.raw.META, receipt)
        control.update(consumed=True, phase="CONSUMED")
        self._store(control)
        self.point("session_consumed")

    # Charge one maximum header frame before requesting even its length prefix.
    def _header(self, incoming, *, ordinary):
        if ordinary:
            control = self._control()
            fixed.raw._require(
                control["requests"] < self.permit["quotas"]["frames"],
                "Frame quota exhausted",
            )
            control["requests"] += 1
            control["headers"] += fixed.raw.META + 16
            self._store(control)
        amount = int.from_bytes(_receive(incoming, 8), "big")
        fixed.raw._require(0 < amount < fixed.raw.META, "Header cap exceeded")
        value = fixed.raw._decoded(_receive(incoming, amount))
        self._shape(value, ordinary=ordinary)
        return value

    # Admit only exact finite headers and externally pinned operation/control preimages.
    def _shape(self, value, *, ordinary):
        fixed.raw._require(
            type(value) is dict and set(value) == FIELDS, "Exact wire header required"
        )
        fixed.raw._require(
            value["version"] == VERSION
            and value["permit"] == self.pin
            and value["launch"] == self.permit["launch"]
            and value["peer"] == self.permit["peer"]
            and type(value["operation"]) is int
            and value["operation"] == self.permit["operation"]
            and value["prior"] == self.permit["prior"]
            and type(value["request"]) is int
            and value["request"] >= 0
            and type(value["verb"]) is str
            and value["verb"] in VERBS
            and type(value["args"]) is dict
            and type(value["payload_bytes"]) is int
            and value["payload_bytes"] >= 0,
            "Wire source/operation/shape differs",
        )
        fixed.raw._digest(value["payload_sha256"])
        control = self._control()
        if ordinary:
            fixed.raw._require(
                value["request"] == control["next"], "Repeated wire sequence refused"
            )
        else:
            fixed.raw._require(
                value["verb"] == "STATUS" and value["request"] == 0,
                "Reopened channel is STATUS only",
            )
        if value["verb"] == "STATUS":
            fixed.raw._require(
                value["control"] is None, "STATUS has no mutation preimage"
            )
        else:
            fixed.raw._require(
                value["control"]
                == fixed.raw._sha(fixed.raw._encoded(self.peer._control())),
                "Peer control preimage differs",
            )

    # Charge bytes and per-kind counts durably before consuming any declared payload.
    def _payload(self, incoming, header, *, ordinary):
        control, verb = self._control(), header["verb"]
        amount = header["payload_bytes"]
        if verb == "PUT":
            args = header["args"]
            fixed.raw._require(
                ordinary
                and control["phase"] == "ARMED"
                and set(args) == {"kind"}
                and type(args["kind"]) is str
                and args["kind"] in {"body", "page"},
                "ARMED PUT shape required",
            )
            kind = args["kind"]
            cap = (
                self.peer.limits["span_bytes"] if kind == "body" else fixed.raw.META - 1
            )
            fixed.raw._require(0 < amount <= cap, "Binary body cap exceeded")
            control["payload"] += amount
            control[f"{kind}_bytes"] += amount
            control[f"{kind}_puts"] += 1
            quotas = self.permit["quotas"]
            fixed.raw._require(
                control["payload"] <= quotas["payload_bytes"]
                and control[f"{kind}_bytes"] <= quotas[f"{kind}_bytes"]
                and control[f"{kind}_puts"] <= quotas[f"{kind}_puts"],
                "Cumulative ingress exhausted before body read",
            )
        else:
            expected = {"root"} if verb == "VERIFY" else set()
            fixed.raw._require(
                set(header["args"]) == expected
                and amount == 0
                and header["payload_sha256"] == EMPTY,
                "Unexpected payload or verb arguments",
            )
        if ordinary:
            control["next"] += 1
            self._store(control)
        self.point("put_ingress_charged" if verb == "PUT" else "header_validated")
        value = _receive(incoming, amount)
        fixed.raw._require(
            _receive(incoming, len(TRAILER)) == TRAILER, "Frame trailer differs"
        )
        fixed.raw._require(
            fixed.raw._sha(value) == header["payload_sha256"],
            "Binary body hash differs",
        )
        return value

    # Return bounded state/witness hashes without any permission to replay or adopt.
    def _status(self):
        control, peer = self._control(), self.peer._control()
        peer_digest = fixed.raw._sha(fixed.raw._encoded(peer))
        recorded = self._session() is not None
        arm = self.peer._record(self.permit["operation"], "ARM")
        prepared = self.peer._record(self.permit["operation"], "PREPARED")
        return {
            "rpc": control,
            "peer_control": peer_digest,
            "peer_open": peer["open"],
            "permit": self.pin,
            "session_recorded": recorded,
            "ordinary_available": not recorded
            and not control["consumed"]
            and peer["open"] is None
            and peer_digest == self.permit["control"],
            "arm": fixed.raw._sha(fixed.raw._encoded(arm)) if arm is not None else None,
            "prepared": fixed.raw._sha(fixed.raw._encoded(prepared))
            if prepared is not None
            else None,
            **CLAIMS,
        }

    # Dispatch explicit checkpoint-only verbs with no caller-controlled method lookup.
    def _dispatch(self, header, payload, *, ordinary):
        self._bound()
        control, verb = self._control(), header["verb"]
        if verb == "STATUS":
            return self._status()
        fixed.raw._require(ordinary, "Mutation requires unique ordinary channel")
        if verb == "HELLO":
            fixed.raw._require(
                control["phase"] == "CONSUMED" and header["request"] == 0,
                "Initial HELLO required",
            )
            control["phase"] = "HELLO"
            self._store(control)
            return {
                "sources": self.permit["sources"],
                "profile": self.permit["profile"],
                "resources": self.permit["resources"],
                **CLAIMS,
            }
        if verb == "ARM":
            fixed.raw._require(control["phase"] == "HELLO", "HELLO before ARM required")
            witness = self.peer._arm(self.permit["operation"], self.permit["prior"])
            control["phase"] = "ARMED"
            self._store(control)
            self.point("arm_readback")
            return {"arm": witness, **CLAIMS}
        if verb == "PUT":
            return {
                "reference": self.peer._put(
                    self.permit["operation"], header["args"]["kind"], payload
                ),
                **CLAIMS,
            }
        fixed.raw._require(
            verb == "VERIFY" and control["phase"] == "ARMED", "ARMED VERIFY required"
        )
        reference = fixed._copy(header["args"]["root"])
        witness = self.peer._prepare(
            self.permit["operation"], self.permit["prior"], reference
        )
        control.update(phase="PREPARED", prepared=reference)
        self._store(control)
        self.point("prepared_readback")
        return {"prepared": witness, "root": reference, **CLAIMS}

    # Preserve consumed/charged uncertainty without refunding or touching Peer effects.
    def _pause(self):
        try:
            control = self._control()
            control.update(consumed=True, phase="PAUSED")
            self._store(control)
        except (OSError, ValueError):
            pass

    # Hold both locks across a finite stream and never replay after a broken channel.
    def serve(self, incoming, outgoing, *, ordinary):
        fixed.raw._require(type(ordinary) is bool, "Explicit channel mode required")
        with self._locked():
            self._bound()
            if ordinary:
                self._consume()
            try:
                while True:
                    header = self._header(incoming, ordinary=ordinary)
                    payload = self._payload(incoming, header, ordinary=ordinary)
                    result = self._dispatch(header, payload, ordinary=ordinary)
                    terminal = not ordinary or self._control()["phase"] == "PREPARED"
                    if terminal:
                        remaining = incoming.read(1)
                        fixed.raw._require(
                            type(remaining) is bytes and remaining == b"",
                            "Terminal frame requires input EOF",
                        )
                    self._bound()
                    response = {
                        "version": VERSION,
                        "request": header["request"],
                        "result": result,
                        "status": self._status(),
                    }
                    self.point("before_response")
                    _send(outgoing, response)
                    self.point("response_flushed")
                    if terminal:
                        return response
            except BaseException:
                if ordinary:
                    self._pause()
                raise
