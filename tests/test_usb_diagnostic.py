# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import MagicMock, call, patch

from xg27ucg_fw import cli
from xg27ucg_fw.ddc import DdcMonitor, VcpValue
from xg27ucg_fw.profiles import MCM104
from xg27ucg_fw.scsi import InquiryData, UsbIdentity


REAL_PROBE_USB_DEVICE = cli._probe_usb_device


class UsbDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.monitor = DdcMonitor(1, 7, 'card0-DP-1', 'AUS', 'XG27UCG', 'PRIVATE-MONITOR-SERIAL')
        self.switch = VcpValue(0xDD, 0x12, 0x34, 0x56, 0x78)
        self.mocks = {}
        defaults = {
            'select_target_monitor': {'return_value': self.monitor},
            'get_firmware_number': {'return_value': 101},
            'get_vcp': {'return_value': self.switch},
            'set_usb_update_mode': {},
            '_diagnostic_usb_count': {'side_effect': [0, 1, 0]},
            'discover_target_devices': {'side_effect': [[], ['/dev/sg99'], []]},
            '_probe_usb_device': {'return_value': {
                'ready': True,
                'device': '/dev/sg99',
                'usb': {'serial': 'PRIVATE-USB-SERIAL', 'sysfs_path': '/PRIVATE-PATH'},
                'inquiry': {'vendor': 'GCREADER', 'raw': 'PRIVATE-RAW'},
            }},
            'flash_firmware': {},
        }
        for name, options in defaults.items():
            self.mocks[name] = self.stack.enter_context(patch.object(cli, name, **options))
        self.stack.enter_context(patch.object(cli.time, 'sleep'))

    def run_diagnostic(self, token: str = cli.USB_DIAGNOSTIC_TOKEN):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            status = cli.main(['diagnose-usb', '--bus', '7', '--confirm', token, '--json'])
        return status, json.loads(output.getvalue()) if output.getvalue() else None

    def test_invalid_confirmation_performs_no_io(self) -> None:
        status, _ = self.run_diagnostic('wrong')
        self.assertEqual(status, 4)
        for mock in self.mocks.values():
            mock.assert_not_called()

    def test_mcm101_success_is_redacted_and_restored(self) -> None:
        status, result = self.run_diagnostic()
        self.assertEqual(status, 0)
        self.assertTrue(result['success'])
        self.assertTrue(result['diagnostic_only'])
        self.assertFalse(result['ready_to_flash'])
        self.assertEqual(result['monitor']['firmware_version'], 'MCM101')
        self.mocks['set_usb_update_mode'].assert_has_calls([call(7, True), call(7, False)])
        self.assertEqual(self.mocks['get_firmware_number'].call_count, 2)
        self.assertEqual(self.mocks['get_vcp'].call_count, 2)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.mocks['flash_firmware'].assert_not_called()

    def test_identity_change_before_enable_performs_no_write(self) -> None:
        changed = DdcMonitor(1, 7, 'card0-DP-1', 'AUS', 'XG27UCG', 'OTHER')
        self.mocks['select_target_monitor'].side_effect = [self.monitor, changed]
        status, result = self.run_diagnostic()
        self.assertNotEqual(status, 0)
        self.assertFalse(result['cleanup_attempted'])
        self.mocks['set_usb_update_mode'].assert_not_called()

    def test_existing_usb_endpoint_refuses_to_toggle(self) -> None:
        self.mocks['_diagnostic_usb_count'].side_effect = [1]
        status, result = self.run_diagnostic()
        self.assertNotEqual(status, 0)
        self.assertFalse(result['cleanup_attempted'])
        self.mocks['set_usb_update_mode'].assert_not_called()

    def test_missing_or_multiple_devices_are_cleaned_up(self) -> None:
        for count, devices in [(0, []), (2, ['/dev/sg98', '/dev/sg99']), (1, [])]:
            with self.subTest(count=count, devices=devices):
                self.mocks['_diagnostic_usb_count'].side_effect = [0, count, 0]
                self.mocks['discover_target_devices'].side_effect = [[], devices, []]
                self.mocks['set_usb_update_mode'].reset_mock()
                status, result = self.run_diagnostic()
                self.assertNotEqual(status, 0)
                self.assertTrue(result['cleanup_verified'])
                self.mocks['set_usb_update_mode'].assert_has_calls([call(7, True), call(7, False)])
        self.mocks['_probe_usb_device'].assert_not_called()

    def test_wrong_usb_or_scsi_identity_is_not_accepted(self) -> None:
        self.mocks['_probe_usb_device'].return_value = {'ready': False, 'error': 'PRIVATE-USB-SERIAL'}
        status, result = self.run_diagnostic()
        self.assertNotEqual(status, 0)
        self.assertTrue(result['cleanup_verified'])
        self.assertFalse(result['usb_identity_verified'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_enable_timeout_or_interrupt_still_attempts_cleanup(self) -> None:
        for error in [subprocess.TimeoutExpired('PRIVATE-COMMAND', 20), KeyboardInterrupt()]:
            with self.subTest(error=type(error).__name__):
                self.mocks['_diagnostic_usb_count'].side_effect = [0, 0]
                self.mocks['discover_target_devices'].side_effect = [[], []]
                self.mocks['set_usb_update_mode'].side_effect = [error, None]
                self.mocks['set_usb_update_mode'].reset_mock()
                status, result = self.run_diagnostic()
                self.assertNotEqual(status, 0)
                self.assertTrue(result['cleanup_verified'])
                self.assertNotIn('PRIVATE', json.dumps(result))
                self.mocks['set_usb_update_mode'].assert_has_calls([call(7, True), call(7, False)])

    def test_probe_exception_or_interrupt_still_attempts_cleanup(self) -> None:
        for error in [RuntimeError('PRIVATE'), KeyboardInterrupt()]:
            with self.subTest(error=type(error).__name__):
                self.mocks['_diagnostic_usb_count'].side_effect = [0, 1, 0]
                self.mocks['discover_target_devices'].side_effect = [[], ['/dev/sg99'], []]
                self.mocks['_probe_usb_device'].side_effect = error
                self.mocks['set_usb_update_mode'].reset_mock()
                status, result = self.run_diagnostic()
                self.assertNotEqual(status, 0)
                self.assertTrue(result['cleanup_verified'])
                self.assertNotIn('PRIVATE', json.dumps(result))
                self.mocks['set_usb_update_mode'].assert_has_calls([call(7, True), call(7, False)])

    def test_changed_identity_before_cleanup_refuses_wrong_monitor_write(self) -> None:
        changed = DdcMonitor(1, 7, 'card0-DP-1', 'AUS', 'XG27UCG', 'OTHER')
        self.mocks['select_target_monitor'].side_effect = [self.monitor, self.monitor, changed]
        status, result = self.run_diagnostic()
        self.assertNotEqual(status, 0)
        self.assertFalse(result['cleanup_verified'])
        self.mocks['set_usb_update_mode'].assert_called_once_with(7, True)
        self.assertIn('usb-off --bus 7 --confirm XG27UCG-USB-OFF', result['recovery'])

    def test_cleanup_timeout_is_reported_with_recovery_command(self) -> None:
        self.mocks['set_usb_update_mode'].side_effect = [None, subprocess.TimeoutExpired('PRIVATE', 20)]
        status, result = self.run_diagnostic()
        self.assertNotEqual(status, 0)
        self.assertFalse(result['cleanup_verified'])
        self.assertIn('usb-off --bus 7 --confirm XG27UCG-USB-OFF', result['recovery'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_cleanup_does_not_assume_current_zero_means_disabled(self) -> None:
        self.mocks['get_vcp'].side_effect = [self.switch, VcpValue(0xDD, 0, 1, 0, 0)]
        status, result = self.run_diagnostic()
        self.assertNotEqual(status, 0)
        self.assertFalse(result['cleanup_verified'])

    def test_changed_firmware_after_cleanup_fails(self) -> None:
        self.mocks['get_firmware_number'].side_effect = [101, 104]
        status, result = self.run_diagnostic()
        self.assertNotEqual(status, 0)
        self.assertFalse(result['cleanup_verified'])

    def test_original_usb_on_gate_still_blocks_mcm101(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            status = cli.main(['usb-on', '--target', 'MCM104', '--confirm', cli.USB_ON_TOKEN])
        self.assertEqual(status, 5)
        self.mocks['set_usb_update_mode'].assert_not_called()

    def test_original_flash_gate_still_blocks_mcm101(self) -> None:
        report = MagicMock()
        report.valid = True
        report.profile = MCM104
        report.size = 2_027_558
        report.checksum16 = 0x79F2
        report.final_transfer_bytes = 512
        report.confirmation_token = 'XG27UCG-MCM104-b73131c2'
        report.to_dict.return_value = {
            'model': 'XG27UCG', 'version': 'MCM104', 'size': report.size,
            'sha256': MCM104.payload_sha256, 'valid': True,
        }
        self.mocks['discover_target_devices'].side_effect = None
        self.mocks['discover_target_devices'].return_value = ['/dev/sg99']
        with patch.object(cli.os, 'geteuid', return_value=0), patch.object(
            cli, 'analyze_firmware', return_value=report
        ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = cli.main([
                'flash', '--firmware', 'unused.bin', '--allow-device-write',
                '--confirm', report.confirmation_token,
            ])
        self.assertEqual(status, 3)
        self.mocks['flash_firmware'].assert_not_called()
        self.mocks['set_usb_update_mode'].assert_not_called()

    def test_diagnostic_parser_has_no_firmware_or_device_override(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            for option in ['--firmware', '--device', '--target', '--allow-device-write']:
                with self.subTest(option=option), self.assertRaises(SystemExit):
                    cli.build_parser().parse_args([
                        'diagnose-usb', '--confirm', cli.USB_DIAGNOSTIC_TOKEN, option, 'value'
                    ])

    def test_blank_monitor_serial_refuses_to_toggle(self) -> None:
        self.mocks['select_target_monitor'].return_value = DdcMonitor(
            1, 7, 'card0-DP-1', 'AUS', 'XG27UCG', ''
        )
        status, _ = self.run_diagnostic()
        self.assertNotEqual(status, 0)
        self.mocks['set_usb_update_mode'].assert_not_called()

    def test_cleanup_rejects_persistent_usb_endpoint(self) -> None:
        self.mocks['_diagnostic_usb_count'].side_effect = [0, 1, 1]
        status, result = self.run_diagnostic()
        self.assertNotEqual(status, 0)
        self.assertFalse(result['cleanup_verified'])
        self.assertIn('usb-off --bus 7', result['recovery'])

    def test_real_probe_opens_read_only_and_only_calls_inquiry(self) -> None:
        self.mocks['_probe_usb_device'].side_effect = REAL_PROBE_USB_DEVICE
        inquiry = InquiryData(0, True, 'GCREADER', 'Monitor', '1.0', b'')
        with patch.object(cli, 'usb_identity_for_device', return_value=UsbIdentity(
            0x0B05, 0x1B9C, 'ASUS', 'XG27UCG', 'PRIVATE', '/PRIVATE'
        )), patch.object(cli, 'device_is_mounted', return_value=False), patch.object(
            cli, 'ScsiDevice'
        ) as transport:
            transport.return_value.__enter__.return_value.inquiry.return_value = inquiry
            status, result = self.run_diagnostic()
        self.assertEqual(status, 0)
        self.assertNotIn('PRIVATE', json.dumps(result))
        transport.assert_called_once_with('/dev/sg99', writable=False)
        self.assertEqual(
            transport.return_value.__enter__.return_value.method_calls,
            [call.inquiry()],
        )
        self.mocks['flash_firmware'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
