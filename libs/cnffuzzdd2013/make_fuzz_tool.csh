#!/bin/bash

for c in cnfuzz; do
	echo "g++ -O3 ${c}.c -o ${c}"
	g++ -O3 ${c}.c -o ${c}
	echo "DONE: g++ -O3 ${c}.c -o ${c}"
done
