#!/usr/bin/env bash
# macOS Finder에서 더블클릭으로 대시보드를 여는 래퍼.
# (start_dashboard.sh 를 같은 폴더에서 실행)
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
./start_dashboard.sh
echo ""
echo "이 창은 닫아도 됩니다. (서버는 백그라운드에서 계속 실행)"
