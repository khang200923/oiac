#!/bin/bash
set -e
set -a
source ./.env
set +a
psql $DATABASE_URL < migrations/up.sql