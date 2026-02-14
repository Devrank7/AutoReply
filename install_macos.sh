#!/bin/bash
# AutoReply AI — macOS Installation
echo "Installing AutoReply AI for macOS..."

pip install -r requirements.txt
pip install pyobjc-core pyobjc-framework-ApplicationServices pyobjc-framework-Quartz

echo ""
echo "Done! To run:"
echo "  python app.py"
echo ""
echo "IMPORTANT: Grant these permissions in System Preferences → Privacy & Security:"
echo "  1. Accessibility — for global hotkey + keyboard simulation"
echo "  2. Screen Recording — for screenshot fallback"
