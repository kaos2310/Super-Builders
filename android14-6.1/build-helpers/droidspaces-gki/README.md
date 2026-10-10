# BakaSU 35222 / DroidSpaces auf Samsung S928B ZZI4

Basis ist der erfolgreiche Build
[37831091198](https://github.com/kaos2310/Super-Builders/actions/runs/37831091198)
mit Builder-Commit `4619b3762a79ec464ae6bea30b4c8544293739d4`.
BakaSU wird für Kernel, ksud und ksuinit gemeinsam auf
`5b76b884c75f729a220bb317aa4a4fc78f0e0e9c` festgelegt:
30700 + 4522 = **35222**. UAPI5 und EVENT_SERVICES=4 bleiben erhalten.
SUSFS bleibt auf `24743360ea08d98f6ad72b856851abed8de5854f`,
ZeroMount auf `c3cb7ffdf749f2441928ec47798615a4c79fab65`.

Die tatsächliche `final.config` aus dem erfolgreichen 35220-Run wurde am
10.10.2026 erneut heruntergeladen. Das Diagnose-ZIP stimmt mit GitHubs
SHA256 `dee78b2d369a4e3339404164b647a9484e60c8299a84833caf87658592156eda`
überein; die Konfigurationsdatei hat SHA256
`baec30ba6f5c76e72e5cae8fe299fe0a6a57034ae1ac73a4db6165b6d0db6d22`.
Von den GKI-DroidSpaces-Zielwerten ohne CPU-/PID-Limits fehlte tatsächlich nur
`CONFIG_NETFILTER_XT_MATCH_RECENT=y`. Die übrigen hier aufgeführten Optionen
waren schon aktiv. Der neue Build ergänzt RECENT und sichert die vorhandenen
Funktionen durch die wirksame Konfigurationsprüfung ab. Die Aufzählung unten
beschreibt den gesamten Zielumfang und behauptet nicht, alle Funktionen seien neu.

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

## Aktueller Build ohne CPU- und PID-Limits

Am 10.10.2026 hat der Nutzer erlaubt, CPU-/PID-Limits wegzulassen, wenn deren
Umsetzung zu aufwendig wird. Der vorherige Versuch
[38021970398](https://github.com/kaos2310/Super-Builders/actions/runs/38021970398)
kompilierte den Kernel, scheiterte aber an 797 von 2485 Stock-Symbol-CRCs.
Die breite ABI-Abweichung rechtfertigt den Wechsel auf den bestehenden
Stock-Modulpfad: Pushes und manuelle Standardstarts verwenden jetzt
`CONFIG_CFS_BANDWIDTH=n`, `CONFIG_CGROUP_PIDS=n` und `kmi_profile=full-strict`.
Speicherlimits über das bereits aktivierte `CONFIG_MEMCG=y` bleiben vorhanden.

Alle übrigen DroidSpaces-Anforderungen bleiben aktiv. Der neue Prüfer kontrolliert
zusätzlich die bereits vorhandenen Basisfunktionen: UTS-Namespace, procfs/sysfs,
Seccomp/Filter, cgroup-BPF, epoll/signalfd, PTY, Loop/ext4, FUSE/OverlayFS,
TUN/VETH/Bridge, IPv4-NAT und die bestehenden Routing-/Netfilter-Abhängigkeiten.
Diese Basiswerte werden nur in der wirksamen `.config` und der eingebetteten
IKCONFIG geprüft; sie werden nicht pauschal umkonfiguriert.

Die erneute Recherche verwendet die offizielle Anleitung und `src/check.c` bei
[`d1d7478d`](https://github.com/ravindu644/Droidspaces-OSS/tree/d1d7478d0abc777ab0cfc4e1d9a902769b8b132a).
Der aktuelle Laufzeitprüfer behandelt devtmpfs als optionale Hardware-Funktion
mit tmpfs-Fallback. Dieser Build aktiviert devtmpfs weiterhin. Für den modernen
cgroup-Pfad ist cgroup-BPF vorhanden; die ältere Non-GKI-Empfehlung
`CONFIG_CGROUP_DEVICE=y` wird nicht auf diesen GKI-Kernel übertragen.
Nftables und Bridge-Netfilter gehören nicht zum empfohlenen GKI-Konfigurationsblock;
der vorhandene iptables-NAT-Pfad bleibt die Grundlage.

`kmi_mode=strict`, die ABI-Symbollisten und die unveränderte Samsung-Prüfung für
2485 Stock-Symbole bleiben erforderlich. Es werden weder CRCs umgeschrieben
noch `CONFIG_MODVERSIONS` deaktiviert. Ein AnyKernel-Paket ist auf dem
Standardpfad erst nach allen erfolgreichen Prüfungen zulässig. Das ist kein
Nachweis eines erfolgreichen Geräteboots oder eines gestarteten Containers.

Der manuelle Parameter `resource_limits=true` bleibt als ausdrücklich gewählter
Diagnoseversuch verfügbar. Er verwendet weiterhin `resource-limits-strict`,
behält Stock-ABI-Prüfungen bei und darf kein Flashpaket erzeugen.

Ein vollständiger Geräte-Modulneubau ist **in diesem CI-Pfad nicht implementiert**.
Der veröffentlichte Quellstand enthält einen Samsung-Common-Kernel-Port und einen
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
