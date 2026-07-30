#!/bin/bash
# ============================================================
#  AlphaSync — SSL Certificate Setup
#
#  NOTE: CloudPanel manages Nginx and SSL certificates.
#  This script is a reference only — SSL is configured via
#  the CloudPanel UI, not through Docker containers.
#
#  Steps to enable HTTPS via CloudPanel:
#    1. Log in to CloudPanel at https://YOUR_SERVER_IP:8443
#    2. Add site: www.alphasync.app (+ alphasync.app alias)
#    3. Set reverse proxy origin to 127.0.0.1:3000
#    4. Click "Issue Let's Encrypt Certificate"
#    5. Add a second reverse proxy rule for /api/* → 127.0.0.1:8000
#       and /ws/* → 127.0.0.1:8000 (WebSocket upgrade)
#
#  CloudPanel auto-renews certificates via cron.
# ============================================================
echo "=========================================="
echo "  AlphaSync — SSL Setup"
echo "=========================================="
echo ""
echo "  SSL is managed via CloudPanel, not this script."
echo "  See the comments in this file for setup instructions."
echo ""
