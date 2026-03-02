#!/bin/bash
# DeepCode New UI 一键启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_UI_DIR="$SCRIPT_DIR/new_ui"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "🚀 启动 DeepCode New UI..."
echo ""

# ============ 自动设置 Python 环境 ============
setup_python_env() {
    # 优先级: 已激活的 conda > 已激活的 venv > 本地 .venv > 本地 venv > 自动激活 conda deepcode

    if [ -n "$CONDA_PREFIX" ]; then
        echo -e "${GREEN}✓ 使用 conda 环境: $(basename $CONDA_PREFIX)${NC}"
        export PATH="$CONDA_PREFIX/bin:$PATH"
        return 0
    fi

    if [ -n "$VIRTUAL_ENV" ]; then
        echo -e "${GREEN}✓ 使用 virtualenv: $(basename $VIRTUAL_ENV)${NC}"
        export PATH="$VIRTUAL_ENV/bin:$PATH"
        return 0
    fi

    # 尝试自动激活本地虚拟环境
    if [ -d "$SCRIPT_DIR/.venv" ]; then
        echo -e "${YELLOW}⚡ 自动激活 .venv 环境${NC}"
        source "$SCRIPT_DIR/.venv/bin/activate"
        return 0
    fi

    if [ -d "$SCRIPT_DIR/venv" ]; then
        echo -e "${YELLOW}⚡ 自动激活 venv 环境${NC}"
        source "$SCRIPT_DIR/venv/bin/activate"
        return 0
    fi

    # 尝试自动激活 conda deepcode 环境
    if command -v conda &> /dev/null; then
        if conda env list 2>/dev/null | grep -q "deepcode"; then
            echo -e "${YELLOW}⚡ 自动激活 conda deepcode 环境${NC}"
            eval "$(conda shell.bash hook)"
            conda activate deepcode
            export PATH="$CONDA_PREFIX/bin:$PATH"
            return 0
        fi
    fi

    echo -e "${YELLOW}⚠ 未检测到虚拟环境，使用系统 Python${NC}"
    return 0
}

setup_python_env
echo -e "📍 Python: $(which python)"
echo ""
# ============================================

# 清理函数 - 使用进程组确保所有子进程都被终止
cleanup() {
    local exit_code="${1:-$?}"
    trap - SIGINT SIGTERM EXIT

    echo ""
    echo "🛑 正在关闭服务..."
    # 杀死后端进程及其子进程
    if [ -n "${BACKEND_PID:-}" ]; then
        kill -- -"$BACKEND_PID" 2>/dev/null || kill "$BACKEND_PID" 2>/dev/null || true
    fi
    # 杀死前端进程及其子进程
    if [ -n "${FRONTEND_PID:-}" ]; then
        kill -- -"$FRONTEND_PID" 2>/dev/null || kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    # 额外清理: 确保端口被释放
    pkill -f "uvicorn main:app.*--port 8000" 2>/dev/null || true
    pkill -f "vite.*5173" 2>/dev/null || true
    echo "✓ 所有服务已停止"
    exit "$exit_code"
}
trap 'cleanup 130' SIGINT
trap 'cleanup 143' SIGTERM
trap 'cleanup $?' EXIT

# 检查目录
if [ ! -d "$NEW_UI_DIR" ]; then
    echo "❌ 错误: new_ui 目录不存在"
    exit 1
fi

# 清理被占用的端口
cleanup_ports() {
    local port=$1
    local pid=$(lsof -ti :$port 2>/dev/null)
    if [ -n "$pid" ]; then
        echo -e "${YELLOW}⚠ 端口 $port 被占用 (PID: $pid)，正在清理...${NC}"
        kill -9 $pid 2>/dev/null || true
        sleep 1
        echo -e "${GREEN}✓ 端口 $port 已释放${NC}"
    fi
}

cleanup_ports 8000
cleanup_ports 5173

# 启动后端
echo -e "${BLUE}[1/2] 启动后端服务...${NC}"
cd "$NEW_UI_DIR/backend"

ensure_backend_deps() {
    if python -c "import fastapi, uvicorn, pydantic_settings, multipart, aiofiles, websockets, yaml" >/dev/null 2>&1; then
        return 0
    fi

    echo -e "${YELLOW}安装后端依赖...${NC}"
    python -m pip install fastapi uvicorn pydantic-settings python-multipart aiofiles websockets pyyaml -q
}

ensure_backend_deps

# 使用 setsid 创建新进程组（如果可用），否则直接后台运行
if command -v setsid &> /dev/null; then
    setsid python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
else
    python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
fi
BACKEND_PID=$!

wait_for_backend_health() {
    local health_url="http://127.0.0.1:8000/health"
    local max_retries=30
    local retry=1

    while [ $retry -le $max_retries ]; do
        if ! kill -0 $BACKEND_PID 2>/dev/null; then
            return 1
        fi

        if command -v curl &> /dev/null; then
            if curl -fsS "$health_url" >/dev/null 2>&1; then
                return 0
            fi
        else
            if python -c "import urllib.request; urllib.request.urlopen('$health_url', timeout=1)" >/dev/null 2>&1; then
                return 0
            fi
        fi

        sleep 1
        retry=$((retry + 1))
    done

    return 1
}

# 检查后端健康接口是否就绪
if wait_for_backend_health; then
    echo -e "${GREEN}✓ 后端已启动: http://localhost:8000${NC}"
else
    echo -e "${RED}✗ 后端启动失败或健康检查超时${NC}"
    echo -e "${YELLOW}  健康检查: http://localhost:8000/health${NC}"
    echo -e "${YELLOW}  尝试: lsof -i :8000 查看占用端口的进程${NC}"
    exit 1
fi

# 启动前端
echo -e "${BLUE}[2/2] 启动前端服务...${NC}"
cd "$NEW_UI_DIR/frontend"

if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}安装前端依赖 (首次运行)...${NC}"
    npm install
fi

# 使用 setsid 创建新进程组（如果可用）
if command -v setsid &> /dev/null; then
    setsid npm run dev &
else
    npm run dev &
fi
FRONTEND_PID=$!
sleep 3

echo ""
echo "╔════════════════════════════════════════╗"
echo -e "║  ${GREEN}DeepCode New UI 已启动!${NC}              ║"
echo "╠════════════════════════════════════════╣"
echo "║                                        ║"
echo "║  🌐 前端: http://localhost:5173        ║"
echo "║  🔧 后端: http://localhost:8000        ║"
echo "║  📚 API:  http://localhost:8000/docs   ║"
echo "║                                        ║"
echo "║  按 Ctrl+C 停止所有服务                ║"
echo "╚════════════════════════════════════════╝"
echo ""

wait
