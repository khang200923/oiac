#!/bin/bash
set -e
set -a
source ./.env
set +a
mkdir -p log/
touch log/oiac.log
psql "$DATABASE_URL" < migrations/up.sql