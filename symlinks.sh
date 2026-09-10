#!/bin/bash

#dd if=/dev/zero of=traffic_0.bin bs=1G count=3 status=progress

# Source file
SRC="traffic_0.bin"

# Ensure the source file exists
if [ ! -f "$SRC" ]; then
    echo "Error: $SRC does not exist."
    exit 1
fi

# Create symlinks
for i in $(seq 1 15); do
    ln -sf "$SRC" "traffic_${i}.bin"
done

echo "Created:"
ls -l traffic_*.bin
