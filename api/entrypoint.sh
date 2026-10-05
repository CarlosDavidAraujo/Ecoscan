#!/bin/sh
set -e

echo "=========================================================="
echo "==> EcoScan: Verificando e aplicando migrações Alembic..."
echo "=========================================================="

if [ -f "ecoscan/alembic.ini" ]; then
    alembic -c ecoscan/alembic.ini upgrade head || {
        echo "Aviso: Tentando novamente aplicar migrações no banco..."
        sleep 3
        alembic -c ecoscan/alembic.ini upgrade head
    }
    echo "==> Migrações aplicadas com sucesso no banco de dados!"
else
    echo "Aviso: ecoscan/alembic.ini não encontrado, pulando migrações."
fi

echo "=========================================================="
echo "==> EcoScan: Iniciando servidor FastAPI (Uvicorn)..."
echo "=========================================================="
exec uvicorn ecoscan.app:app --host 0.0.0.0 --port 8000
