#!/bin/bash
set -e
set -a
source ./.env
set +a
read -p "Are you REALLY sure? (y/N) " -r reply
if [[ ! $reply =~ ^[Yy]$ ]];
then
    echo "Aborting."
    exit 1
fi

psql "$DATABASE_URL" < migrations/down.sql
psql "$DATABASE_URL" < migrations/up.sql