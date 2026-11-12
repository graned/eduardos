"""Disposable-QEMU-ONLY one-shot Forge GUI -> existing lab executor bridge.

NOT packaged into eduardOS live ISO or installed systems. The normal Forge
preview server never receives this controller and has no install endpoint.

This root-only controller is independently pre-authorized at startup by a
local operator (or isolated CI harness), verifies the QEMU marker and fixed
/dev/vda hardware contract AGAIN at the action boundary, then runs only the
already audited forge-installer-lab executable. It cannot select an arbitrary
disk, command, closure, identity, or credential based on HTTP input.

The public QEMU test password is read solely from a root-owned /run fixture.
Browser requests NEVER transport secrets. No automatic retry / resume.
"""
from __future__ import annotations

import os
from dataclasses import asdict, replace
from pathlib import Path
import signal
import stat
import subprocess
import threading

import forge_executor_lab as lab
import forge_installer as core
import forge_secret_handoff as handoff
import forge_credentials as credentials
import forge_lab_progress as progress

VERSION = "eduardos.forge.qemu-gui-install.v1"
ALIAS = "/dev/disk/by-id/virtio-root"
HOSTNAME = "edos-installed-lab"
ACCOUNT_FIXTURE = Path("/run/edos-public-user-password")
MAX_STDOUT = 2 * 1024 * 1024
MAX_EVENTS = 16


class Refused(ValueError):
    pass


def _fixture() -> None:
    # Lab executable checks KEYFILE and the VM marker independently.
    info = ACCOUNT_FIXTURE.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o077 or info.st_size < 16
            or info.st_size > 4096):
        raise Refused("Unsafe disposable account fixture")


class LabInstallSession:
    """One local consent, at most one VM install, no physical write support."""

    def __init__(self, executor: str, operator_confirmation: str, *,
                 sealed_credentials: handoff.CredentialFDs | None = None) -> None:
        if (os.geteuid() != 0 or operator_confirmation != lab.CONFIRM
                or not isinstance(executor, str)
                or not executor.startswith("/nix/store/")
                or not Path(executor).is_file()):
            raise Refused("Trusted local QEMU operator and immutable executor required")
        self._sealed_credentials = sealed_credentials
        self._verify_vm()
        self._executor = executor
        self._used = False
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._phases: list[str] = []
        self._state = "awaiting-lab-trigger"
        self._cancel_requested = False

    def _verify_vm(self) -> None:
        secure = self._sealed_credentials is not None
        if lab.check_lab_guard(require_luks=not secure):
            raise Refused("Not a guarded disposable QEMU VM")
        if not Path(ALIAS).is_symlink() or Path(ALIAS).resolve() != Path(lab.TARGET):
            raise Refused("QEMU root disk stable alias differs from /dev/vda")
        if secure:
            # Validate role-labelled sealed descriptors before offering any
            # executable session. This is not consent: constructor requires
            # independent root confirmation; the executor revalidates too.
            handles = self._sealed_credentials
            handoff._assert_fd(handles.luks, credentials.LUKS_MEMFD_LABEL)
            handoff._assert_fd(handles.account, credentials.ACCOUNT_MEMFD_LABEL)
            if (lab.KEYFILE.exists() or lab.KEYFILE.is_symlink()):
                raise Refused("Sealed lab requires an unused LUKS path")
        else:
            _fixture()

    def _disposable_disk(self) -> tuple[core.Disk, dict]:
        """Re-read real inventory; relax ONLY the VM fixture's size minimum.

        The production preview never calls this. The lab executor separately
        requires a disposable QEMU root and reattests its target at execution.
        """
        self._verify_vm()
        system = core.system_preflight()
        disks = core.disk_inventory(core.run_lsblk(), core.stable_ids())
        disk = next((d for d in disks if d.path == lab.TARGET and d.by_id == ALIAS), None)
        if disk is None:
            raise Refused("Trusted disposable VM target missing from inventory")
        if not system["architecture_supported"]:
            raise Refused("Disposable VM system preflight failed")
        # Only the known 12-GiB disposable fixture may relax the production
        # 32-GiB minimum. Never override mounted, swapped, mapped, removable,
        # read-only or unstable disks.
        if disk.reasons not in ((), ("Smaller than the 32 GiB minimum",)):
            raise Refused("Disposable target has an independent safety blocker")
        return replace(disk, eligible=True, reasons=()), system

    def inventory(self) -> dict:
        target, system = self._disposable_disk()
        return {
            "system": system,
            "disks": [asdict(target)],
            "write_operations_enabled": False,
            "mode": "dry-run-only",
            "lab_only": True,
            "note": "Disposable QEMU only: 8-GiB lab minimum, production 32-GiB minimum unchanged.",
        }

    def preview(self, identifier: str) -> dict:
        if identifier != ALIAS:
            raise Refused("Only pinned disposable VM alias can be reviewed")
        target, system = self._disposable_disk()
        # The QEMU installer guest can boot via BIOS and report less than
        # 4 GiB usable RAM even when provisioned with 4096 MiB; the real
        # guarded test already installs into an OVMF/UEFI target with those
        # constraints. These exceptions are lab-only, never production.
        plan = core.preview(target, {**system, "uefi": True,
                                     "sufficient_memory": True})
        if plan["status"] != "ready-for-review" or plan["blockers"]:
            raise Refused("Disposable target preview has blockers")
        plan["lab_only"] = True
        plan["note"] = ("QEMU-only fixture: installer boot mode, available RAM and "
                        "disk size may differ from production requirements.")
        return plan

    def report(self) -> dict:
        with self._lock:
            return {
                "version": VERSION,
                "status": self._state,
                "phases": list(self._phases),
                "complete": self._state == "installed-lab-only",
                "lab_only": True,
                "physical_hardware_supported": False,
                "automatic_retry_enabled": False,
                "authorization_to_write": False,
            }

    def start(self, payload: object) -> dict:
        expected = {
            "operation": "start-disposable-qemu-install",
            "confirmation": lab.CONFIRM,
            "disk_by_id": ALIAS,
            "username": lab.LAB_USERNAME,
            "hostname": HOSTNAME,
        }
        if not isinstance(payload, dict) or payload != expected:
            raise Refused("Lab request differs from fixed trusted VM identity")
        with self._lock:
            if self._used:
                raise Refused("This VM install session has already been used")
            # Consume first, including a failed reattestation. No retry.
            self._used = True
            self._state = "preflight"
        try:
            self._verify_vm()
            with self._lock:
                self._state = "running"
            thread = threading.Thread(target=self._worker, daemon=True)
            thread.start()
        except (OSError, ValueError, RuntimeError):
            with self._lock:
                self._state = "refused-before-execution"
            raise Refused("Disposable QEMU execution preparation refused") from None
        return self.report()

    def cancel(self) -> dict:
        with self._lock:
            if not self._used or self._state != "running":
                raise Refused("No running lab installation to cancel")
            self._cancel_requested = True
            proc = self._process
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        # After format-started, cancellation can leave an irreversibly
        # modified disposable disk. Only terminal evidence may classify it.
        return self.report()

    def _worker(self) -> None:
        output = bytearray()
        try:
            self._verify_vm()
            handles = self._sealed_credentials
            if handles is None:
                # Compatibility with explicitly marked CI fixture mode.
                password_file = ACCOUNT_FIXTURE.open("rb")
                argv = [self._executor, "--execute", "--confirm", lab.CONFIRM,
                        "--user-password-stdin"]
                inherited = ()
            else:
                password_file = subprocess.DEVNULL
                argv = [self._executor, "--execute", "--confirm", lab.CONFIRM,
                        "--sealed-luks-fd", str(handles.luks),
                        "--sealed-account-fd", str(handles.account)]
                inherited = (handles.luks, handles.account)
            try:
                proc = subprocess.Popen(
                    argv, stdin=password_file, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, start_new_session=True,
                    close_fds=True, pass_fds=inherited,
                )
                with self._lock:
                    self._process = proc
                    cancelled = self._cancel_requested
                if cancelled and proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                assert proc.stdout is not None
                for line in proc.stdout:
                    if len(output) + len(line) > MAX_STDOUT:
                        os.killpg(proc.pid, signal.SIGTERM)
                        raise Refused("Lab output exceeds safe bound")
                    output.extend(line)
                    if line.startswith(progress.PREFIX.encode("ascii")):
                        event = line[len(progress.PREFIX):].strip().decode("ascii", "strict")
                        if event not in progress.ORDER and event not in progress.HALTED:
                            os.killpg(proc.pid, signal.SIGTERM)
                            raise Refused("Unknown lab execution event")
                        with self._lock:
                            if len(self._phases) >= MAX_EVENTS:
                                os.killpg(proc.pid, signal.SIGTERM)
                                raise Refused("Excessive lab execution events")
                            self._phases.append(event)
                code = proc.wait(timeout=30)
            finally:
                if handles is None:
                    password_file.close()
            observed = progress.assess(output.decode("utf-8", "strict"), process_returncode=code)
            terminal = observed["status"]
        except (OSError, ValueError, subprocess.SubprocessError, UnicodeError):
            # An interrupted process may have written disk metadata;
            # deliberately DO NOT return "safe to retry".
            terminal = "incomplete-unknown-disk-state"
        with self._lock:
            self._state = terminal
            self._process = None
