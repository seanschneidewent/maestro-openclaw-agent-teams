# Fleet Runtime Staging (Phase 1)

Fleet remains an active product. During Phase 1 of the package split, core Fleet runtime modules still live in the root `maestro/` package.

- Fleet product CLI is `maestro-fleet`.
- `maestro fleet ...` and `maestro-purchase` remain compatibility aliases during transition.
- New productized Solo work lives under `packages/maestro-solo`.
- Shared extracted primitives live under `packages/maestro-engine`.
- Fleet package wrapper lives under `packages/maestro-fleet`.

Phase 2 moves Fleet internals fully into `packages/maestro-fleet`.
