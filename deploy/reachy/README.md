# Robot-host deployment

Daemon installer, systemd units (the daemon; `reachy-embodiment.service`,
which starts the container only after the daemon's camera socket exists;
and, on the designated production Nano only, `reachy-daemon-recovery.service`,
which restarts a daemon in `state: error` once per boot) and robot
environment template. The confirmed
host is the original Jetson Nano; physical acceptance remains incomplete.

- [Guide](../../docs/deployment.md#robot-host-and-jetson-nano)
- [Development and verification](../../docs/development.md)
- [Documentation index](../../docs/README.md)
