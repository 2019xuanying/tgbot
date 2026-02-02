#!/bin/bash

# ==========================================
#  自动部署脚本 (已修复更新逻辑)
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
echo -e "${GREEN}      开始部署 Yanci Bot      ${PLAIN}"
echo -e "${GREEN}======================================${PLAIN}"

# 0. 停止旧服务
echo -e "${YELLOW}[0/6] 检查并清理旧进程...${PLAIN}"
systemctl stop yanci_bot.service >/dev/null 2>&1
systemctl disable yanci_bot.service >/dev/null 2>&1

# 1. 获取配置信息 (如果 .env 存在则尝试自动读取，否则询问)
WORK_DIR="/root/tg_bot"
ENV_FILE="$WORK_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    echo -e "检测到现有配置文件，正在读取..."
    # 简单的读取逻辑，仅供参考，如果需要修改配置请手动编辑或删除 .env
    export $(grep -v '^#' "$ENV_FILE" | xargs)
    INPUT_TOKEN=$TG_BOT_TOKEN
    INPUT_ADMIN_ID=$TG_ADMIN_ID
fi

if [[ -z "$INPUT_TOKEN" ]]; then
    read -p "请输入您的 Telegram Bot Token: " INPUT_TOKEN
    while [[ -z "$INPUT_TOKEN" ]]; do
        echo -e "${RED}Token 不能为空！${PLAIN}"
        read -p "请输入您的 Telegram Bot Token: " INPUT_TOKEN
    done
fi

if [[ -z "$INPUT_ADMIN_ID" ]]; then
    read -p "请输入管理员 UID (数字ID): " INPUT_ADMIN_ID
    while [[ -z "$INPUT_ADMIN_ID" ]]; do
        echo -e "${RED}ID 不能为空！${PLAIN}"
        read -p "请输入管理员 UID: " INPUT_ADMIN_ID
    done
fi

# 2. 准备工作目录与代码
REPO_URL="https://github.com/2019xuanying/tgbot.git"
CURRENT_DIR=$(pwd)

echo -e "${YELLOW}[2/6] 同步程序文件...${PLAIN}"
mkdir -p "$WORK_DIR"

# ================= 核心修复逻辑 =================
# 只有当当前目录下有 main_bot.py 且 当前目录不是安装目录时，才认为是“本地上传部署”
# 否则一律视为“Git 拉取更新”
if [ -f "main_bot.py" ] && [ "$CURRENT_DIR" != "$WORK_DIR" ]; then
    # 情况A：用户手动上传了文件到其他目录（如 /root/upload/）
    echo -e "📂 检测到本地上传的文件，正在复制..."
    cp -rf "main_bot.py" "$WORK_DIR/"
    [ -d "utils" ] && cp -rf "utils" "$WORK_DIR/"
    [ -d "plugins" ] && cp -rf "plugins" "$WORK_DIR/"
    [ -f "requirements.txt" ] && cp -f "requirements.txt" "$WORK_DIR/"
else
    # 情况B：一键脚本或在安装目录内运行 -> 强制从 Git 拉取
    echo -e "☁️ 正在从 GitHub 拉取最新源码..."
    
    # 确保安装 git
    if ! command -v git &> /dev/null; then
        echo "安装 Git..."
        apt-get update -y >/dev/null 2>&1
        apt-get install -y git >/dev/null 2>&1
    fi

    # 克隆到临时目录
    TEMP_DIR="/tmp/tg_bot_temp"
    rm -rf "$TEMP_DIR"
    git clone "$REPO_URL" "$TEMP_DIR"
    
    if [ -f "$TEMP_DIR/main_bot.py" ]; then
        # 复制文件到工作目录 (保留用户数据 user_data.json)
        echo "正在更新文件..."
        cp -rf "$TEMP_DIR"/* "$WORK_DIR/"
        # 清理临时文件
        rm -rf "$TEMP_DIR"
        echo -e "✅ 代码更新成功！"
    else
        echo -e "${RED}❌ 代码拉取失败，请检查网络或仓库地址！${PLAIN}"
        exit 1
    fi
fi

cd "$WORK_DIR"

# 3. 生成/更新配置文件 (.env)
echo -e "${YELLOW}[3/6] 更新配置文件 (.env)...${PLAIN}"
cat > .env <<EOF
TG_BOT_TOKEN=${INPUT_TOKEN}
TG_ADMIN_ID=${INPUT_ADMIN_ID}
EOF

# 4. 检查依赖列表
echo -e "${YELLOW}[4/6] 检查依赖列表...${PLAIN}"
# 如果 requirements.txt 不存在或内容异常（比如是 HTML 错误页），则重建
if [ ! -f "requirements.txt" ] || grep -q "DOCTYPE" "requirements.txt"; then
    echo -e "${YELLOW}⚠️ 重建默认依赖列表...${PLAIN}"
    cat > requirements.txt <<EOF
python-telegram-bot>=20.0
python-dotenv
requests
PySocks
schedule
EOF
fi

# 5. 安装 Python 环境与依赖
echo -e "${YELLOW}[5/6] 安装环境依赖...${PLAIN}"
# 仅在第一次安装系统依赖，节省时间
if ! command -v python3 &> /dev/null; then
    apt-get update -y >/dev/null 2>&1
    # 注意这里追加了 libzbar0
    apt-get install -y python3 python3-pip python3-venv python3-full libzbar0 >/dev/null 2>&1
else
    # 即使 python 存在，也要确保安装 libzbar0
    apt-get install -y libzbar0 >/dev/null 2>&1
fi

# 创建或修复虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 使用虚拟环境的 pip 进行安装 (更稳健的方式)
echo "正在安装 Python 库..."
./venv/bin/pip install --upgrade pip >/dev/null 2>&1
./venv/bin/pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 依赖安装失败！${PLAIN}"
    exit 1
fi

# 6. 配置并启动 Systemd 服务
echo -e "${YELLOW}[6/6] 启动后台服务...${PLAIN}"
SERVICE_FILE="/etc/systemd/system/yanci_bot.service"

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Telegram Bot Service
After=network.target

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

# 最终检查
sleep 3
STATUS=$(systemctl is-active yanci_bot.service)

echo -e "${GREEN}======================================${PLAIN}"
if [ "$STATUS" = "active" ]; then
    echo -e "${GREEN}   🎉 部署成功！${PLAIN}"
    echo -e "   代码目录: ${WORK_DIR}"
    echo -e "   服务状态: 运行中 (Active)"
else
    echo -e "${RED}   ⚠️ 启动失败，请运行: journalctl -u yanci_bot.service -e -n 20 查看日志${PLAIN}"
fi
echo -e "${GREEN}======================================${PLAIN}"
