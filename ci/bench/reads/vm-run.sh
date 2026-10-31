#!/bin/bash
# A-leitura bench inside a Linux VM (pc-4c8g): PostgreSQL 17 in Docker, the branch's Historian,
# SDK and Analytics in a venv, the same datasets and scripts as the cloud run.
#   bash vm-run.sh            (~40 min; results in ~/a-leitura/results/*.jsonl)
set -euo pipefail
BRANCH=${BRANCH:-claude/project-thread-08h2no}
W=~/a-leitura; mkdir -p $W/results $W/var; cd $W
[ -d plantcraft ] || git clone -q --depth 1 -b "$BRANCH" https://github.com/PlantCraft/PlantCraft.git plantcraft
(cd plantcraft && git fetch -q --depth 1 origin "$BRANCH" && git checkout -q FETCH_HEAD)
sudo apt-get install -y -q python3-venv python3-dev build-essential >/dev/null
[ -d venv ] || python3 -m venv venv
. venv/bin/activate
pip install -q -U pip
grep -v "^ *--hash\|^#" plantcraft/apps/link/deploy/requirements.lock | grep "==" | sed 's/ *\\$//' > link-req.txt
pip install -q -r link-req.txt psycopg[binary] psycopg-pool uvicorn
pip install -q -e plantcraft/sdk/python -e plantcraft/apps/historian -e plantcraft/apps/link --no-deps
sudo docker rm -f a-pg >/dev/null 2>&1 || true
sudo docker run -d --name a-pg -p 127.0.0.1:55432:5432 -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=hist \
  postgres:17 -c shared_buffers=512MB -c effective_cache_size=1GB -c work_mem=16MB -c max_connections=100 -c max_wal_size=4GB >/dev/null
for i in $(seq 60); do sudo docker exec a-pg pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done; sleep 3
DB="postgresql://postgres@127.0.0.1:55432/hist"
KIT=$W/kit; rm -rf $KIT; cp -r plantcraft/ci/bench/reads $KIT; cd $KIT
sed -i "s#/home/user/bench#$W#g" *.py
python seed.py --db "$DB" --points 200 --days 2 --thin 10 --source demo200 | tail -1 | tee $W/results/seed.jsonl
python seed.py --db "$DB" --points 2000 --days 2 --thin 1 --source plant | tail -1 | tee -a $W/results/seed.jsonl
nohup python serve.py --db "$DB" > $W/serve.log 2>&1 & echo $! > $W/serve.pid
for i in $(seq 60); do curl -sf -H "Authorization: Bearer $(cat $W/token.txt 2>/dev/null)" http://127.0.0.1:8100/hist/api/v1/reads >/dev/null && break; sleep 1; done
export PYTHONWARNINGS=ignore
for src in demo200 plant; do
  python round.py --source $src --loops 50 --mode json --frame concat | tee -a $W/results/round.jsonl
  python round.py --source $src --loops 50 --mode binary --frame block | tee -a $W/results/round.jsonl
done
python scale.py --source demo200 --signals 200 --rounds 1 4 16 | grep '^{' | tee -a $W/results/scale.jsonl
python scale.py --source plant --signals 200 --rounds 1 4 8 | grep '^{' | tee -a $W/results/scale.jsonl
python scale.py --source plant --signals 2000 --rounds 1 | grep '^{' | tee -a $W/results/scale.jsonl
python incr.py --source plant --signals 150 --rounds 3 | tail -1 | tee -a $W/results/incr.jsonl
kill $(cat $W/serve.pid); echo "done: $W/results"
