# SukiSU 41165 / SuSFS Runtime v1 / SUSFS 2.4.0

The complete 41159 branch is retained. BASELINE.json and contract.py compare all
build inputs with that branch. The new SukiSU pin is d7d04281, version41165.
The four global runtime flags, root/KSU-domain authorization, generation CAS,
mutex and fixed-size ABI are unchanged. Each compiled filter retains its prior
boot default. Changing flags does not erase registered rules.

release240.py applies only the official v2.4.0 release macro after all existing
functional source checks; the whole final header is bound to the independently
compiled SHA-256. Final Image attestation requires its receipt and v2.4.0 string.

Fresh local evidence is recorded by sukisu-41165-susfs/PREFLIGHT.json:80 ARM64
objects, semantic fault tests and16 runtime configurations/1069 assertions.
Full CI link, firmware CRCs, flash packaging and device boot remain separate.
