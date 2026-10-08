# Vendored Ossie schema

`ossie/ossie-schema.json` is the Apache Ossie (incubating) core metadata JSON Schema, copied unmodified.

- Upstream: https://github.com/apache/ossie, path `core-spec/ossie-schema.json`
- Pinned commit: `8dd6732da354f22ca71f16d82626a46039ecdcd9` (2026-10-07)
- Spec version in the schema: `0.2.0.dev0` (a draft; the schema pins it with `const`)
- SHA-256 of the file: `5b9cf15d31057e2b7363194b1c254a6b669fc412b3f8f402d4efbdcfa25fcc87`
- License: Apache License 2.0 (`ossie/LICENSE`); upstream `ossie/NOTICE` is kept alongside.

To move to another spec version, fetch the schema at the new commit, update this file, `PINNED_SPEC_VERSION` and the golden file in
`tests/fixtures/`, and rerun the Ossie tests. The adapter refuses any other version rather than guessing.
