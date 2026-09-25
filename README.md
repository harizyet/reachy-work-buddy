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

See [project state](docs/project-state.md) for deployment limits, hardware
findings and outstanding acceptance, and the
[phase ledger](docs/plan.md#6-implementation-roadmap) for delivery status and
next gates. Operational instructions are in [deployment](docs/deployment.md).

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
