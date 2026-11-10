#!/usr/bin/env bash
# ==============================================================================
# 台灣運彩瘋狗流決策台 - Google Cloud (Ubuntu/Debian) 一鍵部署腳本
# ==============================================================================
set -e

echo "=== [0/4] 檢查並設定 Swap 虛擬記憶體 (避免 e2-micro 編譯時記憶體不足) ==="
if [ "$(swapon --show | wc -l)" -eq 0 ] && [ ! -f /swapfile ]; then
    echo "建立 2GB Swap 空間..."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "=== [1/4] 更新系統軟體包與安裝 Docker ==="
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release git

if ! command -v docker &> /dev/null; then
    echo "安裝 Docker..."
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker $USER
fi

echo "=== [2/4] 準備目錄與權限 ==="
mkdir -p data/cache data/snapshots data/logs config

echo "=== [2.5/4] 設定防火牆允許 8100 埠 (Oracle Cloud iptables 解鎖) ==="
if command -v iptables &> /dev/null; then
    sudo iptables -I INPUT -p tcp --dport 8100 -j ACCEPT || true
fi
if command -v ufw &> /dev/null; then
    sudo ufw allow 8100/tcp || true
fi

echo "=== [3/4] 建置並啟動服務容器 ==="
sudo docker compose down || true
sudo docker compose up -d --build

echo "=== [4/4] 檢查服務狀態 ==="
sleep 5
sudo docker compose ps

EXTERNAL_IP=$(curl -s https://api.ipify.org || echo "您的主機IP")

echo ""
echo "=============================================================================="
echo "🎉 部署完成！"
echo "請在瀏覽器輸入以下網址開啟決策台："
echo "  👉 http://${EXTERNAL_IP}:8100"
echo ""
echo "💡 提示："
echo "1. 請確保在 Google Cloud 虛擬機的「防火牆設定」中開啟 TCP port 8100。"
echo "2. 若要查看日誌：sudo docker compose logs -f"
echo "3. 若要重新啟動：sudo docker compose restart"
echo "=============================================================================="
