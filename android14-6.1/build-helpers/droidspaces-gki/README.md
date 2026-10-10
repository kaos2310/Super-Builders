# BakaSU 35222 / DroidSpaces auf Samsung S928B ZZI4

Basis ist der erfolgreiche Build
[37831091198](https://github.com/kaos2310/Super-Builders/actions/runs/37831091198)
mit Builder-Commit `4619b3762a79ec464ae6bea30b4c8544293739d4`.
BakaSU wird für Kernel, ksud und ksuinit gemeinsam auf
`5b76b884c75f729a220bb317aa4a4fc78f0e0e9c` festgelegt:
30700 + 4522 = **35222**. UAPI5 und EVENT_SERVICES=4 bleiben erhalten.
SUSFS bleibt auf `24743360ea08d98f6ad72b856851abed8de5854f`,
ZeroMount auf `c3cb7ffdf749f2441928ec47798615a4c79fab65`.

`configure.py` bearbeitet jede angeforderte Option direkt in `gki_defconfig`
und entfernt übersteuernde Einträge aus dem später angewendeten Fragment.
Die bestehende Normalisierung mit dem echten Samsung-Kconfig-Baum bleibt aktiv.
Fehlende Kconfig-Symbole, fehlende SYSVIPC-Padding-Makros und abweichende Werte
in der finalen `.config` führen zum Abbruch.

Aktiviert werden IPC, PID/IPC/User-Namespaces, devtmpfs, addrtype, NAT66,
LOG/RECENT, IP-Sets und xt_set sowie tmpfs-ACL/xattr einschließlich ihrer
Kconfig-Abhängigkeiten. Linux 6.1 verwendet `IP_NF_TARGET_REJECT` und
`IP6_NF_TARGET_REJECT`; das in der Anleitung genannte
`NETFILTER_XT_TARGET_REJECT` existiert dort nicht. Die IPv6-NAT-Maskierung der
eingebetteten IKCONFIG entfällt, damit die gemeldete Fähigkeit dem Build entspricht.

Die Anleitung wurde bei
[`ac38c11f`](https://github.com/ravindu644/Droidspaces-OSS/blob/ac38c11fef1402c0db8172ea8187db0401a0bc30/Documentation/Kernel-Configuration.md#configuring-gki-kernels)
geprüft. Der bereits verwendete SYSVIPC-Patch für Reserveplätze 6/7/8 ist
bytegleich geblieben (Git-Blob `5fb2a9ee7c2ea7de781e023737d9acfecb639098`).
Die gepinnte Composite-Action wendet ihn weiterhin vor der Konfiguration an.
Für Linux 6.1 ist der zusätzliche POSIX-MQUEUE-Patch für 5.10 und älter nicht erforderlich.

## Ausdrücklich angeforderter Versuch mit CPU- und PID-Limits

Nach ausdrücklicher Nutzeranweisung aktiviert der neue Branch bei einem Push
`CONFIG_CFS_BANDWIDTH=y` und `CONFIG_CGROUP_PIDS=y`, zusammen mit
`CONFIG_CGROUP_SCHED=y` und `CONFIG_FAIR_GROUP_SCHED=y`.
Beim manuellen Start ist `resource_limits=true` voreingestellt.
`kmi_mode=strict` bleibt aktiv: Compiler, ABI-Symbollisten und die unveränderte
Samsung-Prüfung für 2485 Stock-Symbole dürfen echte ABI-Unterschiede ablehnen.
Es werden weder CRCs umgeschrieben noch `CONFIG_MODVERSIONS` deaktiviert.
Dieser Versuch erzeugt kein als Stock-kompatibel bezeichnetes AnyKernel-Paket.
Bei `resource_limits=false` bleibt der vorherige strikte Paketpfad verfügbar.

Ein vollständiger Geräte-Modulneubau ist **nicht implementiert und nicht belegt**.
Der vorhandene Quellstand enthält einen Samsung-Common-Kernel-Port und einen
gesonderten Gunyah-Modulprüfpfad. Er enthält keinen vollständigen Baugraphen
für alle 411 erfassten `vendor_boot`-Module und 351 `vendor_dlkm`-Module sowie
`system_dlkm`. Es fehlen die vollständige, zur Firmware passende externe
Modulquellen-Zuordnung und die Bau-/Signier-/Paketierungskette für die drei
Partitionen. Die Stock-Firmware-Hashes belegen keine neu gebauten Module.
Der Kernel-Versuch ersetzt diesen erforderlichen Geräte-Neubau nicht.

`BUILD-SCOPE.json`, angeforderte Defconfigs, vorhandene finale `.config`-Dateien,
`Module.symvers`, die gefundenen Moduldateien und das Kernel-Buildlog werden
auch nach einem fehlgeschlagenen Versuch als Diagnoseartefakt gesichert.
Moduldateien werden nur als gefundene Buildkandidaten gezählt.
Boot, Hardwaretreiber, Manager-Pairing, Containerstart, Firewall/NAT66 und die
tatsächliche Durchsetzung der Limits bleiben am Gerät ungeprüft.
