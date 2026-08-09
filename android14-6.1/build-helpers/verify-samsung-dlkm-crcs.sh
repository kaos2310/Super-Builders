#!/bin/bash
set -euo pipefail

KERNEL_ROOT="${1:?kernel root}"
BASELINE="${2:?Samsung DLKM CRC baseline}"
REPORT_DIR="${3:?report output directory}"
MIN_MATCHED="${SAMSUNG_DLKM_MIN_MATCHED:-}"

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
MIN_MATCHED="${MIN_MATCHED:-$BASELINE_COUNT}"
[[ "$MIN_MATCHED" =~ ^[0-9]+$ ]] && (( MIN_MATCHED <= BASELINE_COUNT )) || {
  echo "::error::Invalid Samsung DLKM minimum coverage: $MIN_MATCHED"
  exit 1
}

BAD_BASELINE=$(awk '
  !/^#/ && (NF < 2 || $2 !~ /^0x[0-9a-fA-F]{8}$/) { print NR ":" $0 }
' "$BASELINE")
[[ -z "$BAD_BASELINE" ]] || {
  echo "::error::Samsung DLKM CRC baseline has malformed entries"
  printf '%s\n' "$BAD_BASELINE"
  exit 1
}

BASELINE_CONFLICTS=$(awk '
  !/^#/ && NF >= 2 {
    crc=tolower($2)
    if ($1 in seen && seen[$1] != crc)
      print $1 "\t" seen[$1] "\t" crc
    seen[$1]=crc
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

awk -v matched="$TMP_DIR/matched" \
    -v mismatched="$TMP_DIR/mismatched" \
    -v missing="$TMP_DIR/missing" '
  NR == FNR {
    if ($0 !~ /^#/ && NF >= 2) {
      expected[$1]=tolower($2)
      consumers[$1]=$3
    }
    next
  }
  NF >= 2 {
    symbol=$2
    crc=tolower($1)
    if (symbol in expected)
      actual[symbol]=crc
  }
  END {
    for (symbol in expected) {
      if (!(symbol in actual))
        print symbol "\t" expected[symbol] "\t" consumers[symbol] > missing
      else if (actual[symbol] != expected[symbol])
        print symbol "\t" expected[symbol] "\t" actual[symbol] "\t" consumers[symbol] > mismatched
      else
        print symbol "\t" expected[symbol] "\t" consumers[symbol] > matched
    }
  }
' "$BASELINE" "$SYMVERS"

{
  printf 'symbol\tcrc\tmodules\n'
  [[ ! -s "$TMP_DIR/matched" ]] || LC_ALL=C sort "$TMP_DIR/matched"
} > "$REPORT_DIR/matched.tsv"
{
  printf 'symbol\texpected_crc\tbuild_crc\tmodules\n'
  [[ ! -s "$TMP_DIR/mismatched" ]] || LC_ALL=C sort "$TMP_DIR/mismatched"
} > "$REPORT_DIR/mismatched.tsv"
{
  printf 'symbol\texpected_crc\tmodules\n'
  [[ ! -s "$TMP_DIR/missing" ]] || LC_ALL=C sort "$TMP_DIR/missing"
} > "$REPORT_DIR/missing.tsv"

MATCHED_COUNT=$(( $(wc -l < "$REPORT_DIR/matched.tsv") - 1 ))
MISMATCH_COUNT=$(( $(wc -l < "$REPORT_DIR/mismatched.tsv") - 1 ))
MISSING_COUNT=$(( $(wc -l < "$REPORT_DIR/missing.tsv") - 1 ))
SYMVERS_SHA256=$(sha256sum "$SYMVERS" | awk '{print $1}')

cat > "$REPORT_DIR/summary.md" <<EOF
# Samsung S928B DLKM CRC audit

- Baseline symbols: **${BASELINE_COUNT}**
- Exact CRC matches: **${MATCHED_COUNT}**
- CRC mismatches: **${MISMATCH_COUNT}**
- Baseline symbols absent from selected Module.symvers: **${MISSING_COUNT}**
- Required minimum matches: **${MIN_MATCHED}**
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
    echo "SAMSUNG_DLKM_MATCHED_COUNT=$MATCHED_COUNT"
    echo "SAMSUNG_DLKM_MISMATCH_COUNT=$MISMATCH_COUNT"
    echo "SAMSUNG_DLKM_MISSING_COUNT=$MISSING_COUNT"
    echo "SAMSUNG_DLKM_SYMVERS_SHA256=$SYMVERS_SHA256"
  } >> "$GITHUB_ENV"
fi

if (( MISMATCH_COUNT > 0 )); then
  echo "::error::Samsung DLKM CRC mismatches detected: $MISMATCH_COUNT"
  sed -n '1,31p' "$REPORT_DIR/mismatched.tsv"
  exit 1
fi
if (( MATCHED_COUNT < MIN_MATCHED )); then
  echo "::error::Samsung DLKM CRC coverage is too low: $MATCHED_COUNT < $MIN_MATCHED"
  exit 1
fi

echo "Verified $MATCHED_COUNT Samsung S928B DLKM symbol CRCs with no mismatch"
