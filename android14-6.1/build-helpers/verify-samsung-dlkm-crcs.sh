#!/bin/bash
set -euo pipefail

KERNEL_ROOT="${1:?kernel root}"
BASELINE="${2:?Samsung DLKM CRC baseline}"
REPORT_DIR="${3:?report output directory}"
KMI_MODE="${4:-runtime-compat}"
KMI_PROFILE="${5:-full}"

case "$KMI_MODE" in
  runtime-compat|symtypes|strict) ;;
  *) echo "::error::Unsupported KMI audit mode: $KMI_MODE"; exit 1 ;;
esac

[[ -f "$BASELINE" ]] || {
  echo "::error::Samsung DLKM CRC baseline is missing: $BASELINE"
  exit 1
}
mkdir -p "$REPORT_DIR"

BASELINE_COUNT=$(awk '!/^#/ && NF >= 2 { count++ } END { print count + 0 }' "$BASELINE")
[[ "$BASELINE_COUNT" -gt 0 ]] || {
  echo "::error::Samsung DLKM CRC baseline contains no symbols"
  exit 1
}
BAD_BASELINE=$(awk '
  !/^#/ && (NF < 3 || $2 !~ /^0x[0-9a-fA-F]{8}$/ || $3 !~ /^0x[0-9a-fA-F]{8}$/) {
    print NR ":" $0
  }
' "$BASELINE")
[[ -z "$BAD_BASELINE" ]] || {
  echo "::error::Samsung DLKM CRC baseline has malformed entries"
  printf '%s\n' "$BAD_BASELINE"
  exit 1
}

BASELINE_CONFLICTS=$(awk '
  !/^#/ && NF >= 3 {
    pair=tolower($2) "/" tolower($3)
    if ($1 in seen && seen[$1] != pair)
      print $1 "\t" seen[$1] "\t" pair
    seen[$1]=pair
  }
' "$BASELINE")
[[ -z "$BASELINE_CONFLICTS" ]] || {
  echo "::error::Samsung DLKM CRC baseline contains conflicting duplicate symbols"
  printf '%s\n' "$BASELINE_CONFLICTS"
  exit 1
}

SYMVERS_CANDIDATES=(
  "$KERNEL_ROOT/out/android14-6.1/dist/Module.symvers"
  "$KERNEL_ROOT/bazel-bin/common/kernel_aarch64/Module.symvers"
  "$KERNEL_ROOT/bazel-bin/common/kernel_aarch64_dist/Module.symvers"
)
while IFS= read -r candidate; do
  SYMVERS_CANDIDATES+=("$candidate")
done < <(find -L "$KERNEL_ROOT/bazel-bin/common" "$KERNEL_ROOT/out/android14-6.1" \
  -type f -name Module.symvers -print 2>/dev/null || true)

SYMVERS=""
BEST_COVERAGE=0
declare -A SEEN_CANDIDATES=()
for candidate in "${SYMVERS_CANDIDATES[@]}"; do
  [[ -s "$candidate" ]] || continue
  resolved=$(realpath "$candidate")
  [[ -z "${SEEN_CANDIDATES[$resolved]:-}" ]] || continue
  SEEN_CANDIDATES[$resolved]=1
  coverage=$(awk '
    NR == FNR {
      if ($0 !~ /^#/ && NF >= 2)
        expected[$1]=1
      next
    }
    NF >= 2 && ($2 in expected) { matched[$2]=1 }
    END { print length(matched) + 0 }
  ' "$BASELINE" "$candidate")
  if (( coverage > BEST_COVERAGE )); then
    BEST_COVERAGE=$coverage
    SYMVERS="$resolved"
  fi
done

[[ -n "$SYMVERS" ]] || {
  echo "::error::No Module.symvers overlaps the Samsung DLKM CRC baseline"
  exit 1
}

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

awk -v exact="$TMP_DIR/exact" \
    -v compatible="$TMP_DIR/compatible" \
    -v unexpected="$TMP_DIR/unexpected" \
    -v missing="$TMP_DIR/missing" '
  NR == FNR {
    if ($0 !~ /^#/ && NF >= 3) {
      expected_device[$1]=tolower($2)
      expected_build[$1]=tolower($3)
      consumers[$1]=$4
    }
    next
  }
  NF >= 2 {
    symbol=$2
    crc=tolower($1)
    if (symbol in expected_device)
      actual[symbol]=crc
  }
  END {
    for (symbol in expected_device) {
      if (!(symbol in actual))
        print symbol "\t" expected_device[symbol] "\t" expected_build[symbol] "\t" consumers[symbol] > missing
      else if (actual[symbol] == expected_device[symbol])
        print symbol "\t" expected_device[symbol] "\t" consumers[symbol] > exact
      else if (actual[symbol] == expected_build[symbol])
        print symbol "\t" expected_device[symbol] "\t" expected_build[symbol] "\t" consumers[symbol] > compatible
      else
        print symbol "\t" expected_device[symbol] "\t" expected_build[symbol] "\t" actual[symbol] "\t" consumers[symbol] > unexpected
    }
  }
' "$BASELINE" "$SYMVERS"

{
  printf 'symbol\tcrc\tmodules\n'
  [[ ! -s "$TMP_DIR/exact" ]] || LC_ALL=C sort "$TMP_DIR/exact"
} > "$REPORT_DIR/exact.tsv"
{
  printf 'symbol\tdevice_crc\tvalidated_build_crc\tmodules\n'
  [[ ! -s "$TMP_DIR/compatible" ]] || LC_ALL=C sort "$TMP_DIR/compatible"
} > "$REPORT_DIR/compatible-differences.tsv"
{
  printf 'symbol\tdevice_crc\tvalidated_build_crc\tactual_build_crc\tmodules\n'
  [[ ! -s "$TMP_DIR/unexpected" ]] || LC_ALL=C sort "$TMP_DIR/unexpected"
} > "$REPORT_DIR/unexpected.tsv"
{
  printf 'symbol\tdevice_crc\tvalidated_build_crc\tmodules\n'
  [[ ! -s "$TMP_DIR/missing" ]] || LC_ALL=C sort "$TMP_DIR/missing"
} > "$REPORT_DIR/missing.tsv"

EXACT_COUNT=$(( $(wc -l < "$REPORT_DIR/exact.tsv") - 1 ))
COMPATIBLE_COUNT=$(( $(wc -l < "$REPORT_DIR/compatible-differences.tsv") - 1 ))
UNEXPECTED_COUNT=$(( $(wc -l < "$REPORT_DIR/unexpected.tsv") - 1 ))
MISSING_COUNT=$(( $(wc -l < "$REPORT_DIR/missing.tsv") - 1 ))
SYMVERS_SHA256=$(sha256sum "$SYMVERS" | awk '{print $1}')
cp "$SYMVERS" "$REPORT_DIR/Module.symvers"

RUNTIME_FALLBACK="unavailable"
VERSION_SOURCE=""
for candidate in \
  "$KERNEL_ROOT/common/kernel/module/version.c" \
  "$KERNEL_ROOT/common/kernel/module.c"; do
  [[ -f "$candidate" ]] || continue
  VERSION_SOURCE="$candidate"
  break
done
[[ -n "$VERSION_SOURCE" ]] || {
  echo "::error::Kernel module version source was not found"
  exit 1
}
BAD_VERSION_RETURN=$(awk '
  /^[[:space:]]*bad_version:/ { in_bad_version=1; next }
  in_bad_version && /return[[:space:]]+[01];/ { print; exit }
' "$VERSION_SOURCE")
if grep -qE 'return[[:space:]]+1;' <<< "$BAD_VERSION_RETURN"; then
  RUNTIME_FALLBACK="accept-mismatch"
elif grep -qE 'return[[:space:]]+0;' <<< "$BAD_VERSION_RETURN"; then
  RUNTIME_FALLBACK="strict-rejection"
else
  RUNTIME_FALLBACK="unknown"
fi

cat > "$REPORT_DIR/summary.env" <<EOF
KMI_PROFILE=$KMI_PROFILE
KMI_MODE=$KMI_MODE
BASELINE_COUNT=$BASELINE_COUNT
EXACT_COUNT=$EXACT_COUNT
REFERENCE_COUNT=$COMPATIBLE_COUNT
VARIANT_COUNT=$UNEXPECTED_COUNT
MISSING_COUNT=$MISSING_COUNT
RUNTIME_FALLBACK=$RUNTIME_FALLBACK
SYMVERS_SHA256=$SYMVERS_SHA256
EOF

cat > "$REPORT_DIR/summary.md" <<EOF
# Samsung S928B DLKM CRC audit

- KMI profile: **${KMI_PROFILE}**
- KMI audit mode: **${KMI_MODE}**
- Baseline symbols: **${BASELINE_COUNT}**
- Exact Samsung/build CRC matches: **${EXACT_COUNT}**
- Current full-build reference CRC matches: **${COMPATIBLE_COUNT}**
- Variant-specific CRCs: **${UNEXPECTED_COUNT}**
- Baseline symbols absent from selected Module.symvers: **${MISSING_COUNT}**
- Module-loader CRC policy: **${RUNTIME_FALLBACK}**
- Module.symvers: \`${SYMVERS#"$KERNEL_ROOT"/}\`
- Module.symvers SHA-256: \`${SYMVERS_SHA256}\`
EOF

cat "$REPORT_DIR/summary.md"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat "$REPORT_DIR/summary.md" >> "$GITHUB_STEP_SUMMARY"
fi
if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    echo "SAMSUNG_DLKM_BASELINE_COUNT=$BASELINE_COUNT"
    echo "SAMSUNG_DLKM_EXACT_COUNT=$EXACT_COUNT"
    echo "SAMSUNG_DLKM_COMPATIBLE_COUNT=$COMPATIBLE_COUNT"
    echo "SAMSUNG_DLKM_UNEXPECTED_COUNT=$UNEXPECTED_COUNT"
    echo "SAMSUNG_DLKM_MISSING_COUNT=$MISSING_COUNT"
    echo "SAMSUNG_DLKM_RUNTIME_FALLBACK=$RUNTIME_FALLBACK"
    echo "SAMSUNG_DLKM_SYMVERS_SHA256=$SYMVERS_SHA256"
  } >> "$GITHUB_ENV"
fi

if (( EXACT_COUNT + COMPATIBLE_COUNT + UNEXPECTED_COUNT + MISSING_COUNT != BASELINE_COUNT )); then
  echo "::error::Samsung DLKM CRC coverage is incomplete"
  exit 1
fi

case "$KMI_MODE" in
  runtime-compat)
    if (( UNEXPECTED_COUNT > 0 )); then
      echo "::error::Unexpected Samsung DLKM build CRCs detected: $UNEXPECTED_COUNT"
      sed -n '1,31p' "$REPORT_DIR/unexpected.tsv"
      exit 1
    fi
    if (( MISSING_COUNT > 0 )); then
      echo "::error::Samsung DLKM baseline symbols are missing from Module.symvers: $MISSING_COUNT"
      sed -n '1,31p' "$REPORT_DIR/missing.tsv"
      exit 1
    fi
    if (( COMPATIBLE_COUNT > 0 )) && [[ "$RUNTIME_FALLBACK" != "accept-mismatch" ]]; then
      echo "::error::Reference CRC differences require the audited bad_version fallback"
      exit 1
    fi
    ;;
  symtypes)
    [[ "$RUNTIME_FALLBACK" == "strict-rejection" ]] || {
      echo "::error::Symtypes diagnostics must retain strict runtime CRC rejection"
      exit 1
    }
    ;;
  strict)
    [[ "$RUNTIME_FALLBACK" == "strict-rejection" ]] || {
      echo "::error::Strict KMI mode does not reject CRC mismatches"
      exit 1
    }
    if (( COMPATIBLE_COUNT + UNEXPECTED_COUNT + MISSING_COUNT > 0 )); then
      echo "::error::Strict Samsung DLKM KMI gate failed: exact=$EXACT_COUNT reference=$COMPATIBLE_COUNT variant=$UNEXPECTED_COUNT missing=$MISSING_COUNT"
      exit 1
    fi
    ;;
esac

echo "Audited $EXACT_COUNT exact Samsung CRCs, $COMPATIBLE_COUNT reference CRCs, $UNEXPECTED_COUNT variant CRCs and $MISSING_COUNT missing symbols"
