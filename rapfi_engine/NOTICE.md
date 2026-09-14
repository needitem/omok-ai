# Third-party engine assets (`rapfi_engine/`)

The files in this directory are **not** first-party. They are redistributed
from the **Rapfi** project by dhbloo.

- Upstream source: https://github.com/dhbloo/rapfi
- Upstream neural-network weights: https://github.com/dhbloo/rapfi (the `Networks` submodule)

## Contents & licenses

| File | What it is | License |
|------|------------|---------|
| `pbrain-rapfi` | Prebuilt Rapfi engine binary (Piskvork/pbrain protocol) | **GPL-3.0** — see `COPYING.GPLv3.txt` |
| `*.bin.lz4`, `model210901.bin` | NNUE / neural-network weights | **CC0-1.0** (public domain) |
| `config.toml` | Rapfi runtime config (bundled with the weights) | CC0-1.0 |

## GPL-3.0 compliance (the `pbrain-rapfi` binary)

`pbrain-rapfi` is a compiled build of GPL-3.0 licensed source. Under GPL-3.0
§6, the corresponding source is offered here by reference to the upstream
repository, from which the exact version can be built:

    https://github.com/dhbloo/rapfi

> Note: this binary was built for **Linux / ARM aarch64** (originally on an
> NVIDIA Jetson). It will not run on x86-64 or other platforms. To use Rapfi
> elsewhere, build it from the upstream source above and drop the resulting
> `pbrain-rapfi` (and the weights) into this directory.

## Relationship to the first-party code

`rapfi_bot.py` communicates with `pbrain-rapfi` only as a **separate process**
over the standard pbrain protocol (arm's-length invocation). The first-party
Python code is therefore a separate work under the MIT license (see the
top-level `LICENSE`); the GPL-3.0 binary is merely aggregated here for
convenience.
