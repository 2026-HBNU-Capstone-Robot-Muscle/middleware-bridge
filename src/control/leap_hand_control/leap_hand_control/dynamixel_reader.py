"""Dynamixel Protocol2 READ-only backend; no write or torque-enable calls."""

import time

from leap_hand_control.hardware_adapter import AdapterError, HandSample


def signed(value, bits):
    return value-(1 << bits) if value >= (1 << (bits-1)) else value


class DynamixelReader:
    simulated = False
    motion_capable = False

    def __init__(self, port, *, baud=1_000_000, sdk=None, now=time.monotonic):
        if not isinstance(port, str) or not port.strip():
            raise ValueError('An explicit port is required; COM7 is not portable.')
        if baud != 1_000_000:
            raise ValueError('This reader uses the recorded1Mbps link.')
        self.device, self.baud, self.sdk, self.now = port, baud, sdk, now
        self.port = None
        self.group = None
        self.inventory = []

    def open(self):
        if self.sdk is None:
            import dynamixel_sdk
            self.sdk = dynamixel_sdk
        self.port = self.sdk.PortHandler(self.device)
        try:
            if not self.port.openPort() or not self.port.setBaudRate(self.baud):
                raise RuntimeError('Cannot open configured motor port.')
            self.packet = self.sdk.PacketHandler(2.0)
            for motor in range(1, 17):
                model, comm, error = self.packet.ping(self.port, motor)
                if comm != self.sdk.COMM_SUCCESS or error or model != 1240:
                    raise RuntimeError(f'ID{motor} inventory mismatch/communication error.')
                self.inventory.append(dict(id=motor, model=model))
            self.group = self.sdk.GroupSyncRead(self.port, self.packet, 64, 83)
            for motor in range(1, 17):
                if not self.group.addParam(motor):
                    raise RuntimeError('Cannot configure all16 motor read parameters.')
        except Exception:
            self.close()
            raise

    def read(self, acquired_at):
        began = self.now()
        comm = self.group.txRxPacket()
        if comm != self.sdk.COMM_SUCCESS:
            raise RuntimeError(f'Full motor state read failed: comm={comm}')
        if self.now()-began > .15:
            raise RuntimeError('Motor state read exceeded150ms; discard snapshot.')
        values = {name: [] for name in ('position', 'goal', 'current', 'voltage',
                                        'temperature', 'torque', 'error')}
        fields = (('position', 132, 4), ('goal', 116, 4), ('current', 126, 2),
                  ('voltage', 144, 2), ('temperature', 146, 1),
                  ('torque', 64, 1), ('error', 70, 1))
        for motor in range(1, 17):
            for key, address, size in fields:
                if not self.group.isAvailable(motor, address, size):
                    raise RuntimeError(f'ID{motor} partial snapshot; discard all16 values.')
                values[key].append(self.group.getData(motor, address, size))
        return HandSample(
            acquired_at, tuple(signed(v, 32) for v in values['position']),
            tuple(signed(v, 32) for v in values['goal']),
            tuple(float(signed(v, 16)) for v in values['current']),
            tuple(v/10. for v in values['voltage']), tuple(values['temperature']),
            tuple(values['torque']), tuple(values['error']))

    def begin(self, command, now):
        raise AdapterError('READ_ONLY', 'No motor command is implemented by this state reader.')

    def completed(self, now):
        return False

    def stop(self):
        pass  # READ-only means no torque/goal/EEPROM writes, even on failure.

    def close(self):
        if self.port is not None:
            self.port.closePort()
            self.port = None
