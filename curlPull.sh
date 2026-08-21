#!/bin/bash

BASE_URL="https://[2001:48d0:3001:113::800]:1094"
NUM_FILES=16
FILE_SIZE_GB=3
DURATION=600      # 10 minutes

END_TIME=$((SECONDS + DURATION))
COUNT_FILE="/tmp/download_count.$$"
: > "$COUNT_FILE"

download_worker() {
    local id=$1
    local count=0

    while (( SECONDS < END_TIME )); do
        if curl --no-progress-meter -k -o /dev/null \
            "$BASE_URL/traffic_$id.bin"; then
            ((count++))
        fi
    done

    echo "$count" >> "$COUNT_FILE"
}

START=$(date +%s.%N)

for ((i=0; i<NUM_FILES; i++)); do
    download_worker "$i" &
done

wait

END=$(date +%s.%N)
ELAPSED=$(echo "$END - $START" | bc -l)

TOTAL_DOWNLOADS=$(awk '{s+=$1} END{print s}' "$COUNT_FILE")
rm -f "$COUNT_FILE"

TOTAL_GB=$(echo "$TOTAL_DOWNLOADS * $FILE_SIZE_GB" | bc)
GBPS=$(echo "scale=3; $TOTAL_GB / $ELAPSED" | bc -l)
MBPS=$(echo "scale=3; $TOTAL_GB * 1024 / $ELAPSED" | bc -l)
Gbps=$(echo "scale=3; $TOTAL_GB * 8 / $ELAPSED" | bc -l)

echo
echo "========== Results =========="
printf "Duration           : %.2f s\n" "$ELAPSED"
printf "Parallel downloads : %d\n" "$NUM_FILES"
printf "Completed files    : %d\n" "$TOTAL_DOWNLOADS"
printf "Data transferred   : %.0f GB\n" "$TOTAL_GB"
printf "Average speed      : %.3f GB/s\n" "$GBPS"
printf "                   : %.3f MB/s\n" "$MBPS"
printf "                   : %.3f Gbps\n" "$Gbps"
