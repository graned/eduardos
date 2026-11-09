"""One-shot root session + two Unix sockets + real sealed memfds, NO DISKS.

The physical hardware preflight is intentionally replaced with a fixed
read-only manifest fixture. Actual kernel disk ancestry is exercised by
the existing preflight/preview tests and the PR #39 adversarial QEMU.
"""
from __future__ import annotations

from array import array
from contextlib import contextmanager
import copy
import hashlib
import json
import os
import socket
import time
import unittest
from unittest.mock import patch

import forge_disk_identity as identity
import forge_execution_rehearsal as session
import forge_local_ipc as ipc
import forge_local_service as local
import forge_physical_preview as preview
import forge_privileged_protocol as protocol
import forge_secret_handoff as handoff


DISK = "/dev/disk/by-id/wwn-QEMU-execution-rehearsal-only"
LUKS = "EDOS-public-fixture-LUKS-41"
ACCOUNT = "EDOS-public-fixture-account-41"
DEVICE = {name: None for name in identity.FIELDS}
DEVICE.update({
    "path": "/dev/vdb", "size": 64 * 1024**3, "maj:min": "8:16",
})
SNAP = {
    "schema": identity.SCHEMA, "boot_id": identity.boot_id(),
    "stable_id": DISK, "device": DEVICE, "layout": [],
    "eligible": True, "blockers": [],
}
REVIEW = {
    "snapshot": SNAP, "sha256": identity.fingerprint(SNAP),
    "write_operations_enabled": False,
}


def request(review=REVIEW):
    return {
        "version": protocol.SCHEMA,
        "operation": protocol.OPERATION,
        "review": copy.deepcopy(review),
        "confirmation": "ERASE " + DISK,
        "username": "testpilot",
        "hostname": "edos-installed",
    }


def preview_report(*, plan=None):
    manifest = plan if plan is not None else {
        "version": preview.SCHEMA,
        "kind": "non-executable-installation-preview",
        "disk_id": DISK,
        "target_devno": "8:16",
        "boot_id": SNAP["boot_id"],
        "disk_review_sha256": REVIEW["sha256"],
        "account": "testpilot",
        "hostname": "edos-installed",
        "storage_intent": {
            "partition_table": "gpt",
            "esp_size_mib": 1024,
            "esp_filesystem": "vfat",
            "encryption": "luks2",
            "encrypted_filesystem": "btrfs",
            "subvolumes": list(preview._SUBVOLUMES),
            "mountpoints": list(preview._MOUNTPOINTS),
        },
        "intended_phases": [
            {"id": name, "description": description, "executable": False}
            for name, description in preview._INTENDED_PHASES
        ],
        "write_operations_enabled": False,
        "destructive_disk_operations_enabled": False,
        "credential_writes_enabled": False,
        "authorization_to_write": False,
    }
    report = {
        "version": preview.SCHEMA,
        "status": "preview-read-only",
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(
            identity.canonical(manifest)
        ).hexdigest(),
    }
    report.update({flag: False for flag in session._NO_WRITE_FLAGS})
    return report


class Clock:
    def __init__(self):
        self.value = time.monotonic()

    def __call__(self):
        return self.value


class ExecutionRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.pclient, self.pserver = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_SEQPACKET,
        )
        self.cclient, self.cserver = socket.socketpair(
            socket.AF_UNIX, socket.SOCK_SEQPACKET,
        )
        for sock in (
            self.pclient, self.pserver, self.cclient, self.cserver
        ):
            self.addCleanup(sock.close)
        self.peer = ipc.PeerIdentity(
            os.getpid(), os.getuid(), os.getgid(),
        )
        self.consent = []
        self.clock = Clock()

    def trusted(self, *, peer=None, local_consent=None, review=None):
        def approval(phrase):
            self.consent.append(phrase)
            return phrase

        return local.TrustedIntent(
            peer=self.peer if peer is None else peer,
            review=copy.deepcopy(REVIEW if review is None else review),
            username="testpilot", hostname="edos-installed",
            local_consent=(
                approval if local_consent is None else local_consent
            ),
            clock=self.clock,
        )

    def send_preflight(self, *, message=None):
        packet = request() if message is None else message
        self.pclient.send(identity.canonical(packet))

    def send_credentials(self):
        with handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
            ipc.OneShotLocalSender(self.cclient, self.peer).send(fds)

    def execute(self, intent, *, previews=None, handler=None):
        reports = ([preview_report(), preview_report()]
                   if previews is None else previews)
        approved = {
            "version": protocol.SCHEMA,
            "status": "attested-read-only",
            "write_operations_enabled": False,
            "destructive_disk_operations_enabled": False,
            "credential_writes_enabled": False,
            "authorization_to_write": False,
        }
        with patch.object(session.os, "geteuid", return_value=0), \
             patch.object(local.protocol, "handle_request",
                          return_value=approved) as backend, \
             patch.object(preview, "preview_request",
                          side_effect=reports) as preview_call:
            outcome = session.OneShotExecutionRehearsal(intent).run(
                self.pserver, self.cserver,
            ) if handler is None else handler(intent)
        return outcome, backend, preview_call

    def test_successful_real_kernel_socket_fd_roundtrip_is_readonly(self):
        intent = self.trusted()
        self.send_preflight()
        self.send_credentials()
        outcome, backend, previews = self.execute(intent)
        self.assertEqual(
            outcome["status"], "rehearsal-complete-read-only",
        )
        self.assertEqual(outcome["manifest_sha256"],
                         preview_report()["manifest_sha256"])
        self.assertTrue(outcome["credential_transport_verified"])
        self.assertEqual(self.consent, ["ERASE " + DISK])
        self.assertEqual(previews.call_count, 2)
        backend.assert_called_once()
        for flag in session._NO_WRITE_FLAGS:
            self.assertIs(outcome[flag], False)
        packet = json.loads(self.pclient.recv(4096))
        self.assertEqual(packet["status"], "attested-read-only")
        for secret in (LUKS, ACCOUNT):
            self.assertNotIn(secret, json.dumps(outcome))
            self.assertNotIn(secret, json.dumps(packet))

        # Both previews come from the ROOT-selected review, never from
        # credential socket data or a client-selected command.
        for call in previews.call_args_list:
            req = protocol.parse_request(call.args[0])
            self.assertEqual(req.review, REVIEW)
            self.assertEqual(req.username, "testpilot")
            self.assertEqual(req.hostname, "edos-installed")

    def test_replay_or_second_attempt_never_reads_another_credential(self):
        intent = self.trusted()
        self.send_preflight()
        self.send_credentials()
        captures = []
        instance = session.OneShotExecutionRehearsal(intent)
        with patch.object(session.os, "geteuid", return_value=0), \
             patch.object(local.protocol, "handle_request",
                          return_value={"version": protocol.SCHEMA,
                                        "status": "attested-read-only",
                                        "authorization_to_write": False,
                                        "write_operations_enabled": False}), \
             patch.object(preview, "preview_request",
                          side_effect=[preview_report(), preview_report()]), \
             patch.object(ipc, "OneShotLocalReceiver",
                          wraps=ipc.OneShotLocalReceiver) as recv:
            first = instance.run(self.pserver, self.cserver)
            second = instance.run(self.pserver, self.cserver)
        self.assertEqual(first["status"], "rehearsal-complete-read-only")
        self.assertEqual(second["status"], "refused")
        recv.assert_called_once()
        self.assertTrue(intent.used)

    def test_nonroot_refuses_before_socket_or_consent(self):
        intent = self.trusted()
        instance = session.OneShotExecutionRehearsal(intent)
        with patch.object(session.os, "geteuid", return_value=1000), \
             patch.object(ipc, "_verify_peer") as verify, \
             patch.object(local, "serve_one_connected") as preflight, \
             patch.object(preview, "preview_request") as root_preview:
            first = instance.run(self.pserver, self.cserver)
            second = instance.run(self.pserver, self.cserver)
        self.assertEqual(first["status"], "refused")
        self.assertEqual(second["status"], "refused")
        self.assertFalse(intent.used)
        verify.assert_not_called()
        preflight.assert_not_called()
        root_preview.assert_not_called()
        self.assertEqual(self.consent, [])

    def test_wrong_peer_on_second_channel_denied_before_consent(self):
        intent = self.trusted()
        with patch.object(session.os, "geteuid", return_value=0), \
             patch.object(ipc, "_verify_peer",
                          side_effect=[None, ipc.Refused("wrong client PID")]) as peer, \
             patch.object(local, "serve_one_connected") as preflight:
            outcome = session.OneShotExecutionRehearsal(intent).run(
                self.pserver, self.cserver,
            )
        self.assertEqual(outcome["status"], "refused")
        self.assertEqual(peer.call_count, 2)
        preflight.assert_not_called()
        self.assertEqual(self.consent, [])

    def test_root_policy_mutations_rejected_before_socket_request(self):
        for field in ("disk", "username", "hostname", "pid", "deadline"):
            with self.subTest(field=field):
                intent = self.trusted()
                run = session.OneShotExecutionRehearsal(intent)
                if field == "disk":
                    intent.review["snapshot"]["stable_id"] = "/dev/disk/by-id/other"
                elif field == "username":
                    intent.username = "hacker"
                elif field == "hostname":
                    intent.hostname = "other-host"
                elif field == "pid":
                    intent.peer = ipc.PeerIdentity(
                        os.getpid() + 1, os.getuid(), os.getgid(),
                    )
                else:
                    intent.deadline += 100
                with patch.object(session.os, "geteuid", return_value=0), \
                     patch.object(ipc, "_verify_peer") as verify:
                    outcome = run.run(self.pserver, self.cserver)
                self.assertEqual(outcome["status"], "refused")
                verify.assert_not_called()

    def test_stale_boot_and_expired_consent_refuse(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                intent = self.trusted()
                if expired:
                    self.clock.value = intent.deadline
                run = session.OneShotExecutionRehearsal(intent)
                with patch.object(session.os, "geteuid", return_value=0), \
                     patch.object(session.identity, "boot_id",
                                  return_value="changed-boot" if not expired
                                  else SNAP["boot_id"]), \
                     patch.object(local, "serve_one_connected") as preflight:
                    result = run.run(self.pserver, self.cserver)
                self.assertEqual(result["status"], "refused")
                preflight.assert_not_called()

    def test_failed_consent_blocks_manifest_and_credential_receive(self):
        intent = self.trusted(local_consent=lambda _: "NO")
        self.send_preflight()
        self.send_credentials()  # already queued; must remain unread
        with patch.object(session.os, "geteuid", return_value=0), \
             patch.object(preview, "preview_request") as previews, \
             patch.object(ipc, "OneShotLocalReceiver") as receiver:
            result = session.OneShotExecutionRehearsal(intent).run(
                self.pserver, self.cserver,
            )
        self.assertEqual(result["status"], "refused")
        previews.assert_not_called()
        receiver.assert_not_called()
        self.assertTrue(intent.used)

    def test_malicious_format_request_blocks_credentials(self):
        intent = self.trusted()
        attack = request()
        attack["operation"] = "format-disk"
        self.send_preflight(message=attack)
        self.send_credentials()
        with patch.object(session.os, "geteuid", return_value=0), \
             patch.object(preview, "preview_request") as previews, \
             patch.object(ipc, "OneShotLocalReceiver") as receiver:
            result = session.OneShotExecutionRehearsal(intent).run(
                self.pserver, self.cserver,
            )
        self.assertEqual(result["status"], "refused")
        previews.assert_not_called()
        receiver.assert_not_called()
        self.assertEqual(
            json.loads(self.pclient.recv(4096))["status"], "refused",
        )

    def test_missing_credential_packet_times_out_without_retry(self):
        intent = self.trusted()
        self.send_preflight()
        with patch.object(session.os, "geteuid", return_value=0), \
             patch.object(ipc, "IO_TIMEOUT_SECONDS", 0.01), \
             patch.object(local.protocol, "handle_request",
                          return_value={"status": "attested-read-only"}), \
             patch.object(preview, "preview_request",
                          return_value=preview_report()) as stages:
            run = session.OneShotExecutionRehearsal(intent)
            first = run.run(self.pserver, self.cserver)
            again = run.run(self.pserver, self.cserver)
        self.assertEqual(first["status"], "refused")
        self.assertEqual(again["status"], "refused")
        self.assertEqual(stages.call_count, 1)

    def test_swapped_or_unsealed_credential_fds_rejected(self):
        for variant in ("swap", "unsealed", "one-fd"):
            with self.subTest(variant=variant):
                # Separate connections per packet to avoid old queued frames.
                pclient, pserver = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                cclient, cserver = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                with pclient, pserver, cclient, cserver, \
                     handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
                    pclient.send(identity.canonical(request()))
                    bad = None
                    try:
                        if variant == "swap":
                            to_send = [fds.account, fds.luks]
                        elif variant == "one-fd":
                            to_send = [fds.luks]
                        else:
                            bad = os.memfd_create(
                                "eduardos-ephemeral-account",
                                os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
                            )
                            os.write(bad, ACCOUNT.encode())
                            to_send = [fds.luks, bad]
                        cclient.sendmsg(
                            [ipc.PROTOCOL_MARKER],
                            [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                              array("i", to_send).tobytes())],
                        )
                        intent = self.trusted()
                        with patch.object(session.os, "geteuid", return_value=0), \
                             patch.object(local.protocol, "handle_request",
                                          return_value={"status": "attested-read-only"}), \
                             patch.object(preview, "preview_request",
                                          return_value=preview_report()) as stages:
                            result = session.OneShotExecutionRehearsal(intent).run(
                                pserver, cserver,
                            )
                        self.assertEqual(result["status"], "refused")
                        self.assertEqual(stages.call_count, 1)
                    finally:
                        if bad is not None:
                            os.close(bad)

    def test_manifest_writes_or_unexpected_commands_refused(self):
        for mutation in ("writer", "extra-phase-key", "different-disk",
                         "forged-digest", "different-layout"):
            with self.subTest(mutation=mutation):
                # Each case owns fresh sockets; no stale frames can leak
                # into the next refusal test.
                pclient, pserver = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                cclient, cserver = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                with pclient, pserver, cclient, cserver, \
                     handoff.sealed_credential_pair(LUKS, ACCOUNT) as fds:
                    pclient.send(identity.canonical(request()))
                    ipc.OneShotLocalSender(cclient, self.peer).send(fds)
                    intent = self.trusted()
                    report = preview_report()
                    if mutation == "writer":
                        report["manifest"]["authorization_to_write"] = True
                    elif mutation == "extra-phase-key":
                        report["manifest"]["intended_phases"][0]["command"] = "sh"
                    elif mutation == "different-disk":
                        report["manifest"]["target_devno"] = "8:32"
                    elif mutation == "forged-digest":
                        report["manifest_sha256"] = "f" * 64
                    else:
                        report["manifest"]["storage_intent"]["esp_size_mib"] = 999
                    with patch.object(session.os, "geteuid", return_value=0), \
                         patch.object(local.protocol, "handle_request",
                                      return_value={"status": "attested-read-only"}), \
                         patch.object(preview, "preview_request",
                                      side_effect=[report]) as stages:
                        outcome = session.OneShotExecutionRehearsal(intent).run(
                            pserver, cserver,
                        )
                    self.assertEqual(outcome["status"], "refused")
                    stages.assert_called_once()

    def test_disk_hotplug_after_receiving_secrets_refuses(self):
        intent = self.trusted()
        self.send_preflight()
        self.send_credentials()
        first = preview_report()
        changed = preview_report()
        changed["manifest"]["intended_phases"][0]["description"] = "altered"
        changed["manifest_sha256"] = hashlib.sha256(
            identity.canonical(changed["manifest"])
        ).hexdigest()
        outcome, _, stages = self.execute(
            intent, previews=[first, changed],
        )
        self.assertEqual(outcome["status"], "refused")
        self.assertEqual(stages.call_count, 2)
        self.assertNotIn(LUKS, json.dumps(outcome))
        self.assertNotIn(ACCOUNT, json.dumps(outcome))

    def test_sealed_mutable_buffers_zeroed_after_rehearsal(self):
        intent = self.trusted()
        self.send_preflight()
        self.send_credentials()
        seen = []
        native = ipc.OneShotLocalReceiver

        def spy(conn, expected):
            receiver = native(conn, expected)

            class Capturing:
                @contextmanager
                def consume(self):
                    with receiver.consume() as buffers:
                        seen.append(buffers)
                        yield buffers
            return Capturing()

        with patch.object(session.os, "geteuid", return_value=0), \
             patch.object(local.protocol, "handle_request",
                          return_value={"status": "attested-read-only"}), \
             patch.object(preview, "preview_request",
                          return_value=preview_report()), \
             patch.object(ipc, "OneShotLocalReceiver", side_effect=spy):
            outcome = session.OneShotExecutionRehearsal(intent).run(
                self.pserver, self.cserver,
            )
        self.assertEqual(outcome["status"], "rehearsal-complete-read-only")
        self.assertEqual(len(seen), 1)
        self.assertEqual(bytes(seen[0].luks), bytes(len(LUKS)))
        self.assertEqual(bytes(seen[0].account), bytes(len(ACCOUNT)))

    def test_same_socket_and_closed_socket_refused(self):
        for both_same in (True, False):
            intent = self.trusted()
            run = session.OneShotExecutionRehearsal(intent)
            if both_same:
                lhs, rhs = self.pserver, self.pserver
            else:
                lhs, rhs = self.pserver, socket.socket(
                    socket.AF_UNIX, socket.SOCK_SEQPACKET,
                )
                rhs.close()
            with patch.object(session.os, "geteuid", return_value=0), \
                 patch.object(ipc, "_verify_peer") as peer:
                result = run.run(lhs, rhs)
            self.assertEqual(result["status"], "refused")
            peer.assert_not_called()

    def test_no_writer_api_or_execution_authority(self):
        for name in (
            "format_disk", "execute", "install", "mount", "stage_account",
            "run_disko", "serve", "main", "grant_root", "authorize_write",
        ):
            self.assertFalse(hasattr(session, name))
        for outcome in (
            session._report("refused"),
            session._report("rehearsal-complete-read-only", digest="0" * 64),
        ):
            self.assertTrue(all(
                outcome[field] is False for field in session._NO_WRITE_FLAGS
            ))


if __name__ == "__main__":
    unittest.main()
