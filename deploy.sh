#!/bin/bash

# ==========================================
#  Yanci Bot v2.0 自动部署脚本 (MySQL版)
# ==========================================

# 定义颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
PLAIN='\033[0m'

# 检查 Root 权限
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}错误: 请使用 root 用户运行此脚本！${PLAIN}" 
   exit 1
fi

echo -e "${GREEN}======================================${PLAIN}"
echo -e "${GREEN}      开始部署 Yanci Bot v2.0      ${PLAIN}"
echo -e "${GREEN}======================================${PLAIN}"

# 0. 停止旧服务
echo -e "${YELLOW}[0/7] 检查并清理旧进程...${PLAIN}"
systemctl stop yanci_bot.service >/dev/null 2>&1
systemctl disable yanci_bot.service >/dev/null 2>&1

# 1. 基础配置与目录
WORK_DIR="/root/tg_bot"
ENV_FILE="$WORK_DIR/.env"
mkdir -p "$WORK_DIR"

# 2. 读取或生成配置
if [ -f "$ENV_FILE" ]; then
    echo -e "📂 检测到现有配置文件，正在读取..."
    export $(grep -v '^#' "$ENV_FILE" | xargs)
    INPUT_TOKEN=$TG_BOT_TOKEN
    INPUT_ADMIN_ID=$TG_ADMIN_ID
    DB_PASSWORD=$MYSQL_PASSWORD # 读取旧密码(如果有)
fi

if [[ -z "$INPUT_TOKEN" ]]; then
    read -p "请输入您的 Telegram Bot Token: " INPUT_TOKEN
fi

if [[ -z "$INPUT_ADMIN_ID" ]]; then
    read -p "请输入管理员 UID (数字ID): " INPUT_ADMIN_ID
fi

# 生成随机数据库密码 (如果不存在)
if [[ -z "$DB_PASSWORD" ]]; then
    DB_PASSWORD=$(date +%s%N | sha256sum | base64 | head -c 16)
fi

# 3. 安装系统依赖 (含 MySQL/MariaDB)
echo -e "${YELLOW}[3/7] 安装系统依赖与数据库...${PLAIN}"
apt-get update -y >/dev/null 2>&1
# 安装 Python, Git, MariaDB Server
apt-get install -y python3 python3-pip python3-venv python3-full libzbar0 git mariadb-server >/dev/null 2>&1

# 启动数据库
systemctl start mariadb
systemctl enable mariadb

# 4. 配置数据库
echo -e "${YELLOW}[4/7] 初始化 MySQL 数据库...${PLAIN}"
DB_NAME="tg_bot_db"
DB_USER="tg_bot_user"

# 使用 mysql 命令直接创建库和用户 (需要 root 权限)
# 如果数据库已存在则忽略错误
mysql -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" >/dev/null 2>&1
mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';" >/dev/null 2>&1
mysql -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';" >/dev/null 2>&1
mysql -e "FLUSH PRIVILEGES;" >/dev/null 2>&1

echo -e "✅ 数据库配置完成！用户: ${DB_USER}"

# 5. 更新代码
REPO_URL="https://github.com/2019xuanying/tgbot.git"
CURRENT_DIR=$(pwd)
echo -e "${YELLOW}[5/7] 同步程序文件...${PLAIN}"

# 这里简化逻辑：如果是本地开发环境直接复制，否则拉取
# 为了演示，假设我们总是从当前目录复制新的 v2 代码 (因为这是你刚才生成的)
# 实际生产中你可能还是用 git pull
if [ -f "main_bot.py" ]; then
    echo "📂 正在部署当前目录代码..."
    cp -rf ./* "$WORK_DIR/"
else
    echo "☁️ 正在从 GitHub 拉取 (请确保仓库已更新到 v2)..."
    # 如果仓库没更新，这里拉取的还是旧代码，请注意！
    # 此处仅作示例，建议手动上传这些新文件覆盖
    rm -rf "/tmp/tg_bot_temp"
    git clone "$REPO_URL" "/tmp/tg_bot_temp"
    cp -rf "/tmp/tg_bot_temp"/* "$WORK_DIR/"
fi

cd "$WORK_DIR"

# 6. 生成 .env
echo -e "${YELLOW}[6/7] 更新配置文件 (.env)...${PLAIN}"
cat > .env <<EOF
TG_BOT_TOKEN=${INPUT_TOKEN}
TG_ADMIN_ID=${INPUT_ADMIN_ID}
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=${DB_USER}
MYSQL_PASSWORD=${DB_PASSWORD}
MYSQL_DB=${DB_NAME}
EOF

# 7. Python 环境
echo -e "${YELLOW}[7/7] 安装 Python 依赖...${PLAIN}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# 确保 requirements.txt 包含 pymysql 和 sqlalchemy
cat > requirements.txt <<EOF
python-telegram-bot>=20.0
python-dotenv
requests
PySocks
schedule
pyzbar
Pillow
SQLAlchemy
pymysql
cryptography
EOF

./venv/bin/pip install --upgrade pip >/dev/null 2>&1
./venv/bin/pip install -r requirements.txt

# 8. 启动服务
echo -e "${YELLOW}启动 Systemd 服务...${PLAIN}"
SERVICE_FILE="/etc/systemd/system/yanci_bot.service"

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Telegram Bot Service (MySQL)
After=network.target mariadb.service

[Service]
Type=simple
User=root
WorkingDirectory=${WORK_DIR}
EnvironmentFile=${WORK_DIR}/.env
ExecStart=${WORK_DIR}/venv/bin/python3 ${WORK_DIR}/main_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable yanci_bot.service
systemctl restart yanci_bot.service

echo -e "${GREEN}======================================${PLAIN}"
echo -e "${GREEN}   🎉 部署成功 (v2.0 MySQL版)！${PLAIN}"
echo -e "   数据库名: ${DB_NAME}"
echo -e "   数据库密码: ${DB_PASSWORD} (已存入 .env)"
echo -e "${GREEN}======================================${PLAIN}"
