# Automatic matching for byte-identical official Kbuild updates

The official main branch replaced ef77212e with b2d01e8b at the same 41183
version while the SuSFS merge repair was being checked. The replacement
includes the two owned-argument corrections upstream, so the narrowly
pin-bound userspace repair correctly becomes a no-op. The official Cargo
manifests and lock remain unchanged locally and are checked against that pin.

To prevent every future unchanged Kbuild update requiring a manual pin-list
entry, the native port now reads the actual Kbuild at the exact checked-out
official source pin and compares the file with git show. It selects the
already audited refresh only for the exact reviewed Git blob
029f391165b27c59cebacc91e94842c2fccdac8e and a valid version/count formula.
An unknown changed Kbuild receives no automatic rewrite; git apply --check
and all following source, kernel, KMI and CRC gates still apply.

The adapter and fixed fragment are copied from this immutable controller
into the ephemeral builder. Existing exact-pin mappings remain supported.
The native-port receipt records both the Kbuild blob and the effective
compatibility patch SHA-256. No source or CRC result is reused from an old run.
