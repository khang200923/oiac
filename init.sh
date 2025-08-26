#!/bin/bash
set -e
set -a
source ./.env
set +a
psql "$DATABASE_URL" < migrations/up.sql
mkdir -p log/
touch log/oiac.log