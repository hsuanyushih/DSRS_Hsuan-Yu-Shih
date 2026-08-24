#!/bin/bash
set -e

clear
echo "=========================================="
echo "  DSRS Curator — Cold Start Demo"
echo "=========================================="
echo ""
echo "Current output/ contents (before clearing):"
ls output/
echo ""
read -p "Press Enter to clear output/ and start the pipeline..."

echo ""
echo "=========================================="
echo "  STEP 1: Cold-start pipeline run"
echo "=========================================="
echo ""

rm -rf output/
python3 main.py --user-agent "Hsuan-Yu Shih hsuanyu5@illinois.edu"

echo ""
echo "=========================================="
echo "  Pipeline finished."
echo "=========================================="
read -p "Press Enter to run schema verification..."

echo ""
echo "=========================================="
echo "  STEP 2: Schema verification"
echo "=========================================="
echo ""

python3 verify.py

echo ""
echo "=========================================="
echo "  Verification complete."
echo "=========================================="
read -p "Press Enter to start the agent web demo..."

echo ""
echo "=========================================="
echo "  STEP 3: Starting web demo"
echo "  Open http://localhost:8765 in your browser"
echo "=========================================="
echo ""

python3 -m webui.server