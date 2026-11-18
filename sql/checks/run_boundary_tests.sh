#!/bin/sh
# ---------------------------------------------------------------------
# Boundary tests for target reports 03, 08 and 09 (SYNTHETIC test data).
#
# For each report: build a throwaway IN-MEMORY database from schema.sql,
# load the tiny boundary_fixture.sql rows, run the report, and compare
# its output with the expected CSV in sql/checks/expected/.
# The real data/pharma_sales.db is never opened.
#
# Run from the project root:   sh sql/checks/run_boundary_tests.sh
# ---------------------------------------------------------------------

cd "$(dirname "$0")/../.." || exit 1
failures=0

for report in 03_region_target_achievement 08_annual_target_misses 09_largest_monthly_target_gaps; do
    # Header/CSV settings are sent INSIDE the input, after the setup SQL:
    # in testing (SQLite 3.54), "-header -csv" printed no header row for
    # this piped input, so the settings are applied explicitly here.
    # tr -d '\r': SQLite's CSV mode ends lines with \r\n; compare text only.
    actual=$({ cat sql/schema.sql sql/checks/boundary_fixture.sql
               printf '.headers on\n.mode csv\n'
               cat "sql/analysis/$report.sql"; } \
             | sqlite3 :memory: 2>&1 | tr -d '\r')
    expected=$(tr -d '\r' < "sql/checks/expected/$report.csv")

    if [ "$actual" = "$expected" ]; then
        echo "PASS  $report"
    else
        echo "FAIL  $report"
        echo "  expected:"; echo "$expected" | sed 's/^/    /'
        echo "  actual:";   echo "$actual"   | sed 's/^/    /'
        failures=$((failures + 1))
    fi
done

if [ "$failures" -eq 0 ]; then
    echo "RESULT: ALL BOUNDARY TESTS PASSED"
else
    echo "RESULT: $failures BOUNDARY TEST(S) FAILED"
    exit 1
fi
