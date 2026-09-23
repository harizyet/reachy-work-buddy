# reachy-work-buddy

Office work companion built on Reachy Mini. A homelab runs reasoning,
work memory, sessions, and channels; a separate embodiment service keeps
robot presence and fallback independent of homelab availability.

**Start with the [documentation index](docs/README.md).**

- [Deploy the stack or robot](docs/deployment.md)
- [Use chat, calls, and the operator dashboard](docs/operator-guide.md)
- [Develop and test](docs/development.md)
- [Find service APIs and source](docs/reference/services.md)
- [Roadmap and release scope](docs/plan.md#6-implementation-roadmap)
- [Coding-agent instructions](AGENTS.md) and [current handover](HANDOVER.md)

## Status

Phases 0–21 and 22a are implemented. Phase 23 (versioned migrations,
SecretStore, then Gmail/Calendar Accounts) is next. The owner deferred
Phase 22b's physical acceptance until after Phase 23. Phases 24–25 remain
planned. The [roadmap](docs/plan.md#6-implementation-roadmap) owns phase scope;
[verification records](docs/README.md#verification-records) distinguish tested
behavior from outstanding acceptance.

The current robot host is an original Jetson Nano with USB-attached Reachy
hardware. WS connectivity is implemented, but commands still travel by HTTP.
See the [deployment limits](docs/deployment.md#robot-host-and-jetson-nano)
before operating real hardware.

## Repository

| Directory | Contents |
|---|---|
| `services/companion-core` | Reasoning, tools, work data, consent, inference |
| `services/reachy-hub` | Sessions, channels, routing, auth, robot connectivity |
| `services/reachy-embodiment` | Robot backend, semantic behaviour, local presence |
| `clients` | Operator dashboard/chat and WebRTC clients |
| `shared` | Cross-service models and protocol constants |
| `deploy`, `scripts` | Configuration, images, and host launchers |
| `docs` | Guides, roadmap, decisions, and verification evidence |
